"""Gambar kartun buatan AI (opsional) lewat Gemini image ("Nano Banana") — generateContent REST.

Dipakai bila ada API key (IMAGE_API_KEY atau GEMINI_API_KEY). Bila gagal (kuota, model tidak
tersedia, atau ditolak filter keamanan), pemanggil kembali ke gaya kartun lokal.
"""
from __future__ import annotations

import base64
import os
import time

import cv2
import numpy as np
import requests

from .utils import ClipAgentError, check_cancel

DEFAULT_MODEL = "gemini-3.1-flash-lite-image"     # Nano Banana 2 Lite: paling cepat & murah
DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"

STYLE_PROMPTS = {
    "anime": "a clean 2D anime-style cel-shaded illustration with flat bright colors and thin dark outlines",
    "komik": "a bold comic-book illustration with thick black ink outlines and flat limited colors",
    "poster": "a pop-art poster illustration with very few bold colors and strong graphic outlines",
    "sketsa": "a hand-drawn pencil sketch on cream paper with a light color wash",
    "catair": "a soft watercolor painting with gentle color washes and no hard outlines",
}


class ImageGen:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE, timeout: int = 120):
        self.api_key, self.model, self.base_url, self.timeout = api_key, model, base_url.rstrip("/"), timeout

    @classmethod
    def from_env(cls) -> "ImageGen | None":
        key = os.getenv("IMAGE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
        if not key:
            return None
        return cls(key, os.getenv("IMAGE_MODEL") or DEFAULT_MODEL, os.getenv("IMAGE_BASE_URL") or DEFAULT_BASE)

    def redraw(self, frame_bgr: np.ndarray, style: str, scene: str = "", aspect: str = "9:16") -> np.ndarray:
        """Gambar ulang satu frame dalam gaya kartun. Mengembalikan gambar BGR."""
        look = STYLE_PROMPTS.get(style, STYLE_PROMPTS["anime"])
        prompt = (f"Redraw this video frame as {look}. Keep the same composition, camera angle, people, "
                  f"poses, clothing and facial expressions so it lines up with the original scene. "
                  + (f"Scene: {scene.strip()}. " if scene.strip() else "")
                  + f"Aspect ratio {aspect}. No text, no captions, no logos, no watermarks.")
        return self._request([{"text": prompt}, _part(frame_bgr)], aspect)

    def generate(self, prompt: str, aspect: str = "9:16", refs: list[np.ndarray] | None = None) -> np.ndarray:
        """Gambar baru dari teks. `refs` = gambar referensi karakter agar wajah/pakaian konsisten."""
        parts = [{"text": prompt}]
        for img in (refs or [])[:3]:
            parts.append(_part(img))
        return self._request(parts, aspect)

    def _request(self, parts: list[dict], aspect: str) -> np.ndarray:
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}},
        }
        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        last = ""
        for attempt in range(3):
            check_cancel()
            try:
                r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as exc:
                last = f"koneksi gagal ({type(exc).__name__})"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code} (sibuk/kuota)"
                time.sleep(6 * (attempt + 1))
                continue
            if not r.ok:
                raise ClipAgentError(f"Model gambar menolak permintaan (HTTP {r.status_code}): {r.text[:200]}")
            img = _decode(r.json())
            if img is None:
                raise ClipAgentError("Model gambar tidak mengembalikan gambar (kemungkinan ditolak filter keamanan).")
            return img
        raise ClipAgentError(f"Model gambar tidak tersedia: {last}")


def _part(img: np.ndarray) -> dict:
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ClipAgentError("Gagal menyiapkan gambar untuk AI.")
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpg.tobytes()).decode()}}


def _decode(data: dict) -> np.ndarray | None:
    for cand in data.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                raw = np.frombuffer(base64.b64decode(blob["data"]), np.uint8)
                img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
    return None
