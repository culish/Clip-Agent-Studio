"""Trend Radar: topik yang sedang ramai + niche CPM tinggi + pencarian video sumber di YouTube.

Sumber data (gratis, tanpa API key):
- Google Trends "Trending now" RSS per negara (default AS).
- Pencarian YouTube lewat yt-dlp (bisa difilter: Creative Commons, periode, durasi, urutan).
Ide topik dibuat LLM bila tersedia; tanpa LLM dipakai aturan sederhana.
"""
from __future__ import annotations

import base64
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, quote_plus

import requests

from .config import Settings
from .utils import ClipAgentError, log

# Rentang CPM kasar per niche (USD per 1.000 tayangan iklan, video panjang, 2026) dari vidIQ.
# Shorts jauh lebih rendah; angka ini dipakai untuk membandingkan niche, bukan janji pendapatan.
NICHES = {
    "insurance":   {"label": "Asuransi", "tier": 1, "cpm": "$20–50",
                    "kw": ["insurance", "geico", "progressive", "allstate", "state farm", "medicare",
                           "medicaid", "obamacare", "aca", "open enrollment", "premiums", "coverage"],
                    "queries": ["insurance explained podcast", "medicare open enrollment explained"]},
    "finance":     {"label": "Keuangan & investasi", "tier": 1, "cpm": "$15–50",
                    "kw": ["stock", "stocks", "market", "dow", "nasdaq", "s&p", "fed", "interest rate",
                           "rates", "inflation", "cpi", "jobs report", "earnings", "ipo", "401k", "ira",
                           "roth", "tax", "taxes", "irs", "refund", "social security", "stimulus",
                           "recession", "dividend", "treasury", "gold price", "silver price", "savings",
                           "credit card", "debt", "bank", "budget", "money", "wealth", "invest", "investing"],
                    "queries": ["personal finance podcast", "investing interview billionaire",
                                "how to build wealth podcast"]},
    "legal":       {"label": "Hukum", "tier": 1, "cpm": "$15–45",
                    "kw": ["lawsuit", "sued", "sues", "court", "supreme court", "judge", "verdict", "trial",
                           "settlement", "class action", "attorney", "lawyer", "ruling"],
                    "queries": ["lawyer explains podcast", "legal advice interview"]},
    "real_estate": {"label": "Properti & KPR", "tier": 1, "cpm": "$15–40",
                    "kw": ["housing", "home prices", "mortgage", "mortgage rates", "rent", "realtor",
                           "zillow", "real estate", "home sales", "homebuyers", "landlord"],
                    "queries": ["real estate investing podcast", "housing market explained"]},
    "health":      {"label": "Kesehatan & medis", "tier": 1, "cpm": "$15–40",
                    "kw": ["health", "cancer", "diabetes", "ozempic", "wegovy", "glp-1", "vaccine", "flu",
                           "covid", "measles", "fda", "drug", "heart", "doctor", "hospital", "cdc",
                           "outbreak", "virus", "dementia", "alzheimer", "longevity"],
                    "queries": ["doctor explains podcast", "longevity podcast interview"]},
    "crypto":      {"label": "Kripto", "tier": 2, "cpm": "$15–40",
                    "kw": ["bitcoin", "btc", "ethereum", "crypto", "solana", "xrp", "dogecoin", "coinbase",
                           "binance", "stablecoin"],
                    "queries": ["bitcoin podcast interview", "crypto explained"]},
    "ai_tech":     {"label": "AI & teknologi", "tier": 2, "cpm": "$10–30",
                    "kw": ["ai", "openai", "chatgpt", "gpt", "gemini", "claude", "anthropic", "nvidia",
                           "apple", "iphone", "ios", "android", "google", "microsoft", "meta", "samsung",
                           "pixel", "windows", "outage", "chip", "robot", "robotics", "software", "app",
                           "spacex", "starlink", "quantum"],
                    "queries": ["AI podcast interview", "tech CEO interview", "future of AI explained"]},
    "business":    {"label": "Bisnis & cari uang online", "tier": 2, "cpm": "$10–25",
                    "kw": ["ceo", "layoffs", "startup", "amazon", "walmart", "costco", "target", "merger",
                           "acquisition", "company", "brand", "tariff", "tariffs", "strike", "founder",
                           "entrepreneur", "side hustle", "marketing", "sales"],
                    "queries": ["entrepreneur podcast", "business advice interview", "side hustle podcast"]},
    "automotive":  {"label": "Otomotif", "tier": 2, "cpm": "$10–25",
                    "kw": ["car", "cars", "ford", "gm", "toyota", "honda", "ev", "tesla", "cybertruck",
                           "f-150", "recall", "chevy", "jeep"],
                    "queries": ["car industry podcast", "EV explained interview"]},
    "careers":     {"label": "Karier & pendidikan", "tier": 2, "cpm": "$8–20",
                    "kw": ["jobs", "hiring", "resume", "interview tips", "salary", "remote work",
                           "student loan", "student loans", "college", "fafsa", "scholarship", "career"],
                    "queries": ["career advice podcast", "how to get hired interview"]},
    "wellness":    {"label": "Kebugaran & gaya hidup sehat", "tier": 2, "cpm": "$7–20",
                    "kw": ["fitness", "workout", "diet", "sleep", "weight loss", "protein", "supplement",
                           "gym", "running", "marathon"],
                    "queries": ["fitness podcast interview", "sleep science podcast"]},
    "travel":      {"label": "Travel", "tier": 3, "cpm": "$4–14",
                    "kw": ["flight", "flights", "airline", "tsa", "airport", "hotel", "travel", "faa",
                           "delta", "united airlines", "american airlines", "cruise"],
                    "queries": ["travel podcast stories"]},
    "gaming":      {"label": "Gaming", "tier": 4, "cpm": "$4–15",
                    "kw": ["xbox", "playstation", "ps5", "nintendo", "switch 2", "fortnite", "minecraft",
                           "gta", "roblox", "steam", "call of duty", "pokemon"],
                    "queries": ["gaming podcast"]},
    "sports":      {"label": "Olahraga", "tier": 4, "cpm": "$2–8",
                    "kw": ["nfl", "nba", "mlb", "nhl", "ncaa", "ufc", "wwe", "vs", "score", "playoffs",
                           "world series", "super bowl", "draft", "fantasy football", "quarterback", "game"],
                    "queries": ["sports podcast"]},
    "entertainment": {"label": "Hiburan & selebriti", "tier": 4, "cpm": "$2–8",
                      "kw": ["movie", "trailer", "box office", "netflix", "season", "episode", "celebrity",
                             "actor", "actress", "singer", "concert", "tour", "album", "grammy", "oscar",
                             "emmy", "snl", "halloween", "show"],
                      "queries": ["celebrity interview podcast"]},
    "politics":    {"label": "Berita & politik (iklan sering dibatasi)", "tier": 4, "cpm": "bervariasi",
                    "kw": ["election", "trump", "biden", "harris", "vance", "senate", "congress", "governor",
                           "vote", "president", "poll", "democrat", "republican", "white house", "shutdown"],
                    "queries": []},
    "sensitive":   {"label": "Tragedi/bencana (hindari)", "tier": 5, "cpm": "dibatasi",
                    "kw": ["died", "dies", "dead", "death", "obituary", "shooting", "killed", "crash",
                           "hurricane", "earthquake", "tornado", "wildfire", "flood", "attack", "murder",
                           "arrested", "missing"],
                    "queries": []},
    "other":       {"label": "Umum", "tier": 3, "cpm": "?", "kw": [], "queries": []},
}
# Urutan pengecekan kata kunci (yang lebih spesifik/sensitif dulu).
_ORDER = ["sensitive", "insurance", "legal", "crypto", "real_estate", "finance", "health", "ai_tech",
          "automotive", "business", "careers", "wellness", "travel", "gaming", "sports",
          "entertainment", "politics"]
