"""Render klip dengan ffmpeg: crop vertikal (ikut wajah / tengah / latar blur) + subtitle."""
from __future__ import annotations

import os
import shutil
import statistics
import urllib.request
from dataclasses import replace
from pathlib import Path

from . import layout as lay_mod
from .config import FONTS, PROJECT_DIR, Settings
from .subtitles import CaptionStyle, build_ass, build_srt
from .transcript import Word, group_segments
from .utils import log, run, slugify

FACE_MODEL = PROJECT_DIR / "models" / "face_detection_yunet_2023mar.onnx"
FACE_MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
                  "face_detection_yunet/face_detection_yunet_2023mar.onnx")


def _even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def plan_geometry(aspect: str, src_w: int, src_h: int) -> dict:
    """Tentukan area crop di video sumber dan resolusi keluaran."""
    if aspect == "original":
        return {"crop_w": src_w, "crop_h": src_h, "out_w": _even(src_w), "out_h": _even(src_h)}
    a, _, b = aspect.partition(":")
    ratio = float(a) / float(b)
    if src_w / src_h > ratio:
        crop_h, crop_w = src_h, _even(src_h * ratio)
    else:
        crop_w, crop_h = src_w, _even(src_w / ratio)
    crop_w, crop_h = min(crop_w, src_w - src_w % 2), min(crop_h, src_h - src_h % 2)
    out_w = 1080 if min(src_w, src_h) >= 1000 else 720
    return {"crop_w": crop_w, "crop_h": crop_h, "out_w": out_w, "out_h": _even(out_w / ratio)}


# ---------------------------------------------------------------- pelacakan wajah
def _load_face_detector():
    try:
        import cv2
    except ImportError:
        log("OpenCV tidak terpasang; crop wajah diganti crop tengah.")
        return None
    if not FACE_MODEL.is_file():
        try:
            FACE_MODEL.parent.mkdir(parents=True, exist_ok=True)
            log("Mengunduh model deteksi wajah YuNet (±230 KB)...")
            urllib.request.urlretrieve(FACE_MODEL_URL, FACE_MODEL)
        except Exception as exc:
            log(f"Gagal mengunduh model wajah ({exc}); memakai crop tengah.")
            return None
    try:
        return cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (320, 320), 0.7, 0.3, 20)
    except Exception as exc:
        log(f"Detektor wajah gagal dimuat ({exc}); memakai crop tengah.")
        return None


def track_faces(video: Path, start: float, end: float, sample_fps: float = 4.0) -> list[tuple[float, float | None]]:
    """Sampel posisi-x pusat wajah terbesar beberapa kali per detik. Waktu relatif ke awal klip."""
    import cv2
    det = _load_face_detector()
    if det is None:
        return []
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / sample_fps))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
    samples: list[tuple[float, float | None]] = []
    idx = 0
    size_set = None
    while True:
        if not cap.grab():
            break
        t = idx / fps
        if start + t > end:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            h, w = frame.shape[:2]
            scale = min(1.0, 640.0 / w)
            sw, sh = int(w * scale), int(h * scale)
            small = cv2.resize(frame, (sw, sh)) if scale < 1.0 else frame
            if size_set != (sw, sh):
                det.setInputSize((sw, sh))
                size_set = (sw, sh)
            _, faces = det.detect(small)
            if faces is not None and len(faces):
                f = max(faces, key=lambda f: float(f[2] * f[3] * f[14]))
                samples.append((t, float(f[0] + f[2] / 2) / scale))
            else:
                samples.append((t, None))
        idx += 1
    cap.release()
    return samples


