"""Pembuat ulang video: dari video viral (atau topik) menjadi video BARU dengan naskah orisinal.

Alur:
1. write_script(): ambil teks ucapan video sumber (tanpa mengunduh videonya), lalu AI menulis naskah
   baru dengan sudut pandang dan kata-kata sendiri. Kemiripan dengan sumber diukur (5-gram) dan AI
   diminta menulis ulang bila terlalu mirip. Ini penting agar lolos aturan "inauthentic/reused content".
2. Pengguna mengedit naskah per adegan (narasi, judul layar, jenis visual, deskripsi gambar, kata kunci stok).
3. build_assets(): suara narasi per adegan (TTS), visual per adegan (gambar AI dengan karakter, video AI,
   video stok Pexels, atau kartu teks), musik latar.
4. render(): semua digabung dan dirender dengan Remotion (caption karaoke, musik dengan ducking).
Proyek disimpan di <output>/_projects/<id>/.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from . import broll, characters, music, tts, videogen
from .animation import PRESETS, _AssetServer, _run_remotion, resolve_style
from .config import Settings
from .download import fetch_source_text, is_url
from .imagegen import ImageGen
from .llm import LLMClient
from .utils import ClipAgentError, check_cancel, log, progress, slugify

VISUALS = {"ai_image": "Gambar AI", "ai_video": "Video AI (berbayar)", "stock": "Video stok (Pexels)",
           "text": "Kartu teks"}
CAMERAS = ["zoom_in", "pan_right", "zoom_out", "pan_left", "static"]
TRANSITIONS = ["fade", "slide", "wipe", "flip", "clockwipe", "iris", "none"]
LENGTHS = [30, 45, 60, 90, 180]
DEFAULT_SETTINGS = {"length": 45, "aspect": "9:16", "audience": "us", "angle": "", "character": "",
                    "voice_engine": "gemini", "voice": "", "voice_style": "", "visual": "ai_image",
                    "art": "kartun3d", "preset": "faceless", "music": "auto", "music_volume": 0.35,
                    "captions": True, "hook": False, "progress_bar": True, "allow_paid_video": False}


# ---------------------------------------------------------------- penyimpanan
def _root(out_dir: Path) -> Path:
    d = out_dir / "_projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdir(out_dir: Path, pid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{10}", pid or ""):
        raise ClipAgentError("ID proyek tidak valid.")
    return _root(out_dir) / pid


def load(out_dir: Path, pid: str) -> dict:
    p = pdir(out_dir, pid) / "project.json"
    if not p.is_file():
        raise ClipAgentError("Proyek tidak ditemukan.")
    return json.loads(p.read_text(encoding="utf-8"))


def save(out_dir: Path, proj: dict) -> dict:
    proj["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d = pdir(out_dir, proj["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
    return proj


def _url(out_dir: Path, p: Path) -> str:
    return f"/files/{p.resolve().relative_to(out_dir.resolve()).as_posix()}?v={int(p.stat().st_mtime)}"


def public(out_dir: Path, proj: dict) -> dict:
    d = pdir(out_dir, proj["id"])
    out = json.loads(json.dumps(proj))
    for r in out.get("renders", []):
        f = d / r["file"]
        r["video_url"] = _url(out_dir, f) if f.is_file() else ""
        r["path"] = f.resolve().relative_to(out_dir.resolve()).as_posix() if f.is_file() else ""
    out["renders"] = [r for r in out.get("renders", []) if r["video_url"]][::-1]
    prev = out.get("preview") or {}
    for sc in prev.get("scenes", []):
        for k in ("thumb", "audio"):
            if sc.get(k) and (d / "assets" / sc[k]).is_file():
                sc[f"{k}_url"] = _url(out_dir, d / "assets" / sc[k])
    return out


def list_projects(out_dir: Path) -> list[dict]:
    items = []
    for p in _root(out_dir).glob("*/project.json"):
        try:
            pr = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        items.append({"id": pr["id"], "title": (pr.get("script") or {}).get("title") or pr.get("source", {}).get("title", ""),
                      "updated": pr.get("updated", ""), "renders": len(pr.get("renders", [])),
                      "source": pr.get("source", {}).get("title") or pr.get("topic", "")})
    return sorted(items, key=lambda x: x["updated"], reverse=True)


def delete(out_dir: Path, pid: str) -> None:
    import shutil
    shutil.rmtree(pdir(out_dir, pid), ignore_errors=True)


def clean_settings(raw: dict, base: dict | None = None) -> dict:
    st = dict(base or DEFAULT_SETTINGS)
    raw = raw or {}
    if raw.get("length") in LENGTHS or str(raw.get("length", "")).isdigit():
        st["length"] = max(15, min(600, int(raw["length"])))
    for k, choices in (("aspect", ("9:16", "16:9")), ("audience", ("us", "id")), ("visual", tuple(VISUALS)),
                       ("art", tuple(characters.ART_STYLES)), ("preset", tuple(PRESETS)),
                       ("voice_engine", ("gemini", "edge"))):
        if raw.get(k) in choices:
            st[k] = raw[k]
    for k, n in (("angle", 400), ("character", 16), ("voice", 60), ("voice_style", 120), ("music", 120)):
        if k in raw:
            st[k] = str(raw[k] or "").strip()[:n]
    for k in ("captions", "hook", "progress_bar", "allow_paid_video"):
        if k in raw:
            st[k] = bool(raw[k])
    try:
        st["music_volume"] = min(1.0, max(0.0, float(raw.get("music_volume", st["music_volume"]))))
    except (TypeError, ValueError):
        pass
    return st


def clean_scenes(raw: list) -> list[dict]:
    out = []
    for i, sc in enumerate(raw or []):
        if not isinstance(sc, dict):
            continue
        narr = re.sub(r"\s+", " ", str(sc.get("narration") or "")).strip()[:600]
        if not narr:
            continue
        out.append({"id": str(sc.get("id") or uuid.uuid4().hex[:6])[:12], "narration": narr,
                    "heading": str(sc.get("heading") or "").strip()[:80],
                    "visual": sc.get("visual") if sc.get("visual") in VISUALS else "",
                    "prompt": str(sc.get("prompt") or "").strip()[:400],
                    "stock": str(sc.get("stock") or "").strip()[:80],
                    "camera": sc.get("camera") if sc.get("camera") in CAMERAS else CAMERAS[i % 4],
                    "transition": sc.get("transition") if sc.get("transition") in TRANSITIONS else "fade"})
    return out


# ---------------------------------------------------------------- naskah
def _ngrams(text: str, n: int = 5) -> set[tuple]:
    toks = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def similarity(script_text: str, source_text: str) -> tuple[float, list[str]]:
    """Porsi 5-gram naskah yang juga muncul di sumber (0–1) + contoh frasa yang sama."""
    a, b = _ngrams(script_text), _ngrams(source_text)
    if not a or not b:
        return 0.0, []
    same = a & b
    return len(same) / len(a), [" ".join(g) for g in list(same)[:6]]


SCRIPT_SYSTEM = """You are a senior scriptwriter for faceless YouTube Shorts and TikTok channels that earn
high CPM in the United States. You write ORIGINAL scripts: you may use a source video only as research on
the topic, never copy its sentences, structure or distinctive phrases. Answer ONLY with valid JSON."""

SCRIPT_PROMPT = """Write a new, original short video script.