_PATTERNS = {k: re.compile(r"\b(" + "|".join(re.escape(w) for w in NICHES[k]["kw"]) + r")\b", re.I)
             for k in _ORDER}

TIER_LABEL = {1: "CPM sangat tinggi", 2: "CPM tinggi", 3: "CPM sedang", 4: "CPM rendah", 5: "Hindari"}


def classify(text: str) -> str:
    for key in _ORDER:
        if _PATTERNS[key].search(text or ""):
            return key
    return "other"


def niche_info(key: str) -> dict:
    n = NICHES.get(key, NICHES["other"])
    return {"niche": key, "niche_label": n["label"], "tier": n["tier"], "tier_label": TIER_LABEL[n["tier"]],
            "cpm": n["cpm"]}


def niche_catalog() -> list[dict]:
    out = []
    for key, n in NICHES.items():
        if n["queries"]:
            out.append({**niche_info(key), "queries": n["queries"]})
    return sorted(out, key=lambda x: x["tier"])


# ---------------------------------------------------------------- Google Trends
_TRENDS_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _traffic_num(s: str) -> int:
    m = re.match(r"([\d.,]+)\s*([KkMm]?)", s or "")
    if not m:
        return 0
    n = float(m.group(1).replace(",", ""))
    return int(n * {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1))


