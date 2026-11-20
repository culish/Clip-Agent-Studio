"""Tema video untuk tab Buat video: format yang sedang ramai di Shorts, Reels, dan TikTok.

Setiap tema mengatur empat hal sekaligus:
- arahan naskah untuk AI (format, nada, struktur) dan skema "art" per adegan;
- visual: digambar langsung oleh Remotion sebagai grafis vektor (gratis, tanpa API gambar), atau gambar AI
  dengan gaya tema bila pengguna memilih "Gambar AI";
- tampilan: warna, font, caption, judul, dan lapisan efek (hujan, kunang-kunang, kilat, butiran film);
- suara dan musik: gaya bicara narator dan suasana musik bawaan.
Visual vektornya ada di remotion/src/Themes.tsx.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import PROJECT_DIR

STICK_POSES = {
    "stand": "berdiri", "wave": "melambai", "point": "menunjuk", "think": "berpikir", "happy": "senang",
    "sad": "sedih", "run": "berlari", "shrug": "angkat bahu", "sit": "duduk", "celebrate": "merayakan",
    "scared": "takut", "idea": "dapat ide",
}
STICK_PROPS = {
    "sun": "matahari", "cloud": "awan", "rain": "hujan", "moon": "bulan", "star": "bintang", "house": "rumah",
    "tree": "pohon", "money": "uang", "coin": "koin", "clock": "jam", "heart": "hati", "bulb": "lampu ide",
    "question": "tanda tanya", "exclaim": "tanda seru", "chart_up": "grafik naik", "chart_down": "grafik turun",
    "book": "buku", "phone": "ponsel", "laptop": "laptop", "globe": "bumi", "mountain": "gunung", "trophy": "piala",
    "fire": "api", "water": "air", "food": "makanan", "car": "mobil", "check": "centang", "cross": "silang",
    "rainbow": "pelangi", "bed": "kasur", "gift": "hadiah", "calendar": "kalender", "arrow": "panah",
}
LOFI_PLACES = {"kamar": "Kamar dengan jendela", "jalan": "Jalan malam", "atap": "Atap gedung", "bus": "Di dalam bus"}
LOFI_TIMES = {"malam": "Malam", "hujan": "Hujan", "senja": "Senja", "pagi": "Pagi"}
LOFI_PROPS = {"mug": "Gelas kopi", "kucing": "Kucing", "tanaman": "Tanaman", "buku": "Buku", "headphone": "Headphone",
              "none": "Tanpa"}
TALE_PLACES = {"hutan": "Hutan", "danau": "Danau", "bukit": "Bukit", "desa": "Desa", "laut": "Laut"}
TALE_TIMES = {"malam": "Malam", "fajar": "Fajar", "siang": "Siang"}
TALE_CREATURES = {"rusa": "Rusa", "kelinci": "Kelinci", "burung_hantu": "Burung hantu", "rubah": "Rubah",
                  "kura": "Kura-kura", "anak": "Anak kecil", "none": "Tanpa"}
DATA_KINDS = {"map": "Peta", "number": "Angka besar", "bars": "Grafik batang", "title": "Judul"}
DOOR_KINDS = {"question": "Pertanyaan", "doors": "Tiga pintu", "countdown": "Hitung mundur", "reveal": "Buka pintu",
              "explain": "Penjelasan"}
TAPE_KINDS = {"speaker": "Pencerita", "tape": "Kaset"}
SPEAKERS = {"nenek": "Nenek", "kakek": "Kakek", "ibu": "Ibu", "ayah": "Ayah", "anak": "Anak"}
SUNSET_SUBJECTS = {"perahu": "Perahu", "orang": "Orang", "pohon": "Pohon", "kota": "Kota", "burung": "Burung",
                   "sepeda": "Sepeda", "gunung": "Gunung"}
MYSTERY_SUBJECTS = {"rumah": "Rumah tua", "menara": "Menara", "hutan": "Hutan", "jalan": "Jalan sepi",
                    "pintu": "Pintu", "jendela": "Jendela"}

_ALL_ART = "No text, no captions, no logos, no watermarks."

THEMES: dict[str, dict] = {
    "stickman": {
        "name": "Stickman", "icon": "✏️",
        "desc": "Coretan stickman di kertas putih seperti papan tulis. Cocok untuk penjelasan sains, psikologi, uang, dan tips.",
        "examples": "Kenapa langit biru? · Efek bunga majemuk · Kenapa kita susah bangun pagi",
        "mood": "santai", "voice_style": "friendly, curious and clear, like a teacher drawing on a whiteboard",
        "art_prompt": "a minimalist hand-drawn stick figure doodle in black marker on plain white paper, simple line art, "
                      "one or two accent colors, lots of empty space",
        "overlays": ["paper"],
        "look": {"bg": "#FAF9F5", "bg2": "#FFFFFF", "accent": "#E4572E", "ink": "#FFFFFF", "text": "#1A1A1A",
                 "font": "Caveat Bold", "captionFont": "Patrick Hand", "frame": "plain", "captions": "karaoke",
                 "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none", "uppercase": False,
                 "transitionSec": 0.3, "captionStroke": 0.35},
        "transition": "fade",
        "script": "Format: whiteboard stick-figure explainer. Explain ONE idea simply, step by step, with everyday "
                  "analogies a 12-year-old understands. Short spoken sentences. Every scene shows one (or two) stick "
                  "figures doing one clear thing with up to three simple props, plus a handwritten label of 1-3 words.",
        "schema": '"art": {"pose": one of [%s], "props": up to 3 of [%s], "label": "1-3 words written on the board", '
                  '"people": 1 or 2, "pose2": pose of the second figure when people is 2}' % (
                      ", ".join(STICK_POSES), ", ".join(STICK_PROPS)),
    },
    "lofi": {
        "name": "Cerita lofi", "icon": "🌧️",
        "desc": "Suasana kamar malam, hujan di jendela, lampu meja hangat. Monolog pelan tentang perasaan sehari-hari.",
        "examples": "Capek tapi harus kuat · Kangen rumah di tanah rantau · Belajar sampai larut",
        "mood": "lofi", "voice_style": "soft, calm and intimate, slow pace, almost whispering, gentle pauses",
        "art_prompt": "a cozy lofi anime illustration, muted warm palette, soft desk lamp light, rain on the window, "
                      "film grain, quiet and melancholic mood",
        "overlays": ["rain", "grain", "vignette"],
        "look": {"bg": "#1D1A2B", "bg2": "#2A2440", "accent": "#F5C27A", "ink": "#141221", "text": "#F4EDE1",
                 "font": "Fraunces Italic", "captionFont": "Patrick Hand", "frame": "plain", "captions": "karaoke",
                 "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none", "uppercase": False,
                 "transitionSec": 0.7, "captionStroke": 0.6},
        "transition": "fade",
        "script": "Format: quiet lo-fi story. A first-person, reflective monologue about an everyday feeling (tired, "
                  "missing home, studying late, starting over, being alone in a big city). Calm short sentences, "
                  "concrete small details (the rain, cold coffee, a phone that does not ring), gentle hope at the end. "
                  "No hype, no exclamation marks, no lists. Headings are lowercase, 1-4 words.",
        "schema": '"art": {"place": one of [%s], "time": one of [%s], "prop": one of [%s]}' % (
            ", ".join(LOFI_PLACES), ", ".join(LOFI_TIMES), ", ".join(LOFI_PROPS)),
    },
    "dongeng": {
        "name": "Dongeng malam", "icon": "🦌",
        "desc": "Ilustrasi buku cerita: bulan purnama, bukit, kunang-kunang, hewan hutan. Narator bercerita dengan pesan moral.",
        "examples": "Rusa yang takut gelap · Asal-usul danau (karangan sendiri) · Kelinci dan janji",
        "mood": "dongeng", "voice_style": "warm storyteller reading a bedtime story, slow and gentle, expressive",
        "art_prompt": "a soft storybook illustration, flat gouache texture, night scene with a big full moon, fireflies, "
                      "gentle rounded shapes, calm deep blue and warm yellow palette",
        "overlays": ["fireflies", "stars", "grain"],
        "look": {"bg": "#0F1B33", "bg2": "#18284A", "accent": "#FFD98A", "ink": "#0A1222", "text": "#FFF7E6",
                 "font": "Fraunces Black", "captionFont": "Fraunces Italic", "frame": "plain", "captions": "karaoke",
                 "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none", "uppercase": False,
                 "transitionSec": 0.6, "captionStroke": 0.7},
        "transition": "fade",
        "script": "Format: bedtime fable (dongeng). Third-person narrator, gentle and vivid, with animals or simple "
                  "villagers as characters, one small problem, a turning point and a clear moral at the end "
                  "('Pesan moralnya...' / 'And the lesson is...'). Start like 'Pada suatu malam...' / 'One quiet night...'. "
                  "Invent your own story or use a public-domain folk tale; never retell a copyrighted story.",
        "schema": '"art": {"place": one of [%s], "time": one of [%s], "creature": one of [%s]}' % (
            ", ".join(TALE_PLACES), ", ".join(TALE_TIMES), ", ".join(TALE_CREATURES)),
    },
    "berita_data": {
        "name": "Berita data", "icon": "🗺️",
        "desc": "Peta bertitik, angka besar, dan grafik di atas kertas krem, seperti jurnalisme data.",
        "examples": "Sebaran gunung api aktif · Kota termacet · Berapa banyak pulau di Indonesia",
        "mood": "teknologi", "voice_style": "clear, neutral news anchor, confident and measured",
        "art_prompt": "a clean editorial infographic illustration on beige paper, muted colors, simple flat shapes",
        "overlays": ["paper"],
        "look": {"bg": "#EFE6D2", "bg2": "#E6DAC0", "accent": "#C8321E", "ink": "#EFE6D2", "text": "#1D1A16",
                 "font": "Archivo Black", "captionFont": "Plus Jakarta Sans", "frame": "plain", "captions": "karaoke",
                 "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none", "uppercase": False,
                 "transitionSec": 0.35, "captionStroke": 0.5},
        "transition": "slide",
        "script": "Format: data-journalism explainer (berita data). Neutral news tone: what, where, how many, why it "
                  "matters. Use ONLY numbers that appear in the research text; never invent statistics. If the research "
                  "has no numbers, use map and title scenes instead of number or bars scenes. Name the source of a "
                  "number in the narration only when the research names it. Map scenes show real places with their "
                  "approximate coordinates.",
        "schema": '"art": {"kind": one of [map, number, bars, title], "country": English country name for map scenes '
                  '(e.g. "Indonesia"), "points": up to 12 [{"name": "", "lat": 0, "lon": 0}] for map scenes, '
                  '"value": "the number as written, e.g. 17.000", "unit": "e.g. pulau, %, juta", "label": "what the '
                  'number means, max 6 words", "items": up to 6 [{"label": "", "value": 0}] for bars scenes}',
    },
    "pilih_pintu": {
        "name": "Pilih pintu", "icon": "🚪",
        "desc": "Tiga pintu bernomor, hitung mundur, lalu pintu jawaban terbuka. Teka-teki atau tes pilihan yang memancing komentar.",
        "examples": "Pintu mana yang aman? · Tes kepribadian dari pilihanmu · Teka-teki logika",
        "mood": "misteri", "voice_style": "playful game-show host, energetic, building suspense before the reveal",
        "art_prompt": "a night scene with three numbered wooden doors on a starry blue wall, warm light, flat illustration",
        "overlays": [],
        "look": {"bg": "#141B3D", "bg2": "#1E2A5E", "accent": "#FFD25A", "ink": "#0B0F24", "text": "#FFFFFF",
                 "font": "Anton", "captionFont": "Montserrat Black", "frame": "plain", "captions": "karaoke",
                 "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none", "uppercase": True,
                 "transitionSec": 0.3, "captionStroke": 1.0},
        "transition": "fade",
        "script": "Format: 'pilih pintu' choice game. Scene 1: a hook question. Scene 2: three doors with three short "
                  "options (max 4 words each) and ask the viewer to pick a number. Scene 3: a countdown ('tiga, dua, "
                  "satu' / 'three, two, one'). Then reveal: open the right door and explain why in 2-3 scenes; you may "
                  "say what the other doors meant. End by asking viewers to comment their number. The answer must be "
                  "logical and defensible (logic riddle, survival choice, trivia, or a light 'what your choice says' "
                  "game clearly framed as just for fun). Use the SAME three options in every scene.",
        "schema": '"art": {"kind": one of [question, doors, countdown, reveal, explain], "options": ["", "", ""] '
                  '(the same three options in every scene), "answer": 1, 2 or 3, "label": "short text on screen"}',
    },
    "kaset": {
        "name": "Kaset cerita", "icon": "📼",
        "desc": "Nenek atau kakek bercerita lewat kaset tua: balon kata, pita berputar, gelombang suara. Hangat dan nostalgia.",
        "examples": "Pesan nenek soal uang · Cerita kakek zaman dulu · Nasihat ibu sebelum merantau",
        "mood": "inspiratif", "voice_style": "an elderly, warm and slow voice telling a memory to a grandchild",
        "art_prompt": "a warm flat illustration of a kind grandparent with a speech bubble next to an old cassette "
                      "player, cream paper background, soft retro colors",
        "overlays": ["paper"],
        "look": {"bg": "#F3EBDD", "bg2": "#EADFCB", "accent": "#D9412B", "ink": "#F3EBDD", "text": "#2A2420",
                 "font": "Special Elite", "captionFont": "Plus Jakarta Sans", "frame": "plain", "captions": "karaoke",
                 "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none", "uppercase": False,
                 "transitionSec": 0.35, "captionStroke": 0.5},
        "transition": "fade",
        "script": "Format: a nostalgic voice-note story told by an elder (grandmother/grandfather) or a parent to a "
                  "grandchild, first person, warm, slow, simple words, one life lesson drawn from a small memory. It "
                  "should feel like listening to an old cassette recording.",
        "schema": '"art": {"kind": one of [speaker, tape], "speaker": one of [%s], "label": "cassette label, 1-3 words"}' % (
            ", ".join(SPEAKERS)),
    },
    "senja": {
        "name": "Senja minimalis", "icon": "🌅",
        "desc": "Ilustrasi flat bergradasi jingga-ungu: laut, perahu, siluet. Untuk kisah inspiratif dan filosofi hidup.",
        "examples": "Nelayan dan laut yang tenang · Pohon yang tidak terburu-buru · Jalan pulang",
        "mood": "inspiratif", "voice_style": "calm, reflective and warm, unhurried",
        "art_prompt": "a minimal flat vector illustration at sunset, retro gradient sky from orange to purple, simple "
                      "silhouettes, subtle grain, calm and poetic",
        "overlays": ["grain"],
        "look": {"bg": "#2B1E3F", "bg2": "#F28C5B", "accent": "#FFD27A", "ink": "#1E1430", "text": "#FFF5E8",
                 "font": "Playfair Display Black", "captionFont": "Plus Jakarta Sans", "frame": "plain",
                 "captions": "karaoke", "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none",
                 "uppercase": False, "transitionSec": 0.6, "captionStroke": 0.7},
        "transition": "fade",
        "script": "Format: a calm inspirational micro-story or life philosophy told like a parable: an old fisherman, "
                  "a tree, a long road. Simple images, slow rhythm, one idea, ending with one memorable line.",
        "schema": '"art": {"subject": one of [%s], "sun": one of [low, half]}' % ", ".join(SUNSET_SUBJECTS),
    },
    "misteri": {
        "name": "Misteri malam", "icon": "⛈️",
        "desc": "Awan badai, kilat, hujan, dan bangunan sepi. Untuk cerita misteri, legenda, dan fenomena aneh.",
        "examples": "Legenda rumah di ujung jalan · Fenomena yang belum terjelaskan · Kisah mercusuar",
        "mood": "misteri", "voice_style": "low, slow and suspenseful, like telling a story by candlelight",
        "art_prompt": "a moody minimal flat illustration at night, dark storm clouds, lightning, a lone building, "
                      "desaturated blue-grey palette",
        "overlays": ["rain", "lightning", "vignette", "grain"],
        "look": {"bg": "#0D1117", "bg2": "#1A2230", "accent": "#E05A4F", "ink": "#05070A", "text": "#E9E6DD",
                 "font": "Special Elite", "captionFont": "Montserrat Black", "frame": "plain", "captions": "karaoke",
                 "texture": "none", "motion": "smooth", "sfx": False, "videoFilter": "none", "uppercase": True,
                 "transitionSec": 0.45, "captionStroke": 1.0},
        "transition": "fade",
        "script": "Format: an eerie mystery story, legend or unexplained phenomenon. Build tension slowly, keep it "
                  "suspenseful but not gory. Present legends as legends and never claim unverified events as facts. "
                  "End with an open question for the viewer.",
        "schema": '"art": {"subject": one of [%s], "storm": true or false}' % ", ".join(MYSTERY_SUBJECTS),
    },
}

# Kolom yang bisa diedit per adegan di UI (kunci, label, jenis, pilihan)
FIELDS: dict[str, list] = {
    "stickman": [["pose", "Pose", STICK_POSES], ["props", "Benda (pisahkan koma)", "list"], ["label", "Tulisan", "text"],
                 ["people", "Jumlah orang", {"1": "1", "2": "2"}], ["pose2", "Pose orang kedua", STICK_POSES]],
    "lofi": [["place", "Tempat", LOFI_PLACES], ["time", "Waktu", LOFI_TIMES], ["prop", "Benda", LOFI_PROPS]],
    "dongeng": [["place", "Tempat", TALE_PLACES], ["time", "Waktu", TALE_TIMES], ["creature", "Tokoh", TALE_CREATURES]],
    "berita_data": [["kind", "Jenis", DATA_KINDS], ["country", "Negara (peta, bahasa Inggris)", "text"],
                    ["points", "Titik peta: nama;lat;lon per baris", "points"], ["value", "Angka", "text"],
                    ["unit", "Satuan", "text"], ["label", "Keterangan", "text"],
                    ["items", "Batang: label;nilai per baris", "items"]],
    "pilih_pintu": [["kind", "Jenis", DOOR_KINDS], ["options", "Pilihan 1, 2, 3 (pisahkan koma)", "list"],
                    ["answer", "Jawaban", {"1": "Pintu 1", "2": "Pintu 2", "3": "Pintu 3"}], ["label", "Tulisan", "text"]],
    "kaset": [["kind", "Jenis", TAPE_KINDS], ["speaker", "Pencerita", SPEAKERS], ["label", "Label kaset", "text"]],
    "senja": [["subject", "Objek", SUNSET_SUBJECTS], ["sun", "Matahari", {"low": "Rendah", "half": "Setengah tenggelam"}]],
    "misteri": [["subject", "Objek", MYSTERY_SUBJECTS], ["storm", "Badai", {"true": "Ya", "false": "Tidak"}]],
}


def get(theme_id: str) -> dict | None:
    return THEMES.get(theme_id or "")


def public() -> dict:
    """Ringkasan tema untuk UI."""
    return {k: {"name": v["name"], "icon": v["icon"], "desc": v["desc"], "examples": v["examples"], "mood": v["mood"],
                "fields": FIELDS.get(k, []), "sample": f"/web/tema/{k}.jpg"} for k, v in THEMES.items()}


def look(theme_id: str) -> dict:
    t = THEMES[theme_id]
    return {**t["look"], "name": t["name"]}


# ---------------------------------------------------------------- naskah
def prompt_block(theme_id: str) -> str:
    t = get(theme_id)
    if not t:
        return ""
    return (f"\n\nVISUAL THEME: {t['name']}.\n{t['script']}\nFor every scene ALSO give {t['schema']}. Keep \"heading\" "
            "short (2-5 words). Still give \"prompt\" (used only if the creator switches to AI images) and \"stock\".")


# ---------------------------------------------------------------- pembersih "art"
_COUNTRIES: set[str] | None = None


def countries() -> set[str]:
    """Nama negara yang dikenal peta (world-atlas). Kosong bila paket Remotion belum terpasang."""
    global _COUNTRIES
    if _COUNTRIES is None:
        _COUNTRIES = set()
        p = PROJECT_DIR / "remotion" / "node_modules" / "world-atlas" / "countries-50m.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            _COUNTRIES = {g["properties"]["name"] for g in data["objects"]["countries"]["geometries"]
                          if g.get("properties", {}).get("name")}
        except (OSError, ValueError, KeyError):
            pass
    return _COUNTRIES


ALIASES = {"usa": "United States of America", "united states": "United States of America", "us": "United States of America",
           "amerika": "United States of America", "amerika serikat": "United States of America", "uk": "United Kingdom",
           "inggris": "United Kingdom", "jepang": "Japan", "korea selatan": "South Korea", "south korea": "South Korea",
           "tiongkok": "China", "cina": "China", "arab saudi": "Saudi Arabia", "belanda": "Netherlands",
           "jerman": "Germany", "prancis": "France", "perancis": "France", "rusia": "Russia", "india": "India",
           "singapura": "Singapore", "filipina": "Philippines", "thailand": "Thailand", "vietnam": "Vietnam",
           "malaysia": "Malaysia", "australia": "Australia", "brasil": "Brazil", "mesir": "Egypt", "turki": "Turkey",
           "korea utara": "North Korea", "timor leste": "Timor-Leste", "timor-leste": "Timor-Leste", "papua nugini": "Papua New Guinea"}


def _country(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not n:
        return "Indonesia"
    known = countries()
    if not known or n in known:
        return n
    alias = ALIASES.get(n.lower())
    if alias and alias in known:
        return alias
    for k in known:
        if k.lower() == n.lower():
            return k
    return "Indonesia"


def _txt(v, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _pick(v, choices, default):
    v = str(v or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in choices else default


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ".").replace(" ", ""))
        return f if f == f and abs(f) < 1e15 else None
    except (TypeError, ValueError):
        return None


def clean_art(theme_id: str, raw, i: int = 0) -> dict:
    """Validasi objek "art" dari AI atau editor. Nilai tidak dikenal diganti bawaan yang masuk akal."""
    a = raw if isinstance(raw, dict) else {}
    if theme_id == "stickman":
        props = a.get("props")
        if isinstance(props, str):
            props = [p.strip() for p in props.split(",")]
        props = [p for p in (_pick(p, STICK_PROPS, "") for p in (props or [])) if p][:3]
        people = 2 if str(a.get("people")) == "2" else 1
        poses = list(STICK_POSES)
        return {"pose": _pick(a.get("pose"), STICK_POSES, poses[i % len(poses)]), "props": props,
                "label": _txt(a.get("label"), 28), "people": people,
                "pose2": _pick(a.get("pose2"), STICK_POSES, "stand")}
    if theme_id == "lofi":
        return {"place": _pick(a.get("place"), LOFI_PLACES, "kamar"), "time": _pick(a.get("time"), LOFI_TIMES, "hujan"),
                "prop": _pick(a.get("prop"), LOFI_PROPS, "mug")}
    if theme_id == "dongeng":
        return {"place": _pick(a.get("place"), TALE_PLACES, list(TALE_PLACES)[i % len(TALE_PLACES)]),
                "time": _pick(a.get("time"), TALE_TIMES, "malam"),
                "creature": _pick(a.get("creature"), TALE_CREATURES, "rusa")}
    if theme_id == "berita_data":
        kind = _pick(a.get("kind"), DATA_KINDS, "title")
        pts = []
        raw_pts = a.get("points")
        if isinstance(raw_pts, str):                                 # dari editor: "nama;lat;lon" per baris
            raw_pts = [dict(zip(("name", "lat", "lon"), ln.split(";"))) for ln in raw_pts.splitlines() if ln.strip()]
        for p in (raw_pts or [])[:14]:
            if not isinstance(p, dict):
                continue
            lat, lon = _num(p.get("lat")), _num(p.get("lon"))
            if lat is None or lon is None or not (-85 <= lat <= 85 and -180 <= lon <= 180):
                continue
            pts.append({"name": _txt(p.get("name"), 28), "lat": round(lat, 3), "lon": round(lon, 3)})
        items = []
        raw_items = a.get("items")
        if isinstance(raw_items, str):
            raw_items = [dict(zip(("label", "value"), ln.split(";"))) for ln in raw_items.splitlines() if ln.strip()]
        for it in (raw_items or [])[:6]:
            if isinstance(it, dict) and _num(it.get("value")) is not None and _txt(it.get("label"), 30):
                items.append({"label": _txt(it.get("label"), 30), "value": _num(it.get("value"))})
        if kind == "bars" and len(items) < 2:
            kind = "title"
        if kind == "number" and not _txt(a.get("value"), 20):
            kind = "title"
        return {"kind": kind, "country": _country(a.get("country")), "points": pts, "value": _txt(a.get("value"), 20),
                "unit": _txt(a.get("unit"), 24), "label": _txt(a.get("label"), 60), "items": items}
    if theme_id == "pilih_pintu":
        opts = a.get("options")
        if isinstance(opts, str):
            opts = [o.strip() for o in opts.split(",")]
        opts = [_txt(o, 32) for o in (opts or [])][:3]
        try:
            ans = int(a.get("answer"))
        except (TypeError, ValueError):
            ans = 0
        return {"kind": _pick(a.get("kind"), DOOR_KINDS, "doors"), "options": opts + [""] * (3 - len(opts)),
                "answer": ans if ans in (1, 2, 3) else 0, "label": _txt(a.get("label"), 40)}
    if theme_id == "kaset":
        return {"kind": _pick(a.get("kind"), TAPE_KINDS, "speaker" if i % 2 == 0 else "tape"),
                "speaker": _pick(a.get("speaker"), SPEAKERS, "nenek"), "label": _txt(a.get("label"), 24)}
    if theme_id == "senja":
        return {"subject": _pick(a.get("subject"), SUNSET_SUBJECTS, list(SUNSET_SUBJECTS)[i % len(SUNSET_SUBJECTS)]),
                "sun": "half" if str(a.get("sun")).lower() == "half" else "low"}
    if theme_id == "misteri":
        storm = a.get("storm")
        return {"subject": _pick(a.get("subject"), MYSTERY_SUBJECTS, list(MYSTERY_SUBJECTS)[i % len(MYSTERY_SUBJECTS)]),
                "storm": storm if isinstance(storm, bool) else str(storm).lower() != "false"}
    return {}


def finalize(theme_id: str, scenes: list[dict]) -> list[dict]:
    """Penyesuaian antar-adegan. Pilih pintu: pilihan dan jawaban sama di semua adegan."""
    if theme_id == "pilih_pintu" and scenes:
        opts = next((s["art"]["options"] for s in scenes if any(s.get("art", {}).get("options", []))), ["", "", ""])
        ans = next((s["art"]["answer"] for s in scenes if s.get("art", {}).get("answer")), 0)
        for s in scenes:
            art = s.setdefault("art", clean_art(theme_id, {}))
            if not any(art["options"]):
                art["options"] = list(opts)
            if not art["answer"]:
                art["answer"] = ans
    return scenes


def ai_style(theme_id: str) -> str:
    t = get(theme_id)
    return t["art_prompt"] if t else ""


def image_prompt(theme_id: str, scene_text: str) -> str:
    return f"{scene_text.strip()}. Style: {ai_style(theme_id)}. {_ALL_ART}"


# ---------------------------------------------------------------- level suara (gelombang kaset)
def audio_levels(wav: Path, fps: int, read_wav) -> list[float]:
    """Kekerasan suara per frame (0..1) untuk gelombang di tema Kaset."""
    import numpy as np
    data, sr = read_wav(wav)
    if data.ndim > 1:
        data = data.mean(axis=1)
    hop = max(1, int(sr / fps))
    n = len(data) // hop
    if n <= 0:
        return []
    frames = data[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    peak = float(np.percentile(rms, 98)) or 1.0
    return [round(float(min(1.0, v / peak)), 3) for v in rms]
