"""Reels viral: 11 format reel faceless (seperti MakeViralReels) yang langsung jadi MP4.

Masukan: tautan (artikel, produk, video), topik, naskah sendiri, atau berita yang sedang ramai. AI menulis isi reel
dalam bentuk data terstruktur untuk format yang dipilih; tampilannya digambar template animasi Clip Agent
(clipagent/reels_tpl/, dijalankan MotionKit di Remotion). Karena visual dan geraknya sudah ditulis tetap, hasilnya
sama rapinya siapa pun penulis isinya: Claude Code, Codex, Gemini CLI, Qwen Code, opencode, atau AI di Pengaturan
(Gemini gratis, OpenRouter, Groq, Ollama, dll.). Isi tetap diperiksa: panjang, ikon, urutan, dan kutipan Proof Punch
harus benar-benar ada di sumber.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path

import requests

from .utils import ClipAgentError, extract_json, log, progress

TPL_DIR = Path(__file__).with_name("reels_tpl")

ICONS = ["idea", "money", "clock", "rocket", "heart", "brain", "phone", "globe", "chart_up", "chart_down", "home",
         "person", "people", "check", "cross", "star", "book", "gear", "lock", "sun", "cloud", "bolt", "leaf",
         "trophy", "warning", "question", "fire", "target", "cart", "car", "food", "water", "shield", "calendar",
         "chat", "search", "gift", "music"]

FORMATS: dict[str, dict] = {
    "cartoon_host": {
        "name": "Cartoon Host", "icon": "🧑‍🏫", "new": True, "voice": "one", "captions": True, "mood": "ceria",
        "look": "a friendly cartoon presenter stands next to a board and tells the story; the board shows one key "
                "word, number or icon per scene", "suits": "cerita, fakta unik, penjelasan ringan, tips",
        "desc": "Presenter kartun menceritakan kisahmu di depan papan",
        "rules": "- Write like a lively host talking to camera (\"Kamu tahu nggak...\").\n"
                 "- board: 2-6 words shown on the board; big: optional short number or stat from the narration "
                 "(\"30%\", \"3x\", \"1998\") or \"\"; icon: one of ICONS; mood: happy|surprised|thinking|serious|excited.",
        "scene": '{"narration": "", "board": "", "big": "", "icon": "idea", "mood": "happy"}',
        "example": {"title": "Kenapa langit sore berwarna oranye?", "scenes": [
            {"narration": "Pernah lihat langit sore yang tiba-tiba oranye menyala?", "board": "Langit oranye?", "big": "",
             "icon": "sun", "mood": "surprised"},
            {"narration": "Sinar matahari sore menempuh jalan yang jauh lebih panjang di atmosfer.", "board": "Jalan lebih panjang",
             "big": "", "icon": "globe", "mood": "thinking"},
            {"narration": "Warna biru tersebar habis di jalan, jadi yang sampai ke mata kita tinggal merah dan oranye.",
             "board": "Biru tersebar", "big": "", "icon": "idea", "mood": "excited"},
            {"narration": "Simpan video ini buat jawab pertanyaan anakmu nanti!", "board": "Simpan ya!", "big": "",
             "icon": "star", "mood": "happy"}]}},
    "whiteboard": {
        "name": "Whiteboard", "icon": "✍️", "voice": "one", "captions": True, "mood": "santai",
        "look": "a hand draws the explanation on a whiteboard while the voiceover talks; doodle icons and short "
                "labels are drawn as they are spoken", "suits": "penjelasan, sains, cara kerja, langkah demi langkah",
        "desc": "Tangan menggambar penjelasannya sambil narasi berjalan",
        "rules": "- title: 2-5 words written at the top of the board.\n"
                 "- items: 1-3 doodles, each {icon (one of ICONS), label (1-3 words)}; link: arrow|plus|vs|none "
                 "(how the doodles connect).",
        "scene": '{"narration": "", "title": "", "items": [{"icon": "idea", "label": ""}], "link": "arrow"}',
        "example": {"title": "Cara kerja vaksin dalam 20 detik", "scenes": [
            {"narration": "Tubuhmu belajar melawan penyakit tanpa harus sakit dulu. Begini caranya.", "title": "Cara kerja vaksin",
             "items": [{"icon": "shield", "label": "Tubuh"}, {"icon": "question", "label": "Belajar?"}], "link": "arrow"},
            {"narration": "Vaksin membawa contoh kuman yang sudah dilemahkan.", "title": "Contoh kuman",
             "items": [{"icon": "warning", "label": "Kuman lemah"}], "link": "none"},
            {"narration": "Sistem imun mempelajarinya lalu menyimpan ingatan untuk serangan berikutnya.", "title": "Imun ingat",
             "items": [{"icon": "brain", "label": "Ingatan"}, {"icon": "shield", "label": "Siap"}], "link": "arrow"},
            {"narration": "Ikuti untuk penjelasan sains singkat lainnya.", "title": "Ikuti ya",
             "items": [{"icon": "star", "label": "Sains"}], "link": "none"}]}},
    "stickman": {
        "name": "Stickman", "icon": "🕺", "voice": "one", "captions": True, "mood": "ceria", "theme": "stickman",
        "look": "two stick figures act the story out on paper", "suits": "situasi sehari-hari, masalah yang relate, dua sisi",
        "desc": "Dua tokoh stickman memerankan ceritanya",
        "rules": "- Each scene is a small acted moment between one or two stick figures (people: 2 when two sides talk).\n"
                 "- heading: 2-5 words; art: as described in the THEME block below.",
        "scene": '{"narration": "", "heading": "", "art": {}}',
        "example": None},
    "proof_punch": {
        "name": "Proof Punch", "icon": "🥊", "voice": "one", "captions": True, "mood": "tegang", "needs_source": True,
        "look": "real quotes and sources on screen with big stamps that land on the key words",
        "suits": "klaim yang butuh bukti: studi, ulasan, angka, kutipan",
        "desc": "Kutipan dan sumber asli di layar, dengan stempel besar di kata kunci",
        "rules": "- Scene kinds: first \"claim\" (the striking claim, claim: 3-8 words), then 2-4 \"proof\" scenes, "
                 "last \"verdict\" (verdict: 1-2 words such as TERBUKTI, FAKTA, MITOS, HATI-HATI).\n"
                 "- proof.quote MUST be copied word for word from the SOURCE (8-30 words, no changes, no ellipsis in "
                 "the middle); proof.source: the outlet or site name; proof.stamp: 1-2 words that appear in that quote.\n"
                 "- The narration explains the quote in your own words; do not read the whole quote aloud.",
        "scene": '{"kind": "claim|proof|verdict", "narration": "", "claim": "", "quote": "", "source": "", "stamp": "", '
                 '"verdict": ""}',
        "example": {"title": "Benarkah jalan kaki 10 ribu langkah wajib?", "scenes": [
            {"kind": "claim", "narration": "Katanya harus sepuluh ribu langkah sehari. Ternyata angka itu bukan dari ilmuwan.",
             "claim": "10.000 langkah itu wajib?"},
            {"kind": "proof", "narration": "Peneliti menemukan manfaatnya sudah terlihat jauh di bawah angka itu.",
             "quote": "The benefits started at around 4,000 steps a day and kept rising up to about 8,000 steps",
             "source": "(sumber dari bahan)", "stamp": "4,000 steps"},
            {"kind": "verdict", "narration": "Jadi mulai saja dari yang kamu mampu, lalu naikkan pelan-pelan.",
             "verdict": "MITOS"}]}},
    "news_brief": {
        "name": "News brief", "icon": "📰", "voice": "one", "captions": True, "mood": "berita",
        "look": "a news-segment look: a headline, the key facts, and a ticker along the bottom",
        "suits": "peluncuran, pengumuman, berita industri, kejadian minggu ini",
        "desc": "Judul berita, fakta kunci, dan ticker di bawah",
        "rules": "- Scene kinds: first \"headline\" (headline: 4-9 words), then 2-4 \"fact\" scenes (fact: 4-12 words, "
                 "number: optional short figure from the source like \"Rp2 T\" or \"40%\"), last \"outro\" (fact: a "
                 "short question or what to watch next).\n"
                 "- Top level also has \"tag\" (TERKINI, BREAKING, UPDATE or EKSKLUSIF) and \"ticker\": 3-5 short phrases "
                 "(3-8 words) with other facts from the source.",
        "scene": '{"kind": "headline|fact|outro", "narration": "", "headline": "", "fact": "", "number": ""}',
        "top": ', "tag": "TERKINI", "ticker": ["", ""]',
        "example": {"title": "Kereta cepat tambah jadwal mulai bulan depan", "tag": "TERKINI",
                    "ticker": ["Tiket bisa dipesan lewat aplikasi", "Jadwal baru berlaku tiap akhir pekan"], "scenes": [
            {"kind": "headline", "narration": "Kereta cepat menambah jadwal perjalanan mulai bulan depan.",
             "headline": "Kereta cepat tambah jadwal"},
            {"kind": "fact", "narration": "Ada tambahan perjalanan setiap akhir pekan untuk mengurai antrean.",
             "fact": "Tambahan perjalanan tiap akhir pekan", "number": ""},
            {"kind": "outro", "narration": "Kamu bakal coba naik? Tulis di komentar.", "fact": "Kamu bakal coba?"}]}},
    "phone_in_hand": {
        "name": "Phone in hand", "icon": "📱", "voice": "one", "captions": True, "mood": "ceria", "needs_link": True,
        "look": "the real web page or app from the link, shown on a phone held in a hand and scrolled while the "
                "voice explains it", "suits": "aplikasi, situs, produk, promo, \"lihat yang kutemukan\"",
        "desc": "Halaman web asli ditampilkan di ponsel yang dipegang",
        "rules": "- Talk about what the page shows, like showing a friend something you found.\n"
                 "- callout: 2-6 words that pop up next to the phone; scroll: 0.0-1.0 how far down the page this "
                 "scene looks (start at 0, go down in order).",
        "scene": '{"narration": "", "callout": "", "scroll": 0.0}',
        "example": {"title": "Situs gratis buat belajar coding", "scenes": [
            {"narration": "Aku nemu situs buat belajar coding yang benar-benar gratis.", "callout": "100% gratis", "scroll": 0.0},
            {"narration": "Materinya dari dasar sampai bikin proyek sendiri.", "callout": "Dari nol", "scroll": 0.35},
            {"narration": "Simpan dulu, nanti kamu cari-cari.", "callout": "Simpan ya", "scroll": 0.7}]}},
    "text_story": {
        "name": "Text story", "icon": "💬", "voice": "two", "captions": False, "mood": "ceria",
        "look": "two people text the story out like a chat; each message is read by its sender's voice",
        "suits": "fakta mengejutkan sebagai reaksi (\"Serius?\"), debat, mitos vs fakta",
        "desc": "Dua orang mengobrol lewat chat, dengan dua suara",
        "rules": "- Each scene is ONE chat message: speaker \"A\" or \"B\", narration = the message text (3-18 words), "
                 "casual texting style. A starts with the hook; B reacts (\"Serius?\", \"Kok bisa?\"); A explains in "
                 "short messages; end with a punchline.\n"
                 "- Top level has \"cast\": {\"A\": name, \"B\": name} with short common first names.",
        "scene": '{"speaker": "A", "narration": ""}',
        "top": ', "cast": {"A": "", "B": ""}',
        "example": {"title": "Kenapa kucing suka kotak?", "cast": {"A": "Rina", "B": "Dimas"}, "scenes": [
            {"speaker": "A", "narration": "Kamu tahu kenapa kucingku lebih suka kardus daripada kasur mahal?"},
            {"speaker": "B", "narration": "Hah, kenapa?"},
            {"speaker": "A", "narration": "Ruang sempit bikin kucing merasa aman dan nggak gampang stres."},
            {"speaker": "B", "narration": "Pantes kasurnya nganggur terus."}]}},
    "bold_text": {
        "name": "Bold text", "icon": "🅰️", "voice": "one", "captions": False, "mood": "tegang",
        "look": "big bold words on strong colour, appearing word by word in time with the voice",
        "suits": "satu klaim mencolok, kutipan, cerita pendek yang menghentak",
        "desc": "Kata-kata besar di warna kuat, mengikuti suara",
        "rules": "- Short punchy scenes (4-14 words each); the words appear on screen exactly as spoken.\n"
                 "- key: 1-2 words from that scene's narration to highlight.",
        "scene": '{"narration": "", "key": [""]}',
        "example": {"title": "Satu kebiasaan yang mengubah pagimu", "scenes": [
            {"narration": "Berhenti cek HP di sepuluh menit pertama.", "key": ["sepuluh menit"]},
            {"narration": "Otakmu langsung sibuk menjawab orang lain.", "key": ["orang lain"]},
            {"narration": "Pakai sepuluh menit itu untuk dirimu sendiri.", "key": ["dirimu"]}]}},
    "text_on_video": {
        "name": "Text on video", "icon": "🎞️", "voice": "none", "captions": False, "mood": "santai", "stock": True,
        "look": "calm footage with music and no voiceover; the words light up as they are read, so it works muted",
        "suits": "tips, kutipan, motivasi, halaman tanpa suara",
        "desc": "Teks di atas video tenang, musik, tanpa suara",
        "rules": "- No voice: narration is the ON-SCREEN TEXT, read silently (4-14 words per scene).\n"
                 "- key: 1-2 words to highlight; stock: 2-4 English keywords for a calm background clip "
                 "(\"ocean waves sunset\", \"rain window cafe\").",
        "scene": '{"narration": "", "key": [""], "stock": ""}',
        "example": {"title": "3 kalimat untuk hari yang berat", "scenes": [
            {"narration": "Hari ini tidak harus sempurna.", "key": ["sempurna"], "stock": "calm ocean waves"},
            {"narration": "Cukup selesaikan satu hal kecil.", "key": ["satu hal"], "stock": "coffee morning window"},
            {"narration": "Sisanya bisa menunggu besok.", "key": ["besok"], "stock": "sunset clouds timelapse"}]}},
    "one_liner": {
        "name": "One-liner", "icon": "❓", "voice": "none", "captions": False, "mood": "santai", "lengths": [8],
        "look": "one big question or statement on screen, made to start a conversation in the comments",
        "suits": "pertanyaan ke penonton, polling, opini panas",
        "desc": "Satu pertanyaan besar untuk memancing komentar",
        "rules": "- Exactly one scene: narration = the question or statement (5-14 words), sub: 2-5 words inviting a "
                 "comment (\"Jawab di komentar\").",
        "scene": '{"narration": "", "sub": ""}',
        "example": {"title": "Pilih satu", "scenes": [
            {"narration": "Gaji besar tapi capek, atau gaji cukup tapi tenang?", "sub": "Jawab di komentar"}]}},
    "countdown": {
        "name": "Countdown", "icon": "🔢", "voice": "one", "captions": True, "mood": "ceria",
        "look": "a ranked top-3 list counted down to number one", "suits": "alat terbaik, tips teratas, perbandingan",
        "desc": "Daftar 3 teratas dihitung mundur sampai nomor satu",
        "rules": "- Scene kinds: \"intro\" (title: 3-7 words), then exactly three \"item\" scenes with rank 3, 2, 1 in "
                 "that order (name: 1-4 words, reason: 3-8 words, icon: one of ICONS), last \"outro\" (title: a 2-6 "
                 "word call to action).",
        "scene": '{"kind": "intro|item|outro", "narration": "", "title": "", "rank": 3, "name": "", "reason": "", "icon": "star"}',
        "example": {"title": "3 aplikasi catatan terbaik", "scenes": [
            {"kind": "intro", "narration": "Tiga aplikasi catatan terbaik, nomor satu paling gratis.", "title": "3 aplikasi catatan"},
            {"kind": "item", "rank": 3, "narration": "Nomor tiga, buat yang suka rapi dan berwarna.", "name": "Aplikasi A",
             "reason": "Rapi dan berwarna", "icon": "book"},
            {"kind": "item", "rank": 2, "narration": "Nomor dua, sinkron cepat di semua perangkat.", "name": "Aplikasi B",
             "reason": "Sinkron di semua perangkat", "icon": "phone"},
            {"kind": "item", "rank": 1, "narration": "Nomor satu, gratis dan bisa dipakai tanpa internet.", "name": "Aplikasi C",
             "reason": "Gratis dan offline", "icon": "trophy"},
            {"kind": "outro", "narration": "Kamu pakai yang mana? Tulis di komentar.", "title": "Kamu pakai yang mana?"}]}},
}
ORDER = ["cartoon_host", "whiteboard", "stickman", "proof_punch", "news_brief", "phone_in_hand", "text_story",
         "bold_text", "text_on_video", "one_liner", "countdown"]
FREE = {"cartoon_host", "whiteboard", "stickman", "news_brief", "bold_text", "one_liner"}   # info saja; semua gratis di sini
LENGTHS = [15, 30, 45, 60]
ENGINES = {"auto": "Otomatis (AI di Pengaturan, atau agen yang terpasang)", "llm": "AI di Pengaturan (Gemini gratis, OpenRouter, dll.)",
           "claude": "Claude Code", "codex": "Codex CLI (ChatGPT)", "gemini": "Gemini CLI (gratis, akun Google)",
           "qwen": "Qwen Code", "opencode": "opencode"}
DESIGN = {"cartoon_host": "pastel", "whiteboard": "clean", "proof_punch": "editorial", "news_brief": "corporate",
          "phone_in_hand": "bold_pop", "text_story": "clean", "bold_text": "bold_pop", "text_on_video": "dark_tech",
          "one_liner": "neon", "countdown": "dark_tech"}


def public() -> dict:
    from . import agents
    return {"formats": [{"id": k, "name": FORMATS[k]["name"], "icon": FORMATS[k]["icon"], "desc": FORMATS[k]["desc"],
                         "suits": FORMATS[k]["suits"], "voice": FORMATS[k]["voice"], "new": bool(FORMATS[k].get("new")),
                         "needs_link": bool(FORMATS[k].get("needs_link")), "needs_source": bool(FORMATS[k].get("needs_source")),
                         "lengths": FORMATS[k].get("lengths") or LENGTHS, "sample": f"/web/reels/{k}.jpg"} for k in ORDER],
            "engines": ENGINES, "agents": agents.public()}


# ---------------------------------------------------------------- template
def template(fmt: str) -> dict:
    """Kode adegan (HTML/CSS/JS MotionKit) untuk format; datanya dibaca template dari S.data."""
    common = (TPL_DIR / "_common.js").read_text(encoding="utf-8")
    files = {k: (TPL_DIR / f"{fmt}.{k}") for k in ("html", "css", "js")}
    return {"html": files["html"].read_text(encoding="utf-8") if files["html"].is_file() else "",
            "css": files["css"].read_text(encoding="utf-8") if files["css"].is_file() else "",
            "js": common + "\n" + files["js"].read_text(encoding="utf-8")}


def scene_data(fmt: str, scenes: list[dict], i: int, reel: dict) -> dict:
    """Data lengkap satu adegan untuk template: isi adegan + info reel + konteks (urutan, riwayat chat)."""
    sc = scenes[i]
    d = dict(sc.get("tdata") or {})
    d.update(i=i, n=len(scenes), narration=sc.get("narration", ""), heading=sc.get("heading", ""),
             speaker=sc.get("speaker") or d.get("speaker") or "A")
    d["reel"] = {k: reel.get(k) for k in ("cast", "ticker", "tag", "page", "shot", "shot_ratio", "title") if reel.get(k)}
    if fmt == "text_story":
        d["history"] = [{"from": s.get("speaker") or "A", "text": s.get("narration", "")} for s in scenes[max(0, i - 6):i]]
    if fmt == "phone_in_hand":
        d["prevScroll"] = (scenes[i - 1].get("tdata") or {}).get("scroll", 0) if i else 0
    if fmt == "countdown":
        d["ranks"] = [s.get("tdata", {}).get("rank") for s in scenes if (s.get("tdata") or {}).get("kind") == "item"]
    return d


# ---------------------------------------------------------------- isi reel
def _words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def word_budget(fmt: str, seconds: int, lang: str) -> int:
    if FORMATS[fmt]["voice"] == "none":
        return max(8, int(seconds * 1.6))
    return int(seconds * (2.5 if lang == "id" else 2.6))


def system_prompt(fmt: str, seconds: int, lang: str) -> str:
    f = FORMATS[fmt]
    words = word_budget(fmt, seconds, lang)
    n_lo, n_hi = (1, 1) if fmt == "one_liner" else (max(3, seconds // 9), max(4, seconds // 5))
    if fmt == "countdown":
        n_lo, n_hi = 5, 5
    top = f.get("top", "")
    schema = ('{"title": "", "description": "", "hashtags": ["", ""], "mood": "santai|ceria|tegang|berita|sedih|epik"'
              + top + ', "scenes": [' + f["scene"] + ']}')
    ex = f.get("example")
    lang_name = "Bahasa Indonesia" if lang == "id" else "English"
    extra = ""
    if f.get("theme"):
        from . import themes
        extra = themes.prompt_block(f["theme"])
    return f"""You write viral short vertical reels (Instagram Reels, YouTube Shorts, TikTok, Facebook) for faceless pages.