def plan_shots(samples: list[tuple[float, float | None]], src_w: int, crop_w: int,
               sample_fps: float = 4.0, min_shot: float = 1.5) -> list[tuple[float, int]]:
    """Ubah posisi wajah menjadi 'shot' stabil (kamera hanya pindah bila wajah bergeser jauh)."""
    max_x = src_w - crop_w
    center_left = max_x // 2
    known = [cx for _, cx in samples if cx is not None]
    if not known or max_x <= 0:
        return [(0.0, center_left)]
    xs, last = [], known[0]
    for _, cx in samples:
        last = cx if cx is not None else last
        xs.append(last)
    ts = [t for t, _ in samples]
    sm = [statistics.median(xs[max(0, i - 2): i + 3]) for i in range(len(xs))]
    dead_zone = crop_w * 0.15
    look = max(2, int(sample_fps))
    cur = statistics.median(sm[:look])
    shots = [(0.0, cur)]
    i = 0
    while i < len(sm):
        if abs(sm[i] - cur) > dead_zone and ts[i] - shots[-1][0] >= min_shot:
            win = sm[i: i + look]
            if len(win) >= 2 and sum(abs(v - cur) > dead_zone for v in win) >= 0.8 * len(win):
                cur = statistics.median(win)
                shots.append((ts[i], cur))
                i += look
                continue
        i += 1
    shots = shots[:40]
    return [(round(t, 3), int(min(max_x, max(0, cx - crop_w / 2)))) for t, cx in shots]


def x_expression(shots: list[tuple[float, int]]) -> str:
    expr = str(shots[-1][1])
    for k in range(len(shots) - 2, -1, -1):
        expr = f"if(lt(t,{shots[k + 1][0]}),{shots[k][1]},{expr})"
    return expr


# ---------------------------------------------------------------- efek
def ensure_fonts(out_root: Path) -> Path:
    """Salin font bundel ke <output>/_fonts agar bisa dirujuk ffmpeg dengan path relatif
    (menghindari masalah huruf drive 'C:' di filter ffmpeg pada Windows)."""
    dst = out_root / "_fonts"
    dst.mkdir(parents=True, exist_ok=True)
    for f in (PROJECT_DIR / "fonts").glob("*.ttf"):
        target = dst / f.name
        if not target.is_file() or target.stat().st_size != f.stat().st_size:
            shutil.copyfile(f, target)
    return dst


def punch_zoom_expr(words: list[Word], start: float, end: float, factor: float = 1.12) -> str | None:
    """Zoom-in bergantian per kalimat (gaya 'jump cut'), waktu relatif ke awal klip."""
    inside = [w for w in words if w.end > start and w.start < end]
    segs = group_segments(inside, max_gap=0.6, max_len=5.0, max_chars=80)
    ranges = []
    for i, sg in enumerate(segs):
        if i % 2 == 1 and sg.end - sg.start >= 1.0:
            ranges.append((max(0.0, sg.start - start), min(end, sg.end) - start))
    if not ranges:
        return None
    cond = "+".join(f"between(it,{a:.2f},{b:.2f})" for a, b in ranges[:24])
    return f"if({cond},{factor},1)"


