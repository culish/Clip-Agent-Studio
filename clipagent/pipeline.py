"""Alur kerja agen: ambil video -> transkrip -> pilih momen -> (terjemah) -> render -> ringkasan."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Settings
from .download import fetch_youtube, is_url, prepare_local
from .render import render_clip
from .selector import select_clips
from .transcript import (group_segments, guess_lang, load_words, save_words, words_from_json3,
                         words_from_whisper, lang_from_caption_source)
from .translate import translate_clip_words
from .utils import ClipAgentError, Cancelled, check_cancel, fmt_ts, log, probe, progress, require_binary


def run_pipeline(cfg: Settings) -> dict:
    """Jalankan seluruh proses. Mengembalikan ringkasan hasil (dipakai web app)."""
    t_begin = time.time()
    require_binary("ffmpeg")
    require_binary("ffprobe")
    cfg.out_dir = Path(cfg.out_dir).expanduser().resolve()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Ambil video
    progress(0.01, "Mengambil video")
    if is_url(cfg.source):
        video, meta, captions, cap_src = fetch_youtube(
            cfg.source, cfg.out_dir, cfg.language, cfg.max_height,
            cfg.cookies, cfg.cookies_from_browser)
    else:
        video, meta = prepare_local(cfg.source, cfg.out_dir)
        captions, cap_src = None, ""
    workdir = cfg.out_dir / meta["id"]
    info = probe(video)
    total = info["duration"] or float(meta.get("duration") or 0)
    log(f"Video: {meta.get('title', '')} — {info['width']}x{info['height']}, {fmt_ts(total)}")
    src_short = min(info["width"], info["height"])
    if src_short < 720:
        log(f"Catatan: video sumber hanya {src_short}p, jadi klip 9:16 keluar 720x1280 dan akan terlihat buram. "
            "Pakai sumber 1080p agar klip 1080x1920 tajam.")
    result = {"video_id": meta["id"], "title": meta.get("title", ""), "url": meta.get("url", ""),
              "clips": [], "plan_only": cfg.plan_only}

    # 2) Transkrip bertimestamp per kata (cache di transcript.json)
    check_cancel()
    progress(0.32, "Menyiapkan transkrip")
    tpath = workdir / "transcript.json"
    words, tsrc, tlang = [], "", ""
    if tpath.is_file():
        words, tsrc, tlang = load_words(tpath)
        if cfg.force_whisper and not tsrc.startswith("whisper"):
            words = []
    if not words:
        if captions and not cfg.force_whisper:
            words, tsrc = words_from_json3(captions), cap_src
            tlang = lang_from_caption_source(cap_src) or guess_lang(words)
        if not words:
            words, tlang = words_from_whisper(video, cfg.whisper_model, cfg.language or None,
                                              prog_range=(0.32, 0.45))
            tsrc = f"whisper-{cfg.whisper_model}:{tlang}"
        save_words(words, tpath, tsrc, tlang)
    segments = group_segments(words)
    log(f"Transkrip: {len(words)} kata, {len(segments)} segmen (sumber: {tsrc}, bahasa: {tlang or '?'})")

    # 3) Rencana klip: dari file rencana (hasil edit manual) atau dipilih agen
    check_cancel()
    progress(0.46, "Agen memilih momen terbaik")
    plan_path = workdir / "plan.json"
    if cfg.plan_file:
        plan = json.loads(Path(cfg.plan_file).read_text(encoding="utf-8"))
        clips = plan["clips"] if isinstance(plan, dict) else plan
        for i, c in enumerate(clips, 1):
            c["start"], c["end"] = float(c["start"]), float(c["end"])
            c["duration"] = round(c["end"] - c["start"], 2)
            c["rank"] = i
            c.pop("file", None)
        log(f"Memakai rencana dari {cfg.plan_file} ({len(clips)} klip)")
    else:
        clips = select_clips(cfg, meta, words, segments, total)
    try:                                    # skor pembuka & judul (youtube-agent-skill, lihat clipagent/ytkit)
        from .ytkit import score_clips
        score_clips(clips, words)
    except Exception as exc:                # noqa: BLE001 - skor hanya tambahan, jangan gagalkan render
        log(f"Skor hook/judul dilewati ({type(exc).__name__}: {str(exc)[:80]})")
    _save_plan(plan_path, meta, clips, cfg)

    print()
    for c in clips:
        print(f"  #{c['rank']:02d} [{fmt_ts(c['start'])}–{fmt_ts(c['end'])}, {c['duration']:.0f} dtk, "
              f"skor {_score(c)}] {c.get('title', '')}")
    print()

    if cfg.plan_only:
        log(f"Rencana tersimpan di {plan_path}")
        log(f'Edit bila perlu, lalu render dengan: python clipper.py "{cfg.source}" --plan "{plan_path}"')
        result["clips"] = clips
        return result

    # 4) Terjemahan subtitle (mis. ke Inggris untuk penonton AS)
    sub_words: dict[int, list] = {}
    target = cfg.sub_lang if cfg.sub_lang not in ("", "auto") else ""
    if target and cfg.subtitles and target != (tlang or ""):
        check_cancel()
        progress(0.55, "Menerjemahkan subtitle")
        sub_words = translate_clip_words(cfg, words, [(c["start"], c["end"]) for c in clips],
                                         target, workdir / f"translations_{target}.json")
        if sub_words:
            log(f"Subtitle {target.upper()} siap untuk {len(sub_words)}/{len(clips)} klip "
                "(waktu per kata diperkirakan dari kalimat aslinya).")
    elif target and target == tlang:
        log(f"Ucapan sudah berbahasa {target.upper()}; subtitle tidak perlu diterjemahkan.")

    # 5) Render
    clips_dir = workdir / "clips"
    n = len(clips)
    done = 0
    for i, c in enumerate(clips):
        check_cancel()
        log(f"Render klip {c['rank']}/{n}: {c.get('title', '')}")
        base = 0.6 + 0.4 * i / n
        progress(base, f"Render klip {i + 1}/{n}")
        try:
            out = render_clip(cfg, video, info, c, words, clips_dir, sub_words=sub_words.get(i),
                              on_frac=lambda f, b=base: progress(b + 0.4 / n * f, f"Render klip {i + 1}/{n}"))
        except Cancelled:
            raise
        except ClipAgentError as exc:
            log(f"  GAGAL: {exc}")
            continue
        c["file"] = out.name
        c["sub_lang"] = target if i in sub_words else (tlang or "")
        c["src_height"] = src_short
        done += 1

    attribution = _attribution(meta)
    for c in clips:
        if attribution:
            c["credit"] = attribution
    _save_plan(plan_path, meta, clips, cfg)
    _write_summary(clips_dir, meta, clips, tsrc)
    progress(1.0, "Selesai")
    log(f"Selesai: {done} klip dalam {time.time() - t_begin:.0f} dtk -> {clips_dir}")
    result["clips"] = clips
    return result


def _save_plan(path: Path, meta: dict, clips: list[dict], cfg: Settings) -> None:
    opts = {k: getattr(cfg, k) for k in ("audience", "sub_lang", "anim", "font", "aspect", "crop", "layout", "split",
                                         "position", "hook_overlay", "progress_bar", "zoom")}
    path.write_text(json.dumps({"source": meta, "render": opts, "clips": clips,
                                "updated": time.strftime("%Y-%m-%d %H:%M:%S")},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def _attribution(meta: dict) -> str:
    """Kredit otomatis untuk video berlisensi Creative Commons (wajib menyebut sumber)."""
    lic = (meta.get("license") or "").lower()
    if "creative commons" not in lic:
        return ""
    return f"Source: {meta.get('channel') or 'YouTube'} — {meta.get('url', '')} (CC BY)"


def _score(c: dict) -> str:
    v = c.get("score")
    return f"{v:.0f}" if isinstance(v, (int, float)) else "-"


def _write_summary(clips_dir: Path, meta: dict, clips: list[dict], tsrc: str) -> None:
    clips_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Klip dari: {meta.get('title', '')}", "",
             f"Sumber: {meta.get('url', '')}  ", f"Transkrip: {tsrc}  ",
             f"Lisensi: {meta.get('license') or 'standar YouTube'}", ""]
    for c in clips:
        tags = " ".join(c.get("hashtags") or [])
        lines += [
            f"## {c['rank']:02d}. {c.get('title', '')}", "",
            f"- **Waktu:** {fmt_ts(c['start'])}–{fmt_ts(c['end'])} ({c['duration']:.0f} dtk), skor {_score(c)}",
            *([f"- **Kalimat pembuka:** {c['opening']} (skor hook {c['hook_score']}"
                + (f"; perbaiki {c['hook_tip']}" if c.get("hook_tip") else "") + ")"] if c.get("opening") else []),
            *([f"- **Skor judul:** {c['title_score']}" + (f" ({', '.join(c['title_issues'])})" if c.get("title_issues") else "")]
              if c.get("title_score") is not None else []),
            f"- **File:** {c.get('file', '(gagal dirender)')}",
            f"- **Hook:** {c.get('hook', '')}",
            f"- **Alasan dipilih:** {c.get('reason', '')}",
            f"- **Caption:** {c.get('caption', '')} {tags}".rstrip(),
        ]
        if c.get("credit"):
            lines.append(f"- **Kredit (wajib dicantumkan):** {c['credit']}")
        lines.append("")
    (clips_dir / "RINGKASAN.md").write_text("\n".join(lines), encoding="utf-8")
