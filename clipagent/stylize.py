"""Gaya kartun lokal (OpenCV, gratis, tanpa internet) untuk cover, storyboard, dan video.

Palet warna dihitung sekali dari beberapa frame lalu dipakai untuk semua frame,
sehingga warna tidak berkedip dari frame ke frame.
"""
from __future__ import annotations

import cv2
import numpy as np

# id -> (nama tampilan, keterangan)
STYLES = {
    "anime": ("Anime", "Warna rata dan cerah dengan garis tipis, seperti serial kartun TV"),
    "komik": ("Komik", "Garis hitam tebal dan warna terbatas, seperti halaman buku komik"),
    "poster": ("Pop poster", "Sedikit warna, kontras tinggi, garis tegas"),
    "sketsa": ("Sketsa pensil", "Goresan pensil di atas kertas dengan sedikit warna"),
    "catair": ("Cat air", "Sapuan warna lembut tanpa garis keras"),
}

_PALETTE_K = {"anime": 14, "komik": 12, "poster": 6}
# Lebar proses: video dibuat lebih kecil agar cepat, lalu diperbesar kembali.
_VIDEO_WIDTH = {"catair": 360}
_STILL_WIDTH = {"catair": 720}
_INK = np.array([38, 28, 34], np.uint8)          # warna garis (BGR), sedikit ungu gelap


def _saturate(img: np.ndarray, factor: float, value: float = 1.0) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * factor, 0, 255)
    if value != 1.0:
        hsv[..., 2] = np.clip(hsv[..., 2] * value, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _fit_palette(images: list[np.ndarray], k: int) -> np.ndarray:
    px = np.concatenate([im.reshape(-1, 3) for im in images]).astype(np.float32)
    if len(px) > 40000:
        idx = np.random.default_rng(7).choice(len(px), 40000, replace=False)
        px = px[idx]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0)
    _, _, centers = cv2.kmeans(px, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    return centers.astype(np.float32)


def _quantize(img: np.ndarray, palette: np.ndarray) -> np.ndarray:
    flat = img.reshape(-1, 3).astype(np.float32)
    d = (flat * flat).sum(1, keepdims=True) - 2.0 * flat @ palette.T + (palette * palette).sum(1)[None, :]
    return palette[d.argmin(1)].astype(np.uint8).reshape(img.shape)


class Stylizer:
    """Ubah gambar BGR menjadi gaya kartun. Panggil `fit()` dengan beberapa frame contoh dulu."""

    def __init__(self, style: str, still: bool = False):
        if style not in STYLES:
            raise ValueError(f"Gaya kartun '{style}' tidak dikenal. Pilihan: {', '.join(STYLES)}")
        self.style = style
        self.proc_width = (_STILL_WIDTH if still else _VIDEO_WIDTH).get(style, 1080 if still else 540)
        self.palette: np.ndarray | None = None

    # ---------------- persiapan
    def _small(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        if w <= self.proc_width:
            return img
        return cv2.resize(img, (self.proc_width, round(h * self.proc_width / w)), interpolation=cv2.INTER_AREA)

    def _pre(self, small: np.ndarray) -> np.ndarray:
        if self.style == "anime":
            s = cv2.edgePreservingFilter(small, flags=1, sigma_s=50, sigma_r=0.4)
            return _saturate(s, 1.3, 1.04)
        if self.style == "komik":
            s = cv2.bilateralFilter(small, 7, 60, 7)
            return _saturate(cv2.bilateralFilter(s, 7, 60, 7), 1.15)
        if self.style == "poster":
            return _saturate(cv2.bilateralFilter(small, 9, 80, 9), 1.5, 1.05)
        return small

    def fit(self, samples: list[np.ndarray]) -> "Stylizer":
        k = _PALETTE_K.get(self.style)
        if k and samples:
            pre = [self._pre(self._small(s)) for s in samples[:8]]
            self.palette = _fit_palette(pre, k)
        return self

    # ---------------- gaya
    def __call__(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        small = self._small(img)
        if _PALETTE_K.get(self.style) and self.palette is None:
            self.fit([img])
        out = getattr(self, f"_{self.style}")(small)
        if out.shape[:2] != (h, w):
            out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
        return out

    def _anime(self, small):
        s = self._pre(small)
        q = cv2.medianBlur(_quantize(s, self.palette), 3)
        # sisakan sedikit bayangan asli agar wajah tidak rata sepenuhnya
        q = cv2.addWeighted(q, 0.78, s, 0.22, 0)
        edges = cv2.Canny(cv2.cvtColor(s, cv2.COLOR_BGR2GRAY), 60, 140)
        edges = cv2.dilate(edges, np.ones((2, 2), np.uint8))
        q[edges > 0] = _INK
        return q

    def _komik(self, small):
        s = self._pre(small)
        q = _quantize(s, self.palette)
        gray = cv2.medianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), 5)
        lines = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 4)
        q[lines == 0] = (18, 14, 16)
        return q

    def _poster(self, small):
        s = self._pre(small)
        q = cv2.medianBlur(_quantize(s, self.palette), 5)
        gray = cv2.GaussianBlur(cv2.cvtColor(s, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        edges = cv2.dilate(cv2.Canny(gray, 50, 120), np.ones((3, 3), np.uint8))
        q[edges > 0] = (10, 10, 12)
        return q

    def _sketsa(self, small):
        gray, color = cv2.pencilSketch(small, sigma_s=50, sigma_r=0.08, shade_factor=0.04)
        paper = np.array([228, 238, 245], np.float32)           # kertas krem (BGR)
        strokes = (gray.astype(np.float32) / 255.0) ** 2.2      # pertegas goresan pensil
        sketch = strokes[..., None] * paper
        out = 0.82 * sketch + 0.18 * color.astype(np.float32)
        return np.clip(out, 0, 255).astype(np.uint8)

    def _catair(self, small):
        s = cv2.stylization(small, sigma_s=60, sigma_r=0.45)
        s = _saturate(s, 1.1, 1.06)
        return cv2.addWeighted(s, 0.9, np.full_like(s, 250), 0.1, 0)


def stylize_image(img: np.ndarray, style: str, samples: list[np.ndarray] | None = None) -> np.ndarray:
    """Satu gambar diam (cover, keyframe storyboard) dengan kualitas penuh."""
    st = Stylizer(style, still=True)
    st.fit(samples or [img])
    return st(img)
