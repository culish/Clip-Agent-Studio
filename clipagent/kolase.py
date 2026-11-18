"""Video Kolase: dari satu voice-over menjadi video explainer bergaya kolase editorial.

Alur:
1. Proyek baru dari file VO yang diunggah, atau dari narasi yang dibacakan suara AI (Gemini/Edge).
2. storyboard(): transkrip per kata (Whisper; suara AI sudah membawa waktu katanya), dipecah menjadi
   ketukan pendek, lalu AI (atau aturan sederhana bila AI tidak ada) memilih tata letak tiap adegan:
   foto guntingan, foto tempel, dokumen distabilo, peta, tipografi besar, angka, garis waktu,
   perbandingan, alur, kutipan. Angka, tahun, dan negara yang tampil di layar wajib benar-benar diucapkan.
3. Pengguna boleh mengubah tata letak dan teks tiap adegan.
4. render(): foto (gambar AI hitam-putih lalu digunting otomatis, atau foto stok Pexels), efek suara
   sintetis yang jatuh tepat pada animasinya, musik dengan ducking, render Remotion (komposisi "Kolase"),
   lalu dua file: versi final dan versi tanpa musik. Ada lembar tinjau dan ukuran loudness untuk QA.
Disimpan di <output>/_kolase/<id>/. Implementasi ini ditulis sendiri untuk Clip Agent.

Bagian akhir modul berisi adaptor untuk paket "Kolase Editorial" yang dibeli pengguna dan terpasang di
komputernya sendiri (KOLASE_PAKET_DIR). Isi paket tidak pernah disalin ke repo ini.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from . import broll, music, tts
from .animation import REMOTION_DIR, _AssetServer, _run_remotion
from .config import Settings
from .gemini import QuotaError
from .imagegen import ImageGen
from .llm import LLMClient
from .transcript import Word, group_segments, words_from_whisper
from .utils import ClipAgentError, check_cancel, log, progress, slugify

SR = 48000
RATIOS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
THEMES = {
    "koran": {"name": "Kertas koran", "paper": "#ECE5D3", "paper2": "#DCD2BC", "ink": "#161514", "accent": "#D12A1F",
              "marker": "#FFE14A", "dark": "#1C1B19"},
    "sepia": {"name": "Sepia", "paper": "#E9D6B4", "paper2": "#D8C097", "ink": "#2B1D12", "accent": "#A3361F",
              "marker": "#F6CB4C", "dark": "#2B1D12"},
    "biru": {"name": "Cetak biru", "paper": "#E4EBF0", "paper2": "#CBD8E2", "ink": "#0F1D2E", "accent": "#1E5BD8",
             "marker": "#9DE6FF", "dark": "#0F1D2E"},
    "hijau": {"name": "Hijau lumut", "paper": "#E5EADB", "paper2": "#CFD8BF", "ink": "#18261B", "accent": "#2E7A47",
              "marker": "#D4F26A", "dark": "#18261B"},
    "arsip": {"name": "Arsip", "paper": "#E6DDC8", "paper2": "#D3C7AB", "ink": "#22201C", "accent": "#9E2A2B",
              "marker": "#F2C94C", "dark": "#22201C"},
    "laut": {"name": "Laut", "paper": "#E1EBEC", "paper2": "#C6D8DC", "ink": "#0E2A33", "accent": "#0F7C8C",
             "marker": "#FFD166", "dark": "#0E2A33"},
    "hutan": {"name": "Hutan", "paper": "#E3E5D3", "paper2": "#CBD1B4", "ink": "#1C2A1E", "accent": "#4A6B2F",
              "marker": "#EBC95E", "dark": "#1C2A1E"},
    "jingga": {"name": "Jingga", "paper": "#F2E5D3", "paper2": "#E4CEB1", "ink": "#2A1A10", "accent": "#E0601A",
               "marker": "#FFE066", "dark": "#2A1A10"},
    "ungu": {"name": "Ungu", "paper": "#ECE5EF", "paper2": "#D8CDE1", "ink": "#24162E", "accent": "#6B3FA0",
             "marker": "#F9D65C", "dark": "#24162E"},
    "malam": {"name": "Malam", "paper": "#1D1D22", "paper2": "#2A2A31", "ink": "#F2EDE3", "accent": "#FF5B36",
              "marker": "#FFD43D", "dark": "#0E0E11"},
}
FONT_SETS = {
    "editorial": {"name": "Editorial (Playfair, Anton, Special Elite)", "sans": "Anton", "serif": "Playfair Display Black",
                  "italic": "Playfair Italic", "type": "Special Elite", "hand": "Permanent Marker", "caption": "Montserrat Black",
                  "wk": 1.0, "ts": 1.0, "hs": 1.0},
    "klasik": {"name": "Klasik (Fraunces, Archivo Black, Caveat)", "sans": "Archivo Black", "serif": "Fraunces Black",
               "italic": "Fraunces Italic", "type": "Special Elite", "hand": "Caveat Bold", "caption": "Plus Jakarta Sans",
               "wk": 1.42, "ts": 0.8, "hs": 1.3},
}
LAYOUTS = {"potong": "Foto guntingan", "foto": "Foto tempel", "dokumen": "Dokumen distabilo", "peta": "Peta",
           "judul": "Tipografi besar", "angka": "Angka besar", "garis_waktu": "Garis waktu", "banding": "Perbandingan",
           "alur": "Diagram alur", "kutipan": "Kutipan"}
PHOTO_LAYOUTS = ("potong", "foto")
IMAGE_SOURCES = {"ai": "Gambar AI (Gemini, berbayar)", "stok": "Foto stok (Pexels, gratis)",
                 "grafis": "Tanpa foto (grafis saja)"}
LANGS = {"id": "Indonesia", "en": "Inggris", "auto": "Deteksi otomatis"}
DEFAULTS = {"ratio": "9:16", "theme": "koran", "fonts": "editorial", "images": "stok", "language": "id", "captions": True,
            "music": "auto", "music_volume": 0.22, "sfx": True, "max_images": 12,
            "voice_engine": "edge", "voice": "id-ID-ArdiNeural", "voice_style": ""}
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".webm")
_STOP = set("""yang dan di ke dari ini itu untuk dengan pada adalah akan juga tidak ada atau karena jadi saat
sudah bisa lebih kita kami saya kamu mereka dia ia oleh dalam sebuah seperti hanya agar namun tapi tetapi
the a an and or but to of in on for with is are was were be been it this that you your we our they them he
she his her so just like what when where how why not do does did have has had can could would should will about
from at as by if then than there here""".split())


# ---------------------------------------------------------------- penyimpanan
def _root(out_dir: Path) -> Path:
    d = out_dir / "_kolase"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdir(out_dir: Path, pid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{10}", pid or ""):
        raise ClipAgentError("ID proyek kolase tidak valid.")
    return _root(out_dir) / pid


def load(out_dir: Path, pid: str) -> dict:
    p = pdir(out_dir, pid) / "project.json"
    if not p.is_file():
        raise ClipAgentError("Proyek kolase tidak ditemukan.")
    return json.loads(p.read_text(encoding="utf-8"))


def save(out_dir: Path, proj: dict) -> dict:
    proj["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d = pdir(out_dir, proj["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "project.json.tmp"
    tmp.write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(d / "project.json")
    return proj


def _url(out_dir: Path, p: Path) -> str:
    return f"/files/{p.resolve().relative_to(out_dir.resolve()).as_posix()}?v={int(p.stat().st_mtime)}"


def public(out_dir: Path, proj: dict) -> dict:
    d = pdir(out_dir, proj["id"])
    out = json.loads(json.dumps(proj))
    out.pop("words", None)
    vo = d / (proj.get("vo") or {}).get("file", "-")
    out["vo_url"] = _url(out_dir, vo) if vo.is_file() else ""
    for sc in out.get("scenes", []):
        a = sc.get("asset") or {}
        f = d / "assets" / a.get("file", "-")
        sc["asset_url"] = _url(out_dir, f) if a.get("file") and f.is_file() else ""
        sc["asset_source"] = a.get("source", "") if sc["asset_url"] else ""
        if sc.get("layout") in PHOTO_LAYOUTS:
            sc["prompt_ai"] = _prompt(sc)
        pv = d / "assets" / f"prev_{sc['id']}.jpg"
        sc["preview_url"] = _url(out_dir, pv) if sc.get("preview") == _scene_key(sc, proj["settings"]) and pv.is_file() else ""
    rends = []
    for r in out.get("renders", []):
        f = d / r["file"]
        if not f.is_file():
            continue
        r["video_url"] = _url(out_dir, f)
        r["path"] = f.resolve().relative_to(out_dir.resolve()).as_posix()
        r["files"] = {k: _url(out_dir, d / v) for k, v in (r.get("extra") or {}).items() if (d / v).is_file()}
        nm = d / r.get("nomusic", "-")
        r["nomusic_url"] = _url(out_dir, nm) if r.get("nomusic") and nm.is_file() else ""
        qa = d / r.get("sheet", "-")
        r["sheet_url"] = _url(out_dir, qa) if r.get("sheet") and qa.is_file() else ""
        rends.append(r)
    out["renders"] = rends[::-1]
    out["clips"] = [dict(c, video_url=_url(out_dir, d / c["file"])) for c in out.get("clips", []) if (d / c["file"]).is_file()][::-1]
    out["paket_status"] = paket_project_status(out_dir, proj)
    return out


def list_projects(out_dir: Path) -> list[dict]:
    items = []
    for p in _root(out_dir).glob("*/project.json"):
        try:
            pr = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        items.append({"id": pr["id"], "title": pr.get("title") or "Video kolase", "updated": pr.get("updated", ""),
                      "scenes": len(pr.get("scenes") or []), "renders": len(pr.get("renders") or []),
                      "duration": (pr.get("vo") or {}).get("duration", 0)})
    return sorted(items, key=lambda x: x["updated"], reverse=True)


def delete(out_dir: Path, pid: str) -> None:
    shutil.rmtree(pdir(out_dir, pid), ignore_errors=True)


def clean_settings(raw: dict, base: dict | None = None) -> dict:
    st = dict(base or DEFAULTS)
    raw = raw or {}
    for k, choices in (("ratio", RATIOS), ("theme", THEMES), ("fonts", FONT_SETS), ("images", IMAGE_SOURCES), ("language", LANGS),
                       ("voice_engine", ("gemini", "edge"))):
        if raw.get(k) in choices:
            st[k] = raw[k]
    for k in ("captions", "sfx"):
        if k in raw:
            st[k] = bool(raw[k])
    for k, n in (("music", 120), ("voice", 60), ("voice_style", 120)):
        if k in raw:
            st[k] = str(raw[k] or "").strip()[:n]
    try:
        st["music_volume"] = min(1.0, max(0.0, float(raw.get("music_volume", st["music_volume"]))))
        st["max_images"] = max(0, min(40, int(raw.get("max_images", st["max_images"]))))
    except (TypeError, ValueError):
        pass
    return st


def meta(out_dir: Path) -> dict:
    return {"ratios": list(RATIOS), "themes": {k: dict(v) for k, v in THEMES.items()}, "layouts": LAYOUTS,
            "fonts": {k: v["name"] for k, v in FONT_SETS.items()},
            "images": IMAGE_SOURCES, "languages": LANGS, "defaults": DEFAULTS, "music": music.choices(),
            "voices": {"gemini": tts.GEMINI_VOICES, "edge": tts.EDGE_VOICES}, "engines": tts.engines(),
            "keys": {"gemini": ImageGen.from_env() is not None, "pexels": broll.available()},
            "whisper": _has_whisper(), "paket": paket_status()}


def _has_whisper() -> bool:
    import importlib.util
    return importlib.util.find_spec("faster_whisper") is not None


# ---------------------------------------------------------------- audio
def _ffmpeg(args: list[str], what: str) -> None:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ClipAgentError(f"{what} gagal: {r.stderr.strip()[-300:]}")


def _decode(path: Path, sr: int = SR) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise ClipAgentError(f"Audio tidak bisa dibaca: {r.stderr.decode('utf-8', 'replace')[-200:]}")
    return np.frombuffer(r.stdout, np.float32).copy()


def _save_upload(d: Path, data_url: str, name: str) -> Path:
    m = re.match(r"data:[\w/.+-]*;base64,(.+)", data_url or "", re.S)
    if not m:
        raise ClipAgentError("File VO tidak valid. Pilih file audio (MP3, WAV, M4A).")
    raw = base64.b64decode(m.group(1))
    if len(raw) > 80_000_000:
        raise ClipAgentError("File VO terlalu besar (maks. 80 MB). Pakai MP3 atau M4A.")
    ext = Path(name or "vo.mp3").suffix.lower()
    if ext not in AUDIO_EXT:
        ext = ".mp3"
    src = d / f"vo_asli{ext}"
    src.write_bytes(raw)
    return src


def _vo_from_file(d: Path, src: Path) -> float:
    """Ubah VO ke WAV 48 kHz mono. Mengembalikan durasi."""
    _ffmpeg(["-i", str(src), "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(d / "vo.wav")], "Membaca VO")
    data = _decode(d / "vo.wav")
    if len(data) < SR * 1.5:
        raise ClipAgentError("VO terlalu pendek (minimal 1,5 detik).")
    if np.abs(data).max() < 0.01:
        raise ClipAgentError("VO tidak berisi suara (hening).")
    return round(len(data) / SR, 3)


def _split_text(text: str, limit: int = 280) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip())
    out, cur = [], ""
    for s in sents:
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def _vo_from_text(d: Path, text: str, st: dict) -> tuple[float, list[dict]]:
    """Narasi dibacakan suara AI per potongan, lalu digabung. Waktu kata ikut disusun."""
    parts, words, t = [], [], 0.0
    chunks = _split_text(text)
    gap = np.zeros(int(0.22 * SR), np.float32)
    for i, chunk in enumerate(chunks):
        check_cancel()
        progress(0.04 + 0.3 * i / len(chunks), f"Suara narasi {i + 1}/{len(chunks)}")
        meta_ = tts.synthesize(chunk, st.get("voice", ""), st.get("voice_engine", "edge"), st.get("voice_style", ""),
                               d / "tts")
        data, sr = tts.read_wav(d / "tts" / meta_["file"])
        s0, e0 = meta_["speech"]
        a, b = max(0, int((s0 - 0.06) * sr)), min(len(data), int((e0 + 0.12) * sr))
        seg = data[a:b]
        for w in meta_["words"]:
            ws, we = w["s"] - a / sr, w["e"] - a / sr
            if we > 0 and ws < len(seg) / sr:
                words.append({"s": round(t + max(0.0, ws), 3), "e": round(t + min(len(seg) / sr, we), 3), "t": w["t"]})
        parts += [seg, gap]
        t += len(seg) / sr + len(gap) / sr
    full = np.concatenate(parts[:-1]) if parts else np.zeros(SR, np.float32)
    tts.write_wav(d / "vo.wav", full * min(3.0, 0.89 / float(np.abs(full).max() or 1)), SR)
    return round(len(full) / SR, 3), words


def new_project(out_dir: Path, body: dict) -> dict:
    pid = uuid.uuid4().hex[:10]
    d = pdir(out_dir, pid)
    d.mkdir(parents=True, exist_ok=True)
    st = clean_settings(body.get("settings") or {})
    text = re.sub(r"\s+", " ", str(body.get("text") or "")).strip()[:6000]
    proj = {"id": pid, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "title": str(body.get("title") or "").strip()[:100],
            "settings": st, "vo": {}, "text": text, "words": [], "scenes": [], "renders": []}
    try:
        if body.get("audio"):
            src = _save_upload(d, str(body["audio"]), str(body.get("audio_name") or ""))
            proj["vo"] = {"file": "vo.wav", "source": "upload", "original": src.name, "duration": _vo_from_file(d, src)}
        elif not text:
            raise ClipAgentError("Unggah file VO, atau tulis narasinya untuk dibacakan suara AI.")
        else:
            tts.pick_engine(st["voice_engine"])
            proj["vo"] = {"source": "tts", "duration": 0}
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    if not proj["title"]:
        proj["title"] = (text[:60] + "…") if len(text) > 60 else (text or "Video kolase")
    return save(out_dir, proj)


# ---------------------------------------------------------------- storyboard
SB_SYSTEM = """You are the art director of an editorial collage explainer channel. You turn a narrated voice-over
into a sequence of collage scenes: cut-out archival photos, taped prints, typed documents with highlighter marks,
maps, big kinetic typography, counters, timelines, comparisons and simple flow diagrams. Every visual must explain
or reinforce exactly what the narrator says at that moment. Answer ONLY with valid JSON."""

SB_PROMPT = """Voice-over beats (index, start-end seconds, text):
{beats}

