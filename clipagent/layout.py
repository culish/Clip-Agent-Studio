"""Layout klip untuk konten streaming, reaction, dan podcast (seperti pilihan layout di Opus Clip).

- stream   : facecam di atas, gameplay/layar di bawah (layar terbagi).
- reaction : video yang ditonton di atas (utuh selebar layar), wajah orang yang bereaksi di bawah.
- pip      : video utama memenuhi layar, facecam kecil di pojok atas.
- duo      : dua orang (podcast/wawancara) ditumpuk atas-bawah.
- auto     : satu layar seperti biasa (ikuti pengaturan Pembingkaian).

Wajah dicari otomatis di beberapa frame klip (YuNet). Wajah yang posisinya tetap di banyak frame dianggap
facecam, sehingga wajah karakter game yang muncul sesekali tidak ikut terpilih. Semua kotak bisa diubah
pengguna (koordinat 0..1 relatif ke frame sumber) dan disimpan per klip di plan.json.
"""
from __future__ import annotations

import statistics
from pathlib import Path

from .utils import log

MODES = {
    "auto": "Satu layar (ikuti Pembingkaian)",
    "stream": "Streaming/gameplay: facecam atas, game bawah",
    "reaction": "Reaction: video atas, wajah bawah",
    "pip": "Facecam kecil di pojok",
    "duo": "Podcast 2 orang: atas dan bawah",
}
DEFAULT_SPLIT = {"stream": 0.38, "reaction": 0.0, "duo": 0.5, "pip": 0.0}   # porsi tinggi panel wajah; 0 = otomatis
FIT = ("cover", "contain")


