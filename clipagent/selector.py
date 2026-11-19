"""Otak agen: memilih momen terbaik dari transkrip, lalu merapikan batas klip."""
from __future__ import annotations

import bisect
import math
import os

from .config import Settings
from .llm import LLMClient, LLMUnavailable
from .transcript import Segment, Word, to_prompt_lines
from .utils import ClipAgentError, fmt_ts, log

SYSTEM_PROMPT = """Anda adalah editor video pendek (TikTok, Instagram Reels, YouTube Shorts) yang sangat berpengalaman.
Tugas Anda: membaca transkrip bertimestamp lalu memilih potongan yang paling berpotensi menarik penonton
dan tetap utuh maknanya bila ditonton sendiri.

Kriteria klip yang bagus:
1. Dibuka dengan hook kuat di 3 detik pertama (pertanyaan, pernyataan mengejutkan, konflik, angka, janji manfaat).
2. Berdiri sendiri: penonton paham tanpa menonton video penuh.
3. Berisi satu ide/cerita utuh dengan akhir yang jelas (punchline, kesimpulan, atau insight).
4. Mulai dan selesai di batas kalimat; jangan memotong di tengah kalimat.
5. Hindari pembuka/penutup basa-basi, iklan sponsor, dan ajakan subscribe.

Jawab HANYA dengan JSON yang valid, tanpa teks lain."""

SELECT_TEMPLATE = """Judul video: {title}
Channel: {channel}
Durasi total: {total}
Deskripsi (cuplikan): {desc}

Target penonton: {audience}
Arahan tambahan dari pengguna: {instructions}

Pilih {k} klip terbaik dari transkrip di bawah (bagian {t0}–{t1} dari video).
Aturan:
- Durasi tiap klip {min_d:.0f}–{max_d:.0f} detik.
- "start" dan "end" dalam detik (angka desimal), mengikuti timestamp transkrip.
- Klip tidak boleh saling tumpang tindih.
- Tulis "title", "hook", "caption", dan "hashtags" dalam bahasa {lang}.
- "score" 0-100 = perkiraan potensi klip menarik penonton.

Format JSON:
{{"clips": [{{"start": 12.3, "end": 55.0, "title": "judul singkat, maks 60 karakter", "hook": "kalimat pembuka yang bikin penasaran", "reason": "alasan singkat klip ini dipilih", "caption": "caption media sosial 1-2 kalimat", "hashtags": ["#contoh"], "score": 85}}]}}

TRANSKRIP ([mulai-selesai] teks):
{lines}"""

RANK_TEMPLATE = """Judul video: {title}
Target penonton: {audience}
Arahan tambahan dari pengguna: {instructions}

Berikut kandidat klip dari seluruh video. Pilih {k} kandidat terbaik sebagai klip pendek yang berdiri sendiri,
urutkan dari yang terbaik. Boleh perbaiki "title", "caption", dan "hashtags" (bahasa {lang}).

Format JSON:
{{"selected": [{{"id": 3, "score": 90, "title": "...", "caption": "...", "hashtags": ["#..."]}}]}}

KANDIDAT:
{cands}"""


AUDIENCE_TEXT = {
    "us": ("penonton Amerika Serikat / global berbahasa Inggris (pasar iklan CPM tinggi). Utamakan momen "
           "yang relevan dan mudah dipahami penonton AS: uang & investasi, bisnis, karier, teknologi & AI, "
           "kesehatan & produktivitas, kisah inspiratif, opini tegas. Hindari rujukan yang hanya dipahami "
           "penonton lokal, dan hindari konten yang tidak ramah pengiklan (kekerasan, tragedi, kata kasar). "
           "Judul dan caption ditulis dengan gaya kreator AS, hashtag yang umum dipakai di AS."),
    "id": "penonton Indonesia.",
}


