"""Editor otomatis untuk klip yang sudah jadi: b-roll, musik latar dengan ducking, dan caption.

AI memilih 2–5 momen di klip yang cocok diberi b-roll (video stok Pexels/Pixabay atau gambar AI), lalu klip
dirender ulang dengan Remotion: video asli + potongan b-roll + caption karaoke + musik yang otomatis
mengecil saat ada orang bicara.
"""
from __future__ import annotations

import re
import time

from . import broll, music, videogen
from .animation import _AssetServer, _run_remotion, _subtitle_words, resolve_style
from .creative import ClipContext, clean_clip, plan_segments, save_plan
from .gemini import QuotaError
from .imagegen import ImageGen
from .llm import LLMClient
from .utils import ClipAgentError, check_cancel, log, probe, progress

SOURCES = {"stock": "Video stok (Pexels/Pixabay)", "ai_image": "Gambar AI", "none": "Tanpa b-roll"}

BR_SYSTEM = "You are a short-form video editor. Answer ONLY with valid JSON."
BR_PROMPT = """Clip title: {title}
Sentences (index, seconds from clip start, text):
{lines}

Pick {n} moments where a short B-roll cutaway would make the clip more engaging (show what is being talked about).
Rules: never in the first 2.5 seconds; at least 3 seconds apart; prefer concrete nouns and actions.
For each: "sentence" (index), "keywords" (2–4 English words to search stock footage),
"prompt" (one English sentence describing an illustration for this moment).
Also choose "mood" for background music: santai, semangat, inspiratif, dramatis, misteri or teknologi.
JSON: {{"broll": [{{"sentence": 0, "keywords": "", "prompt": ""}}], "mood": ""}}"""

_STOP = set("the a an and or but to of in on for with is are was were be been it this that you your we our i my me "
            "they them he she his her so just like really very what when where how why not do does did have has "
            "had can could would should will about from at as by if then than there here".split())


def _heuristic(segs: list[dict], n: int) -> list[dict]:
    out, last = [], -10.0
    for i, s in enumerate(segs):
        if s["start"] < 2.5 or s["start"] - last < 3 or not s["text"]:
            continue
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", s["text"]) if w.lower() not in _STOP]
        if not words:
            continue
        kw = " ".join(sorted(words, key=len, reverse=True)[:2])
        out.append({"sentence": i, "keywords": kw, "prompt": s["text"][:140]})
        last = s["start"]
        if len(out) >= n:
            break
    return out


def plan_broll(ctx: ClipContext, n: int) -> tuple[list[dict], str]:
    segs = plan_segments(ctx.words, ctx.start, ctx.end)
    picks, mood = [], "santai"
    try:
        cfg = ctx.settings()
        if cfg.provider != "heuristic":
            lines = "\n".join(f"[{i}] {s['start']:.1f}-{s['end']:.1f}: {s['text']}" for i, s in enumerate(segs))
            client = LLMClient(cfg.provider, cfg.model, cfg.base_url, cfg.api_key, fallbacks=cfg.fallback_models)
            data = client.complete_json(BR_SYSTEM, BR_PROMPT.format(title=ctx.clip.get("title", ""), lines=lines, n=n),
                                         list_key="broll")
            for b in data.get("broll") or []:
                try:
                    i = int(b.get("sentence"))
                except (TypeError, ValueError):
                    continue
                if 0 <= i < len(segs) and segs[i]["start"] >= 2.5:
                    picks.append({"sentence": i, "keywords": str(b.get("keywords") or "")[:60],
                                  "prompt": str(b.get("prompt") or "")[:300]})
            if data.get("mood") in music.MOODS:
                mood = data["mood"]
    except (ClipAgentError, ValueError) as exc:
        log(f"AI tidak tersedia untuk memilih b-roll ({str(exc).splitlines()[0][:100]}); memakai aturan sederhana.")
    if not picks:
        picks = _heuristic(segs, n)
    # rapikan: urut, jarak minimal 3 detik, maksimal n
    picks.sort(key=lambda b: segs[b["sentence"]]["start"])
    out, last = [], -10.0
    for b in picks:
        s = segs[b["sentence"]]
        if s["start"] - last < 3:
            continue
        dur = min(3.0, max(1.6, s["end"] - s["start"] - 0.3))
        start = s["start"] + 0.25
        if start + dur > ctx.duration - 0.5:
            continue
        out.append({**b, "start": round(start, 2), "end": round(start + dur, 2)})
        last = start
        if len(out) >= n:
            break
    return out, mood


