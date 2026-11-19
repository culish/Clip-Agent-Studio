"""Konteks klip + storyboard untuk versi animasi/kartun (dirender dengan Remotion, lihat animation.py).

Alur:
1. build_storyboards(): siapkan klip "bersih" (tanpa subtitle), bagi menjadi kalimat, lalu AI menyusun
   TIGA pilihan storyboard: per kalimat, per poin utama, dan panel komik.
2. Pengguna memilih salah satu atau menulis storyboard sendiri, lalu mengedit adegan
   (waktu, judul layar, balon kata, SFX, deskripsi gambar AI, gerak kamera, transisi).
3. Pengguna memilih gaya animasi (preset atau kustom), melihat pratinjau, lalu merender video.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, fields
from pathlib import Path

import cv2
import numpy as np

from .config import Settings
from .imagegen import ImageGen
from .llm import LLMClient
from .render import _load_face_detector, render_clip
from .transcript import Word, group_segments, load_words
from .utils import ClipAgentError, check_cancel, log, probe, progress, slugify

CAMERAS = {"zoom_in": "Zoom masuk", "zoom_out": "Zoom keluar", "pan_right": "Geser ke kanan",
           "pan_left": "Geser ke kiri", "static": "Diam"}
TRANSITIONS = {"fade": "Pudar", "slide": "Geser", "wipe": "Sapu", "flip": "Balik", "clockwipe": "Putar jam",
               "iris": "Lingkaran", "none": "Potong langsung"}
OPTION_INFO = {
    "kalimat": ("Per kalimat", "Satu adegan untuk setiap kalimat. Paling setia pada isi video."),
    "poin": ("Per poin utama", "Beberapa kalimat digabung menjadi 3–6 poin, masing-masing dengan judul besar."),
    "komik": ("Panel komik", "4–8 panel dengan balon kata singkat dan efek suara."),
}
MAX_SEGMENTS = 24
_SETTING_KEYS = {f.name for f in fields(Settings)}


# ====================================================================== konteks klip
@dataclass
class ClipContext:
    out_dir: Path
    video_id: str
    rank: int
    workdir: Path
    plan: dict
    clip: dict
    video: Path
    info: dict
    words: list[Word]
    tlang: str
    render_opts: dict

    @property
    def start(self) -> float:
        return float(self.clip["start"])

    @property
    def end(self) -> float:
        return float(self.clip["end"])

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def slug(self) -> str:
        return f"{self.rank:02d}_{slugify(self.clip.get('title', ''))}"

    @property
    def cdir(self) -> Path:
        d = self.workdir / "creative" / f"{self.rank:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def url(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.out_dir.resolve()).as_posix()
        return f"/files/{rel}?v={int(path.stat().st_mtime)}" if path.exists() else f"/files/{rel}"

    def settings(self, **overrides) -> Settings:
        data = {k: v for k, v in {**self.render_opts, **overrides}.items() if k in _SETTING_KEYS}
        cfg = Settings(source=str(self.video), out_dir=self.out_dir, **data)
        cfg.resolve()
        return cfg


def load_context(out_dir: Path, video_id: str, rank: int) -> ClipContext:
    workdir = out_dir / video_id
    plan_path = workdir / "plan.json"
    if not plan_path.is_file():
        raise ClipAgentError("Video ini belum punya klip. Buat klip dulu di Studio.")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    clip = next((c for c in plan.get("clips", []) if int(c.get("rank", 0)) == int(rank)), None)
    if clip is None:
        raise ClipAgentError(f"Klip #{rank} tidak ditemukan.")
    video = next((workdir / f"source{e}" for e in (".mp4", ".webm", ".mov", ".mkv")
                  if (workdir / f"source{e}").is_file()), None)
    if video is None:
        local = Path(plan.get("source", {}).get("url", ""))
        if local.is_file():
            video = local
    if video is None:
        raise ClipAgentError("File video sumber tidak ditemukan. Buat ulang klip dari Studio.")
    tpath = workdir / "transcript.json"
    words, _, tlang = load_words(tpath) if tpath.is_file() else ([], "", "")
    return ClipContext(out_dir, video_id, int(rank), workdir, plan, clip, video, probe(video), words, tlang,
                       dict(plan.get("render") or {}))


def clean_clip(ctx: ClipContext) -> Path:
    """Klip tanpa subtitle/efek dengan crop yang sama, bahan untuk versi animasi (disimpan di cache)."""
    work = ctx.cdir / "work"
    out = work / "clean.mp4"
    stamp = (f"{ctx.start:.2f}-{ctx.end:.2f}-{ctx.render_opts.get('aspect', '9:16')}-{ctx.render_opts.get('crop', 'face')}-"
             f"{json.dumps(ctx.clip.get('layout') or ctx.render_opts.get('layout') or 'auto', sort_keys=True)}")
    marker = work / "clean.txt"
    if out.is_file() and marker.is_file() and marker.read_text() == stamp:
        return out
    log("Menyiapkan klip bersih (tanpa subtitle) sebagai bahan animasi...")
    for stale in ("thumbs", "assets"):                 # cache frame lama milik klip versi sebelumnya
        shutil.rmtree(ctx.cdir / stale, ignore_errors=True)
    cfg = ctx.settings()
    render_clip(cfg, ctx.video, ctx.info, ctx.clip, ctx.words, work, name="clean", bare=True,
                on_frac=lambda f: progress(0.02 + 0.3 * f, "Menyiapkan klip bersih"))
    marker.write_text(stamp)
    return out


def layout_info(ctx: ClipContext) -> dict:
    """Data untuk editor layout: frame sumber, ukuran, usulan kotak tiap mode, dan layout klip saat ini."""
    import cv2

    from . import layout as L
    from .render import plan_geometry
    W, H = ctx.info["width"], ctx.info["height"]
    aspect = ctx.render_opts.get("aspect", "9:16")
    geo = plan_geometry(aspect if aspect in ("9:16", "4:5") else "9:16", W, H)
    frame = ctx.cdir / f"layout_frame_{int(ctx.start * 10)}_{int(ctx.end * 10)}.jpg"
    if not frame.is_file():
        cap = cv2.VideoCapture(str(ctx.video))
        cap.set(cv2.CAP_PROP_POS_MSEC, (ctx.start + ctx.duration * 0.4) * 1000)
        ok, img = cap.read()
        cap.release()
        if not ok:
            raise ClipAgentError("Frame video sumber tidak bisa dibaca.")
        sc = min(1.0, 1280 / img.shape[1])
        if sc < 1:
            img = cv2.resize(img, (int(img.shape[1] * sc), int(img.shape[0] * sc)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(frame), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    cache = ctx.cdir / f"layout_suggest_{int(ctx.start * 10)}_{int(ctx.end * 10)}.json"
    if cache.is_file():
        sug = json.loads(cache.read_text(encoding="utf-8"))
    else:
        sug = L.suggestions(ctx.video, ctx.start, ctx.end, geo["out_w"], geo["out_h"])
        cache.write_text(json.dumps(sug), encoding="utf-8")
    cur = L.clean(ctx.clip.get("layout") or {"mode": ctx.render_opts.get("layout", "auto"),
                                              "split": ctx.render_opts.get("split", 0)})
    return {"frame_url": ctx.url(frame), "W": W, "H": H, "OW": geo["out_w"], "OH": geo["out_h"], "aspect": aspect,
            "modes": L.MODES, "suggest": sug, "current": cur, "title": ctx.clip.get("title", ""),
            "video_url": ctx.url(ctx.workdir / "clips" / ctx.clip["file"]) if ctx.clip.get("file") else ""}


def relayout_clip(ctx: ClipContext, opts: dict) -> dict:
    """Render ulang klip dengan layout baru (streaming/reaction/pip/podcast atau satu layar)."""
    import os

    from . import layout as L
    from .translate import translate_clip_words
    lay = L.clean(opts.get("layout"))
    cfg = ctx.settings()
    if lay["mode"] != "auto" and cfg.aspect not in ("9:16", "4:5"):
        raise ClipAgentError("Layout streaming/reaction hanya untuk klip 9:16 atau 4:5. Buat ulang klip dengan rasio 9:16.")
    sub_words = None
    target = ctx.clip.get("sub_lang") or ""
    if cfg.subtitles and target and target != (ctx.tlang or ""):
        try:
            sub_words = translate_clip_words(cfg, ctx.words, [(ctx.start, ctx.end)], target,
                                             ctx.workdir / f"translations_{target}.json").get(0)
        except ClipAgentError as exc:
            log(f"Terjemahan subtitle dilewati ({str(exc).splitlines()[0][:100]}).")
    clips_dir = ctx.workdir / "clips"
    name = Path(ctx.clip.get("file") or f"{ctx.slug}.mp4").stem
    tmp = f"{name}__layout"
    log(f"Render ulang klip #{ctx.rank} dengan layout: {L.MODES[lay['mode']]}")
    out = render_clip(cfg, ctx.video, ctx.info, dict(ctx.clip, layout=lay), ctx.words, clips_dir, sub_words=sub_words,
                      name=tmp, on_frac=lambda f: progress(0.05 + 0.9 * f, "Render ulang klip"))
    for ext in (".mp4", ".ass", ".srt"):
        src = clips_dir / f"{tmp}{ext}"
        if src.is_file():
            os.replace(src, clips_dir / f"{name}{ext}")
    ctx.clip["layout"] = lay
    ctx.clip["file"] = f"{name}.mp4"
    save_plan(ctx)
    progress(1.0, "Klip selesai dirender ulang")
    return {"file": f"{name}.mp4", "layout": lay, "video_url": ctx.url(clips_dir / f"{name}.mp4")}


def save_plan(ctx: ClipContext) -> None:
    (ctx.workdir / "plan.json").write_text(json.dumps(ctx.plan, ensure_ascii=False, indent=2), encoding="utf-8")


def same_range(meta: dict | None, ctx: ClipContext) -> bool:
    """Data kreatif lama tidak dipakai bila klipnya sudah berubah (dibuat ulang dari Studio)."""
    r = (meta or {}).get("clip_range")
    return bool(r) and abs(r[0] - ctx.start) < 0.05 and abs(r[1] - ctx.end) < 0.05


# ====================================================================== frame & wajah
def _sharpness(img: np.ndarray) -> float:
    g = cv2.cvtColor(cv2.resize(img, (270, 480)) if img.shape[1] > 270 else img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


_DET = {"d": None, "loaded": False}


def face_box(img: np.ndarray) -> tuple[float, float, float, float] | None:
    """Wajah terbesar (x, y, w, h) dalam koordinat gambar, atau None."""
    if not _DET["loaded"]:
        _DET["d"], _DET["loaded"] = _load_face_detector(), True
    det = _DET["d"]
    if det is None:
        return None
    h, w = img.shape[:2]
    sc = min(1.0, 480 / w)
    small = cv2.resize(img, (int(w * sc), int(h * sc))) if sc < 1 else img
    det.setInputSize((small.shape[1], small.shape[0]))
    _, faces = det.detect(small)
    if faces is None or not len(faces):
        return None
    f = max(faces, key=lambda f: float(f[2] * f[3]))
    return tuple(float(v) / sc for v in f[:4])


def read_frame(video: Path, t: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def best_frame(video: Path, s: float, e: float) -> np.ndarray | None:
    """Frame terbaik di rentang [s, e): utamakan wajah yang jelas, lalu ketajaman."""
    cap = cv2.VideoCapture(str(video))
    cands = []
    for f in (0.2, 0.35, 0.5, 0.65, 0.8):
        cap.set(cv2.CAP_PROP_POS_MSEC, (s + (e - s) * f) * 1000.0)
        ok, frame = cap.read()
        if ok:
            fb = face_box(frame)
            area = (fb[2] * fb[3]) / (frame.shape[0] * frame.shape[1]) if fb else 0.0
            cands.append((frame, _sharpness(frame), area))
    cap.release()
    if not cands:
        return None
    ms = max(c[1] for c in cands) or 1.0
    ma = max(c[2] for c in cands) or 1.0
    return max(cands, key=lambda c: c[1] / ms + (1.5 * c[2] / ma if c[2] else 0.0))[0]


def thumb(ctx: ClipContext, t: float, width: int = 270) -> Path:
    """Gambar kecil klip bersih pada detik t (untuk kartu adegan di UI), di-cache."""
    clean = ctx.cdir / "work" / "clean.mp4"
    t = round(min(max(0.0, t), max(0.0, ctx.duration - 0.05)), 1)
    # Sebelum klip bersih ada, ambil dari video sumber (belum di-crop) dan jangan di-cache.
    p = ctx.cdir / "thumbs" / (f"t{int(t * 10):05d}.jpg" if clean.is_file() else f"src{int(t * 10):05d}.jpg")
    if not p.is_file():
        frame = read_frame(clean, t) if clean.is_file() else read_frame(ctx.video, ctx.start + t)
        if frame is None:
            raise ClipAgentError("Frame tidak bisa dibaca.")
        p.parent.mkdir(parents=True, exist_ok=True)
        h = round(frame.shape[0] * width / frame.shape[1])
        cv2.imwrite(str(p), cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 82])
    return p


# ====================================================================== storyboard
def plan_segments(words: list[Word], start: float, end: float, max_segments: int = MAX_SEGMENTS) -> list[dict]:
    """Bagi klip menjadi kalimat (relatif terhadap awal klip), menutup seluruh durasi tanpa celah."""
    dur = end - start
    inside = [w for w in words if w.end > start + 0.02 and w.start < end - 0.02]
    segs = group_segments(inside, max_gap=0.5, max_len=6.0, max_chars=100)
    cuts: list[dict] = []
    for sg in segs:
        s = max(0.0, sg.start - start)
        if not cuts or s - cuts[-1]["start"] >= 1.2:
            cuts.append({"start": s, "text": sg.text})
        else:
            cuts[-1]["text"] += " " + sg.text
    if not cuts:
        n = max(1, round(dur / 3.0))
        cuts = [{"start": dur * i / n, "text": ""} for i in range(n)]
    cuts[0]["start"] = 0.0
    while len(cuts) > max_segments:
        lens = [(cuts[i + 1]["start"] if i + 1 < len(cuts) else dur) - c["start"] for i, c in enumerate(cuts)]
        i = min(range(len(cuts) - 1), key=lambda k: lens[k] + lens[k + 1])
        cuts[i]["text"] = (cuts[i]["text"] + " " + cuts[i + 1]["text"]).strip()
        del cuts[i + 1]
    out: list[dict] = []
    for i, c in enumerate(cuts):
        e = cuts[i + 1]["start"] if i + 1 < len(cuts) else dur
        if e - c["start"] < 0.4 and out:
            out[-1]["end"] = round(e, 3)
            out[-1]["text"] = (out[-1]["text"] + " " + c["text"]).strip()
            continue
        out.append({"start": round(c["start"], 3), "end": round(e, 3), "text": c["text"].strip()})
    return out


SB_SYSTEM = """You are a storyboard artist for short vertical videos. You turn a spoken clip into
scenes for an animated/cartoon version. Answer ONLY with valid JSON."""

SB_PROMPT = """Clip title: {title}
Target audience: {audience}. On-screen text language: {lang}.

Sentences (index, seconds, what is said):
{lines}

Create THREE storyboard options. In every option, scenes cover the sentences in order without gaps;
each scene covers a continuous range of sentence indexes "from".."to" (inclusive).
- "kalimat": one scene per sentence (from = to).
- "poin": 3 to 6 scenes; each groups consecutive sentences into one key point with a punchy "heading".
- "komik": 4 to 8 comic panels; each has a short "bubble" (max 12 words, condensed from what is said)
  and an optional "sfx" (one onomatopoeia such as "BOOM!", "WAIT...", "WOW!" or empty).

Every scene: "from", "to",
"title" (2-5 words, Bahasa Indonesia, editor label),
"heading" (2-6 words in {lang}, shown on screen; may be empty in "kalimat"),
"bubble" (in {lang}; empty unless it helps),
"sfx", "visual" (one sentence, Bahasa Indonesia),
"prompt" (one English sentence for an illustrator: setting, subject, mood; no names of real people),
"camera" (zoom_in|zoom_out|pan_left|pan_right|static), "transition" (fade|slide|wipe|flip|clockwipe|iris|none).

JSON: {{"options": {{"kalimat": [...], "poin": [...], "komik": [...]}}}}"""

_CAMS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]


def _scene(segs: list[dict], a: int, b: int, k: int, **kw) -> dict:
    text = " ".join(s["text"] for s in segs[a:b + 1]).strip()
    words = text.split()
    sc = {"start": segs[a]["start"], "end": segs[b]["end"], "text": text,
          "title": " ".join(words[:5]) or f"Adegan {k + 1}", "heading": "", "bubble": "", "sfx": "",
          "visual": text or "Pembicara di depan kamera",
          "prompt": "A person talking to the camera with an expressive face, cinematic lighting",
          "camera": _CAMS[k % len(_CAMS)], "transition": "fade"}
    sc.update(kw)
    return sc


def _even_groups(n: int, k: int) -> list[tuple[int, int]]:
    k = max(1, min(k, n))
    bounds = [round(i * n / k) for i in range(k + 1)]
    return [(bounds[i], bounds[i + 1] - 1) for i in range(k) if bounds[i + 1] > bounds[i]]


def fallback_options(segs: list[dict]) -> dict:
    n = len(segs)
    kal = [_scene(segs, i, i, i) for i in range(n)]
    poin = [_scene(segs, a, b, k, transition="slide") for k, (a, b) in enumerate(_even_groups(n, min(6, max(3, round(n / 2)))))]
    for sc in poin:
        sc["heading"] = " ".join(sc["text"].split()[:4])
    kom = [_scene(segs, a, b, k, transition="slide") for k, (a, b) in enumerate(_even_groups(n, min(8, max(4, n))))]
    for sc in kom:
        sc["bubble"] = " ".join(sc["text"].split()[:12])
    return {"kalimat": kal, "poin": poin, "komik": kom}


def _from_llm(items: list, segs: list[dict]) -> list[dict] | None:
    n, scenes, expect = len(segs), [], 0
    for k, it in enumerate(items or []):
        try:
            a, b = int(it["from"]), int(it["to"])
        except (KeyError, TypeError, ValueError):
            return None
        if a != expect or b < a or b >= n:
            return None
        sc = _scene(segs, a, b, k)
        for key in ("title", "heading", "bubble", "sfx", "visual", "prompt"):
            v = str(it.get(key) or "").strip()
            if v or key in ("heading", "bubble", "sfx"):
                sc[key] = v[:160]
        if it.get("camera") in CAMERAS:
            sc["camera"] = it["camera"]
        if it.get("transition") in TRANSITIONS:
            sc["transition"] = it["transition"]
        scenes.append(sc)
        expect = b + 1
    return scenes if scenes and expect == n else None


def build_storyboards(ctx: ClipContext) -> dict:
    clean_clip(ctx)
    check_cancel()
    progress(0.4, "Membagi kalimat")
    segs = plan_segments(ctx.words, ctx.start, ctx.end)
    options = fallback_options(segs)
    source = "aturan"
    try:
        cfg = ctx.settings()
    except ValueError:
        cfg = None
    if cfg is not None and cfg.provider != "heuristic":
        progress(0.5, "AI menyusun pilihan storyboard")
        lines = "\n".join(f"[{i}] {s['start']:.1f}-{s['end']:.1f}: {s['text'] or '(no speech)'}" for i, s in enumerate(segs))
        try:
            client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)
            data = client.complete_json(SB_SYSTEM, SB_PROMPT.format(
                title=ctx.clip.get("title", ""), audience="United States" if cfg.audience == "us" else "Indonesia",
                lang=cfg.output_language, lines=lines))
            for key in OPTION_INFO:
                got = _from_llm((data.get("options") or {}).get(key), segs)
                if got:
                    options[key] = got
                    source = "ai"
                else:
                    log(f"Pilihan storyboard '{key}' dari AI tidak valid; memakai versi sederhana.")
        except ClipAgentError as exc:
            log(f"AI storyboard tidak tersedia ({str(exc).splitlines()[0]}); memakai versi sederhana.")
    progress(0.9, "Menyimpan storyboard")
    data = {"video_id": ctx.video_id, "rank": ctx.rank, "clip_title": ctx.clip.get("title", ""),
            "clip_range": [round(ctx.start, 2), round(ctx.end, 2)], "duration": round(ctx.duration, 2),
            "segments": segs, "source": source, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "options": [{"id": k, "name": OPTION_INFO[k][0], "desc": OPTION_INFO[k][1], "scenes": options[k]}
                        for k in OPTION_INFO]}
    (ctx.cdir / "storyboards.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Storyboard siap: {', '.join(f'{o['name']} ({len(o['scenes'])} adegan)' for o in data['options'])}.")
    progress(1.0, "Storyboard siap")
    return data


def load_storyboards(ctx: ClipContext) -> dict | None:
    p = ctx.cdir / "storyboards.json"
    sb = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    return sb if same_range(sb, ctx) else None


# ====================================================================== status untuk UI
def creative_state(ctx: ClipContext) -> dict:
    """Semua data untuk tab Cover & animasi: klip, cover, storyboard, pratinjau, dan hasil animasi."""
    from .animation import PRESETS, OPTIONS as STYLE_OPTIONS, remotion_status

    clips_dir = ctx.workdir / "clips"
    clip = dict(ctx.clip)
    if clip.get("file") and (clips_dir / clip["file"]).is_file():
        clip["video_url"] = ctx.url(clips_dir / clip["file"])
    covers = None
    cpath = ctx.cdir / "covers" / "covers.json"
    if cpath.is_file():
        meta = json.loads(cpath.read_text(encoding="utf-8"))
        if same_range(meta, ctx):
            for c in meta["covers"]:
                for tag in ("v", "h"):
                    if c.get(tag):
                        c[f"{tag}_url"] = ctx.url(ctx.cdir / "covers" / c[tag])
            covers = meta
    previews = {}
    pp = ctx.cdir / "preview" / "preview.json"
    if pp.is_file():
        pv = json.loads(pp.read_text(encoding="utf-8"))
        for kind in ("frames", "styles"):
            items = [dict(x, url=ctx.url(ctx.cdir / "preview" / x["file"])) for x in pv.get(kind, [])
                     if (ctx.cdir / "preview" / x["file"]).is_file()]
            if items:
                previews[kind] = items
    anims = []
    for x in clip.get("extras", []):
        f = clips_dir / x.get("file", "")
        if x.get("kind") in ("animation", "autoedit") and f.is_file():
            sc = x.get("scenes")
            anims.append({**x, "video_url": ctx.url(f), "scenes": len(sc) if isinstance(sc, list) else sc or 0,
                          "path": f.resolve().relative_to(ctx.out_dir.resolve()).as_posix(),
                          "label": x.get("label") or f"Versi lama, gaya {x.get('style', '?')}"})
    return {"video_id": ctx.video_id, "rank": ctx.rank, "title": ctx.plan.get("source", {}).get("title", ""),
            "duration": round(ctx.duration, 2), "clip": clip, "covers": covers,
            "storyboards": load_storyboards(ctx), "segments": plan_segments(ctx.words, ctx.start, ctx.end),
            "previews": previews, "animations": anims[::-1],
            "image_ai": ImageGen.from_env() is not None, "remotion": remotion_status(),
            "presets": PRESETS, "style_options": STYLE_OPTIONS, "cameras": CAMERAS, "transitions": TRANSITIONS}
