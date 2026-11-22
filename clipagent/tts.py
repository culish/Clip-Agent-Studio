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
import time
import wave
from pathlib import Path

import numpy as np

from .gemini import QuotaError, api_key, with_fallbacks
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
_BLOCKED: dict[str, float] = {}


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
_NO_WAV: set[str] = set()          # model yang menolak keluaran WAV ("Audio MIME type AUDIO_WAV is not supported")


def _gemini(text: str, voice: str, style: str, tmp: Path) -> None:
    def body(model):
        item = {"type": "text", "text": text}
        if style:
            item["annotations"] = [{"type": "speech_metadata", "style": style}]
        fmt = {"type": "audio"} if model in _NO_WAV else {"type": "audio", "mime_type": "audio/wav"}
        return {"model": model, "input": [{"type": "user_input", "content": [item]}],
                "response_format": fmt, "generation_config": {"speech_config": [{"voice": voice}]}}

    try:
        data, item, _ = with_fallbacks(tts_models(), body, "audio", timeout=180, what="suara")
    except QuotaError:
        raise
    except ClipAgentError as exc:
        m = re.search(r"MIME type \w+ is not supported for models/([\w.\-]+)", str(exc))
        if not m or m.group(1) in _NO_WAV:
            raise
        _NO_WAV.add(m.group(1))                           # minta format bawaan model itu, lalu dikonversi ffmpeg
        data, item, _ = with_fallbacks(tts_models(), body, "audio", timeout=180, what="suara")
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


_ID_WORDS = re.compile(r"\b(yang|dan|di|ke|itu|ini|kamu|aku|tidak|nggak|ada|untuk|dengan|kita|saja|juga|sudah|bisa)\b", re.I)


def looks_indonesian(text: str) -> bool:
    return len(_ID_WORDS.findall(text or "")) >= 2


def edge_default(text: str) -> str:
    """Suara Edge bawaan sesuai bahasa naskah: penutur asli Indonesia untuk naskah berbahasa Indonesia."""
    return "id-ID-ArdiNeural" if looks_indonesian(text) else DEFAULT_VOICE["edge"]


def _edge_clean(text: str) -> str:
    """Teks yang aman untuk Edge: tanpa arahan [..], emoji, dan tanda baca berulang yang membuatnya diam."""
    t = re.sub(r"\[[^\]]{0,60}\]", " ", text)
    t = t.replace("…", ", ").replace("...", ", ")
    t = re.sub(r"[^\w\s.,!?;:'\"()%&/\-]", " ", t)
    t = re.sub(r"([.,!?;:])(\s*[.,!?;:])+", r"\1", t)
    return re.sub(r"\s+", " ", t).strip(" ,;:")


def _edge(text: str, voice: str, style: str, tmp: Path) -> list[dict]:
    import edge_tts

    rate = "+8%" if re.search(r"energetic|excited|upbeat|semangat", style or "", re.I) else "+0%"

    async def run(txt: str, vc: str, boundary: str):
        words, audio = [], bytearray()
        com = edge_tts.Communicate(txt, vc, rate=rate, boundary=boundary)
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append({"s": round(s, 3), "e": round(s + chunk["duration"] / 1e7, 3), "t": chunk["text"]})
        return words, bytes(audio)

    clean = _edge_clean(text)
    if not re.search(r"\w", clean):
        raise ClipAgentError(f"Narasi \"{text[:60]}\" tidak berisi kata yang bisa diucapkan.")
    alts = ["id-ID-ArdiNeural", "id-ID-GadisNeural", "en-US-AndrewMultilingualNeural"] if looks_indonesian(text) else \
        ["en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural", "en-US-GuyNeural"]
    others = [v for v in alts if v != voice][:2]
    # Percobaan: teks asli, teks dibersihkan, suara lain, lalu tanpa penanda kata (waktu kata diperkirakan).
    tries = [(text, voice, "WordBoundary"), (clean, voice, "WordBoundary")] + [(clean, v, "WordBoundary") for v in others] \
        + [(clean, others[0] if others else voice, "SentenceBoundary")]
    last, net_errors = None, 0
    for k, (txt, vc, bd) in enumerate(tries):
        if k and (txt, vc, bd) == tries[k - 1]:
            continue
        try:
            words, audio = asyncio.run(run(txt, vc, bd))
        except Exception as exc:                                       # noqa: BLE001 (galat edge-tts/aiohttp)
            last = exc
            if type(exc).__name__ != "NoAudioReceived":
                net_errors += 1
                if net_errors >= 2:
                    break
            continue
        if audio:
            if vc != voice:
                log(f"  Suara Edge {voice} tidak mengirim audio; memakai {vc}.")
            tmp.write_bytes(audio)
            return words if bd == "WordBoundary" else []
    name = type(last).__name__ if last else "tanpa audio"
    if net_errors >= 2:
        raise ClipAgentError(f"Suara Edge tidak bisa dihubungi ({name}: {str(last)[:120]}). Periksa koneksi internet, VPN, "
                             "atau firewall.")
    raise ClipAgentError("Layanan suara Edge (Microsoft) tidak mengirim audio walau sudah dicoba dengan beberapa suara. "
                         "Biasanya ini gangguan sementara di sisi Microsoft atau jaringan yang memblokirnya; coba lagi "
                         "beberapa menit lagi, atau pakai suara Gemini.")


def synthesize(text: str, voice: str, engine: str, style: str, cache_dir: Path, _fallback: bool = True) -> dict:
    """Buat narasi untuk satu adegan. Mengembalikan {'file', 'duration', 'words', 'engine', 'voice'} (di-cache)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise ClipAgentError("Narasi adegan kosong.")
    engine = pick_engine(engine)
    if engine == "gemini" and _BLOCKED.get("gemini", 0) > time.time() and edge_available():
        engine = "edge"                                   # kuota Gemini baru saja habis
    voices = GEMINI_VOICES if engine == "gemini" else EDGE_VOICES
    if voice not in voices:
        voice = edge_default(text) if engine == "edge" else DEFAULT_VOICE[engine]
    model = tts_models()[0] if engine == "gemini" else "edge"
    key = hashlib.sha1(json.dumps([engine, voice, style, text, model]).encode()).hexdigest()[:14]
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav, meta_path = cache_dir / f"vo_{key}.wav", cache_dir / f"vo_{key}.json"
    if wav.is_file() and meta_path.is_file():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    tmp = cache_dir / f"vo_{key}.raw"
    words = None
    if engine == "gemini":
        try:
            _gemini(text, voice, style, tmp)
        except QuotaError as exc:
            if not edge_available():
                raise QuotaError(f"{exc} Atau pasang suara gratis: pip install edge-tts.") from exc
            _BLOCKED["gemini"] = time.time() + 1800
            log(f"{exc} Memakai suara Edge (gratis) untuk sisa narasi.")
            return synthesize(text, edge_default(text), "edge", style, cache_dir, False)
        except ClipAgentError as exc:
            if not (_fallback and edge_available()):
                raise
            log(f"  Suara Gemini gagal ({str(exc).splitlines()[0][:160]}); memakai suara Edge (gratis) untuk narasi ini.")
            return synthesize(text, edge_default(text), "edge", style, cache_dir, False)
    else:
        try:
            words = _edge(text, voice, style, tmp)
        except ClipAgentError as exc:
            if not (_fallback and api_key()):
                raise
            log(f"  {str(exc).splitlines()[0][:200]} Memakai suara Gemini untuk narasi ini.")
            return synthesize(text, "", "gemini", style, cache_dir, False)
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
