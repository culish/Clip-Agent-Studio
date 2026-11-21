"""Motion AI: video motion graphics yang kodenya ditulis AI, seperti hasil Claude saat diminta membuat video animasi
dengan HTML/GSAP (HyperFrames) atau Remotion, tetapi langsung jadi MP4 di Clip Agent.

Alurnya: naskah per adegan (tab Buat video) → narasi TTS dengan waktu per kata → AI menulis HTML + CSS + timeline
animasi tiap adegan, disinkronkan dengan kata yang diucapkan → Clip Agent mengujinya di browser render, memperbaiki
adegan yang galat, lalu merender semuanya dengan Remotion bersama suara, musik, transisi, dan caption.

Penulis kode bisa Claude lewat Claude Code (kuota langganan Claude Anda, tanpa API key) atau AI yang diatur di
Pengaturan (Gemini gratis, OpenRouter, Claude API, dll.). Animasi dijalankan MotionKit (remotion/src/motionkit.js),
mesin timeline bergaya GSAP yang ditulis sendiri untuk Clip Agent.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .config import PROJECT_DIR
from .utils import ClipAgentError, extract_json, log

STYLES = {
    "clean": {"name": "Bersih minimal", "bg": "#F7F5F0", "surface": "#FFFFFF", "ink": "#121212", "muted": "#5E5A55",
              "accent": "#2F6BFF", "accent2": "#FF5A36", "head": "Archivo Black", "body": "Plus Jakarta Sans", "radius": 28},
    "dark_tech": {"name": "Teknologi gelap", "bg": "#0B0F1A", "surface": "#141B2D", "ink": "#E8EEFF", "muted": "#8A96B8",
                  "accent": "#4CC9F0", "accent2": "#B5179E", "head": "Montserrat Black", "body": "Plus Jakarta Sans", "radius": 24},
    "bold_pop": {"name": "Pop berani", "bg": "#FFE14D", "surface": "#FFFFFF", "ink": "#111111", "muted": "#4A4430",
                 "accent": "#FF3B30", "accent2": "#2D5BFF", "head": "Anton", "body": "Poppins", "radius": 20},
    "editorial": {"name": "Editorial koran", "bg": "#F1EADB", "surface": "#FBF6EC", "ink": "#1D1A16", "muted": "#6B6253",
                  "accent": "#C8321E", "accent2": "#1F4E79", "head": "Playfair Display Black", "body": "Plus Jakarta Sans",
                  "radius": 6},
    "pastel": {"name": "Pastel lembut", "bg": "#FDF1EC", "surface": "#FFFFFF", "ink": "#3A2E39", "muted": "#8A7684",
               "accent": "#FF6F91", "accent2": "#4DB6AC", "head": "Fraunces Black", "body": "Plus Jakarta Sans", "radius": 36},
    "neon": {"name": "Neon malam", "bg": "#090014", "surface": "#170A2B", "ink": "#F8F0FF", "muted": "#A899C2",
             "accent": "#39FF14", "accent2": "#FF2BD6", "head": "Bebas Neue", "body": "Plus Jakarta Sans", "radius": 18},
    "corporate": {"name": "Profesional", "bg": "#FFFFFF", "surface": "#F2F5FA", "ink": "#0F1B2D", "muted": "#5B6B82",
                  "accent": "#0057FF", "accent2": "#00B894", "head": "Montserrat Black", "body": "Plus Jakarta Sans", "radius": 20},
    "sketch": {"name": "Coretan tangan", "bg": "#FFFDF7", "surface": "#FFFFFF", "ink": "#1A1A1A", "muted": "#6B6B6B",
               "accent": "#E4572E", "accent2": "#2E86DE", "head": "Permanent Marker", "body": "Patrick Hand", "radius": 14},
}
ENGINES = {"auto": "Otomatis (Claude Code bila ada, selain itu AI di Pengaturan)", "claude": "Claude (lewat Claude Code)",
           "llm": "AI di Pengaturan (Gemini, OpenRouter, Claude API, dll.)"}
FONTS = ["Anton", "Bangers", "Bebas Neue", "Montserrat Black", "Patrick Hand", "Poppins", "Playfair Display Black",
         "Playfair Italic", "Special Elite", "Permanent Marker", "Fraunces Black", "Fraunces Italic", "Caveat Bold",
         "Archivo Black", "Plus Jakarta Sans"]
KIT = PROJECT_DIR / "remotion" / "src" / "motionkit.js"
CSP = ("default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; font-src data:; media-src data:; "
       "img-src data:")         # halaman ekspor tidak boleh menghubungi apa pun
VERSION = "m2"          # ubah bila aturan/prompt berubah agar cache kode lama tidak dipakai


def design(style_id: str) -> dict:
    d = dict(STYLES.get(style_id) or STYLES["clean"])
    d.pop("name", None)
    return d


def public() -> dict:
    return {"styles": {k: {"name": v["name"], "bg": v["bg"], "accent": v["accent"], "accent2": v["accent2"], "ink": v["ink"]}
                       for k, v in STYLES.items()}, "engines": ENGINES}


# ---------------------------------------------------------------- prompt
SYSTEM = """You are a senior motion designer who builds short explainer and social videos entirely in code, the way
Claude builds HTML + GSAP motion graphics (HyperFrames) or Remotion videos. For every scene you write HTML, CSS and an
animation timeline script. Answer with JSON only.

