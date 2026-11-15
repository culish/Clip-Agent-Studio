"""B-roll dari video stok Pexels (gratis, butuh PEXELS_API_KEY dari pexels.com/api).

Video Pexels boleh dipakai gratis tanpa atribusi wajib; Clip Agent tetap mencatat nama pembuatnya
di metadata agar bisa dicantumkan di deskripsi.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests

from .utils import ClipAgentError, check_cancel, log

DEFAULT_BASE = "https://api.pexels.com"


def api_key() -> str:
    return os.getenv("PEXELS_API_KEY") or ""


def available() -> bool:
    return bool(api_key())


def _base() -> str:
    return (os.getenv("PEXELS_BASE_URL") or DEFAULT_BASE).rstrip("/")


def search(query: str, orientation: str = "portrait", per_page: int = 8) -> list[dict]:
    r = requests.get(f"{_base()}/v1/videos/search", headers={"Authorization": api_key()},
                     params={"query": query, "orientation": orientation, "size": "medium", "per_page": per_page},
                     timeout=30)
    if r.status_code == 401:
        raise ClipAgentError("PEXELS_API_KEY tidak valid.")
    if not r.ok:
        raise ClipAgentError(f"Pexels error HTTP {r.status_code}")
    return r.json().get("videos") or []


def _best_file(video: dict, portrait: bool) -> dict | None:
    files = [f for f in video.get("video_files") or [] if f.get("link") and (f.get("file_type") or "").endswith("mp4")]
    if not files:
        return None
    target = 1080

    def score(f):
        w, h = f.get("width") or 0, f.get("height") or 0
        short = min(w, h) or 1
        ori = (h >= w) == portrait
        return (0 if ori else 1, abs(short - target))
    return sorted(files, key=score)[0]


def fetch(keywords: str, min_dur: float, aspect: str, cache_dir: Path, used: set[int] | None = None) -> dict | None:
    """Unduh satu klip stok yang cocok. Mengembalikan {'path', 'credit', 'id'} atau None."""
    if not available() or not keywords.strip():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    portrait = aspect in ("9:16", "4:5")
    tag = hashlib.sha1(f"{keywords}|{portrait}".encode()).hexdigest()[:10]
    listing = cache_dir / f"pexels_{tag}.json"
    try:
        if listing.is_file():
            videos = json.loads(listing.read_text(encoding="utf-8"))
        else:
            videos = search(keywords, "portrait" if portrait else "landscape")
            listing.write_text(json.dumps(videos), encoding="utf-8")
    except (requests.RequestException, ClipAgentError) as exc:
        log(f"  Pexels: {str(exc)[:120]}")
        return None
    used = used if used is not None else set()
    cands = [v for v in videos if v.get("id") not in used]
    cands.sort(key=lambda v: (0 if (v.get("duration") or 0) >= min_dur else 1, -(v.get("duration") or 0) * 0))
    for v in cands[:3]:
        check_cancel()
        f = _best_file(v, portrait)
        if not f:
            continue
        path = cache_dir / f"pexels_{v['id']}_{f.get('id', 0)}.mp4"
        if not path.is_file():
            try:
                with requests.get(f["link"], stream=True, timeout=120) as r:
                    r.raise_for_status()
                    tmp = path.with_suffix(".part")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_content(1 << 16):
                            check_cancel()
                            fh.write(chunk)
                    tmp.replace(path)
            except requests.RequestException as exc:
                log(f"  Pexels: unduhan gagal ({type(exc).__name__}).")
                continue
        used.add(v.get("id"))
        user = v.get("user") or {}
        return {"path": path, "id": v.get("id"), "credit": f"{user.get('name', 'Pexels')} (Pexels)",
                "page": v.get("url", "")}
    return None