# ====================================================================== publik
def select_clips(cfg: Settings, meta: dict, words: list[Word], segments: list[Segment],
                 total: float) -> list[dict]:
    if not segments:
        raise ClipAgentError("Transkrip kosong: video tidak berisi ucapan yang bisa dianalisis.")
    if total < cfg.min_dur:
        raise ClipAgentError(f"Video terlalu pendek ({total:.0f} dtk) untuk klip minimal {cfg.min_dur:.0f} dtk.")

    if cfg.provider == "heuristic":
        if cfg.instructions:
            log("Catatan: mode heuristic tidak bisa mengikuti --instructions (butuh LLM).")
        raw = _heuristic(segments, cfg, total)
    else:
        try:
            raw = _llm_select(cfg, meta, segments, total)
        except LLMUnavailable as exc:
            log(str(exc))
            log("PERINGATAN: LLM tidak tersedia, jadi klip dipilih dengan mode heuristic (tanpa AI).")
            log("Video & transkrip sudah tersimpan; jalankan ulang perintah yang sama nanti "
                "untuk hasil pilihan AI (tidak perlu unduh ulang).")
            raw = _heuristic(segments, cfg, total)

    clips = []
    for c in raw:
        try:
            s, e = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        s, e = snap_bounds(s, e, segments, words, cfg.min_dur, cfg.max_dur, total)
        if e - s < cfg.min_dur * 0.7:
            continue
        c.update(start=round(s, 2), end=round(e, 2), duration=round(e - s, 2))
        c["score"] = _to_score(c.get("score"))
        clips.append(c)

    clips = _dedupe(clips)[: cfg.num_clips]
    for i, c in enumerate(clips, 1):
        c["rank"] = i
        c["text"] = _text_between(words, c["start"], c["end"])
        c.setdefault("title", f"Klip {i}")
        c["hashtags"] = [h if str(h).startswith("#") else f"#{h}" for h in (c.get("hashtags") or [])]
    if not clips:
        raise ClipAgentError("Agen tidak menemukan klip yang valid. Coba ubah --min/--max atau model LLM.")
    return clips


# ====================================================================== LLM
def _llm_select(cfg: Settings, meta: dict, segments: list[Segment], total: float) -> list[dict]:
    client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key,
                       fallbacks=cfg.fallback_models)
    limit = int(os.getenv("CHUNK_CHARS") or (9000 if cfg.provider == "ollama" else 60000))
    chunks = _chunk(segments, limit)
    log(f"Agen ({cfg.provider}/{client.model}) menganalisis transkrip dalam {len(chunks)} bagian...")

    candidates: list[dict] = []
    for idx, chunk in enumerate(chunks, 1):
        t0, t1 = chunk[0].start, chunk[-1].end
        share = (t1 - t0) / max(total, 1)
        k = cfg.num_clips + 2 if len(chunks) == 1 else max(2, math.ceil(cfg.num_clips * share * 1.6))
        prompt = SELECT_TEMPLATE.format(
            title=meta.get("title", "-"), channel=meta.get("channel", "-") or "-",
            total=fmt_ts(total), desc=(meta.get("description") or "-")[:600].replace("\n", " "),
            audience=AUDIENCE_TEXT.get(cfg.audience, AUDIENCE_TEXT["id"]),
            instructions=cfg.instructions or "-", k=k, t0=fmt_ts(t0), t1=fmt_ts(t1),
            min_d=cfg.min_dur, max_d=cfg.max_dur, lang=cfg.output_language,
            lines=to_prompt_lines(chunk),
        )
        try:
            data = client.complete_json(SYSTEM_PROMPT, prompt, list_key="clips")
        except LLMUnavailable:
            if not candidates:
                raise
            log(f"LLM tidak tersedia; memakai {len(candidates)} kandidat dari bagian sebelumnya.")
            break
        got = [c for c in data.get("clips", []) if isinstance(c, dict)]
        log(f"  bagian {idx}/{len(chunks)}: {len(got)} kandidat")
        candidates += got

    if len(chunks) > 1 and len(candidates) > cfg.num_clips:
        candidates = _rank(client, cfg, meta, segments, candidates)
    return candidates


def _rank(client: LLMClient, cfg: Settings, meta: dict, segments: list[Segment],
          cands: list[dict]) -> list[dict]:
    lines = []
    for i, c in enumerate(cands):
        try:
            s, e = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        txt = " ".join(seg.text for seg in segments if seg.end > s and seg.start < e)
        lines.append(f'[id {i}] {fmt_ts(s)}-{fmt_ts(e)} | {c.get("title", "")}\n{txt[:900]}')
    prompt = RANK_TEMPLATE.format(title=meta.get("title", "-"), instructions=cfg.instructions or "-",
                                  audience=AUDIENCE_TEXT.get(cfg.audience, AUDIENCE_TEXT["id"]),
                                  k=cfg.num_clips, lang=cfg.output_language, cands="\n\n".join(lines))
    try:
        data = client.complete_json(SYSTEM_PROMPT, prompt, list_key="selected")
    except ClipAgentError as exc:
        log(f"Tahap pemeringkatan gagal ({exc}); memakai skor awal.")
        return cands
    ranked = []
    for pos, sel in enumerate(data.get("selected", [])):
        try:
            c = dict(cands[int(sel["id"])])
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        for key in ("title", "caption", "hashtags"):
            if sel.get(key):
                c[key] = sel[key]
        c["score"] = _to_score(sel.get("score"), fallback=100 - pos)
        ranked.append(c)
    return ranked or cands


