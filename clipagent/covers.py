"""Generator cover/thumbnail: pilih frame terbaik, tulis teks cover, buat versi 9:16 dan 16:9.

Hasil per klip (folder creative/<rank>/covers):
- 9:16 1080x1920 untuk Shorts/Reels/TikTok
- 16:9 1280x720 untuk thumbnail YouTube (di bawah 2 MB)
Varian: tiga frame berbeda (foto asli), satu versi kartun, dan opsional satu versi AI.
"""
from __future__ import annotations

import json
import re
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import PROJECT_DIR
from .creative import ClipContext
from .imagegen import ImageGen
from .llm import LLMClient
from .render import _load_face_detector
from .stylize import STYLES, stylize_image
from .utils import Cancelled, ClipAgentError, check_cancel, log, progress

COVER_FONTS = {"Anton": "Anton-Regular.ttf", "Montserrat Black": "Montserrat-Black.ttf",
               "Bebas Neue": "BebasNeue-Regular.ttf", "Poppins": "Poppins-Bold.ttf"}

TEXT_SYSTEM = "You write thumbnail text for short-form videos. Answer ONLY with valid JSON."
TEXT_PROMPT = """Clip title: {title}
Hook: {hook}
What is said: {text}

Write 3 different thumbnail texts in {lang}: 2-5 words each, punchy and curiosity-driven, true to what is said.
No hashtags, no emoji, no quotation marks. For each, pick ONE word from it to highlight.
JSON: {{"texts": [{{"text": "...", "highlight": "..."}}]}}"""


# ---------------------------------------------------------------- teks
def _auto_highlight(text: str) -> str:
    words = [re.sub(r"[^\w$%]", "", w) for w in text.split()]
    words = [w for w in words if w]
    if not words:
        return ""
    for w in words:
        if re.search(r"[\d$%]", w):
            return w
    return max(words, key=len)


def cover_texts(ctx: ClipContext) -> list[dict]:
    title = ctx.clip.get("title") or ""
    fallback = [{"text": " ".join(title.split()[:5]) or "Watch this", "highlight": ""}]
    try:
        cfg = ctx.settings()
    except ValueError:
        return fallback
    if cfg.provider == "heuristic":
        return fallback
    spoken = " ".join(w.text for w in ctx.words if ctx.start <= w.start < ctx.end)[:1500]
    try:
        client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)
        data = client.complete_json(TEXT_SYSTEM, TEXT_PROMPT.format(
            title=title, hook=ctx.clip.get("hook", ""), text=spoken or "-", lang=cfg.output_language))
    except ClipAgentError as exc:
        log(f"Teks cover AI tidak tersedia ({str(exc).splitlines()[0]}); memakai judul klip.")
        return fallback
    out = []
    for item in data.get("texts", []):
        t = str((item or {}).get("text") or "").strip().strip('"')
        if t:
            out.append({"text": t[:60], "highlight": str(item.get("highlight") or "").strip()})
    return out[:3] or fallback


