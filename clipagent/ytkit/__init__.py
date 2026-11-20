"""Kanal YouTube: 11 skill dari youtube-agent-skill (MIT, Jake Schincariol) yang dijalankan di dalam Clip Agent.

Setiap skill memakai SKILL.md aslinya sebagai instruksi untuk AI, menjalankan alat Python-nya (penilai hook,
linter judul, daftar potong, bab, retensi, outlier) lewat tools.py, lalu menambah sumber data yang sudah
dimiliki Clip Agent: transkrip video di Library, subtitle YouTube lewat yt-dlp, komentar, dan daftar video
channel. Tambahan yang tidak ada di repo aslinya:
- kosakata bahasa Indonesia untuk semua alat penilai (tools.py);
- daftar potong bisa langsung DITERAPKAN ke video (apply_edit), bukan hanya dicetak;
- Shorts hasil temuan bisa langsung dirender oleh Clip Agent;
- naskah bisa langsung dijadikan video Kolase; deskripsi/tag bisa langsung dipakai di Posting;
- audit dan riset outlier mengumpulkan data channel sendiri (yt-dlp, tanpa login).
Seperti aslinya, tidak ada yang dipublikasikan otomatis: semua berakhir di teks yang Anda salin atau pakai.
"""
from __future__ import annotations

import base64
import json
import re
import statistics
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from ..config import PROJECT_DIR, Settings
from ..llm import LLMClient
from ..utils import ClipAgentError, check_cancel, log, progress
from . import tools as T

TOOLS = {
    "script": ("yt-script", "Naskah video", "Ide jadi naskah: 5 hook dari 21 rumus, dinilai, lalu naskah per beat."),
    "package": ("yt-package", "Judul & thumbnail", "10 pasangan judul + teks thumbnail, dicek panjang, duplikasi, dan kekaburan."),
    "seo": ("yt-seo", "Deskripsi & SEO", "Dua baris pertama, tag secukupnya, dan 3 kueri pencarian yang harus dimenangkan."),
    "chapters": ("yt-chapters", "Bab video", "Bab dari transkrip, divalidasi dengan aturan YouTube agar benar-benar tampil."),
    "shorts": ("yt-shorts", "Cari Shorts", "Momen 20–55 detik yang berdiri sendiri, dengan kalimat pembuka baru."),
    "edit": ("yt-edit", "Potong jeda & ulangan", "Daftar potong dari transkrip: jeda kosong, kata pengisi, kalimat diulang."),
    "retention": ("yt-retention", "Baca retensi", "File retensi dari YouTube Studio: hook leak, cliff, dan slide."),
    "viral": ("yt-viral", "Riset outlier", "Video yang mengalahkan median channelnya sendiri, beserta rumus judulnya."),
    "comment": ("yt-comment", "Balas komentar", "Komentar dipilah 4 kelompok, balasan dengan gaya Anda, dan yang perlu disematkan."),
    "plan": ("yt-plan", "Rencana mingguan", "Jadwal yang muat di jam Anda: satu video utama, satu ringan, tiga Shorts."),
    "audit": ("yt-audit", "Audit channel", "Judul, hook, ritme upload, dan SATU perbaikan terpenting."),
}
LANGS = {"id": "Bahasa Indonesia", "en": "English"}
ISSUE_ID = {
    "length": "terlalu panjang", "mobile": "terpotong di feed ponsel", "shouting": "terlalu banyak huruf kapital",
    "vague": "kata kabur", "no-number": "tanpa angka/nama/tanggal", "front-load": "subjek terlambat",
    "duplicate": "thumbnail mengulang judul", "thumb-length": "teks thumbnail terlalu panjang",
}
FIX_ID = {
    "SPECIFICITY": "ganti satu kata sifat dengan angka, nama, atau tanggal",
    "ADDRESS": "sebut \"kamu\" di enam kata pertama",
    "STAKES": "sebut apa ruginya kalau penonton terus melakukan cara yang sekarang",
    "CURIOSITY": "buang separuh kalimat yang menjawab dirinya sendiri",
    "BREVITY": "9 sampai 24 kata; baca keras-keras dan berhenti saat napas habis",
}
PROP_ID = {"SPECIFICITY": "Spesifik", "ADDRESS": "Menyapa penonton", "STAKES": "Taruhan", "CURIOSITY": "Rasa penasaran",
           "BREVITY": "Ringkas"}
BAND_ID = {"STRONG": "KUAT", "WORKABLE": "LUMAYAN", "WEAK": "LEMAH"}
VOICE_PATH = PROJECT_DIR / "data" / "voice.md"
VOICE_TEMPLATE_ID = """# Profil suara saya

Semua alat di tab Kanal membaca profil ini. Sepuluh menit di sini lebih berharga dari prompt mana pun,
karena di YouTube Anda harus mengucapkan kata-katanya sendiri.

## Siapa yang saya ajak bicara

Satu orang. Sebutkan dengan jelas, bukan "gamer", tapi misalnya "anak SMA yang main GTA di HP kentang dan
pengin tahu cara cepat dapat duit di game tanpa cheat".

## Cara saya benar-benar bicara

Tempel transkrip video terbaik Anda di sini, atau tiga video. Bukan cara bicara yang Anda inginkan.

## Kata yang tidak pernah saya pakai

Yang bukan gaya Anda. Spesifik: "gokil abis", "wajib tonton", "tanpa basa-basi".

## Kata yang saya pakai

Kebiasaan bicara Anda, ungkapan khas Anda. Pertahankan.

## Yang tidak akan saya klaim

Angka yang tidak bisa Anda tunjukkan, hasil yang bukan milik Anda, game yang belum Anda mainkan.

## Format saya

Durasi, cara membuka video, ada intro atau tidak, boleh kasar atau tidak, wajah tampil atau hanya facecam,
bahasa (Indonesia/Inggris/campur).
"""


# ---------------------------------------------------------------- dasar
def _hist(out_dir: Path) -> Path:
    d = out_dir / "_kanal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def voice_get() -> dict:
    exists = VOICE_PATH.is_file()
    return {"text": VOICE_PATH.read_text(encoding="utf-8") if exists else VOICE_TEMPLATE_ID, "exists": exists}


def voice_save(text: str) -> dict:
    text = (text or "").strip()
    if len(text) > 60_000:
        raise ClipAgentError("Profil suara terlalu panjang (maks. 60.000 karakter).")
    VOICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    VOICE_PATH.write_text(text + "\n", encoding="utf-8")
    return voice_get()


def _voice_for_prompt() -> str:
    if VOICE_PATH.is_file():
        txt = VOICE_PATH.read_text(encoding="utf-8").strip()
        if txt and txt != VOICE_TEMPLATE_ID.strip():
            return txt[:12000]
    return ""


def _client(out_dir: Path) -> LLMClient:
    try:
        cfg = Settings(source="-", out_dir=out_dir)
        cfg.resolve()
    except (ValueError, ClipAgentError) as exc:
        raise ClipAgentError(f"Pengaturan AI belum benar: {exc}") from exc
    if cfg.provider == "heuristic":
        raise ClipAgentError("Alat ini butuh penyedia AI. Atur di Pengaturan (mis. Gemini gratis), atau pakai "
                             "Uji hook dan Cek judul yang jalan tanpa AI.")
    return LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)


def _system(tool: str, lang: str) -> str:
    skill = TOOLS[tool][0]
    voice = _voice_for_prompt()
    return f"""You are running the "{skill}" skill from the open-source youtube-agent-skill pack, inside Clip Agent
(a desktop app for a YouTube creator). Follow the skill exactly. Its Python tools have ALREADY been run by the app;
their real output is in the user message. Never invent numbers, results, sources or quotes; if a figure is missing,
write the line without it.

Write your whole answer for the creator in Bahasa Indonesia, as clean Markdown (headings, short tables, lists).
Anything the creator will SAY on camera or PUBLISH (hooks, scripts, titles, thumbnail text, descriptions, replies)
must be in {LANGS.get(lang, lang)} and in the creator's voice. The creator cannot answer follow-up questions in this
flow: if information is missing, state your assumption in one short line and continue. End with the block the
creator copies, then the final line: **Kirim, atau ubah?**

## The skill
{T.skill_text(skill)}

## The creator's voice profile (voice.md)
{voice or "(Not filled in yet. Write in a natural, conversational voice, and add one line at the end telling the creator that filling in \"Profil suara\" in the Kanal tab will make every result sound like them.)"}
"""


def _save(out_dir: Path, tool: str, title: str, md: str, data: dict | None = None, actions: list | None = None) -> dict:
    res = {"id": f"{time.strftime('%Y%m%d_%H%M%S')}_{tool}_{uuid.uuid4().hex[:4]}", "tool": tool,
           "label": TOOLS.get(tool, ("", tool))[1] if tool in TOOLS else tool, "title": title[:120], "markdown": md,
           "data": data or {}, "actions": actions or [], "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    (_hist(out_dir) / f"{res['id']}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def history(out_dir: Path, limit: int = 40) -> list[dict]:
    items = []
    for p in sorted(_hist(out_dir).glob("2*_*.json"), reverse=True)[:limit]:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            items.append({k: r.get(k) for k in ("id", "tool", "label", "title", "created")})
        except (ValueError, OSError):
            continue
    return items


def get_result(out_dir: Path, rid: str) -> dict:
    if not re.fullmatch(r"[\w-]{6,80}", rid or ""):
        raise ClipAgentError("ID hasil tidak valid.")
    p = _hist(out_dir) / f"{rid}.json"
    if not p.is_file():
        raise ClipAgentError("Hasil tidak ditemukan.")
    return json.loads(p.read_text(encoding="utf-8"))


def delete_result(out_dir: Path, rid: str) -> None:
    get_result(out_dir, rid)
    (_hist(out_dir) / f"{rid}.json").unlink(missing_ok=True)


def library(out_dir: Path) -> list[dict]:
    """Video di Library yang punya transkrip (bisa dipakai sebagai sumber oleh alat Kanal)."""
    items = []
    for t in out_dir.glob("*/transcript.json"):
        d = t.parent
        if d.name.startswith("_"):
            continue
        meta = {}
        try:
            if (d / "meta.json").is_file():
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
        items.append({"id": d.name, "title": meta.get("title") or d.name, "duration": meta.get("duration") or 0,
                      "url": meta.get("url") or "", "video": bool(_source_video(out_dir, d.name)),
                      "mtime": t.stat().st_mtime})
    return sorted(items, key=lambda x: x["mtime"], reverse=True)


def ai_ready(out_dir: Path) -> bool:
    try:
        _client(out_dir)
        return True
    except ClipAgentError:
        return False


NEEDS_AI = {"script", "package", "seo", "shorts", "comment", "plan", "audit", "voice"}


def score_clips(clips: list[dict], words) -> None:
    """Skor kemasan tiap klip: kalimat pembuka (hookscore.py) dan judul (title.py). Dipakai pipeline klip."""
    openings = []
    for c in clips:
        ws = [w for w in words if c["start"] - 0.05 <= w.start < min(c["end"], c["start"] + 9)]
        text = ""
        for w in ws:
            text = (text + " " + w.text).strip()
            if len(text.split()) >= 8 and re.search(r"[.!?…]$", w.text):
                break
            if len(text.split()) >= 26:
                break
        openings.append(text)
    hooks = {r["hook"]: r for r in score_hooks_id([o for o in openings if len(o.split()) >= 3])}
    titles = {r["title"]: r for r in lint_titles_id([(c.get("title", ""), None) for c in clips if c.get("title")])}
    for c, o in zip(clips, openings):
        h = hooks.get(o)
        if h:
            c["opening"] = o
            c["hook_score"] = h["verdict"]
            c["hook_tip"] = "" if h["band"] == "STRONG" else f"{h['weakest_id']}: {h['fix_id']}"
        t = titles.get(c.get("title", ""))
        if t:
            c["title_score"] = t["score"]
            c["title_issues"] = [i["label"] for i in t["issues_id"]]


def score_hooks_id(hooks: list[str]) -> list[dict]:
    rows = T.score_hooks(hooks)
    for r in rows:
        r["band_id"] = BAND_ID[r["band"]]
        r["fix_id"] = FIX_ID[r["weakest"]]
        r["weakest_id"] = PROP_ID[r["weakest"]]
        r["properties_id"] = {PROP_ID[k]: v for k, v in r["properties"].items()}
    return rows


def lint_titles_id(pairs: list[tuple[str, str | None]]) -> list[dict]:
    rows = T.lint_titles(pairs)
    for r in rows:
        r["issues_id"] = [{"kind": k, "label": ISSUE_ID.get(k, k), "detail": _issue_detail(k, m, r)} for k, m in r["issues"]]
    return rows


def _issue_detail(kind: str, msg: str, row: dict) -> str:
    n = row["chars"]
    if kind == "length":
        return f"{n} karakter; pencarian desktop memotong sekitar 60, batas YouTube 100"
    if kind == "mobile":
        m = re.search(r'"(.*?)\.\.\."', msg)
        return f'feed ponsel hanya menampilkan "{m.group(1) if m else ""}…", pastikan subjeknya terlihat'
    if kind == "shouting":
        return "lebih dari dua kata huruf kapital semua terlihat seperti spam"
    if kind == "vague":
        return msg.split(" - ")[0] + ": ganti dengan angka, nama, atau tanggal"
    if kind == "no-number":
        return "tambahkan angka, tanggal, atau nama: perbaikan yang paling andal"
    if kind == "front-load":
        return "tiga kata pertama hanya kata pengisi; majukan subjeknya"
    if kind == "duplicate":
        m = re.search(r"title on (.*?) -", msg)
        return f"kata yang sama di judul dan thumbnail ({m.group(1) if m else ''}); thumbnail harus bilang hal lain"
    if kind == "thumb-length":
        return "maksimal tiga kata di thumbnail agar terbaca di ukuran feed"
    return msg


# ---------------------------------------------------------------- unggahan besar
def stash_uploads(out_dir: Path, inp: dict) -> dict:
    """File CSV/SRT yang diunggah disimpan ke disk agar opsi job (yang ikut dikirim ke daftar job) tetap kecil."""
    inp = dict(inp or {})

    def put(val: str) -> str:
        if len(val) < 4000:
            return val
        if len(val) > 25_000_000:
            raise ClipAgentError("File terlalu besar (maks. sekitar 18 MB).")
        name = f"up_{uuid.uuid4().hex[:12]}.txt"
        (_hist(out_dir) / name).write_text(val, encoding="utf-8")
        return f"@upload:{name}"
    if isinstance(inp.get("csv"), str):
        inp["csv"] = put(inp["csv"])
    for key in ("text",):
        if isinstance(inp.get(key), str):
            inp[key] = put(inp[key])
    src = inp.get("source")
    if isinstance(src, dict) and isinstance(src.get("text"), str):
        inp["source"] = dict(src, text=put(src["text"]))
    return inp


def _unstash(out_dir: Path, val):
    if isinstance(val, str) and val.startswith("@upload:"):
        name = val.split(":", 1)[1]
        if not re.fullmatch(r"up_[0-9a-f]{12}\.txt", name):
            raise ClipAgentError("Unggahan tidak valid.")
        p = _hist(out_dir) / name
        if not p.is_file():
            raise ClipAgentError("File unggahan sudah tidak ada; unggah ulang.")
        return p.read_text(encoding="utf-8")
    return val


# ---------------------------------------------------------------- sumber transkrip
def _cues_from_words(words) -> list[tuple[float, float, str]]:
    from ..transcript import group_segments
    return [(round(s.start, 2), round(s.end, 2), s.text) for s in group_segments(words, max_gap=0.6, max_len=7.0)
            if s.text.strip()]


def _yt_info(url: str, extra: dict | None = None) -> dict:
    import os

    import yt_dlp

    from ..download import _QuietLogger, _explain_ytdlp_error
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": _QuietLogger(), "skip_download": True,
            **(extra or {})}
    if os.getenv("COOKIES_FROM_BROWSER"):
        opts["cookiesfrombrowser"] = (os.getenv("COOKIES_FROM_BROWSER"),)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            return ydl.sanitize_info(ydl.extract_info(url, download=False))
        except Exception as exc:
            raise ClipAgentError(_explain_ytdlp_error(str(exc))) from exc