# ---------------------------------------------------------------- render
def render_clip(cfg: Settings, video: Path, info: dict, clip: dict, words: list[Word],
                clips_dir: Path, sub_words: list[Word] | None = None, on_frac=None,
                name: str | None = None, bare: bool = False) -> Path:
    """Render satu klip. `words` = transkrip asli (untuk zoom), `sub_words` = kata subtitle
    (bisa hasil terjemahan). `bare=True`: tanpa subtitle/efek (bahan untuk versi kartun)."""
    if bare:
        cfg = replace(cfg, subtitles=False, hook_overlay=False, progress_bar=False, zoom="none")
    clips_dir.mkdir(parents=True, exist_ok=True)
    start, end = float(clip["start"]), float(clip["end"])
    dur = end - start
    name = name or f"{clip['rank']:02d}_{slugify(clip.get('title', ''))}"
    out = clips_dir / f"{name}.mp4"
    src_w, src_h = info["width"], info["height"]
    geo = plan_geometry(cfg.aspect, src_w, src_h)
    cw, ch, ow, oh = geo["crop_w"], geo["crop_h"], geo["out_w"], geo["out_h"]
    vertical = oh > ow
    sub_words = sub_words if sub_words is not None else words

    # layout streaming / reaction / pip / podcast (hanya untuk keluaran vertikal)
    lp = None
    lay = lay_mod.clean(clip.get("layout") or {"mode": cfg.layout, "split": cfg.split})
    if lay["mode"] != "auto":
        if cfg.aspect not in ("9:16", "4:5"):
            log(f"  Layout '{lay['mode']}' hanya untuk rasio 9:16 atau 4:5; memakai satu layar.")
        else:
            need_detect = not lay.get("face_box") or (lay["mode"] == "duo" and not lay.get("face2_box"))
            det = lay_mod.detect(video, start, end) if need_detect else {"faces": []}
            lp = lay_mod.plan(lay, src_w, src_h, ow, oh, det)
            if lp:
                log(f"  layout: {lay_mod.MODES[lp['mode']]}")

    style = CaptionStyle(
        anim=cfg.anim, font=cfg.font, fake_bold=FONTS.get(cfg.font, (None, True))[1],
        size=cfg.font_size, uppercase=cfg.uppercase, text_color=cfg.text_color,
        highlight=cfg.highlight_color, max_words=cfg.words_per_line, position=cfg.position,
        captions=cfg.subtitles,
        hook_text=(clip.get("title") or clip.get("hook") or "") if cfg.hook_overlay else "",
        progress_bar=cfg.progress_bar,
        y_frac=(lp["seam"] if lp and lp["seam"] else 0.0),
    )
    sub_filter = ""
    if style.captions or style.hook_text or style.progress_bar:
        ass = build_ass(sub_words, start, end, ow, oh, style, vertical=vertical)
        (clips_dir / f"{name}.ass").write_text(ass, encoding="utf-8")
        fonts = ensure_fonts(clips_dir.parent.parent)
        # path relatif: ffmpeg dijalankan di clips_dir = <output>/<id>/clips
        sub_filter = f",ass={name}.ass:fontsdir={os.path.relpath(fonts, clips_dir).replace(os.sep, '/')}"
    if not bare:
        (clips_dir / f"{name}.srt").write_text(build_srt(sub_words, start, end), encoding="utf-8")

    zoom_filter = ""
    if cfg.zoom == "punch":
        expr = punch_zoom_expr(words, start, end)
        if expr:
            zoom_filter = (f",zoompan=z='{expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                           f":d=1:s={ow}x{oh}:fps={info.get('fps', 30):.3f}")
    post = f"{zoom_filter}{sub_filter}"

    mode = cfg.crop if cfg.aspect != "original" else "none"
    if lp:
        graph = lay_mod.filter_graph(lp, ow, oh, post)
    elif mode == "blur":
        graph = (f"[0:v]split=2[a][b];"
                 f"[a]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},"
                 f"gblur=sigma=28,eq=brightness=-0.07[bg];"
                 f"[b]scale={ow}:{oh}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1{post}[v]")
    elif mode == "none":
        graph = f"[0:v]scale={ow}:{oh}:flags=lanczos,setsar=1{post}[v]"
    else:
        y = (src_h - ch) // 2
        x = str((src_w - cw) // 2)
        if mode == "face" and src_w > cw:
            shots = plan_shots(track_faces(video, start, end), src_w, cw)
            x = x_expression(shots)
            log(f"  pelacakan wajah: {len(shots)} posisi kamera")
        graph = (f"[0:v]crop=w={cw}:h={ch}:x='{x}':y={y},"
                 f"scale={ow}:{oh}:flags=lanczos,setsar=1{post}[v]")

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y",
           "-ss", f"{start:.3f}", "-i", str(video.resolve()), "-t", f"{dur:.3f}"]
    maps = ["-map", "[v]"]
    if info.get("has_audio"):
        fade_out = max(0.0, dur - 0.15)
        graph += f";[0:a]afade=t=in:st=0:d=0.05,afade=t=out:st={fade_out:.3f}:d=0.15[a]"
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    cmd += ["-filter_complex", graph, *maps,
            "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out.resolve())]
    run(cmd, cwd=clips_dir, on_seconds=(lambda sec: on_frac(min(1.0, sec / dur))) if on_frac else None)
    return out