On-screen language: {lang}. Aspect ratio: {ratio}. {photo_rule}

Group consecutive beats into scenes: each scene has 1-3 beats and lasts about 2-6 seconds. Never skip or reorder
beats; the scenes together cover every beat exactly once. For each scene choose the layout that explains it best:
- "potong": one cut-out photo subject (a type of person, an object, a building, an animal). Needs "image".
- "foto": a taped documentary photo of a place or situation. Needs "image".
- "dokumen": the spoken words are typed on a document page and the key phrase is highlighted.
- "peta": a map highlighting up to 3 countries named in the narration. Needs "places" (English country names).
- "judul": big kinetic typography of the core idea in "heading".
- "angka": a number SPOKEN in these beats, shown big and counting up. Needs "number" written exactly as spoken and a short "label".
- "garis_waktu": 2-4 years SPOKEN in the narration, each with a 1-4 word label: "items": [{{"t": "1998", "label": "..."}}].
- "banding": a contrast between two things said in the narration: "items" with exactly 2 entries [{{"t": "...", "label": "..."}}].
- "alur": a cause-and-effect chain or steps said in the narration, 2-4 short steps in "items".
- "kutipan": a striking sentence from the narration as a pull quote; put its exact words in "quote".
Rules:
- Use only facts, numbers, years and names that are in the narration. Never invent statistics, dates, names or quotes.
- Vary the layouts and never use the same layout three times in a row. Open with a strong visual.
- "heading": 2-6 punchy words in {lang} for every scene.
- "keyword": one word or a short phrase literally spoken in that scene; it is highlighted when it is said.
- "image": one English sentence describing a single photo subject. No text in the image, no famous real people;
  describe people by role (e.g. "a street vendor counting coins").