def _url_words(url: str, lang: str, cache: Path):
    """Kata bertanda waktu dari subtitle YouTube (tanpa mengunduh video); bila tidak ada, Whisper dari audio."""
    from ..transcript import Word, words_from_json3
    if cache.is_file():
        d = json.loads(cache.read_text(encoding="utf-8"))
        return d["meta"], [Word(*w) for w in d["words"]]
    import yt_dlp

    from ..download import _QuietLogger, _pick_caption
    info = _yt_info(url)
    meta = {"title": info.get("title", ""), "url": info.get("webpage_url") or url, "duration": info.get("duration") or 0,
            "channel": info.get("channel") or info.get("uploader") or "", "id": info.get("id", "")}
    words = []
    picked = _pick_caption(info, lang)
    if picked:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "logger": _QuietLogger()}) as ydl:
                words = words_from_json3(json.loads(ydl.urlopen(picked[0]).read().decode("utf-8")))
        except Exception as exc:                                    # noqa: BLE001
            log(f"Subtitle tidak bisa diambil ({type(exc).__name__}).")
    if not words:
        import importlib.util
        if not importlib.util.find_spec("faster_whisper"):
            raise ClipAgentError("Video ini tidak punya subtitle dan Whisper belum terpasang "
                                 "(pip install -r requirements-whisper.txt).")
        from ..transcript import words_from_whisper
        log("Subtitle tidak ada: mengunduh audio untuk Whisper…")
        with tempfile.TemporaryDirectory() as d:
            with yt_dlp.YoutubeDL({"quiet": True, "logger": _QuietLogger(), "format": "ba/bestaudio/b",
                                   "outtmpl": str(Path(d) / "a.%(ext)s"), "noplaylist": True}) as ydl:
                ydl.download([url])
            audio = next(iter(Path(d).glob("a.*")), None)
            if audio:
                words, _ = words_from_whisper(audio, "base", None)
    cache.write_text(json.dumps({"meta": meta, "words": [[w.start, w.end, w.text] for w in words]}, ensure_ascii=False),
                     encoding="utf-8")
    return meta, words


def get_source(out_dir: Path, src: dict | None, need_timing: bool = False, lang: str = "id") -> dict:
    """Sumber teks: video di Library, URL YouTube, file SRT/VTT yang diunggah, atau teks biasa."""
    src = src or {}
    kind = src.get("kind") or ""
    if kind == "library":
        from ..transcript import load_words
        vid = str(src.get("video_id") or "")
        if not re.fullmatch(r"[\w.-]{2,80}", vid) or not (out_dir / vid / "transcript.json").is_file():
            raise ClipAgentError("Video Library tidak ditemukan atau belum punya transkrip.")
        words, _, _ = load_words(out_dir / vid / "transcript.json")
        meta = {}
        for name in ("meta.json",):
            if (out_dir / vid / name).is_file():
                meta = json.loads((out_dir / vid / name).read_text(encoding="utf-8"))
        cues = _cues_from_words(words)
        return {"kind": kind, "video_id": vid, "title": meta.get("title", vid), "url": meta.get("url", ""),
                "duration": float(meta.get("duration") or (cues[-1][1] if cues else 0)), "cues": cues,
                "text": " ".join(c[2] for c in cues)}
    if kind == "url":
        url = str(src.get("url") or "").strip()
        if not re.match(r"https?://", url):
            raise ClipAgentError("Isi URL video YouTube.")
        key = re.sub(r"\W+", "_", url)[-60:]
        meta, words = _url_words(url, lang, _hist(out_dir) / f"src_{key}.json")
        cues = _cues_from_words(words)
        return {"kind": kind, "title": meta["title"], "url": meta["url"], "duration": float(meta["duration"] or 0),
                "cues": cues, "text": " ".join(c[2] for c in cues), "channel": meta.get("channel", "")}
    if kind == "srt":
        raw = str(_unstash(out_dir, src.get("text")) or "")
        if raw.startswith("data:"):
            raw = base64.b64decode(raw.split(",", 1)[1]).decode("utf-8", "replace")
        if "-->" not in raw:
            raise ClipAgentError("File transkrip harus SRT atau VTT (berisi waktu 00:00:01,000 --> ...).")
        da = T.deadair_mod()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ("t.vtt" if raw.lstrip().startswith("WEBVTT") else "t.srt")
            p.write_text(raw, encoding="utf-8")
            cues = [(float(a), float(b), t) for a, b, t in da.load(str(p))]
        return {"kind": kind, "title": str(src.get("title") or "Transkrip"), "url": "", "cues": cues,
                "duration": cues[-1][1] if cues else 0, "text": " ".join(c[2] for c in cues)}
    text = re.sub(r"\s+", " ", str(_unstash(out_dir, src.get("text")) or "")).strip()
    if need_timing:
        raise ClipAgentError("Alat ini butuh transkrip bertanda waktu: pilih video dari Library, isi URL YouTube, "
                             "atau unggah file SRT/VTT.")
    return {"kind": "text", "title": str(src.get("title") or ""), "url": "", "cues": [], "duration": 0, "text": text}


def _has_source(src: dict | None) -> bool:
    src = src or {}
    return bool(src.get("video_id") or src.get("url") or src.get("text"))


def _mmss(t: float) -> str:
    t = int(t)
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _transcript_lines(cues: list, limit_chars: int = 14000) -> str:
    lines, n = [], 0
    for a, b, t in cues:
        line = f"[{_mmss(a)}|{a:.1f}-{b:.1f}] {t}"
        n += len(line) + 1
        if n > limit_chars:
            lines.append("[… transkrip dipotong …]")
            break
        lines.append(line)
    return "\n".join(lines)


def _panel_md(rows: list[dict]) -> str:
    head = "| Hook | Skor | " + " | ".join(PROP_ID.values()) + " | Rumus |\n|---|---|" + "---|" * len(PROP_ID) + "---|"
    body = [f"| {r['hook']} | **{r['verdict']}** {r['band_id']} | " + " | ".join(str(v) for v in r["properties"].values())
            + f" | {r['formula']} |" for r in rows]
    return "\n".join([head] + body)