def _chunk(segments: list[Segment], limit: int, overlap_sec: float = 45.0) -> list[list[Segment]]:
    chunks, cur, size = [], [], 0
    for seg in segments:
        line = len(seg.text) + 16
        if cur and size + line > limit:
            chunks.append(cur)
            tail_start = cur[-1].end - overlap_sec
            cur = [s for s in cur if s.start >= tail_start]
            size = sum(len(s.text) + 16 for s in cur)
        cur.append(seg)
        size += line
    if cur:
        chunks.append(cur)
    return chunks


# ====================================================================== heuristik
def _heuristic(segments: list[Segment], cfg: Settings, total: float) -> list[dict]:
    """Tanpa AI: pilih jendela dengan bicara paling padat & sedikit jeda."""
    log("Mode heuristic (tanpa AI): memilih bagian dengan bicara paling padat.")
    target = min(cfg.max_dur, max(cfg.min_dur, (cfg.min_dur + cfg.max_dur) / 2))
    windows = []
    for i, seg in enumerate(segments):
        s = seg.start
        j, n_words, speech = i, 0, 0.0
        while j < len(segments) and segments[j].end - s <= target:
            n_words += len(segments[j].words)
            speech += segments[j].end - segments[j].start
            j += 1
        if j == i:
            continue
        e = segments[j - 1].end
        dur = e - s
        if dur < cfg.min_dur:
            continue
        density = n_words / dur
        fullness = speech / dur
        q_bonus = 0.3 if "?" in seg.text else 0.0
        windows.append({"start": s, "end": e, "score": density * fullness + q_bonus,
                        "title": " ".join(seg.text.split()[:8]),
                        "hook": seg.text[:100], "reason": "Bicara padat dengan sedikit jeda",
                        "caption": "", "hashtags": []})
    if not windows:
        raise ClipAgentError("Tidak ada jendela yang memenuhi durasi minimum.")
    best = max(w["score"] for w in windows) or 1
    for w in windows:
        w["score"] = round(100 * w["score"] / best)
    return _dedupe(windows)[: cfg.num_clips]


# ====================================================================== perapian batas
def snap_bounds(start: float, end: float, segments: list[Segment], words: list[Word],
                min_d: float, max_d: float, total: float) -> tuple[float, float]:
    """Geser start/end ke batas kalimat/kata terdekat dan paksa durasi min–maks."""
    if end < start:
        start, end = end, start
    start, end = max(0.0, start), min(total, end)
    seg_starts = [s.start for s in segments]
    seg_ends = [s.end for s in segments]
    w_starts = [w.start for w in words]
    w_ends = [w.end for w in words]

    s = _nearest(seg_starts, start, 3.0)
    if s is None:
        s = _nearest(w_starts, start, 2.0)
    s = start if s is None else s
    e = _nearest(seg_ends, end, 3.0)
    if e is None:
        e = _nearest(w_ends, end, 2.0)
    e = end if e is None else e

    if e - s > max_d:
        e = _last_le(seg_ends, s + max_d, s + min_d) or _last_le(w_ends, s + max_d, s + min_d) or s + max_d
    if e - s < min_d:
        e = (_first_ge(seg_ends, s + min_d, s + max_d) or _first_ge(w_ends, s + min_d, s + max_d)
             or s + min_d)
    if e > total:  # mentok di akhir video: mundurkan awal klip
        e = total
        if e - s < min_d:
            target = max(0.0, e - min_d)
            s = _last_le(seg_starts, target, max(0.0, e - max_d)) or target
    s = max(0.0, s - 0.15)
    e = min(total, e + 0.35)
    return s, e


def _nearest(values: list[float], x: float, tol: float) -> float | None:
    if not values:
        return None
    i = bisect.bisect_left(values, x)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(values) and abs(values[j] - x) <= tol:
            if best is None or abs(values[j] - x) < abs(best - x):
                best = values[j]
    return best


def _last_le(values: list[float], hi: float, lo: float) -> float | None:
    i = bisect.bisect_right(values, hi) - 1
    return values[i] if i >= 0 and values[i] >= lo else None


def _first_ge(values: list[float], lo: float, hi: float) -> float | None:
    i = bisect.bisect_left(values, lo)
    return values[i] if i < len(values) and values[i] <= hi else None


def _dedupe(clips: list[dict], max_overlap: float = 0.25) -> list[dict]:
    kept: list[dict] = []
    for c in sorted(clips, key=lambda c: _to_score(c.get("score")), reverse=True):
        s, e = float(c["start"]), float(c["end"])
        ok = True
        for k in kept:
            inter = min(e, k["end"]) - max(s, k["start"])
            if inter > max_overlap * min(e - s, k["end"] - k["start"]):
                ok = False
                break
        if ok:
            kept.append(c)
    return kept


def _to_score(v, fallback: float = 50) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(fallback)


def _text_between(words: list[Word], s: float, e: float) -> str:
    return " ".join(w.text for w in words if w.start >= s - 0.05 and w.start < e)
