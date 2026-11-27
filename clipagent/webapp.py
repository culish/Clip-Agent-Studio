"""Web app lokal untuk Clip Agent (hanya pustaka standar Python, tanpa dependensi tambahan).

Jalankan dengan: python app.py  → buka http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import mimetypes
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import fields
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .config import ANIMATIONS, FONTS, PROJECT_DIR, PROVIDERS, Settings
from .download import is_url, youtube_id
from .pipeline import run_pipeline
from .remote import COOKIE, Remote, blocked_page, login_page, welcome_page
from .utils import Cancelled, ClipAgentError, clear_context, set_context, slugify

WEB_DIR = PROJECT_DIR / "web"
ENV_PATH = PROJECT_DIR / ".env"
KEY_VARS = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
            "YOUTUBE_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY"]
PLAIN_VARS = ["LLM_PROVIDER", "LLM_MODEL", "LLM_FALLBACK_MODELS", "LLM_BASE_URL", "COOKIES_FROM_BROWSER",
              "IMAGE_MODEL", "TTS_MODEL", "VIDEO_MODEL"]
CREATIVE_KINDS = ("covers", "storyboard", "preview", "styles_preview", "animate", "autoedit", "relayout",
                  "retime", "framecheck", "trim_ai", "loudnorm")
APK_PATH = PROJECT_DIR / "android" / "ClipAgent.apk"
LOOPBACK = ("127.", "::1", "::ffff:127.")

CHOICES = {
    "audience": ["us", "id"], "sub_lang": ["auto", "en", "id"], "anim": list(ANIMATIONS),
    "font": list(FONTS), "position": ["lower", "middle", "upper"], "zoom": ["none", "punch"],
    "aspect": ["9:16", "1:1", "4:5", "original"], "crop": ["face", "center", "blur"],
    "layout": ["auto", "stream", "reaction", "pip", "duo"],
    "whisper_model": ["tiny", "base", "small", "medium", "large-v3"],
}
_TYPES = {f.name: f.type for f in fields(Settings)}
ALLOWED = ["source", "num_clips", "min_dur", "max_dur", "instructions", "audience", "sub_lang", "language",
           "anim", "font", "uppercase", "text_color", "highlight_color", "words_per_line", "position",
           "hook_overlay", "progress_bar", "zoom", "aspect", "crop", "layout", "split", "subtitles", "provider", "model",
           "whisper_model", "max_height", "plan_only", "force_whisper"]


# ====================================================================== job
class Job:
    def __init__(self, options: dict):
        self.id = uuid.uuid4().hex[:10]
        self.options = options
        self.status = "queued"          # queued | running | done | error | canceled
        self.stage = "Menunggu giliran"
        self.progress = 0.0
        self.logs: list[str] = []
        self.error = ""
        self.result: dict | None = None
        self.created = time.time()
        self.finished = 0.0
        self.cancel = threading.Event()

    def add_log(self, msg: str) -> None:
        for line in str(msg).splitlines() or [""]:
            self.logs.append(f"{time.strftime('%H:%M:%S')}  {line}")

    def set_progress(self, frac: float, stage: str | None) -> None:
        self.progress = max(self.progress, frac)
        if stage:
            self.stage = stage

    def to_dict(self, since: int | None = None) -> dict:
        d = {"id": self.id, "kind": self.options.get("kind", "clip"), "status": self.status, "stage": self.stage,
             "progress": round(self.progress, 4), "error": self.error, "created": self.created,
             "finished": self.finished, "source": self.options.get("source", ""),
             "title": (self.result or {}).get("title", "") or self.options.get("label", ""),
             "options": self.options}
        if since is not None:
            d["logs"] = self.logs[since:]
            d["log_count"] = len(self.logs)
            d["result"] = self.result
        return d


class JobManager:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[Job] = queue.Queue()
        self.q_long: queue.Queue[Job] = queue.Queue()     # film agen (30–60 menit) punya antrean sendiri
        threading.Thread(target=self._worker, daemon=True, name="clip-worker").start()
        threading.Thread(target=self._worker, args=(self.q_long,), daemon=True, name="film-worker").start()

    LONG_KINDS = ("film_setup", "film_make", "film_revise")

    def submit(self, options: dict) -> Job:
        job = Job(options)
        self.jobs[job.id] = job
        (self.q_long if options.get("kind") in self.LONG_KINDS else self.q).put(job)
        return job

    def list(self) -> list[dict]:
        return [j.to_dict() for j in sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)][:30]

    def _worker(self, q: "queue.Queue[Job] | None" = None) -> None:
        q = q or self.q
        while True:
            job = q.get()
            if job.cancel.is_set():
                job.status, job.stage = "canceled", "Dibatalkan"
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        job.status, job.stage = "running", "Memulai"
        set_context(job.add_log, job.set_progress, job.cancel)
        try:
            kind = job.options.get("kind", "clip")
            if kind in CREATIVE_KINDS:
                job.result = run_creative(kind, job.options, self.out_dir)
                job.status, job.stage, job.progress = "done", "Selesai", 1.0
                return
            from .studio_api import STUDIO_KINDS, run_job
            if kind in STUDIO_KINDS:
                job.result = run_job(kind, job.options, self.out_dir)
                job.status, job.stage, job.progress = "done", "Selesai", 1.0
                return
            cfg = build_settings(job.options, self.out_dir)
            result = run_pipeline(cfg)
            for c in result.get("clips", []):
                if c.get("file"):
                    c["video_url"] = f"/files/{result['video_id']}/clips/{c['file']}"
                    c["srt_url"] = c["video_url"][:-4] + ".srt"
            job.result = result
            job.status, job.stage, job.progress = "done", "Selesai", 1.0
        except Cancelled:
            job.status, job.stage = "canceled", "Dibatalkan"
            job.add_log("Proses dibatalkan.")
        except (ClipAgentError, ValueError) as exc:
            job.status, job.error = "error", str(exc)
            job.add_log(f"Error: {exc}")
        except Exception as exc:  # bug tak terduga: tampilkan agar mudah dilaporkan
            job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
            job.add_log(traceback.format_exc())
        finally:
            job.finished = time.time()
            clear_context()


def creative_ctx(opts: dict, out_dir: Path):
    from .creative import load_context
    vid = str(opts.get("video_id") or "")
    if not re.fullmatch(r"[\w-]{1,80}", vid):
        raise ValueError("Pilih klip dulu.")
    try:
        rank = int(opts.get("rank"))
    except (TypeError, ValueError):
        raise ValueError("Nomor klip tidak valid.")
    return load_context(out_dir, vid, rank)


def run_creative(kind: str, opts: dict, out_dir: Path) -> dict:
    ctx = creative_ctx(opts, out_dir)
    base = {"kind": kind, "video_id": ctx.video_id, "rank": ctx.rank, "title": ctx.clip.get("title", "")}
    if kind == "covers":
        from .covers import generate_covers
        meta = generate_covers(ctx, opts)
        return {**base, "count": len(meta["covers"])}
    if kind == "storyboard":
        from .creative import build_storyboards
        sb = build_storyboards(ctx)
        return {**base, "options": [{"id": o["id"], "scenes": len(o["scenes"])} for o in sb["options"]]}
    if kind == "autoedit":
        from .autoedit import auto_edit
        return {**base, **auto_edit(ctx, anim_opts(opts))}
    if kind == "relayout":
        from .creative import relayout_clip
        return {**base, **relayout_clip(ctx, {"layout": opts.get("layout")})}
    if kind in ("retime", "framecheck", "trim_ai", "loudnorm"):
        from . import trim
        if kind == "retime":
            return {**base, **trim.retime_clip(ctx, {k: opts.get(k) for k in ("start", "end", "check")})}
        if kind == "trim_ai":
            return {**base, **trim.suggest_ai(ctx, {k: opts[k] for k in ("start", "end") if k in opts})}
        if kind == "loudnorm":
            return {**base, **trim.normalize_audio(ctx)}
        return {**base, "check": trim.frame_check(ctx)}
    from .animation import preview_frames, preview_styles, render_animation
    opts = anim_opts(opts)
    if kind == "preview":
        return {**base, **preview_frames(ctx, opts)}
    if kind == "styles_preview":
        return {**base, **preview_styles(ctx, opts)}
    return {**base, **render_animation(ctx, opts)}


def anim_opts(opts: dict) -> dict:
    """Ambil hanya pilihan animasi yang dikenal dari body permintaan."""
    out = {k: opts[k] for k in ("scenes", "preset", "custom", "broll", "count", "music", "music_volume") if k in opts}
    if opts.get("sub_lang") in CHOICES["sub_lang"]:
        out["sub_lang"] = opts["sub_lang"]
    for k in ("subtitles", "hook_overlay", "progress_bar", "allow_ai"):
        if k in opts:
            out[k] = bool(opts[k])
    return out


def build_settings(opts: dict, out_dir: Path) -> Settings:
    data: dict = {}
    for key in ALLOWED:
        if key not in opts or opts[key] is None:
            continue
        val, typ = opts[key], str(_TYPES.get(key, "str"))
        try:
            if typ == "bool":
                val = val if isinstance(val, bool) else str(val).lower() in ("1", "true", "on", "yes")
            elif typ == "int":
                val = int(float(val))
            elif typ == "float":
                val = float(val)
            else:
                val = str(val).strip()
        except (TypeError, ValueError):
            raise ValueError(f"Nilai '{key}' tidak valid: {val!r}")
        if key in CHOICES and val not in CHOICES[key]:
            raise ValueError(f"Pilihan '{key}' tidak dikenal: {val}")
        data[key] = val
    if not data.get("source"):
        raise ValueError("Tempel link YouTube atau path file video dulu.")
    if not (0 < data.get("min_dur", 20) <= data.get("max_dur", 60)):
        raise ValueError("Durasi minimal harus > 0 dan tidak lebih besar dari durasi maksimal.")
    data["num_clips"] = max(1, min(15, data.get("num_clips", 5)))
    cfg = Settings(out_dir=out_dir, cookies_from_browser=os.getenv("COOKIES_FROM_BROWSER", ""), **data)
    if opts.get("reuse_plan"):
        plan = find_plan(out_dir, cfg.source)
        if not plan:
            raise ValueError("Belum ada rencana klip untuk video ini; buat klip dulu sekali.")
        cfg.plan_file = str(plan)
    if isinstance(opts.get("plan"), list) and opts["plan"]:
        target = out_dir / "_plans" / f"plan_{uuid.uuid4().hex[:8]}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"clips": opts["plan"]}, ensure_ascii=False), encoding="utf-8")
        cfg.plan_file = str(target)
    cfg.resolve()
    return cfg


def video_key(source: str) -> str | None:
    if is_url(source):
        return youtube_id(source)
    return slugify(Path(source).stem, 50) if source else None


def find_plan(out_dir: Path, source: str) -> Path | None:
    key = video_key(source)
    p = out_dir / key / "plan.json" if key else None
    return p if p and p.is_file() else None


# ====================================================================== data lain
def library(out_dir: Path) -> list[dict]:
    items = []
    for plan_path in out_dir.glob("*/plan.json"):
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        vid = plan_path.parent.name
        clips = []
        for c in plan.get("clips", []):
            f = c.get("file")
            if f and (plan_path.parent / "clips" / f).is_file():
                url = f"/files/{vid}/clips/{f}"
                clips.append({**c, "video_url": url, "srt_url": url[:-4] + ".srt"})
        if clips:
            src = plan.get("source", {})
            src_file = next((f"source{e}" for e in (".mp4", ".webm", ".mov", ".mkv")
                             if (plan_path.parent / f"source{e}").is_file()), "")
            items.append({"video_id": vid, "title": src.get("title", vid), "url": src.get("url", ""),
                          "channel": src.get("channel", ""), "license": src.get("license", ""),
                          "render": plan.get("render", {}), "updated": plan_path.stat().st_mtime,
                          "source_file": f"/files/{vid}/{src_file}" if src_file else "",
                          "is_url": is_url(src.get("url", "")), "clips": clips})
    return sorted(items, key=lambda x: x["updated"], reverse=True)


def system_check() -> dict:
    def version(cmd):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
            return (out.splitlines() or [""])[0][:80]
        except Exception:
            return ""
    checks = []
    ff = shutil.which("ffmpeg")
    checks.append({"name": "ffmpeg", "ok": bool(ff), "detail": version(["ffmpeg", "-version"]) if ff else
                   "Belum terpasang. Windows: winget install Gyan.FFmpeg"})
    deno = shutil.which("deno")
    checks.append({"name": "Deno (dibutuhkan yt-dlp untuk YouTube)", "ok": bool(deno),
                   "detail": version(["deno", "--version"]) if deno else "Windows: winget install DenoLand.Deno"})
    try:
        import yt_dlp
        checks.append({"name": "yt-dlp", "ok": True, "detail": yt_dlp.version.__version__})
    except ImportError:
        checks.append({"name": "yt-dlp", "ok": False, "detail": "pip install -r requirements.txt"})
    try:
        import cv2
        checks.append({"name": "OpenCV (pelacakan wajah)", "ok": True, "detail": cv2.__version__})
    except ImportError:
        checks.append({"name": "OpenCV (pelacakan wajah)", "ok": False, "detail": "pip install -r requirements.txt"})
    import importlib.util
    if importlib.util.find_spec("faster_whisper"):
        checks.append({"name": "Whisper (video tanpa subtitle)", "ok": True, "detail": "terpasang"})
    else:
        checks.append({"name": "Whisper (video tanpa subtitle)", "ok": None,
                       "detail": "Opsional: pip install -r requirements-whisper.txt (Python 3.10–3.14)"})
    from .animation import remotion_status
    rm = remotion_status()
    checks.append({"name": "Node.js + Remotion (animasi, edit otomatis, buat video)", "ok": rm["ready"],
                   "detail": version(["node", "--version"]) + ", Remotion terpasang" if rm["ready"] else rm["hint"]})
    if importlib.util.find_spec("edge_tts"):
        checks.append({"name": "Suara gratis Edge (edge-tts)", "ok": True, "detail": "terpasang"})
    else:
        checks.append({"name": "Suara gratis Edge (edge-tts)", "ok": None,
                       "detail": "Opsional bila tanpa Gemini API key: pip install edge-tts"})
    checks.append({"name": "Python", "ok": True, "detail": f"{platform.python_version()} ({sys.platform})"})
    return {"checks": checks}


def read_settings() -> dict:
    keys = {}
    for k in KEY_VARS:
        v = os.getenv(k, "")
        keys[k] = ("••••" + v[-4:]) if len(v) > 8 else ("terisi" if v else "")
    provider = (os.getenv("LLM_PROVIDER") or "gemini").lower()
    preset = PROVIDERS.get(provider, PROVIDERS["gemini"])
    return {"provider": provider, "model": os.getenv("LLM_MODEL", ""), "default_model": preset["model"],
            "fallbacks": os.getenv("LLM_FALLBACK_MODELS", ""),
            "default_fallbacks": ",".join(preset.get("fallbacks", [])),
            "base_url": os.getenv("LLM_BASE_URL", ""), "cookies_from_browser": os.getenv("COOKIES_FROM_BROWSER", ""),
            "image_model": os.getenv("IMAGE_MODEL", ""), "tts_model": os.getenv("TTS_MODEL", ""),
            "video_model": os.getenv("VIDEO_MODEL", ""), "image_ready": bool(os.getenv("IMAGE_API_KEY") or os.getenv("GEMINI_API_KEY")),
            "keys": keys, "providers": {k: {"key_env": v["key_env"], "model": v["model"]} for k, v in PROVIDERS.items()}}


def save_settings(data: dict) -> None:
    updates = {}
    for k in PLAIN_VARS:
        if k in data:
            updates[k] = str(data[k] or "").strip()
    for k in KEY_VARS:
        v = str(data.get(k) or "").strip()
        if v:                                # kosong = tidak diubah
            updates[k] = v
    save_env(updates)


def save_env(updates: dict) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.is_file() else []
    seen = set()
    for i, line in enumerate(lines):
        m = re.match(r"\s*(?:export\s+)?([A-Z_]+)\s*=", line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            seen.add(m.group(1))
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in updates.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def llm_test() -> dict:
    from .llm import LLMClient
    cfg = Settings(source="-")
    cfg.resolve_llm()
    if cfg.provider == "heuristic":
        return {"ok": True, "message": "Mode heuristic tidak memakai AI."}
    client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)
    t0 = time.time()
    data = client.complete_json("Answer only with JSON.", 'Reply with {"ok": true}.', attempts_per_model=1)
    return {"ok": bool(data.get("ok", True)), "model": client.model,
            "message": f"Terhubung ke {cfg.provider}/{client.model} ({time.time() - t0:.1f} dtk)."}


def open_folder(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ====================================================================== HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "ClipAgent/2.0"
    manager: JobManager
    out_dir: Path
    remote: Remote
    port: int = 8765

    def log_message(self, fmt, *args):  # tenangkan log akses
        pass

    # ---------------- akses & keamanan
    @property
    def is_local(self) -> bool:
        return self.client_address[0].startswith(LOOPBACK)

    @property
    def is_app(self) -> bool:
        return "ClipAgentApp" in (self.headers.get("User-Agent") or "")

    def _host_ok(self) -> bool:
        """Tolak Host asing (melindungi dari serangan DNS rebinding lewat browser)."""
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return True
        name = host[1:host.index("]")] if host.startswith("[") else host.rsplit(":", 1)[0]
        allowed = {"127.0.0.1", "localhost", "::1"}
        if self.remote.enabled and self.remote.ip:
            allowed.add(self.remote.ip)
        return name.lower() in allowed

    def _token(self) -> str:
        tok = self.headers.get("X-ClipAgent-Token") or ""
        if not tok:
            try:
                c = SimpleCookie(self.headers.get("Cookie") or "")
                tok = c[COOKIE].value if COOKIE in c else ""
            except Exception:
                tok = ""
        return tok

    def _authorized(self) -> bool:
        return self.is_local or (self.remote.enabled and self.remote.check(self._token()))

    def _html(self, body: bytes, status: int = 200, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _gate(self, path: str) -> bool:
        """True bila permintaan boleh lanjut; jika tidak, respons sudah dikirim."""
        if not self._host_ok():
            self._html(b"Host tidak diizinkan.", 403)
            return False
        if path == "/connect" or path.startswith("/fonts/") or self._authorized():
            return True
        if path.startswith(("/api/", "/files/", "/app/")):
            self._json({"error": "Butuh kode akses. Buka /connect di HP.", "auth": True}, 401)
        else:
            self._html(login_page(next_path=path if path.startswith("/") else "/"), 401)
        return False

    def _connect(self, params: dict) -> None:
        get = lambda k: (params.get(k) or [""])[0]  # noqa: E731
        nxt = get("next") or "/"
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        if self.is_local:
            return self._redirect(nxt)
        ip = self.client_address[0]
        if self.remote.blocked(ip):
            return self._html(blocked_page(), 429)
        code = get("code")
        if not code:
            return self._html(login_page(next_path=nxt), 200)
        if not self.remote.check(code):
            self.remote.record_fail(ip)
            return self._html(login_page("Kode akses salah. Periksa lagi di laptop.", nxt), 401)
        self.remote.clear_fail(ip)
        cookie = f"{COOKIE}={self.remote.code}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"
        if get("welcome") and not self.is_app:
            return self._html(welcome_page(self.remote, APK_PATH.is_file()), 200, {"Set-Cookie": cookie})
        self._redirect(nxt, {"Set-Cookie": cookie})

    def _redirect(self, location: str, headers: dict | None = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _lan_status(self) -> dict:
        r = self.remote
        d = {"enabled": r.enabled, "url": r.base_url, "local": self.is_local, "app": self.is_app,
             "apk": APK_PATH.is_file()}
        if self.is_local:
            d.update({"code": r.code if r.enabled else "", "server": r.server_addr,
                      "connect_url": r.connect_url(), "qr_svg": r.qr_svg()})
        return d

    # ---------------- helpers
    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, msg: str, status: int = 400) -> None:
        self._json({"error": msg}, status)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Body bukan JSON yang valid.")
        return data if isinstance(data, dict) else {}

    def _file(self, path: Path, root: Path) -> None:
        try:
            path = path.resolve()
            path.relative_to(root.resolve())
        except (ValueError, OSError):
            return self._error("Tidak ditemukan", 404)
        if not path.is_file():
            return self._error("Tidak ditemukan", 404)
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in (".srt", ".md", ".ass"):
            ctype = "text/plain; charset=utf-8"
        elif path.suffix == ".apk":
            ctype = "application/vnd.android.package-archive"
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if "download" in parse_qs(urlparse(self.path).query) or path.suffix == ".apk":
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        try:
            with path.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    # ---------------- routes
    def do_GET(self):
        url = urlparse(self.path)
        p, qs = unquote(url.path), parse_qs(url.query)
        self._qs = qs
        q = lambda k, d="": (qs.get(k) or [d])[0]  # noqa: E731
        if not self._gate(p):
            return
        try:
            if p == "/connect":
                return self._connect(qs)
            if p == "/app/ClipAgent.apk":
                return self._file(APK_PATH, APK_PATH.parent)
            if p == "/api/lan":
                return self._json(self._lan_status())
            if p in ("/", "/index.html"):
                return self._file(WEB_DIR / "index.html", WEB_DIR)
            if p.startswith("/web/"):
                return self._file(WEB_DIR / p[5:], WEB_DIR)
            if p.startswith("/fonts/"):
                return self._file(PROJECT_DIR / "fonts" / p[7:], PROJECT_DIR / "fonts")
            if p.startswith("/files/"):
                return self._file(self.out_dir / p[7:], self.out_dir)
            if p == "/api/meta":
                from .stylize import STYLES
                return self._json({"animations": ANIMATIONS, "fonts": list(FONTS), "choices": CHOICES,
                                   "styles": {k: v[0] for k, v in STYLES.items()},
                                   "client": {"local": self.is_local, "app": self.is_app},
                                   "defaults": {f.name: f.default for f in fields(Settings)
                                                if f.name in ALLOWED and not callable(f.default)}})
            if p == "/api/system":
                return self._json(system_check())
            if p == "/api/settings":
                return self._json(read_settings())
            if p == "/api/jobs":
                return self._json({"jobs": self.manager.list()})
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)", p)
            if m:
                job = self.manager.jobs.get(m.group(1))
                return self._json(job.to_dict(int(q("since", "0") or 0))) if job else self._error("Job tidak ada", 404)
            if p == "/api/creative":
                from .creative import creative_state
                return self._json(creative_state(creative_ctx({"video_id": q("video"), "rank": q("rank")},
                                                              self.out_dir)))
            if p == "/api/creative/frame":
                from .creative import thumb
                ctx = creative_ctx({"video_id": q("video"), "rank": q("rank")}, self.out_dir)
                return self._file(thumb(ctx, float(q("t", "0") or 0)), self.out_dir)
            if p == "/api/library":
                return self._json({"items": library(self.out_dir)})
            if p == "/api/trends":
                from .trends import fetch_trends
                geo = q("geo", "US")
                return self._json({"geo": geo, "items": fetch_trends(geo)})
            if p == "/api/niches":
                from .trends import niche_catalog
                return self._json({"items": niche_catalog()})
            if p == "/api/search":
                from .trends import search_youtube
                query = q("q").strip()
                if not query:
                    return self._error("Isi kata kunci pencarian.")
                return self._json(search_youtube(
                    query, cc=q("cc", "1") == "1", period=q("period", "month"), length=q("length", "long"),
                    sort=q("sort", "views"), limit=min(24, int(q("limit", "12") or 12)),
                    cookies_from_browser=os.getenv("COOKIES_FROM_BROWSER", "")))
            from .studio_api import handle_get
            if handle_get(self, p, q):
                return
            return self._error("Tidak ditemukan", 404)
        except ValueError as exc:
            return self._error(str(exc), 400)
        except ClipAgentError as exc:
            return self._error(str(exc), 502)
        except Exception as exc:
            traceback.print_exc()
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    def _same_origin(self) -> bool:
        """POST dari halaman lain (situs web, atau kode animasi yang berjalan di browser render) ditolak.
        Browser selalu mengirim Origin pada POST lintas asal; permintaan tanpa Origin (alat CLI) tetap boleh."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return urlparse(origin).netloc.lower() == (self.headers.get("Host") or "").strip().lower()

    def do_POST(self):
        p = urlparse(self.path).path
        if not self._same_origin():
            return self._html(b"Permintaan dari situs lain ditolak.", 403)
        if not self._gate(p):
            return
        if p == "/connect":
            n = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(n).decode("utf-8", "replace")) if n else {}
            return self._connect(form)
        try:
            body = self._body()
            if p == "/api/lan":
                if not self.is_local:
                    return self._error("Hanya bisa diubah dari laptop.", 403)
                if body.get("regenerate"):
                    self.remote.regenerate()
                    save_env({"LAN_ACCESS_CODE": self.remote.code})
                if "enabled" in body:
                    if body["enabled"]:
                        self.remote.start(Handler, self.port)
                        save_env({"LAN_ENABLED": "1", "LAN_ACCESS_CODE": self.remote.code})
                    else:
                        self.remote.stop()
                        save_env({"LAN_ENABLED": "0"})
                return self._json(self._lan_status())
            if p == "/api/jobs":
                from .studio_api import STUDIO_KINDS, validate_job
                if body.get("kind", "clip") in CREATIVE_KINDS:
                    ctx = creative_ctx(body, self.out_dir)   # validasi dulu agar error langsung terlihat
                    body["label"] = ctx.clip.get("title", "")
                    if body["kind"] == "retime":
                        from .trim import validate
                        validate(ctx, body)
                    if body["kind"] == "autoedit":
                        from .animation import remotion_status
                        if not remotion_status()["ready"]:
                            raise ValueError(remotion_status()["hint"])
                    if body["kind"] in ("preview", "styles_preview", "animate"):
                        from .animation import normalize_scenes, remotion_status
                        st = remotion_status()
                        if not st["ready"]:
                            raise ValueError(st["hint"])
                        normalize_scenes(body.get("scenes"), ctx.duration)
                elif body.get("kind") in STUDIO_KINDS:
                    validate_job(body, self.out_dir)
                else:
                    build_settings(body, self.out_dir)       # validasi dulu agar error langsung terlihat
                job = self.manager.submit(body)
                return self._json(job.to_dict(0), 201)
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/cancel", p)
            if m:
                job = self.manager.jobs.get(m.group(1))
                if not job:
                    return self._error("Job tidak ada", 404)
                job.cancel.set()
                if job.status == "queued":
                    job.status, job.stage = "canceled", "Dibatalkan"
                return self._json(job.to_dict())
            if p == "/api/ideas":
                from .trends import fetch_trends, heuristic_ideas, recommend_ideas
                geo = str(body.get("geo") or "US")
                try:
                    trends = fetch_trends(geo)
                except ClipAgentError:
                    trends = []
                cfg = Settings(source="-")
                cfg.resolve_llm()
                n = max(3, min(12, int(body.get("n") or 8)))
                ideas, source = recommend_ideas(cfg, trends, geo, n) if trends or cfg.provider != "heuristic" \
                    else (heuristic_ideas([], n), "aturan")
                return self._json({"ideas": ideas, "source": source, "trend_count": len(trends)})
            if p == "/api/settings":
                save_settings(body)
                return self._json(read_settings())
            if p == "/api/llm-test":
                return self._json(llm_test())
            if p == "/api/open-folder":
                if not self.is_local:
                    return self._error("Folder hanya bisa dibuka dari laptop.", 403)
                vid = str(body.get("video_id") or "")
                folder = (self.out_dir / vid / "clips") if vid else self.out_dir
                if not re.fullmatch(r"[\w-]*", vid) or not folder.is_dir():
                    return self._error("Folder tidak ditemukan", 404)
                open_folder(folder)
                return self._json({"ok": True})
            from .studio_api import handle_post
            if handle_post(self, p, body):
                return
            return self._error("Tidak ditemukan", 404)
        except ValueError as exc:
            return self._error(str(exc), 400)
        except ClipAgentError as exc:
            return self._error(str(exc), 502)
        except Exception as exc:
            traceback.print_exc()
            return self._error(f"{type(exc).__name__}: {exc}", 500)


def serve(host: str = "127.0.0.1", port: int = 8765, out_dir: str | Path = "output",
          open_browser: bool = True) -> None:
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    Handler.manager = JobManager(out)
    Handler.out_dir = out
    Handler.remote = Remote()
    from .publish import PostQueue
    Handler.posts = PostQueue(out)
    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"Port {port}–{port + 9} sedang dipakai. Pakai --port lain.")
    httpd.daemon_threads = True
    Handler.port = port
    url = f"http://{host}:{port}"
    print(f"\n  Clip Agent berjalan di {url}\n  Folder hasil: {out}", flush=True)
    if os.getenv("LAN_ENABLED") == "1":
        try:
            Handler.remote.start(Handler, port)
            print(f"  Akses dari HP: {Handler.remote.base_url}  (kode: {Handler.remote.code})", flush=True)
        except ClipAgentError as exc:
            print(f"  Akses dari HP belum aktif: {exc}", flush=True)
    print("  Tekan Ctrl+C untuk berhenti.\n", flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")
    finally:
        Handler.remote.stop()
        httpd.server_close()