# ---------------------------------------------------------------- 1. naskah
def run_script(out_dir: Path, inp: dict) -> dict:
    idea = str(inp.get("idea") or "").strip()
    if len(idea) < 8:
        raise ClipAgentError("Tulis idenya dulu (satu atau dua kalimat).")
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    minutes = max(0.5, min(40.0, float(inp.get("minutes") or 8)))
    c = _client(out_dir)
    sys_ = _system("script", lang)
    fl = "\n".join(f"- {f['name']}: {f['shape']} Example: {f['example']} Fails when: {f['fails_when']}" for f in T.formulas())
    rules = "\n".join(f"- {r}" for r in T.formula_rules()["rules"])
    progress(0.1, "Menulis 5 hook")
    data = c.complete_json(sys_ + "\nFor THIS step answer ONLY with JSON.",
                           f"Video idea: {idea}\nNotes: {inp.get('notes') or '-'}\n\nThe 21 hook formulas:\n{fl}\n\nRules:\n{rules}\n\n"
                           f"Write FIVE hook options (the first 15 seconds, spoken, 9-24 words each) in {LANGS[lang]}, each from a "
                           "DIFFERENT formula. JSON: {\"hooks\": [{\"text\": \"\", \"formula\": \"\"}]}", list_key="hooks")
    hooks = [str(h.get("text") if isinstance(h, dict) else h).strip() for h in data.get("hooks") or []][:5]
    hooks = [h for h in hooks if h]
    if len(hooks) < 2:
        raise ClipAgentError("AI tidak memberi hook yang bisa dinilai. Coba lagi.")
    scored = score_hooks_id(hooks)
    progress(0.4, "Menilai hook dan menulis naskah")
    budget = int(minutes * 150)
    top = scored[:2]
    md = c.complete_text(sys_, f"""Video idea: {idea}
Notes: {inp.get('notes') or '-'}
Target runtime: {minutes:g} minutes = about {budget} spoken words at 150 words per minute.

hookscore.py output for all five hooks (Indonesian vocabulary added by the app), best first:
{json.dumps([{k: r[k] for k in ('hook', 'verdict', 'band', 'formula', 'properties', 'weakest')} for r in scored], ensure_ascii=False, indent=1)}

Hand back, in this order:
1. The two best hooks with their scored panels (a table: hook, score, the five properties) and, for each, its weakest
   property with a concrete fix.
2. The script, beat by beat (the turn, the body beats, the payoff, the close), with [ON SCREEN: ...] on every beat.
   The spoken lines in {LANGS[lang]}.
3. One line naming which formula the winning hook used and why it fits this idea.
4. Then a fenced code block with the info string `naskah` containing ONLY the words to be spoken, start to finish
   (winning hook first), no stage directions, no [ON SCREEN] notes, no headings. The app uses it for the teleprompter,
   the runtime estimate and text-to-speech.""")
    spoken = _fenced(md, "naskah")
    nwords = len(spoken.split())
    runtime = nwords / 150 * 60
    md += f"\n\n> Perkiraan durasi dihitung aplikasi: **{nwords} kata ≈ {_mmss(runtime)}** pada 150 kata/menit."
    actions = [{"type": "kolase", "label": "Jadikan video Kolase (suara AI)", "text": spoken}] if spoken else []
    return _save(out_dir, "script", idea, md, {"hooks": scored, "spoken": spoken, "words": nwords,
                                                "runtime": round(runtime)}, actions)


def _fenced(md: str, info: str) -> str:
    m = re.search(rf"```{info}\s*\n(.*?)```", md, re.S)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------- 2. judul & thumbnail