CANVAS: {W}x{H} px at 30 fps. Each scene renders alone inside a container that already fills the canvas
(position:absolute; inset:0; background:var(--bg); color:var(--ink)). The app adds scene transitions, the narration
audio, background music{captions_note}.

DESIGN SYSTEM ("{style_name}"). Use these CSS variables; do not invent other colors except tints/transparency of them:
--bg {bg}, --surface {surface}, --ink {ink}, --muted {muted}, --accent {accent}, --accent2 {accent2},
--font-head ("{head}"), --font-body ("{body}"), --radius, --u (1% of the shorter canvas side: size everything with
calc(var(--u)*N)). Ready-made classes: .center (full-canvas flex column, centered) .stack .row .title .subtitle .kicker
.big (giant number) .card .pill .accent .accent2 .muted .hl (marker highlight). Fonts: only these families exist:
{fonts}. No web fonts, no <img>, no emoji, no external URLs. Draw icons, illustrations, charts, maps and diagrams yourself
with inline SVG or CSS shapes.

SCRIPT: a JavaScript function body run as function(tl, $, S, gsap, root). Animate ONLY through `tl`, a GSAP-compatible
timeline: tl.from / tl.to / tl.fromTo / tl.set(targets, vars, position), chainable. Targets: CSS selectors (scoped to
this scene automatically) or elements. Supported vars: duration, delay, ease ("power1".."power4" + ".in/.out/.inOut",
"back.out(1.7)", "elastic.out(1,0.4)", "expo.out", "circ.out", "sine.inOut", "bounce.out", "steps(5)", "none"),
stagger (number or {{each, from:"start"|"center"|"end"|"edges"|"random"}}), repeat (number, or -1 to loop until the
scene ends), yoyo, repeatDelay, transformOrigin, x, y, xPercent, yPercent, scale, scaleX, scaleY, rotation, skewX,
opacity, autoAlpha, color, backgroundColor, borderColor, width, height, borderRadius, letterSpacing, filter
("blur(8px)"), clipPath ("inset(0 100% 0 0)" -> "inset(0 0% 0 0)", same number of values), CSS variables ("--p"),
attr:{{...}} for SVG attributes, drawSVG ("0%" -> "100%") to draw strokes, and onUpdate(){{...}} on a plain object
target for counters, e.g. const n={{v:0}}; tl.to(n,{{v:73,duration:1.2,onUpdate(){{ $('.num')[0].textContent=Math.round(n.v)+'%' }}}},0.4).
Positions: seconds from scene start, "<", ">", "<0.2", "+=0.3", "-=0.2".
Helpers: S.w, S.h, S.dur (scene length in seconds), S.words (narration words [{{t,s,e}}] in seconds from scene start),
S.at("word", fallback) = the second the narrator says that word, S.splitWords(selector) / S.splitChars(selector) wrap
text into .w / .ch spans (kinetic typography) and return them, S.rand(i) = deterministic random 0..1, $(selector) =
array of elements in this scene, root = the scene element.
FORBIDDEN: setTimeout, setInterval, requestAnimationFrame, Math.random, Date, fetch, async code, CSS @keyframes /
animation / transition, selecting outside the scene (document.querySelector), :root or body selectors, and visible
text that is not in the narration language.

