"""Cek frame dan atur panjang klip (perpanjang/pendekkan) untuk hasil Auto clip.

Memakai modul yang diadaptasi dari AutoClip (lihat clipagent/autoclip, MIT):
- trim_info(): data editor: rentang klip, kata-kata di sekitar tepi, penilaian tepi saat ini, saran rapi.
- suggest(): rapikan awal/akhir ke kalimat utuh dan jeda di audio (autoclip.boundaries.sentence_bounds).
- suggest_ai(): AI memilih awal pertanyaan dan akhir jawaban (autoclip.boundaries.refine_with_model).
- retime_clip(): render ulang satu klip dengan awal/akhir baru lalu perbarui plan.json.
- frame_check(): strip frame + pemeriksaan mutu (autoclip.qa) pada klip hasil render.
- normalize_audio(): samakan keras suara klip ke -14 LUFS tanpa merender ulang gambarnya.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import cv2

from .autoclip import boundaries as B
from .autoclip import qa as Q
from .creative import ClipContext, read_frame, save_plan
from .utils import ClipAgentError, check_cancel, log, probe, progress

EDGE_WORDS_SEC = 45.0       # kata yang dikirim ke editor: sejauh ini sebelum awal / sesudah akhir klip
MIN_LEN, MAX_LEN = 1.0, 600.0
VERDICT = {
    "complete": "Utuh",
    "mid_word": "Terpotong di tengah kata",
    "mid_sentence": "Terpotong di tengah kalimat",
    "no_words": "Tidak ada transkrip",
}


# ====================================================================== data editor
def _rows(ctx: ClipContext) -> list[B.Row]:
    lo, hi = ctx.start - B.CONTEXT_BEFORE - 30, ctx.end + B.CONTEXT_AFTER + 30
    return B.rows_from_words([w for w in ctx.words if lo <= w.start <= hi])


def _silences(ctx: ClipContext):
    return B.combined_silences(ctx.video, ctx.words)


def edges(words, start: float, end: float) -> dict:
    s, sr = Q.judge_start(words, start)
    e, er = Q.judge_ending(words, end, start)
    return {"start": {"status": s, "reason": sr, "label": VERDICT.get(sr, sr)},
            "end": {"status": e, "reason": er, "label": VERDICT.get(er, er)}}


def _clamp(ctx: ClipContext, start: float, end: float) -> tuple[float, float]:
    total = float(ctx.info.get("duration") or 0) or max(end, ctx.end)
    start, end = max(0.0, float(start)), min(total, float(end))
    if end <= start:
        raise ValueError("Akhir klip harus sesudah awal klip.")
    if end - start < MIN_LEN:
        raise ValueError(f"Klip terlalu pendek ({end - start:.1f} dtk). Minimal {MIN_LEN:.0f} detik.")
    if end - start > MAX_LEN:
        raise ValueError(f"Klip terlalu panjang ({end - start:.0f} dtk). Maksimal {MAX_LEN / 60:.0f} menit.")
    return round(start, 3), round(end, 3)


def suggest(ctx: ClipContext, start: float | None = None, end: float | None = None) -> dict:
    """Saran awal/akhir di kalimat utuh dan jeda audio, untuk rentang (start, end) mana pun."""
    start = ctx.start if start is None else float(start)
    end = ctx.end if end is None else float(end)
    if not ctx.words:
        return {"start": start, "end": end, "changed": False, "note": "Klip ini belum punya transkrip per kata."}
    s, e = B.sentence_bounds(_rows(ctx), start, end, _silences(ctx))
    s, e = _clamp(ctx, s, e)
    changed = abs(s - start) > 0.04 or abs(e - end) > 0.04
    return {"start": s, "end": e, "changed": changed, "edges": edges(ctx.words, s, e),
            "note": "" if changed else "Awal dan akhir klip sudah di kalimat utuh."}


def source_url(ctx: ClipContext) -> str:
    """Video sumber untuk pratinjau di browser (juga file lokal di luar folder hasil)."""
    if ctx.video.suffix.lower() not in (".mp4", ".webm", ".mov", ".m4v", ".mkv"):
        return ""
    from urllib.parse import quote
    return (f"/api/trim/source?video_id={quote(ctx.video_id)}&rank={ctx.rank}"
            f"&v={int(ctx.video.stat().st_mtime)}")


def trim_info(ctx: ClipContext) -> dict:
    cfg = ctx.settings()
    lo, hi = ctx.start - EDGE_WORDS_SEC, ctx.end + EDGE_WORDS_SEC
    words = [[round(w.start, 3), round(w.end, 3), w.text] for w in ctx.words if w.end >= lo and w.start <= hi]
    clip_file = ctx.workdir / "clips" / ctx.clip["file"] if ctx.clip.get("file") else None
    orig = ctx.clip.get("orig_range") or [ctx.start, ctx.end]
    return {"video_id": ctx.video_id, "rank": ctx.rank, "title": ctx.clip.get("title", ""),
            "start": ctx.start, "end": ctx.end, "orig": orig,
            "total": float(ctx.info.get("duration") or 0), "fps": float(ctx.info.get("fps") or 30),
            "source_url": source_url(ctx),
            "video_url": ctx.url(clip_file) if clip_file and clip_file.is_file() else "",
            "words": words, "edges": edges(ctx.words, ctx.start, ctx.end),
            "limits": {"min": cfg.min_dur, "max": cfg.max_dur},
            "ai": (cfg.provider or "heuristic") != "heuristic",
            "check": load_check(ctx)}


def source_frame(ctx: ClipContext, t: float, width: int = 320) -> Path:
    """Frame video sumber pada detik absolut t (untuk pratinjau awal/akhir), di-cache."""
    t = round(min(max(0.0, float(t)), max(0.0, float(ctx.info.get("duration") or t) - 0.04)), 2)
    p = ctx.workdir / "creative" / "srcframes" / f"t{int(round(t * 100)):08d}.jpg"
    if not p.is_file():
        frame = read_frame(ctx.video, t)
        if frame is None:
            raise ClipAgentError("Frame tidak bisa dibaca.")
        p.parent.mkdir(parents=True, exist_ok=True)
        h = round(frame.shape[0] * width / frame.shape[1])
        cv2.imwrite(str(p), cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return p


def suggest_ai(ctx: ClipContext, opts: dict) -> dict:
    """AI merapikan tepi klip (job): mengembalikan saran, belum dirender."""
    from .llm import LLMClient
    cfg = ctx.settings()
    if (cfg.provider or "heuristic") == "heuristic":
        raise ClipAgentError("Rapikan dengan AI butuh model AI. Pilih provider AI di Pengaturan, "
                             "atau pakai 'Rapikan ke kalimat' yang tidak butuh AI.")
    start = float(opts.get("start", ctx.start))
    end = float(opts.get("end", ctx.end))
    if not ctx.words:
        raise ClipAgentError("Klip ini belum punya transkrip per kata.")
    client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)
    progress(0.2, "AI membaca kalimat di sekitar klip")

    def call(system: str, payload: dict) -> dict:
        return client.complete_json(system, json.dumps(payload, ensure_ascii=False))

    rows = _rows(ctx)
    got = B.refine_with_model(rows, start, end, call, _silences(ctx))
    if got is None:
        log("Jawaban AI tidak dipakai (di luar batas wajar); memakai saran kalimat utuh.")
        base = suggest(ctx, start, end)
        return {**base, "reason": "Jawaban AI tidak masuk akal, jadi dipakai saran kalimat utuh.", "ai": False}
    s, e = _clamp(ctx, got[0], got[1])
    log(f"Saran AI: {s:.2f}–{e:.2f} dtk. {got[2]}")
    return {"start": s, "end": e, "changed": abs(s - start) > 0.04 or abs(e - end) > 0.04,
            "edges": edges(ctx.words, s, e), "reason": got[2], "ai": True}


# ====================================================================== render ulang dengan rentang baru
def validate(ctx: ClipContext, body: dict) -> None:
    try:
        s, e = float(body.get("start")), float(body.get("end"))
    except (TypeError, ValueError):
        raise ValueError("Isi awal dan akhir klip dalam detik.")
    _clamp(ctx, s, e)


def retime_clip(ctx: ClipContext, opts: dict) -> dict:
    """Render ulang klip dengan awal/akhir baru (perpanjang atau pendekkan), lalu cek frame-nya."""
    from .render import render_clip
    from .translate import translate_clip_words
    start, end = _clamp(ctx, opts.get("start"), opts.get("end"))
    old = (ctx.start, ctx.end)
    cfg = ctx.settings()
    ctx.clip.setdefault("orig_range", [round(old[0], 3), round(old[1], 3)])
    ctx.clip["start"], ctx.clip["end"], ctx.clip["duration"] = start, end, round(end - start, 2)
    old_segs = ctx.clip.get("layout_segments")
    if old_segs:                                   # layout per bagian ikut bergeser bersama awal klip
        from .layout import shift_segments
        segs = shift_segments(old_segs, old[0] - start, end - start)
        if segs:
            ctx.clip["layout_segments"] = segs
        else:
            ctx.clip.pop("layout_segments", None)
    sub_words = None
    target = ctx.clip.get("sub_lang") or ""
    if cfg.subtitles and target and target != (ctx.tlang or ""):
        try:
            sub_words = translate_clip_words(cfg, ctx.words, [(start, end)], target,
                                             ctx.workdir / f"translations_{target}.json").get(0)
        except ClipAgentError as exc:
            log(f"Terjemahan subtitle dilewati ({str(exc).splitlines()[0][:100]}).")
    clips_dir = ctx.workdir / "clips"
    name = Path(ctx.clip.get("file") or f"{ctx.slug}.mp4").stem
    tmp = f"{name}__retime"
    d0, d1 = old[1] - old[0], end - start
    log(f"Render ulang klip #{ctx.rank}: {old[0]:.2f}–{old[1]:.2f} → {start:.2f}–{end:.2f} dtk "
        f"({'lebih panjang' if d1 > d0 else 'lebih pendek' if d1 < d0 else 'durasi sama'} {abs(d1 - d0):.1f} dtk)")
    try:
        render_clip(cfg, ctx.video, ctx.info, ctx.clip, ctx.words, clips_dir, sub_words=sub_words, name=tmp,
                    on_frac=lambda f: progress(0.05 + 0.7 * f, "Render ulang klip"))
    except BaseException:
        ctx.clip["start"], ctx.clip["end"], ctx.clip["duration"] = old[0], old[1], round(old[1] - old[0], 2)
        if old_segs:
            ctx.clip["layout_segments"] = old_segs
        raise
    for ext in (".mp4", ".ass", ".srt"):
        src = clips_dir / f"{tmp}{ext}"
        if src.is_file():
            os.replace(src, clips_dir / f"{name}{ext}")
    ctx.clip["file"] = f"{name}.mp4"
    ctx.clip.pop("loudnorm", None)
    try:                                   # kalimat pembuka berubah: nilai ulang hook-nya
        from .ytkit import score_clips
        for k in ("opening", "hook_score", "hook_tip"):
            ctx.clip.pop(k, None)
        score_clips([ctx.clip], ctx.words)
    except Exception as exc:               # noqa: BLE001 - skor hanya tambahan
        log(f"Skor pembuka dilewati ({type(exc).__name__}).")
    save_plan(ctx)
    out = {"file": ctx.clip["file"], "start": start, "end": end, "duration": round(end - start, 2),
           "video_url": ctx.url(clips_dir / ctx.clip["file"])}
    if opts.get("check", True):
        out["check"] = frame_check(ctx, base=0.78)
    progress(1.0, "Klip selesai dirender ulang")
    return out


def normalize_audio(ctx: ClipContext) -> dict:
    """Samakan keras suara klip ke -14 LUFS / -1,5 dBTP (loudnorm dua tahap); gambar disalin apa adanya."""
    clips_dir = ctx.workdir / "clips"
    path = clips_dir / (ctx.clip.get("file") or "")
    if not path.is_file():
        raise ClipAgentError("File klip belum ada. Render klipnya dulu.")
    progress(0.1, "Mengukur keras suara")
    target = f"I={Q.TARGET_LUFS}:TP=-1.5:LRA=11"
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af",
                           f"loudnorm={target}:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = proc.stderr or ""
    try:
        m = json.loads(text[text.rindex("{"):text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        raise ClipAgentError("Keras suara klip tidak bisa diukur (klip tanpa audio?).")
    check_cancel()
    progress(0.5, "Menyamakan keras suara")
    tmp = path.with_name(path.stem + "__loud.mp4")
    af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    run = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0",
                          "-c:v", "copy", "-c:s", "copy", "-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                          "-movflags", "+faststart", str(tmp)], capture_output=True, text=True)
    if run.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise ClipAgentError(f"Gagal menyamakan keras suara: {(run.stderr or '').strip()[-300:]}")
    os.replace(tmp, path)
    ctx.clip["loudnorm"] = True
    save_plan(ctx)
    log(f"Keras suara: {float(m['input_i']):.1f} → {Q.TARGET_LUFS:.0f} LUFS")
    out = {"video_url": ctx.url(path), "check": frame_check(ctx, base=0.6)}
    progress(1.0, "Keras suara sudah disamakan")
    return out


# ====================================================================== cek frame
def _check_path(ctx: ClipContext) -> Path:
    return ctx.cdir / "framecheck" / "check.json"


def load_check(ctx: ClipContext) -> dict | None:
    p = _check_path(ctx)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    f = ctx.workdir / "clips" / (ctx.clip.get("file") or "")
    r = data.get("clip_range") or [0, 0]
    if (not f.is_file() or abs(r[0] - ctx.start) > 0.05 or abs(r[1] - ctx.end) > 0.05
            or abs(float(data.get("mtime", 0)) - f.stat().st_mtime) > 1):
        return None                          # klipnya sudah dirender ulang sejak dicek
    for fr in data.get("frames", []):
        fp = p.parent / fr["file"]
        fr["url"] = ctx.url(fp) if fp.is_file() else ""
    return data


def _fmt(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def frame_check(ctx: ClipContext, frames: int = 12, base: float = 0.0) -> dict:
    """Strip frame klip hasil render dan daftar pemeriksaan mutu. Disimpan untuk ditampilkan lagi."""
    from .render import _load_face_detector
    path = ctx.workdir / "clips" / (ctx.clip.get("file") or "")
    if not ctx.clip.get("file") or not path.is_file():
        raise ClipAgentError("File klip belum ada. Render klipnya dulu.")
    span = 1.0 - base
    step = lambda f, msg: progress(base + span * f, msg)  # noqa: E731
    pinfo = probe(path)
    W, H, dur, fps = pinfo["width"], pinfo["height"], pinfo["duration"] or ctx.duration, pinfo["fps"] or 30.0
    cfg = ctx.settings()
    out_dir = _check_path(ctx).parent
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []

    # 1) tepi kalimat
    step(0.02, "Cek awal dan akhir kalimat")
    ed = edges(ctx.words, ctx.start, ctx.end)
    fix = None
    if "fail" in (ed["start"]["status"], ed["end"]["status"]):
        sg = suggest(ctx)
        fix = {"start": sg["start"], "end": sg["end"]} if sg["changed"] else None
    for side, label in (("start", "Awal kalimat"), ("end", "Akhir kalimat")):
        v = ed[side]
        bad = v["status"] == "fail"
        checks.append({"id": f"edge_{side}", "label": label,
                       "status": {"pass": "pass", "fail": "fail"}.get(v["status"], "skip"),
                       "detail": v["label"] + (". 'Rapikan ke kalimat' menggeser ke kalimat utuh terdekat." if bad else ""),
                       "times": [0.0 if side == "start" else round(dur, 2)] if bad else [], "fix": fix if bad else None})
        if bad:
            fix = None                      # satu tombol saran cukup untuk kedua tepi

    # 2) potongan adegan di tepi (frame "berkedip" dari shot lain)
    check_cancel()
    step(0.1, "Cek potongan adegan di awal dan akhir")
    cuts = Q.edge_cuts(ctx.video, ctx.start, ctx.end)
    for side, label in (("start", "Potongan adegan di awal"), ("end", "Potongan adegan di akhir")):
        c = cuts.get(side)
        if c is None:
            checks.append({"id": f"cut_{side}", "label": label, "status": "pass",
                           "detail": "Tidak ada frame dari shot lain di tepi klip."})
            continue
        rel = c - ctx.start
        n = max(1, round((rel if side == "start" else ctx.end - c) * fps))
        # mulai tepat di frame pertama shot baru / berhenti tepat sebelum frame itu
        f2 = ({"start": round(c - 0.3 / fps, 3), "end": ctx.end} if side == "start"
              else {"start": ctx.start, "end": round(c - 0.3 / fps, 3)})
        ef = edges(ctx.words, f2["start"], f2["end"])[side]
        clash = " Saran ini memotong kalimat, jadi pilih mana yang lebih penting." if ef["status"] == "fail" else ""
        checks.append({"id": f"cut_{side}", "label": label, "status": "warn",
                       "detail": (f"{n} frame pertama masih dari shot sebelumnya (pindah shot di {_fmt(rel)})."
                                  if side == "start" else
                                  f"{n} frame terakhir sudah masuk shot berikutnya (pindah shot di {_fmt(rel)}).") + clash,
                       "times": [round(max(0.0, rel), 2)], "fix": f2})

    # 3) frame hitam & beku
    check_cancel()
    step(0.2, "Cek frame hitam dan beku")
    iv = Q.detect_intervals(path)
    black = iv["black"]
    if black:
        f3 = None
        lead = next((b for b in black if b[0] <= 0.05), None)
        tail = next((b for b in black if b[1] >= dur - 0.1), None)
        if lead or tail:
            f3 = {"start": round(ctx.start + (lead[1] if lead else 0.0), 3),
                  "end": round(ctx.start + (tail[0] if tail else dur), 3)}
        checks.append({"id": "black", "label": "Frame hitam", "status": "warn",
                       "detail": ", ".join(f"{_fmt(a)}–{_fmt(b)}" for a, b in black[:6]) +
                                 (" (di tepi klip, bisa dipotong)" if f3 else ""),
                       "times": [round(a, 2) for a, _ in black[:6]], "fix": f3})
    else:
        checks.append({"id": "black", "label": "Frame hitam", "status": "pass", "detail": "Tidak ada."})
    freeze = [(a, b if b is not None else dur) for a, b in iv["freeze"]]
    checks.append({"id": "freeze", "label": "Gambar beku",
                   "status": "warn" if freeze else "pass",
                   "detail": (", ".join(f"{_fmt(a)}–{_fmt(b)} ({b - a:.1f} dtk)" for a, b in freeze[:6])
                              + ". Wajar untuk slide atau layar diam; periksa bila seharusnya bergerak.")
                             if freeze else "Tidak ada.",
                   "times": [round(a, 2) for a, _ in freeze[:6]]})

    # 4) strip frame + wajah
    det = _load_face_detector()
    times = [0.0] + [dur * (i + 0.5) / (frames - 2) for i in range(frames - 2)] + [max(0.0, dur - 1.5 / fps)]
    cap_rect = Q.caption_rect(W, H, cfg.position)
    split_layout = ((ctx.clip.get("layout") or {}).get("mode") or ctx.render_opts.get("layout") or "auto") != "auto"
    vertical_crop = (ctx.render_opts.get("aspect") or cfg.aspect) != "original"
    shots, face_issues = [], {"face_cut": [], "caption_face": [], "no_face": []}
    cap = cv2.VideoCapture(str(path))
    for i, t in enumerate(times):
        check_cancel()
        step(0.3 + 0.45 * i / len(times), f"Cek frame {i + 1}/{len(times)}")
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, img = cap.read()
        if not ok:
            continue
        flags = []
        fs = Q.faces(det, img) if det is not None else []
        big = [f for f in fs if f[2] >= W * 0.04]
        if any(f[0] < W * 0.005 or f[0] + f[2] > W * 0.995 for f in big):
            flags.append("face_cut")
        if cfg.subtitles and not split_layout and any(Q.covered_fraction(f, cap_rect) > Q.FACE_OVERLAP for f in big):
            flags.append("caption_face")
        if det is not None and vertical_crop and not big:
            src = read_frame(ctx.video, ctx.start + t)
            sw = src.shape[1] if src is not None else 1
            if src is not None and any(f[2] >= sw * 0.03 for f in Q.faces(det, src)):
                flags.append("no_face")
        if any(a - 0.02 <= t <= b + 0.02 for a, b in black):
            flags.append("black")
        if any(a <= t <= b for a, b in freeze):
            flags.append("frozen")
        for k in flags:
            if k in face_issues:
                face_issues[k].append(round(t, 2))
        fname = f"f{i:02d}.jpg"
        tw = 180
        th = round(img.shape[0] * tw / img.shape[1])
        cv2.imwrite(str(out_dir / fname), cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA),
                    [cv2.IMWRITE_JPEG_QUALITY, 80])
        shots.append({"t": round(t, 3), "abs": round(ctx.start + t, 3), "file": fname, "flags": flags,
                      "faces": len(big), "edge": "start" if i == 0 else "end" if i == len(times) - 1 else ""})
    cap.release()
    if det is None:
        checks.append({"id": "faces", "label": "Wajah di bingkai", "status": "skip",
                       "detail": "Detektor wajah (YuNet) tidak tersedia."})
    else:
        label = {"face_cut": "wajah terpotong tepi bingkai", "caption_face": "subtitle menutupi wajah",
                 "no_face": "orang di video sumber tidak masuk bingkai"}
        bad = {k: v for k, v in face_issues.items() if v}
        detail = "; ".join(f"{label[k]} di {', '.join(_fmt(t) for t in v[:4])}" for k, v in bad.items())
        tip = ""
        if "caption_face" in bad:
            tip = " Pindahkan posisi subtitle (atas/tengah) di Studio."
        if "no_face" in bad or "face_cut" in bad:
            tip += " Atur kotak wajah di 'Layout klip'."
        checks.append({"id": "faces", "label": "Wajah di bingkai", "status": "warn" if bad else "pass",
                       "detail": (detail.capitalize() + "." + tip) if bad else "Wajah aman di semua frame contoh.",
                       "times": sorted({t for v in bad.values() for t in v})})

    # 5) getar (jitter)
    check_cancel()
    step(0.78, "Cek getar gambar")
    raw = []
    for f in (0.25, 0.5, 0.75):
        raw += Q.sample_shifts(path, dur * f)
    if raw:
        scale = W / Q.SAMPLE_W
        raw = Q.quiet_sample_noise(raw)
        rms, mean = Q.motion_stats([(dx * scale, dy * scale) for dx, dy in raw])
        st, why = Q.judge_motion(Q.flashes_from_shifts(raw), dur, rms, mean)
        checks.append({"id": "jitter", "label": "Getar gambar", "status": "pass" if st == "pass" else "warn",
                       "detail": "Gambar stabil." if st == "pass" else
                                 ("Bingkai bolak-balik melompat (crop wajah terlalu sering pindah)." if "flash" in why
                                  else f"Gambar bergetar halus (RMS {rms:.2f} px). Coba mode crop 'center' atau layout tetap.")})
    else:
        checks.append({"id": "jitter", "label": "Getar gambar", "status": "skip", "detail": "Frame tidak terbaca."})

    # 6) keras suara
    check_cancel()
    step(0.88, "Ukur keras suara")
    lv = Q.measure_loudness(path) if pinfo.get("has_audio") else None
    if lv is None:
        checks.append({"id": "loudness", "label": "Keras suara", "status": "skip", "detail": "Klip tanpa audio."})
    else:
        lufs, peak = lv
        st, why = Q.judge_levels(lufs, peak)
        msg = f"{lufs:.1f} LUFS, puncak {peak:.1f} dBTP (target -14 LUFS, puncak ≤ -1)."
        if st != "pass":
            msg += (" Terlalu pelan." if why.startswith("quiet") else " Terlalu keras." if why.startswith("loud")
                    else " Puncaknya bisa pecah.")
        checks.append({"id": "loudness", "label": "Keras suara", "status": "pass" if st == "pass" else "warn",
                       "detail": msg, "action": "loudnorm" if st != "pass" else ""})

    # 7) durasi
    lo, hi = cfg.min_dur, cfg.max_dur
    d = ctx.duration
    checks.append({"id": "duration", "label": "Durasi", "status": "pass" if lo - 0.5 <= d <= hi + 0.5 else "warn",
                   "detail": f"{d:.1f} dtk" + ("" if lo - 0.5 <= d <= hi + 0.5 else
                                              f" (di luar pengaturan {lo:.0f}–{hi:.0f} dtk)") +
                             (". Lebih dari 60 dtk: TikTok/Reels aman, Shorts maksimal 3 menit." if d > 60 else ".")})

    order = {"fail": 0, "warn": 1, "pass": 2, "skip": 3}
    summary = {k: sum(c["status"] == k for c in checks) for k in order}
    data = {"clip_range": [ctx.start, ctx.end], "mtime": path.stat().st_mtime, "duration": round(dur, 2),
            "fps": fps, "width": W, "height": H, "frames": shots, "checks": checks, "summary": summary,
            "edges": ed}
    _check_path(ctx).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log("Cek frame: " + ", ".join(f"{c['label']}: {c['status']}" for c in checks))
    step(1.0, "Cek frame selesai")
    return load_check(ctx) or data
