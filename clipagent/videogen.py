"""Video AI per adegan lewat Gemini Omni Flash (Interactions API). Opsional dan berbayar.

Gambar adegan (yang sudah memuat karakter) dipakai sebagai frame awal (image_to_video), sehingga
karakter tetap konsisten. Audio bawaan video AI dibuang karena narasi dibuat terpisah.
Perkiraan harga: sekitar US$0,10 per detik video 720p (lihat ai.google.dev/gemini-api/docs/pricing).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .gemini import api_key, with_fallbacks
from .utils import ClipAgentError, log

PRICE_PER_SECOND = 0.10
EST_SECONDS = 8


def video_models() -> list[str]:
    return [os.getenv("VIDEO_MODEL") or "gemini-omni-1.1-flash"]


def available() -> bool:
    return bool(api_key())


def generate_clip(prompt: str, image: np.ndarray | None, aspect: str, cache_dir: Path,
                  resolution: str = "720p") -> Path:
    """Buat satu klip video AI (di-cache berdasarkan prompt + gambar)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    jpg = b""
    if image is not None:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        jpg = buf.tobytes() if ok else b""
    key = hashlib.sha1(prompt.encode() + jpg + aspect.encode() + resolution.encode()).hexdigest()[:14]
    out = cache_dir / f"aivid_{key}.mp4"
    if out.is_file():
        return out
    import base64

    text = (f"{prompt.strip()}. Smooth cinematic camera motion, natural movement, keep the same character, "
            "no on-screen text, no captions, no logos, no watermarks.")

    def body(model):
        parts = []
        if jpg:
            parts.append({"type": "image", "data": base64.b64encode(jpg).decode(), "mime_type": "image/jpeg"})
        parts.append({"type": "text", "text": text})
        return {"model": model, "input": parts,
                "response_format": {"type": "video", "aspect_ratio": "9:16" if aspect == "9:16" else "16:9",
                                    "resolution": resolution},
                "generation_config": {"video_config": {"task": "image_to_video" if jpg else "text_to_video"}}}

    log("  Membuat video AI (bisa 1–3 menit per adegan)...")
    data, _, model = with_fallbacks(video_models(), body, "video", timeout=900)
    out.write_bytes(data)
    log(f"  Video AI siap ({model}).")
    return out


def fit_clip(src: Path, dur: float, width: int, height: int, dst: Path) -> Path:
    """Sesuaikan klip (stok/AI) ke ukuran & durasi adegan: crop isi layar, 30 fps, tanpa audio, diulang bila pendek."""
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
          f"fps=30,format=yuv420p")
    cmd = ["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(src), "-t", f"{dur + 0.5:.2f}",
           "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dst.is_file():
        raise ClipAgentError(f"Gagal menyiapkan klip video: {r.stderr[-300:]}")
    return dst
