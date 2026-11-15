"""Character Studio: karakter AI yang konsisten di semua video.

Setiap karakter punya nama, persona, deskripsi penampilan, gaya gambar, suara, dan satu gambar referensi
(diunggah atau dibuat AI). Gambar referensi ikut dikirim ke model gambar setiap kali adegan dibuat,
sehingga wajah, rambut, dan pakaian tetap sama dari video ke video.
Disimpan di <output>/_characters/<id>/.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from .gemini import QuotaError
from .imagegen import ImageGen
from .utils import ClipAgentError, check_cancel, log, progress

ART_STYLES = {
    "kartun3d": ("Kartun 3D", "a friendly stylized 3D animated character with soft studio lighting and smooth shading"),
    "anime": ("Anime", "a clean 2D anime character with cel shading, flat bright colors and thin outlines"),
    "flat": ("Ilustrasi flat", "a clean flat vector illustration character with simple shapes and a limited palette"),
    "komik": ("Komik", "a bold comic-book character with thick ink outlines and flat colors"),
    "realistis": ("Lukisan realistis", "a realistic digital painting of a fictional person with cinematic lighting"),
    "chibi": ("Chibi lucu", "a cute chibi character with a big head, small body and expressive eyes"),
}


def _root(out_dir: Path) -> Path:
    d = out_dir / "_characters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dir(out_dir: Path, cid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{8,16}", cid or ""):
        raise ClipAgentError("ID karakter tidak valid.")
    return _root(out_dir) / cid


def _url(out_dir: Path, p: Path) -> str:
    rel = p.resolve().relative_to(out_dir.resolve()).as_posix()
    return f"/files/{rel}?v={int(p.stat().st_mtime)}"


def get(out_dir: Path, cid: str) -> dict:
    p = _dir(out_dir, cid) / "character.json"
    if not p.is_file():
        raise ClipAgentError("Karakter tidak ditemukan.")
    return json.loads(p.read_text(encoding="utf-8"))


def public(out_dir: Path, ch: dict) -> dict:
    d = _dir(out_dir, ch["id"])
    ref = d / "ref.png"
    cands = sorted(d.glob("cand_*.png"))
    return {**ch, "ref_url": _url(out_dir, ref) if ref.is_file() else "",
            "candidates": [{"file": c.name, "url": _url(out_dir, c)} for c in cands],
            "art_label": ART_STYLES.get(ch.get("art"), ("", ""))[0]}


def list_all(out_dir: Path) -> list[dict]:
    out = []
    for p in _root(out_dir).glob("*/character.json"):
        try:
            out.append(public(out_dir, json.loads(p.read_text(encoding="utf-8"))))
        except (ValueError, OSError, ClipAgentError):
            continue
    return sorted(out, key=lambda c: c.get("created", ""), reverse=True)


def save(out_dir: Path, data: dict) -> dict:
    cid = data.get("id") or uuid.uuid4().hex[:10]
    d = _dir(out_dir, cid)
    d.mkdir(parents=True, exist_ok=True)
    old = get(out_dir, cid) if (d / "character.json").is_file() else {"created": time.strftime("%Y-%m-%d %H:%M:%S")}
    ch = {**old, "id": cid}
    for k, n in (("name", 40), ("persona", 300), ("look", 500), ("voice", 60), ("voice_engine", 10), ("style", 120)):
        if k in data:
            ch[k] = str(data[k] or "").strip()[:n]
    if data.get("art") in ART_STYLES:
        ch["art"] = data["art"]
    ch.setdefault("art", "kartun3d")
    if not ch.get("name"):
        raise ClipAgentError("Beri nama karakter.")
    (d / "character.json").write_text(json.dumps(ch, ensure_ascii=False, indent=2), encoding="utf-8")
    return public(out_dir, ch)


def delete(out_dir: Path, cid: str) -> None:
    shutil.rmtree(_dir(out_dir, cid), ignore_errors=True)


def set_reference_upload(out_dir: Path, cid: str, data_url: str) -> dict:
    """Simpan gambar referensi dari unggahan (data URL base64)."""
    ch = get(out_dir, cid)
    m = re.match(r"data:image/[\w.+-]+;base64,(.+)", data_url or "", re.S)
    if not m:
        raise ClipAgentError("File gambar tidak valid.")
    raw = base64.b64decode(m.group(1))
    if len(raw) > 12_000_000:
        raise ClipAgentError("Gambar terlalu besar (maks. 12 MB).")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ClipAgentError("Gambar tidak bisa dibaca. Pakai JPG atau PNG.")
    _write_ref(_dir(out_dir, cid) / "ref.png", img)
    return public(out_dir, ch)


def choose_candidate(out_dir: Path, cid: str, file: str) -> dict:
    ch = get(out_dir, cid)
    d = _dir(out_dir, cid)
    if not re.fullmatch(r"cand_\d+_\d+\.png", file or "") or not (d / file).is_file():
        raise ClipAgentError("Pilihan gambar tidak ditemukan.")
    shutil.copyfile(d / file, d / "ref.png")
    return public(out_dir, ch)


def _write_ref(path: Path, img: np.ndarray) -> None:
    h, w = img.shape[:2]
    sc = min(1.0, 1024 / max(h, w))
    if sc < 1:
        img = cv2.resize(img, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img)


def sheet_prompt(ch: dict) -> str:
    art = ART_STYLES.get(ch.get("art"), ART_STYLES["kartun3d"])[1]
    return (f"Character design reference of an original fictional character named {ch['name']}: {ch.get('look') or 'a friendly host'}. "
            f"Style: {art}. Full body, front view, standing, neutral friendly pose, plain light grey background, "
            "even lighting, the whole character visible. No text, no logos, no watermark.")


def generate_candidates(out_dir: Path, cid: str, n: int = 3) -> dict:
    ch = get(out_dir, cid)
    gen = ImageGen.from_env()
    if gen is None:
        raise ClipAgentError("Membuat gambar karakter butuh GEMINI_API_KEY (isi di Pengaturan), atau unggah gambar sendiri.")
    d = _dir(out_dir, cid)
    for old in d.glob("cand_*.png"):
        old.unlink()
    stamp = int(time.time())
    made = 0
    for i in range(n):
        check_cancel()
        progress(0.1 + 0.85 * i / n, f"Membuat gambar karakter {i + 1}/{n}")
        try:
            img = gen.generate(sheet_prompt(ch) + f" Variation {i + 1}.", "3:4")
        except QuotaError as exc:
            raise ClipAgentError(f"{exc} Atau unggah gambar karakter sendiri (tombol Unggah gambar).") from exc
        except ClipAgentError as exc:
            log(f"  Gambar {i + 1} gagal: {str(exc)[:160]}")
            continue
        _write_ref(d / f"cand_{stamp}_{i}.png", img)
        made += 1
    if not made:
        raise ClipAgentError("AI gagal membuat gambar karakter. Coba lagi atau unggah gambar sendiri.")
    progress(1.0, "Gambar karakter siap")
    return public(out_dir, ch)


def references(out_dir: Path, cid: str) -> list[np.ndarray]:
    if not cid:
        return []
    p = _dir(out_dir, cid) / "ref.png"
    img = cv2.imread(str(p)) if p.is_file() else None
    return [img] if img is not None else []


def scene_prompt(ch: dict | None, scene_prompt_text: str, art_override: str = "") -> str:
    """Prompt gambar adegan. Bila ada karakter, minta model mempertahankan wujudnya dari gambar referensi."""
    if not ch:
        art = ART_STYLES.get(art_override, ART_STYLES["kartun3d"])[1]
        return (f"{scene_prompt_text.strip()}. Style: {art}. Vertical composition with the main subject in the "
                "middle third. No text, no captions, no logos, no watermarks.")
    art = ART_STYLES.get(ch.get("art"), ART_STYLES["kartun3d"])[1]
    return (f"Use the exact same character shown in the reference image ({ch['name']}: {ch.get('look', '')}). "
            "Keep the face, hair, body shape, outfit and colors identical. "
            f"Scene: {scene_prompt_text.strip()}. Style: {art}. The character is clearly visible in the middle "
            "third of the frame. No text, no captions, no logos, no watermarks.")