def _even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def _fe(x: float) -> int:
    """Bilangan genap ke bawah (ukuran crop tidak boleh melewati batas frame)."""
    return max(2, int(x) // 2 * 2)


# ---------------------------------------------------------------- deteksi wajah
def sample_faces(video: Path, start: float, end: float, n: int = 14, grays: list | None = None
                 ) -> tuple[list[list[tuple]], int, int]:
    """Kotak wajah (x, y, w, h, skor) di n frame yang tersebar merata di klip, dalam piksel sumber.
    Bila `grays` diberikan, frame abu-abu lebar 640 px ikut dikumpulkan (untuk mencari tepi facecam)."""
    import cv2

    from .render import _load_face_detector
    det = _load_face_detector()
    cap = cv2.VideoCapture(str(video))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    frames: list[list[tuple]] = []
    if det is None or not cap.isOpened():
        cap.release()
        return frames, W, H
    dur = max(0.5, end - start)
    size_set = None
    for i in range(n):
        t = start + dur * (i + 0.5) / n
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        W, H = w, h
        if grays is not None:
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            grays.append(cv2.resize(g, (640, max(2, int(h * 640 / w))), interpolation=cv2.INTER_AREA))
        scale = min(1.0, 960.0 / w)
        sw, sh = int(w * scale), int(h * scale)
        small = cv2.resize(frame, (sw, sh)) if scale < 1 else frame
        if size_set != (sw, sh):
            det.setInputSize((sw, sh))
            size_set = (sw, sh)
        _, faces = det.detect(small)
        boxes = []
        for f in faces if faces is not None else []:
            if float(f[14]) < 0.6:
                continue
            boxes.append((float(f[0]) / scale, float(f[1]) / scale, float(f[2]) / scale, float(f[3]) / scale, float(f[14])))
        frames.append(boxes)
    cap.release()
    return frames, W, H


def face_clusters(frames: list[list[tuple]]) -> list[dict]:
    """Kelompokkan wajah berdasarkan posisi. Wajah facecam muncul di tempat yang sama di banyak frame."""
    clusters: list[dict] = []
    for fi, boxes in enumerate(frames):
        for (x, y, w, h, s) in boxes:
            cx, cy = x + w / 2, y + h / 2
            best = None
            for c in clusters:
                if fi in c["frames"]:
                    continue
                mx, my, mw = c["cx"], c["cy"], c["w"]
                if abs(cx - mx) < mw * 0.9 and abs(cy - my) < mw * 0.9 and 0.5 < w / mw < 2:
                    best = c
                    break
            if best is None:
                best = {"items": [], "frames": set()}
                clusters.append(best)
            best["items"].append((x, y, w, h))
            best["frames"].add(fi)
            best["cx"] = statistics.median(i[0] + i[2] / 2 for i in best["items"])
            best["cy"] = statistics.median(i[1] + i[3] / 2 for i in best["items"])
            best["w"] = statistics.median(i[2] for i in best["items"])
    out = []
    for c in clusters:
        w = statistics.median(i[2] for i in c["items"])
        h = statistics.median(i[3] for i in c["items"])
        out.append({"box": (c["cx"] - w / 2, c["cy"] - h / 2, w, h), "count": len(c["frames"])})
    return sorted(out, key=lambda c: (c["count"], c["box"][2]), reverse=True)


def camera_box(grays: list, face: tuple, W: int, H: int) -> tuple | None:
    """Cari kotak overlay facecam di sekitar wajah dari garis lurus yang menetap di semua frame
    (tepi gameplay berubah-ubah; batas overlay kamera tidak). None bila tidak ada kotak yang jelas."""
    import cv2
    import numpy as np
    if len(grays) < 4:
        return None
    gh, gw = grays[0].shape[:2]
    k = gw / W
    gx = np.median(np.stack([np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) for g in grays]), axis=0)
    gy = np.median(np.stack([np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) for g in grays]), axis=0)
    fx, fy, fw, fh = [v * k for v in face]
    cx, cy = fx + fw / 2, fy + fh / 2
    y0, y1 = int(max(0, fy - fh * 0.2)), int(min(gh, fy + fh * 1.2))
    x0, x1 = int(max(0, fx - fw * 0.2)), int(min(gw, fx + fw * 1.2))
    colp = gx[y0:y1].mean(axis=0)                # kekuatan garis tegak per kolom (setinggi wajah)
    rowp = gy[:, x0:x1].mean(axis=1)             # kekuatan garis datar per baris (selebar wajah)
    lim_x, lim_y = fw * 4.5, fh * 3.5
    span = {"y": (int(max(0, cy - fh * 0.5)), int(min(gh, cy + fh))),      # rentang yang pasti di dalam facecam
            "x": (int(max(0, cx - fw * 0.6)), int(min(gw, cx + fw * 0.6)))}

    def straight(img, line, vertical) -> float:
        """Porsi garis yang kuat sepanjang sisi (garis bingkai menerus, tepi objek biasanya tidak)."""
        a, b = span["y"] if vertical else span["x"]
        band = img[a:b, max(0, line - 1):line + 2] if vertical else img[max(0, line - 1):line + 2, a:b]
        strong = band.max(axis=1 if vertical else 0)
        return float((strong > max(12.0, float(strong.max()) * 0.3)).mean()) if strong.size else 0.0

    def pick(profile, img, lo, hi, vertical):
        lo, hi = int(max(0, lo)), int(min(len(profile), hi))
        if hi - lo < 2:
            return None
        thr = max(25.0, (float(np.median(profile)) + 1.0) * 6)
        cands = [i for i in range(lo, hi) if profile[i] > thr and profile[i] >= profile[max(lo, i - 2):i + 3].max()]
        scored = [(float(profile[i]) * straight(img, i, vertical), i) for i in cands]
        scored = [c for c in scored if c[0] > 0 and straight(img, c[1], vertical) >= 0.7]
        if not scored:
            return None
        # garis kuat yang paling dekat ke wajah: kalau keliru, hasilnya sedikit lebih sempit (aman),
        # bukan ikut memotong gameplay di luar facecam
        best = max(c[0] for c in scored)
        near = [c for c in scored if c[0] >= best * 0.35]
        mid = (lo + hi) / 2
        face_side = hi if lo < mid and (vertical and lo < cx or not vertical and lo < cy) else lo
        return min(near, key=lambda c: abs(c[1] - face_side))[1]

    # garis datar dulu (diukur selebar wajah), lalu garis tegak diukur di antara keduanya
    top = pick(rowp, gy, cy - lim_y, cy - fh * 0.35, False)
    bottom = pick(rowp, gy, cy + fh * 0.45, cy + lim_y, False)
    # overlay yang menempel ke sisi layar: tepi frame jadi batasnya
    top = top if top is not None else (0 if cy - lim_y <= 0 else None)
    bottom = bottom if bottom is not None else (gh - 1 if cy + lim_y >= gh else None)
    if top is not None and bottom is not None:
        span["y"] = (top + 3, max(top + 4, bottom - 3))
    left = pick(colp, gx, cx - lim_x, cx - fw * 0.45, True)
    right = pick(colp, gx, cx + fw * 0.45, cx + lim_x, True)
    left = left if left is not None else (0 if cx - lim_x <= 0 else None)
    right = right if right is not None else (gw - 1 if cx + lim_x >= gw else None)
    if None in (left, right, top, bottom) or right - left < fw * 1.4 or bottom - top < fh * 1.4:
        return None
    pad = 3                                            # lewati garis bingkai
    x, y = (left + pad) / k, (top + pad) / k
    w, h = (right - left - 2 * pad) / k, (bottom - top - 2 * pad) / k
    if w * h > W * H * 0.6:
        return None
    return (x, y, w, h)