def parse_trends_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        d = {"title": "", "traffic": "", "published": "", "picture": "", "news": []}
        for ch in item:
            name = _local(ch.tag)
            if name == "title":
                d["title"] = (ch.text or "").strip()
            elif name == "approx_traffic":
                d["traffic"] = (ch.text or "").strip()
            elif name == "pubDate":
                d["published"] = (ch.text or "").strip()
            elif name == "picture":
                d["picture"] = (ch.text or "").strip()
            elif name == "news_item":
                n = {_local(x.tag).replace("news_item_", ""): (x.text or "").strip() for x in ch}
                if n.get("title"):
                    d["news"].append({"title": n.get("title", ""), "url": n.get("url", ""),
                                      "source": n.get("source", "")})
        if d["title"]:
            d["traffic_num"] = _traffic_num(d["traffic"])
            text = " ".join([d["title"]] + [n["title"] for n in d["news"][:3]])
            d.update(niche_info(classify(text)))
            items.append(d)
    items.sort(key=lambda x: x["traffic_num"], reverse=True)
    return items


def fetch_trends(geo: str = "US", max_age: int = 900) -> list[dict]:
    geo = (geo or "US").upper()
    hit = _TRENDS_CACHE.get(geo)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    try:
        r = requests.get("https://trends.google.com/trending/rss", params={"geo": geo}, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 (clip-agent trend radar)"})
        r.raise_for_status()
        items = parse_trends_rss(r.text)
    except (requests.RequestException, ET.ParseError) as exc:
        raise ClipAgentError(f"Google Trends tidak bisa dimuat ({type(exc).__name__}). Periksa koneksi "
                             "internet lalu muat ulang. Ide topik dan niche CPM tinggi tetap bisa dipakai.") from exc
    _TRENDS_CACHE[geo] = (time.time(), items)
    return items


# ---------------------------------------------------------------- ide topik
IDEAS_SYSTEM = """You are a YouTube Shorts strategist. The creator clips long-form videos (podcasts,
interviews, explainers) into vertical shorts with English captions for US viewers, and wants topics in
high-CPM niches that are advertiser-friendly. Answer ONLY with valid JSON."""

IDEAS_PROMPT = """Today: {today}. Trending Google searches in {geo} right now (title | traffic | niche | headline):
{trends}

High-CPM niches (key: label, CPM range): {niches}

Suggest {n} clip topic ideas. Mix about half that ride today's trends with half evergreen high-CPM topics.
Rules:
- Advertiser-friendly only: skip deaths, tragedies, violence, crime and partisan politics.
- Prefer niches with higher CPM, but only when there is real viewer interest.
- "search_query" must find LONG-FORM source videos on YouTube (podcast, interview, explainer, keynote).
- Write "topic", "hook" and "search_query" in English; write "why_now" and "angle" in Bahasa Indonesia.

JSON format:
{{"ideas": [{{"topic": "...", "niche": "finance", "trend": "matching trend title or empty",
"why_now": "1 kalimat", "angle": "sudut pandang klip, 1 kalimat", "hook": "first line of the short (<= 12 words)",
"search_query": "..."}}]}}"""

_FALLBACK_ANGLE = {
    "finance": ("Jelaskan dampaknya ke dompet orang biasa", "Here's what {t} means for your money"),
    "insurance": ("Kesalahan umum yang bikin orang rugi", "Most people get {t} completely wrong"),
    "legal": ("Apa artinya bagi orang biasa", "A lawyer explains what {t} really means"),
    "real_estate": ("Untung-rugi bagi pembeli rumah", "Is {t} good or bad news for buyers?"),
    "health": ("Penjelasan dokter dalam 30 detik", "A doctor explains {t} in 30 seconds"),
    "crypto": ("Pandangan pakar: peluang dan risikonya", "What experts are saying about {t}"),
    "ai_tech": ("Apa yang benar-benar berubah untuk pengguna", "What {t} actually changes for you"),
    "business": ("Pelajaran bisnis di balik berita ini", "The business lesson behind {t}"),
    "automotive": ("Perlu dipertimbangkan sebelum beli mobil", "Watch this before buying: {t}"),
    "careers": ("Tips karier yang bisa langsung dipakai", "How {t} affects your career"),
    "wellness": ("Kebiasaan sehat yang mudah ditiru", "The science behind {t}"),
}


# Ide evergreen (topik, hook, kueri pencarian) untuk niche CPM tinggi.
_EVERGREEN = {
    "finance": ("Money habits of millionaires", "Rich people never do this with their money",
                "millionaire money habits podcast"),
    "ai_tech": ("How AI will change everyday jobs", "This job won't exist in 5 years",
                "future of AI jobs interview"),
    "business": ("Lessons from founders who started with nothing", "He started with $500 and built this",
                 "entrepreneur origin story podcast"),
    "real_estate": ("Buying vs renting a home", "Renting isn't throwing money away. Here's why",
                    "rent vs buy home explained podcast"),
    "health": ("Simple habits doctors swear by", "A doctor's #1 habit for living longer",
               "doctor longevity habits podcast"),
    "careers": ("How to negotiate a higher salary", "Say this to get a higher salary offer",
                "salary negotiation tips interview"),
    "insurance": ("Insurance mistakes that cost thousands", "This insurance mistake costs people thousands",
                  "insurance mistakes explained"),
    "crypto": ("What experts really think about Bitcoin", "Why this billionaire changed his mind on Bitcoin",
               "bitcoin billionaire interview"),
}


def heuristic_ideas(trends: list[dict], n: int = 8) -> list[dict]:
    ideas = []
    for t in trends:
        if t["tier"] <= 2 and t["niche"] in _FALLBACK_ANGLE:
            angle, hook = _FALLBACK_ANGLE[t["niche"]]
            ideas.append({"topic": t["title"], "niche": t["niche"], "trend": t["title"],
                          "why_now": f"Sedang dicari {t['traffic'] or 'banyak'} kali di Google hari ini.",
                          "angle": angle, "hook": hook.format(t=t["title"]),
                          "search_query": f"{t['title']} explained podcast"})
        if len(ideas) >= n // 2:
            break
    for key, (topic, hook, query) in _EVERGREEN.items():
        if len(ideas) >= n:
            break
        ideas.append({"topic": topic, "niche": key, "trend": "",
                      "why_now": f"Topik evergreen dengan CPM {NICHES[key]['cpm']}; dicari sepanjang tahun.",
                      "angle": _FALLBACK_ANGLE[key][0], "hook": hook, "search_query": query})
    return [{**i, **niche_info(i["niche"])} for i in ideas[:n]]


def recommend_ideas(cfg: Settings, trends: list[dict], geo: str = "US", n: int = 8) -> tuple[list[dict], str]:
    """Mengembalikan (ide, sumber) — sumber 'ai' atau 'aturan'."""
    if cfg.provider == "heuristic":
        return heuristic_ideas(trends, n), "aturan"
    from .llm import LLMClient
    lines = []
    for t in trends[:25]:
        head = t["news"][0]["title"] if t.get("news") else ""
        lines.append(f"- {t['title']} | {t['traffic']} | {t['niche']} | {head}")
    niches = "; ".join(f"{k}: {v['label']}, {v['cpm']}" for k, v in NICHES.items() if v["tier"] <= 3
                       and k != "other")
    prompt = IDEAS_PROMPT.format(today=time.strftime("%Y-%m-%d"), geo=geo, trends="\n".join(lines) or "-",
                                 niches=niches, n=n)
    try:
        client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)
        data = client.complete_json(IDEAS_SYSTEM, prompt)
    except ClipAgentError as exc:
        log(f"Ide AI gagal ({str(exc).splitlines()[0]}); memakai aturan sederhana.")
        return heuristic_ideas(trends, n), "aturan"
    ideas = []
    for i in data.get("ideas", []):
        if not isinstance(i, dict) or not i.get("search_query"):
            continue
        key = i.get("niche") if i.get("niche") in NICHES else classify(f"{i.get('topic', '')} {i.get('search_query', '')}")
        if NICHES[key]["tier"] >= 5:
            continue
        ideas.append({**{k: str(i.get(k) or "") for k in ("topic", "trend", "why_now", "angle", "hook",
                                                         "search_query")}, **niche_info(key)})
    return (ideas or heuristic_ideas(trends, n)), ("ai" if ideas else "aturan")