def auto_edit(ctx: ClipContext, opts: dict) -> dict:
    source = opts.get("broll") if opts.get("broll") in SOURCES else "stock"
    count = max(0, min(6, int(opts.get("count") or max(2, round(ctx.duration / 10)))))
    clean = clean_clip(ctx)
    cinfo = probe(clean)
    W, H = cinfo["width"], cinfo["height"]
    aspect = "9:16" if H > W else "16:9"
    adir = ctx.cdir / "edit"
    adir.mkdir(parents=True, exist_ok=True)
    progress(0.34, "Memilih momen b-roll")
    plans, mood = plan_broll(ctx, count) if source != "none" and count else ([], "santai")
    if source == "stock" and not broll.available():
        log("Key video stok (PEXELS_API_KEY/PIXABAY_API_KEY) belum diisi; b-roll memakai gambar AI." if ImageGen.from_env() else
            "Key video stok dan GEMINI_API_KEY belum diisi; klip diedit tanpa b-roll.")
        source = "ai_image" if ImageGen.from_env() else "none"
    gen = ImageGen.from_env() if source == "ai_image" else None
    used: set[int] = set()
    cuts, credits = [], []
    for k, b in enumerate(plans if source != "none" else []):
        check_cancel()
        progress(0.36 + 0.24 * k / max(1, len(plans)), f"Menyiapkan b-roll {k + 1}/{len(plans)}")
        dur = b["end"] - b["start"]
        try:
            if source == "stock":
                got = broll.fetch(b["keywords"], dur, aspect, adir, used)
                if not got:
                    continue
                fit = videogen.fit_clip(got["path"], dur, W, H, adir / f"fit_{got['path'].stem}_{int(dur * 10)}.mp4")
                cuts.append({**b, "video": fit})
                credits.append(got["credit"])
            elif gen is not None:
                import hashlib

                import cv2
                prompt = (f"{b['prompt'] or b['keywords']}. Cinematic, vivid, high detail, vertical composition. "
                          "No text, no captions, no logos, no watermarks.")
                p = adir / f"img_{hashlib.sha1((prompt + aspect).encode()).hexdigest()[:12]}.png"
                if not p.is_file():
                    cv2.imwrite(str(p), gen.generate(prompt, aspect))
                cuts.append({**b, "image": p})
        except QuotaError as exc:
            log(f"  {exc} B-roll gambar AI dihentikan.")
            gen = None
        except ClipAgentError as exc:
            log(f"  b-roll {k + 1} dilewati: {str(exc)[:120]}")
    log(f"B-roll: {len(cuts)} potongan ({SOURCES[source]}).")
    # timeline: klip asli diselingi b-roll
    timeline, t = [], 0.0
    for c in cuts:
        if c["start"] > t + 0.05:
            timeline.append({"kind": "clip", "start": t, "end": c["start"]})
        timeline.append({"kind": "broll", **c})
        t = c["end"]
    if t < ctx.duration - 0.05:
        timeline.append({"kind": "clip", "start": t, "end": ctx.duration})
    words = _subtitle_words(ctx, opts, [{"start": 0.0, "end": ctx.duration}])
    look = resolve_style({"preset": opts.get("preset") or "faceless"})
    style = dict(look["style"], transitionSec=0.2)
    if opts.get("subtitles") is False:
        style["captions"] = "none"
    elif style["captions"] == "bubble":
        style["captions"] = "karaoke"
    speech = [[w.start - ctx.start, w.end - ctx.start] for w in ctx.words if w.end > ctx.start and w.start < ctx.end]
    choice = opts.get("music") or "auto"
    mtrack = music.track(choice, ctx.duration + 0.5, adir, mood)
    with _AssetServer(ctx.out_dir) as srv:
        scenes = []
        for seg in timeline:
            dur = seg["end"] - seg["start"]
            sc = {"start": round(seg["start"], 3), "dur": round(dur, 3), "heading": "", "bubble": "", "sfx": "",
                  "camera": "static", "transition": "fade" if seg["kind"] == "broll" else "none"}
            if seg["kind"] == "clip":
                sc.update(video=srv.url(clean), videoFrom=seg["start"])
            elif seg.get("video"):
                sc.update(video=srv.url(seg["video"]), videoFrom=0)
            else:
                sc.update(image=srv.url(seg["image"]), camera="zoom_in")
            scenes.append(sc)
        # transisi "fade" berlaku MENUJU adegan berikutnya: masuk b-roll juga dipudar
        for i in range(len(scenes) - 1):
            if timeline[i + 1]["kind"] == "broll" or timeline[i]["kind"] == "broll":
                scenes[i]["transition"] = "fade"
        props = {"fps": 30, "width": W, "height": H, "duration": round(ctx.duration, 3),
                 "audio": srv.url(clean) if cinfo["has_audio"] else None,
                 "audioParts": [{"at": 0, "from": 0, "to": round(ctx.duration, 3)}], "scenes": scenes, "words": words,
                 "hook": (ctx.clip.get("title") or "") if opts.get("hook_overlay", True) else "",
                 "progressBar": bool(opts.get("progress_bar", False)), "style": style, "speech": speech}
        if mtrack:
            props["music"] = {"src": srv.url(mtrack), "volume": float(opts.get("music_volume") or 0.3), "duck": 0.25}
        out = ctx.workdir / "clips" / f"{ctx.slug}__edit.mp4"
        tmp = out.with_name(out.stem + ".part.mp4")
        try:
            _run_remotion({"mode": "video", "props": props, "output": str(tmp.resolve()), "crf": 20},
                          0.62, 0.99, "Merender dengan Remotion")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    tmp.replace(out)
    label = "Edit otomatis: " + ", ".join(x for x in (f"{len(cuts)} b-roll" if cuts else "", "musik" if mtrack else "",
                                                      "caption" if style["captions"] != "none" else "") if x)
    entry = {"kind": "autoedit", "file": out.name, "label": label, "scenes": len(scenes), "duration": round(ctx.duration, 2),
             "broll": len(cuts), "credits": sorted(set(credits)), "music": choice if mtrack else "none",
             "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    ctx.clip["extras"] = [x for x in ctx.clip.get("extras", []) if x.get("file") != out.name] + [entry]
    save_plan(ctx)
    progress(1.0, "Edit otomatis selesai")
    return {**entry, "video_url": ctx.url(out)}