def fit_inside(region: tuple, cam: tuple, face: tuple) -> tuple:
    """Kecilkan area (rasio tetap) agar tidak keluar dari kotak facecam, tetap memuat wajah."""
    x, y, w, h = region
    cx0, cy0, cw, ch = cam
    s = min(1.0, cw / w, ch / h)
    w, h = w * s, h * s
    fx, fy, fw, fh = face
    nx = min(max(fx + fw / 2 - w / 2, cx0), cx0 + cw - w)
    ny = min(max(fy + fh / 2 - h * 0.42, cy0), cy0 + ch - h)
    return (nx, ny, w, h)


def detect(video: Path, start: float, end: float) -> dict:
    grays: list = []
    frames, W, H = sample_faces(video, start, end, grays=grays)
    cl = face_clusters(frames)
    need = max(2, int(len(frames) * 0.3))
    steady = [c for c in cl if c["count"] >= need]
    faces = [c["box"] for c in steady[:2]]
    cams = []
    for f in faces:
        try:
            cams.append(camera_box(grays, f, W, H))
        except Exception as exc:                    # pencarian tepi hanya penyempurna
            log(f"  Tepi facecam tidak terbaca ({type(exc).__name__}).")
            cams.append(None)
    return {"W": W, "H": H, "frames": len(frames), "faces": faces, "cams": cams,
            "counts": [c["count"] for c in steady[:2]]}


# ---------------------------------------------------------------- geometri
def panel_sizes(mode: str, OW: int, OH: int, split: float, main_aspect: float) -> dict:
    """Tinggi panel wajah dan panel utama di video keluaran."""
    if mode == "reaction" and not split:
        main_h = min(OH * 0.62, max(OH * 0.3, OW / max(0.2, main_aspect)))
        split = 1 - main_h / OH
    split = min(0.7, max(0.2, split or DEFAULT_SPLIT.get(mode) or 0.4))
    face_h = _even(OH * split)
    return {"split": round(split, 4), "face_h": face_h, "main_h": OH - face_h}


def _clamp_box(x: float, y: float, w: float, h: float, W: int, H: int) -> tuple[float, float, float, float]:
    if w > W:
        h, w = h * W / w, W
    if h > H:
        w, h = w * H / h, H
    return min(max(0.0, x), W - w), min(max(0.0, y), H - h), w, h


def face_region(face: tuple, aspect: float, W: int, H: int, zoom: float = 3.0, cam: tuple | None = None) -> tuple:
    """Area sekitar wajah dengan rasio panel (lebar/tinggi), wajah sedikit di atas tengah.
    Bila kotak facecam diketahui, area dibuat sebesar mungkin di dalamnya (tanpa ikut gameplay)."""
    fx, fy, fw, fh = face
    if cam:
        cw, ch = cam[2], cam[3]
        rw, rh = (ch * aspect, ch) if cw / ch > aspect else (cw, cw / aspect)
        if rh < fh * 1.6:                         # facecam sangat kecil: jangan lebih sempit dari wajah
            rh = fh * 1.6
            rw = rh * aspect
        return _clamp_box(*fit_inside((0, 0, rw, rh), cam, face), W, H)
    rw = fw * zoom
    rh = rw / aspect
    if rh < fh * 2.3:
        rh = fh * 2.3
        rw = rh * aspect
    cx, cy = fx + fw / 2, fy + fh / 2
    return _clamp_box(cx - rw / 2, cy - rh * 0.42, rw, rh, W, H)


