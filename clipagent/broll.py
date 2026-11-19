"""Media stok gratis untuk b-roll dan foto adegan, dari beberapa penyedia.

Video:  Pexels (PEXELS_API_KEY), Pixabay (PIXABAY_API_KEY).
Foto:   Pexels, Pixabay, lalu Openverse (tanpa key; hanya lisensi CC0, Public Domain Mark, dan CC BY).
Penyedia dicoba berurutan; yang tidak punya key dilewati. Nama pembuat dan lisensi selalu dicatat agar bisa
dicantumkan di deskripsi video (wajib untuk CC BY, dianjurkan untuk yang lain).
Hasil pencarian disimpan di cache (Pixabay mewajibkan cache 24 jam) dan file diunduh ke folder proyek,
bukan ditautkan langsung.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests

from .utils import ClipAgentError, check_cancel, log

UA = {"User-Agent": "ClipAgentStudio/1.0 (+https://github.com/culish/Clip-Agent-Studio)"}


def api_key() -> str:
    return os.getenv("PEXELS_API_KEY") or ""


def pixabay_key() -> str:
    return os.getenv("PIXABAY_API_KEY") or ""


def openverse_on() -> bool:
    return (os.getenv("OPENVERSE_ENABLED") or "1").strip().lower() not in ("0", "false", "no", "tidak")


def _base() -> str:
    return (os.getenv("PEXELS_BASE_URL") or "https://api.pexels.com").rstrip("/")


def _pixabay_base() -> str:
    return (os.getenv("PIXABAY_BASE_URL") or "https://pixabay.com").rstrip("/")


def _openverse_base() -> str:
    return (os.getenv("OPENVERSE_BASE_URL") or "https://api.openverse.org").rstrip("/")


def video_providers() -> list[str]:
    return [n for n, ok in (("Pexels", bool(api_key())), ("Pixabay", bool(pixabay_key()))) if ok]


def photo_providers() -> list[str]:
    return video_providers() + (["Openverse"] if openverse_on() else [])


def available() -> bool:
    """Ada penyedia VIDEO stok (untuk b-roll)."""
    return bool(video_providers())


def photos_available() -> bool:
    return bool(photo_providers())


def label() -> str:
    return "/".join(video_providers()) or "stok"


# ---------------------------------------------------------------- unduh + cache
def _cached(listing: Path, fetch) -> list:
    if listing.is_file():
        try:
            return json.loads(listing.read_text(encoding="utf-8"))
        except ValueError:
            pass
    items = fetch()
    listing.write_text(json.dumps(items), encoding="utf-8")
    return items


def _download(url: str, path: Path, what: str) -> bool:
    if path.is_file():
        return True
    try:
        with requests.get(url, stream=True, timeout=120, headers=UA) as r:
            r.raise_for_status()
            tmp = path.with_suffix(path.suffix + ".part")
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(1 << 16):
                    check_cancel()
                    fh.write(chunk)
            tmp.replace(path)
        return True
    except requests.RequestException as exc:
        log(f"  {what}: unduhan gagal ({type(exc).__name__}).")
        return False


def _http(url: str, params: dict, what: str, headers: dict | None = None) -> dict:
    r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=30)
    if r.status_code in (401, 403):
        raise ClipAgentError(f"{what}: key tidak valid atau akses ditolak (HTTP {r.status_code}).")
    if r.status_code == 429:
        raise ClipAgentError(f"{what}: batas permintaan tercapai, coba lagi nanti.")
    if not r.ok:
        raise ClipAgentError(f"{what} error HTTP {r.status_code}")
    return r.json()


# ---------------------------------------------------------------- VIDEO
def search(query: str, orientation: str = "portrait", per_page: int = 8) -> list[dict]:
    """Pencarian video Pexels (dipertahankan untuk kompatibilitas)."""
    return _http(f"{_base()}/v1/videos/search", {"query": query, "orientation": orientation, "size": "medium",
                                                  "per_page": per_page}, "Pexels", {"Authorization": api_key()}).get("videos") or []


def _pexels_videos(q: str, portrait: bool, cache: Path) -> list[dict]:
    tag = hashlib.sha1(f"{q}|{portrait}".encode()).hexdigest()[:10]
    vids = _cached(cache / f"pexels_{tag}.json", lambda: search(q, "portrait" if portrait else "landscape"))
    out = []
    for v in vids:
        files = [f for f in v.get("video_files") or [] if f.get("link") and (f.get("file_type") or "").endswith("mp4")]
        if not files:
            continue
        f = sorted(files, key=lambda f: (0 if ((f.get("height") or 0) >= (f.get("width") or 0)) == portrait else 1,
                                         abs(min(f.get("width") or 0, f.get("height") or 0) - 1080)))[0]
        user = v.get("user") or {}
        out.append({"id": f"px{v.get('id')}", "url": f["link"], "duration": v.get("duration") or 0,
                    "portrait": (f.get("height") or 0) >= (f.get("width") or 0), "file": f"pexels_{v['id']}_{f.get('id', 0)}.mp4",
                    "credit": f"{user.get('name', 'Pexels')} (Pexels)", "page": v.get("url", "")})
    return out


def _pixabay_videos(q: str, portrait: bool, cache: Path) -> list[dict]:
    tag = hashlib.sha1(f"pbv|{q}".encode()).hexdigest()[:10]
    hits = _cached(cache / f"pixabay_v_{tag}.json", lambda: _http(
        f"{_pixabay_base()}/api/videos/", {"key": pixabay_key(), "q": q[:100], "safesearch": "true", "per_page": 12},
        "Pixabay").get("hits") or [])
    out = []
    for h in hits:
        vs = h.get("videos") or {}
        f = next((vs[k] for k in ("medium", "large", "small") if (vs.get(k) or {}).get("url")), None)
        if not f:
            continue
        out.append({"id": f"pb{h.get('id')}", "url": f["url"], "duration": h.get("duration") or 0,
                    "portrait": (f.get("height") or 0) >= (f.get("width") or 0), "file": f"pixabay_{h.get('id')}.mp4",
                    "credit": f"{h.get('user', 'Pixabay')} (Pixabay)", "page": h.get("pageURL", "")})
    return out


def fetch(keywords: str, min_dur: float, aspect: str, cache_dir: Path, used: set | None = None) -> dict | None:
    """Unduh satu klip video stok yang cocok. Mengembalikan {'path', 'credit', 'id', 'page'} atau None."""
    if not available() or not keywords.strip():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    portrait = aspect in ("9:16", "4:5")
    used = used if used is not None else set()
    for name, fn, ok in (("Pexels", _pexels_videos, bool(api_key())), ("Pixabay", _pixabay_videos, bool(pixabay_key()))):
        if not ok:
            continue
        try:
            cands = [c for c in fn(keywords, portrait, cache_dir) if c["id"] not in used]
        except (requests.RequestException, ClipAgentError, ValueError) as exc:
            log(f"  {name}: {str(exc)[:120]}")
            continue
        cands.sort(key=lambda c: (0 if c["duration"] >= min_dur else 1, 0 if c["portrait"] == portrait else 1))
        for c in cands[:3]:
            check_cancel()
            path = cache_dir / c["file"]
            if _download(c["url"], path, name):
                used.add(c["id"])
                return {"path": path, "id": c["id"], "credit": c["credit"], "page": c["page"]}
    return None


# ---------------------------------------------------------------- FOTO
def _pexels_photos(q: str, portrait: bool, cache: Path) -> list[dict]:
    tag = hashlib.sha1(f"photo|{q}|{portrait}".encode()).hexdigest()[:10]
    photos = _cached(cache / f"pexels_photo_{tag}.json", lambda: _http(
        f"{_base()}/v1/search", {"query": q, "orientation": "portrait" if portrait else "landscape", "per_page": 8},
        "Pexels foto", {"Authorization": api_key()}).get("photos") or [])
    out = []
    for ph in photos:
        src = (ph.get("src") or {}).get("large2x") or (ph.get("src") or {}).get("large")
        if src:
            out.append({"id": f"px{ph.get('id')}", "url": src, "file": f"pexels_{ph.get('id')}.jpg",
                        "credit": f"Foto: {ph.get('photographer', 'Pexels')} / Pexels", "page": ph.get("url", ""), "license": "Pexels"})
    return out


def _pixabay_photos(q: str, portrait: bool, cache: Path) -> list[dict]:
    tag = hashlib.sha1(f"pbp|{q}|{portrait}".encode()).hexdigest()[:10]
    hits = _cached(cache / f"pixabay_p_{tag}.json", lambda: _http(
        f"{_pixabay_base()}/api/", {"key": pixabay_key(), "q": q[:100], "image_type": "photo", "safesearch": "true",
                                    "orientation": "vertical" if portrait else "horizontal", "per_page": 10}, "Pixabay").get("hits") or [])
    return [{"id": f"pb{h.get('id')}", "url": h["largeImageURL"], "file": f"pixabay_{h.get('id')}.jpg",
             "credit": f"Foto: {h.get('user', 'Pixabay')} / Pixabay", "page": h.get("pageURL", ""), "license": "Pixabay"}
            for h in hits if h.get("largeImageURL")]


def _openverse_photos(q: str, portrait: bool, cache: Path) -> list[dict]:
    tag = hashlib.sha1(f"ov|{q}|{portrait}".encode()).hexdigest()[:10]
    res = _cached(cache / f"openverse_{tag}.json", lambda: _http(
        f"{_openverse_base()}/v1/images/", {"q": q[:200], "license": "cc0,pdm,by", "page_size": 20, "mature": "false",
                                            "aspect_ratio": "tall" if portrait else "wide"}, "Openverse").get("results") or [])
    out = []
    for it in res:
        if not it.get("url") or (it.get("width") or 0) and (it.get("width") or 0) < 700:
            continue
        lic = (it.get("license") or "").lower()
        lic_txt = {"cc0": "CC0", "pdm": "Domain publik"}.get(lic, f"CC {lic.upper()} {it.get('license_version') or ''}".strip())
        title = (it.get("title") or "foto").strip()[:60]
        who = (it.get("creator") or "tidak diketahui").strip()[:50]
        out.append({"id": f"ov{it.get('id')}", "url": it["url"], "file": f"openverse_{hashlib.sha1(it['url'].encode()).hexdigest()[:12]}.jpg",
                    "credit": f"\"{title}\" oleh {who}, {lic_txt} (via Openverse) {it.get('foreign_landing_url') or ''}".strip(),
                    "page": it.get("foreign_landing_url", ""), "license": lic_txt})
    return out


def fetch_photo(query: str, portrait: bool, cache_dir: Path, used: set | None = None) -> dict | None:
    """Unduh satu foto stok. Mengembalikan {'path', 'credit', 'id', 'page', 'license', 'provider'} atau None."""
    if not query.strip():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    used = used if used is not None else set()
    for name, fn, ok in (("Pexels", _pexels_photos, bool(api_key())), ("Pixabay", _pixabay_photos, bool(pixabay_key())),
                         ("Openverse", _openverse_photos, openverse_on())):
        if not ok:
            continue
        try:
            cands = [c for c in fn(query, portrait, cache_dir) if c["id"] not in used]
        except (requests.RequestException, ClipAgentError, ValueError) as exc:
            log(f"  {name}: {str(exc)[:120]}")
            continue
        for c in cands[:4]:
            check_cancel()
            path = cache_dir / c["file"]
            if _download(c["url"], path, name):
                used.add(c["id"])
                return {"path": path, "id": c["id"], "credit": c["credit"], "page": c["page"], "license": c["license"],
                        "provider": name}
    return None
