"""Enam alat Python dari youtube-agent-skill, dimuat dari folder vendor/ dan diberi kosakata bahasa Indonesia.

File vendor tidak diubah. Modulnya dimuat sekali, lalu daftar kata dan pola regex-nya diperluas di sini
(gabungan Inggris + Indonesia), karena alat aslinya hanya mengenali kata bahasa Inggris: hook "Kamu masih
salah..." akan dinilai lemah hanya karena tidak ada kata "you".

Alat yang mencetak hasilnya (deadair, chapters, retention, swipe) dipanggil lewat fungsi main() masing-masing
dengan --json dan keluarannya ditangkap, persis seperti dijalankan dari terminal.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import threading
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor"
SKILLS = VENDOR / "skills"
_LOCK = threading.Lock()
_MODS: dict = {}

# ---------------------------------------------------------------- kosakata Indonesia
ID_YOU = r"kamu|kau|lo|lu|loe|elo|anda|kalian|gaes|guys"
# akhiran -mu = "your" (uangmu, akunmu, waktumu); kata dasar yang kebetulan berakhiran -mu dikecualikan
ID_MU = r"(?!(?:il|te|berte|kete|ja|ra|ta|pemu|semu|ke|ba|ma|me|ha|ru|lu|ku|ja|seja|cu|ka|na)mu\b)[a-z]{3,}mu"
ID_STAKE = (r"rugi|gagal|buang|terbuang|sia-sia|berhenti|bangkrut|mati|kalah|hilang|jangan|sebelum|terlambat|"
            r"biaya|mahal|bahaya|nyesel|menyesal|ketipu|tertipu|banned|kena\s+ban")
ID_CURIOSITY = (r"kenapa|mengapa|bagaimana|gimana|apa|siapa|mana|sampai|sebelum|tapi|tetapi|padahal|ternyata|"
                r"alasan|rahasia|tidak\s+ada\s+yang|gak\s+ada\s+yang|nggak\s+ada\s+yang|hampir|kecuali|cuma")
ID_FILLER = {"jadi", "nah", "oke", "halo", "hai", "selamat", "datang", "sebenarnya", "sebetulnya", "banget", "gitu",
             "kayak", "pokoknya", "intinya", "langsung", "aja", "saja"}
ID_VAGUE = {"luar", "biasa", "gila", "keren", "parah", "terbaik", "rahasia", "ampuh", "dahsyat", "epik", "mantap",
            "sempurna", "lengkap", "semuanya", "terhebat", "terkeren"}
ID_STOP = set("""yang dan di ke dari ini itu untuk dengan pada adalah akan juga tidak ada atau karena jadi saat sudah
bisa lebih kita kami saya aku gue gua kamu lo mereka dia ia oleh dalam sebuah seperti hanya agar namun tapi tetapi cara
gimana kenapa apa begini begitu ya nih sih dong kok deh aja saja banget""".split())
ID_FILLER_CUE = r"eh+|em+|emm+|hmm+|anu|apa\s+ya|gimana\s+ya|jadi|nah|oke|ya+|gitu|kayak|terus|pokoknya|intinya|sebenarnya"
# pola rumus hook versi Indonesia (ditambahkan ke pola bahasa Inggris tiap rumus)
ID_FORMULA = {
    "the-statistic": [r"\b\d+\s?persen\b", r"\b\d+ dari \d+\b"],
    "someone-elses-result": [r"\b(channel|orang|kreator|akun) ini\b", r"\bdari .* (jadi|menjadi|sampai)\b",
                             r"\bdalam (satu|dua|tiga|\d+) (minggu|bulan|tahun)\b"],
    "the-mistake": [r"\b(kamu|lo|anda) (pasti |masih )?(salah|melakukan)\b", r"\bkesalahan\b", r"\bberhenti\b"],
    "contrarian-flip": [r"\bsemua orang (bilang|bilangin|mikir)\b", r"\b(itu )?salah besar\b",
                        r"\b(gak|nggak|tidak) ada yang (bilang|ngomongin|kasih tahu)\b"],
    "the-reveal": [r"\b(aku|gue|saya) (mau|akan) (tunjukin|tunjukkan|kasih lihat)\b", r"\b(ini|inilah) (dia|caranya)\b"],
    "the-superlative": [r"\b(paling|ter)(cepat|mudah|gampang|susah|sulit|buruk|bagus|seram|ngeri|kuat|langka)\w*\b",
                        r"\bsatu-satunya\b", r"\bnomor satu\b"],
    "the-clock": [r"\bdalam \d+ (detik|menit|jam)\b", r"\b(di )?akhir video( ini)?\b", r"\bkurang dari \d+\b"],
    "i-tried-it": [r"\b(aku|gue|saya) (coba|nyoba|mencoba|habiskan|ngabisin|tes|main)\b", r"\bselama \d+ (hari|minggu|bulan|jam)\b",
                   r"\bbiar (kamu|lo) (gak|nggak|tidak) perlu\b"],
    "the-question": [r"^(kenapa|mengapa|bagaimana|gimana|apa|kapan|apakah|bisakah|haruskah)\b"],
    "the-before-after": [r"\bsebelum\b.*\bsesudah\b", r"\bdulu\b.*\bsekarang\b"],
    "the-teardown": [r"\b(bedah|membedah|ngebedah|kupas|mengupas|analisis|breakdown)\b"],
    "the-stack": [r"\bdigabung\b", r"\bgabungan\b", r"\bbareng\b"],
    "the-warning": [r"\bjangan\b", r"\bsebelum (kamu|lo|anda)\b", r"\bawas\b", r"\bhati-hati\b"],
    "the-list": [r"^\d+ \w+", r"\b(ini dia|berikut) \d+\b"],
    "the-receipt": [r"\bini (bukti|hasil)nya\b", r"\bbukti\b", r"\btangkapan layar\b"],
    "the-insider": [r"\b(gak|nggak|tidak|jarang) (ada yang|banyak yang) (tahu|tau|sadar)\b", r"\btersembunyi\b",
                    r"\b(easter egg|rahasia)\b"],
    "the-impossible": [r"\btanpa\b", r"\b(tidak|gak|nggak) pernah\b", r"\bsekali (jalan|coba)\b", r"\bnol\b"],
    "the-comparison": [r"\blawan\b", r"\bmana yang (lebih|menang)\b"],
    "the-origin": [r"\bsemua(nya)? (berawal|dimulai) dari\b", r"\balasan (sebenarnya|aslinya)\b"],
    "the-deadline": [r"\b(minggu|bulan|tahun) (ini|depan)\b", r"\b(akan )?berubah\b", r"\b(tidak|gak) lagi\b"],
    "the-direct-address": [r"^(kalau|kalo|jika) (kamu|lo|anda)\b", r"\buntuk (kamu|lo|kalian|anda) yang\b"],
}


def _load(name: str, rel: str):
    if name in _MODS:
        return _MODS[name]
    spec = importlib.util.spec_from_file_location(name, SKILLS / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                       # chapters/retention memanggil `from deadair import ...`
    spec.loader.exec_module(mod)
    _MODS[name] = mod
    return mod


def _extend_formulas(formulas: list) -> None:
    for f in formulas:
        extra = ID_FORMULA.get(f.get("id"), [])
        f["match"] = list(dict.fromkeys(list(f.get("match", [])) + extra))


def hookscore():
    hs = _load("hookscore", "yt-script/hookscore.py")
    if not getattr(hs, "_clipagent_id", False):
        hs.FILLER |= ID_FILLER
        hs.VAGUE |= ID_VAGUE
        hs.YOU = re.compile(rf"\b(you|your|you're|youre|yourself|{ID_YOU}|{ID_MU})\b", re.I)
        hs.STAKE = re.compile(rf"\b(lose|lost|wasting|waste|quit|fail|broke|cost|risk|before|stop|never|die|dying|dead|"
                              rf"{ID_STAKE})\b", re.I)
        hs.CURIOSITY = re.compile(rf"\b(why|how|what|which|until|before|but|nobody|almost|except|reason|actually|"
                                  rf"{ID_CURIOSITY})\b", re.I)
        hs.CONCRETE = re.compile(r"\b(\d[\d,.]*\s?(%|k|m|x|s|m|h|rb|jt|juta|ribu)?|\$\d|rp\s?\d[\d.,]*|"
                                 r"\d+\s?(second|minute|hour|day|week|month|year|detik|menit|jam|hari|minggu|bulan|tahun)s?)\b",
                                 re.I)
        _extend_formulas(hs.FORMULAS)
        orig_curiosity = hs.curiosity

        def curiosity(t):                       # kalimat yang menjawab dirinya sendiri: "karena", "sehingga"
            v = orig_curiosity(t)
            return max(0, v - 18) if re.search(r"\b(karena|sehingga|makanya|yang berarti)\b", t, re.I) else v
        hs.curiosity = curiosity
        hs.PROPS = [("SPECIFICITY", hs.specificity), ("ADDRESS", hs.address), ("STAKES", hs.stakes),
                    ("CURIOSITY", curiosity), ("BREVITY", hs.brevity)]
        hs._clipagent_id = True
    return hs


def title_mod():
    tm = _load("yt_title", "yt-package/title.py")
    if not getattr(tm, "_clipagent_id", False):
        tm.VAGUE |= ID_VAGUE
        tm.STOP |= ID_STOP
        tm._clipagent_id = True
    return tm


def deadair_mod():
    da = _load("deadair", "yt-edit/deadair.py")
    if not getattr(da, "_clipagent_id", False):
        da.FILLER_ONLY = re.compile(r"^[\s,.-]*((um+|uh+|er+|ah+|so|okay|ok|right|yeah|like|anyway|basically|"
                                    r"actually|you know|i mean|let me see|hold on|" + ID_FILLER_CUE + r")[\s,.-]*)+$", re.I)
        da._clipagent_id = True
    return da


def _run_main(mod, argv: list[str]) -> dict:
    """Jalankan main() alat seperti dari terminal (dengan --json) dan kembalikan hasil JSON-nya."""
    with _LOCK:
        old = sys.argv
        buf = io.StringIO()
        try:
            sys.argv = [mod.__name__] + argv + ["--json"]
            with contextlib.redirect_stdout(buf):
                try:
                    mod.main()
                except SystemExit:
                    pass
        finally:
            sys.argv = old
    out = buf.getvalue().strip()
    try:
        return json.loads(out)
    except ValueError:
        return {"error": out.splitlines()[0] if out else "alat tidak mengeluarkan hasil"}


# ---------------------------------------------------------------- API yang dipakai Clip Agent
def score_hooks(hooks: list[str]) -> list[dict]:
    hs = hookscore()
    out = []
    for h in hooks:
        h = (h or "").strip()
        if not h:
            continue
        parts, verdict, name, hits = hs.score(h)
        low = min(parts, key=parts.get)
        out.append({"hook": h, "properties": parts, "verdict": verdict, "band": hs.band(verdict), "formula": name,
                    "matched": hits, "weakest": low, "fix": hs.FIX[low]})
    return sorted(out, key=lambda r: -r["verdict"])


def lint_titles(pairs: list[tuple[str, str | None]]) -> list[dict]:
    tm = title_mod()
    rows = [tm.check(t, th or None) for t, th in pairs if (t or "").strip()]
    for r in rows:
        r["issues"] = [list(i) for i in r["issues"]]
    return sorted(rows, key=lambda r: -r["score"])


def formulas() -> list[dict]:
    return hookscore().FORMULAS


def formula_rules() -> dict:
    data = json.loads((SKILLS / "yt-script" / "hooks.json").read_text(encoding="utf-8"))
    return {"note": data.get("note", ""), "rules": data.get("rules", [])}


def _srt_time(t: float) -> str:
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def cues_to_srt(cues: list[tuple[float, float, str]], path: Path) -> Path:
    lines = []
    for i, (a, b, t) in enumerate(cues, 1):
        lines += [str(i), f"{_srt_time(a)} --> {_srt_time(b)}", t.strip() or "-", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _with_srt(cues, fn):
    with tempfile.TemporaryDirectory() as d:
        return fn(cues_to_srt(cues, Path(d) / "transcript.srt"))


def edit_list(cues: list, floor: float = 0.45) -> dict:
    da = deadair_mod()
    return _with_srt(cues, lambda p: _run_main(da, [str(p), "--floor", str(floor)]))


def chapter_list(cues: list, target: int = 7) -> dict:
    deadair_mod()
    ch = _load("yt_chapters", "yt-chapters/chapters.py")
    if not getattr(ch, "_clipagent_id", False):
        ch.STOP |= ID_STOP
        ch._clipagent_id = True
    return _with_srt(cues, lambda p: _run_main(ch, [str(p), "--target", str(int(target))]))


def retention_report(csv_path: Path, cues: list | None = None, duration: float | None = None) -> dict:
    deadair_mod()
    rt = _load("yt_retention", "yt-retention/retention.py")
    args = [str(csv_path)]
    if duration:
        args += ["--duration", f"{float(duration):.2f}"]
    if cues:
        return _with_srt(cues, lambda p: _run_main(rt, args + ["--transcript", str(p)]))
    return _run_main(rt, args)


def swipe_rank(videos: list[dict], minimum: float = 1.5) -> dict:
    hookscore()                                   # pastikan pola rumus versi Indonesia sudah terpasang
    sw = _load("yt_swipe", "yt-viral/swipe.py")
    if not getattr(sw, "_clipagent_id", False):
        _extend_formulas(sw.FORMULAS)
        sw._clipagent_id = True
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "collected.json"
        p.write_text(json.dumps(videos, ensure_ascii=False), encoding="utf-8")
        return _run_main(sw, [str(p), "--min", str(minimum)])


def skill_text(name: str) -> str:
    """Isi SKILL.md tanpa frontmatter dan tanpa blok perintah terminal (alatnya dijalankan oleh Clip Agent)."""
    txt = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    txt = re.sub(r"\A---.*?---\s*", "", txt, flags=re.S)
    return re.sub(r"```bash.*?```", "[Alat ini sudah dijalankan oleh Clip Agent; hasilnya ada di pesan pengguna.]",
                  txt, flags=re.S).strip()


def voice_template() -> str:
    return (VENDOR / "templates" / "voice.md").read_text(encoding="utf-8")