def cover_region(aspect: float, W: int, H: int, cx: float | None = None, cy: float | None = None) -> tuple:
    """Area terbesar dengan rasio `aspect` di frame, berpusat di (cx, cy)."""
    if W / H > aspect:
        rh, rw = H, H * aspect
    else:
        rw, rh = W, W / aspect
    cx = W / 2 if cx is None else cx
    cy = H / 2 if cy is None else cy
    return _clamp_box(cx - rw / 2, cy - rh / 2, rw, rh, W, H)


def _avoid(main: tuple, cam: tuple, W: int) -> tuple:
    """Geser area gameplay ke samping agar facecam tidak ikut terpotong di panel bawah (bila muat)."""
    x, y, w, h = main
    cx0, _, cw, _ = cam
    cx0, cw = cx0 - cw * 0.2, cw * 1.4                # beri jarak: tepi facecam hasil deteksi bisa sedikit ke dalam
    if x < cx0 + cw and cx0 < x + w:
        if cx0 + cw / 2 < W / 2 and cx0 + cw + w <= W:
            x = cx0 + cw
        elif cx0 + cw / 2 >= W / 2 and cx0 - w >= 0:
            x = cx0 - w
    return (x, y, w, h)


def _overlap(cam: tuple, main: tuple) -> tuple | None:
    """Bagian facecam yang ikut tampil di area video utama (koordinat relatif ke area itu)."""
    cam = (cam[0] - cam[2] * 0.15, cam[1] - cam[3] * 0.08, cam[2] * 1.3, cam[3] * 1.16)
    x0, y0 = max(cam[0], main[0]), max(cam[1], main[1])
    x1, y1 = min(cam[0] + cam[2], main[0] + main[2]), min(cam[1] + cam[3], main[1] + main[3])
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return (x0 - main[0], y0 - main[1], x1 - x0, y1 - y0)


def _norm(box: tuple, W: int, H: int) -> list[float]:
    x, y, w, h = box
    return [round(x / W, 4), round(y / H, 4), round(w / W, 4), round(h / H, 4)]


def _px(box: list, W: int, H: int) -> tuple:
    x, y, w, h = [float(v) for v in box]
    return _clamp_box(x * W, y * H, max(8.0, w * W), max(8.0, h * H), W, H)


def clean(raw: dict | None) -> dict:
    """Validasi layout dari pengguna/plan."""
    raw = raw or {}
    mode = raw.get("mode") if raw.get("mode") in MODES else "auto"
    out = {"mode": mode}
    try:
        sp = float(raw.get("split") or 0)
        out["split"] = round(min(0.7, max(0.2, sp)), 4) if sp else 0.0
    except (TypeError, ValueError):
        out["split"] = 0.0
    for k in ("face_box", "face2_box", "main_box"):
        b = raw.get(k)
        if isinstance(b, (list, tuple)) and len(b) == 4:
            try:
                x, y, w, h = [min(1.0, max(0.0, float(v))) for v in b]
                if w > 0.01 and h > 0.01:
                    out[k] = [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]
            except (TypeError, ValueError):
                pass
    out["main_fit"] = raw.get("main_fit") if raw.get("main_fit") in FIT else ""
    if "hide_cam" in raw:
        out["hide_cam"] = bool(raw.get("hide_cam"))
    out["pip_corner"] = raw.get("pip_corner") if raw.get("pip_corner") in ("kiri", "kanan") else ""
    return out


MIN_SEG = 0.4          # bagian layout paling pendek (detik)


def clean_segments(raw, dur: float) -> list[dict]:
    """Layout per bagian klip: [{"t": detik relatif awal klip, "layout": {...}}, ...], urut, bagian pertama di 0.
    Kurang dari dua bagian (atau semua layout sama) = [] (pakai satu layout untuk seluruh klip)."""
    out: list[dict] = []
    for r in raw or []:
        if not isinstance(r, dict):
            continue
        try:
            t = float(r.get("t") or 0)
        except (TypeError, ValueError):
            continue
        if t < 0 or t > dur - MIN_SEG:
            continue
        out.append({"t": round(t, 3), "layout": clean(r.get("layout"))})
    out.sort(key=lambda x: x["t"])
    merged: list[dict] = []
    for seg in out:
        if merged and (seg["t"] - merged[-1]["t"] < MIN_SEG or seg["layout"] == merged[-1]["layout"]):
            if seg["t"] - merged[-1]["t"] < MIN_SEG:
                merged[-1]["layout"] = seg["layout"]     # dua titik terlalu rapat: pakai yang terakhir
            continue
        merged.append(seg)
    if merged:
        merged[0]["t"] = 0.0
    return merged if len(merged) >= 2 else []