- "search": 2-4 English keywords to find a stock photo of the same subject.
Also return "title" (max 70 characters, in {lang}) and "mood" (one of: {moods}).
JSON: {{"title": "", "mood": "", "scenes": [{{"beats": [0, 1], "layout": "", "heading": "", "keyword": "", "image": "",
"search": "", "places": [], "number": "", "label": "", "items": [], "quote": ""}}]}}"""


def _norm(w: str) -> str:
    return re.sub(r"[^\w]+", "", (w or "").lower())


def _beats(words: list[dict]) -> list[dict]:
    ws = [Word(w["s"], w["e"], w["t"]) for w in words]
    segs = group_segments(ws, max_gap=0.6, max_len=4.2, max_chars=90)
    return [{"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text} for s in segs if s.text.strip()]


def _llm(out_dir: Path) -> LLMClient | None:
    try:
        cfg = Settings(source="-", out_dir=out_dir)
        cfg.resolve()
    except (ValueError, ClipAgentError):
        return None
    if cfg.provider == "heuristic":
        return None
    return LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W\d_][\w'-]{2,}", text) if w.lower() not in _STOP]


_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
_NUM = re.compile(r"\d[\d.,]*\d|\d")


def _heuristic(beats: list[dict], photos: bool) -> list[dict]:
    groups, cur = [], []
    for i, b in enumerate(beats):
        cur.append(i)
        if beats[cur[-1]]["end"] - beats[cur[0]]["start"] >= 3.2 or len(cur) == 2:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    cycle = ["potong", "dokumen", "judul", "foto", "kutipan", "judul"] if photos else ["judul", "dokumen", "kutipan", "judul"]
    out = []
    for k, g in enumerate(groups):
        text = " ".join(beats[i]["text"] for i in g)
        cw = _content_words(text)
        years = sorted(set(_YEAR.findall(text)))
        nums = [n for n in _NUM.findall(text) if not _YEAR.fullmatch(n)]
        first = re.sub(r"[^\w\s-]", "", beats[g[0]]["text"]).split()
        sc = {"beats": [g[0], g[-1]], "heading": " ".join(first[:5]), "keyword": max(cw, key=len) if cw else "",
              "image": text[:160], "search": " ".join(sorted(cw, key=len, reverse=True)[:2])}
        if len(years) >= 2:
            sc.update(layout="garis_waktu", items=[{"t": y, "label": ""} for y in years[:4]])
        elif nums:
            sc.update(layout="angka", number=nums[0], label=" ".join(cw[:3]))
        else:
            sc["layout"] = cycle[k % len(cycle)]
            if sc["layout"] == "kutipan":
                sc["quote"] = text
        out.append(sc)
    return out


def _country_names() -> dict[str, str]:
    p = REMOTION_DIR / "node_modules" / "world-atlas" / "countries-50m.json"
    try:
        geo = json.loads(p.read_text(encoding="utf-8"))
        names = [g["properties"]["name"] for g in geo["objects"]["countries"]["geometries"] if g.get("properties")]
    except (OSError, ValueError, KeyError):
        return {}
    table = {n.lower(): n for n in names}
    aliases = {"usa": "United States of America", "united states": "United States of America", "us": "United States of America",
               "amerika serikat": "United States of America", "america": "United States of America",
               "uk": "United Kingdom", "britain": "United Kingdom", "great britain": "United Kingdom", "inggris": "United Kingdom",
               "england": "United Kingdom", "south korea": "South Korea", "korea selatan": "South Korea",
               "north korea": "North Korea", "korea utara": "North Korea", "czech republic": "Czechia",
               "democratic republic of the congo": "Dem. Rep. Congo", "drc": "Dem. Rep. Congo",
               "timor-leste": "Timor-Leste", "east timor": "Timor-Leste", "timor leste": "Timor-Leste",
               "jepang": "Japan", "tiongkok": "China", "cina": "China", "belanda": "Netherlands", "jerman": "Germany",
               "prancis": "France", "perancis": "France", "rusia": "Russia", "arab saudi": "Saudi Arabia",
               "malaysia": "Malaysia", "singapura": "Singapore", "filipina": "Philippines", "mesir": "Egypt",
               "turki": "Turkey", "italia": "Italy", "spanyol": "Spain", "brasil": "Brazil", "meksiko": "Mexico",
               "kanada": "Canada", "selandia baru": "New Zealand", "afrika selatan": "South Africa",
               "ivory coast": "Côte d'Ivoire", "uae": "United Arab Emirates", "uni emirat arab": "United Arab Emirates"}
    for k, v in aliases.items():
        if v.lower() in table:
            table[k] = table[v.lower()]
    return table


def _match_places(raw, table: dict) -> list[str]:
    out = []
    for p in (raw if isinstance(raw, list) else [raw]):
        n = table.get(str(p or "").strip().lower())
        if n and n not in out:
            out.append(n)
    return out[:3]


def _clean_items(raw, n_max: int) -> list[dict]:
    out = []
    for it in raw if isinstance(raw, list) else []:
        if isinstance(it, str):
            it = {"t": it}
        if not isinstance(it, dict):
            continue
        t = str(it.get("t") or it.get("text") or "").strip()[:40]
        if t:
            out.append({"t": t, "label": str(it.get("label") or "").strip()[:48]})
    return out[:n_max]


def validate_scenes(raw: list, beats: list[dict], total: float, photos: bool, table: dict) -> list[dict]:
    """Rapikan rencana AI/pengguna: cakupan ketukan, tata letak, dan fakta yang tampil harus diucapkan."""
    if not beats:
        return []
    full_text = " ".join(b["text"] for b in beats)
    claimed: list[tuple[int, int, dict]] = []
    nxt = 0
    for sc in raw or []:
        if not isinstance(sc, dict):
            continue
        try:
            a, b = [int(x) for x in (sc.get("beats") or [])[:2]] + [None] * (2 - len((sc.get("beats") or [])[:2]))
        except (TypeError, ValueError):
            continue
        b = a if b is None else b
        if a is None or a != nxt or b < a or b >= len(beats):
            if a is not None and a > nxt:              # ketukan terlewat: sisipkan adegan judul
                claimed.append((nxt, a - 1, {"layout": "judul"}))
                nxt = a
                if b < a or b >= len(beats):
                    continue
            else:
                continue
        claimed.append((a, b, sc))
        nxt = b + 1
    if nxt < len(beats):
        claimed.append((nxt, len(beats) - 1, {"layout": "judul"}))
    # gabung adegan yang terlalu pendek (< 1,3 detik) ke adegan sebelumnya
    merged: list[tuple[int, int, dict]] = []
    for a, b, sc in claimed:
        dur = beats[b]["end"] - beats[a]["start"]
        if merged and dur < 1.3:
            pa, _, psc = merged[-1]
            merged[-1] = (pa, b, psc)
        else:
            merged.append((a, b, sc))
    out = []
    for k, (a, b, sc) in enumerate(merged):
        text = " ".join(beats[i]["text"] for i in range(a, b + 1))
        cw = _content_words(text)
        layout = sc.get("layout") if sc.get("layout") in LAYOUTS else "judul"
        if layout in PHOTO_LAYOUTS and not photos and (sc.get("asset") or {}).get("source") != "unggah":
            layout = "judul"
        heading = re.sub(r"\s+", " ", str(sc.get("heading") or "")).strip()[:60] or " ".join(cw[:4])[:60]
        kw = str(sc.get("keyword") or "").strip()[:40]
        if not kw or _norm(kw.split()[0]) not in {_norm(x) for x in text.split()}:
            kw = max(cw, key=len) if cw else ""
        item = {"id": str(sc.get("id") or uuid.uuid4().hex[:6])[:12], "beats": [a, b], "layout": layout,
                "heading": heading, "keyword": kw, "text": text,
                "image": str(sc.get("image") or "").strip()[:300], "search": str(sc.get("search") or "").strip()[:80],
                "places": [], "number": "", "label": str(sc.get("label") or "").strip()[:60], "items": [], "quote": ""}
        if layout == "peta":
            item["places"] = _match_places(sc.get("places") or [], table)
            if not item["places"]:
                layout = "judul"
        if layout == "angka":
            num = str(sc.get("number") or "").strip()[:30]
            m = _NUM.search(num)
            digits = re.sub(r"\D", "", m.group(0)) if m else ""
            if digits and digits in re.sub(r"\D", "", text):
                item["number"] = num
            else:
                layout = "judul"
        if layout == "garis_waktu":
            items = [it for it in _clean_items(sc.get("items"), 4) if _YEAR.fullmatch(it["t"]) and it["t"] in full_text]
            if len(items) >= 2:
                item["items"] = items
            else:
                layout = "judul"
        if layout in ("banding", "alur"):
            items = _clean_items(sc.get("items"), 2 if layout == "banding" else 4)
            if len(items) >= 2:
                item["items"] = items
            else:
                layout = "judul"
        if layout == "kutipan":
            q = re.sub(r"\s+", " ", str(sc.get("quote") or "")).strip().strip('"“”')
            item["quote"] = q if q and _norm(q)[:40] in _norm(text) else text
            if len(item["quote"].split()) > 26:
                item["quote"] = " ".join(item["quote"].split()[:26]) + "…"
        if layout in PHOTO_LAYOUTS and not item["image"]:
            item["image"] = text[:200]
        if layout in PHOTO_LAYOUTS and not item["search"]:
            item["search"] = " ".join(cw[:2])
        item["layout"] = layout
        out.append(item)
    # jangan tiga kali berturut-turut tata letak yang sama
    for i in range(2, len(out)):
        if out[i]["layout"] == out[i - 1]["layout"] == out[i - 2]["layout"]:
            alt = "dokumen" if out[i]["layout"] != "dokumen" else "judul"
            out[i]["layout"] = alt
    _time_scenes(out, beats, total)
    return out


def _time_scenes(scenes: list[dict], beats: list[dict], total: float) -> None:
    for i, sc in enumerate(scenes):
        a, b = sc["beats"]
        sc["start"] = 0.0 if i == 0 else round(beats[a]["start"] - 0.12, 3)
        sc["end"] = round(total, 3)
        if i:
            scenes[i - 1]["end"] = sc["start"]


def storyboard(out_dir: Path, pid: str) -> dict:
    proj = load(out_dir, pid)
    st = proj["settings"]
    d = pdir(out_dir, pid)
    if proj["vo"].get("source") == "tts" and not (d / "vo.wav").is_file():
        dur, words = _vo_from_text(d, proj["text"], st)
        proj["vo"].update(file="vo.wav", duration=dur)
        proj["words"] = words
        save(out_dir, proj)
    if not proj.get("words"):
        progress(0.05, "Transkrip per kata (Whisper)")
        lang = None if st["language"] == "auto" else st["language"]
        ws, detected = words_from_whisper(d / "vo.wav", os.getenv("KOLASE_WHISPER_MODEL") or "small", lang, (0.05, 0.5))
        if not ws:
            raise ClipAgentError("Whisper tidak menemukan ucapan di VO.")
        proj["words"] = [{"s": round(w.start, 3), "e": round(w.end, 3), "t": w.text} for w in ws]
        if st["language"] == "auto":
            proj["detected_language"] = detected
        save(out_dir, proj)
    words = proj["words"]
    beats = _beats(words)
    total = proj["vo"]["duration"]
    photos = st["images"] != "grafis"
    lang_code = st["language"] if st["language"] != "auto" else proj.get("detected_language", "en")
    lang = "Bahasa Indonesia" if lang_code == "id" else "English" if lang_code == "en" else f"the narration language ({lang_code})"
    table = _country_names()
    raw, title, mood = None, "", "santai"
    client = _llm(out_dir)
    if client:
        progress(0.55, "AI menyusun storyboard kolase")
        lines = "\n".join(f"[{i}] {b['start']:.1f}-{b['end']:.1f}: {b['text']}" for i, b in enumerate(beats))
        photo_rule = ("Photos are available: use potong or foto for about a third of the scenes." if photos else
                      "No photos are available: do NOT use potong or foto.")
        try:
            data = client.complete_json(SB_SYSTEM, SB_PROMPT.format(beats=lines, lang=lang, ratio=st["ratio"],
                                                                     photo_rule=photo_rule, moods=", ".join(music.MOODS)))
            raw, title = data.get("scenes"), str(data.get("title") or "")[:100]
            mood = data.get("mood") if data.get("mood") in music.MOODS else "santai"
        except (ClipAgentError, ValueError) as exc:
            log(f"AI storyboard tidak tersedia ({str(exc).splitlines()[0][:120]}); memakai aturan sederhana.")
    else:
        log("Penyedia AI belum diatur; storyboard dibuat dengan aturan sederhana. Atur AI di Pengaturan untuk hasil lebih kaya.")
    scenes = validate_scenes(raw, beats, total, photos, table) if raw else []
    if len(scenes) < max(1, len(beats) // 4):
        scenes = validate_scenes(_heuristic(beats, photos), beats, total, photos, table)
    proj = load(out_dir, pid)
    proj.update(beats=beats, scenes=scenes, mood=mood)
    if title and (not proj.get("title") or proj["title"] == "Video kolase" or proj["vo"].get("source") == "upload"):
        proj["title"] = title
    save(out_dir, proj)
    counts = {}
    for sc in scenes:
        counts[LAYOUTS[sc["layout"]]] = counts.get(LAYOUTS[sc["layout"]], 0) + 1
    log(f"Storyboard: {len(scenes)} adegan dari {len(beats)} ketukan ({', '.join(f'{v} {k}' for k, v in counts.items())}).")
    progress(1.0, "Storyboard siap")
    return proj


def update(out_dir: Path, pid: str, body: dict) -> dict:
    proj = load(out_dir, pid)
    if "settings" in body:
        proj["settings"] = clean_settings(body["settings"], proj["settings"])
    if "title" in body:
        proj["title"] = str(body["title"] or "").strip()[:100]
    if isinstance(body.get("scenes"), list) and proj.get("beats"):
        old = {s["id"]: s for s in proj.get("scenes", [])}
        raw = []
        for s in body["scenes"]:
            if isinstance(s, dict) and s.get("id") in old:
                base = dict(old[s["id"]])
                for k in ("layout", "heading", "keyword", "image", "search", "places", "number", "label", "items", "quote"):
                    if k in s:
                        base[k] = s[k]
                upl = (base.get("asset") or {}).get("source") == "unggah"
                if upl and base.get("layout") in PHOTO_LAYOUTS:
                    pass                                  # foto unggahan tetap dipakai
                elif base.get("layout") != old[s["id"]].get("layout") or base.get("image") != old[s["id"]].get("image") \
                        or base.get("search") != old[s["id"]].get("search"):
                    base.pop("asset", None)
                raw.append(base)
        assets = {s["id"]: s.get("asset") for s in raw if s.get("asset")}
        wanted = {s["id"]: s.get("layout") for s in raw}
        scenes = validate_scenes(raw, proj["beats"], proj["vo"]["duration"], proj["settings"]["images"] != "grafis",
                                 _country_names())
        notices = []
        for i, s in enumerate(scenes):
            if s["id"] in assets:
                s["asset"] = assets[s["id"]]
            w = wanted.get(s["id"])
            if w in LAYOUTS and w != s["layout"]:
                why = {"angka": "angkanya harus diucapkan di adegan itu", "garis_waktu": "butuh minimal 2 tahun yang diucapkan di VO",
                       "peta": "nama negara tidak dikenali (pakai nama bahasa Inggris)", "banding": "isi 2 baris",
                       "alur": "isi 2–4 baris", "potong": "sumber foto diatur 'Tanpa foto'", "foto": "sumber foto diatur 'Tanpa foto'"}
                notices.append(f"Adegan {i + 1}: {LAYOUTS[w]} diganti {LAYOUTS[s['layout']]} ({why.get(w, 'isinya belum lengkap')}).")
        proj["scenes"] = scenes
        proj = save(out_dir, proj)
        return dict(proj, notices=notices)
    return save(out_dir, proj)


# ---------------------------------------------------------------- gambar
def _cutout(img: np.ndarray) -> np.ndarray | None:
    """Gunting subjek dari latar putih polos. Hasil BGRA dengan pinggiran stiker putih, atau None bila gagal."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    light = ((gray > 226) & (hsv[..., 1] < 40)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(light, 4)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(edge)) if edge else np.zeros_like(light, bool)
    fg = (~bg).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k, iterations=2)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n <= 1:
        return None
    big = stats[1:, cv2.CC_STAT_AREA].max()
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= big * 0.04]
    fg = np.isin(lab, keep).astype(np.uint8)
    frac = fg.mean()
    if not 0.06 <= frac <= 0.88:
        return None
    # isi lubang kecil di dalam subjek
    inv = (1 - fg).astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(inv, 4)
    edge2 = set(np.unique(np.concatenate([lab2[0], lab2[-1], lab2[:, 0], lab2[:, -1]])))
    for i in range(1, n2):
        if i not in edge2 and st2[i, cv2.CC_STAT_AREA] < h * w * 0.01:
            fg[lab2 == i] = 1
    r = max(6, int(0.014 * max(h, w)))
    pad = r + 4
    fgp = cv2.copyMakeBorder(fg, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    imgp = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    dist = cv2.distanceTransform((1 - fgp).astype(np.uint8), cv2.DIST_L2, 5)
    rng = np.random.default_rng(int(fg.sum()) % 9973)
    noise = cv2.resize(rng.random((max(2, fgp.shape[0] // 40), max(2, fgp.shape[1] // 40))).astype(np.float32),
                       (fgp.shape[1], fgp.shape[0]), interpolation=cv2.INTER_CUBIC)
    border = (dist <= r * (0.75 + 0.5 * noise)).astype(np.float32)
    alpha = cv2.GaussianBlur(border, (0, 0), 0.9)
    soft = cv2.GaussianBlur(fgp.astype(np.float32), (0, 0), 0.8)
    rgb = imgp.astype(np.float32) * soft[..., None] + 255.0 * (1 - soft[..., None])
    out = np.dstack([rgb.clip(0, 255).astype(np.uint8), (alpha * 255).clip(0, 255).astype(np.uint8)])
    ys, xs = np.where(alpha > 0.02)
    return out[max(0, ys.min() - 2):ys.max() + 3, max(0, xs.min() - 2):xs.max() + 3]


def _pexels_photo(query: str, portrait: bool, adir: Path, used: set) -> dict | None:
    import requests
    if not broll.available() or not query.strip():
        return None
    tag = hashlib.sha1(f"photo|{query}|{portrait}".encode()).hexdigest()[:10]
    listing = adir / f"pexels_photo_{tag}.json"
    try:
        if listing.is_file():
            photos = json.loads(listing.read_text(encoding="utf-8"))
        else:
            r = requests.get(f"{broll._base()}/v1/search", headers={"Authorization": broll.api_key()},
                             params={"query": query, "orientation": "portrait" if portrait else "landscape",
                                     "per_page": 8}, timeout=30)
            if not r.ok:
                raise ClipAgentError(f"Pexels foto HTTP {r.status_code}")
            photos = r.json().get("photos") or []
            listing.write_text(json.dumps(photos), encoding="utf-8")
        for ph in photos:
            if ph.get("id") in used:
                continue
            src = (ph.get("src") or {}).get("large2x") or (ph.get("src") or {}).get("large")
            if not src:
                continue
            p = adir / f"pexels_{ph['id']}.jpg"
            if not p.is_file():
                rr = requests.get(src, timeout=60)
                if not rr.ok:
                    continue
                p.write_bytes(rr.content)
            used.add(ph.get("id"))
            return {"path": p, "credit": f"Photo: {ph.get('photographer', 'Pexels')} / Pexels"}
    except (requests.RequestException, ClipAgentError, ValueError) as exc:
        log(f"  Pexels foto: {str(exc)[:120]}")
    return None


def _prompt(sc: dict) -> str:
    subject = sc["image"] or sc["heading"]
    if sc["layout"] == "potong":
        return (f"Archival black-and-white photograph of {subject}. A single subject, isolated on a plain pure white "
                "background, centered, the whole subject visible with space around it, sharp focus, high contrast, "
                "subtle film grain. A real photograph, not an illustration. No text, no letters, no logos, no watermark.")
    return (f"Archival black-and-white documentary photograph: {subject}. Natural composition, film grain, high "
            "contrast, soft vignette. A real photograph, not an illustration. No text, no letters, no logos, no watermark.")


def _scene_images(proj: dict, d: Path, p0: float, p1: float) -> None:
    st = proj["settings"]
    adir = d / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    gen = ImageGen.from_env() if st["images"] == "ai" else None
    if st["images"] == "ai" and gen is None:
        log("GEMINI_API_KEY belum diisi; foto memakai stok Pexels." if broll.available() else
            "GEMINI_API_KEY dan PEXELS_API_KEY belum diisi; adegan foto diganti tipografi.")
    portrait = st["ratio"] in ("9:16", "4:5")
    need = [sc for sc in proj["scenes"] if sc["layout"] in PHOTO_LAYOUTS]
    used: set = set()
    made = 0
    for k, sc in enumerate(need):
        check_cancel()
        progress(p0 + (p1 - p0) * k / max(1, len(need)), f"Foto adegan {k + 1}/{len(need)}")
        a = sc.get("asset") or {}
        if a.get("source") == "unggah" and (adir / a.get("orig", "-")).is_file():
            if a.get("layout") != sc["layout"] or not (adir / a.get("file", "-")).is_file():
                _store_photo(sc, adir, cv2.imread(str(adir / a["orig"])), "unggah", "", a["orig"])
            continue                                      # foto unggahan pengguna tidak pernah diganti
        if a.get("file") and (adir / a["file"]).is_file() and a.get("layout") == sc["layout"]:
            continue
        sc.pop("asset", None)
        img, credit, src = None, "", ""
        if gen is not None and made < st["max_images"]:
            key = hashlib.sha1(f"{_prompt(sc)}|{gen.model}".encode()).hexdigest()[:14]
            raw = adir / f"ai_{key}.png"
            try:
                if not raw.is_file():
                    cv2.imwrite(str(raw), gen.generate(_prompt(sc), "3:4" if sc["layout"] == "potong" else
                                                       ("4:5" if portrait else "3:2")))
                    made += 1
                img, src = cv2.imread(str(raw)), "ai"
            except QuotaError as exc:
                log(f"  {exc} Foto berikutnya memakai stok Pexels." if broll.available() else f"  {exc}")
                gen = None
            except ClipAgentError as exc:
                log(f"  Adegan {sc['id']}: gambar AI gagal ({str(exc)[:140]}).")
        if img is None:
            got = _pexels_photo(sc["search"] or sc["heading"], portrait, adir, used)
            if got:
                img, credit, src = cv2.imread(str(got["path"])), got["credit"], "stok"
        if img is None:
            log(f"  Adegan '{sc['heading']}': foto tidak tersedia; diganti tipografi besar. "
                "Bisa juga unggah foto sendiri di adegan itu.")
            sc["layout"] = "judul"
            continue
        _store_photo(sc, adir, img, src, credit)


def _store_photo(sc: dict, adir: Path, img: np.ndarray, src: str, credit: str, orig: str = "") -> None:
    """Simpan foto adegan. Untuk 'potong', subjek digunting dari latar putih; bila gagal, jadi foto tempel."""
    cut = _cutout(img) if sc["layout"] == "potong" and src in ("ai", "unggah") else None
    if sc["layout"] == "potong" and cut is None:
        sc["layout"] = "foto"                             # latar ramai: jadi foto tempel
    h, w = img.shape[:2]
    scale = min(1.0, 1600 / max(h, w))
    if cut is not None:
        cut = cv2.resize(cut, (int(cut.shape[1] * scale), int(cut.shape[0] * scale)), interpolation=cv2.INTER_AREA) \
            if scale < 1 else cut
        name = f"cut_{sc['id']}_{hashlib.sha1(cut.tobytes()[:4096]).hexdigest()[:6]}.png"
        cv2.imwrite(str(adir / name), cut)
    else:
        im = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img
        name = f"foto_{sc['id']}_{hashlib.sha1(im.tobytes()[:4096]).hexdigest()[:6]}.jpg"
        cv2.imwrite(str(adir / name), im, [cv2.IMWRITE_JPEG_QUALITY, 90])
    sc["asset"] = {"file": name, "cutout": cut is not None, "credit": credit, "source": src, "layout": sc["layout"]}
    if orig:
        sc["asset"]["orig"] = orig


def set_scene_photo(out_dir: Path, pid: str, scene_id: str, data_url: str = "", remove: bool = False) -> dict:
    """Foto adegan dari generator apa pun (Google Flow, ChatGPT, Midjourney) atau kamera pengguna."""
    proj = load(out_dir, pid)
    sc = next((x for x in proj.get("scenes", []) if x["id"] == scene_id), None)
    if not sc:
        raise ClipAgentError("Adegan tidak ditemukan.")
    adir = pdir(out_dir, pid) / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    notice = ""
    if remove:
        if (sc.get("asset") or {}).get("source") == "unggah":
            sc.pop("asset", None)
    else:
        if sc["layout"] not in PHOTO_LAYOUTS:
            raise ClipAgentError("Ubah tata letak adegan ini ke Foto guntingan atau Foto tempel dulu.")
        m = re.match(r"data:image/[\w.+-]+;base64,(.+)", data_url or "", re.S)
        if not m:
            raise ClipAgentError("File gambar tidak valid. Pakai JPG, PNG, atau WEBP.")
        raw = base64.b64decode(m.group(1))
        if len(raw) > 20_000_000:
            raise ClipAgentError("Gambar terlalu besar (maks. 20 MB).")
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ClipAgentError("Gambar tidak bisa dibaca. Pakai JPG atau PNG.")
        h, w = img.shape[:2]
        sc_ = min(1.0, 2400 / max(h, w))
        if sc_ < 1:
            img = cv2.resize(img, (int(w * sc_), int(h * sc_)), interpolation=cv2.INTER_AREA)
        orig = f"unggah_{sc['id']}_{hashlib.sha1(raw[:65536]).hexdigest()[:8]}.png"
        cv2.imwrite(str(adir / orig), img)
        wanted = sc["layout"]
        _store_photo(sc, adir, img, "unggah", "", orig)
        if wanted == "potong" and sc["layout"] == "foto":
            notice = ("Latar foto tidak putih polos, jadi subjek tidak bisa digunting; adegan dipakai sebagai foto tempel. "
                      "Untuk foto guntingan, buat gambar dengan latar putih polos.")
    sc.pop("preview", None)
    save(out_dir, proj)
    return dict(public(out_dir, proj), notices=[notice] if notice else [])


# ---------------------------------------------------------------- isyarat waktu (dipakai animasi DAN efek suara)
def parse_number(s: str, lang: str) -> dict | None:
    m = _NUM.search(s or "")
    if not m:
        return None
    tok = m.group(0)
    prefix, suffix = s[:m.start()].strip(), s[m.end():].strip()
    last_dot, last_com = tok.rfind("."), tok.rfind(",")
    if last_dot >= 0 and last_com >= 0:
        dec_sep = "." if last_dot > last_com else ","
    elif last_dot >= 0 or last_com >= 0:
        sep = "." if last_dot >= 0 else ","
        groups = tok.split(sep)
        if len(groups) > 2:                                  # 1.000.000 / 1,000,000
            dec_sep = ""
        elif len(groups[-1]) == 3:                           # 1.200 (id) / 1,200 (en) = ribuan
            dec_sep = "" if sep == ("." if lang == "id" else ",") else sep
        else:
            dec_sep = sep
    else:
        dec_sep = ""
    if dec_sep:
        ip, _, fp = tok.rpartition(dec_sep)
        ip, fp = re.sub(r"\D", "", ip), re.sub(r"\D", "", fp)
        value, decimals = float(f"{ip or 0}.{fp or 0}"), len(fp)
    else:
        value, decimals = float(re.sub(r"\D", "", tok)), 0
    if decimals > 3:
        decimals = 3
    return {"value": value, "decimals": decimals, "prefix": prefix[:12], "suffix": suffix[:16],
            "group": "." if lang == "id" else ",", "dec": "," if lang == "id" else ".", "year": bool(_YEAR.fullmatch(tok))}


def _scene_words(words: list[dict], sc: dict) -> list[dict]:
    return [w for w in words if sc["start"] <= (w["s"] + w["e"]) / 2 < sc["end"]]


def _find(ws: list[dict], phrase: str, after: float = -1) -> tuple[int, int] | None:
    toks = [_norm(t) for t in (phrase or "").split() if _norm(t)]
    if not toks:
        return None
    nw = [_norm(w["t"]) for w in ws]
    for i in range(len(nw)):
        if ws[i]["s"] < after:
            continue
        if all(i + j < len(nw) and (nw[i + j] == t or (len(t) > 3 and nw[i + j].startswith(t[:max(4, len(t) - 2)])))
               for j, t in enumerate(toks)):
            return i, i + len(toks) - 1
    return None


def cues(sc: dict, words: list[dict], lang: str) -> dict:
    """Waktu kejadian di adegan (detik absolut). Animasi Remotion dan efek suara memakai angka yang sama."""
    ws = _scene_words(words, sc)
    s, e = sc["start"], sc["end"]
    dur = e - s
    c: dict = {"words": [{"s": w["s"], "e": w["e"], "t": w["t"]} for w in ws]}
    hit = _find(ws, sc.get("keyword", ""))
    c["mark"] = [hit[0], hit[1]] if hit else None
    c["markAt"] = round(ws[hit[0]]["s"], 3) if hit else round(s + min(1.6, dur * 0.45), 3)
    lay = sc["layout"]
    if lay == "judul":
        toks = sc["heading"].split()[:8]
        rev, last = [], s + 0.12
        for i, t in enumerate(toks):
            h = _find(ws, t, after=last - 0.05)
            at = ws[h[0]]["s"] if h else last + (0.18 if i else 0.0)
            at = max(at, last if i else s + 0.12)
            rev.append(round(min(at, e - 0.4), 3))
            last = at
        c["reveal"] = rev
        kw = _norm(sc.get("keyword", "").split()[0]) if sc.get("keyword") else ""
        c["hot"] = next((i for i, t in enumerate(toks) if kw and _norm(t).startswith(kw[:5])), max(range(len(toks)),
                        key=lambda i: len(toks[i])) if toks else 0)
    if lay == "kutipan":
        qt = sc.get("quote", "").split()
        rev, j, last = [], 0, s + 0.2
        for t in qt:
            k = j
            while k < len(ws) and _norm(ws[k]["t"]) != _norm(t):
                k += 1
            if k < len(ws):
                last, j = max(last, ws[k]["s"]), k + 1
            else:
                last += 0.16
            rev.append(round(min(last, e - 0.3), 3))
        c["reveal"] = rev
        hit = _find([{"t": t, "s": 0, "e": 0} for t in qt], sc.get("keyword", ""))
        c["mark"] = [hit[0], hit[1]] if hit else None
        if hit:
            c["markAt"] = rev[hit[0]]
    if lay == "angka":
        num = parse_number(sc.get("number", ""), lang) or {"value": 0, "decimals": 0, "prefix": "", "suffix": ""}
        m = _NUM.search(sc.get("number", ""))
        h = None
        if m:
            digits = re.sub(r"\D", "", m.group(0))
            h = next((i for i, w in enumerate(ws) if digits and digits in re.sub(r"\D", "", w["t"])), None)
        at = ws[h]["s"] if h is not None else s + 0.35
        c["number"] = {**num, "at": round(max(s + 0.2, min(at, e - 1.3)), 3)}
        c["countEnd"] = round(c["number"]["at"] + (0.0 if num.get("year") else 1.0), 3)
    if lay in ("garis_waktu", "banding", "alur"):
        items = sc.get("items") or []
        n = len(items)
        out, last = [], s + 0.25
        for i, it in enumerate(items):
            first = (it.get("t") or "").split()[0] if it.get("t") else ""
            h = _find(ws, first, after=last - 0.05) if first else None
            even = s + 0.3 + (dur - 1.0) * i / max(1, n)
            at = ws[h[0]]["s"] if h else even
            at = round(min(max(at, last if i else s + 0.25), e - 0.5), 3)
            out.append({**it, "at": at})
            last = at + 0.15
        c["items"] = out
        if lay == "banding" and out:
            c["vsAt"] = round(min(e - 0.3, max(x["at"] for x in out) + 0.25), 3)
    if lay == "peta":
        c["pinAt"] = round(s + min(1.2, dur * 0.4), 3)
    return c


# ---------------------------------------------------------------- efek suara sintetis
def _bp(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Band-pass lewat FFT dengan tepi landai (tanpa scipy)."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    gain = 1 / np.sqrt(1 + (lo / np.maximum(f, 1)) ** 4) / np.sqrt(1 + (f / hi) ** 4)
    return np.fft.irfft(spec * gain, len(x)).astype(np.float32)


def _env(n: int, a: float, r: float) -> np.ndarray:
    t = np.arange(n) / SR
    return (np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))).astype(np.float32)


def _norm_amp(x: np.ndarray, peak: float) -> np.ndarray:
    return (x / (np.abs(x).max() or 1) * peak).astype(np.float32)


def sfx_bank(seed: int = 3) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    out = {}
    n = int(0.42 * SR)                                      # kertas: gemerisik berderak
    crack = np.zeros(n, np.float32)
    for k in rng.integers(0, int(n * 0.8), 46):
        L = int(rng.uniform(0.004, 0.02) * SR)
        crack[k:k + L] += np.exp(-np.arange(min(L, n - k)) / (L / 3)) * rng.uniform(0.3, 1)
    crack = np.convolve(crack, np.ones(64) / 64, "same")
    out["kertas"] = _norm_amp(_bp(rng.standard_normal(n), 1400, 7500) * crack * _env(n, 0.02, 0.25), 0.32)
    n = int(0.34 * SR)                                      # stempel: hentakan rendah
    t = np.arange(n) / SR
    thud = np.sin(2 * np.pi * 64 * t) * np.exp(-t * 15) + 0.45 * np.sin(2 * np.pi * 131 * t) * np.exp(-t * 24)
    click = _bp(rng.standard_normal(n), 300, 3200) * np.exp(-t * 70)
    out["stempel"] = _norm_amp(thud + 0.55 * click, 0.62)
    n = int(0.46 * SR)                                      # spidol: gesekan tinggi
    t = np.arange(n) / SR
    am = 0.6 + 0.4 * np.sin(2 * np.pi * 27 * t) ** 2
    shape = np.sin(np.pi * np.clip(t / (n / SR), 0, 1)) ** 0.6
    out["spidol"] = _norm_amp(_bp(rng.standard_normal(n), 2600, 7000) * am * shape, 0.13)
    n = int(0.5 * SR)                                       # wus: transisi
    t = np.arange(n) / SR
    bell = np.exp(-((t - 0.24) / 0.11) ** 2)
    lo, hi = _bp(rng.standard_normal(n), 250, 1400), _bp(rng.standard_normal(n), 1800, 8000)
    mixw = np.clip(t / (n / SR), 0, 1)
    out["wus"] = _norm_amp((lo * (1 - mixw) + hi * mixw * 0.7) * bell, 0.2)
    n = int(0.03 * SR)                                      # ketik: satu tuts
    t = np.arange(n) / SR
    key = _bp(rng.standard_normal(n), 1800, 9000) * np.exp(-t * 220) + 0.35 * np.sin(2 * np.pi * 2300 * t) * np.exp(-t * 160)
    out["ketik"] = _norm_amp(key, 0.12)
    n = int(0.09 * SR)                                      # pop: penanda muncul
    t = np.arange(n) / SR
    f = 950 * np.exp(-t * 18) + 260
    out["pop"] = _norm_amp(np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.03), 0.28)
    n = int(0.018 * SR)                                     # tik: penghitung angka
    t = np.arange(n) / SR
    out["tik"] = _norm_amp(np.sin(2 * np.pi * 2500 * t) * np.exp(-t * 260), 0.08)
    return out


SFX_DIR = Path(__file__).resolve().parent.parent / "sfx"
SFX_NAMES = {"kertas": "kertas/foto ditempel", "stempel": "hentakan judul & angka", "spidol": "stabilo",
             "wus": "transisi antar-adegan", "ketik": "ketikan dokumen (per kata)", "pop": "penanda muncul", "tik": "hitungan angka"}


def sfx_with_overrides() -> dict[str, np.ndarray]:
    """Bunyi sintetis, diganti file milik pengguna di folder sfx/ bila ada (mis. sfx/kertas.wav)."""
    bank = sfx_bank()
    used = []
    for name in list(bank):
        for ext in (".wav", ".mp3", ".ogg", ".flac", ".m4a"):
            f = SFX_DIR / f"{name}{ext}"
            if f.is_file():
                try:
                    x = _decode(f)[: int(2.5 * SR)]
                    fade = min(len(x), int(0.02 * SR))
                    if fade:
                        x[-fade:] *= np.linspace(1, 0, fade)
                    bank[name] = _norm_amp(x, float(np.abs(bank[name]).max()))
                    used.append(f.name)
                except ClipAgentError as exc:
                    log(f"  Efek suara {f.name} dilewati: {exc}")
                break
    if used:
        log(f"Efek suara sendiri dipakai: {', '.join(used)}")
    return bank


def sfx_events(scenes: list[dict], cue_list: list[dict]) -> list[tuple[float, str, float]]:
    ev: list[tuple[float, str, float]] = []
    for i, (sc, c) in enumerate(zip(scenes, cue_list)):
        s = sc["start"]
        if i:
            ev.append((s - 0.28, "wus", 0.9))
        lay = sc["layout"]
        if lay in PHOTO_LAYOUTS:
            ev.append((s + 0.04, "kertas", 1.0))
        if lay == "judul":
            for k, at in enumerate(c.get("reveal", [])):
                ev.append((at, "stempel" if k == 0 else "pop", 0.8 if k == 0 else 0.45))
        if lay == "dokumen":
            for w in c["words"]:
                ev.append((w["s"] - 0.03, "ketik", 0.8))
        if lay in ("dokumen", "kutipan", "potong", "foto") and c.get("mark") is not None:
            ev.append((c["markAt"], "spidol", 1.0))
        if lay == "angka" and c.get("number"):
            a, b = c["number"]["at"], c["countEnd"]
            tt = a
            while tt < b - 0.02:
                ev.append((tt, "tik", 1.0))
                tt += 0.075
            ev.append((b, "stempel", 0.9))
        if lay in ("garis_waktu", "alur", "banding"):
            for it in c.get("items", []):
                ev.append((it["at"], "pop", 0.8))
            if c.get("vsAt"):
                ev.append((c["vsAt"], "stempel", 0.9))
        if lay == "peta":
            ev.append((c["pinAt"], "pop", 1.0))
            ev.append((s + 0.05, "kertas", 0.6))
    return ev


def _speech_env(words: list[dict], n: int) -> np.ndarray:
    raw = np.zeros(n, np.float32)
    for w in words:
        a, b = max(0, int((w["s"] - 0.15) * SR)), min(n, int((w["e"] + 0.3) * SR))
        raw[a:b] = 1
    k = int(0.25 * SR)
    kern = np.ones(k, np.float32) / k
    return np.convolve(raw, kern, "same")


def mix_audio(proj: dict, d: Path, scenes: list[dict], cue_list: list[dict]) -> tuple[Path, Path, bool]:
    st = proj["settings"]
    vo = _decode(d / "vo.wav")
    total = len(vo)
    peak = float(np.abs(vo).max() or 1)
    vo = vo * min(4.0, 0.89 / peak)
    fx = np.zeros(total + SR, np.float32)
    if st.get("sfx", True):
        bank = sfx_with_overrides()
        for at, name, gain in sfx_events(scenes, cue_list):
            x = bank[name] * gain
            a = int(max(0.0, at) * SR)
            if a >= len(fx):
                continue
            fx[a:a + len(x)] += x[:len(fx) - a]
    fx = fx[:total]
    nomusic = vo + fx
    adir = d / "assets"
    mus = None
    choice = st.get("music") or "auto"
    try:
        mpath = music.track(choice, total / SR + 0.5, adir, proj.get("mood") or "santai")
        if mpath:
            mus = _decode(mpath)[:total]
            mus = np.pad(mus, (0, total - len(mus)))
            env = _speech_env(proj["words"], total)
            vol = float(st.get("music_volume", 0.22))
            fade = np.minimum(1, np.arange(total) / (0.8 * SR)) * np.minimum(1, (total - np.arange(total)) / (1.5 * SR))
            mus = mus / (np.abs(mus).max() or 1) * vol * (1 - 0.7 * env) * fade
    except ClipAgentError as exc:
        log(f"Musik dilewati: {exc}")
    full = nomusic + (mus if mus is not None else 0)
    for arr, name in ((full, "mix.wav"), (nomusic, "mix_tanpa_musik.wav"), (vo, "stem_narasi.wav"), (fx, "stem_efek.wav")):
        tts.write_wav(adir / name, np.clip(arr, -1, 1), SR)
    if mus is not None:
        tts.write_wav(adir / "stem_musik.wav", np.clip(mus, -1, 1), SR)
    else:
        (adir / "stem_musik.wav").unlink(missing_ok=True)
    return adir / "mix.wav", adir / "mix_tanpa_musik.wav", mus is not None


# ---------------------------------------------------------------- render
def _loudness(path: Path) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    txt = r.stderr[-1500:]
    i = re.search(r"I:\s*(-?[\d.]+) LUFS", txt)
    p = re.search(r"Peak:\s*(-?[\d.]+) dBFS", txt)
    return {"lufs": float(i.group(1)) if i else None, "peak": float(p.group(1)) if p else None}


def _contact_sheet(video: Path, scenes: list[dict], out: Path) -> None:
    cap = cv2.VideoCapture(str(video))
    tiles = []
    for i, sc in enumerate(scenes[:24]):
        t = sc["start"] + min(sc["end"] - sc["start"] - 0.1, max(1.0, (sc["end"] - sc["start"]) * 0.7))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        h = 360
        fr = cv2.resize(fr, (int(fr.shape[1] * h / fr.shape[0]), h))
        cv2.rectangle(fr, (0, 0), (fr.shape[1], 30), (20, 20, 20), -1)
        cv2.putText(fr, f"{i + 1}. {LAYOUTS[sc['layout']]} {t:.1f}s", (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(fr)
    cap.release()
    if not tiles:
        return
    cols = 6 if tiles[0].shape[1] < tiles[0].shape[0] else 3
    w = tiles[0].shape[1]
    tiles = [cv2.resize(t, (w, 360)) for t in tiles]
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 240))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 82])