DIRECTION (this is what makes it look like a finished, professional motion video):
- One strong idea per scene, built around a big headline, keyword or number plus a supporting visual (icon, chart,
  diagram, comparison, timeline, checklist, map-like diagram, quote). Vary the layout from scene to scene.
- Everything moves: elements enter between 0.1 s and 1.2 s with staggered, eased entrances (vary them: rise, scale
  pop, mask wipe, draw, slide, letter cascade); afterwards keep subtle secondary motion (float, pulse, drawing lines,
  counters, slow drift) until the end. No exit animations: the app handles transitions.
- Sync with the voice: reveal each key word/number with S.at("...") when the narrator says it. Nothing important
  appears after S.dur - 0.6.
- On-screen text: short phrases (max ~8 words per block) in {lang}, taken from the narration; big and readable
  (never smaller than calc(var(--u)*4.2)); highlight the key word with an accent color or .hl.
- Safe area: keep content inside 6% side margins{safe_note}.
- Layout: build the composition in normal flow (.center / .stack / .row, flex and grid) so blocks never overlap;
  absolute positioning only for decorative shapes and backgrounds, never for text. Text must fit inside the canvas
  at its final size: headings of more than ~14 characters per line need a smaller size or fewer words.
- Fill the frame: use the whole safe area (not only the top half); one clear focal point, generous but balanced space.
- Compact markup: at most ~40 elements per scene. Give elements clear class names and style them in css.
- Clip Agent renders every scene and checks it (errors, empty frames, overlapping or cut-off text); scenes that fail
  are sent back to you to fix, so write code that works the first time.

OUTPUT: {{"scenes":[{{"id":"s1","html":"...","css":"...","js":"..."}}]}} with one entry per requested scene, same ids.
html: markup only (no <script>, no <style>). css: rules for this scene only (they are scoped automatically; select
your own classes; plain declarations at the top level style the scene container). js: the timeline code."""


SHORT_SYSTEM = ("You are a senior motion designer who writes motion graphics code. Follow the rules in the message "
                "exactly and answer with one JSON object only, without commentary")


def system_prompt(style_id: str, W: int, H: int, lang: str, captions: bool) -> str:
    d = STYLES.get(style_id) or STYLES["clean"]
    return SYSTEM.format(
        W=W, H=H, style_name=d["name"], bg=d["bg"], surface=d["surface"], ink=d["ink"], muted=d["muted"], accent=d["accent"],
        accent2=d["accent2"], head=d["head"], body=d["body"], fonts=", ".join(f'"{f}"' for f in FONTS),
        lang="Bahasa Indonesia" if lang == "id" else "English",
        captions_note=" and word-by-word captions at the bottom" if captions else "",
        safe_note=" and leave the bottom 24% of the canvas empty (captions go there)" if captions else
        " and keep text out of the bottom 8%")


def _scene_brief(sc: dict) -> str:
    words = " ".join(f"{w['t']}@{w['s']:.1f}" for w in sc.get("words", [])[:80])
    return (f"- id: {sc['sid']} | duration: {sc['dur']:.1f} s\n  narration: {sc['narration']}\n"
            f"  suggested on-screen headline: {sc.get('heading') or '-'}\n"
            f"  visual direction: {sc.get('prompt') or '-'}\n  word timings (word@second): {words or '-'}")


def user_prompt(title: str, topic: str, scenes: list[dict], total: int, note: str = "") -> str:
    return (f"Video: \"{title or topic}\". Topic: {topic or title}. {total} scenes in total; write the scenes listed "
            f"below and keep one consistent visual language across them.{(' ' + note) if note else ''}\n\n"
            + "\n".join(_scene_brief(s) for s in scenes))


# ---------------------------------------------------------------- mesin penulis kode
def _claude_available() -> bool:
    try:
        from . import film
        return bool(film.claude_bin())
    except Exception:                                   # noqa: BLE001
        return False


def engine_name(engine: str) -> str:
    if engine == "claude" or (engine in ("", "auto") and _claude_available()):
        return "claude"
    return "llm"


def _ask_claude(system: str, prompt: str) -> dict:
    from . import film
    exe = film.claude_bin()
    if not exe:
        raise ClipAgentError("Claude Code (perintah `claude`) tidak ditemukan. Pasang dan login, atau pilih AI di Pengaturan.")
    st = film.get_settings()
    # Aturan lengkap dikirim lewat stdin: argumen baris perintah berisi < > & " rusak bila lewat cmd.exe di Windows.
    cmd = film._launch(exe) + ["-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
                               "--system-prompt", SHORT_SYSTEM]
    if st.get("model"):
        cmd += ["--model", st["model"]]
    def run(c: list):
        return subprocess.run(c, input=f"{system}\n\n=== TASK ===\n{prompt}", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=900, cwd=tempfile.gettempdir())
    try:
        r = run(cmd)
        if r.returncode != 0 and "unknown option" in (r.stderr or "").lower() and "--no-session-persistence" in r.stderr:
            r = run([x for x in cmd if x != "--no-session-persistence"])        # Claude Code versi lama
    except subprocess.TimeoutExpired as exc:
        raise ClipAgentError("Claude Code tidak menjawab dalam 15 menit.") from exc
    except OSError as exc:
        raise ClipAgentError(f"Claude Code tidak bisa dijalankan: {exc}") from exc
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except ValueError:
        res = {}
    if r.returncode != 0 or res.get("is_error") or not res.get("result"):
        msg = res.get("result") or (r.stderr or r.stdout or "").strip()[-400:]
        if "login" in msg.lower() or "auth" in msg.lower():
            msg += " (jalankan `claude` sekali di terminal untuk login)"
        raise ClipAgentError(f"Claude Code gagal: {msg}")
    return _as_scenes(extract_json(res["result"]))


def _ask_llm(system: str, prompt: str, client) -> dict:
    return _as_scenes(client.complete_json(system, prompt, list_key="scenes"))


def _as_scenes(data) -> dict:
    if isinstance(data, list):
        data = {"scenes": data}
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        raise ClipAgentError("Jawaban AI bukan daftar adegan.")
    out = {}
    for s in data["scenes"]:
        if isinstance(s, dict) and s.get("id"):
            out[str(s["id"])] = clean_code(s)
    return out


def clean_code(s: dict) -> dict:
    html = str(s.get("html") or "")
    html = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html, flags=re.I)
    html = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", html, flags=re.I)        # onload= dll.
    css = re.sub(r"@import[^;]+;|url\(\s*['\"]?https?:[^)]*\)", "", str(s.get("css") or ""), flags=re.I)
    js = str(s.get("js") or "")
    js = re.sub(r"^\s*```\w*|```\s*$", "", js.strip())
    return {"html": html[:30000], "css": css[:20000], "js": js[:20000]}


def static_problems(code: dict) -> list[str]:
    """Pemeriksaan cepat sebelum render: hal yang pasti merusak hasil."""
    p = []
    js = code["js"]
    for bad, why in ((r"\bsetTimeout|setInterval|requestAnimationFrame", "memakai timer; semua gerak harus lewat tl"),
                     (r"\bMath\.random\b", "memakai Math.random; pakai S.rand(i)"),
                     (r"\bfetch\s*\(|XMLHttpRequest|import\s*\(", "mengambil data dari luar"),
                     (r"\bnew\s+Date|Date\.now", "memakai waktu nyata")):
        if re.search(bad, js):
            p.append(why)
    if re.search(r"@keyframes|animation\s*:|transition\s*:", code["css"]):
        p.append("memakai animasi/transition CSS; semua gerak harus lewat tl")
    if not code["html"].strip():
        p.append("html kosong")
    if "tl." not in js and "gsap." not in js:
        p.append("tidak ada animasi di tl")
    return p


# ---------------------------------------------------------------- cadangan bila AI gagal
def fallback_code(sc: dict) -> dict:
    """Adegan kinetik sederhana tanpa AI: judul per kata, garis aksen, bentuk melayang."""
    head = (sc.get("heading") or " ".join(sc.get("narration", "").split()[:6]) or "…").strip()
    words = head.split()
    key = max(words, key=len) if words else head
    safe = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")   # noqa: E731
    html = (f'<div class="blob b1"></div><div class="blob b2"></div><div class="center"><div class="kicker">'
            f'{safe(sc.get("kicker", ""))}</div><h1 class="title t">{safe(head)}</h1><div class="bar"></div></div>')
    css = (".t{max-width:86%} .bar{width:calc(var(--u)*30);height:calc(var(--u)*1.6);background:var(--accent);"
           "border-radius:99px;transform-origin:left} .blob{position:absolute;border-radius:50%;opacity:.16}"
           ".b1{width:calc(var(--u)*60);height:calc(var(--u)*60);background:var(--accent);left:-12%;top:8%}"
           ".b2{width:calc(var(--u)*44);height:calc(var(--u)*44);background:var(--accent2);right:-10%;bottom:14%}")
    js = (f"const w=S.splitWords('.t');\n"
          f"w.forEach(el=>{{ if(el.textContent.replace(/[^\\p{{L}}\\p{{N}}]/gu,'')==={json.dumps(re.sub(r'[^\w]', '', key, flags=re.U))}) el.classList.add('accent'); }});\n"
          "tl.from('.blob',{scale:0,duration:1,ease:'power2.out',stagger:.2},0)\n"
          "  .from(w,{yPercent:120,opacity:0,stagger:.08,duration:.6,ease:'back.out(1.6)'},0.15)\n"
          "  .from('.bar',{scaleX:0,duration:.6,ease:'power3.out'},'>-0.2')\n"
          "  .to('.b1',{x:40,y:30,duration:3,yoyo:true,repeat:-1,ease:'sine.inOut'},1)\n"
          "  .to('.b2',{x:-30,y:-40,duration:3.4,yoyo:true,repeat:-1,ease:'sine.inOut'},1);")
    return {"html": html, "css": css, "js": js, "fallback": True}


# ---------------------------------------------------------------- pembuatan + cache
def cache_key(sc: dict, style_id: str, W: int, H: int, lang: str, captions: bool, engine: str) -> str:
    raw = json.dumps([VERSION, sc.get("narration"), sc.get("heading"), sc.get("prompt"), round(sc["dur"], 1), style_id, W, H, lang,
                      captions, engine, sc.get("rev", 0), [(w["t"], round(w["s"], 1)) for w in sc.get("words", [])]],
                     ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def generate(scenes: list[dict], *, title: str, topic: str, style_id: str, W: int, H: int, lang: str, captions: bool,
             engine: str, adir: Path, client_factory, progress_cb=None) -> dict[str, dict]:
    """Kode animasi untuk adegan-adegan (sid -> {html, css, js}). Memakai cache di folder aset."""
    eng = engine_name(engine)
    system = system_prompt(style_id, W, H, lang, captions)
    out: dict[str, dict] = {}
    todo = []
    for sc in scenes:
        p = adir / f"motion_{cache_key(sc, style_id, W, H, lang, captions, eng)}.json"
        sc["_cache"] = p
        if p.is_file():
            try:
                out[sc["sid"]] = json.loads(p.read_text(encoding="utf-8"))
                continue
            except (OSError, ValueError):
                pass
        todo.append(sc)
    if not todo:
        return out
    client = None if eng == "claude" else client_factory()
    log(f"  Menulis kode animasi {len(todo)} adegan dengan " + ("Claude (Claude Code)…" if eng == "claude" else "AI di Pengaturan…"))
    chunk = 4 if eng == "claude" else 3
    for k in range(0, len(todo), chunk):
        part = todo[k:k + chunk]
        if progress_cb:
            progress_cb(k / len(todo), f"Menulis animasi adegan {k + 1}–{k + len(part)} dari {len(todo)}")
        prompt = user_prompt(title, topic, part, len(scenes))
        got: dict = {}
        for attempt in range(2):
            try:
                got = _ask_claude(system, prompt) if eng == "claude" else _ask_llm(system, prompt, client)
                break
            except ClipAgentError as exc:
                log(f"  Percobaan {attempt + 1} gagal: {str(exc).splitlines()[0][:200]}")
        for sc in part:
            code = got.get(sc["sid"])
            if code:
                probs = static_problems(code)
                if probs:
                    log(f"  Adegan {sc['sid']}: {', '.join(probs)}; diperbaiki.")
                    code = repair(sc, code, "; ".join(probs), system, eng, client) or None
            if not code:
                log(f"  Adegan {sc['sid']}: kode animasi tidak didapat; memakai animasi cadangan.")
                code = fallback_code(sc)
            else:
                sc["_cache"].write_text(json.dumps(code, ensure_ascii=False), encoding="utf-8")
            out[sc["sid"]] = code
    return out


def repair_many(problems: list[tuple[dict, dict, str]], system: str, eng: str, client) -> dict[str, dict]:
    """Perbaiki adegan bermasalah (galat, kanvas kosong, teks bertumpuk), beberapa adegan per panggilan."""
    out: dict[str, dict] = {}
    for k in range(0, len(problems), 3):
        part = problems[k:k + 3]
        ids = [sc["sid"] for sc, _, _ in part]
        blocks = [f"### Scene {sc['sid']}\nProblem found when it was rendered and checked: {err}\n{_scene_brief(sc)}\n"
                  f"Current code:\n{json.dumps(code, ensure_ascii=False)[:20000]}" for sc, code, err in part]
        prompt = ("Some scenes failed the render check. Fix each one: keep its idea, design and timing, follow every rule, "
                  "and solve the problem described (for overlapping or cut-off text: lay blocks out in normal flow with "
                  ".center/.stack, shorten or shrink the text, never absolutely position text over other text). "
                  f"Return {{\"scenes\":[{{\"id\":...,\"html\":...,\"css\":...,\"js\":...}}]}} with exactly these ids: "
                  f"{', '.join(ids)}.\n\n" + "\n\n".join(blocks))
        try:
            got = _ask_claude(system, prompt) if eng == "claude" else _ask_llm(system, prompt, client)
        except ClipAgentError as exc:
            log(f"  Perbaikan adegan {', '.join(x[1:] for x in ids)} gagal: {str(exc).splitlines()[0][:160]}")
            continue
        for sc, _, _ in part:
            fixed = got.get(sc["sid"]) or (next(iter(got.values())) if len(part) == 1 and len(got) == 1 else None)
            if fixed and not static_problems(fixed):
                out[sc["sid"]] = fixed
    return out


def repair(sc: dict, code: dict, error: str, system: str, eng: str, client) -> dict | None:
    return repair_many([(sc, code, error)], system, eng, client).get(sc["sid"])


def fix_many(problems: list[tuple[dict, dict, str]], *, style_id: str, W: int, H: int, lang: str, captions: bool,
             engine: str, client_factory) -> dict[str, dict]:
    """Perbaikan setelah adegan diuji di browser render."""
    if not problems:
        return {}
    eng = engine_name(engine)
    try:
        client = None if eng == "claude" else client_factory()
    except ClipAgentError:
        return {}
    return repair_many(problems, system_prompt(style_id, W, H, lang, captions), eng, client)


def save_cache(sc: dict, code: dict) -> None:
    p = sc.get("_cache")
    if p:
        try:
            Path(p).write_text(json.dumps(code, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def parse_layout(logs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in logs:
        m = re.search(r"MOTION_LAYOUT (\{.*\})", line)
        if not m:
            continue
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if d.get("scene") and d.get("issues"):
            out.setdefault(str(d["scene"]), f"at {d.get('t', 0)} s: " + "; ".join(map(str, d["issues"]))[:600])
    return out


def parse_errors(logs: list[str]) -> dict[str, str]:
    errs: dict[str, str] = {}
    for line in logs:
        m = re.search(r"MOTION_ERROR (\{.*\})", line)
        if not m:
            continue
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if d.get("scene"):
            errs.setdefault(str(d["scene"]), str(d.get("msg") or ""))
    return errs


# ---------------------------------------------------------------- blueprint & ekspor HTML
def blueprint(proj: dict, W: int, H: int, timeline: list[dict] | None = None) -> str:
    """Prompt lengkap untuk ditempel di claude.ai (seperti aplikasi Blueprint): Claude menulis kodenya di sana.
    Bila suara sudah disiapkan, durasi dan waktu tiap kata ikut disertakan."""
    st, script = proj["settings"], proj["script"]
    style_id = st.get("motion_style") or "clean"
    if timeline:
        scenes = [{"sid": r["sid"], "dur": r["dur"], "narration": r["narration"], "heading": r["heading"],
                   "prompt": r.get("prompt", ""), "words": r.get("words", [])} for r in timeline]
        note = "Word timings come from the recorded narration."
    else:
        scenes = [{"sid": f"s{i + 1}", "dur": max(2.0, len((sc.get("narration") or "").split()) / 2.4),
                   "narration": sc.get("narration", ""), "heading": sc.get("heading", ""), "prompt": sc.get("prompt", ""),
                   "words": []} for i, sc in enumerate(script.get("scenes") or [])]
        note = "Durations are estimates; word timings are not available yet, so S.at() falls back to its second argument."
    sysp = system_prompt(style_id, W, H, "en" if st.get("audience") == "us" else "id", bool(st.get("captions")))
    return ("Build a motion-graphics video from this script. Write the code for every scene exactly in the format "
            "below, so it can be pasted back into Clip Agent or played with its MotionKit runtime.\n\n" + sysp + "\n\n" +
            user_prompt(script.get("title", ""), proj.get("topic", ""), scenes, len(scenes), note))


def _font_faces(design_: dict, codes: list[dict]) -> str:
    """Font yang dipakai disertakan di dalam file (base64), agar tampilan sama dengan videonya di komputer mana pun."""
    import base64
    src = (PROJECT_DIR / "remotion" / "src" / "fonts.ts").read_text(encoding="utf-8")
    files = dict(re.findall(r'"([^"]+)":\s*"([^"]+\.(?:ttf|woff2))"', src))
    text = " ".join(c.get("css", "") + c.get("html", "") for c in codes)
    used = {design_["head"], design_["body"]} | {f for f in files if f in text}
    out = []
    for fam in sorted(used):
        f = PROJECT_DIR / "remotion" / "public" / "fonts" / files.get(fam, "-")
        if f.is_file():
            kind = "woff2" if f.suffix == ".woff2" else "truetype"
            out.append(f'@font-face{{font-family:"{fam}";src:url(data:font/{f.suffix[1:]};base64,'
                       f'{base64.b64encode(f.read_bytes()).decode()}) format("{kind}")}}')
    return "\n".join(out)


def _esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def export_html(scenes: list[dict], codes: list[dict], design_: dict, W: int, H: int, audio_src: str = "",
                title: str = "Motion AI") -> str:
    """Satu file HTML yang memutar animasinya di browser (seperti artifact Claude), bisa diedit dan dibagikan."""
    kit = KIT.read_text(encoding="utf-8")
    kit = re.sub(r"^export\s+(?=(function|class|const))", "", kit, flags=re.M)
    css_base = (PROJECT_DIR / "remotion" / "src" / "MotionScene.tsx").read_text(encoding="utf-8")
    m = re.search(r"export const baseCss = \(d: MotionDesign, W: number, H: number\) => `([\s\S]*?)`;", css_base)
    base = m.group(1) if m else ""
    base = (base.replace("${d.bg}", design_["bg"]).replace("${d.surface}", design_["surface"]).replace("${d.ink}", design_["ink"])
            .replace("${d.muted}", design_["muted"]).replace("${d.accent}", design_["accent"]).replace("${d.accent2}", design_["accent2"])
            .replace("${d.head}", design_["head"]).replace("${d.body}", design_["body"])
            .replace("${d.radius ?? 28}", str(design_.get("radius", 28))).replace("${W}", str(W)).replace("${H}", str(H))
            .replace("${Math.min(W, H) / 100}", str(min(W, H) / 100))
            .replace("${Math.round(Math.min(W, H) * 0.04)}", str(round(min(W, H) * 0.04))))
    data = [{"start": s["start"], "dur": s["dur"], "words": s.get("words", []), "code": c} for s, c in zip(scenes, codes)]
    total = sum(s["dur"] for s in scenes)
    styles = "\n".join(f"#ms-{i}{{{base}}}\n#ms-{i}{{{c.get('css', '')}}}" for i, c in enumerate(codes))
    styles = _font_faces(design_, codes) + "\n" + styles
    return f"""<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{_esc(title)}</title><style>
html,body{{margin:0;height:100%;background:#111;color:#eee;font-family:system-ui,sans-serif}}
#wrap{{display:grid;place-items:center;height:calc(100% - 56px)}} #frame{{position:relative;width:{W}px;height:{H}px;transform-origin:0 0;overflow:hidden}}
#bar{{height:56px;display:flex;gap:12px;align-items:center;padding:0 16px}} #bar input{{flex:1}}
.scene{{position:absolute;inset:0;visibility:hidden}}
{styles}
</style></head><body><div id="wrap"><div id="box"><div id="frame">{''.join(f'<div class="scene" id="ms-{i}"></div>' for i in range(len(codes)))}</div></div></div>
<div id="bar"><button id="play">Putar</button><input id="seek" type="range" min="0" max="{total:.2f}" step="0.01" value="0"><span id="t">0.0</span></div>
{f'<audio id="vo" src="{audio_src}" preload="auto"></audio>' if audio_src else ''}
<script>
{kit}
const DATA={json.dumps(data, ensure_ascii=False).replace("</", "<\\/")};
const TL=DATA.map((d,i)=>{{const root=document.getElementById('ms-'+i);try{{return buildScene(root,d.code,{{id:'s'+(i+1),w:{W},h:{H},dur:d.dur,words:d.words}});}}catch(e){{return null;}}}});
const frame=document.getElementById('frame'),box=document.getElementById('box');
function fit(){{const s=Math.min(innerWidth/{W},(innerHeight-56)/{H});frame.style.transform='scale('+s+')';box.style.width={W}*s+'px';box.style.height={H}*s+'px';}}
addEventListener('resize',fit);fit();
let t=0,playing=false,last=0;const vo=document.getElementById('vo');
function show(time){{DATA.forEach((d,i)=>{{const on=time>=d.start&&time<d.start+d.dur;const el=document.getElementById('ms-'+i);el.style.visibility=on?'visible':'hidden';if(on&&TL[i])TL[i].seek(time-d.start);}});
document.getElementById('seek').value=time;document.getElementById('t').textContent=time.toFixed(1);}}
function loop(ts){{if(playing){{t=vo?vo.currentTime:t+(ts-last)/1000;last=ts;if(t>={total:.2f}){{playing=false;t=0;}}show(t);}}requestAnimationFrame(loop);}}
document.getElementById('play').onclick=()=>{{playing=!playing;last=performance.now();if(vo){{vo.currentTime=t;playing?vo.play():vo.pause();}}}};
document.getElementById('seek').oninput=e=>{{t=+e.target.value;if(vo)vo.currentTime=t;show(t);}};
show(0);requestAnimationFrame(loop);
</script></body></html>"""