def run_package(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    topic = str(inp.get("topic") or "").strip()
    src = get_source(out_dir, inp.get("source"), lang=lang) if _has_source(inp.get("source")) else None
    if not topic and not src:
        raise ClipAgentError("Tulis topik/isi videonya, atau pilih video sebagai sumber.")
    ctx = (src["text"][:6000] if src else "")
    c = _client(out_dir)
    sys_ = _system("package", lang)
    progress(0.15, "Menulis 10 judul + thumbnail")
    data = c.complete_json(sys_ + "\nFor THIS step answer ONLY with JSON.",
                           f"Video topic: {topic or (src or {}).get('title', '')}\nCurrent title: {inp.get('current') or '-'}\n"
                           f"What the video says (excerpt): {ctx or '-'}\n\nWrite TEN title + thumbnail-text pairings in "
                           f"{LANGS[lang]}. Thumbnail text: max three words, different words from the title, same promise. "
                           "JSON: {\"pairs\": [{\"title\": \"\", \"thumb\": \"\"}]}", list_key="pairs")
    pairs = [(str(p.get("title") or "").strip(), str(p.get("thumb") or "").strip())
             for p in data.get("pairs") or [] if isinstance(p, dict)]
    rows = lint_titles_id([p for p in pairs if p[0]])
    if not rows:
        raise ClipAgentError("AI tidak memberi judul. Coba lagi.")
    thumbs = dict(pairs)
    for r in rows:
        r["thumb"] = thumbs.get(r["title"], "")
    progress(0.55, "Memilih tiga terbaik dan menulis brief thumbnail")
    md = c.complete_text(sys_, f"""Video topic: {topic or (src or {}).get('title', '')}
title.py output for all ten pairings, best first:
{json.dumps([{k: r[k] for k in ('title', 'thumb', 'chars', 'score', 'issues', 'good')} for r in rows], ensure_ascii=False, indent=1)}

Show the top three with their scores and the specific issue on each (in Indonesian). For the winner write the thumbnail
brief: the expression, the framing, the three words, and what the background must do to hold contrast at feed size.
End with a copy block containing the winning title and thumbnail text.""")
    win = rows[0]
    return _save(out_dir, "package", topic or (src or {}).get("title", ""), md, {"rows": rows},
                 [{"type": "posting", "label": "Pakai judul di Posting", "title": win["title"]}])


# ---------------------------------------------------------------- 3. SEO
STOP_Q = T.ID_STOP | {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "how", "what", "why", "with"}


def run_seo(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    title = str(inp.get("title") or "").strip()
    src = get_source(out_dir, inp.get("source"), lang=lang) if _has_source(inp.get("source")) else None
    if not title and not src:
        raise ClipAgentError("Isi judul video, atau pilih video sebagai sumber.")
    title = title or src["title"]
    c = _client(out_dir)
    sys_ = _system("seo", lang)
    progress(0.2, "Menulis deskripsi dan kueri")
    data = c.complete_json(sys_ + "\nFor THIS step answer ONLY with JSON.",
                           f"Title: {title}\nSummary/notes: {inp.get('summary') or '-'}\nLinks/resources: {inp.get('links') or '-'}\n"
                           f"Chapters block (paste as-is if given): {inp.get('chapters') or '-'}\n"
                           f"Transcript excerpt: {(src or {}).get('text', '')[:7000] or '-'}\n\n"
                           f"Write in {LANGS[lang]}: the full description (first two lines say what the viewer gets, in the words "
                           "they would type; then the link if any; then the chapters block if given; then the long version), at most "
                           "15 tags for disambiguation only, and the THREE search queries this video should win. Also say if this "
                           "video is aimed at the subscriber feed rather than search. JSON: {\"description\": \"\", \"tags\": [], "
                           "\"queries\": [], \"feed_video\": false, \"note\": \"\"}")
    desc = str(data.get("description") or "").strip()
    tags = [str(t).strip().lstrip("#") for t in data.get("tags") or [] if str(t).strip()][:15]
    queries = [str(q).strip() for q in data.get("queries") or [] if str(q).strip()][:3]
    first2 = " ".join(desc.splitlines()[:2])
    hay = set(re.findall(r"\w+", (title + " " + first2).lower()))
    test = []
    for q in queries:
        need = [w for w in re.findall(r"\w+", q.lower()) if w not in STOP_Q]
        miss = [w for w in need if w not in hay]
        test.append({"query": q, "ok": not miss, "missing": miss})
    md = [f"## Deskripsi\n\n```\n{desc}\n```", f"## Tag ({len(tags)})\n\n```\n{', '.join(tags)}\n```",
          "## Uji kueri\n\nSetiap kueri harus muncul di judul atau dua baris pertama deskripsi.\n\n| Kueri | Hasil |\n|---|---|"]
    md += [f"| {t['query']} | {'✓ lolos' if t['ok'] else '✗ kurang: ' + ', '.join(t['missing'])} |" for t in test]
    if any(not t["ok"] for t in test):
        md.append("\nAda kueri yang tidak lolos: masalahnya di **judul**, bukan deskripsi. Coba alat *Judul & thumbnail*.")
    if data.get("feed_video"):
        md.append("\n> Video ini lebih cocok untuk feed subscriber daripada pencarian; tenaga lebih baik dipakai di judul & thumbnail.")
    if data.get("note"):
        md.append(f"\n{data['note']}")
    md.append("\n**Kirim, atau ubah?**")
    return _save(out_dir, "seo", title, "\n".join(md), {"description": desc, "tags": tags, "queries": test},
                 [{"type": "posting", "label": "Pakai di Posting", "title": title, "description": desc, "tags": tags}])


# ---------------------------------------------------------------- 4. bab
def run_chapters(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    src = get_source(out_dir, inp.get("source"), need_timing=True, lang=lang)
    if len(src["cues"]) < 6:
        raise ClipAgentError("Transkrip terlalu pendek untuk dibuat bab.")
    target = max(3, min(20, int(inp.get("target") or 7)))
    res = T.chapter_list(src["cues"], target)
    if res.get("error"):
        raise ClipAgentError(f"chapters.py: {res['error']}")
    chs = res["chapters"]
    titles = [c["draft_title"] for c in chs]
    try:
        c = _client(out_dir)
        sections = []
        for i, ch in enumerate(chs):
            end = chs[i + 1]["start"] if i + 1 < len(chs) else src["duration"] or 1e9
            text = " ".join(t for a, b, t in src["cues"] if a >= ch["start"] and a < end)[:600]
            sections.append({"i": i, "start": ch["label"], "draft": ch["draft_title"], "text": text})
        progress(0.5, "Menamai ulang tiap bab")
        data = c.complete_json(_system("chapters", lang) + "\nFor THIS step answer ONLY with JSON.",
                               f"Sections found by chapters.py:\n{json.dumps(sections, ensure_ascii=False)}\n\nRetitle every "
                               f"section as the promise of that section, 3-5 words, in {LANGS[lang]}, in the creator's voice. Flag "
                               "a section that cannot be named in five words. JSON: {\"titles\": [{\"i\": 0, \"title\": \"\"}], \"flags\": []}",
                               list_key="titles")
        for t in data.get("titles") or []:
            if isinstance(t, dict) and isinstance(t.get("i"), int) and 0 <= t["i"] < len(titles) and t.get("title"):
                titles[t["i"]] = str(t["title"]).strip()[:60]
        flags = [str(f) for f in data.get("flags") or []][:5]
    except ClipAgentError as exc:
        log(f"Judul bab tidak ditulis ulang oleh AI ({str(exc).splitlines()[0][:100]}); memakai draf kata kunci.")
        flags = ["Judul masih draf kata kunci; tulis ulang sendiri sebelum ditempel."]
    block = "\n".join(f"{c['label']} {t}" for c, t in zip(chs, titles))
    ok = res.get("valid")
    md = [f"## Bab untuk *{src['title']}*\n", f"```\n{block}\n```",
          "✓ Lolos aturan YouTube: mulai 0:00, minimal 3 bab, tiap bab minimal 10 detik." if ok else
          "✗ **Belum valid**: YouTube butuh minimal 3 bab, mulai 0:00, tiap bab minimal 10 detik. Blok ini tidak akan tampil sebagai bab."]
    md += [f"- {f}" for f in flags]
    md.append("\n**Kirim, atau ubah?**")
    return _save(out_dir, "chapters", src["title"], "\n".join(md), {"chapters": [dict(c, title=t) for c, t in zip(chs, titles)],
                                                                    "valid": ok, "block": block},
                 [{"type": "chapters", "label": "Pakai di Deskripsi & SEO", "block": block}])


# ---------------------------------------------------------------- 5. edit (daftar potong) + terapkan
KIND_ID = {"DEAD": "Jeda kosong", "FILLER": "Kata pengisi", "REPEAT": "Kalimat diulang"}


def run_edit(out_dir: Path, inp: dict) -> dict:
    src = get_source(out_dir, inp.get("source"), need_timing=True)
    floor = max(0.2, min(3.0, float(inp.get("floor") or 0.45)))
    res = T.edit_list(src["cues"], floor)
    if res.get("error"):
        raise ClipAgentError(f"deadair.py: {res['error']}")
    cuts = res["cuts"]
    dur, removed = res["duration"], res["removed"]
    md = [f"## Daftar potong: *{src['title']}*", "",
          f"{len(cuts)} potongan, **{removed:.1f} dtk** dibuang, durasi jadi **{_mmss(res['out'])}** "
          f"({removed / dur * 100 if dur else 0:.1f}% lebih pendek). Batas jeda {floor:g} dtk, dipotong di tengah agar kedua sisi tetap bernapas.",
          "", "| Jenis | Mulai | Selesai | Durasi | Alasan |", "|---|---|---|---|---|"]
    md += [f"| {KIND_ID.get(c['kind'], c['kind'])} | {c['start']:.2f} | {c['end']:.2f} | {c['end'] - c['start']:.2f} | {_why_id(c)} |"
           for c in cuts[:300]]
    md.append("\n> Persentase dihitung dari UCAPAN. Bila video punya bagian demo/gameplay tanpa suara yang panjang, "
              "cek dulu hasilnya sebelum percaya durasi akhirnya.")
    actions = []
    if src["kind"] == "library" and cuts and _source_video(out_dir, src["video_id"]):
        actions.append({"type": "apply_edit", "label": "Terapkan potongan ke video", "video_id": src["video_id"]})
    md.append("\n**Kirim, atau ubah?**")
    return _save(out_dir, "edit", src["title"], "\n".join(md), {**res, "video_id": src.get("video_id")}, actions)


def _why_id(c: dict) -> str:
    why = str(c.get("why") or "")
    m = re.fullmatch(r"([\d.]+)s gap", why)
    if m:
        return f"jeda {float(m.group(1)):.2f} dtk"
    m = re.fullmatch(r'restart of "(.*)"', why)
    if m:
        return f'diulang: "{m.group(1)}"'
    return f'hanya kata pengisi: "{why}"' if c.get("kind") == "FILLER" else why


def _source_video(out_dir: Path, vid: str) -> Path | None:
    from ..download import _find_video
    return _find_video(out_dir / vid) if (out_dir / vid).is_dir() else None


def apply_edit(out_dir: Path, rid: str) -> dict:
    """Terapkan daftar potong ke video sumber di Library: hasilnya video baru tanpa jeda/pengisi/ulangan."""
    res = get_result(out_dir, rid)
    if res.get("tool") != "edit" or not res["data"].get("video_id"):
        raise ClipAgentError("Hasil ini bukan daftar potong untuk video Library.")
    vid = res["data"]["video_id"]
    src = _source_video(out_dir, vid)
    if not src:
        raise ClipAgentError("Video sumber tidak ditemukan di Library.")
    from ..utils import probe
    info = probe(src)
    dur = info["duration"]
    cuts = sorted((max(0.0, c["start"]), min(dur, c["end"])) for c in res["data"]["cuts"] if c["end"] > c["start"])
    keep, t = [], 0.0
    for a, b in cuts:
        if a > t + 0.05:
            keep.append((t, a))
        t = max(t, b)
    if dur - t > 0.05:
        keep.append((t, dur))
    if not keep:
        raise ClipAgentError("Tidak ada bagian yang tersisa setelah dipotong.")
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    out = out_dir / vid / f"edited_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    script = Path(tempfile.mkstemp(suffix=".txt")[1])
    script.write_text(f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];"
                      + (f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]" if info["has_audio"] else ""), encoding="utf-8")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex_script", str(script), "-map", "[v]"]
    if info["has_audio"]:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", str(out)]
    log(f"Menerapkan {len(cuts)} potongan ({len(keep)} bagian dipertahankan)…")
    progress(0.2, "Memotong video")
    r = subprocess.run(cmd, capture_output=True, text=True)
    script.unlink(missing_ok=True)
    if r.returncode != 0:
        out.unlink(missing_ok=True)
        raise ClipAgentError(f"ffmpeg gagal memotong: {r.stderr.strip()[-300:]}")
    new = probe(out)["duration"]
    log(f"Selesai: {out.name} ({_mmss(dur)} → {_mmss(new)})")
    progress(1.0, "Video hasil edit siap")
    rel = out.relative_to(out_dir).as_posix()
    return {"file": rel, "video_url": f"/files/{rel}?v={int(out.stat().st_mtime)}", "before": round(dur, 2), "after": round(new, 2)}


# ---------------------------------------------------------------- 6. Shorts
def run_shorts(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    src = get_source(out_dir, inp.get("source"), need_timing=True, lang=lang)
    n = max(1, min(8, int(inp.get("count") or 5)))
    c = _client(out_dir)
    progress(0.15, "Membaca transkrip dan mencari momen")
    data = c.complete_json(_system("shorts", lang) + "\nFor THIS step answer ONLY with JSON.",
                           f"Video: {src['title']} ({_mmss(src['duration'])})\nTranscript (start|seconds range):\n"
                           f"{_transcript_lines(src['cues'])}\n\nFind the {n} best Shorts: spans of 20-55 seconds that open on a "
                           "complete thought, contain a turn, and end on a line. Use the seconds from the transcript. For each: "
                           f"a NEW first line ({LANGS[lang]}) for viewers without context, on-screen text for the first two seconds "
                           "(different words, max 6), the loop point, a vertical framing note, and why it survives alone. JSON: "
                           "{\"shorts\": [{\"start\": 0, \"end\": 0, \"first_line\": \"\", \"new_first_line\": \"\", "
                           "\"on_screen\": \"\", \"loop\": \"\", \"framing\": \"\", \"why\": \"\"}]}", list_key="shorts")
    dur = src["duration"] or (src["cues"][-1][1] if src["cues"] else 0)
    picks = []
    for s in data.get("shorts") or []:
        try:
            a, b = float(s.get("start")), float(s.get("end"))
        except (TypeError, ValueError):
            continue
        a = max(0.0, a)
        b = min(dur, b) if dur else b
        if b - a < 12 or b - a > 75:
            continue
        # rapikan ke batas kalimat terdekat
        starts = [q[0] for q in src["cues"]]
        ends = [q[1] for q in src["cues"]]
        a = min(starts, key=lambda x: abs(x - a)) if starts else a
        b = min(ends, key=lambda x: abs(x - b)) if ends else b
        if b - a < 12:
            continue
        picks.append({**{k: str(s.get(k) or "").strip() for k in ("first_line", "new_first_line", "on_screen", "loop",
                                                                   "framing", "why")}, "start": round(a, 2), "end": round(b, 2)})
    if not picks:
        raise ClipAgentError("AI tidak menemukan momen yang valid. Coba lagi atau pakai video yang lebih panjang.")
    scored = {r["hook"]: r for r in score_hooks_id([p["new_first_line"] for p in picks if p["new_first_line"]])}
    md = [f"## {len(picks)} Shorts dari *{src['title']}*", "", "| # | Waktu | Kalimat pembuka baru | Skor hook | Teks layar |",
          "|---|---|---|---|---|"]
    for i, p in enumerate(picks, 1):
        sc = scored.get(p["new_first_line"])
        p["hook_score"] = sc["verdict"] if sc else None
        md.append(f"| {i} | {_mmss(p['start'])}–{_mmss(p['end'])} ({p['end'] - p['start']:.0f} dtk) | {p['new_first_line']} | "
                  f"{(str(sc['verdict']) + ' ' + sc['band_id']) if sc else '-'} | {p['on_screen']} |")
    for i, p in enumerate(picks, 1):
        sc = scored.get(p["new_first_line"])
        md += ["", f"### Short {i}: {_mmss(p['start'])}–{_mmss(p['end'])}",
               f"- **Kalimat asli:** {p['first_line']}", f"- **Kalimat pembuka baru:** {p['new_first_line']}"
               + (f" (lemah di *{sc['weakest_id']}*: {sc['fix_id']})" if sc and sc["band"] != "STRONG" else ""),
               f"- **Teks layar 2 detik pertama:** {p['on_screen']}", f"- **Titik loop:** {p['loop']}",
               f"- **Bingkai vertikal:** {p['framing']}", f"- **Kenapa berdiri sendiri:** {p['why']}"]
    md.append("\nTombol *Render dengan Clip Agent* memotong momen-momen ini dengan pengaturan Studio Anda; teks layar "
              "dipakai sebagai judul pembuka di klip.\n\n**Kirim, atau ubah?**")
    plan = [{"start": p["start"], "end": p["end"], "title": p["on_screen"] or p["new_first_line"][:60],
             "hook": p["new_first_line"], "reason": p["why"], "score": 80} for p in picks]
    source = src.get("url") or ""          # URL YouTube atau path file asli: dipakai ulang oleh Studio (cache yang sama)
    actions = [{"type": "render_shorts", "label": "Render dengan Clip Agent", "source": source, "plan": plan}] if source else []
    return _save(out_dir, "shorts", src["title"], "\n".join(md), {"shorts": picks}, actions)


# ---------------------------------------------------------------- 7. retensi
def run_retention(out_dir: Path, inp: dict) -> dict:
    raw = str(_unstash(out_dir, inp.get("csv")) or "")
    if raw.startswith("data:"):
        raw = base64.b64decode(raw.split(",", 1)[1]).decode("utf-8-sig", "replace")
    if raw.count("\n") < 8:
        raise ClipAgentError("Unggah file CSV retensi dari YouTube Studio (Analytics → Engagement → grafik retensi → unduh).")
    src = get_source(out_dir, inp.get("source"), need_timing=True) if _has_source(inp.get("source")) else None
    duration = float(inp.get("duration") or 0) or (src["duration"] if src else 0)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "retention.csv"
        p.write_text(raw, encoding="utf-8")
        res = T.retention_report(p, src["cues"] if src else None, duration or None)
        rt = T._load("yt_retention", "yt-retention/retention.py")
        points = rt.load_csv(str(p))
    if res.get("error"):
        raise ClipAgentError(f"retention.py: {res['error']}")
    verdict = "sehat" if res["hook_leak"] < 25 else "bocor" if res["hook_leak"] < 40 else "parah"
    try:
        c = _client(out_dir)
        progress(0.5, "Membaca kebocoran terbesar")
        md = c.complete_text(_system("retention", inp.get("lang") or "id"),
                             f"Video: {(src or {}).get('title') or inp.get('title') or '-'}; duration {duration or 'unknown'} s.\n"
                             f"retention.py output:\n{json.dumps(res, ensure_ascii=False, indent=1)}\n\nName the single biggest leak "
                             "and ONE change for it. Then a short table of the cliffs (time, % lost, what was said). If the hook "
                             "leak is healthy and the slide is flat, say the video is fine and the problem is packaging (the "
                             "'Judul & thumbnail' tool).")
    except ClipAgentError as exc:
        log(f"Ringkasan AI dilewati ({str(exc).splitlines()[0][:100]}).")
        md = (f"## Retensi\n\n- **Hook leak:** {res['hook_leak']:.1f}% hilang di pembukaan ({verdict}; di bawah 25 sehat)\n"
              f"- **Slide:** {res['slide_per_unit']}% per unit di bagian tengah\n\n| Waktu | Hilang | Yang diucapkan |\n|---|---|---|\n"
              + "\n".join(f"| {c['at_seconds'] if c['at_seconds'] is not None else c['from']} | {c['lost']}% | "
                          f"{res.get('said', {}).get(str(c['from']), '')} |" for c in res["cliffs"]))
    return _save(out_dir, "retention", (src or {}).get("title") or inp.get("title") or "Retensi", md,
                 {**res, "verdict": verdict, "points": points[:400], "duration": duration})


# ---------------------------------------------------------------- 8. riset outlier
def _channel_videos(url: str, n: int) -> list[dict]:
    u = url.strip()
    if u.startswith("@"):
        u = f"https://www.youtube.com/{u}"
    if re.match(r"https?://(www\.)?youtube\.com/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$", u):
        u = u.rstrip("/") + "/videos"
    info = _yt_info(u, {"extract_flat": "in_playlist", "playlistend": n})
    ch = info.get("channel") or info.get("uploader") or info.get("title") or u
    out = []
    for e in info.get("entries") or []:
        if not e or e.get("view_count") is None:
            continue
        out.append({"channel": ch, "title": e.get("title") or "", "views": int(e.get("view_count") or 0),
                    "url": e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}", "duration": e.get("duration") or 0})
    return out


def run_viral(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    chans = [c.strip() for c in re.split(r"[\n,]+", str(inp.get("channels") or "")) if c.strip()][:12]
    kw = str(inp.get("keyword") or "").strip()
    per = max(8, min(60, int(inp.get("per_channel") or 30)))
    lo = max(1.0, min(20.0, float(inp.get("min") or 2.0)))
    if not chans and not kw:
        raise ClipAgentError("Isi URL/handle channel pesaing, atau kata kunci niche.")
    if kw:
        progress(0.05, "Mencari channel dari kata kunci")
        found = _yt_info(f"ytsearch25:{kw}", {"extract_flat": True})
        for e in found.get("entries") or []:
            cu = e.get("channel_url") or (f"https://www.youtube.com/channel/{e['channel_id']}" if e.get("channel_id") else "")
            if cu and cu not in chans:
                chans.append(cu)
            if len(chans) >= 8:
                break
    rows, failed = [], []
    for i, ch in enumerate(chans):
        check_cancel()
        progress(0.1 + 0.6 * i / max(1, len(chans)), f"Mengambil daftar video {i + 1}/{len(chans)}")
        try:
            rows += _channel_videos(ch, per)
        except ClipAgentError as exc:
            failed.append(ch)
            log(f"  {ch}: {str(exc).splitlines()[0][:120]}")
    if not rows:
        raise ClipAgentError("Tidak ada video yang bisa dibaca dari channel tersebut.")
    res = T.swipe_rank(rows, lo)
    outl = res.get("outliers") or []
    md_tbl = ["| Kelipatan | Views | Median channel | Channel | Judul | Rumus judul |", "|---|---|---|---|---|---|"]
    md_tbl += [f"| **{r['multiple']}x** | {r['views']:,} | {r['median']:,} | {r['channel'][:24]} | [{r['title'][:70]}]({r['url']}) | "
               f"{r['formula']} |" for r in outl[:25]]
    thin = res.get("skipped_thin_channels") or []
    try:
        c = _client(out_dir)
        progress(0.8, "Merangkum pola")
        md = c.complete_text(_system("viral", lang),
                             f"Niche keyword: {kw or '-'}\nswipe.py output (outliers at {lo}x or better):\n"
                             f"{json.dumps(outl[:20], ensure_ascii=False, indent=1)}\n\nHand back: the top five with their multiples "
                             "and the formula each used (say the formula is a judgement about the title words, not why it worked), "
                             "the ONE structural thing they share, and which of those the creator could actually make this week, "
                             "in their voice, with what they have (gaming channel).")
    except ClipAgentError as exc:
        md = f"_(Ringkasan AI dilewati: {str(exc).splitlines()[0][:100]})_"
    md = (f"## Outlier: {len(outl)} video ≥ {lo:g}x median channelnya\n\n" + "\n".join(md_tbl) +
          (f"\n\nDilewati (kurang dari 4 video terbaca): {', '.join(str(t[0]) for t in thin)}" if thin else "") +
          (f"\n\nGagal dibaca: {', '.join(failed)}" if failed else "") + "\n\n" + md)
    actions = [{"type": "script_idea", "label": f"Naskah: {r['title'][:40]}", "idea": f"Video seperti \"{r['title']}\" "
                f"({r['multiple']}x median {r['channel']}), dengan versi dan suara saya sendiri"} for r in outl[:3]]
    return _save(out_dir, "viral", kw or ", ".join(chans[:3]), md, {**res, "collected": len(rows)}, actions)


# ---------------------------------------------------------------- 9. komentar
def run_comment(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    url = str(inp.get("url") or "").strip()
    pasted = str(_unstash(out_dir, inp.get("text")) or "").strip()
    title, items = "", []
    if url:
        n = max(10, min(300, int(inp.get("max") or 100)))
        progress(0.1, "Mengambil komentar")
        info = _yt_info(url, {"getcomments": True,
                              "extractor_args": {"youtube": {"max_comments": [str(n), "all", "0", "0"], "comment_sort": ["top"]}}})
        title = info.get("title", "")
        for cm in (info.get("comments") or [])[:n]:
            if cm.get("parent") not in (None, "root"):
                continue
            items.append(f"(👍{cm.get('like_count') or 0}) {cm.get('author') or '?'}: {re.sub(r'\s+', ' ', cm.get('text') or '')[:400]}")
        if not items:
            raise ClipAgentError("Komentar tidak bisa diambil (mungkin dinonaktifkan). Tempel komentarnya secara manual.")
    elif pasted:
        items = [l.strip() for l in pasted.splitlines() if l.strip()][:300]
    else:
        raise ClipAgentError("Isi URL video, atau tempel komentarnya (satu per baris).")
    c = _client(out_dir)
    progress(0.5, f"Memilah {len(items)} komentar")
    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(items, 1))
    md = c.complete_text(_system("comment", lang),
                         f"Video: {title or '-'}\nComments ({len(items)}):\n{numbered}\n\nTriage into the four piles and say how many "
                         "are in each before writing anything. Then write the replies (under 30 words each, in the language of "
                         "the comment, referencing the comment number), say which ONE to pin and why, and list repeated questions "
                         "as next-video topics. Bait gets no reply.")
    return _save(out_dir, "comment", title or f"{len(items)} komentar", md, {"count": len(items)})


# ---------------------------------------------------------------- 10. rencana
def run_plan(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    hours = str(inp.get("hours") or "").strip()
    if not hours:
        raise ClipAgentError("Isi berapa jam yang benar-benar Anda punya per minggu.")
    existing = []
    try:
        from ..studio_api import all_videos
        for v in all_videos(out_dir)[:15]:
            existing.append(f"- {v.get('group')}: {v.get('title') or v.get('label')}")
    except Exception:
        pass
    c = _client(out_dir)
    progress(0.3, "Menyusun rencana")
    md = c.complete_text(_system("plan", lang),
                         f"Hours per week: {hours}\nAlready half-made: {inp.get('half') or '-'}\nBest upload day from their analytics: "
                         f"{inp.get('best_day') or 'not given (do not assume; tell them where to find it)'}\nNiche / notes: "
                         f"{inp.get('notes') or 'gaming (GTA, Resident Evil, etc.)'}\nWeeks to plan: {inp.get('weeks') or 1}\n"
                         f"Finished items already in their Clip Agent library (usable for the cheap one and Shorts):\n"
                         f"{chr(10).join(existing) or '- (empty)'}\n\nWrite the table (day, format, working title, the one sentence it "
                         "promises, what already exists for it), then the honest line: hours it costs and what to drop first.")
    return _save(out_dir, "plan", f"Rencana: {hours} per minggu", md)


# ---------------------------------------------------------------- 11. audit
def run_audit(out_dir: Path, inp: dict) -> dict:
    lang = inp.get("lang") if inp.get("lang") in LANGS else "id"
    ch = str(inp.get("channel") or "").strip()
    if not ch:
        raise ClipAgentError("Isi URL atau @handle channel.")
    progress(0.05, "Mengambil daftar video channel")
    vids = _channel_videos(ch, 12)
    if len(vids) < 3:
        raise ClipAgentError("Channel ini punya terlalu sedikit video yang bisa dibaca.")
    rows = []
    for i, v in enumerate(vids[:10]):
        check_cancel()
        progress(0.1 + 0.6 * i / 10, f"Membaca video {i + 1}/10")
        row = {"title": v["title"], "views": v["views"], "url": v["url"], "duration": v["duration"], "date": "",
               "thumb": "", "hook": "", "hook_score": None}
        try:
            info = _yt_info(v["url"])
            row["date"] = info.get("upload_date") or ""
            row["thumb"] = f"https://i.ytimg.com/vi/{info.get('id')}/mqdefault.jpg"
            if i < 3:                                       # 15 detik pertama dari 3 video terbaru
                from ..download import _pick_caption
                picked = _pick_caption(info, lang)
                if picked:
                    import yt_dlp

                    from ..download import _QuietLogger
                    from ..transcript import words_from_json3
                    with yt_dlp.YoutubeDL({"quiet": True, "logger": _QuietLogger()}) as ydl:
                        ws = words_from_json3(json.loads(ydl.urlopen(picked[0]).read().decode("utf-8")))
                    row["hook"] = " ".join(w.text for w in ws if w.start < 15)
        except Exception as exc:                                    # noqa: BLE001
            log(f"  {v['title'][:40]}: {str(exc).splitlines()[0][:100] if str(exc) else type(exc).__name__}")
        rows.append(row)
    lint = {r["title"]: r for r in lint_titles_id([(r["title"], None) for r in rows])}
    hooks = {r["hook"]: r for r in score_hooks_id([r["hook"] for r in rows if r["hook"]])}
    for r in rows:
        r["title_score"] = lint.get(r["title"], {}).get("score")
        r["title_issues"] = [i["label"] for i in lint.get(r["title"], {}).get("issues_id", [])]
        if r["hook"] in hooks:
            r["hook_score"] = hooks[r["hook"]]["verdict"]
    dates = sorted(r["date"] for r in rows if r["date"])
    gaps = []
    for a, b in zip(dates, dates[1:]):
        try:
            gaps.append((time.mktime(time.strptime(b, "%Y%m%d")) - time.mktime(time.strptime(a, "%Y%m%d"))) / 86400)
        except ValueError:
            pass
    rhythm = {"median_days": round(statistics.median(gaps), 1) if gaps else None, "max_days": round(max(gaps), 1) if gaps else None,
              "min_days": round(min(gaps), 1) if gaps else None}
    c = _client(out_dir)
    progress(0.8, "Mencari satu perbaikan terpenting")
    md = c.complete_text(_system("audit", lang),
                         f"Channel: {ch} ({vids[0]['channel']})\nLast ten videos, newest first (title.py score and issues, hookscore "
                         f"of the first 15 seconds for the three most recent, upload date, views):\n"
                         f"{json.dumps([{k: r[k] for k in ('title', 'views', 'date', 'title_score', 'title_issues', 'hook', 'hook_score')} for r in rows], ensure_ascii=False, indent=1)}\n"
                         f"Upload rhythm (days between uploads): {json.dumps(rhythm)}\nThumbnails: shown to the creator in the app at "
                         "feed size; you cannot see them, so ask the creator to check them at that size rather than judging.\n\n"
                         "Hand back the single biggest fix with what to do this week, three specific things already working, and "
                         "what NOT to do yet.")
    return _save(out_dir, "audit", vids[0]["channel"], md, {"rows": rows, "rhythm": rhythm})


# ---------------------------------------------------------------- profil suara dari video
def run_voice(out_dir: Path, inp: dict) -> dict:
    urls = [u.strip() for u in re.split(r"[\n,\s]+", str(inp.get("urls") or "")) if u.strip().startswith("http")][:3]
    if not urls:
        raise ClipAgentError("Isi 1–3 URL video Anda sendiri.")
    import os

    from ..download import fetch_source_text
    texts = []
    for i, u in enumerate(urls):
        check_cancel()
        progress(0.1 + 0.5 * i / len(urls), f"Membaca video {i + 1}/{len(urls)}")
        key = re.sub(r"\W+", "_", u)[-40:]
        d = fetch_source_text(u, _hist(out_dir) / f"voice_{key}", "id", os.getenv("COOKIES_FROM_BROWSER", ""))
        texts.append(f"### {d.get('title', '')}\n{(d.get('text') or '')[:9000]}")
    c = _client(out_dir)
    progress(0.7, "Menulis profil suara")
    md = c.complete_text("You infer a YouTube creator's on-camera voice from their own transcripts and fill in their voice "
                         "profile. Quote their real phrases. Never invent facts about them.",
                         f"Template (keep these headings, write in Bahasa Indonesia):\n{VOICE_TEMPLATE_ID}\n\nTheir videos:\n"
                         + "\n\n".join(texts) + "\n\nReturn ONLY the filled-in Markdown file.")
    md = re.sub(r"^```(markdown|md)?\s*|```\s*$", "", md.strip())
    voice_save(md)
    return _save(out_dir, "voice", "Profil suara", md + "\n\n> Tersimpan sebagai profil suara. Periksa dan ubah bila ada yang keliru.")


RUNNERS = {"script": run_script, "package": run_package, "seo": run_seo, "chapters": run_chapters, "shorts": run_shorts,
           "edit": run_edit, "retention": run_retention, "viral": run_viral, "comment": run_comment, "plan": run_plan,
           "audit": run_audit, "voice": run_voice}


def run(out_dir: Path, tool: str, inp: dict) -> dict:
    if tool not in RUNNERS:
        raise ClipAgentError("Alat tidak dikenal.")
    log(f"Kanal: {TOOLS.get(tool, ('', 'Profil suara'))[1]}")
    res = RUNNERS[tool](out_dir, inp or {})
    progress(1.0, "Selesai")
    return res


def meta() -> dict:
    return {"tools": {k: {"skill": v[0], "label": v[1], "desc": v[2]} for k, v in TOOLS.items()}, "langs": LANGS,
            "needs_ai": sorted(NEEDS_AI),
            "voice": voice_get()["exists"], "formulas": [{"name": f["name"], "shape": f["shape"], "example": f["example"]}
                                                         for f in T.formulas()]}
