"""Suara narasi (text-to-speech) untuk video buatan ulang.

Dua mesin:
- "gemini": Gemini TTS lewat Interactions API (butuh GEMINI_API_KEY). 30 suara bawaan, multibahasa.
- "edge":   Microsoft Edge Read Aloud lewat paket `edge-tts` (gratis, tanpa key, butuh internet).
Hasil disimpan sebagai WAV 48 kHz mono + waktu tiap kata (untuk caption karaoke).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from .gemini import api_key, with_fallbacks
from .utils import ClipAgentError, log

GEMINI_VOICES = {
    "Puck": "Ceria", "Charon": "Informatif", "Kore": "Tegas", "Fenrir": "Bersemangat", "Leda": "Muda",
    "Orus": "Tegas (pria)", "Aoede": "Ringan", "Zephyr": "Cerah", "Callirrhoe": "Santai", "Autonoe": "Cerah",
    "Enceladus": "Berdesah", "Iapetus": "Jelas", "Umbriel": "Santai", "Algieba": "Halus", "Despina": "Halus",
    "Erinome": "Jelas", "Algenib": "Serak", "Rasalgethi": "Informatif", "Laomedeia": "Ceria",
    "Achernar": "Lembut", "Alnilam": "Tegas", "Schedar": "Datar", "Gacrux": "Dewasa", "Pulcherrima": "Lugas",
    "Achird": "Ramah", "Zubenelgenubi": "Kasual", "Vindemiatrix": "Lembut", "Sadachbia": "Hidup",
    "Sadaltager": "Berwawasan", "Sulafat": "Hangat",
}
EDGE_VOICES = {
    "en-US-AndrewMultilingualNeural": "Andrew, pria, hangat (AS)",
    "en-US-BrianMultilingualNeural": "Brian, pria, santai (AS)",
    "en-US-AvaMultilingualNeural": "Ava, wanita, ekspresif (AS)",
    "en-US-EmmaMultilingualNeural": "Emma, wanita, ramah (AS)",
    "en-US-GuyNeural": "Guy, pria, gaya berita (AS)",
    "en-US-JennyNeural": "Jenny, wanita, jelas (AS)",
    "id-ID-ArdiNeural": "Ardi, pria (Indonesia)",
    "id-ID-GadisNeural": "Gadis, wanita (Indonesia)",
}
DEFAULT_VOICE = {"gemini": "Puck", "edge": "en-US-AndrewMultilingualNeural"}


def tts_models() -> list[str]:
    first = os.getenv("TTS_MODEL") or "gemini-3.8-flash-tts"
    return [first, "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview"]


def edge_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("edge_tts") is not None


def engines() -> dict:
    return {"gemini": bool(api_key()), "edge": edge_available()}


def pick_engine(engine: str) -> str:
    ok = engines()
    if engine in ok and ok[engine]:
        return engine
    for e in ("gemini", "edge"):
        if ok[e]:
            if engine and engine != e:
                log(f"Mesin suara '{engine}' tidak tersedia; memakai '{e}'.")
            return e
    raise ClipAgentError("Belum ada mesin suara. Isi GEMINI_API_KEY di Pengaturan, atau pasang suara gratis: "
                         "pip install edge-tts")


# ---------------------------------------------------------------- audio util
def _to_wav48(src: Path, dst: Path) -> None:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "48000",
                        "-c:a", "pcm_s16le", str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        raise ClipAgentError(f"Gagal mengonversi audio narasi: {r.stderr[-300:]}")


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        data = np.frombuffer(w.readframes(n), np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def write_wav(path: Path, data: np.ndarray, sr: int = 48000) -> None:
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _speech_bounds(data: np.ndarray, sr: int) -> tuple[float, float]:
    win = max(1, sr // 100)
    n = len(data) // win
    if n == 0:
        return 0.0, float(len(data) / sr)
    rms = np.sqrt((data[: n * win].reshape(n, win) ** 2).mean(axis=1))
    thr = max(0.01, rms.max() * 0.06)
    idx = np.where(rms > thr)[0]
    if not len(idx):
        return 0.0, float(len(data) / sr)
    return float(idx[0] * win / sr), float((idx[-1] + 1) * win / sr)


def estimate_words(text: str, start: float, end: float) -> list[dict]:
    """Perkiraan waktu tiap kata: dibagi proporsional panjang kata, plus jeda di tanda baca."""
    toks = text.split()
    if not toks:
        return []
    weights = []
    for t in toks:
        w = len(re.sub(r"\W", "", t)) + 2
        if re.search(r"[.!?]$", t):
            w += 5
        elif re.search(r"[,;:]$", t):
            w += 3
        weights.append(w)
    total, t0, out = sum(weights), start, []
    span = max(0.1, end - start)
    for tok, w in zip(toks, weights):
        d = span * w / total
        out.append({"s": round(t0, 3), "e": round(t0 + d * 0.85, 3), "t": tok})
        t0 += d
    return out


# ---------------------------------------------------------------- mesin
def _gemini(text: str, voice: str, style: str, tmp: Path) -> None:
    def body(model):
        item = {"type": "text", "text": text}
        if style:
            item["annotations"] = [{"type": "speech_metadata", "style": style}]
        return {"model": model, "input": [{"type": "user_input", "content": [item]}],
                "response_format": {"type": "audio", "mime_type": "audio/wav"},
                "generation_config": {"speech_config": [{"voice": voice}]}}

    data, item, _ = with_fallbacks(tts_models(), body, "audio", timeout=180)
    mime = (item.get("mime_type") or "audio/wav").lower()
    if "l16" in mime or "pcm" in mime:                     # PCM mentah tanpa header
        rate = int(re.search(r"rate=(\d+)", mime).group(1)) if re.search(r"rate=(\d+)", mime) else 24000
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(data)
    else:
        tmp.write_bytes(data)


def _edge(text: str, voice: str, style: str, tmp: Path) -> list[dict]:
    import edge_tts

    rate = "+8%" if re.search(r"energetic|excited|upbeat|semangat", style or "", re.I) else "+0%"

    async def run():
        words, audio = [], bytearray()
        com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append({"s": round(s, 3), "e": round(s + chunk["duration"] / 1e7, 3), "t": chunk["text"]})
        return words, bytes(audio)

    try:
        words, audio = asyncio.run(run())
    except Exception as exc:
        raise ClipAgentError(f"Suara Edge gagal ({type(exc).__name__}: {str(exc)[:160]}). Periksa koneksi internet.")
    if not audio:
        raise ClipAgentError("Suara Edge tidak mengembalikan audio.")
    tmp.write_bytes(audio)
    return words


def synthesize(text: str, voice: str, engine: str, style: str, cache_dir: Path) -> dict:
    """Buat narasi untuk satu adegan. Mengembalikan {'file', 'duration', 'words', 'engine', 'voice'} (di-cache)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise ClipAgentError("Narasi adegan kosong.")
    engine = pick_engine(engine)
    voices = GEMINI_VOICES if engine == "gemini" else EDGE_VOICES
    if voice not in voices:
        voice = DEFAULT_VOICE[engine]
    model = tts_models()[0] if engine == "gemini" else "edge"
    key = hashlib.sha1(json.dumps([engine, voice, style, text, model]).encode()).hexdigest()[:14]
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav, meta_path = cache_dir / f"vo_{key}.wav", cache_dir / f"vo_{key}.json"
    if wav.is_file() and meta_path.is_file():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    tmp = cache_dir / f"vo_{key}.raw"
    words = None
    if engine == "gemini":
        _gemini(text, voice, style, tmp)
    else:
        words = _edge(text, voice, style, tmp)
    _to_wav48(tmp, wav)
    tmp.unlink(missing_ok=True)
    data, sr = read_wav(wav)
    s, e = _speech_bounds(data, sr)
    if not words:
        words = estimate_words(text, s, e)
    meta = {"file": wav.name, "duration": round(len(data) / sr, 3), "speech": [round(s, 3), round(e, 3)],
            "words": words, "engine": engine, "voice": voice}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta
