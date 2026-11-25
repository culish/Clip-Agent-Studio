"""Film bergaya dari Lemo-Opuscar (github.com/lemomo-ai/lemo-opuscar): 99 gaya film yang dibuat seluruhnya dengan kode.

Library itu dibuat untuk dikerjakan oleh agen coding: agen membaca panduan sutradara dan STYLE.md, menulis treatment,
lalu menggambar, mengisi suara, membuat musik, dan me-mix film itu dengan kode (30–60 menit per film). Clip Agent
tidak menyalin isi library (panduannya berlisensi CC BY-NC 4.0); Clip Agent mengunduh library ke komputer Anda dengan
skrip pemasangnya sendiri, lalu menjalankan Claude Code (CLI `claude`) tanpa pengawasan dengan skill lemo-opuscar,
mengikuti langkahnya, mencatat kemajuannya, dan memasukkan film jadinya ke Klip saya dan Posting.
Film yang Anda buat adalah milik Anda, termasuk untuk komersial (lihat LICENSE library tersebut).
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .config import PROJECT_DIR
from .utils import Cancelled, ClipAgentError, check_cancel, log, progress

REPO = "https://github.com/lemomo-ai/lemo-opuscar"
GALLERY = "https://lemomo-ai.github.io/lemo-opuscar/"
CARD_URL = "https://raw.githubusercontent.com/lemomo-ai/lemo-opuscar/main/docs/readme/cards/{slug}-poster.webp"
DEMO_URL = "https://github.com/lemomo-ai/lemo-opuscar/releases/download/films/{slug}.mp4"
SETTINGS_PATH = PROJECT_DIR / "data" / "film_settings.json"
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080)}
LANGS = {"id": "Bahasa Indonesia", "en": "English"}
VOICES = {"pria": "a warm male narrator", "wanita": "a warm female narrator", "none": "no narration (music, sound and on-screen text only)"}
EFFORTS = ["high", "xhigh", "max", "medium"]
MATERIAL_EXT = {".jpg", ".jpeg", ".png", ".webp", ".svg", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mov",
                ".ttf", ".otf", ".pdf", ".txt", ".csv", ".json"}
DEFAULTS = {"library": "", "claude": "", "model": "", "effort": "high", "budget_usd": 0, "consent": False,
            "agent": "claude", "agent_model": "", "bins": {}}

# Fase kerja agen, dikenali dari alat dan perintah yang dipakainya (untuk perkiraan kemajuan)
PHASES = [
    (r"setup\.sh|AGENTS\.md|lemo-opuscar", 0.05, "Menyiapkan library"),
    (r"TREATMENT\.md", 0.15, "Menulis treatment"),
    (r"still\.mjs|style frame|model sheet|STYLE\.md", 0.25, "Membuktikan tampilan"),
    (r"tts(_zh)?\.py|edge[-_]tts|asr_check|kokoro|lines\.json", 0.4, "Mengisi suara"),
    (r"pluck\.py|sampler|score|music|sfx", 0.52, "Membuat musik dan efek suara"),
    (r"core/render/(render|frames)|render\.mjs|frames/", 0.65, "Merender gambar"),
    (r"loudnorm|mux|amix|LUFS|ffmpeg .*-i", 0.85, "Mixing dan menggabungkan"),
    (r"poster\.jpg|CREDITS|build\.sh|contact sheet|asr", 0.93, "Memeriksa dan menyerahkan"),
]


# ---------------------------------------------------------------- pengaturan & lingkungan
def films_dir(out_dir: Path) -> Path:
    d = out_dir / "_film"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_settings() -> dict:
    st = dict(DEFAULTS)
    try:
        st.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return st


def save_settings(raw: dict) -> dict:
    st = get_settings()
    if "library" in raw:
        st["library"] = str(raw["library"] or "").strip()
    if "claude" in raw:
        st["claude"] = str(raw["claude"] or "").strip()
    if "model" in raw:
        m = str(raw["model"] or "").strip()
        st["model"] = m if re.fullmatch(r"[\w.\-\[\]]{0,60}", m) else ""
    if raw.get("effort") in EFFORTS:
        st["effort"] = raw["effort"]
    if "budget_usd" in raw:
        try:
            st["budget_usd"] = max(0.0, min(500.0, float(raw["budget_usd"] or 0)))
        except (TypeError, ValueError):
            pass
    if "consent" in raw:
        st["consent"] = bool(raw["consent"])
    from . import agents
    if raw.get("agent") in agents.AGENTS and agents.AGENTS[raw["agent"]]["film"]:
        st["agent"] = raw["agent"]
    if "agent_model" in raw:
        m = str(raw["agent_model"] or "").strip()
        st["agent_model"] = m if re.fullmatch(r"[\w.:/\-\[\]]{0,80}", m) else ""
    if isinstance(raw.get("bins"), dict):
        st["bins"] = {k: str(v or "").strip()[:400] for k, v in raw["bins"].items() if k in agents.AGENTS}
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return st


def library_dir() -> Path:
    st = get_settings()
    p = st.get("library") or os.getenv("LEMO_OPUSCAR_HOME") or str(Path.home() / "lemo-opuscar")
    return Path(os.path.expanduser(p))


def is_library(p: Path) -> bool:
    return (p / "AGENTS.md").is_file() and (p / "core" / "render").is_dir()


def claude_bin() -> str | None:
    st = get_settings()
    if st.get("claude"):
        p = os.path.expanduser(st["claude"])
        return p if Path(p).is_file() else shutil.which(p)
    found = shutil.which("claude")
    if found:
        return found
    for cand in (Path.home() / ".local" / "bin" / "claude", Path.home() / ".claude" / "local" / "claude",
                 Path(os.getenv("APPDATA", "")) / "npm" / "claude.cmd"):
        if cand.is_file():
            return str(cand)
    return None


def sh_bin() -> str | None:
    for name in ("sh", "bash"):
        p = shutil.which(name)
        if p and not p.lower().endswith(("system32\\bash.exe", "system32/bash.exe")):
            return p
    if os.name == "nt":
        for base in (os.getenv("ProgramFiles", r"C:\Program Files"), os.getenv("ProgramFiles(x86)", ""),
                     str(Path.home() / "AppData" / "Local" / "Programs")):
            p = Path(base) / "Git" / "bin" / "sh.exe"
            if p.is_file():
                return str(p)
    return None


def _ver(cmd: list, pat: str) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=20, encoding="utf-8",
                             errors="replace")
        m = re.search(pat, (out.stdout or "") + (out.stderr or ""))
        return m.group(1) if m else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _launch(exe: str) -> list:
    """Windows tidak bisa menjalankan .cmd/.bat langsung tanpa cmd.exe."""
    return ["cmd", "/c", exe] if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")) else [exe]


def status() -> dict:
    from . import agents
    lib = library_dir()
    claude = claude_bin()
    agent = get_settings().get("agent") or "claude"
    agent_exe = claude if agent == "claude" else agents.find(agent)
    node_v = _ver(["node", "-v"], r"v(\d+)") if shutil.which("node") else ""
    ff_v = _ver(["ffmpeg", "-version"], r"ffmpeg version n?(\d+)") if shutil.which("ffmpeg") else ""
    py_ok = bool(shutil.which("uv")) or any(
        _ver([c, "-c", "import sys;print(sys.version_info[:2]>=(3,11))"], r"(True)") for c in ("python3", "python") if shutil.which(c))
    have = is_library(lib)
    core_ok = have and (lib / "node_modules" / ".lemo-ok").is_file() and (lib / ".venv" / ".lemo-core").is_file()
    voice_ok = have and (lib / ".venv" / ".lemo-voice").is_file() and (lib / "core" / "tts" / "kokoro-v1.0.onnx").is_file()
    music_ok = have and (lib / ".venv" / ".lemo-music").is_file()
    rev = ""
    if have:
        rev = _ver(["git", "-C", str(lib), "log", "-1", "--format=%h %cs"], r"(\w+ \S+)")
    checks = [
        {"id": "claude", "label": f"Agen: {agents.AGENTS[agent]['name']}", "ok": bool(agent_exe),
         "detail": _ver(_launch(agent_exe) + ["--version"], r"(\d+\.\d+\.\d+)") if agent_exe else "",
         "fix": (f"Pasang {agents.AGENTS[agent]['name']} dengan `{agents.AGENTS[agent]['install']}`, lalu login dengan "
                 f"`{agents.AGENTS[agent]['login']}` (perintah harus jalan di terminal). Atau pilih agen lain di pengaturan film.")},
        {"id": "node", "label": "Node.js 20+", "ok": bool(node_v) and int(node_v) >= 20, "detail": f"v{node_v}" if node_v else "",
         "fix": "Pasang Node.js 20 atau lebih baru dari https://nodejs.org"},
        {"id": "ffmpeg", "label": "ffmpeg 7+", "ok": bool(ff_v) and int(ff_v) >= 7, "detail": ff_v,
         "fix": "ffmpeg 7 atau lebih baru (Ubuntu 24.04 masih 6.1: pakai build statis)."},
        {"id": "python", "label": "Python 3.11+ atau uv", "ok": py_ok, "detail": "",
         "fix": "Pasang Python 3.11+ atau uv (https://docs.astral.sh/uv/)."},
        {"id": "sh", "label": "Shell (sh / Git Bash)", "ok": bool(sh_bin()), "detail": "",
         "fix": "Di Windows: pasang Git for Windows (Git Bash)."},
        {"id": "library", "label": "Library Lemo-Opuscar", "ok": have, "detail": f"{lib} {rev}".strip(),
         "fix": "Klik Pasang library (unduhan pertama beberapa ratus MB)."},
        {"id": "deps", "label": "Paket render (Node, browser, Python)", "ok": core_ok,
         "detail": "suara " + ("✓" if voice_ok else "✗") + " · musik " + ("✓" if music_ok else "✗"),
         "fix": "Klik Pasang library: paket inti ikut dipasang. Paket suara dan musik dipasang agen bila film membutuhkannya."},
    ]
    ready = all(c["ok"] for c in checks if c["id"] in ("claude", "library", "node", "ffmpeg", "python", "sh"))
    return {"checks": checks, "ready": ready, "library": str(lib), "gallery": GALLERY, "repo": REPO,
            "settings": get_settings(), "efforts": EFFORTS, "agents": agents.public()}


# ---------------------------------------------------------------- daftar gaya
_STYLES: tuple[float, list] | None = None


def styles() -> list[dict]:
    """Gaya dari library yang terpasang (styles/*/style.json)."""
    global _STYLES
    lib = library_dir()
    root = lib / "styles"
    if not root.is_dir():
        return []
    mtime = root.stat().st_mtime
    if _STYLES and _STYLES[0] == mtime:
        return _STYLES[1]
    out = []
    for f in sorted(root.glob("*/style.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slug = d.get("slug") or f.parent.name
        if slug.startswith("_") or f.parent.name.startswith("_"):
            continue
        out.append({"slug": slug, "num": d.get("num", ""), "en": d.get("en", slug), "cn": d.get("cn", ""),
                    "category": d.get("category_en", ""), "uses": d.get("uses", [])[:4], "film": d.get("film", ""),
                    "line": d.get("line", ""), "dur": d.get("dur", 0), "image_gen": "image-generation" in (d.get("needs") or []),
                    "by": d.get("by", ""), "card": CARD_URL.format(slug=slug), "page": f"{GALLERY}styles/{slug}/",
                    "demo": DEMO_URL.format(slug=slug),
                    "poster_local": (f.parent / "poster.jpg").is_file()})
    out.sort(key=lambda x: (x["num"] or "999").zfill(3))
    _STYLES = (mtime, out)
    return out


def style(slug: str) -> dict:
    for s in styles():
        if s["slug"] == slug:
            return s
    raise ClipAgentError("Gaya film tidak ditemukan di library. Pasang atau perbarui library dulu.")


# ---------------------------------------------------------------- pemasangan library
def _stream(cmd: list, cwd: Path | None, env: dict | None, on_line, idle_check=None) -> int:
    """Jalankan perintah, kirim tiap baris output ke on_line, dan hentikan seluruh pohon proses bila dibatalkan."""
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)
    return _pump(proc, on_line, idle_check)


def _pump(proc: subprocess.Popen, on_line, idle_check=None, stdin_text: str | None = None) -> int:
    q: queue.Queue = queue.Queue()

    def reader():
        for line in proc.stdout:
            q.put(line)
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    if stdin_text is not None:
        try:
            proc.stdin.write(stdin_text)
        except OSError:
            pass
    try:
        proc.stdin.close()
    except OSError:
        pass
    try:
        while True:
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                check_cancel()
                if idle_check:
                    idle_check()
                continue
            if line is None:
                break
            on_line(line.rstrip("\n"))
            check_cancel()
        return proc.wait()
    except Cancelled:
        kill_tree(proc)
        raise


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _setup_script(lib: Path) -> Path | None:
    p = lib / "plugin" / "skills" / "lemo-opuscar" / "scripts" / "setup.sh"
    return p if p.is_file() else None


def install(with_voice: bool = False, with_music: bool = False) -> dict:
    """Unduh/perbarui library dengan skrip pemasangnya sendiri, lalu pasang paket intinya."""
    sh = sh_bin()
    if not sh:
        raise ClipAgentError("Perlu sh untuk memasang library. Di Windows, pasang Git for Windows (Git Bash).")
    if not shutil.which("git"):
        raise ClipAgentError("Perlu git untuk mengunduh library.")
    lib = library_dir()
    env = {**os.environ, "LEMO_OPUSCAR_HOME": str(lib)}
    if not is_library(lib):
        if lib.exists() and any(lib.iterdir()):
            raise ClipAgentError(f"Folder {lib} sudah berisi file lain. Pilih folder library lain di pengaturan film.")
        log(f"Mengunduh library Lemo-Opuscar ke {lib} (unduhan pertama bisa beberapa menit)…")
        progress(0.05, "Mengunduh library")
        lib.parent.mkdir(parents=True, exist_ok=True)
        # klon jarang (sparse) seperti skrip pemasangnya: panduan, core/, dan semua STYLE.md, tanpa video demo
        rc = _stream(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", "--branch", "main", REPO + ".git", str(lib)],
                     None, env, lambda ln: log(f"  {ln}") if ln.strip() else None)
        if rc != 0:
            shutil.rmtree(lib, ignore_errors=True)
            raise ClipAgentError("Gagal mengunduh library (cek koneksi internet).")
        # pola yang sama dengan setup.sh: panduan, core/ dan semua STYLE.md; tanpa sumber demo, galeri, dan poster
        subprocess.run(["git", "-C", str(lib), "sparse-checkout", "set", "--no-cone", "/*", "!/styles/*/demo/", "!/styleboard/",
                        "!/docs/readme/", "!/docs/cover.jpg", "!/styles/*/poster.jpg"], capture_output=True)
        subprocess.run(["git", "-C", str(lib), "config", "lemo.managed", "true"], capture_output=True)
    script = _setup_script(lib)
    if not script:
        raise ClipAgentError("Skrip pemasang library tidak ditemukan; hapus folder library lalu pasang ulang.")
    progress(0.2, "Memeriksa library")
    _stream([sh, str(script)], lib, env, lambda ln: log(f"  {ln}") if ln.strip() else None)
    tiers = ["deps"] + (["voice"] if with_voice else []) + (["music"] if with_music else [])
    log("Memasang paket render (Node, browser headless, Python). Pertama kali bisa 5–15 menit…")
    progress(0.3, "Memasang paket")
    n = {"i": 0}

    def tick(ln):
        if ln.strip():
            log(f"  {ln[:200]}")
        n["i"] += 1
        progress(min(0.95, 0.3 + n["i"] * 0.004), "Memasang paket")
    rc = _stream([sh, str(script), *tiers], lib, env, tick)
    if rc != 0:
        raise ClipAgentError("Pemasangan paket gagal; lihat log. Biasanya karena Node/Python belum terpasang.")
    global _STYLES
    _STYLES = None
    progress(1.0, "Library siap")
    return status()