# ---------------------------------------------------------------- frame
def pick_frames(ctx: ClipContext, n: int = 3, samples: int = 24) -> list[dict]:
    det = _load_face_detector()
    cap = cv2.VideoCapture(str(ctx.video))
    lo, hi = ctx.start + 0.3, max(ctx.start + 0.4, ctx.end - 0.3)
    cands = []
    for t in np.linspace(lo, hi, samples):
        check_cancel()
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        sc = min(1.0, 640 / w)
        small = cv2.resize(frame, (int(w * sc), int(h * sc))) if sc < 1 else frame
        sharp = float(cv2.Laplacian(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        face, conf, area = None, 0.0, 0.0
        if det is not None:
            det.setInputSize((small.shape[1], small.shape[0]))
            _, faces = det.detect(small)
            if faces is not None and len(faces):
                f = max(faces, key=lambda f: float(f[2] * f[3]))
                face = tuple(float(v) / sc for v in f[:4])
                conf = float(f[14])
                area = float(f[2] * f[3]) / (small.shape[0] * small.shape[1])
        bright = float(small.mean()) / 255
        cands.append({"t": float(t), "frame": frame, "face": face, "sharp": sharp, "conf": conf,
                      "area": area, "bright": bright})
    cap.release()
    if not cands:
        raise ClipAgentError("Tidak bisa membaca frame dari video sumber.")
    ms = max(c["sharp"] for c in cands) or 1.0
    ma = max(c["area"] for c in cands) or 1.0
    for c in cands:
        c["score"] = (0.45 * c["sharp"] / ms + 0.4 * c["area"] / ma + 0.15 * c["conf"]
                      - 0.5 * max(0.0, 0.18 - c["bright"]) - 0.5 * max(0.0, c["bright"] - 0.85))
    picked: list[dict] = []
    for c in sorted(cands, key=lambda c: c["score"], reverse=True):
        if all(abs(c["t"] - p["t"]) >= 1.5 for p in picked):
            picked.append(c)
        if len(picked) >= n:
            break
    return picked


def crop_aspect(frame: np.ndarray, face, aw: int, ah: int, zoom: float = 1.0, fx_pos: float = 0.5) -> np.ndarray:
    """Potong ke rasio aw:ah. `fx_pos` = posisi horizontal wajah di hasil (0.68 = sepertiga kanan)."""
    H, W = frame.shape[:2]
    r = aw / ah
    cw, ch = (H * r, H) if W / H > r else (W, W / r)
    cw, ch = cw / zoom, ch / zoom
    if face:
        fx, fy = face[0] + face[2] / 2, face[1] + face[3] / 2
    else:
        fx, fy, fx_pos = W / 2, H / 2, 0.5
    cy_target = fy + ch * 0.12                       # wajah sedikit di atas tengah
    x0 = int(min(max(fx - cw * fx_pos, 0), W - cw))
    y0 = int(min(max(cy_target - ch / 2, 0), H - ch))
    return frame[y0:y0 + int(ch), x0:x0 + int(cw)]


def _punch(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.15, 0, 255)
    out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return cv2.convertScaleAbs(out, alpha=1.08, beta=4)


# ---------------------------------------------------------------- komposisi
def _contrast(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
    return (17, 17, 17) if lum > 0.55 else (255, 255, 255)


def _hex(c: str) -> tuple[int, int, int]:
    c = (c or "#FFE24A").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        c = "FFE24A"
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def compose(img_bgr: np.ndarray, text: str, highlight: str, W: int, H: int, vertical: bool,
            accent: str = "#FFE24A", font: str = "Anton") -> Image.Image:
    base = cv2.resize(img_bgr, (W, H), interpolation=cv2.INTER_AREA if img_bgr.shape[1] > W else cv2.INTER_CUBIC)
    im = Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB)).convert("RGBA")

    # Bayangan gelap di belakang teks supaya terbaca di atas gambar apa pun.
    if vertical:
        ramp = np.clip((np.linspace(0, 1, H) - 0.4) / 0.6, 0, 1) ** 1.3 * 200
        alpha = np.repeat(ramp[:, None], W, axis=1)
    else:
        ramp = np.clip(1 - np.linspace(0, 1, W) / 0.68, 0, 1) ** 1.2 * 205
        alpha = np.repeat(ramp[None, :], H, axis=0)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shade.putalpha(Image.fromarray(alpha.astype(np.uint8)))
    im = Image.alpha_composite(im, shade)

    words = text.upper().split()
    hl = re.sub(r"[^\w$%]", "", (highlight or _auto_highlight(text)).upper())
    path = str(PROJECT_DIR / "fonts" / COVER_FONTS.get(font, "Anton-Regular.ttf"))
    max_w = W * (0.86 if vertical else 0.56)
    size = int(H * (0.085 if vertical else 0.16))
    while True:
        f = ImageFont.truetype(path, size)
        space = f.getlength(" ")
        lines, cur, cur_w = [], [], 0.0
        for w in words:
            ww = f.getlength(w)
            if cur and cur_w + space + ww > max_w:
                lines.append(cur)
                cur, cur_w = [w], ww
            else:
                cur_w = cur_w + (space if cur else 0) + ww
                cur.append(w)
        if cur:
            lines.append(cur)
        widest = max((sum(f.getlength(w) for w in ln) + space * (len(ln) - 1)) for ln in lines) if lines else 0
        if (len(lines) <= 3 and widest <= max_w) or size <= 40:
            break
        size = int(size * 0.94)

    draw = ImageDraw.Draw(im)
    acc = _hex(accent)
    line_h = size * 1.08
    block_h = line_h * len(lines)
    y = (H * 0.80 - block_h) if vertical else (H - block_h) / 2
    stroke = max(4, int(size * 0.07))
    pad = size * 0.12
    for ln in lines:
        lw = sum(f.getlength(w) for w in ln) + space * (len(ln) - 1)
        x = (W - lw) / 2 if vertical else W * 0.06
        for w in ln:
            ww = f.getlength(w)
            if hl and re.sub(r"[^\w$%]", "", w) == hl:
                top, bottom = f.getbbox(w)[1], f.getbbox(w)[3]
                draw.rounded_rectangle([x - pad, y + top - pad, x + ww + pad, y + bottom + pad],
                                       radius=int(size * 0.14), fill=acc + (255,))
                draw.text((x, y), w, font=f, fill=_contrast(acc))
            else:
                draw.text((x, y), w, font=f, fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0))
            x += ww + space
        y += line_h
    return im.convert("RGB")