REEL FORMAT: {f['name']}: {f['look']}.

RULES
- Language: {lang_name}. Natural spoken {lang_name}: short sentences, everyday words, no filler, no emoji, no hashtags in
  the narration.
- Hook first: the first scene must stop the scroll within 2 seconds (at most 9 words): lead with the surprise, name the
  viewer's problem, or ask the question they are already thinking. Specific, never vague clickbait.
- One idea per video. Total narration about {words} words for a {seconds}-second reel, in {n_lo}-{n_hi} scenes.
- Facts: when a SOURCE is given, use only facts that are in it and never invent numbers, quotes, names or dates. Without
  a source, keep claims general and well known. Tell it in your own words (do not copy the source's sentences, except
  Proof Punch quotes).
- title: what the viewer gets (max 70 characters). description: 1-2 lines plus a question that invites comments.
  hashtags: 3-5 specific ones without spaces.
- End with a light call to action that fits the format (comment, save, follow), except One-liner.
- ICONS (use exactly these names): {', '.join(ICONS)}.
{f['rules']}{extra}

OUTPUT: one JSON object, nothing else:
{schema}
""" + (f"\nEXAMPLE of this format (different topic; match its quality, not its words):\n{json.dumps(ex, ensure_ascii=False)}\n"
       if ex else "")


def user_prompt(material: dict) -> str:
    parts = []
    if material.get("script"):
        parts.append("USE MY SCRIPT as the narration: keep my words and order, only split it into scenes, fix obvious "
                     "typos and trim it to fit the length.\nMY SCRIPT:\n" + material["script"][:6000])
    if material.get("topic"):
        parts.append(f"TOPIC: {material['topic'][:1500]}")
    if material.get("angle"):
        parts.append(f"MY ANGLE / NOTES: {material['angle'][:600]}")
    if material.get("source"):
        src = material["source"]
        parts.append(f"SOURCE ({src.get('site') or src.get('url', '')}): {src.get('title', '')}\n"
                     f"{src.get('description', '')}\n{(src.get('text') or '')[:9000]}")
    return "\n\n".join(parts) or "TOPIC: (none given; pick a widely relatable everyday topic)"


def ai_json(engine: str, system: str, prompt: str, out_dir: Path, audience: str) -> dict:
    """Minta JSON dari penulis yang dipilih. Otomatis: AI di Pengaturan, lalu agen yang terpasang."""
    from . import agents
    from .remake import _llm
    order = [engine] if engine not in ("", "auto") else ["llm"] + list(agents.available())
    last: Exception | None = None
    for eng in order:
        try:
            if eng == "llm":
                return _llm(out_dir, audience).complete_json(system, prompt)
            data = extract_json(agents.text(eng, system, prompt))
            if isinstance(data, dict):
                return data
            raise ClipAgentError("Jawaban AI bukan objek JSON.")
        except ClipAgentError as exc:
            last = exc
            if len(order) > 1:
                log(f"  {('AI di Pengaturan' if eng == 'llm' else agents.AGENTS[eng]['name'])}: {str(exc).splitlines()[0][:160]}")
    raise ClipAgentError(f"Tidak ada penulis AI yang bisa dipakai: {last}") if last else ClipAgentError("Penulis AI tidak ada.")


def _norm(t: str) -> str:
    t = (t or "").lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[^\w%.,']+", " ", t).strip()


def verify_quote(quote: str, source_text: str) -> str:
    """Kembalikan kutipan yang benar-benar ada di sumber: kutipan itu sendiri, atau kalimat sumber yang paling mirip."""
    q, src = _norm(quote), _norm(source_text)
    if q and len(q) > 15 and q in src:
        return quote.strip().strip('"“”')
    qt = set(q.split())
    best, score = "", 0.0
    for sent in re.split(r"(?<=[.!?])\s+|\n", source_text or ""):
        st = set(_norm(sent).split())
        if len(st) < 5 or not qt:
            continue
        sc = len(qt & st) / len(qt)
        if sc > score:
            best, score = sent.strip(), sc
    if score >= 0.5:
        w = best.split()
        return " ".join(w[:30]) + ("…" if len(w) > 30 else "")
    return ""


def _icon(v) -> str:
    v = str(v or "").strip().lower().replace(" ", "_").replace("-", "_")
    if v in ICONS:
        return v
    alias = {"lightbulb": "idea", "bulb": "idea", "cash": "money", "dollar": "money", "time": "clock", "watch": "clock",
             "love": "heart", "mind": "brain", "world": "globe", "earth": "globe", "growth": "chart_up", "up": "chart_up",
             "down": "chart_down", "house": "home", "user": "person", "users": "people", "team": "people", "ok": "check",
             "yes": "check", "no": "cross", "x": "cross", "settings": "gear", "security": "lock", "energy": "bolt",
             "electricity": "bolt", "plant": "leaf", "nature": "leaf", "award": "trophy", "win": "trophy", "alert": "warning",
             "danger": "warning", "help": "question", "hot": "fire", "goal": "target", "shopping": "cart", "buy": "cart",
             "drink": "water", "protect": "shield", "date": "calendar", "message": "chat", "talk": "chat", "find": "search",
             "present": "gift", "song": "music"}
    return alias.get(v, "idea")


def _s(v, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def clean(fmt: str, data: dict, source_text: str, seconds: int, lang: str) -> tuple[dict, list[str]]:
    """Rapikan jawaban AI untuk format ini. Mengembalikan (reel, masalah) — masalah dipakai untuk satu putaran perbaikan."""
    probs: list[str] = []
    if not isinstance(data, dict):
        return {}, ["the answer is not a JSON object"]
    raw = data.get("scenes") if isinstance(data.get("scenes"), list) else []
    scenes = []
    for k, sc in enumerate(raw):
        if not isinstance(sc, dict):
            continue
        narr = _s(sc.get("narration"), 400)
        if not narr:
            continue
        d: dict = {}
        heading = ""
        if fmt == "cartoon_host":
            d = {"board": _s(sc.get("board"), 48) or " ".join(narr.split()[:4]), "big": _s(sc.get("big"), 8),
                 "icon": _icon(sc.get("icon")), "mood": sc.get("mood") if sc.get("mood") in
                 ("happy", "surprised", "thinking", "serious", "excited") else "happy"}
            heading = d["board"]
        elif fmt == "whiteboard":
            items = [{"icon": _icon(x.get("icon")), "label": _s(x.get("label"), 24)} for x in (sc.get("items") or [])
                     if isinstance(x, dict)][:3] or [{"icon": "idea", "label": ""}]
            d = {"title": _s(sc.get("title"), 40) or " ".join(narr.split()[:4]), "items": items,
                 "link": sc.get("link") if sc.get("link") in ("arrow", "plus", "vs", "none") else "arrow"}
            heading = d["title"]
        elif fmt == "stickman":
            heading = _s(sc.get("heading"), 60)
            d = {"art": sc.get("art") if isinstance(sc.get("art"), dict) else {}}
        elif fmt == "proof_punch":
            kind = sc.get("kind") if sc.get("kind") in ("claim", "proof", "verdict") else "proof"
            d = {"kind": kind}
            if kind == "claim":
                d["claim"] = _s(sc.get("claim"), 70) or " ".join(narr.split()[:7])
                heading = d["claim"]
            elif kind == "verdict":
                d["verdict"] = _s(sc.get("verdict"), 18).upper() or "FAKTA"
                heading = d["verdict"]
            else:
                q = verify_quote(_s(sc.get("quote"), 400), source_text) if source_text else ""
                if not q:
                    probs.append(f"scene {k + 1}: the quote is not word for word in the SOURCE; copy an exact sentence")
                    d = {"kind": "claim", "claim": " ".join(narr.split()[:8])}
                else:
                    stamp = _s(sc.get("stamp"), 30)
                    if not stamp or _norm(stamp) not in _norm(q):
                        stamp = max(q.split(), key=len)
                    d.update(quote=q, source=_s(sc.get("source"), 40), stamp=stamp)
                heading = d.get("claim") or stamp if d["kind"] == "proof" else d.get("claim", "")
        elif fmt == "news_brief":
            kind = sc.get("kind") if sc.get("kind") in ("headline", "fact", "outro") else ("headline" if k == 0 else "fact")
            d = {"kind": kind, "headline": _s(sc.get("headline"), 80), "fact": _s(sc.get("fact"), 90), "number": _s(sc.get("number"), 12)}
            if kind == "headline" and not d["headline"]:
                d["headline"] = " ".join(narr.split()[:8])
            if kind != "headline" and not d["fact"]:
                d["fact"] = " ".join(narr.split()[:10])
            heading = d["headline"] or d["fact"]
        elif fmt == "phone_in_hand":
            try:
                scroll = max(0.0, min(1.0, float(sc.get("scroll") or 0)))
            except (TypeError, ValueError):
                scroll = 0.0
            d = {"callout": _s(sc.get("callout"), 40), "scroll": scroll}
            heading = d["callout"]
        elif fmt == "text_story":
            d = {"speaker": "B" if str(sc.get("speaker") or "").upper() == "B" else "A"}
        elif fmt in ("bold_text", "text_on_video"):
            key = [_s(x, 30) for x in (sc.get("key") or []) if _s(x, 30) and _norm(x) in _norm(narr)][:2]
            d = {"key": key}
            if fmt == "text_on_video":
                d["stock"] = _s(sc.get("stock"), 60) or "calm nature landscape"
        elif fmt == "one_liner":
            d = {"sub": _s(sc.get("sub"), 40) or ("Jawab di komentar" if lang == "id" else "Answer in the comments")}
        elif fmt == "countdown":
            kind = sc.get("kind") if sc.get("kind") in ("intro", "item", "outro") else "item"
            d = {"kind": kind, "title": _s(sc.get("title"), 50), "name": _s(sc.get("name"), 36), "reason": _s(sc.get("reason"), 60),
                 "icon": _icon(sc.get("icon"))}
            try:
                d["rank"] = int(sc.get("rank") or 0)
            except (TypeError, ValueError):
                d["rank"] = 0
            heading = d["title"] or d["name"]
        scenes.append({"narration": narr, "heading": heading, "tdata": d,
                       "speaker": d.get("speaker", "A") if fmt == "text_story" else ""})
    if not scenes:
        return {}, ["no usable scenes"]
    if fmt == "one_liner":
        scenes = scenes[:1]
    if fmt == "countdown":
        items = [s for s in scenes if s["tdata"]["kind"] == "item"]
        if len(items) != 3:
            probs.append(f"countdown needs exactly three item scenes (got {len(items)})")
        for s, r in zip(items, (3, 2, 1)):
            s["tdata"]["rank"] = r
        if scenes[0]["tdata"]["kind"] != "intro":
            probs.append("countdown must start with an intro scene")
    if fmt == "proof_punch" and source_text and not any(s["tdata"].get("kind") == "proof" for s in scenes):
        probs.append("proof punch needs at least one proof scene with an exact quote from the SOURCE")
    if fmt == "text_story":
        for a, b in zip(scenes, scenes[1:]):
            if a["speaker"] == b["speaker"] == "B":
                break
    total = sum(_words(s["narration"]) for s in scenes)
    target = word_budget(fmt, seconds, lang)
    if fmt != "one_liner" and total > target * 1.4:
        probs.append(f"too long: {total} words of narration, target about {target}")
    if fmt != "one_liner" and total < target * 0.55:
        probs.append(f"too short: {total} words of narration, target about {target}")
    hook = _words(scenes[0]["narration"])
    if fmt not in ("text_story",) and hook > 16:
        probs.append(f"the hook (first scene) has {hook} words; make it 9 words or fewer")
    tags = [re.sub(r"[^\w]", "", str(h)) for h in (data.get("hashtags") or [])][:6]
    reel = {"title": _s(data.get("title"), 90) or scenes[0]["narration"][:70],
            "description": _s(data.get("description"), 600), "hashtags": [t for t in tags if t],
            "mood": data.get("mood") if data.get("mood") in ("santai", "ceria", "tegang", "berita", "sedih", "epik") else
            FORMATS[fmt]["mood"], "scenes": scenes}
    if fmt == "text_story":
        cast = data.get("cast") if isinstance(data.get("cast"), dict) else {}
        reel["cast"] = {"A": _s(cast.get("A"), 16) or "Rina", "B": _s(cast.get("B"), 16) or "Dimas"}
    if fmt == "news_brief":
        reel["tag"] = _s(data.get("tag"), 14).upper() or ("TERKINI" if lang == "id" else "BREAKING")
        reel["ticker"] = [_s(x, 70) for x in (data.get("ticker") or []) if _s(x, 70)][:5] or \
            [s["tdata"].get("fact") for s in scenes if s["tdata"].get("fact")][:4]
    return reel, probs


def write(fmt: str, material: dict, *, seconds: int, lang: str, engine: str, out_dir: Path, audience: str) -> dict:
    system = system_prompt(fmt, seconds, lang)
    prompt = user_prompt(material)
    src_text = ((material.get("source") or {}).get("text") or "") + "\n" + ((material.get("source") or {}).get("description") or "")
    data = ai_json(engine, system, prompt, out_dir, audience)
    reel, probs = clean(fmt, data, src_text.strip(), seconds, lang)
    if probs:
        log("  Isi reel diperbaiki: " + "; ".join(probs)[:300])
        fix = (prompt + "\n\nYOUR PREVIOUS ANSWER:\n" + json.dumps(data, ensure_ascii=False)[:12000] +
               "\n\nFix these problems and answer with the full corrected JSON:\n- " + "\n- ".join(probs))
        try:
            data2 = ai_json(engine, system, fix, out_dir, audience)
            reel2, probs2 = clean(fmt, data2, src_text.strip(), seconds, lang)
            if reel2 and len(probs2) <= len(probs):
                reel = reel2
        except ClipAgentError as exc:
            log(f"  Perbaikan isi dilewati: {str(exc)[:160]}")
    if not reel:
        raise ClipAgentError("AI tidak memberi isi reel yang bisa dipakai. Coba lagi atau pilih penulis lain.")
    return reel


# ---------------------------------------------------------------- yang sedang ramai
_TREND_CACHE: dict[str, tuple[float, list]] = {}


def trending(kind: str, lang: str = "id") -> list[dict]:
    """Bahan cerita yang sedang ramai: berita utama, Google Trends, Hacker News, YouTube (bila ada API key)."""
    import time
    key = f"{kind}:{lang}"
    hit = _TREND_CACHE.get(key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    try:
        items = _trending(kind, lang)
    except requests.RequestException as exc:
        name = {"news": "Google News", "trends": "Google Trends", "hn": "Hacker News", "youtube": "YouTube"}.get(kind, kind)
        raise ClipAgentError(f"{name} tidak bisa dibuka sekarang (cek koneksi internet).") from exc
    _TREND_CACHE[key] = (time.time(), items)
    return items


def _trending(kind: str, lang: str) -> list[dict]:
    items: list[dict] = []
    if kind == "news":
        import xml.etree.ElementTree as ET
        url = ("https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id" if lang == "id"
               else "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        for it in ET.fromstring(r.content).iter("item"):
            title = (it.findtext("title") or "").strip()
            src = it.find("source")
            items.append({"title": title, "url": (it.findtext("link") or "").strip(),
                          "meta": (src.text if src is not None else "") or "", "when": it.findtext("pubDate") or ""})
            if len(items) >= 15:
                break
    elif kind == "trends":
        from . import trends
        for t in trends.fetch_trends("ID" if lang == "id" else "US")[:15]:
            news = (t.get("news") or [{}])[0]
            items.append({"title": t["title"] + (f": {news.get('title')}" if news.get("title") else ""),
                          "url": news.get("url", ""), "meta": t.get("traffic", ""), "when": t.get("published", "")})
    elif kind == "hn":
        ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=20).json()[:12]
        out: list = [None] * len(ids)

        def one(k: int, i: int):
            try:
                out[k] = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json", timeout=20).json()
            except requests.RequestException:
                pass
        ts = [threading.Thread(target=one, args=(k, i)) for k, i in enumerate(ids)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(25)
        for it in out:
            if it and it.get("title"):
                items.append({"title": it["title"], "url": it.get("url") or f"https://news.ycombinator.com/item?id={it['id']}",
                              "meta": f"{it.get('score', 0)} poin", "when": ""})
    elif kind == "youtube":
        from . import viral
        if not viral.api_key():
            raise ClipAgentError("Video YouTube teratas butuh YOUTUBE_API_KEY di Pengaturan. Atau cari di tab Riset lalu tempel tautannya.")
        for v in viral.trending_chart("", 15):
            items.append({"title": v.get("title", ""), "url": v.get("url") or f"https://www.youtube.com/watch?v={v.get('id')}",
                          "meta": f"{v.get('views', 0):,} tayangan".replace(",", "."), "when": ""})
    else:
        raise ClipAgentError("Sumber tren tidak dikenal.")
    return items


def recent(out_dir: Path, limit: int = 12) -> list[dict]:
    """Reel yang pernah dibuat (proyek Buat video bertanda reel), terbaru dulu."""
    from . import remake
    out = []
    for item in remake.list_projects(out_dir):
        try:
            pr = remake.load(out_dir, item["id"])
        except ClipAgentError:
            continue
        reel = (pr.get("settings") or {}).get("reel") or {}
        if not reel.get("format"):
            continue
        last = (pr.get("renders") or [None])[-1]
        video = ""
        if last:
            f = remake.pdir(out_dir, pr["id"]) / last["file"]
            if f.is_file():
                video = remake._url(out_dir, f)
        out.append({"project": pr["id"], "format": reel["format"], "format_name": FORMATS.get(reel["format"], {}).get("name", ""),
                    "title": pr["script"].get("title", ""), "description": pr["script"].get("description", ""),
                    "hashtags": pr["script"].get("hashtags", []), "video_url": video, "updated": pr.get("updated", ""),
                    "duration": (last or {}).get("duration")})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- buat reel dari awal sampai MP4
def make(out_dir: Path, raw: dict) -> dict:
    from . import download, remake, webpage
    fmt = raw.get("format") if raw.get("format") in FORMATS else "cartoon_host"
    f = FORMATS[fmt]
    src_type = raw.get("source_type") if raw.get("source_type") in ("link", "topic", "script", "trend") else "topic"
    text = str(raw.get("source") or "").strip()
    if not text:
        raise ClipAgentError("Isi dulu tautan, topik, atau naskahnya.")
    lengths = f.get("lengths") or LENGTHS
    try:
        seconds = int(raw.get("length") or 30)
    except (TypeError, ValueError):
        seconds = 30
    seconds = min(lengths, key=lambda x: abs(x - seconds))
    audience = "us" if raw.get("lang") == "en" else "id"
    lang = "en" if audience == "us" else "id"
    engine = raw.get("engine") if raw.get("engine") in ENGINES else "auto"
    url = text if re.match(r"https?://", text) else (str(raw.get("url") or "") if src_type == "trend" else "")
    if f.get("needs_link") and not url:
        raise ClipAgentError(f"Format {f['name']} butuh tautan halaman web (produk, aplikasi, artikel).")
    material: dict = {"angle": str(raw.get("angle") or "")[:600]}
    if src_type == "script" and not url:
        material["script"] = text[:6000]
    elif not url:
        material["topic"] = text[:1500]
    elif src_type == "trend":
        material["topic"] = str(raw.get("title") or "")[:300]

    settings = {"length": seconds, "aspect": "9:16", "audience": audience, "visual": "motion", "theme": "",
                "captions": bool(f["captions"]), "progress_bar": False, "music": "auto", "voice_mode": f["voice"],
                "motion_style": DESIGN.get(fmt, "clean"), "motion_engine": "auto"}
    if raw.get("voice") in ("pria", "wanita"):
        settings["voice_gender"] = raw["voice"]
    if f.get("theme"):
        settings.update(theme=f["theme"], visual="tema")
    proj = remake.new_project(out_dir, material.get("topic") or (material.get("script") or "")[:200] or url, settings, blank=True)
    pid = proj["id"]
    adir = remake.pdir(out_dir, pid) / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    reel_meta: dict = {"format": fmt}
    progress(0.03, "Membaca sumber")
    if url:
        log(f"Membaca {url}")
        try:
            if webpage.is_video_url(url):
                srcd = download.fetch_source_text(url, remake.pdir(out_dir, pid), lang)
                material["source"] = {"url": url, "title": srcd.get("title", ""), "site": srcd.get("channel", ""),
                                      "description": srcd.get("description", ""), "text": srcd.get("text", "")}
            else:
                page = webpage.fetch(url)
                material["source"] = page
                reel_meta["page"] = webpage.page_card(page)
        except ClipAgentError as exc:
            if f.get("needs_source") or f.get("needs_link"):
                raise
            log(f"  Sumber tidak terbaca ({str(exc)[:160]}); reel dibuat dari judul/topik saja.")
            material.setdefault("topic", str(raw.get("title") or url)[:300])
        if fmt in ("phone_in_hand", "news_brief") and not webpage.is_video_url(url):
            progress(0.08, "Mengambil tangkapan layar halaman")
            try:
                shot = webpage.screenshot(url, adir / f"shot_{uuid.uuid4().hex[:8]}.png")
                reel_meta["shot"] = "@asset:" + shot.name
                reel_meta["shot_ratio"] = webpage.image_ratio(shot)
            except ClipAgentError as exc:
                log(f"  Tangkapan layar dilewati: {str(exc)[:160]}")
    if f.get("needs_source") and not (material.get("source") or {}).get("text"):
        raise ClipAgentError("Proof Punch butuh sumber berisi teks (tautan artikel, studi, atau ulasan) agar kutipannya asli.")
    progress(0.12, f"Menulis isi reel {f['name']}")
    log(f"Menulis isi reel {f['name']} ({seconds} detik).")
    reel = write(fmt, material, seconds=seconds, lang=lang, engine=engine, out_dir=out_dir, audience=audience)
    for k in ("cast", "ticker", "tag"):
        if reel.get(k):
            reel_meta[k] = reel[k]
    reel_meta["title"] = reel["title"]
    proj = remake.load(out_dir, pid)
    src = material.get("source") or {}
    proj["source"] = {"url": url, "title": src.get("title", ""), "channel": src.get("site", "")}
    proj["topic"] = material.get("topic") or src.get("title") or proj.get("topic", "")
    scenes = []
    for k, sc in enumerate(reel["scenes"]):
        row = {"id": uuid.uuid4().hex[:6], "narration": sc["narration"], "heading": sc["heading"][:80],
               "visual": "", "prompt": "", "stock": (sc["tdata"].get("stock") or "")[:80], "camera": "static",
               "transition": "fade" if fmt not in ("text_story", "bold_text") else "none"}
        if f.get("theme"):
            row["art"] = sc["tdata"].get("art") or {}
        else:
            row.update(template=fmt, tdata=sc["tdata"])
        if sc.get("speaker"):
            row["speaker"] = sc["speaker"]
        scenes.append(row)
    proj["settings"]["reel"] = reel_meta
    proj["script"].update(title=reel["title"], description=reel["description"], hashtags=reel["hashtags"],
                          mood=reel["mood"], scenes=scenes)
    remake.save(out_dir, proj)
    res = remake.render(out_dir, pid)
    proj = remake.load(out_dir, pid)
    return {"project": pid, "format": fmt, "file": res.get("file"), "video_url": res.get("video_url"),
            "duration": res.get("duration"),
            "title": proj["script"]["title"], "description": proj["script"]["description"],
            "hashtags": proj["script"]["hashtags"]}