# ---------------------------------------------------------------- pencarian YouTube
_PERIOD = {"hour": 1, "today": 2, "week": 3, "month": 4, "year": 5}
_LENGTH = {"short": 1, "long": 2, "medium": 3}
_SORT = {"relevance": 0, "rating": 1, "date": 2, "views": 3}


def search_params(cc: bool = True, period: str = "month", length: str = "long", sort: str = "views") -> str:
    """Bangun parameter filter pencarian YouTube ('sp', protobuf base64)."""
    filt = bytearray()
    if period in _PERIOD:
        filt += bytes([0x08, _PERIOD[period]])
    filt += bytes([0x10, 0x01])                      # tipe: video
    if length in _LENGTH:
        filt += bytes([0x18, _LENGTH[length]])
    if cc:
        filt += bytes([0x30, 0x01])                  # lisensi Creative Commons
    msg = bytearray()
    if _SORT.get(sort):
        msg += bytes([0x08, _SORT[sort]])
    msg += bytes([0x12, len(filt)]) + filt
    return base64.b64encode(bytes(msg)).decode()


def search_youtube(query: str, cc: bool = True, period: str = "month", length: str = "long",
                   sort: str = "views", limit: int = 12, cookies_from_browser: str = "", region: str = "") -> dict:
    try:
        import yt_dlp
    except ImportError as exc:
        raise ClipAgentError('yt-dlp belum terpasang. Jalankan: pip install -U "yt-dlp[default]"') from exc
    from .download import _QuietLogger, _explain_ytdlp_error

    def run(per: str) -> list[dict]:
        sp = search_params(cc, per, length, sort)
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={quote(sp, safe='')}"
        if region:                                   # hasil seperti dilihat penonton di negara itu
            url += f"&gl={region}&hl=en"
        opts = {"extract_flat": "in_playlist", "playlistend": limit * 2, "quiet": True,
                "no_warnings": True, "logger": _QuietLogger(), "skip_download": True,
                "extractor_args": {"youtubetab": {"approximate_date": [""]}}}
        if cookies_from_browser:
            opts["cookiesfrombrowser"] = (cookies_from_browser,)
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as exc:
                raise ClipAgentError(_explain_ytdlp_error(str(exc))) from exc
        out = []
        for e in (info or {}).get("entries") or []:
            vid = e.get("id") or ""
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) or e.get("live_status") in ("is_live", "is_upcoming"):
                continue
            out.append({
                "id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": e.get("title") or "",
                "channel": e.get("channel") or e.get("uploader") or "", "duration": e.get("duration") or 0,
                "views": e.get("view_count") or 0, "timestamp": e.get("timestamp") or 0,
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", "cc": cc,
            })
            if len(out) >= limit:
                break
        return out

    results = run(period)
    widened = False
    if not results and period not in ("", "any"):
        results, widened = run("any"), True
    return {"query": query, "results": results, "widened": widened,
            "filters": {"cc": cc, "period": "any" if widened else period, "length": length, "sort": sort}}