# ---------------------------------------------------------------- utama
def generate_covers(ctx: ClipContext, opts: dict) -> dict:
    style = opts.get("style") if opts.get("style") in STYLES else "anime"
    font = opts.get("font") if opts.get("font") in COVER_FONTS else "Anton"
    accent = opts.get("accent") or "#FFE24A"
    progress(0.05, "Memilih frame terbaik")
    frames = pick_frames(ctx, 3)
    log(f"Frame terpilih: {', '.join(f'{f["t"] - ctx.start:.1f}s' for f in frames)}")

    progress(0.25, "Menulis teks cover")
    user_text = str(opts.get("text") or "").strip()
    texts = [{"text": user_text, "highlight": ""}] if user_text else cover_texts(ctx)

    variants = []
    for k in range(min(3, len(frames))):
        variants.append({"look": "asli", "label": "Foto asli", "frame": frames[k], "text": texts[k % len(texts)]})
    variants.append({"look": style, "label": f"Kartun {STYLES[style][0]}", "frame": frames[0], "text": texts[0]})
    gen = ImageGen.from_env() if opts.get("ai") else None
    if opts.get("ai") and gen is None:
        log("Cover AI butuh GEMINI_API_KEY (atau IMAGE_API_KEY); dilewati.")
    if gen is not None:
        variants.append({"look": "ai", "label": f"AI {STYLES[style][0]}", "frame": frames[0], "text": texts[0]})

    cdir = ctx.cdir / "covers"
    cdir.mkdir(parents=True, exist_ok=True)
    for old in cdir.glob("cover_*.jpg"):
        old.unlink()
    stamp = time.strftime("%H%M%S")
    results = []
    for i, v in enumerate(variants):
        check_cancel()
        progress(0.3 + 0.65 * i / len(variants), f"Membuat cover {i + 1}/{len(variants)}")
        fr = v["frame"]
        item = {"id": i, "look": v["look"], "label": v["label"], "text": v["text"]["text"],
                "time": round(fr["t"] - ctx.start, 2)}
        ok = True
        for tag, (W, H, vertical) in {"v": (1080, 1920, True), "h": (1280, 720, False)}.items():
            img = crop_aspect(fr["frame"], fr["face"], 9 if vertical else 16, 16 if vertical else 9,
                              zoom=1.0 if vertical else 1.3, fx_pos=0.5 if vertical else 0.7)
            if v["look"] == "asli":
                img = _punch(img)
            elif v["look"] == "ai":
                try:
                    img = gen.redraw(img, style, ctx.clip.get("title", ""), "9:16" if vertical else "16:9")
                except Cancelled:
                    raise
                except ClipAgentError as exc:
                    log(f"Cover AI gagal ({str(exc)[:120]}); varian AI dilewati.")
                    ok = False
                    break
            else:
                img = stylize_image(img, v["look"])
            out = compose(img, v["text"]["text"], v["text"].get("highlight", ""), W, H, vertical, accent, font)
            name = f"cover_{i}_{tag}_{stamp}.jpg"
            q = 90
            out.save(cdir / name, quality=q, optimize=True)
            while (cdir / name).stat().st_size > 1_900_000 and q > 60:     # batas thumbnail YouTube 2 MB
                q -= 8
                out.save(cdir / name, quality=q, optimize=True)
            item[tag] = name
        if ok:
            results.append(item)
    meta = {"covers": results, "style": style, "font": font, "accent": accent,
            "clip_range": [round(ctx.start, 2), round(ctx.end, 2)],
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    (cdir / "covers.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    progress(1.0, "Cover siap")
    log(f"{len(results)} cover dibuat.")
    return meta