Topic research (source video, for facts only; do NOT reuse its wording):
Title: {title}
Channel: {channel}
What is said:
\"\"\"{text}\"\"\"

Requirements:
- Language for narration, headings, title, description: {lang}. Audience: {audience}.
- Target length: about {seconds} seconds of narration (about {words} words in total).
- {scenes} scenes. Scene 1 is a hook of at most 12 words that creates curiosity.
- Use your own angle and structure. {angle}
- Every sentence must be in your own words. Add at least one useful insight that the source does not say.
- Do not invent precise statistics, quotes or names; when unsure, speak generally.
- Never claim to be the original creator, and do not mention the source channel.
- Narrator persona: {persona}
- End with a short call to action (follow / comment).

For every scene give:
"narration" (1–2 spoken sentences), "heading" (2–5 punchy words shown on screen),
"prompt" (one English sentence for an illustrator describing the image: setting, subject, action, mood{char_rule}),
"stock" (2–4 English keywords to search stock footage), "camera" (zoom_in|zoom_out|pan_left|pan_right|static),
"transition" (fade|slide|wipe|flip|iris|none).

Also give: "title" (max 70 characters, curiosity-driven, no clickbait lies), "description" (2–3 sentences plus a
call to action), "hashtags" (5 items without #), "mood" (one of: santai, semangat, inspiratif, dramatis, misteri, teknologi).

JSON: {{"title": "", "description": "", "hashtags": [], "mood": "", "scenes": [{{...}}]}}"""


def _llm(out_dir: Path, audience: str) -> LLMClient:
    try:
        cfg = Settings(source="-", out_dir=out_dir, audience=audience)
        cfg.resolve()
    except (ValueError, ClipAgentError) as exc:
        raise ClipAgentError(f"Menulis naskah butuh AI. Atur penyedia AI di Pengaturan ({exc}).")
    if cfg.provider == "heuristic":
        raise ClipAgentError("Menulis naskah butuh AI. Pilih penyedia AI di Pengaturan, atau pakai 'Tulis sendiri'.")
    return LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)


def new_project(out_dir: Path, source: str, settings: dict, blank: bool = False) -> dict:
    pid = uuid.uuid4().hex[:10]
    st = clean_settings(settings)
    src = (source or "").strip()
    proj = {"id": pid, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "settings": st,
            "source": {"url": src, "title": ""} if is_url(src) else {"url": "", "title": ""},
            "topic": "" if is_url(src) else src[:500], "script": {"title": "", "description": "", "hashtags": [],
                                                                  "mood": "santai", "scenes": []},
            "similarity": None, "renders": []}
    if blank:
        n = max(3, round(st["length"] / 6))
        proj["script"]["title"] = proj["topic"][:70]
        proj["script"]["scenes"] = [{"id": uuid.uuid4().hex[:6], "narration": "", "heading": "", "visual": "",
                                     "prompt": "", "stock": "", "camera": CAMERAS[i % 4], "transition": "fade"}
                                    for i in range(n)]
    return save(out_dir, proj)


def write_script(out_dir: Path, pid: str) -> dict:
    proj = load(out_dir, pid)
    st = proj["settings"]
    d = pdir(out_dir, pid)
    lang = "English" if st["audience"] == "us" else "Bahasa Indonesia"
    if proj["source"].get("url"):
        progress(0.08, "Mengambil teks video sumber")
        src = fetch_source_text(proj["source"]["url"], d, "en" if st["audience"] == "us" else "id")
        proj["source"] = {k: src.get(k) for k in ("url", "id", "title", "channel", "views", "duration", "text_source")}
        source_text = src.get("text") or ""
        title, channel = src.get("title", ""), src.get("channel", "")
        if not source_text:
            source_text = f"{src.get('title', '')}. {src.get('description', '')}"
    else:
        source_text, title, channel = proj["topic"], proj["topic"][:100], "-"
        if not source_text:
            raise ClipAgentError("Tempel link video viral atau tulis topiknya.")
    ch = characters.get(out_dir, st["character"]) if st.get("character") else None
    persona = (f"{ch['name']}, {ch.get('persona') or 'a friendly expert host'}" if ch
               else "a confident, friendly expert host speaking directly to the viewer")
    seconds = st["length"]
    words = int(seconds * (2.5 if st["audience"] == "us" else 2.2))
    n_scenes = max(3, min(24, round(seconds / 5)))
    client = _llm(out_dir, st["audience"])
    prompt = SCRIPT_PROMPT.format(
        title=title, channel=channel, text=source_text[:7000], lang=lang,
        audience="United States" if st["audience"] == "us" else "Indonesia", seconds=seconds, words=words,
        scenes=n_scenes, angle=f"Creator's angle/instructions: {st['angle']}." if st.get("angle") else "",
        persona=persona, char_rule=f"; the recurring character {ch['name']} appears in most scenes" if ch else "")
    best = None
    for attempt in range(3):
        check_cancel()
        progress(0.25 + 0.2 * attempt, "AI menulis naskah orisinal" if attempt == 0 else "Menulis ulang agar lebih orisinal")
        data = client.complete_json(SCRIPT_SYSTEM, prompt)
        scenes = clean_scenes(data.get("scenes"))
        if not scenes:
            log("Jawaban AI tidak berisi adegan; mencoba lagi.")
            continue
        text = " ".join(s["narration"] for s in scenes)
        sim, same = similarity(text, source_text) if proj["source"].get("url") else (0.0, [])
        cand = (sim, data, scenes)
        if best is None or sim < best[0]:
            best = cand
        log(f"Naskah {attempt + 1}: {len(scenes)} adegan, kemiripan dengan sumber {sim * 100:.1f}%.")
        if sim <= 0.08:
            break
        prompt += ("\n\nYour previous draft reused these phrases from the source: "
                   + "; ".join(f'"{x}"' for x in same) + ". Rewrite everything in completely new words.")
    if best is None:
        raise ClipAgentError("AI gagal menulis naskah. Coba lagi atau pakai 'Tulis sendiri'.")
    sim, data, scenes = best
    tags = [re.sub(r"[^\w]", "", str(t)) for t in (data.get("hashtags") or []) if str(t).strip()][:8]
    proj["script"] = {"title": str(data.get("title") or title)[:100], "description": str(data.get("description") or "")[:4000],
                      "hashtags": tags, "mood": data.get("mood") if data.get("mood") in music.MOODS else "santai",
                      "scenes": scenes}
    proj["similarity"] = round(sim, 3) if proj["source"].get("url") else None
    proj.pop("preview", None)
    save(out_dir, proj)
    progress(1.0, "Naskah siap")
    return proj


def update(out_dir: Path, pid: str, data: dict) -> dict:
    proj = load(out_dir, pid)
    if "settings" in data:
        proj["settings"] = clean_settings(data["settings"], proj["settings"])
    if "script" in data and isinstance(data["script"], dict):
        s = data["script"]
        sc = proj["script"]
        sc["title"] = str(s.get("title", sc.get("title", "")))[:100]
        sc["description"] = str(s.get("description", sc.get("description", "")))[:4000]
        if isinstance(s.get("hashtags"), list):
            sc["hashtags"] = [re.sub(r"[^\w]", "", str(t)) for t in s["hashtags"] if str(t).strip()][:10]
        if s.get("mood") in music.MOODS:
            sc["mood"] = s["mood"]
        if isinstance(s.get("scenes"), list):
            sc["scenes"] = [dict(x, narration=str(x.get("narration") or "")) for x in s["scenes"] if isinstance(x, dict)][:40]
    return save(out_dir, proj)


# ---------------------------------------------------------------- aset
def _dims(aspect: str) -> tuple[int, int]:
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def _ai_image(gen: ImageGen, ch: dict | None, refs: list, sc: dict, st: dict, adir: Path) -> Path:
    prompt = characters.scene_prompt(ch, sc["prompt"] or sc["heading"] or sc["narration"], st.get("art", "kartun3d"))
    import hashlib
    key = hashlib.sha1(f"{prompt}|{st['aspect']}|{gen.model}|{len(refs)}|{ch.get('id') if ch else ''}".encode()).hexdigest()[:14]
    p = adir / f"img_{key}.png"
    if not p.is_file():
        img = gen.generate(prompt, st["aspect"], refs=refs)
        cv2.imwrite(str(p), img)
    return p


def build_assets(out_dir: Path, pid: str, p0: float = 0.0, p1: float = 1.0) -> dict:
    """Narasi + visual + musik untuk semua adegan (di-cache). Menyimpan ringkasan di project['preview']."""
    proj = load(out_dir, pid)
    st, script = proj["settings"], proj["script"]
    scenes = clean_scenes(script.get("scenes"))
    if not scenes:
        raise ClipAgentError("Naskah masih kosong. Isi narasi minimal satu adegan.")
    d = pdir(out_dir, pid)
    adir = d / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    W, H = _dims(st["aspect"])
    ch = None
    if st.get("character"):
        try:
            ch = characters.get(out_dir, st["character"])
        except ClipAgentError:
            log("Karakter yang dipilih tidak ditemukan; adegan dibuat tanpa karakter.")
    refs = characters.references(out_dir, ch["id"]) if ch else []
    voice_engine = (ch or {}).get("voice_engine") or st["voice_engine"]
    voice = st.get("voice") or (ch or {}).get("voice") or ""
    style_hint = st.get("voice_style") or (ch or {}).get("style") or ""
    gen = ImageGen.from_env()
    n = len(scenes)
    span = p1 - p0

    # 1) narasi
    vo = []
    for i, sc in enumerate(scenes):
        check_cancel()
        progress(p0 + span * 0.35 * i / n, f"Suara narasi adegan {i + 1}/{n}")
        vo.append(tts.synthesize(sc["narration"], voice, voice_engine, style_hint, adir))

    # 2) visual
    used: set[int] = set()
    items = []
    paid = 0
    for i, (sc, v) in enumerate(zip(scenes, vo)):
        check_cancel()
        progress(p0 + span * (0.35 + 0.6 * i / n), f"Visual adegan {i + 1}/{n}")
        s0, e0 = v["speech"]
        dur = round(max(0.8, (e0 - max(0.0, s0 - 0.08)) + 0.3), 3)
        kind = sc["visual"] or st["visual"]
        if kind == "ai_video" and not st.get("allow_paid_video"):
            log(f"  Adegan {i + 1}: video AI belum diizinkan (centang izin biaya); memakai gambar AI.")
            kind = "ai_image"
        item = {"kind": kind, "dur": dur}
        try:
            if kind == "stock":
                got = broll.fetch(sc["stock"] or sc["heading"] or sc["narration"][:40], dur, st["aspect"], adir, used)
                if got:
                    fit = videogen.fit_clip(got["path"], dur, W, H, adir / f"fit_{got['path'].stem}_{int(dur * 10)}.mp4")
                    item.update(video=fit.name, credit=got["credit"])
                else:
                    if not broll.available():
                        log(f"  Adegan {i + 1}: PEXELS_API_KEY belum diisi.")
                    kind = "ai_image" if gen else "text"
                    item["kind"] = kind
            if kind in ("ai_image", "ai_video"):
                if gen is None:
                    log(f"  Adegan {i + 1}: gambar AI butuh GEMINI_API_KEY; memakai kartu teks.")
                    item["kind"] = kind = "text"
                else:
                    img_path = _ai_image(gen, ch, refs, sc, st, adir)
                    item["image"] = img_path.name
                    if kind == "ai_video":
                        clip = videogen.generate_clip(sc["prompt"] or sc["heading"], cv2.imread(str(img_path)),
                                                      st["aspect"], adir)
                        fit = videogen.fit_clip(clip, dur, W, H, adir / f"fit_{clip.stem}_{int(dur * 10)}.mp4")
                        item["video"] = fit.name
                        paid += 1
        except ClipAgentError as exc:
            log(f"  Adegan {i + 1}: visual gagal ({str(exc)[:160]}); memakai kartu teks.")
            item = {"kind": "text", "dur": dur}
        # gambar kecil untuk editor
        thumb = adir / f"thumb_{sc['id']}.jpg"
        src_img = None
        if item.get("image"):
            src_img = cv2.imread(str(adir / item["image"]))
        elif item.get("video"):
            cap = cv2.VideoCapture(str(adir / item["video"]))
            cap.set(cv2.CAP_PROP_POS_MSEC, 500)
            ok, fr = cap.read()
            cap.release()
            src_img = fr if ok else None
        if src_img is not None:
            h = 300
            cv2.imwrite(str(thumb), cv2.resize(src_img, (int(src_img.shape[1] * h / src_img.shape[0]), h)),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
            item["thumb"] = thumb.name
        item["audio"] = v["file"]
        item["speech"] = v["speech"]
        item["words"] = v["words"]
        item["vo_duration"] = v["duration"]
        items.append(item)
    total = round(sum(x["dur"] for x in items), 2)
    proj = load(out_dir, pid)
    proj["preview"] = {"scenes": [{"id": sc["id"], **{k: it.get(k) for k in ("kind", "dur", "thumb", "audio", "credit")}}
                                  for sc, it in zip(scenes, items)], "duration": total, "paid_videos": paid}
    save(out_dir, proj)
    progress(p1, "Aset siap")
    return {"scenes": scenes, "items": items, "duration": total, "character": ch}


def _narration(adir: Path, items: list[dict]) -> tuple[Path, list[dict], list[list[float]]]:
    """Gabungkan narasi tiap adegan (dipangkas jedanya) menjadi satu WAV; kembalikan kata & rentang suara."""
    parts, words, speech, t = [], [], [], 0.0
    for it in items:
        data, sr = tts.read_wav(adir / it["audio"])
        s0, _ = it["speech"]
        cut = max(0.0, s0 - 0.08)
        seg = data[int(cut * sr):]
        need = int(it["dur"] * sr)
        seg = seg[:need] if len(seg) >= need else np.concatenate([seg, np.zeros(need - len(seg), np.float32)])
        fade = min(len(seg), int(0.03 * sr))
        seg[-fade:] *= np.linspace(1, 0, fade)
        parts.append(seg)
        for w in it["words"]:
            ws, we = w["s"] - cut + t, w["e"] - cut + t
            if ws < t + it["dur"]:
                words.append({"s": round(max(t, ws), 3), "e": round(min(t + it["dur"], we), 3), "t": w["t"]})
        speech.append([round(t + max(0.0, s0 - cut), 3), round(t + it["dur"] - 0.25, 3)])
        t += it["dur"]
    full = np.concatenate(parts) if parts else np.zeros(1, np.float32)
    peak = float(np.abs(full).max() or 1.0)
    full = full * min(3.0, 0.89 / peak)
    out = adir / "narration.wav"
    tts.write_wav(out, full, 48000)
    return out, words, speech


def render(out_dir: Path, pid: str) -> dict:
    proj = load(out_dir, pid)
    st, script = proj["settings"], proj["script"]
    log(f"Membuat video '{script.get('title') or pid}'.")
    res = build_assets(out_dir, pid, 0.0, 0.55)
    items = res["items"]
    d = pdir(out_dir, pid)
    adir = d / "assets"
    W, H = _dims(st["aspect"])
    narration, words, speech = _narration(adir, items)
    total = round(sum(x["dur"] for x in items), 3)
    look = resolve_style({"preset": st.get("preset", "faceless")})
    style = dict(look["style"])
    if not st.get("captions", True):
        style["captions"] = "none"
    elif style["captions"] == "bubble":
        style["captions"] = "karaoke"
    mtrack = music.track(st.get("music", "auto"), total + 0.5, adir, script.get("mood", "santai"))
    with _AssetServer(out_dir) as srv:
        scenes, t = [], 0.0
        for sc, it in zip(res["scenes"], items):
            s = {"start": round(t, 3), "dur": it["dur"], "heading": sc["heading"], "bubble": "", "sfx": "",
                 "camera": sc["camera"] if not it.get("video") else "static", "transition": sc["transition"]}
            if it.get("video"):
                s["video"], s["videoFrom"] = srv.url(adir / it["video"]), 0
            elif it.get("image"):
                s["image"] = srv.url(adir / it["image"])
            scenes.append(s)
            t += it["dur"]
        props = {"fps": 30, "width": W, "height": H, "duration": total, "audio": srv.url(narration),
                 "audioParts": [{"at": 0, "from": 0, "to": total}], "scenes": scenes, "words": words,
                 "hook": script.get("title", "") if st.get("hook") else "", "progressBar": bool(st.get("progress_bar")),
                 "style": style, "speech": speech}
        if mtrack:
            props["music"] = {"src": srv.url(mtrack), "volume": float(st.get("music_volume", 0.35)), "duck": 0.28}
        name = f"video_{time.strftime('%Y%m%d_%H%M%S')}_{slugify(script.get('title') or 'video', 30)}.mp4"
        out = d / name
        tmp = d / (name + ".part.mp4")
        try:
            _run_remotion({"mode": "video", "props": props, "output": str(tmp.resolve()), "crf": 21},
                          0.55, 0.99, "Merender dengan Remotion")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    tmp.replace(out)
    credits = sorted({it["credit"] for it in items if it.get("credit")})
    proj = load(out_dir, pid)
    entry = {"file": name, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "duration": total,
             "scenes": len(items), "credits": credits, "ai_media": any(it["kind"] in ("ai_image", "ai_video") for it in items)}
    proj.setdefault("renders", []).append(entry)
    save(out_dir, proj)
    progress(1.0, "Video selesai")
    log(f"Selesai: {name} ({total:.1f} dtk).")
    return {**entry, "video_url": _url(out_dir, out)}