def shift_segments(segs: list[dict], delta: float, dur: float) -> list[dict]:
    """Geser waktu bagian layout setelah awal klip berubah (delta = awal lama - awal baru)."""
    if not segs:
        return []
    moved = [{"t": s["t"] + delta, "layout": s["layout"]} for s in segs]
    before = [s for s in moved if s["t"] <= 0]
    keep = ([{"t": 0.0, "layout": before[-1]["layout"]}] if before else []) + [s for s in moved if 0 < s["t"] < dur - MIN_SEG]
    return clean_segments(keep, dur)


def plan(lay: dict, W: int, H: int, OW: int, OH: int, det: dict | None) -> dict | None:
    """Susun panel. None = pakai render satu layar biasa (mode auto, atau wajah tidak ditemukan)."""
    mode = lay.get("mode", "auto")
    if mode == "auto":
        return None
    faces = list((det or {}).get("faces") or [])
    cams = list((det or {}).get("cams") or []) + [None, None]
    face = _px(lay["face_box"], W, H) if lay.get("face_box") else None
    face2 = _px(lay["face2_box"], W, H) if lay.get("face2_box") else None
    main_box = _px(lay["main_box"], W, H) if lay.get("main_box") else None
    main_aspect = (main_box[2] / main_box[3]) if main_box else W / H
    sizes = panel_sizes(mode, OW, OH, float(lay.get("split") or 0), main_aspect)
    fh, mh = sizes["face_h"], sizes["main_h"]
    if mode == "duo":
        if face is None or face2 is None:
            if len(faces) < 2:
                log("  Layout podcast: dua wajah tidak ditemukan; memakai satu layar. Atur kotaknya di tab Kreatif.")
                return None
            a, b = sorted(faces[:2], key=lambda f: f[0])
            face = face or face_region(a, OW / fh, W, H, 2.6)
            face2 = face2 or face_region(b, OW / mh, W, H, 2.6)
        panels = [{"role": "face", "src": face, "dst": (0, 0, OW, fh), "fit": "cover"},
                  {"role": "face2", "src": face2, "dst": (0, fh, OW, mh), "fit": "cover"}]
        return {"mode": mode, "panels": panels, "seam": fh / OH, **sizes,
                "boxes": {"face_box": _norm(face, W, H), "face2_box": _norm(face2, W, H)}}
    if face is None:
        if not faces:
            log("  Facecam/wajah tidak ditemukan; memakai satu layar. Atur kotak wajah di tab Kreatif bila perlu.")
            return None
        if mode == "pip":
            face = face_region(faces[0], 0.8, W, H, 2.4, cams[0])
        else:
            face = face_region(faces[0], OW / fh, W, H, 3.0 if mode == "stream" else 3.4, cams[0])
    if mode == "pip":
        fit = lay.get("main_fit") or "cover"
        main = main_box or (cover_region(OW / OH, W, H) if fit == "cover" else (0, 0, W, H))
        pw = _even(OW * 0.4)
        ph = _even(pw * face[3] / face[2])
        corner = lay.get("pip_corner") or ("kiri" if face[0] + face[2] / 2 < W / 2 else "kanan")
        margin = _even(OW * 0.045)
        px = margin if corner == "kiri" else OW - pw - margin
        panels = [{"role": "main", "src": main, "dst": (0, 0, OW, OH), "fit": fit},
                  {"role": "face", "src": face, "dst": (px, _even(OH * 0.06), pw, ph), "fit": "cover", "overlay": True}]
        return {"mode": mode, "panels": panels, "seam": 0.0, "split": 0.0, "face_h": ph, "main_h": OH,
                "boxes": {"face_box": _norm(face, W, H), "main_box": _norm(main, W, H)}, "corner": corner}
    fit = lay.get("main_fit") or ("contain" if mode == "reaction" else "cover")
    if main_box is None:
        main_box = cover_region(OW / mh, W, H) if fit == "cover" else (0, 0, W, H)
        if fit == "cover":
            main_box = _avoid(main_box, cams[0] or face, W)
    hide = None
    if lay.get("hide_cam", mode == "reaction"):
        hide = _overlap(cams[0] or face, main_box)
    if mode == "stream":
        panels = [{"role": "face", "src": face, "dst": (0, 0, OW, fh), "fit": "cover"},
                  {"role": "main", "src": main_box, "dst": (0, fh, OW, mh), "fit": fit, "hide": hide}]
        seam = fh / OH
    else:                                               # reaction: video atas, wajah bawah
        panels = [{"role": "main", "src": main_box, "dst": (0, 0, OW, mh), "fit": fit, "hide": hide},
                  {"role": "face", "src": face, "dst": (0, mh, OW, fh), "fit": "cover"}]
        seam = mh / OH
    return {"mode": mode, "panels": panels, "seam": seam, **sizes,
            "boxes": {"face_box": _norm(face, W, H), "main_box": _norm(main_box, W, H)}, "main_fit": fit}


