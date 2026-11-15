"""Terjemahan subtitle (mis. Indonesia -> Inggris) dengan LLM, lalu waktu dibagi ulang per kata.

Hanya bagian yang menjadi klip yang diterjemahkan, dalam satu atau beberapa permintaan.
Hasil disimpan di cache (translations_<lang>.json) supaya render ulang tidak memanggil LLM lagi.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import Settings
from .llm import LLMClient
from .transcript import Word, group_segments
from .utils import ClipAgentError, log

LANG_NAMES = {"en": "English (natural American English)", "id": "Bahasa Indonesia"}

SYSTEM = """You are a professional subtitle translator for viral short-form videos
(TikTok, Reels, YouTube Shorts) watched by a US audience. Translate each line naturally and
concisely, the way a native speaker would say it. Keep names, numbers and brand names.
Keep each translation roughly as long as the original so it fits the same timing.
Answer ONLY with valid JSON."""

PROMPT = """Translate every line into {lang}. Return the same ids.
Format: {{"lines": [{{"i": 0, "t": "translation"}}]}}

LINES (JSON):
{lines}"""


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def translate_clip_words(cfg: Settings, words: list[Word], ranges: list[tuple[float, float]],
                         target: str, cache_path: Path) -> dict[int, list[Word]]:
    """Terjemahkan kata di setiap rentang klip. Mengembalikan {indeks_rentang: kata_terjemahan}.

    Bila LLM tidak tersedia, rentang yang gagal tidak ada di hasil (pemanggil memakai teks asli).
    """
    cache: dict[str, str] = {}
    if cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}

    # Frasa pendek (≤ ~6 dtk) supaya pembagian waktu per kata tetap mendekati ucapan.
    phrases_per_range = []
    for s, e in ranges:
        inside = [w for w in words if w.end > s + 0.02 and w.start < e - 0.02]
        phrases_per_range.append(group_segments(inside, max_gap=0.6, max_len=6.0, max_chars=90))

    todo = []
    for phrases in phrases_per_range:
        for ph in phrases:
            if _key(ph.text) not in cache and ph.text not in todo:
                todo.append(ph.text)

    if todo:
        if cfg.provider == "heuristic":
            log("Terjemahan subtitle butuh LLM (provider 'heuristic' tidak bisa menerjemahkan); "
                "subtitle memakai bahasa asli.")
            return {}
        client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)
        log(f"Menerjemahkan {len(todo)} baris subtitle ke {target.upper()}...")
        for b in range(0, len(todo), 80):
            batch = todo[b:b + 80]
            payload = json.dumps([{"i": i, "s": t} for i, t in enumerate(batch)], ensure_ascii=False)
            try:
                data = client.complete_json(SYSTEM, PROMPT.format(lang=LANG_NAMES.get(target, target),
                                                                  lines=payload))
            except ClipAgentError as exc:
                log(f"Terjemahan gagal ({str(exc).splitlines()[0]}); subtitle yang belum "
                    "diterjemahkan memakai bahasa asli.")
                break
            for item in data.get("lines", []):
                try:
                    src = batch[int(item["i"])]
                except (KeyError, ValueError, IndexError, TypeError):
                    continue
                txt = str(item.get("t") or "").strip()
                if txt:
                    cache[_key(src)] = txt
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")

    result: dict[int, list[Word]] = {}
    for idx, phrases in enumerate(phrases_per_range):
        out: list[Word] = []
        complete = True
        for ph in phrases:
            tr = cache.get(_key(ph.text))
            if not tr:
                complete = False
                break
            out += _spread(tr, ph.start, ph.end)
        if complete and out:
            result[idx] = out
    return result


def _spread(text: str, start: float, end: float) -> list[Word]:
    """Bagi rentang waktu frasa ke tiap kata, sebanding dengan panjang katanya."""
    toks = text.split()
    if not toks:
        return []
    weights = [len(t) + 2 for t in toks]
    total = sum(weights)
    dur = max(0.2, end - start)
    out, t = [], start
    for tok, w in zip(toks, weights):
        d = dur * w / total
        out.append(Word(round(t, 3), round(t + d, 3), tok))
        t += d
    return out
