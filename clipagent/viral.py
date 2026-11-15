"""Riset video viral: cari video yang sedang naik cepat lalu beri skor.

Skor viral (0–100) menggabungkan:
- kecepatan: views per jam sejak diunggah (bobot 50%)
- outlier: views dibanding jumlah subscriber channel; 10x berarti video ini jauh di atas biasanya (35%)
- interaksi: (like + 2×komentar) / views (15%)
Sumber data: YouTube Data API v3 bila YOUTUBE_API_KEY diisi (cepat dan lengkap), selain itu yt-dlp.
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from .trends import classify, niche_info, search_youtube
from .utils import ClipAgentError, log

YT_BASE = "https://www.googleapis.com/youtube/v3"
_CACHE: dict[str, tuple[float, dict]] = {}
PERIOD_HOURS = {"today": 24, "week": 24 * 7, "month": 24 * 30, "year": 24 * 365}


def api_key() -> str:
    return os.getenv("YOUTUBE_API_KEY") or ""


def _base() -> str:
    return (os.getenv("YT_API_BASE") or YT_BASE).rstrip("/")


def _iso_dur(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def _ts(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


# ---------------------------------------------------------------- YouTube Data API
def _get(path: str, **params) -> dict:
    params["key"] = api_key()
    r = requests.get(f"{_base()}/{path}", params=params, timeout=30)
    if r.status_code == 403 and "quota" in r.text.lower():
        raise ClipAgentError("Kuota YouTube Data API hari ini habis. Coba besok, atau kosongkan YOUTUBE_API_KEY agar memakai yt-dlp.")
    if not r.ok:
        raise ClipAgentError(f"YouTube Data API error HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _details(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    vids = _get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[:50]), maxResults=50)
    items = vids.get("items") or []
    chan_ids = sorted({i["snippet"]["channelId"] for i in items if i.get("snippet")})
    subs = {}
    if chan_ids:
        for c in _get("channels", part="statistics", id=",".join(chan_ids[:50])).get("items") or []:
            st = c.get("statistics") or {}
            subs[c["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount") or 0)
    out = []
    for i in items:
        sn, st = i.get("snippet") or {}, i.get("statistics") or {}
        out.append({"id": i["id"], "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                    "channel_id": sn.get("channelId", ""), "timestamp": _ts(sn.get("publishedAt", "")),
                    "duration": _iso_dur((i.get("contentDetails") or {}).get("duration", "")),
                    "views": int(st.get("viewCount") or 0), "likes": int(st.get("likeCount") or 0),
                    "comments": int(st.get("commentCount") or 0), "subscribers": subs.get(sn.get("channelId")),
                    "cc": (i.get("status") or {}).get("license") == "creativeCommon",
                    "tags": (sn.get("tags") or [])[:12], "category": sn.get("categoryId", "")})
    return out


def _api_search(query: str, period: str, length: str, cc: bool, limit: int) -> list[dict]:
    params = {"part": "snippet", "type": "video", "q": query, "order": "viewCount", "regionCode": "US",
              "relevanceLanguage": "en", "maxResults": min(50, limit * 2)}
    if period in PERIOD_HOURS:
        after = datetime.now(timezone.utc) - timedelta(hours=PERIOD_HOURS[period])
        params["publishedAfter"] = after.strftime("%Y-%m-%dT%H:%M:%SZ")
    if length in ("short", "medium", "long"):
        params["videoDuration"] = length
    if cc:
        params["videoLicense"] = "creativeCommon"
    ids = [i["id"]["videoId"] for i in _get("search", **params).get("items") or [] if i.get("id", {}).get("videoId")]
    out = _details(ids)
    if cc:
        for v in out:
            v["cc"] = True
    return out


def trending_chart(category: str = "", limit: int = 30) -> list[dict]:
    """Daftar video paling populer di AS saat ini (butuh YOUTUBE_API_KEY)."""
    if not api_key():
        raise ClipAgentError("Daftar populer AS butuh YOUTUBE_API_KEY (gratis, isi di Pengaturan).")
    params = {"part": "id", "chart": "mostPopular", "regionCode": "US", "maxResults": min(50, limit)}
    if category:
        params["videoCategoryId"] = category
    ids = [i["id"] for i in _get("videos", **params).get("items") or []]
    return _details(ids)


# ---------------------------------------------------------------- yt-dlp
def _enrich_one(v: dict) -> dict:
    try:
        import yt_dlp
        from .download import _QuietLogger
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "logger": _QuietLogger(),
                "socket_timeout": 20}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(v["url"], download=False, process=False)
    except Exception:
        return v
    return {**v, "subscribers": info.get("channel_follower_count"), "likes": info.get("like_count") or 0,
            "comments": info.get("comment_count") or 0, "timestamp": info.get("timestamp") or v.get("timestamp"),
            "tags": (info.get("tags") or [])[:12], "channel_id": info.get("channel_id", ""),
            "cc": v.get("cc") or (info.get("license") or "").lower().startswith("creative commons")}


def _ytdlp_search(query: str, period: str, length: str, cc: bool, limit: int, enrich: bool) -> list[dict]:
    res = search_youtube(query, cc=cc, period=period, length=length, sort="views", limit=limit,
                         cookies_from_browser=os.getenv("COOKIES_FROM_BROWSER", ""), region="US")
    items = res["results"]
    if enrich and items:
        with ThreadPoolExecutor(4) as ex:
            items = list(ex.map(_enrich_one, items[:12])) + items[12:]
    return items


# ---------------------------------------------------------------- skor
def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for pos, i in enumerate(order):
        ranks[i] = pos / max(1, len(values) - 1)
    return ranks


def score(items: list[dict]) -> list[dict]:
    now = time.time()
    for v in items:
        ts = v.get("timestamp") or 0
        hours = max(1.0, (now - ts) / 3600) if ts else None
        v["age_hours"] = round(hours, 1) if hours else None
        v["vph"] = round(v["views"] / hours, 1) if hours else None
        subs = v.get("subscribers")
        v["outlier"] = round(v["views"] / max(1000, subs), 2) if subs is not None and subs >= 0 else None
        v["engagement"] = round((v.get("likes", 0) + 2 * v.get("comments", 0)) / v["views"], 4) if v.get("views") else None
    parts = [("vph", 0.5), ("outlier", 0.35), ("engagement", 0.15)]
    ranks = {k: _rank([v.get(k) or 0 for v in items]) for k, _ in parts}
    for i, v in enumerate(items):
        got = [(ranks[k][i], w) for k, w in parts if v.get(k) is not None]
        v["score"] = round(100 * sum(r * w for r, w in got) / sum(w for _, w in got)) if got else 0
        v["label"] = ("Sedang meledak" if v["score"] >= 80 else "Naik cepat" if v["score"] >= 60
                      else "Lumayan" if v["score"] >= 35 else "Biasa")
        v.update(niche_info(classify(v["title"] + " " + " ".join(v.get("tags") or []))))
        v.setdefault("url", f"https://www.youtube.com/watch?v={v['id']}")
        v.setdefault("thumbnail", f"https://i.ytimg.com/vi/{v['id']}/mqdefault.jpg")
        v["is_short"] = 0 < (v.get("duration") or 0) <= 180
    return sorted(items, key=lambda v: v["score"], reverse=True)


def research(query: str, period: str = "week", length: str = "short", cc: bool = False,
             enrich: bool = True, limit: int = 20) -> dict:
    query = (query or "").strip()
    if not query:
        raise ClipAgentError("Isi kata kunci atau pilih niche.")
    key = f"{query}|{period}|{length}|{cc}|{enrich}|{limit}|{bool(api_key())}"
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    source = "youtube-api" if api_key() else "yt-dlp"
    if api_key():
        items = _api_search(query, period, length, cc, limit)
    else:
        items = _ytdlp_search(query, period, length, cc, limit, enrich)
    items = score([v for v in items if v.get("views")])[:limit]
    log(f"Riset viral '{query}': {len(items)} video ({source}).")
    data = {"query": query, "source": source, "items": items,
            "filters": {"period": period, "length": length, "cc": cc}}
    _CACHE[key] = (time.time(), data)
    return data
