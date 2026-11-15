"""Transkrip bertimestamp per kata: dari subtitle YouTube (json3) atau Whisper lokal."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .utils import ClipAgentError, check_cancel, log, progress


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


# ---------------------------------------------------------------- subtitle YouTube
def words_from_json3(data: dict) -> list[Word]:
    """Ubah format json3 YouTube menjadi daftar kata bertimestamp.

    Auto-caption menyimpan offset tiap kata (tOffsetMs); subtitle manual hanya
    per baris, sehingga waktunya dibagi rata ke tiap kata di baris itu.
    """
    words: list[Word] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0) / 1000.0
        dur = ev.get("dDurationMs", 0) / 1000.0
        pieces = [(s.get("utf8", ""), s.get("tOffsetMs")) for s in segs]
        pieces = [(t, o) for t, o in pieces if t.strip()]
        if not pieces:
            continue
        if len(pieces) == 1:
            toks = pieces[0][0].split()
            step = (dur / len(toks)) if dur > 0 else 0.3
            for i, tok in enumerate(toks):
                words.append(Word(t0 + i * step, t0 + (i + 1) * step, tok))
        else:
            ev_words = []
            for txt, off in pieces:
                ws = t0 + (off or 0) / 1000.0
                for tok in txt.split():
                    ev_words.append(Word(ws, -1.0, tok))
            for i, w in enumerate(ev_words):
                # kata terakhir di baris berakhir paling lambat di akhir baris itu
                w.end = ev_words[i + 1].start if i + 1 < len(ev_words) else (t0 + dur if dur > 0 else -1.0)
            words += ev_words
    return _finalize(words)


def _finalize(words: list[Word]) -> list[Word]:
    """Urutkan, buang duplikat & tag seperti [Musik], dan lengkapi waktu akhir kata."""
    words.sort(key=lambda w: w.start)
    cleaned: list[Word] = []
    in_tag = False
    for w in words:
        tok = w.text.strip()
        if tok.startswith("["):
            in_tag = not tok.endswith("]")
            continue
        if in_tag:
            if tok.endswith("]"):
                in_tag = False
            continue
        if cleaned and abs(cleaned[-1].start - w.start) < 1e-3 and cleaned[-1].text == tok:
            continue
        cleaned.append(Word(w.start, w.end, tok))
    for i, w in enumerate(cleaned):
        nxt = cleaned[i + 1].start if i + 1 < len(cleaned) else w.start + 0.8
        if w.end <= w.start:
            w.end = w.start + 0.9
        w.end = min(w.end, nxt, w.start + 1.5)
        if w.end <= w.start:
            w.end = w.start + 0.05
    return cleaned


# ---------------------------------------------------------------- Whisper
def words_from_whisper(media: Path, model_size: str = "small", language: str | None = None,
                       prog_range: tuple[float, float] = (0.0, 1.0)) -> tuple[list[Word], str]:
    """Transkripsi lokal. Mengembalikan (kata, kode_bahasa)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ClipAgentError(
            "Video ini tidak punya subtitle, dan faster-whisper belum terpasang.\n"
            "Jalankan: pip install -r requirements-whisper.txt\n"
            "(butuh Python 3.10–3.14; cek dengan: python --version)"
        ) from exc

    device, compute = "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device, compute = "cuda", "float16"
    except Exception:
        pass
    log(f"Transkripsi Whisper '{model_size}' di {device.upper()} (bisa beberapa menit)...")
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute)
    except Exception as exc:
        raise ClipAgentError(
            f"Gagal memuat model Whisper '{model_size}' ({type(exc).__name__}: {str(exc)[:200]}).\n"
            "Pemakaian pertama perlu internet untuk mengunduh model dari Hugging Face."
        ) from exc
    segments, info = model.transcribe(
        str(media), language=language or None, word_timestamps=True,
        vad_filter=True, beam_size=5,
    )
    total = float(getattr(info, "duration", 0) or 0)
    p0, p1 = prog_range
    words: list[Word] = []
    for seg in segments:
        check_cancel()
        for w in seg.words or []:
            if w.word.strip():
                words.append(Word(float(w.start), float(w.end), w.word.strip()))
        if total:
            progress(p0 + (p1 - p0) * min(1.0, seg.end / total), "Transkripsi Whisper")
    log(f"Bahasa terdeteksi: {info.language} (p={info.language_probability:.2f})")
    return _finalize(words), info.language


# Kata umum bahasa Inggris untuk menebak bahasa transkrip lama yang belum menyimpan kode bahasa.
_EN_COMMON = set("""the and to of a in is it you that i for this was on with be are have not
but they we so what can do just like my your if all about there one at or as from""".split())


def guess_lang(words: list[Word]) -> str:
    sample = [w.text.lower().strip(".,!?\"'") for w in words[:600]]
    if not sample:
        return ""
    ratio = sum(t in _EN_COMMON for t in sample) / len(sample)
    return "en" if ratio > 0.12 else ""


def lang_from_caption_source(source: str) -> str:
    """'youtube-auto:id-orig' -> 'id', 'youtube-manual:en-US' -> 'en', 'whisper-small:en' -> 'en'."""
    tail = source.split(":", 1)[1] if ":" in source else ""
    return tail.split("-")[0].split(" ")[0].lower()


# ---------------------------------------------------------------- segmentasi
def group_segments(words: list[Word], max_gap: float = 0.8, max_len: float = 9.0,
                   max_chars: int = 140) -> list[Segment]:
    """Gabungkan kata menjadi kalimat/frasa berdasar tanda baca, jeda, dan panjang."""
    segments: list[Segment] = []
    cur: list[Word] = []

    def flush():
        if cur:
            segments.append(Segment(cur[0].start, cur[-1].end,
                                    " ".join(w.text for w in cur), list(cur)))
            cur.clear()

    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            length = w.end - cur[0].start
            chars = sum(len(x.text) + 1 for x in cur)
            sentence_end = cur[-1].text[-1:] in ".?!" and length > 1.5
            if gap > max_gap or length > max_len or chars > max_chars or sentence_end:
                flush()
        cur.append(w)
    flush()
    return segments


def to_prompt_lines(segments: list[Segment]) -> str:
    return "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in segments)


def save_words(words: list[Word], path: Path, source: str, lang: str = "") -> None:
    path.write_text(json.dumps({"source": source, "lang": lang, "words": [asdict(w) for w in words]},
                               ensure_ascii=False), encoding="utf-8")


def load_words(path: Path) -> tuple[list[Word], str, str]:
    """Mengembalikan (kata, sumber, kode_bahasa)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    words = [Word(**w) for w in data["words"]]
    source = data.get("source", "?")
    lang = data.get("lang") or lang_from_caption_source(source) or guess_lang(words)
    return words, source, lang