def _on_screen_facts(scenes: list[dict]) -> list[str]:
    facts = []
    for i, sc in enumerate(scenes):
        lay = sc["layout"]
        if lay == "angka":
            facts.append(f"Adegan {i + 1}: angka {sc['number']} ({sc.get('label', '')})")
        if lay == "garis_waktu":
            facts.append(f"Adegan {i + 1}: " + "; ".join(f"{x['t']} {x.get('label', '')}".strip() for x in sc["items"]))
        if lay == "peta":
            facts.append(f"Adegan {i + 1}: peta {', '.join(sc['places'])}")
        if lay in ("banding", "alur"):
            facts.append(f"Adegan {i + 1}: " + " / ".join(x["t"] for x in sc["items"]))
    return facts


def build_props(proj: dict, d: Path, srv: _AssetServer) -> tuple[dict, list[dict]]:
    st = proj["settings"]
    W, H = RATIOS[st["ratio"]]
    lang = st["language"] if st["language"] != "auto" else proj.get("detected_language", "en")
    rng = np.random.default_rng(int(hashlib.sha1(proj["id"].encode()).hexdigest()[:6], 16))
    cue_list, scenes = [], []
    dirs = ["kiri", "bawah", "kanan", "atas"]
    for i, sc in enumerate(proj["scenes"]):
        c = cues(sc, proj["words"], lang)
        cue_list.append(c)
        a = sc.get("asset") or {}
        img = d / "assets" / a.get("file", "-")
        scenes.append({"id": sc["id"], "idx": i, "start": sc["start"], "end": sc["end"], "layout": sc["layout"],
                       "heading": sc["heading"], "keyword": sc.get("keyword", ""), "label": sc.get("label", ""),
                       "places": sc.get("places", []), "quote": sc.get("quote", ""),
                       "image": srv.url(img) if a.get("file") and img.is_file() else "",
                       "cutout": bool(a.get("cutout")), "tilt": round(float(rng.uniform(-2.6, 2.6)), 2),
                       "enter": dirs[int(rng.integers(0, 4))] if i else "none", "seed": int(rng.integers(1, 10_000)),
                       "dark": sc["layout"] == "judul" and i % 3 == 1,
                       "captions": bool(st.get("captions", True)) and sc["layout"] not in ("dokumen", "kutipan"), **c})
    theme = dict(THEMES[st["theme"]])
    props = {"fps": 30, "width": W, "height": H, "duration": proj["vo"]["duration"], "theme": theme,
             "scenes": scenes, "words": proj["words"], "lang": lang,
             "fonts": {k: v for k, v in FONT_SETS[st.get("fonts", "editorial")].items() if k != "name"}}
    return props, cue_list


def _scene_key(sc: dict, st: dict) -> str:
    """Sidik isi adegan + gaya; pratinjau lama tidak ditampilkan bila adegan sudah diubah."""
    keep = {k: sc.get(k) for k in ("layout", "heading", "keyword", "label", "number", "items", "quote", "places", "start", "end")}
    keep["asset"] = (sc.get("asset") or {}).get("file")
    keep["st"] = [st.get(k) for k in ("ratio", "theme", "fonts", "captions")]
    return hashlib.sha1(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _notes(proj: dict, entry: dict) -> str:
    st = proj["settings"]
    lines = [f"# {proj.get('title') or 'Video kolase'} (v{entry['version']})", "",
             f"- Dibuat: {entry['created']}",
             f"- Format {st['ratio']}, tema {THEMES[st['theme']]['name']}, gaya huruf {FONT_SETS[st.get('fonts', 'editorial')]['name']}",
             f"- Durasi {entry['duration']} dtk, {entry['scenes']} adegan, loudness {entry['loudness'].get('lufs')} LUFS",
             f"- Suara: {'suara AI' if proj['vo'].get('source') == 'tts' else 'VO unggahan'}; musik: {'ya' if entry['music'] else 'tidak'}",
             "", "## Periksa fakta di layar", ""]
    lines += [f"- [ ] {f}" for f in entry["facts"]] or ["- (tidak ada angka, tahun, atau peta di layar)"]
    lines += ["", "## Adegan", "", "| No | Waktu | Tata letak | Teks di layar | Foto |", "|---|---|---|---|---|"]
    for i, sc in enumerate(proj["scenes"]):
        extra = sc.get("number") or ", ".join(sc.get("places") or []) or " / ".join(x["t"] for x in sc.get("items") or []) \
            or sc.get("quote", "")[:60]
        txt = (sc["heading"] + (f" — {extra}" if extra else "")).replace("|", "/")
        a = sc.get("asset") or {}
        foto = {"ai": "AI", "stok": a.get("credit", "stok"), "unggah": "unggahan sendiri"}.get(a.get("source"), "-")
        lines.append(f"| {i + 1} | {sc['start']:.1f}–{sc['end']:.1f} | {LAYOUTS[sc['layout']]} | {txt} | {foto} |")
    lines += ["", "## Pemeriksaan otomatis", ""] + [f"- {'LULUS' if c['ok'] else 'PERIKSA'}: {c['text']}" for c in entry["checks"]]
    if entry["credits"]:
        lines += ["", "## Kredit", ""] + [f"- {c}" for c in entry["credits"]]
    if entry["ai_media"]:
        lines += ["", "Video memakai gambar atau suara buatan AI: nyalakan label konten AI saat mengunggah."]
    lines += ["", "Agent tidak bisa mendengar. Level suara sudah diukur, tapi dengarkan sendiri sebelum mengunggah.", ""]
    return "\n".join(lines)


def _mux(silent: Path, wav: Path, outp: Path, start: float = 0.0, dur: float = 0.0) -> None:
    cut = (["-ss", f"{start:.3f}", "-t", f"{dur:.3f}"] if dur else [])
    _ffmpeg(["-i", str(silent), *cut, "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
             "-shortest", "-movflags", "+faststart", str(outp)], "Menggabung audio")


def render(out_dir: Path, pid: str, clip_from: str = "") -> dict:
    """Render penuh, atau cuplikan 12 detik mulai dari adegan `clip_from` (untuk cek cepat)."""
    proj = load(out_dir, pid)
    if not proj.get("scenes"):
        raise ClipAgentError("Storyboard masih kosong. Klik Buat storyboard dulu.")
    d = pdir(out_dir, pid)
    st = proj["settings"]
    total = proj["vo"]["duration"]
    rng = None
    if clip_from:
        sc0 = next((x for x in proj["scenes"] if x["id"] == clip_from), proj["scenes"][0])
        s0 = max(0.0, sc0["start"])
        rng = (s0, min(total, s0 + 12.0))
        log(f"Cuplikan {rng[0]:.1f}–{rng[1]:.1f} dtk dari '{proj.get('title') or pid}'.")
    else:
        log(f"Membuat video kolase '{proj.get('title') or pid}' ({st['ratio']}, {len(proj['scenes'])} adegan).")
    _scene_images(proj, d, 0.02, 0.3)
    save(out_dir, proj)
    slug = slugify(proj.get("title") or "video", 30)
    version = 1 + max([r.get("version", 0) for r in proj.get("renders", [])] + [len(proj.get("renders", []))])
    base = f"cuplikan_{time.strftime('%H%M%S')}" if rng else f"{slug}_v{version}"
    silent = d / f"{base}.silent.mp4"
    with _AssetServer(out_dir) as srv:
        props, cue_list = build_props(proj, d, srv)
        progress(0.32, "Efek suara dan musik")
        mix, mix_nm, has_music = mix_audio(proj, d, proj["scenes"], cue_list)
        job = {"mode": "video", "composition": "Kolase", "props": props, "output": str(silent.resolve()), "crf": 19}
        if rng:
            job["frameRange"] = [int(rng[0] * 30), max(int(rng[0] * 30), int(rng[1] * 30) - 1)]
        try:
            _run_remotion(job, 0.35, 0.93, "Merender cuplikan" if rng else "Merender kolase dengan Remotion")
        except BaseException:
            silent.unlink(missing_ok=True)
            raise
    progress(0.94, "Menggabung audio")
    if rng:
        outp = d / f"{base}.mp4"
        _mux(silent, mix, outp, rng[0], rng[1] - rng[0])
        silent.unlink(missing_ok=True)
        proj = load(out_dir, pid)
        clips = [c for c in proj.get("clips", []) if (d / c["file"]).is_file()]
        for old in clips[:-2]:                            # simpan 3 cuplikan terakhir saja
            (d / old["file"]).unlink(missing_ok=True)
        proj["clips"] = clips[-2:] + [{"file": outp.name, "start": round(rng[0], 2), "end": round(rng[1], 2),
                                        "created": time.strftime("%Y-%m-%d %H:%M:%S")}]
        save(out_dir, proj)
        progress(1.0, "Cuplikan selesai")
        return {"file": outp.name, "clip": True, "video_url": _url(out_dir, outp)}
    final, nomusic = d / f"{base}.mp4", d / f"{base}_tanpa-musik.mp4"
    _mux(silent, mix, final)
    _mux(silent, mix_nm, nomusic)
    silent.unlink(missing_ok=True)
    extra = {}
    for key, stem in (("narasi", "stem_narasi.wav"), ("efek", "stem_efek.wav"), ("musik", "stem_musik.wav")):
        if (d / "assets" / stem).is_file():
            shutil.copyfile(d / "assets" / stem, d / f"{base}_{key}.wav")
            extra[key] = f"{base}_{key}.wav"
    progress(0.97, "Pemeriksaan akhir")
    sheet = d / f"{base}_tinjau.jpg"
    _contact_sheet(final, proj["scenes"], sheet)
    loud = _loudness(final)
    from .utils import probe
    vdur = probe(final)["duration"]
    checks = [{"ok": abs(vdur - total) < 0.25, "text": f"Durasi video {vdur:.2f} dtk, VO {total:.2f} dtk"},
              {"ok": loud["lufs"] is not None and -16.5 <= loud["lufs"] <= -11.5,
               "text": f"Loudness {loud['lufs']} LUFS (target -14)"},
              {"ok": loud["peak"] is not None and loud["peak"] <= -0.5, "text": f"Puncak {loud['peak']} dBFS (maks. -1)"},
              {"ok": all(s.get("asset") for s in proj["scenes"] if s["layout"] in PHOTO_LAYOUTS),
               "text": "Semua adegan foto punya gambar"}]
    for c in checks:
        log(("  LULUS  " if c["ok"] else "  PERIKSA ") + c["text"])
    ai_media = any((s.get("asset") or {}).get("source") == "ai" for s in proj["scenes"])
    credits = sorted({(s.get("asset") or {}).get("credit") for s in proj["scenes"] if (s.get("asset") or {}).get("credit")})
    entry = {"file": final.name, "nomusic": nomusic.name, "sheet": sheet.name if sheet.is_file() else "", "version": version,
             "created": time.strftime("%Y-%m-%d %H:%M:%S"), "duration": round(vdur, 2), "scenes": len(props["scenes"]),
             "music": has_music, "loudness": loud, "checks": checks, "facts": _on_screen_facts(proj["scenes"]),
             "credits": credits, "ai_media": ai_media or proj["vo"].get("source") == "tts"}
    (d / f"{base}_catatan.md").write_text(_notes(proj, entry), encoding="utf-8")
    extra["catatan"] = f"{base}_catatan.md"
    entry["extra"] = extra
    proj = load(out_dir, pid)
    proj.setdefault("renders", []).append(entry)
    save(out_dir, proj)
    progress(1.0, "Video kolase selesai")
    log(f"Selesai: {final.name}")
    return {**entry, "video_url": _url(out_dir, final)}


def preview(out_dir: Path, pid: str) -> dict:
    """Gambar diam satu per adegan (cepat) untuk dicek sebelum render penuh."""
    proj = load(out_dir, pid)
    if not proj.get("scenes"):
        raise ClipAgentError("Storyboard masih kosong.")
    d = pdir(out_dir, pid)
    _scene_images(proj, d, 0.02, 0.45)
    save(out_dir, proj)
    adir = d / "assets"
    with _AssetServer(out_dir) as srv:
        props, _ = build_props(proj, d, srv)
        stills = []
        for sc in proj["scenes"]:
            dur = sc["end"] - sc["start"]
            t = sc["start"] + min(max(0.8, dur * 0.75), dur - 0.05)
            stills.append({"frame": int(t * 30), "output": str((adir / f"prev_{sc['id']}.jpg").resolve())})
        _run_remotion({"mode": "stills", "composition": "Kolase", "props": props, "stills": stills, "scale": 0.4},
                      0.5, 0.98, "Pratinjau tiap adegan")
    proj = load(out_dir, pid)
    for sc in proj["scenes"]:
        if (adir / f"prev_{sc['id']}.jpg").is_file():
            sc["preview"] = _scene_key(sc, proj["settings"])
    save(out_dir, proj)
    progress(1.0, "Pratinjau siap")
    return {"scenes": len(proj["scenes"])}


# ---------------------------------------------------------------- paket "Kolase Editorial" milik pengguna (lokal)
PAKET_ENV = "KOLASE_PAKET_DIR"


def _paket_paths(root: Path) -> dict | None:
    """Kenali folder paket: root paket, folder skill, atau skill yang sudah terpasang di agent."""
    for skill in (root / "skills" / "kolase-editorial", root, root / "kolase-editorial"):
        m = skill / "scripts" / "mulai.py"
        if m.is_file():
            pkg = skill.parent.parent if skill.parent.name == "skills" else skill
            return {"root": str(pkg), "skill": str(skill), "mulai": str(m)}
    return None


def paket_status() -> dict:
    raw = (os.getenv(PAKET_ENV) or "").strip()
    if not raw:
        return {"configured": False, "found": False, "path": ""}
    p = _paket_paths(Path(raw).expanduser())
    return {"configured": True, "found": bool(p), "path": raw, **(p or {})}


def paket_dir(out_dir: Path) -> Path:
    d = out_dir / "_kolase_paket"
    d.mkdir(parents=True, exist_ok=True)
    return d


def paket_project_status(out_dir: Path, proj: dict) -> dict:
    pk = proj.get("paket") or {}
    dst = Path(pk.get("dir", "-"))
    if not pk or not dst.is_dir():
        return {}
    files = []
    for f in sorted((dst / "hasil").glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rel = f.resolve().relative_to(out_dir.resolve()).as_posix()
            files.append({"name": f.name, "url": f"/files/{rel}?v={int(f.stat().st_mtime)}", "path": rel})
        except ValueError:
            files.append({"name": f.name, "url": "", "path": str(f)})
    return {**pk, "results": files}


def paket_prepare(out_dir: Path, pid: str) -> dict:
    """Siapkan proyek paket lokal dari VO proyek ini: jalankan mulai.py dan transkrip paket."""
    stt = paket_status()
    if not stt.get("found"):
        raise ClipAgentError("Folder paket Kolase Editorial belum diatur atau tidak dikenali. Isi lokasinya di tab Kolase.")
    proj = load(out_dir, pid)
    d = pdir(out_dir, pid)
    vo = d / ((proj.get("vo") or {}).get("original") or "vo.wav")
    if not vo.is_file():
        vo = d / "vo.wav"
    if not vo.is_file():
        raise ClipAgentError("VO proyek belum ada. Buat storyboard dulu agar suara AI dibuat, atau unggah VO.")
    st = proj["settings"]
    slug = slugify(proj.get("title") or "video", 30)
    dst = paket_dir(out_dir) / f"{slug}-{pid[:6]}"
    if dst.exists() and any(dst.iterdir()):
        dst = paket_dir(out_dir) / f"{slug}-{pid[:6]}-{time.strftime('%H%M%S')}"
    lang = st["language"] if st["language"] in ("id", "en") else proj.get("detected_language", "id")
    progress(0.1, "Membuat proyek paket")
    cmd = [sys.executable, stt["mulai"], str(dst), "--vo", str(vo), "--nama", slug, "--rasio", st["ratio"],
           "--bahasa", lang]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=stt["root"])
    for line in (r.stdout + r.stderr).strip().splitlines()[-12:]:
        log(f"  paket: {line}")
    if r.returncode != 0:
        raise ClipAgentError("Skrip paket gagal membuat proyek: " + (r.stderr or r.stdout).strip()[-300:])
    tr = dst / "tools" / "transkrip.py"
    if tr.is_file():
        progress(0.35, "Transkrip dengan alat paket")
        r = subprocess.run([sys.executable, str(tr)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(dst), timeout=3600)
        for line in (r.stdout + r.stderr).strip().splitlines()[-8:]:
            log(f"  paket: {line}")
        if r.returncode != 0:
            log("  Transkrip paket gagal; agent akan menjalankannya lagi.")
    prompt = (f"Baca AGENTS.md dan skills/kolase-editorial/SKILL.md di folder ini, lalu lanjutkan proyek Kolase "
              f"Editorial yang sudah disiapkan di folder \"{dst}\" (VO sudah ada"
              f"{', transkrip sudah dibuat' if (dst / 'transkrip').is_dir() and any((dst / 'transkrip').iterdir()) else ''}). "
              f"Rasio {st['ratio']}. Simpan hasil di folder hasil/ proyek itu.")
    proj = load(out_dir, pid)
    proj["paket"] = {"dir": str(dst), "root": stt["root"], "prompt": prompt, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    save(out_dir, proj)
    progress(1.0, "Proyek paket siap")
    return proj["paket"]


def paket_videos(out_dir: Path) -> list[dict]:
    out = []
    for f in paket_dir(out_dir).glob("*/hasil/*.mp4"):
        out.append({"path": f.relative_to(out_dir).as_posix(), "mtime": f.stat().st_mtime, "name": f.name,
                    "project": f.parent.parent.name})
    return out
