"""Render animasi/kartun dengan Remotion (https://www.remotion.dev) dari storyboard + gaya animasi.

Python menyiapkan bahan (gambar tiap adegan, waktu kata, potongan audio), lalu memanggil
`node remotion/render.mjs` yang merender komposisi React "CartoonStory".
Lisensi Remotion: gratis untuk perorangan dan perusahaan dengan maksimal 3 karyawan.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import cv2

from .config import PROJECT_DIR
from .creative import CAMERAS, TRANSITIONS, ClipContext, best_frame, clean_clip, face_box, save_plan
from .gemini import QuotaError
from .imagegen import ImageGen
from .stylize import STYLES, stylize_image
from .transcript import Word
from .translate import translate_clip_words
from .utils import Cancelled, ClipAgentError, check_cancel, log, probe, progress, slugify

REMOTION_DIR = PROJECT_DIR / "remotion"
FONTS = ["Anton", "Bangers", "Bebas Neue", "Montserrat Black", "Patrick Hand", "Poppins"]

# ---------------------------------------------------------------- preset gaya
PRESETS = {
    "komik": {
        "name": "Komik klasik", "desc": "Panel bergaris tebal, latar titik halftone, balon kata, dan efek suara.",
        "media": "kartun", "cartoon": "komik", "ai_prompt": "", "transition": "slide",
        "style": {"bg": "#FFF4D6", "bg2": "#F2C14E", "accent": "#FFD400", "ink": "#111111", "text": "#FFFFFF",
                  "font": "Bangers", "captionFont": "Bangers", "frame": "panel", "captions": "bubble",
                  "texture": "halftone", "motion": "smooth", "sfx": True, "videoFilter": "none",
                  "uppercase": True, "transitionSec": 0.35},
    },
    "anime": {
        "name": "Anime cerah", "desc": "Gambar penuh layar bergaya anime, garis kecepatan, caption karaoke.",
        "media": "kartun", "cartoon": "anime", "ai_prompt": "", "transition": "wipe",
        "style": {"bg": "#1B1440", "bg2": "#2A2160", "accent": "#FF4FA3", "ink": "#140E2E", "text": "#FFFFFF",
                  "font": "Montserrat Black", "captionFont": "Montserrat Black", "frame": "full",
                  "captions": "karaoke", "texture": "speedlines", "motion": "smooth", "sfx": False,
                  "videoFilter": "none", "uppercase": True, "transitionSec": 0.3},
    },
    "kertas": {
        "name": "Stop-motion kertas", "desc": "Potongan kertas sobek di atas karton, gerak patah-patah 12 fps.",
        "media": "kartun", "cartoon": "catair", "ai_prompt": "", "transition": "fade",
        "style": {"bg": "#C9A27A", "bg2": "#E9D9C0", "accent": "#E4572E", "ink": "#2B2118", "text": "#FFFDF6",
                  "font": "Patrick Hand", "captionFont": "Patrick Hand", "frame": "paper", "captions": "karaoke",
                  "texture": "paper", "motion": "stop", "sfx": False, "videoFilter": "none",
                  "uppercase": False, "transitionSec": 0.3},
    },
    "explainer": {
        "name": "Explainer bersih", "desc": "Foto dalam kartu, judul besar per poin, satu kata besar sebagai caption.",
        "media": "asli", "cartoon": "anime", "ai_prompt": "", "transition": "slide",
        "style": {"bg": "#0F3D3E", "bg2": "#145A5B", "accent": "#F6C445", "ink": "#082425", "text": "#FFFFFF",
                  "font": "Anton", "captionFont": "Montserrat Black", "frame": "card", "captions": "pop",
                  "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none",
                  "uppercase": True, "transitionSec": 0.35},
    },
    "video_kartun": {
        "name": "Video kartun bergerak", "desc": "Video asli tetap bergerak dengan warna poster seperti kartun.",
        "media": "video", "cartoon": "poster", "ai_prompt": "", "transition": "fade",
        "style": {"bg": "#111111", "bg2": "#222222", "accent": "#FFE24A", "ink": "#000000", "text": "#FFFFFF",
                  "font": "Anton", "captionFont": "Montserrat Black", "frame": "full", "captions": "karaoke",
                  "texture": "grain", "motion": "smooth", "sfx": False, "videoFilter": "posterize",
                  "uppercase": True, "transitionSec": 0.25},
    },
    "faceless": {
        "name": "Faceless layar penuh", "desc": "Visual penuh layar, judul kuning tegas, caption karaoke besar. Cocok untuk channel faceless.",
        "media": "kartun", "cartoon": "anime", "ai_prompt": "", "transition": "fade",
        "style": {"bg": "#0B0B12", "bg2": "#1A1A28", "accent": "#FFD400", "ink": "#000000", "text": "#FFFFFF",
                  "font": "Anton", "captionFont": "Montserrat Black", "frame": "full", "captions": "karaoke",
                  "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none",
                  "uppercase": True, "transitionSec": 0.25},
    },
    "ilustrasi_ai": {
        "name": "Ilustrasi AI", "desc": "Setiap adegan digambar ulang oleh AI (Gemini). Butuh API key, bisa berbayar.",
        "media": "ai", "cartoon": "anime",
        "ai_prompt": "a clean modern 2D animated-series illustration with soft cel shading and warm light",
        "transition": "iris",
        "style": {"bg": "#0E1726", "bg2": "#1C2A44", "accent": "#4FD1FF", "ink": "#07101C", "text": "#FFFFFF",
                  "font": "Montserrat Black", "captionFont": "Montserrat Black", "frame": "full",
                  "captions": "karaoke", "texture": "none", "motion": "smooth", "sfx": False,
                  "videoFilter": "none", "uppercase": True, "transitionSec": 0.35},
    },
}

OPTIONS = {
    "media": {"kartun": "Gambar kartun (lokal, gratis)", "ai": "Gambar AI (Gemini)", "asli": "Foto dari video",
              "video": "Video bergerak"},
    "cartoon": {k: v[0] for k, v in STYLES.items()},
    "frame": {"full": "Layar penuh", "panel": "Panel komik", "card": "Kartu", "paper": "Potongan kertas"},
    "captions": {"karaoke": "Karaoke (kata aktif berwarna)", "pop": "Satu kata besar", "bubble": "Balon kata",
                 "none": "Tanpa caption"},
    "texture": {"none": "Tanpa", "halftone": "Titik halftone", "paper": "Kertas", "grain": "Grain film",
                "speedlines": "Garis kecepatan"},
    "motion": {"smooth": "Halus", "stop": "Stop-motion (patah-patah)"},
    "videoFilter": {"none": "Tanpa", "posterize": "Warna poster"},
    "fonts": FONTS,
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def resolve_style(opts: dict) -> dict:
    """Gabungkan preset terpilih dengan isian gaya kustom pengguna (divalidasi)."""
    pid = opts.get("preset") if opts.get("preset") in PRESETS else "komik"
    base = json.loads(json.dumps(PRESETS[pid]))
    cust = opts.get("custom") if isinstance(opts.get("custom"), dict) else {}
    out = {"id": pid if not cust else "kustom", "name": str(cust.get("name") or base["name"])[:40],
           "media": cust.get("media") if cust.get("media") in OPTIONS["media"] else base["media"],
           "cartoon": cust.get("cartoon") if cust.get("cartoon") in STYLES else base["cartoon"],
           "ai_prompt": str(cust.get("ai_prompt") if "ai_prompt" in cust else base["ai_prompt"])[:400],
           "transition": base["transition"]}
    st = base["style"]
    for k in ("bg", "bg2", "accent", "ink", "text"):
        if _HEX.match(str(cust.get(k, ""))):
            st[k] = cust[k]
    for k in ("font", "captionFont"):
        if cust.get(k) in FONTS:
            st[k] = cust[k]
    for k, choices in (("frame", "frame"), ("captions", "captions"), ("texture", "texture"),
                       ("motion", "motion"), ("videoFilter", "videoFilter")):
        if cust.get(k) in OPTIONS[choices]:
            st[k] = cust[k]
    for k in ("sfx", "uppercase"):
        if isinstance(cust.get(k), bool):
            st[k] = cust[k]
    try:
        st["transitionSec"] = min(1.0, max(0.1, float(cust.get("transitionSec", st["transitionSec"]))))
    except (TypeError, ValueError):
        pass
    st["name"] = out["name"]
    out["style"] = st
    return out


# ---------------------------------------------------------------- Remotion
def remotion_status() -> dict:
    node = shutil.which("node")
    installed = (REMOTION_DIR / "node_modules" / "remotion").is_dir()
    hint = ""
    if not node:
        hint = "Node.js belum terpasang. Windows: winget install OpenJS.NodeJS.LTS, lalu jalankan ulang start.bat."
    elif not installed:
        hint = "Paket Remotion belum terpasang. Jalankan ulang start.bat, atau: cd remotion && npm install"
    return {"node": bool(node), "installed": installed, "ready": bool(node) and installed, "hint": hint}


def _run_remotion(job: dict, p0: float, p1: float, stage: str) -> None:
    st = remotion_status()
    if not st["ready"]:
        raise ClipAgentError(st["hint"])
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(job, fh)
        job_path = fh.name
    err_file = tempfile.TemporaryFile()
    proc = subprocess.Popen([shutil.which("node"), "render.mjs", job_path], cwd=str(REMOTION_DIR),
                            stdout=subprocess.PIPE, stderr=err_file, text=True, encoding="utf-8", errors="replace")
    try:
        for line in proc.stdout:
            key, _, val = line.strip().partition(" ")
            if key == "PROGRESS":
                progress(p0 + (p1 - p0) * float(val or 0), stage)
            elif key == "BUNDLE":
                progress(p0, "Menyiapkan Remotion (sekali saja)")
            elif key == "STAGE":
                log(f"  Remotion: {val}")
            try:
                check_cancel()
            except Cancelled:
                _kill_tree(proc)
                raise
        proc.wait()
        if proc.returncode != 0:
            err_file.seek(0)
            tail = "\n".join(err_file.read().decode("utf-8", "replace").strip().splitlines()[-12:])
            raise ClipAgentError(f"Remotion gagal merender:\n{tail}")
    finally:
        try:
            os.unlink(job_path)
        except OSError:
            pass


def _kill_tree(proc: subprocess.Popen) -> None:
    """Hentikan Node beserta browser yang dibukanya (di Windows proses anak tidak ikut mati)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    proc.kill()
    proc.wait()


class _AssetServer:
    """Server file sementara (127.0.0.1) agar Remotion bisa memuat gambar, video, dan audio."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        handler = functools.partial(_QuietHandler, directory=str(self.root))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: Path) -> str:
        return f"{self.base}/{quote(path.resolve().relative_to(self.root).as_posix())}"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


# ---------------------------------------------------------------- bahan adegan
def normalize_scenes(scenes: list, duration: float) -> list[dict]:
    out = []
    for raw in scenes or []:
        if not isinstance(raw, dict):
            continue
        try:
            s = max(0.0, min(duration, float(raw.get("start", 0))))
            e = max(0.0, min(duration, float(raw.get("end", 0))))
        except (TypeError, ValueError):
            continue
        if raw.get("include") is False or e - s < 0.5:
            continue
        sc = {"start": round(s, 3), "end": round(e, 3)}
        for k in ("heading", "bubble", "sfx", "prompt", "title"):
            sc[k] = str(raw.get(k) or "").strip()[:200]
        sc["camera"] = raw.get("camera") if raw.get("camera") in CAMERAS else "zoom_in"
        sc["transition"] = raw.get("transition") if raw.get("transition") in TRANSITIONS else "fade"
        out.append(sc)
    out.sort(key=lambda x: x["start"])
    cleaned: list[dict] = []
    for sc in out:                                   # hapus tumpang tindih
        if cleaned and sc["start"] < cleaned[-1]["end"]:
            sc["start"] = cleaned[-1]["end"]
        if sc["end"] - sc["start"] >= 0.5:
            cleaned.append(sc)
    if not cleaned:
        raise ClipAgentError("Storyboard kosong. Tambahkan minimal satu adegan (minimal 0,5 detik).")
    return cleaned


def _remap(words: list[Word], clip_start: float, scenes: list[dict]) -> list[dict]:
    out, off = [], 0.0
    for sc in scenes:
        s, e = sc["start"], sc["end"]
        for w in words:
            ws, we = w.start - clip_start, w.end - clip_start
            if s <= (ws + we) / 2 < e:
                out.append({"s": round(max(0.0, ws - s) + off, 3), "e": round(min(e, we) - s + off, 3), "t": w.text})
        off += e - s
    return out


def _subtitle_words(ctx: ClipContext, opts: dict, scenes: list[dict]) -> list[dict]:
    words = [w for w in ctx.words if w.end > ctx.start and w.start < ctx.end]
    if opts.get("subtitles") is False:
        return []
    try:
        cfg = ctx.settings(**{k: opts[k] for k in ("sub_lang",) if k in opts})
        target = cfg.sub_lang if cfg.sub_lang not in ("", "auto") else ""
        if target and words and target != (ctx.tlang or ""):
            progress(0.06, "Menerjemahkan subtitle")
            tr = translate_clip_words(cfg, ctx.words, [(ctx.start, ctx.end)], target,
                                      ctx.workdir / f"translations_{target}.json")
            words = tr.get(0, words)
    except (ClipAgentError, ValueError) as exc:
        log(f"Terjemahan subtitle dilewati ({str(exc).splitlines()[0][:120]}); memakai bahasa asli.")
    return _remap(words, ctx.start, scenes)


def _scene_assets(ctx: ClipContext, clean: Path, scenes: list[dict], look: dict, srv: _AssetServer,
                  W: int, H: int, allow_ai: bool, p0: float, p1: float) -> tuple[list[dict], int]:
    adir = ctx.cdir / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    keyframes = []
    for i, sc in enumerate(scenes):
        check_cancel()
        progress(p0 + (p1 - p0) * 0.4 * i / len(scenes), f"Keyframe adegan {i + 1}/{len(scenes)}")
        kp = adir / f"kf_{int(sc['start'] * 100):06d}_{int(sc['end'] * 100):06d}.jpg"
        if not kp.is_file():
            frame = best_frame(clean, sc["start"], sc["end"])
            if frame is None:
                frame = (keyframes[-1][1] if keyframes else None)
            if frame is None:
                raise ClipAgentError("Tidak bisa membaca frame dari klip.")
            cv2.imwrite(str(kp), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        img = cv2.imread(str(kp))
        fb = face_box(img)
        focus = [(fb[0] + fb[2] / 2) / img.shape[1], (fb[1] + fb[3] / 2) / img.shape[0]] if fb else None
        keyframes.append((kp, img, focus))

    gen = ImageGen.from_env() if (look["media"] == "ai" and allow_ai) else None
    if look["media"] == "ai" and allow_ai and gen is None:
        log("Gambar AI butuh GEMINI_API_KEY (atau IMAGE_API_KEY); memakai gambar kartun lokal.")
    samples = [k[1] for k in keyframes]
    out, ai_used = [], 0
    for i, (sc, (kp, img, focus)) in enumerate(zip(scenes, keyframes)):
        check_cancel()
        progress(p0 + (p1 - p0) * (0.4 + 0.6 * i / len(scenes)), f"Gambar adegan {i + 1}/{len(scenes)}")
        item = {"focus": focus}
        if look["media"] == "video":
            item["video"] = srv.url(clean)
            item["videoFrom"] = sc["start"]
        elif look["media"] == "asli":
            item["image"] = srv.url(kp)
        else:
            path = None
            if gen is not None:
                tag = hashlib.sha1(f"{kp.name}|{look['cartoon']}|{look['ai_prompt']}|{sc['prompt']}|{gen.model}".encode()).hexdigest()[:12]
                path = adir / f"ai_{tag}.png"
                if not path.is_file():
                    try:
                        desc = ", ".join(x for x in (look["ai_prompt"], sc["prompt"]) if x)
                        res = gen.redraw(img, look["cartoon"], desc, "9:16" if H > W else "16:9")
                        cv2.imwrite(str(path), res)
                    except Cancelled:
                        raise
                    except QuotaError as exc:
                        log(f"  {exc} Semua adegan memakai kartun lokal.")
                        gen, path = None, None
                    except ClipAgentError as exc:
                        log(f"  adegan {i + 1}: AI gagal ({str(exc)[:120]}); memakai kartun lokal.")
                        path = None
                if path is not None:
                    ai_used += 1
            if path is None:
                path = adir / f"{look['cartoon']}_{kp.stem}.jpg"
                if not path.is_file():
                    cv2.imwrite(str(path), stylize_image(img, look["cartoon"], samples), [cv2.IMWRITE_JPEG_QUALITY, 92])
            item["image"] = srv.url(path)
        out.append(item)
    return out, ai_used


def _props(ctx: ClipContext, opts: dict, scenes: list[dict], assets: list[dict], look: dict,
           srv: _AssetServer, clean: Path, cinfo: dict, words: list[dict]) -> dict:
    t, sc_props, audio_parts = 0.0, [], []
    for sc, a in zip(scenes, assets):
        dur = sc["end"] - sc["start"]
        sc_props.append({"start": round(t, 3), "dur": round(dur, 3), "heading": sc["heading"], "bubble": sc["bubble"],
                         "sfx": sc["sfx"], "camera": sc["camera"], "transition": sc["transition"], **a})
        audio_parts.append({"at": round(t, 3), "from": sc["start"], "to": sc["end"]})
        t += dur
    style = dict(look["style"])
    if opts.get("subtitles") is False:
        style["captions"] = "none"
    hook = (ctx.clip.get("title") or "") if opts.get("hook_overlay", True) else ""
    return {"fps": 30, "width": cinfo["width"], "height": cinfo["height"], "duration": round(t, 3),
            "audio": srv.url(clean) if cinfo["has_audio"] else None, "audioParts": audio_parts,
            "scenes": sc_props, "words": words, "hook": hook, "progressBar": bool(opts.get("progress_bar", False)),
            "style": style}


# ---------------------------------------------------------------- tugas utama
def render_animation(ctx: ClipContext, opts: dict) -> dict:
    scenes = normalize_scenes(opts.get("scenes"), ctx.duration)
    look = resolve_style(opts)
    clean = clean_clip(ctx)
    cinfo = probe(clean)
    log(f"Animasi Remotion gaya '{look['name']}' ({len(scenes)} adegan).")
    words = _subtitle_words(ctx, opts, scenes)
    with _AssetServer(ctx.out_dir) as srv:
        assets, ai_used = _scene_assets(ctx, clean, scenes, look, srv, cinfo["width"], cinfo["height"], True, 0.08, 0.35)
        props = _props(ctx, opts, scenes, assets, look, srv, clean, cinfo, words)
        name = f"{ctx.slug}__remotion-{slugify(look['name'], 24)}"
        out = ctx.workdir / "clips" / f"{name}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".part.mp4")
        try:
            # Video bergerak berwarna poster sangat detail; CRF sedikit lebih tinggi menjaga ukuran file wajar.
            crf = 23 if look["media"] == "video" else 20
            _run_remotion({"mode": "video", "props": props, "output": str(tmp.resolve()), "crf": crf},
                          0.35, 0.99, "Merender dengan Remotion")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    os.replace(tmp, out)
    (ctx.cdir / "last_storyboard.json").write_text(json.dumps({"scenes": scenes, "style": look}, ensure_ascii=False,
                                                              indent=2), encoding="utf-8")
    entry = {"kind": "animation", "engine": "remotion", "file": out.name, "label": look["name"],
             "media": look["media"], "scenes": len(scenes), "duration": props["duration"], "ai_images": ai_used,
             "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    ctx.clip["extras"] = [x for x in ctx.clip.get("extras", []) if x.get("file") != out.name] + [entry]
    save_plan(ctx)
    progress(1.0, "Animasi selesai")
    log(f"Selesai: {out.name}")
    return {**entry, "video_url": ctx.url(out)}


def _save_preview(ctx: ClipContext, kind: str, items: list[dict]) -> None:
    p = ctx.cdir / "preview" / "preview.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    data[kind] = items
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def preview_frames(ctx: ClipContext, opts: dict) -> dict:
    """Tiga frame contoh dari storyboard + gaya yang dipilih, sebelum merender video penuh."""
    scenes = normalize_scenes(opts.get("scenes"), ctx.duration)
    look = resolve_style(opts)
    clean = clean_clip(ctx)
    cinfo = probe(clean)
    words = _subtitle_words(ctx, opts, scenes)
    pdir = ctx.cdir / "preview"
    pdir.mkdir(parents=True, exist_ok=True)
    for old in pdir.glob("frame_*.jpg"):
        old.unlink()
    pick = sorted({0, len(scenes) // 2, len(scenes) - 1})
    with _AssetServer(ctx.out_dir) as srv:
        assets, _ = _scene_assets(ctx, clean, scenes, look, srv, cinfo["width"], cinfo["height"],
                                  bool(opts.get("allow_ai")), 0.05, 0.5)
        props = _props(ctx, opts, scenes, assets, look, srv, clean, cinfo, words)
        stamp = time.strftime("%H%M%S")
        stills, items = [], []
        for k in pick:
            sc = props["scenes"][k]
            frame = int((sc["start"] + sc["dur"] * 0.6) * props["fps"])
            name = f"frame_{k}_{stamp}.jpg"
            stills.append({"frame": frame, "output": str((pdir / name).resolve())})
            items.append({"file": name, "label": f"Adegan {k + 1}", "style": look["name"]})
        _run_remotion({"mode": "stills", "props": props, "stills": stills, "scale": 0.5}, 0.5, 1.0,
                      "Merender pratinjau")
    _save_preview(ctx, "frames", items)
    progress(1.0, "Pratinjau siap")
    return {"count": len(items)}


def preview_styles(ctx: ClipContext, opts: dict) -> dict:
    """Satu frame contoh untuk setiap preset gaya (tanpa memanggil AI agar gratis dan cepat)."""
    scenes = normalize_scenes(opts.get("scenes"), ctx.duration)
    k = next((i for i, s in enumerate(scenes) if s["heading"] or s["bubble"]), 0)
    one = [scenes[k]]
    clean = clean_clip(ctx)
    cinfo = probe(clean)
    words = _subtitle_words(ctx, opts, one)
    pdir = ctx.cdir / "preview"
    pdir.mkdir(parents=True, exist_ok=True)
    for old in pdir.glob("style_*.jpg"):
        old.unlink()
    stamp = time.strftime("%H%M%S")
    stills, items = [], []
    with _AssetServer(ctx.out_dir) as srv:
        for n, pid in enumerate(PRESETS):
            look = resolve_style({"preset": pid})
            if look["media"] == "ai":
                look["media"] = "kartun"
            assets, _ = _scene_assets(ctx, clean, one, look, srv, cinfo["width"], cinfo["height"], False,
                                      0.05 + 0.6 * n / len(PRESETS), 0.05 + 0.6 * (n + 1) / len(PRESETS))
            props = _props(ctx, {**opts, "hook_overlay": False}, one, assets, look, srv, clean, cinfo, words)
            name = f"style_{pid}_{stamp}.jpg"
            stills.append({"props": props, "frame": int(props["duration"] * 0.6 * props["fps"]),
                           "output": str((pdir / name).resolve())})
            items.append({"file": name, "preset": pid, "label": PRESETS[pid]["name"]})
        _run_remotion({"mode": "stills", "props": stills[0]["props"], "stills": stills, "scale": 0.4}, 0.65, 1.0,
                      "Merender contoh gaya")
    _save_preview(ctx, "styles", items)
    progress(1.0, "Contoh gaya siap")
    return {"count": len(items)}
