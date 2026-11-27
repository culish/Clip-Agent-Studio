"""Pemeriksaan mutu klip hasil render: tepi kalimat, keras suara, getar, frame hitam/beku, potongan adegan, wajah.

Ambang dan cara ukurnya diambil dari AutoClip (backend/services/studio/qa/: ending.py, loudness.py, jitter.py,
face.py; MIT, Copyright (c) 2024 AutoClip Team, https://github.com/zhouxiaoka/autoclip):
- tepi: kata yang masih tersisa lebih dari 80 md = terpotong di tengah kata; kata berikutnya mulai dalam
  0,6 dtk padahal kata terakhir bukan akhir kalimat = terpotong di tengah kalimat. Clip Agent juga memeriksa
  awal klip dengan aturan cermin.
- keras suara: -14 LUFS ± 1 LU dan true peak paling tinggi -1 dBTP (ffmpeg ebur128).
- getar: korelasi fase pada frame abu-abu 96x54; gagal bila kedip arah > 1/menit, atau RMS > 0,30 px saat
  kamera tidak sedang menggeser.
- wajah: YuNet; subtitle menutupi lebih dari 35% kotak wajah, atau orang yang ada di sumber tidak masuk bingkai.
Tambahan Clip Agent: frame hitam/beku (ffmpeg blackdetect/freezedetect) dan potongan adegan di 0,75 dtk
pertama/terakhir (beberapa frame dari shot lain yang "berkedip" di awal atau akhir klip).
"""
from __future__ import annotations

import math
import re
import subprocess

# ---------------------------------------------------------------- tepi kalimat (ending.py)
SLACK_S = 0.08
GAP_S = 0.6
_FINAL = re.compile(r'[。！？!?…]$|\.$')


def _sentence_final(text: str) -> bool:
    token = str(text).strip().strip('"\'“”‘’')
    return bool(token) and bool(_FINAL.search(token))


def _w(word):
    return (word["start"], word["end"], word["text"]) if isinstance(word, dict) else (word.start, word.end, word.text)


def judge_ending(words, clip_end: float, clip_start: float = 0.0) -> tuple[str, str]:
    """('pass'|'fail'|'skip', 'complete'|'mid_word'|'mid_sentence'|'no_words') untuk akhir klip."""
    ws = [_w(w) for w in words or []]
    if not ws:
        return 'skip', 'no_words'
    if any(s < clip_end < e - SLACK_S and e > clip_start for s, e, _ in ws):
        return 'fail', 'mid_word'
    spoken = [(s, e, t) for s, e, t in ws if clip_start - SLACK_S <= s and e <= clip_end + SLACK_S]
    if not spoken:
        return 'pass', 'complete'
    last = max(spoken, key=lambda w: w[1])
    if _sentence_final(last[2]):
        return 'pass', 'complete'
    nxt = next((w for w in sorted(ws) if w[0] >= clip_end - 1e-6), None)
    if nxt is not None and nxt[0] - clip_end <= GAP_S:
        return 'fail', 'mid_sentence'
    return 'pass', 'complete'


def judge_start(words, clip_start: float) -> tuple[str, str]:
    """Aturan cermin untuk awal klip: kata pertama terpotong, atau klip mulai di tengah kalimat."""
    ws = sorted(_w(w) for w in words or [])
    if not ws:
        return 'skip', 'no_words'
    if any(s + SLACK_S < clip_start < e for s, e, _ in ws):
        return 'fail', 'mid_word'
    before = [w for w in ws if w[1] <= clip_start + SLACK_S]
    if not before:
        return 'pass', 'complete'
    prev = before[-1]
    if clip_start - prev[1] <= GAP_S and not _sentence_final(prev[2]):
        return 'fail', 'mid_sentence'
    return 'pass', 'complete'


# ---------------------------------------------------------------- keras suara (loudness.py)
TARGET_LUFS, TOLERANCE_LU, PEAK_MAX = -14.0, 1.0, -1.0
_I = re.compile(r'I:\s*(-?\d+(?:\.\d+)?)\s*LUFS')
_PEAK = re.compile(r'Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS')


def judge_levels(lufs: float, peak: float) -> tuple[str, str]:
    offset = lufs - TARGET_LUFS
    level_bad, peak_bad = abs(offset) > TOLERANCE_LU, peak > PEAK_MAX
    if not level_bad and not peak_bad:
        return 'pass', 'in_target'
    if level_bad and peak_bad:
        return 'fail', 'peak_and_level'
    if peak_bad:
        return 'fail', 'peak'
    return 'fail', f"{'loud' if offset > 0 else 'quiet'}_{'1_3' if abs(offset) <= 3 else 'gt3'}"


def measure_loudness(path, timeout: float = 120) -> tuple[float, float] | None:
    """(LUFS terintegrasi, true peak dBTP) atau None bila tidak ada audio."""
    try:
        proc = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-map', '0:a:0', '-vn', '-sn',
                               '-dn', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    text = f"{proc.stderr or ''}\n{proc.stdout or ''}"
    integrated, peaks = _I.findall(text), _PEAK.findall(text)
    if not integrated or not peaks:
        return None
    return float(integrated[-1]), float(peaks[-1])


# ---------------------------------------------------------------- getar (jitter.py)
FLASHES_PER_MIN = 1.0
RMS_PX = 0.30
STATIC_MEAN_PX = 8.0
SAMPLE_FLASH_PX = 3.0
SAMPLE_NOISE_PX = 0.12
SAMPLE_W, SAMPLE_H = 96, 54


def flashes_from_shifts(shifts: list[tuple[float, float]], min_px: float = SAMPLE_FLASH_PX) -> int:
    count, previous = 0, None
    for dx, dy in shifts:
        if math.hypot(dx, dy) < min_px:
            previous = None
            continue
        sign = 1 if dx > 0 or (dx == 0 and dy > 0) else -1
        if previous is not None and previous * sign < 0:
            count += 1
        previous = sign
    return count


def quiet_sample_noise(shifts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(0.0, 0.0) if math.hypot(dx, dy) < SAMPLE_NOISE_PX else (dx, dy) for dx, dy in shifts]


def motion_stats(shifts: list[tuple[float, float]]) -> tuple[float, float]:
    if not shifts:
        return 0.0, 0.0
    mags = [math.hypot(dx, dy) for dx, dy in shifts]
    return math.sqrt(sum(v * v for v in mags) / len(mags)), sum(mags) / len(mags)


def judge_motion(flash_count: int, duration_s: float, rms_px: float, mean_abs_px: float) -> tuple[str, str]:
    flash_fail = flash_count / max(duration_s, 1e-3) * 60 > FLASHES_PER_MIN
    rms_fail = mean_abs_px < STATIC_MEAN_PX and rms_px > RMS_PX
    if flash_fail and rms_fail:
        return 'fail', 'flash_and_rms'
    if flash_fail:
        return 'fail', 'flash'
    if rms_fail:
        return 'fail', 'rms'
    return 'pass', 'calm'


def sample_shifts(path, at: float, frames: int = 6) -> list[tuple[float, float]]:
    """Pergeseran antar frame berurutan (piksel sampel 96x54) mulai detik `at`, lewat korelasi fase."""
    import cv2
    import numpy as np
    try:
        proc = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{max(0.0, at):.3f}', '-i', str(path),
                               '-frames:v', str(frames), '-vf', f'scale={SAMPLE_W}:{SAMPLE_H}',
                               '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    size = SAMPLE_W * SAMPLE_H
    raw = proc.stdout or b''
    imgs = [np.frombuffer(raw[i * size:(i + 1) * size], dtype=np.uint8).reshape(SAMPLE_H, SAMPLE_W).astype(np.float32)
            for i in range(len(raw) // size)]
    window = cv2.createHanningWindow((SAMPLE_W, SAMPLE_H), cv2.CV_32F)
    out = []
    for a, b in zip(imgs, imgs[1:]):
        (dx, dy), _ = cv2.phaseCorrelate(a, b, window)
        out.append((float(dx), float(dy)))
    return out


# ---------------------------------------------------------------- frame hitam / beku (Clip Agent)
def detect_intervals(path, timeout: float = 180) -> dict:
    """{'black': [(s, e)], 'freeze': [(s, e)]} di klip hasil render (detik relatif klip)."""
    try:
        proc = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-an', '-vf',
                               'blackdetect=d=0.1:pic_th=0.98:pix_th=0.10,freezedetect=n=-60dB:d=1.5',
                               '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {'black': [], 'freeze': []}
    log = proc.stderr or ''
    black = [(float(a), float(b)) for a, b in
             re.findall(r'black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)', log)]
    starts = [float(x) for x in re.findall(r'freeze_start:\s*([\d.]+)', log)]
    ends = [float(x) for x in re.findall(r'freeze_end:\s*([\d.]+)', log)]
    freeze = [(s, ends[i] if i < len(ends) else None) for i, s in enumerate(starts)]
    return {'black': black, 'freeze': freeze}


# ---------------------------------------------------------------- potongan adegan di tepi (Clip Agent)
def _hist(img):
    import cv2
    hsv = cv2.cvtColor(cv2.resize(img, (160, 90)), cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


def edge_cuts(video, start: float, end: float, reach: float = 0.75, threshold: float = 0.45) -> dict:
    """Pergantian shot dalam `reach` detik setelah awal / sebelum akhir klip (di video sumber).

    Mengembalikan {'start': detik absolut potongan atau None, 'end': ...}. Potongan di awal berarti beberapa
    frame pertama klip berasal dari shot sebelumnya; di akhir berarti klip berakhir dengan kedipan shot baru.
    """
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out: dict = {'start': None, 'end': None, 'fps': fps}

    def scan(a: float, b: float):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, a) * 1000.0)
        prev, cuts, t = None, [], max(0.0, a)
        while t <= b:
            ok, frame = cap.read()
            if not ok:
                break
            t = (cap.get(cv2.CAP_PROP_POS_MSEC) or t * 1000.0) / 1000.0
            h = _hist(frame)
            if prev is not None:
                corr = float(cv2.compareHist(prev, h, cv2.HISTCMP_CORREL))
                if corr < threshold:
                    cuts.append((t, corr))          # t = waktu frame pertama shot baru
            prev = h
        return cuts

    try:
        first = [c for c in scan(start, start + reach) if c[0] > start + 0.5 / fps]
        last = [c for c in scan(max(start, end - reach - 1.0 / fps), end) if c[0] < end - 0.5 / fps]
    finally:
        cap.release()
    if first:
        out['start'] = round(max(first, key=lambda c: c[0])[0], 3)   # shot terakhir yang dimulai di awal klip
    if last:
        out['end'] = round(min(last, key=lambda c: c[0])[0], 3)      # shot baru pertama yang muncul di akhir
    return out


# ---------------------------------------------------------------- wajah (face.py)
FACE_OVERLAP = 0.35


def caption_rect(width: int, height: int, position: str = "lower", y_frac: float = 0.0) -> tuple[float, float, float, float]:
    """Perkiraan kotak subtitle (x, y, w, h) di klip hasil render, mengikuti posisi di subtitles.py."""
    vertical = height > width
    band = height * (0.16 if vertical else 0.14)
    inset = width * 0.07
    if y_frac > 0:
        y = height * y_frac - band / 2
    elif position == "upper":
        y = height * (0.20 if vertical else 0.10)
    elif position == "middle":
        y = height * (0.58 if vertical else 0.55) - band / 2
    else:
        y = height * (0.76 if vertical else 0.92) - band
    return inset, max(0.0, y), width - 2 * inset, band


def covered_fraction(face, rect) -> float:
    fx, fy, fw, fh = face
    ox, oy, ow, oh = rect
    area = fw * fh
    if area <= 0:
        return 0.0
    ix = max(0.0, min(fx + fw, ox + ow) - max(fx, ox))
    iy = max(0.0, min(fy + fh, oy + oh) - max(fy, oy))
    return ix * iy / area


def faces(detector, img, score: float = 0.6) -> list[tuple[float, float, float, float]]:
    """Semua wajah (x, y, w, h) di gambar BGR."""
    import cv2
    if detector is None or img is None:
        return []
    h, w = img.shape[:2]
    sc = min(1.0, 640 / max(w, 1))
    small = cv2.resize(img, (int(w * sc), int(h * sc))) if sc < 1 else img
    detector.setInputSize((small.shape[1], small.shape[0]))
    try:
        detector.setScoreThreshold(score)
    except Exception:  # noqa: BLE001 - versi OpenCV lama
        pass
    _, found = detector.detect(small)
    if found is None:
        return []
    return [tuple(float(v) / sc for v in f[:4]) for f in found if float(f[14]) >= score]