# ---------------------------------------------------------------- proyek film
def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(s) > 40:
        s = s[:40].rsplit("-", 1)[0] if "-" in s[:40] else s[:40]
    return s.strip("-") or "film"


def _films_file(out_dir: Path) -> Path:
    return films_dir(out_dir) / "films.json"


def list_films(out_dir: Path) -> list[dict]:
    try:
        items = json.loads(_films_file(out_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    for f in items:
        f.update(_files(out_dir, f))
    return sorted(items, key=lambda x: x.get("created", ""), reverse=True)


def _save_films(out_dir: Path, items: list[dict]) -> None:
    keep = [{k: v for k, v in f.items() if k not in ("video_url", "poster_url", "files")} for f in items]
    _films_file(out_dir).write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")


def get_film(out_dir: Path, fid: str) -> dict:
    for f in list_films(out_dir):
        if f["id"] == fid:
            return f
    raise ClipAgentError("Film tidak ditemukan.")


def _update(out_dir: Path, fid: str, **kw) -> dict:
    items = list_films(out_dir)
    for f in items:
        if f["id"] == fid:
            f.update(kw)
            _save_films(out_dir, items)
            return f
    raise ClipAgentError("Film tidak ditemukan.")


def project(out_dir: Path, film: dict) -> Path:
    return films_dir(out_dir) / film["name"]


def _files(out_dir: Path, f: dict) -> dict:
    d = films_dir(out_dir) / f["name"]
    res: dict = {"files": []}
    if not d.is_dir():
        return res
    mp4 = d / f"{f['name']}.mp4"
    if not mp4.is_file():
        vids = sorted((p for p in d.glob("*.mp4") if p.stat().st_size > 50_000), key=lambda p: p.stat().st_mtime, reverse=True)
        mp4 = vids[0] if vids else None
    if mp4 and mp4.is_file():
        rel = mp4.relative_to(out_dir).as_posix()
        res["video"] = rel
        res["video_url"] = f"/files/{rel}?v={int(mp4.stat().st_mtime)}"
    poster = d / "poster.jpg"
    if poster.is_file():
        res["poster_url"] = f"/files/{poster.relative_to(out_dir).as_posix()}?v={int(poster.stat().st_mtime)}"
    for name in ("TREATMENT.md", "CREDITS", f"{f['name']}.srt", "build.sh"):
        if (d / name).is_file():
            res["files"].append({"name": name, "url": f"/files/{(d / name).relative_to(out_dir).as_posix()}"})
    for p in sorted(d.glob("subtitles_*.srt")):
        res["files"].append({"name": p.name, "url": f"/files/{p.relative_to(out_dir).as_posix()}"})
    return res


def new_film(out_dir: Path, raw: dict) -> dict:
    st = style(str(raw.get("style") or ""))
    topic = re.sub(r"\s+", " ", str(raw.get("topic") or "")).strip()
    if len(topic) < 8:
        raise ClipAgentError("Ceritakan topik filmnya (minimal satu kalimat).")
    try:
        dur = int(raw.get("duration") or 45)
    except (TypeError, ValueError):
        dur = 45
    dur = max(15, min(180, dur))
    aspect = raw.get("aspect") if raw.get("aspect") in ASPECTS else "16:9"
    lang = raw.get("lang") if raw.get("lang") in LANGS else "id"
    voice = raw.get("voice") if raw.get("voice") in VOICES else "pria"
    existing = {f["name"] for f in list_films(out_dir)}
    base = _slug(str(raw.get("name") or "") or topic)
    name, i = base, 2
    while name in existing or (films_dir(out_dir) / name).exists():
        name, i = f"{base}-{i}", i + 1
    film = {"id": uuid.uuid4().hex[:10], "name": name, "style": st["slug"], "style_name": st["en"], "topic": topic[:2000],
            "duration": dur, "aspect": aspect, "lang": lang, "voice": voice,
            "facts": str(raw.get("facts") or "").strip()[:2000], "notes": str(raw.get("notes") or "").strip()[:2000],
            "status": "baru", "created": time.strftime("%Y-%m-%d %H:%M:%S"), "session": "", "cost_usd": 0.0, "runs": []}
    (films_dir(out_dir) / name / "material").mkdir(parents=True, exist_ok=True)
    items = list_films(out_dir)
    items.append(film)
    _save_films(out_dir, items)
    return get_film(out_dir, film["id"])


def add_material(out_dir: Path, fid: str, filename: str, data_url: str) -> dict:
    f = get_film(out_dir, fid)
    name = re.sub(r"[^\w.\- ]+", "_", Path(str(filename or "")).name).strip() or "file"
    if Path(name).suffix.lower() not in MATERIAL_EXT:
        raise ClipAgentError("Jenis file tidak didukung (foto, logo, musik, rekaman suara, video, font, PDF, CSV).")
    if not str(data_url).startswith("data:") or "," not in data_url:
        raise ClipAgentError("Unggahan tidak valid.")
    raw = base64.b64decode(data_url.split(",", 1)[1])
    if len(raw) > 60_000_000:
        raise ClipAgentError("File terlalu besar (maks. 60 MB).")
    d = project(out_dir, f) / "material"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(raw)
    return {"materials": materials(out_dir, f)}


def materials(out_dir: Path, f: dict) -> list[str]:
    d = project(out_dir, f) / "material"
    return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []


def delete_film(out_dir: Path, fid: str, files: bool = False) -> None:
    items = list_films(out_dir)
    f = next((x for x in items if x["id"] == fid), None)
    if not f:
        raise ClipAgentError("Film tidak ditemukan.")
    _save_films(out_dir, [x for x in items if x["id"] != fid])
    if files:
        shutil.rmtree(project(out_dir, f), ignore_errors=True)


# ---------------------------------------------------------------- menjalankan agen
def brief(out_dir: Path, f: dict) -> str:
    """Permintaan untuk agen: satu kalimat seperti di README library, plus semua jawaban babak pertanyaannya."""
    lib = library_dir()
    W, H = ASPECTS[f["aspect"]]
    mats = materials(out_dir, f)
    lang = LANGS[f["lang"]]
    lines = [
        f"Use the lemo-opuscar skill. Make a {f['duration']}-second film in the **{f['style_name']}** style "
        f"(folder `{f['style']}`) about: {f['topic']}",
        "",
        "Brief (these are my answers to your one round of questions; don't ask again):",
        f"- Project folder: `{f['name']}/` in the current folder (skill mode). The library is at {lib}.",
        f"- Frame: {W}x{H}" + (" (vertical, for Shorts/Reels/TikTok: keep text and key action away from the bottom 20%)"
                                if H > W else "") + ".",
        f"- Language for voice, on-screen text and subtitles: {lang}.",
        f"- Narration: {VOICES[f['voice']]}."
        + (" For Indonesian narration use edge-tts with an id-ID neural voice (id-ID-ArdiNeural male, id-ID-GadisNeural "
           "female), with the same outputs as core/tts/tts_zh.py, and check every line with faster-whisper in Indonesian."
           if f["lang"] == "id" and f["voice"] != "none" else ""),
        "- Facts, names or products that must appear: " + (f["facts"] or "none beyond the topic; keep facts accurate and "
                                                            "don't invent statistics."),
        ("- My own material is in `" + f["name"] + "/material/`: " + ", ".join(mats) + ". Use it where it fits the style.")
        if mats else "- I have no material of my own: use your defaults (TTS voice, an original score).",
        "- No storyboard: go straight to the finished film.",
    ]
    if f.get("notes"):
        lines.append(f"- Other notes: {f['notes']}")
    lines += ["", "Deliver everything DIRECTOR.md §11 lists in the project folder, named "
              f"`{f['name']}.mp4`. End your final message with one line: FILM=<absolute path of the mp4>."]
    return "\n".join(lines)


UNATTENDED = ("You are running unattended inside Clip Agent, a desktop app. Nobody can answer questions or permission "
              "prompts: never ask the user, never wait for approval, never use AskUserQuestion. The brief in the prompt "
              "already answers the skill's one round of questions; fill any other gap with a sensible default, state it "
              "in one line and carry on to the finished film. Install packages with the library's setup.sh as the skill "
              "says. Don't install system software; if something essential is missing, stop and say exactly what.")


def _cmd(prompt_resume: str | None, f: dict) -> list:
    exe = claude_bin()
    if not exe:
        raise ClipAgentError("Claude Code (perintah `claude`) tidak ditemukan. Pasang dan login dulu, atau isi lokasinya di pengaturan film.")
    st = get_settings()
    lib = library_dir()
    cmd = _launch(exe) + ["-p", "--output-format", "stream-json", "--verbose",
                          "--plugin-dir", str(lib / "plugin"), "--add-dir", str(lib),
                          "--permission-mode", os.getenv("OPUSCAR_PERMISSION_MODE", "acceptEdits"),
                          "--allowedTools", "Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "WebFetch",
                          "WebSearch", "Skill", "TodoWrite", "Task", "NotebookEdit",
                          "--disallowedTools", "AskUserQuestion",
                          "--append-system-prompt", UNATTENDED]
    if st.get("effort"):
        cmd += ["--effort", st["effort"]]
    if st.get("model"):
        cmd += ["--model", st["model"]]
    if st.get("budget_usd"):
        cmd += ["--max-budget-usd", str(st["budget_usd"])]
    if prompt_resume:
        cmd += ["--resume", prompt_resume]
    return cmd


def _describe_tool(name: str, inp: dict) -> str:
    if name == "Bash":
        return "$ " + re.sub(r"\s+", " ", str(inp.get("command", "")))[:160]
    if name in ("Write", "Edit", "MultiEdit", "Read", "NotebookEdit"):
        return f"{name}: {inp.get('file_path') or inp.get('notebook_path') or ''}"
    if name == "Skill":
        return f"Skill: {inp.get('skill') or inp.get('command') or ''}"
    if name in ("WebSearch", "WebFetch"):
        return f"{name}: {inp.get('query') or inp.get('url') or ''}"[:160]
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        doing = next((t.get("activeForm") or t.get("content") for t in todos if t.get("status") == "in_progress"), "")
        return f"Daftar tugas: {doing}" if doing else ""
    return name


def run_agent(out_dir: Path, fid: str, revision: str = "") -> dict:
    f = get_film(out_dir, fid)
    st = get_settings()
    if not st.get("consent"):
        raise ClipAgentError("Centang dulu izin agen di pengaturan film: agen akan menjalankan perintah di komputer ini.")
    lib = library_dir()
    if not is_library(lib):
        raise ClipAgentError("Library Lemo-Opuscar belum terpasang. Klik Pasang library di tab Film.")
    if revision and not f.get("session") and (st.get("agent") or "claude") == "claude":
        raise ClipAgentError("Film ini belum punya sesi agen untuk direvisi; buat filmnya dulu.")
    prompt = (f"Revise the film in `{f['name']}/` (style {f['style_name']}). My notes:\n{revision}\n\nChange only what the "
              f"notes ask, re-render, run the checks again and deliver `{f['name']}.mp4` again. End your final message "
              "with one line: FILM=<absolute path of the mp4>.") if revision else brief(out_dir, f)
    agent = st.get("agent") or "claude"
    if agent != "claude":
        return _run_other(out_dir, f, agent, revision)
    cmd = _cmd(f["session"] if revision else None, f)
    cwd = films_dir(out_dir)
    pdir = cwd / f["name"]
    pdir.mkdir(parents=True, exist_ok=True)
    logs = pdir / ".clipagent"
    logs.mkdir(exist_ok=True)
    run_no = len(f.get("runs") or []) + 1
    transcript = logs / f"agent-{run_no}.jsonl"
    _update(out_dir, fid, status="revisi" if revision else "dibuat")
    log(("Revisi film" if revision else "Membuat film") + f" «{f['name']}» bergaya {f['style_name']} dengan Claude Code.")
    log("Agen bekerja sendiri sekitar 30–60 menit dan memakai kuota Claude Anda. Jangan tutup Clip Agent.")
    env = {**os.environ, "LEMO_OPUSCAR_HOME": str(lib)}
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)
    t0 = time.time()
    state = {"phase": 0.02, "stage": "Agen mulai", "result": None, "session": f.get("session", ""), "last_text": "",
             "errors": []}

    def bump(text: str):
        for pat, frac, stage in PHASES:
            if frac > state["phase"] and re.search(pat, text, re.I):
                state["phase"], state["stage"] = frac, stage
        tf = min(0.9, (time.time() - t0) / (50 * 60) * 0.9)      # ~50 menit untuk film biasa
        progress(max(state["phase"], tf if state["phase"] > 0.05 else min(tf, 0.05)), state["stage"])

    def on_line(line: str):
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        try:
            ev = json.loads(line)
        except ValueError:
            if line.strip():
                log(f"  {line.strip()[:200]}")
                state["errors"].append(line.strip())
            return
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            state["session"] = ev.get("session_id") or state["session"]
            _update(out_dir, fid, session=state["session"])
            log(f"  Claude Code {ev.get('claude_code_version', '')}, model {ev.get('model', '')}")
        elif t == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "text" and c.get("text", "").strip():
                    txt = c["text"].strip()
                    state["last_text"] = txt
                    log("  " + re.sub(r"\s+", " ", txt)[:300])
                    bump(txt)
                elif c.get("type") == "tool_use":
                    desc = _describe_tool(c.get("name", ""), c.get("input") or {})
                    if desc:
                        log("  ▸ " + desc)
                    bump(json.dumps(c.get("input") or {})[:2000] + " " + desc)
        elif t == "result":
            state["result"] = ev
        bump("")

    try:
        rc = _pump(proc, on_line, idle_check=lambda: bump(""), stdin_text=prompt)
    except Cancelled:
        _update(out_dir, fid, status="dibatalkan")
        raise
    res = state["result"] or {}
    cost = float(res.get("total_cost_usd") or 0)
    runs = list(f.get("runs") or []) + [{"at": time.strftime("%Y-%m-%d %H:%M:%S"), "revision": revision[:500],
                                         "minutes": round((time.time() - t0) / 60, 1), "cost_usd": round(cost, 4),
                                         "ok": not res.get("is_error") and rc == 0}]
    final = str(res.get("result") or state["last_text"] or "")
    m = re.search(r"FILM=(.+\.mp4)", final)
    mp4 = Path(m.group(1).strip().strip("`")) if m else None
    expected = pdir / f"{f['name']}.mp4"
    if mp4 and mp4.is_file() and mp4.resolve() != expected.resolve() and mp4.resolve().is_relative_to(cwd.resolve()):
        shutil.copy2(mp4, expected)
    info = _files(out_dir, f)
    ok = bool(info.get("video")) and rc == 0 and not res.get("is_error")
    _update(out_dir, fid, status="selesai" if ok else "gagal", session=state["session"] or f.get("session", ""),
            cost_usd=round(float(f.get("cost_usd") or 0) + cost, 4), runs=runs, summary=final[-1500:])
    if not ok:
        why = final[-600:] or "\n".join(state["errors"][-6:]) or f"kode keluar {rc}"
        if not info.get("video"):
            raise ClipAgentError(f"Agen selesai tanpa file film. Pesan terakhirnya:\n{why}")
        raise ClipAgentError(f"Agen berhenti dengan galat:\n{why}")
    log(f"Film siap: {info['video']}" + (f" (biaya API sekitar US${cost:.2f})" if cost else ""))
    progress(1.0, "Film siap")
    return {"film": fid, "video": info["video"], "video_url": info.get("video_url"), "cost_usd": cost}


def _other_prompt(f: dict, lib: Path, revision: str, brief_text: str) -> str:
    """Agen selain Claude tidak memuat plugin Claude Code: arahkan ke panduan library yang sama (AGENTS.md + skill)."""
    skills = sorted(str(p) for p in (lib / "plugin").glob("**/SKILL.md")) if (lib / "plugin").is_dir() else []
    head = (UNATTENDED.replace(", never use AskUserQuestion", "") + "\n\nThe lemo-opuscar library is at " + str(lib)
            + ". Before anything else read " + str(lib / "AGENTS.md")
            + (" and the skill instructions in " + ", ".join(skills[:3]) if skills else "")
            + ", then follow them exactly as a coding agent would (DIRECTOR.md, the style's STYLE.md, the checks). "
              "Work in the current folder. Run long commands to completion and check their output.\n\n")
    if revision:
        return head + (f"Revise the film already in `{f['name']}/` (style {f['style_name']}); read its TREATMENT.md and "
                       f"files first. My notes:\n{revision}\n\nChange only what the notes ask, re-render, run the checks "
                       f"again and deliver `{f['name']}.mp4` again. End your final message with one line: "
                       "FILM=<absolute path of the mp4>.")
    return head + brief_text.replace("Use the lemo-opuscar skill. ", "")


def _run_other(out_dir: Path, f: dict, agent: str, revision: str) -> dict:
    """Film dengan Codex / Gemini CLI / Qwen Code: panduan yang sama, keluaran JSON Lines atau teks."""
    from . import agents
    st = get_settings()
    lib = library_dir()
    cwd = films_dir(out_dir)
    pdir = cwd / f["name"]
    pdir.mkdir(parents=True, exist_ok=True)
    logs = pdir / ".clipagent"
    logs.mkdir(exist_ok=True)
    prompt = _other_prompt(f, lib, revision, brief(out_dir, f))
    done_before = [p.name for p in pdir.iterdir() if not p.name.startswith(".")] if pdir.is_dir() else []
    if done_before and not revision and f.get("runs"):
        prompt += (f"\n\nNOTE: an earlier attempt stopped midway (for example a usage limit). `{f['name']}/` already "
                   f"contains: {', '.join(sorted(done_before)[:25])}. Read what is there and CONTINUE from it; do not redo "
                   "finished steps or overwrite good work.")
    cmd, _ = agents.agentic_cmd(agent, lib=lib, cwd=cwd, model=st.get("agent_model") or "")
    name = agents.AGENTS[agent]["name"]
    run_no = len(f.get("runs") or []) + 1
    transcript = logs / f"agent-{run_no}.jsonl"
    fid = f["id"]
    _update(out_dir, fid, status="revisi" if revision else "dibuat")
    log(("Revisi film" if revision else "Membuat film") + f" «{f['name']}» bergaya {f['style_name']} dengan {name}.")
    log(f"Agen bekerja sendiri sekitar 30–60 menit dan memakai kuota {name} Anda. Jangan tutup Clip Agent.")
    env = {**agents.env(), "LEMO_OPUSCAR_HOME": str(lib)}
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)
    t0 = time.time()
    state = {"phase": 0.02, "stage": "Agen mulai", "texts": [], "buf": "", "errors": [], "session": ""}

    def bump(text: str):
        for pat, frac, stage in PHASES:
            if frac > state["phase"] and re.search(pat, text, re.I):
                state["phase"], state["stage"] = frac, stage
        tf = min(0.9, (time.time() - t0) / (50 * 60) * 0.9)
        progress(max(state["phase"], tf if state["phase"] > 0.05 else min(tf, 0.05)), state["stage"])

    def on_line(line: str):
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        ev = agents.parse_event(line)
        if ev.get("session"):
            state["session"] = ev["session"]
        if ev.get("tool"):
            log("  ▸ " + ev["tool"])
            bump(ev["tool"])
        if ev.get("text"):
            if ev.get("delta"):
                state["buf"] += ev["text"]
            else:
                txt = (state["buf"] + ev["text"]).strip()
                state["buf"] = ""
                state["texts"].append(txt)
                log("  " + re.sub(r"\s+", " ", txt)[:300])
                bump(txt)
        if ev.get("error"):
            state["errors"].append(ev["error"])
            log("  ! " + ev["error"][:300])
        bump("")

    try:
        rc = _pump(proc, on_line, idle_check=lambda: bump(""), stdin_text=prompt)
    except Cancelled:
        _update(out_dir, fid, status="dibatalkan")
        raise
    if state["buf"].strip():
        state["texts"].append(state["buf"].strip())
    final = "\n".join(state["texts"][-3:])
    runs = list(f.get("runs") or []) + [{"at": time.strftime("%Y-%m-%d %H:%M:%S"), "revision": revision[:500],
                                         "minutes": round((time.time() - t0) / 60, 1), "cost_usd": 0, "agent": agent,
                                         "ok": rc == 0}]
    m = re.search(r"FILM=(.+\.mp4)", final)
    mp4 = Path(m.group(1).strip().strip("`")) if m else None
    expected = pdir / f"{f['name']}.mp4"
    if mp4 and mp4.is_file() and mp4.resolve() != expected.resolve() and mp4.resolve().is_relative_to(cwd.resolve()):
        shutil.copy2(mp4, expected)
    info = _files(out_dir, f)
    ok = bool(info.get("video")) and rc == 0
    _update(out_dir, fid, status="selesai" if ok else "gagal", runs=runs, summary=final[-1500:], agent=agent)
    if not ok:
        why = final[-600:] or "\n".join(state["errors"][-6:]) or f"kode keluar {rc}"
        try:
            tail = transcript.read_text(encoding="utf-8", errors="replace")[-6000:]
        except OSError:
            tail = ""
        if re.search(r"not running in a trusted directory|folder is not trusted", tail + why, re.I):
            raise ClipAgentError(
                f"{name} menolak bekerja karena folder film belum dipercaya. Buka terminal di folder {cwd}, jalankan "
                f"`{agent}`, pilih Trust folder, keluar dengan /quit, lalu klik Coba lagi.")
        if re.search(r"\b429\b|RESOURCE_EXHAUSTED|quota|rate.?limit|usage limit|too many requests", tail + why, re.I):
            raise ClipAgentError(
                f"Kuota {name} habis atau terlalu banyak permintaan (HTTP 429). Pekerjaan yang sudah jadi tetap tersimpan di "
                f"folder proyek; klik Coba lagi setelah kuotanya pulih (batas per menit pulih dalam beberapa menit, batas "
                f"harian keesokan harinya) dan agen akan melanjutkannya. Atau ganti agen di Pengaturan agen.")
        if not info.get("video"):
            raise ClipAgentError(f"{name} selesai tanpa file film. Pesan terakhirnya:\n{why}")
        raise ClipAgentError(f"{name} berhenti dengan galat:\n{why}")
    log(f"Film siap: {info['video']}")
    progress(1.0, "Film siap")
    return {"film": fid, "video": info["video"], "video_url": info.get("video_url"), "cost_usd": 0}


def all_film_videos(out_dir: Path) -> list[dict]:
    out = []
    for f in list_films(out_dir):
        if not f.get("video"):
            continue
        p = out_dir / f["video"]
        if not p.is_file():
            continue
        out.append({"path": f["video"], "group": "Film (Lemo-Opuscar)", "label": f"{f['topic'][:60]} · {f['style_name']}",
                    "title": f["topic"][:100], "description": "", "hashtags": [], "ai": True, "mtime": p.stat().st_mtime,
                    "url": f"/files/{f['video']}"})
    return out