def filter_graph(lp: dict, OW: int, OH: int, post: str) -> str:
    """Filter ffmpeg: potong tiap panel dari sumber, susun, lalu efek/subtitle (`post`)."""
    panels = lp["panels"]
    parts = [f"[0:v]split={len(panels)}" + "".join(f"[s{i}]" for i in range(len(panels)))]
    for i, p in enumerate(panels):
        x, y, w, h = p["src"]
        _, _, pw, ph = p["dst"]
        cw_, ch_ = _fe(w), _fe(h)
        crop = f"crop={cw_}:{ch_}:{int(x)}:{int(y)}"
        if p.get("hide"):
            hx, hy, hw, hh = [int(v) for v in p["hide"]]
            hw, hh = _fe(min(hw, cw_ - hx)), _fe(min(hh, ch_ - hy))
            parts.append(f"[s{i}]{crop},split=2[h{i}a][h{i}b]")
            parts.append(f"[h{i}b]crop={hw}:{hh}:{hx}:{hy},boxblur=24:3[h{i}c]")
            parts.append(f"[h{i}a][h{i}c]overlay={int(hx)}:{int(hy)}[s{i}x]")
            src_lbl, crop = f"s{i}x", "null"
        else:
            src_lbl = f"s{i}"
        if p["fit"] == "contain":
            parts.append(f"[{src_lbl}]{crop},split=2[c{i}a][c{i}b]")
            parts.append(f"[c{i}a]scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},"
                         f"gblur=sigma=26,eq=brightness=-0.08[c{i}bg]")
            parts.append(f"[c{i}b]scale={pw}:{ph}:force_original_aspect_ratio=decrease:flags=lanczos[c{i}fg]")
            parts.append(f"[c{i}bg][c{i}fg]overlay=(W-w)/2:(H-h)/2,setsar=1[p{i}]")
        else:
            parts.append(f"[{src_lbl}]{crop},scale={pw}:{ph}:force_original_aspect_ratio=increase:flags=lanczos,"
                         f"crop={pw}:{ph},setsar=1[p{i}]")
    if lp["mode"] == "pip":
        bx, by, bw, bh = panels[1]["dst"]
        b = max(4, _even(OW * 0.008))
        parts.append(f"[p1]pad={bw + 2 * b}:{bh + 2 * b}:{b}:{b}:color=white[pb]")
        parts.append(f"[p0][pb]overlay={bx - b}:{by - b},setsar=1{post}[v]")
    else:
        seam = _even(panels[0]["dst"][3])
        line = max(4, _even(OH * 0.003))
        parts.append(f"[p0][p1]vstack=inputs=2,drawbox=x=0:y={seam - line // 2}:w={OW}:h={line}:color=black@0.9:t=fill,"
                     f"setsar=1{post}[v]")
    return ";".join(parts)


def suggestions(video: Path, start: float, end: float, OW: int, OH: int) -> dict:
    """Usulan kotak untuk tiap mode (dipakai editor layout di tab Kreatif)."""
    det = detect(video, start, end)
    W, H = det["W"], det["H"]
    out = {"W": W, "H": H, "faces": [_norm(f, W, H) for f in det["faces"]],
           "cams": [_norm(c, W, H) if c else None for c in det.get("cams", [])], "modes": {}}
    for mode in ("stream", "reaction", "pip", "duo"):
        lp = plan({"mode": mode}, W, H, OW, OH, det)
        if lp:
            out["modes"][mode] = {"split": lp["split"], **lp["boxes"], "main_fit": lp.get("main_fit", "cover")}
    return out
