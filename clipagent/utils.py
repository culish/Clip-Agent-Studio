"""Fungsi bantu umum: logging, progres, pembatalan, menjalankan perintah, ffprobe, parsing JSON."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import unicodedata
from pathlib import Path


class ClipAgentError(Exception):
    """Error yang pesannya aman ditampilkan langsung ke pengguna."""


class Cancelled(ClipAgentError):
    """Proses dihentikan oleh pengguna."""


# ---------------------------------------------------------------- konteks per thread
# Web app menjalankan tiap job di thread sendiri; log/progres/pembatalan diarahkan ke job itu.
_ctx = threading.local()


def set_context(log_fn=None, progress_fn=None, cancel_event: threading.Event | None = None) -> None:
    _ctx.log_fn, _ctx.progress_fn, _ctx.cancel_event = log_fn, progress_fn, cancel_event


def clear_context() -> None:
    set_context(None, None, None)


def log(msg: str) -> None:
    print(f"[clip-agent] {msg}", flush=True)
    fn = getattr(_ctx, "log_fn", None)
    if fn:
        fn(msg)


def progress(frac: float, stage: str | None = None) -> None:
    """Laporkan progres keseluruhan 0..1 (dipakai web app; CLI mengabaikannya)."""
    fn = getattr(_ctx, "progress_fn", None)
    if fn:
        fn(max(0.0, min(1.0, frac)), stage)


def check_cancel() -> None:
    ev = getattr(_ctx, "cancel_event", None)
    if ev is not None and ev.is_set():
        raise Cancelled("Dibatalkan oleh pengguna.")


def run(cmd: list, cwd: str | Path | None = None, on_seconds=None) -> subprocess.CompletedProcess:
    """Jalankan perintah; bisa dibatalkan. Untuk ffmpeg dengan `-progress pipe:1`,
    `on_seconds(detik)` dipanggil berkala. Jika gagal, tampilkan potongan akhir stderr."""
    check_cancel()
    args = [str(c) for c in cmd]
    proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    err: list[str] = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    out_lines: list[str] = []
    cancel_ev = getattr(_ctx, "cancel_event", None)
    for line in proc.stdout:
        out_lines.append(line)
        if on_seconds and line.startswith("out_time_us="):
            try:
                on_seconds(int(line.split("=", 1)[1]) / 1_000_000)
            except ValueError:
                pass
        if cancel_ev is not None and cancel_ev.is_set():
            proc.kill()
            proc.wait()
            raise Cancelled("Dibatalkan oleh pengguna.")
    proc.wait()
    reader.join(timeout=5)
    stderr = "".join(err)
    if cancel_ev is not None and cancel_ev.is_set():
        raise Cancelled("Dibatalkan oleh pengguna.")
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-12:])
        raise ClipAgentError(f"Perintah '{Path(args[0]).name}' gagal:\n{tail}")
    return subprocess.CompletedProcess(args, proc.returncode, "".join(out_lines), stderr)


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise ClipAgentError(
            f"Program '{name}' tidak ditemukan di PATH. Install ffmpeg dulu (lihat README)."
        )


def probe(path: str | Path) -> dict:
    """Ambil durasi, resolusi, fps, dan ada/tidaknya audio dari file video."""
    proc = run(["ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", str(path)])
    data = json.loads(proc.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if v is None:
        raise ClipAgentError(f"Tidak ada stream video di {path}")
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    num, _, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    if not fps or fps > 240:
        fps = 30.0
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    width, height = int(v["width"]), int(v["height"])
    # Video ponsel kadang disimpan dengan metadata rotasi 90°.
    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = abs(int(float(sd["rotation"])))
    if rotation in (90, 270):
        width, height = height, width
    return {"duration": duration, "width": width, "height": height,
            "fps": fps, "has_audio": has_audio}


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-")) or "klip"


def fmt_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def extract_json(text: str) -> dict:
    """Ambil objek JSON dari jawaban LLM (toleran terhadap ```json ... ``` dan teks tambahan)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ClipAgentError("Jawaban LLM bukan JSON yang valid:\n" + text[:500])
