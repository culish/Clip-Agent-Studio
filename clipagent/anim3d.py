"""Animasi 3D engineering ("cara kerja ...") dengan Blender, kodenya ditulis AI.

Alur (mengikuti pola video 3D edukasi/engineering yang sering viral):
1. Riset & bedah: topik, naskah sendiri, atau video/artikel rujukan dibaca, lalu AI memetakan HOOK -> PROBLEM ->
   ENGINEERING SOLUTION (langkah demi langkah) -> CTA, ditambah sudut pandang sendiri agar bukan konten duplikat.
2. Naskah + production plan per adegan: narasi, aksi visual 3D, objek, kamera, efek suara, label di layar.
3. QC naskah: panjang hook, urutan struktur, tempo kata per detik, ejaan istilah teknis untuk suara AI
   (ditulis fonetik khusus untuk TTS; caption tetap ejaan asli), kemiripan dengan rujukan.
4. Suara narasi (Gemini/Edge) dan musik latar (generator bawaan sesuai suasana).
5. Kode Python Blender per adegan ditulis AI (Claude Code, Codex, Gemini CLI, Qwen Code, opencode, atau AI di
   Pengaturan) memakai kit clipagent/anim3d_kit/kit.py, diperiksa (aturan keamanan + uji jalan + frame kosong),
   diperbaiki otomatis bila error, lalu dirender Blender di komputer sendiri (gratis, GPU sendiri).
6. Digabung oleh Remotion lewat pipeline "Buat video": caption, musik yang mengecil saat narasi, transisi.
"""
from __future__ import annotations

import ast
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .utils import ClipAgentError, check_cancel, extract_json, log, progress

KIT_DIR = Path(__file__).with_name("anim3d_kit")
VERSION = "b1"                    # ubah bila prompt/kit berubah agar cache kode lama tidak dipakai
FPS = 30
STYLES = {
    "studio": {"name": "Studio terang", "desc": "Latar abu-abu muda bersih seperti video 'cara kerja' populer"},
    "blueprint": {"name": "Cetak biru", "desc": "Latar biru gelap, label terang, kesan teknik"},
    "warm": {"name": "Hangat", "desc": "Latar krem lembut, cocok untuk rumah, dapur, bangunan"},
}
QUALITIES = {
    "fast": {"name": "Cepat (Workbench)", "desc": "Hitungan detik per adegan; tampilan model berwarna tanpa pantulan",
             "spf": 0.05},
    "good": {"name": "Bagus (EEVEE)", "desc": "Cahaya dan bayangan halus; butuh kartu grafis (GPU)", "spf": 0.6},
    "best": {"name": "Terbaik (Cycles)", "desc": "Paling realistis, paling lama; GPU NVIDIA/AMD/Apple disarankan",
             "spf": 4.0},
}
SCALES = {100: "1080p", 67: "720p (lebih cepat)", 50: "540p (draf)"}
LENGTHS = [30, 45, 60]
ROLES = ("hook", "problem", "solution", "cta")
WPS = {"id": 2.3, "en": 2.5}          # kata per detik narasi yang nyaman
EXAMPLES = ["Cara kerja septic tank dua ruang", "Kenapa kolam renang tidak mengapung saat dikuras",
            "Cara kerja rem cakram motor", "Bagaimana turbo menambah tenaga mesin", "Cara kerja water heater tenaga surya",
            "Kenapa gedung tinggi tidak roboh saat gempa"]


# ====================================================================== Blender
def _settings() -> dict:
    from . import film
    return film.get_settings()


def find_blender() -> str | None:
    """Lokasi blender(.exe): pengaturan, variabel BLENDER_BIN, PATH, lalu lokasi pemasangan umum."""
    cand = [(_settings().get("blender") or "").strip(), os.getenv("BLENDER_BIN", ""), os.getenv("BLENDER_PATH", "")]
    for c in cand:
        if c:
            p = os.path.expanduser(c)
            if Path(p).is_dir():
                for name in ("blender.exe", "blender", "Contents/MacOS/Blender"):
                    if (Path(p) / name).is_file():
                        return str(Path(p) / name)
            if Path(p).is_file():
                return p
            found = shutil.which(p)
            if found:
                return found
    found = shutil.which("blender")
    if found:
        return found
    pats = []
    for root in (os.getenv("ProgramFiles", r"C:\Program Files"), os.getenv("ProgramFiles(x86)", ""),
                 os.path.expanduser("~")):
        if root:
            pats += [os.path.join(root, "Blender Foundation", "Blender*", "blender.exe"),
                     os.path.join(root, "Steam", "steamapps", "common", "Blender", "blender.exe")]
    pats += [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation\Blender*\blender.exe"),
             "/Applications/Blender*.app/Contents/MacOS/Blender", "/snap/bin/blender", "/usr/bin/blender",
             "/usr/local/bin/blender", os.path.expanduser("~/blender*/blender"),
             os.path.expanduser("~/Applications/Blender*.app/Contents/MacOS/Blender")]
    hits = []
    for pat in pats:
        hits += [h for h in glob.glob(pat) if Path(h).is_file()]
    if hits:
        return sorted(hits, key=lambda h: [int(x) for x in re.findall(r"\d+", h)] or [0])[-1]
    return None


def _is_py(exe: str) -> bool:
    """Uji tanpa Blender: python yang punya modul bpy (pip install bpy) juga bisa menjalankan runner."""
    return Path(exe).name.lower().startswith("python")


_VER: dict[str, str] = {}


def blender_version(exe: str) -> str:
    key = f"{exe}:{Path(exe).stat().st_mtime if Path(exe).exists() else 0}"
    if key in _VER:
        return _VER[key]
    try:
        cmd = [exe, "-c", "import bpy;print('Blender', bpy.app.version_string)"] if _is_py(exe) else [exe, "--version"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace").stdout
        m = re.search(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", out or "")
        _VER[key] = m.group(1) if m else ""
    except (OSError, subprocess.SubprocessError):
        _VER[key] = ""
    return _VER[key]


def status() -> dict:
    exe = find_blender()
    ver = blender_version(exe) if exe else ""
    ok = bool(exe and ver)
    major = tuple(int(x) for x in ver.split(".")[:2]) if ver else (0, 0)
    hint = ""
    if not exe:
        hint = ("Blender belum ditemukan. Pasang gratis dari blender.org (versi 4.2 atau lebih baru), lalu buka lagi "
                "halaman ini. Bila dipasang di folder lain, isi lokasinya di bawah.")
    elif not ver:
        hint = "File Blender ditemukan tetapi tidak bisa dijalankan. Periksa lokasinya."
    elif major < (3, 6):
        hint = f"Blender {ver} terlalu lama. Pakai versi 4.2 atau lebih baru."
        ok = False
    return {"found": ok, "path": exe or "", "version": ver, "hint": hint}


def public() -> dict:
    from . import agents, reels
    return {"styles": STYLES, "qualities": {k: {"name": v["name"], "desc": v["desc"]} for k, v in QUALITIES.items()},
            "scales": SCALES, "lengths": LENGTHS, "engines": reels.ENGINES, "agents": agents.public(),
            "blender": status(), "examples": EXAMPLES, "samples": {k: f"/web/anim3d/{k}.jpg" for k in STYLES}}


def save_blender_path(path: str) -> dict:
    from . import film
    st = film.get_settings()
    st["blender"] = str(path or "").strip()[:400]
    film.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    film.SETTINGS_PATH.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return status()


# ====================================================================== naskah & production plan
PLAN_SYSTEM = """You are the director and head writer of a faceless channel that makes viral short 3D engineering
explainer videos ("how it works" animations: a clean 3D model, cutaways, flowing water/air, moving parts, labels).
You research the topic, break down any reference, and write an ORIGINAL script with its production plan.

FORMULA (strict order):
1. HOOK: one surprising, funny or contrarian sentence that makes viewers need the answer. Max {hook_words} words.
   Example (Indonesian): "Kalau kamu gali lubang buat nampung kotoran WC, selamat, kamu baru bikin sumur racun."
2. PROBLEM: 1-2 scenes. What goes wrong with the naive way (show it failing).
3. ENGINEERING SOLUTION: 3-5 scenes, ONE clear visual step per scene, cause -> effect, physically correct.
4. CTA: one short interactive line that invites comments (e.g. "Habis ini mau kita bongkar apa lagi?").

RULES
- Language of narration, labels, title, description: {lang_name}. Natural spoken style, short sentences.
- Total narration about {words} words for a {seconds}-second video ({wps} words per second). 5-8 scenes.
- Every visual must be buildable from simple 3D parts: boxes, tanks, walls, cylinders, pipes, tubes, gears, springs,
  spheres, cones, arrows, text labels, liquid levels that rise/fall, particles that flow along a path or settle,
  cutaway sections, exploded views, rotating/oscillating parts, camera moves. NO people, animals, faces, hands,
  brand logos, readable screens or photoreal textures.
- Keep one consistent model across scenes (same parts, sizes, colours) so the video feels like one continuous build.
- Facts must be correct; prefer concrete numbers (sizes, pressures, temperatures) that an engineer would accept.
- If a reference is given: do NOT copy its wording or order of jokes. Analyse it, then write a new script with your own
  angle (a different hook, an extra insight, a local example, a common mistake) so it is not duplicate content.
- "pronunciation": technical terms, abbreviations, numbers with units or foreign words that a text-to-speech voice in
  {lang_name} would likely misread, with a phonetic respelling ("say") written the way it should be spoken
  (e.g. "PVC" -> "pe-ve-ce", "inconel" -> "in-ko-nel", "10 bar" -> "sepuluh bar"). Empty list if none.

Answer with JSON only:
{{"title": "max 70 chars, curiosity", "description": "2-3 sentences for YouTube/TikTok", "hashtags": ["5-8 tags without #"],
  "mood": "one of: {moods}",
  "analysis": {{"hook": "...", "problem": "...", "solution_steps": ["..."], "cta": "...",
               "unique_angle": "what makes THIS video original"}},
  "voice_style": "e.g. calm deep male narrator, tutorial pace",
  "music_prompt": "e.g. upbeat ambient science background, subtle synth beat",
  "scenes": [{{"role": "hook|problem|solution|cta", "narration": "...", "label": "on-screen label, max 4 words",
              "visual": "precise 3D action: what is built, what moves, where the camera looks",
              "objects": ["concrete tank 3x1.5x1.4 m", "..."], "camera": "e.g. 3/4 view from front-left, slow push in",
              "sfx": "e.g. water gurgle"}}],
  "pronunciation": [{{"word": "...", "say": "..."}}]}}"""


def _plan_user(material: dict) -> str:
    parts = []
    if material.get("topic"):
        parts.append("TOPIC: " + material["topic"])
    if material.get("script"):
        parts.append("USER SCRIPT (keep its meaning and most of its words; only split it into scenes, tighten it, "
                     "and add the 3D production plan):\n" + material["script"])
    src = material.get("source") or {}
    if src:
        parts.append("REFERENCE (analyse and break down, never copy):\n" +
                     json.dumps({k: (src.get(k) or "")[:6000 if k == "text" else 400]
                                 for k in ("title", "site", "description", "text")}, ensure_ascii=False))
    if material.get("angle"):
        parts.append("CREATOR'S OWN ANGLE / DIRECTION: " + material["angle"])
    return "\n\n".join(parts) + "\n\nWrite the JSON now."


def _words(t: str) -> int:
    return len(re.findall(r"\w+", t or ""))


def clean_plan(data: dict, seconds: int, lang: str) -> tuple[dict, list[str]]:
    from . import music
    probs: list[str] = []
    if not isinstance(data, dict):
        return {}, ["The answer is not a JSON object."]
    scenes = []
    for sc in data.get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        narr = re.sub(r"\s+", " ", str(sc.get("narration") or "")).strip()
        if not narr:
            continue
        role = str(sc.get("role") or "").lower().strip()
        role = role if role in ROLES else "solution"
        objects = [str(o)[:120] for o in (sc.get("objects") or []) if str(o).strip()][:12]
        scenes.append({"role": role, "narration": narr[:600], "label": " ".join(str(sc.get("label") or "").split()[:5])[:48],
                       "visual": str(sc.get("visual") or "").strip()[:900], "objects": objects,
                       "camera": str(sc.get("camera") or "").strip()[:200], "sfx": str(sc.get("sfx") or "").strip()[:120]})
    if len(scenes) < 4:
        probs.append(f"Write 5-8 scenes (got {len(scenes)}).")
    if scenes:
        if scenes[0]["role"] != "hook":
            probs.append("The first scene must be the HOOK (role 'hook').")
        if scenes[-1]["role"] != "cta":
            probs.append("The last scene must be the CTA (role 'cta').")
        if sum(s["role"] == "solution" for s in scenes) < 2:
            probs.append("Show the engineering solution step by step in at least 3 'solution' scenes.")
        if any(not s["visual"] for s in scenes):
            probs.append("Every scene needs a concrete 'visual' description.")
        hook_n = _words(scenes[0]["narration"])
        if hook_n > 24:
            probs.append(f"The hook has {hook_n} words; keep it to one punchy sentence under 22 words.")
    budget = int(seconds * WPS.get(lang, 2.4))
    total = sum(_words(s["narration"]) for s in scenes)
    if scenes and not (budget * 0.65 <= total <= budget * 1.35):
        probs.append(f"Total narration is {total} words; the video needs about {budget} words ({seconds} s).")
    pron = []
    for p in data.get("pronunciation") or []:
        if isinstance(p, dict) and str(p.get("word") or "").strip() and str(p.get("say") or "").strip():
            w, s = str(p["word"]).strip()[:40], str(p["say"]).strip()[:60]
            if w.lower() != s.lower():
                pron.append({"word": w, "say": s})
    an = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    mood = str(data.get("mood") or "").strip().lower()
    plan = {"title": str(data.get("title") or (scenes[0]["label"] if scenes else "Cara kerjanya"))[:90].strip(),
            "description": str(data.get("description") or "")[:600].strip(),
            "hashtags": [re.sub(r"[^\w]", "", str(h))[:30] for h in (data.get("hashtags") or []) if str(h).strip()][:10],
            "mood": mood if mood in music.MOODS else "semangat" if "semangat" in music.MOODS else next(iter(music.MOODS)),
            "analysis": {"hook": str(an.get("hook") or "")[:300], "problem": str(an.get("problem") or "")[:400],
                         "solution_steps": [str(x)[:200] for x in (an.get("solution_steps") or [])][:8],
                         "cta": str(an.get("cta") or "")[:200], "unique_angle": str(an.get("unique_angle") or "")[:400]},
            "voice_style": str(data.get("voice_style") or "")[:120], "music_prompt": str(data.get("music_prompt") or "")[:200],
            "scenes": scenes[:9], "pronunciation": pron[:20]}
    return plan, probs


def say_text(narration: str, pron: list[dict]) -> str:
    """Narasi untuk TTS: istilah teknis diganti ejaan fonetiknya (caption tetap memakai ejaan asli)."""
    out = narration
    for p in pron or []:
        out = re.sub(rf"(?<!\w){re.escape(p['word'])}(?!\w)", p["say"], out, flags=re.IGNORECASE)
    return out


def qc_report(plan: dict, lang: str, seconds: int, source_text: str = "") -> list[dict]:
    """Pemeriksaan naskah sebelum render (hook, struktur, tempo, ejaan TTS, orisinalitas)."""
    from .remake import similarity
    sc = plan.get("scenes") or []
    out = []
    hook = sc[0]["narration"] if sc else ""
    hn = _words(hook)
    out.append({"id": "hook", "label": "Hook", "status": "pass" if 0 < hn <= 22 else "warn",
                "detail": f"{hn} kata: “{hook[:140]}”" + ("" if hn <= 22 else " Terlalu panjang untuk 2 detik pertama.")})
    roles = [s["role"] for s in sc]
    order_ok = bool(roles) and roles[0] == "hook" and roles[-1] == "cta" and roles.count("solution") >= 2
    out.append({"id": "structure", "label": "Struktur", "status": "pass" if order_ok else "warn",
                "detail": " → ".join({"hook": "Hook", "problem": "Masalah", "solution": "Solusi", "cta": "CTA"}[r] for r in roles)})
    total = sum(_words(s["narration"]) for s in sc)
    est = total / WPS.get(lang, 2.4)
    ok = abs(est - seconds) <= seconds * 0.25
    out.append({"id": "pacing", "label": "Tempo narasi", "status": "pass" if ok else "warn",
                "detail": f"{total} kata ≈ {est:.0f} dtk untuk target {seconds} dtk" +
                          ("" if ok else (" (terlalu padat, suara akan terburu-buru)" if est > seconds else " (terlalu sedikit)"))})
    fast = [i + 1 for i, s in enumerate(sc) if _words(s["narration"]) / max(1.0, 9.0) > 3.2]
    if fast:
        out.append({"id": "scene_pace", "label": "Adegan padat", "status": "warn",
                    "detail": "Adegan " + ", ".join(map(str, fast)) + " punya narasi panjang; animasinya ikut lama."})
    pr = plan.get("pronunciation") or []
    out.append({"id": "tts", "label": "Ejaan suara AI", "status": "pass",
                "detail": ("; ".join(f"{p['word']} → dibaca “{p['say']}”" for p in pr[:8]) +
                           ". Caption tetap memakai ejaan asli.") if pr else "Tidak ada istilah yang perlu dieja khusus."})
    if source_text:
        script = " ".join(s["narration"] for s in sc)
        ratio, shared = similarity(script, source_text)
        out.append({"id": "original", "label": "Orisinalitas", "status": "pass" if ratio < 0.12 else "warn",
                    "detail": f"Kemiripan dengan rujukan {ratio * 100:.0f}%" +
                              (". Aman dari konten duplikat." if ratio < 0.12 else
                               ". Terlalu mirip; tambahkan sudut pandang sendiri lalu buat ulang.") +
                              (f" Contoh frasa sama: “{shared[0]}”" if shared and ratio >= 0.12 else "")})
    if (plan.get("analysis") or {}).get("unique_angle"):
        out.append({"id": "angle", "label": "Sudut pandang", "status": "pass", "detail": plan["analysis"]["unique_angle"]})
    return out


def write_plan(material: dict, *, seconds: int, lang: str, engine: str, out_dir: Path) -> dict:
    from . import music, reels
    audience = "us" if lang == "en" else "id"
    system = PLAN_SYSTEM.format(hook_words=20, lang_name="English" if lang == "en" else "Bahasa Indonesia",
                                words=int(seconds * WPS.get(lang, 2.4)), seconds=seconds, wps=WPS.get(lang, 2.4),
                                moods=", ".join(music.MOODS))
    prompt = _plan_user(material)
    data = reels.ai_json(engine, system, prompt, out_dir, audience)
    plan, probs = clean_plan(data, seconds, lang)
    if probs:
        log("  Naskah diperbaiki: " + "; ".join(probs)[:300])
        fix = (prompt + "\n\nYOUR PREVIOUS ANSWER:\n" + json.dumps(data, ensure_ascii=False)[:12000] +
               "\n\nFix these problems and answer with the full corrected JSON:\n- " + "\n- ".join(probs))
        try:
            plan2, probs2 = clean_plan(reels.ai_json(engine, system, fix, out_dir, audience), seconds, lang)
            if plan2.get("scenes") and len(probs2) <= len(probs):
                plan = plan2
        except ClipAgentError as exc:
            log(f"  Perbaikan naskah dilewati: {str(exc)[:160]}")
    if len(plan.get("scenes") or []) < 2:
        raise ClipAgentError("AI tidak memberi naskah yang bisa dipakai. Coba lagi atau pilih penulis lain.")
    return plan


# ====================================================================== kode Blender
CODE_SYSTEM = """You are a senior technical 3D artist who writes Blender Python for short vertical engineering explainer
videos. Each scene is rendered separately by Blender in the background. Write ONE function per scene:

    def build(k):
        ...

`k` is Clip Agent's 3D kit (already imported). Use ONLY these helpers (plus math, random, mathutils, and bpy for
small tweaks). Units: metres, Z up, floor at z=0, times in SECONDS from the start of the scene.

SCENE: k.P["T"] = scene duration (s), k.P["W"], k.P["H"] = {W}x{H} ({orient}). k.words() -> [(time, word), ...] of
this scene's narration; k.when("word", default) -> time a word is spoken. Sync actions to the narration with k.when().
MATERIALS (color = '#RRGGBB' or a name: concrete soil sand gravel grass water dirty_water sludge steel metal iron copper
  brass aluminum chrome pvc plastic rubber wood brick glass fire air gas oil red orange yellow green teal blue navy
  purple pink white gray dark black brown):
  k.mat(color, rough=0.5, metal=0.0, alpha=1.0, emit=0.0)  k.concrete()  k.metal(color='steel')  k.water(color='water', alpha=0.55)
  k.glass(alpha=0.25)  k.plastic(color='pvc')  k.glow(color='orange', strength=4)
SHAPES (all return the Blender object; `at` = position; base=True puts the pivot at the bottom face):
  k.box(size=(x,y,z), at=(0,0,0), mat=None, bevel=0.02, base=False)
  k.cylinder(r=0.5, h=1, at=(0,0,0), axis='Z'|'X'|'Y'|(dx,dy,dz), mat=None, base=False, open_top=False)
  k.tube(r=0.3, h=1, wall=0.04, at, axis, mat)                hollow straight pipe
  k.tank(size=(x,y,z), wall=0.08, at=(x,y,floor_z), mat=None, open_top=True)   hollow box, bottom at at.z
  k.wall(a=(x,y,z), b=(x,y,z), h=1, thick=0.1, mat)            vertical partition between two floor points
  k.sphere(r, at, mat)  k.cone(r1, r2, h, at, axis, mat)  k.torus(R, r, at, axis, mat)  k.plane(size=(x,y), at, mat)
  k.gear(r=0.6, teeth=14, thick=0.15, at, axis, mat)  k.spring(r, wire, turns, h, at, mat)
  k.pipe(points=[(x,y,z),...], r=0.08, mat=None, smooth=True)  pipe/cable/hose through points (rounded corners)
  k.group(objs, at)  -> parent empty to move/rotate several parts together
  k.cut(objs, side='front'|'back'|'left'|'right'|'top', at=(0,0,0))  cutaway: removes the front half so the inside shows
  k.text(txt, at, size=0.35, color=None)   3D text that always faces the camera
  k.label(txt, point=(x,y,z), offset=(0,0,0.9), size=0.22)  infographic label: plate + leader line to `point`
  k.arrow(start, end, color=None, r=0.05)
ANIMATION (t in seconds; objects stay as built unless animated):
  k.appear(obj, t, dur=0.5, how='pop'|'grow'|'rise'|'drop'|'left'|'right')  hidden before t
  k.disappear(obj, t, dur=0.4)   k.show_between(obj, t0, t1)
  k.move(obj, t0, t1, to=(x,y,z))   k.rotate(obj, t0, t1, to_deg=(rx,ry,rz))   k.spin(obj, axis='Z', rps=0.5, t0, t1)
  k.oscillate(obj, axis='Z', amp=0.2, hz=1, t0, t1)   pistons, pumps, valves, vibration
  k.level(obj, t0, t1, frm=0.0, to=1.0)   rise/fall of a base=True object (water filling, sludge growing)
  k.flow(path_or_pipe, t0, t1=None, n=18, r=0.05, color='water', speed=0.8, shape='ball')  particles flowing along a
      pipe/path (pipes become see-through automatically)
  k.settle(t0, t1, at=(x,y,z_start), area=(w,d), floor_z=0, n=30, r=0.04, color='sludge')  particles sinking to a floor
  k.pulse(obj, t0, t1, color=None, times=2)   glowing highlight   k.explode(objs, t0, t1, offsets=[(dx,dy,dz),...])
CAMERA (a default framing is applied if you set none):
  k.fit(objs=None, az=-60, el=22, margin=1.1, t=None, lens=40)  frame objects (None = everything) from azimuth/elevation
      in degrees (az -90 = from the front, i.e. the -Y side). With t: keyframe only; combine several fits to move.
  k.camera(at, look, lens=40)   k.cam_move(t0, t1, at=None, look=None, lens=None)
  k.orbit(center, radius=9, height=4, deg0=-100, deg1=-60, t0=0, t1=None)

DIRECTION
- The frame is {orient} {W}x{H}. {compose}
- Something must move during the WHOLE scene (flow, spin, level change, slow camera push/orbit). No static seconds.
- Reveal parts in the order the narration mentions them (k.when). Hold the final state readable for the last second.
- Use cutaways for anything with an inside (tanks, engines, walls, pipes). Show the PROBLEM failing visibly.
- 1-3 labels per scene, max 3 words each, in {lang_name}. Label size about 5% of the subject width.
- Keep the same model, sizes and colours as in the other scenes of this video (continuity). Put shared building code
  in "common" (plain Python defining helper functions that take k), and call it from each scene.
- Allowed imports: math, random, mathutils, bpy, bmesh. No file access, no bpy.ops except bpy.ops.mesh / bpy.ops.object
  primitives, no bpy.app/bpy.utils, no names starting with "__". Keep each scene under 120 lines.

Answer with JSON only: {{"common": "def model(k): ...", "scenes": [{{"id": "<scene id>", "code": "def build(k):\\n    ..."}}]}}

EXAMPLE scene code (cutaway septic tank; uses a common helper):
def build(k):
    T = k.P["T"]
    parts = tank_model(k)                        # from "common"
    k.cut(parts["cut"], side="front")
    k.level(parts["water1"], 0.3, k.when("ruang", 2.0), 0.05, 1.0)
    k.flow(parts["inlet"], 0.2, T, n=12, color="dirty_water", speed=1.2)
    k.settle(1.0, T, at=(-0.7, 0, 0.9), area=(1.5, 1.0), floor_z=0.12)
    lab = k.label("Endapan", point=(-0.8, 0, 0.3), offset=(-0.4, 0, 1.5))
    k.appear(lab, k.when("endapan", 1.5))
    k.fit(az=-70, el=25, t=0)
    k.fit([parts["tank"]], az=-60, el=30, t=T)"""


def _compose(W: int, H: int) -> str:
    if H > W:
        return ("The frame is narrow: build TALL rather than wide, keep the main subject within about 3 m width, "
                "use the upper and lower thirds (e.g. ground level + underground, or stacked parts). For a wide system "
                "show one part at a time with k.fit on a subset or k.cam_move.")
    return "Wide frame: lay the system out left to right, keep labels inside the frame."


def scene_brief(sc: dict, item: dict, i: int, n: int) -> dict:
    b3 = sc.get("b3d") or {}
    s0 = (item.get("speech") or [0, 0])[0]
    cut = max(0.0, s0 - 0.08)
    words = [[round(w["s"] - cut, 2), w["t"]] for w in item.get("words") or [] if w["s"] - cut < item["dur"]]
    return {"id": sc["id"], "n": i + 1, "of": n, "role": b3.get("role") or ("hook" if i == 0 else "cta" if i == n - 1 else "solution"),
            "duration": round(float(item["dur"]), 2), "narration": sc["narration"], "label": sc.get("heading") or "",
            "visual": b3.get("visual") or sc.get("prompt") or sc.get("heading") or sc["narration"],
            "objects": b3.get("objects") or [], "camera": b3.get("camera") or "", "word_times": words}


def code_user(title: str, topic: str, briefs: list[dict]) -> str:
    return ("VIDEO: " + title + (f"\nTOPIC: {topic}" if topic else "") +
            "\nWrite the Blender code for these scenes (same model across all of them):\n" +
            json.dumps(briefs, ensure_ascii=False, indent=1) + "\n\nAnswer with the JSON now.")


_BAD_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
              "delattr", "input", "breakpoint", "exit", "quit", "memoryview", "os", "sys", "subprocess", "shutil",
              "socket", "pathlib", "importlib"}
_OK_IMPORTS = {"math", "random", "mathutils", "bpy", "bmesh", "colorsys", "itertools", "functools"}
_OK_OPS = {"mesh", "object", "curve"}


def static_problems(code: str) -> list[str]:
    """Aturan keamanan dan bentuk kode adegan (sebelum dijalankan Blender)."""
    if not code.strip():
        return ["The code is empty."]
    if len(code) > 30000:
        return ["The code is too long; keep each scene short and put shared parts in 'common'."]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"SyntaxError line {exc.lineno}: {exc.msg}"]
    probs = []
    if not any(isinstance(n, ast.FunctionDef) and n.name == "build" for n in tree.body):
        probs.append("Define the function build(k).")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] not in _OK_IMPORTS:
                    probs.append(f"import {m} is not allowed.")
        elif isinstance(node, ast.Name) and node.id in _BAD_NAMES:
            probs.append(f"'{node.id}' is not allowed.")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                probs.append(f"'.{node.attr}' is not allowed.")
            if node.attr in ("filepath", "app", "utils", "texts", "libraries", "handlers", "driver_namespace"):
                probs.append(f"'.{node.attr}' is not allowed.")
            if isinstance(node.value, ast.Attribute) and node.value.attr == "ops" and node.attr not in _OK_OPS:
                probs.append(f"bpy.ops.{node.attr} is not allowed (only bpy.ops.mesh/object/curve).")
    return sorted(set(probs))[:8]


def _ask(eng: str, system: str, prompt: str, out_dir: Path, audience: str) -> dict:
    from . import agents
    from .remake import _llm
    if eng == "llm":
        return _llm(out_dir, audience).complete_json(system, prompt)
    data = extract_json(agents.text(eng, system, prompt))
    if not isinstance(data, dict):
        raise ClipAgentError("Jawaban AI bukan objek JSON.")
    return data


def _codes_from(data: dict) -> dict[str, str]:
    common = str(data.get("common") or "").strip()
    out = {}
    for s in data.get("scenes") or []:
        if isinstance(s, dict) and s.get("id") and str(s.get("code") or "").strip():
            out[str(s["id"])] = ((common + "\n\n\n") if common else "") + str(s["code"]).strip() + "\n"
    return out


def _engines(engine: str) -> list[str]:
    from . import agents, motion
    if engine in ("", "auto"):
        first = motion.engine_name("auto")
        return [first] + [e for e in (["llm"] + list(agents.available())) if e != first]
    return [engine]


def write_codes(briefs: list[dict], *, title: str, topic: str, W: int, H: int, lang: str, engine: str,
                out_dir: Path) -> tuple[dict[str, str], str]:
    """Kode semua adegan dalam satu permintaan (model yang sama di semua adegan). Mengembalikan (kode, penulis)."""
    system = CODE_SYSTEM.format(W=W, H=H, orient="vertical" if H > W else "horizontal", compose=_compose(W, H),
                                lang_name="English" if lang == "en" else "Bahasa Indonesia")
    prompt = code_user(title, topic, briefs)
    audience = "us" if lang == "en" else "id"
    last: Exception | None = None
    for eng in _engines(engine):
        try:
            codes = _codes_from(_ask(eng, system, prompt, out_dir, audience))
            if not codes:
                raise ClipAgentError("AI tidak mengirim kode adegan.")
            return codes, eng
        except ClipAgentError as exc:
            last = exc
            log(f"  Penulis kode {eng}: {str(exc).splitlines()[0][:160]}")
    raise ClipAgentError(f"Tidak ada penulis AI yang bisa menulis kode 3D: {last}")


def repair_codes(problems: list[tuple[dict, str, str]], *, title: str, W: int, H: int, lang: str, eng: str,
                 out_dir: Path) -> dict[str, str]:
    system = CODE_SYSTEM.format(W=W, H=H, orient="vertical" if H > W else "horizontal", compose=_compose(W, H),
                                lang_name="English" if lang == "en" else "Bahasa Indonesia")
    items = [{"brief": b, "code": code, "error": err[:1500]} for b, code, err in problems]
    prompt = ("VIDEO: " + title + "\nThese scenes failed when Blender ran them. Fix each one (keep the same idea and "
              "model; include any helper functions INSIDE the code since 'common' is not re-sent):\n" +
              json.dumps(items, ensure_ascii=False, indent=1) +
              '\n\nAnswer with JSON only: {"scenes": [{"id": "<scene id>", "code": "...full fixed code..."}]}')
    try:
        return _codes_from(_ask(eng, system, prompt, out_dir, "us" if lang == "en" else "id"))
    except ClipAgentError as exc:
        log(f"  Perbaikan kode 3D gagal: {str(exc).splitlines()[0][:160]}")
        return {}


def fallback_code(b: dict) -> str:
    """Adegan cadangan sederhana (dipakai bila kode AI tetap gagal): label besar + model berputar."""
    label = json.dumps((b.get("label") or b.get("narration") or "")[:28], ensure_ascii=False)
    return f'''def build(k):
    T = k.P["T"]
    base = k.cylinder(1.4, 0.25, at=(0, 0, 0), mat=k.concrete(), base=True)
    g1 = k.gear(0.9, 16, 0.25, at=(-0.45, 0, 1.6), axis="Y", mat=k.metal("steel"))
    g2 = k.gear(0.55, 10, 0.25, at=(0.95, 0, 1.6), axis="Y", mat=k.metal("brass"))
    k.spin(g1, "Y", 0.25)
    k.spin(g2, "Y", -0.41)
    k.appear(base, 0.0, 0.5, "grow")
    k.appear(g1, 0.2, 0.5)
    k.appear(g2, 0.4, 0.5)
    lab = k.label({label}, point=(0.2, 0, 2.6), offset=(0, 0, 0.9), size=0.28, dot=False)
    k.appear(lab, 0.6, 0.4)
    k.orbit((0.2, 0, 1.5), radius=8.5, height=2.5, deg0=-110, deg1=-70)
'''


def _hash(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:14]


def _job(exe: str, mode: str, code: str, work: Path, *, W: int, H: int, T: float, quality: str, style: str, lang: str,
         words: list, scale: int, stills: list[float] | None = None, on_frame=None, timeout: float = 900) -> dict:
    """Jalankan runner di Blender; kembalikan result.json."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "scene.py").write_text(code, encoding="utf-8")
    for old in ("result.json",):
        (work / old).unlink(missing_ok=True)
    job = {"mode": mode, "code_file": str((work / "scene.py").resolve()), "out_dir": str(work.resolve()),
           "kit_dir": str(KIT_DIR.resolve()), "W": W, "H": H, "fps": FPS, "T": round(T, 3), "quality": quality,
           "style": style, "lang": lang, "words": words, "scale": scale, "stills": stills or [],
           "samples": {"best": 48, "good": 24}.get(quality, 16)}
    jf = work / "job.json"
    jf.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    runner = str((KIT_DIR / "runner.py").resolve())
    cmd = [exe, runner, str(jf)] if _is_py(exe) else \
        [exe, "-b", "--factory-startup", "--python-exit-code", "1", "-P", runner, "--", str(jf)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", cwd=str(work), creationflags=flags)
    tail: list[str] = []
    t0 = time.time()
    saved = 0
    try:
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-40:]
            if "Saved:" in line and on_frame:
                saved += 1
                on_frame(saved)
            if time.time() - t0 > timeout:
                proc.kill()
                raise ClipAgentError(f"Blender melebihi batas waktu ({timeout / 60:.0f} menit).")
            try:
                check_cancel()
            except BaseException:
                proc.kill()
                raise
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    rf = work / "result.json"
    if not rf.is_file():
        raise ClipAgentError("Blender berhenti tanpa hasil: " + " | ".join(t for t in tail[-6:] if t.strip())[-600:])
    return json.loads(rf.read_text(encoding="utf-8"))


def _empty_still(path: str) -> bool:
    """Frame hampir polos (kamera tidak melihat apa pun / objek terlalu kecil)."""
    import cv2
    import numpy as np
    img = cv2.imread(path)
    if img is None:
        return True
    small = cv2.resize(img, (90, 160)).astype("float32")
    bg = np.median(small.reshape(-1, 3), axis=0)
    diff = np.abs(small - bg).sum(axis=2)
    return float((diff > 30).mean()) < 0.015


def _frames_to_mp4(frames: Path, dst: Path, W: int, H: int, T: float) -> Path:
    files = sorted(frames.glob("f_*.jpg"))
    if not files:
        raise ClipAgentError("Blender tidak menghasilkan frame.")
    digits = len(re.sub(r"\D", "", files[0].stem))
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-start_number", str(int(re.sub(r"\D", "", files[0].stem))),
           "-i", str(frames / f"f_%0{digits}d.jpg"), "-vf",
           f"scale={W}:{H}:flags=lanczos,fps={FPS},tpad=stop_mode=clone:stop_duration=1,format=yuv420p",
           "-t", f"{T:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dst.is_file():
        raise ClipAgentError(f"Gagal menyusun video adegan 3D: {r.stderr[-300:]}")
    return dst


def build(out_dir: Path, proj: dict, scenes: list[dict], items: list[dict], adir: Path, p0: float, p1: float) -> None:
    """Dipanggil remake.build_assets: tulis kode, uji, perbaiki, lalu render setiap adegan 'blender3d'."""
    import cv2
    from .remake import _dims
    st = proj["settings"]
    b3 = st.get("b3d") or {}
    idx = [i for i, it in enumerate(items) if it["kind"] == "blender3d"]
    if not idx:
        return
    span = p1 - p0
    exe = find_blender()
    stt = status()
    if not stt["found"]:
        log("  " + (stt["hint"] or "Blender tidak ditemukan.") + " Adegan 3D diganti kartu teks.")
        for i in idx:
            items[i]["kind"] = "text"
        return
    log(f"Blender {stt['version']}: {exe}")
    W, H = _dims(st["aspect"])
    style = b3.get("style") if b3.get("style") in STYLES else "studio"
    quality = b3.get("quality") if b3.get("quality") in QUALITIES else "good"
    scale = int(b3.get("scale") or 100) if int(b3.get("scale") or 100) in SCALES else 100
    lang = "en" if st.get("audience") == "us" else "id"
    title = proj["script"].get("title") or proj.get("topic") or ""
    n = len(scenes)
    briefs = {scenes[i]["id"]: scene_brief(scenes[i], items[i], i, n) for i in idx}
    wdir = adir / "b3d"
    wdir.mkdir(parents=True, exist_ok=True)

    # 1) kode (di-cache per isi adegan)
    def key(b):
        return _hash(VERSION, b, style, W, H, lang)
    codes: dict[str, str] = {}
    for sid, b in briefs.items():
        p = wdir / f"code_{key(b)}.py"
        if p.is_file():
            codes[sid] = p.read_text(encoding="utf-8")
    need = [b for sid, b in briefs.items() if sid not in codes]
    eng = _engines(b3.get("engine") or "auto")[0]
    if need:
        progress(p0 + span * 0.02, f"AI menulis kode Blender untuk {len(need)} adegan")
        log(f"Menulis kode Blender untuk {len(need)} adegan 3D.")
        got, eng = write_codes(need, title=title, topic=proj.get("topic", ""), W=W, H=H, lang=lang,
                               engine=b3.get("engine") or "auto", out_dir=out_dir)
        codes.update({sid: c for sid, c in got.items() if sid in briefs})

    # 2) uji jalan + frame kosong, perbaiki otomatis (maks 2 putaran)
    good: set[str] = set()
    fallback: set[str] = set()
    for rnd in range(3):
        problems = []
        todo = [sid for sid in briefs if sid not in good]
        for k_, sid in enumerate(todo):
            check_cancel()
            progress(p0 + span * (0.12 + 0.1 * rnd + 0.08 * k_ / max(1, len(todo))), f"Menguji kode 3D adegan {briefs[sid]['n']}")
            b, code = briefs[sid], codes.get(sid, "")
            probs = static_problems(code) if code else ["No code was written for this scene."]
            if probs:
                problems.append((b, code, "Static check failed:\n- " + "\n- ".join(probs)))
                continue
            T = b["duration"]
            res = _job(exe, "check", code, wdir / f"check_{sid}", W=W, H=H, T=T, quality="fast", style=style,
                       lang=lang, words=b["word_times"], scale=25, stills=[min(0.6, T / 3), T / 2, max(0.0, T - 0.2)],
                       timeout=240)
            if not res.get("ok"):
                problems.append((b, code, res.get("error") or "Blender failed."))
            elif sum(_empty_still(s) for s in res.get("stills") or []) >= 2:
                problems.append((b, code, "The frames are almost empty: the camera does not see the model or it is "
                                          "tiny. Frame the subject with k.fit() and keep parts near the origin."))
            else:
                good.add(sid)
        if not problems:
            break
        if rnd == 2:
            for b, _, err in problems:
                log(f"  Adegan {b['n']}: kode 3D tetap gagal ({err.splitlines()[-1][:140]}); memakai adegan cadangan.")
                codes[b["id"]] = fallback_code(b)
                fallback.add(b["id"])
            break
        log(f"  {len(problems)} adegan 3D perlu diperbaiki: " +
            "; ".join(f"#{b['n']}: {err.strip().splitlines()[-1][:90]}" for b, _, err in problems))
        progress(p0 + span * (0.14 + 0.1 * rnd), "AI memperbaiki kode 3D")
        fixed = repair_codes(problems, title=title, W=W, H=H, lang=lang, eng=eng, out_dir=out_dir)
        for b, code, _ in problems:
            if fixed.get(b["id"]):
                codes[b["id"]] = fixed[b["id"]]
    for sid, b in briefs.items():
        if sid not in fallback:
            (wdir / f"code_{key(b)}.py").write_text(codes[sid], encoding="utf-8")

    # 3) render tiap adegan
    total_frames = sum(int(round(b["duration"] * FPS)) for b in briefs.values()) or 1
    done_frames = 0
    r0 = p0 + span * 0.36
    est = total_frames * QUALITIES[quality]["spf"] * (scale / 100) ** 2
    log(f"Merender {len(briefs)} adegan 3D ({total_frames} frame, kualitas {QUALITIES[quality]['name']}"
        + (f", perkiraan ±{max(1, round(est / 60))} menit dengan GPU" if est > 60 else "") + ").")
    for i in idx:
        sid = scenes[i]["id"]
        b = briefs[sid]
        frames_n = int(round(b["duration"] * FPS))
        vkey = _hash(VERSION, codes[sid], W, H, FPS, b["duration"], quality, style, scale, b["word_times"])
        mp4 = adir / f"b3d_{vkey}.mp4"
        if not mp4.is_file():
            work = wdir / f"render_{sid}"
            shutil.rmtree(work / "frames", ignore_errors=True)
            base = done_frames

            def tick(nf, base=base, n_=b["n"]):
                progress(r0 + (p1 - r0) * min(1.0, (base + nf) / total_frames), f"Render 3D adegan {n_}: frame {nf}")
            progress(r0 + (p1 - r0) * base / total_frames, f"Render 3D adegan {b['n']}")

            def render_one(code: str, q: str, b=b, work=work, tick=tick, frames_n=frames_n) -> dict:
                try:
                    return _job(exe, "render", code, work, W=W, H=H, T=b["duration"], quality=q, style=style,
                                lang=lang, words=b["word_times"], scale=scale, on_frame=tick,
                                timeout=300 + frames_n * QUALITIES[q]["spf"] * 25)
                except ClipAgentError as exc:                 # Blender berhenti/crash (mis. driver GPU)
                    return {"ok": False, "error": "RUNNER: " + str(exc)}
            res = render_one(codes[sid], quality)
            if not res.get("ok") and quality != "fast" and str(res.get("error", "")).startswith("RUNNER"):
                log(f"  Adegan {b['n']}: mesin render {QUALITIES[quality]['name']} gagal di komputer ini "
                    f"({str(res.get('error'))[8:160]}); mencoba mode Cepat (Workbench).")
                quality = "fast"                              # adegan berikutnya juga memakai mode Cepat
                res = render_one(codes[sid], quality)
            if not res.get("ok") and sid not in fallback:
                log(f"  Adegan {b['n']}: render gagal ({(res.get('error') or '').strip().splitlines()[-1][:140]}); "
                    "memakai adegan cadangan.")
                codes[sid] = fallback_code(b)
                res = render_one(codes[sid], quality)
            if not res.get("ok"):
                log(f"  Adegan {b['n']}: Blender gagal merender; memakai kartu teks.")
                items[i]["kind"] = "text"
                done_frames += frames_n
                continue
            _frames_to_mp4(work / "frames", mp4, W, H, b["duration"])
            shutil.rmtree(work / "frames", ignore_errors=True)
        done_frames += frames_n
        items[i]["video"] = mp4.name
        if sid in fallback:
            items[i]["motion_fallback"] = True
        cap = cv2.VideoCapture(str(mp4))
        cap.set(cv2.CAP_PROP_POS_MSEC, min(1500, b["duration"] * 500))
        ok, fr = cap.read()
        cap.release()
        if ok:
            th = adir / f"thumb_{sid}.jpg"
            cv2.imwrite(str(th), cv2.resize(fr, (int(fr.shape[1] * 300 / fr.shape[0]), 300)), [cv2.IMWRITE_JPEG_QUALITY, 80])
            items[i]["thumb"] = th.name
    if fallback:
        log(f"  {len(fallback)} adegan memakai animasi cadangan. Buat ulang videonya untuk mencoba kode baru.")
    progress(p1, "Adegan 3D selesai")


# ====================================================================== buat dari awal sampai MP4
def recent(out_dir: Path, limit: int = 12) -> list[dict]:
    from . import remake
    out = []
    for item in remake.list_projects(out_dir):
        try:
            pr = remake.load(out_dir, item["id"])
        except ClipAgentError:
            continue
        a3 = (pr.get("settings") or {}).get("anim3d")
        if not a3:
            continue
        last = (pr.get("renders") or [None])[-1]
        video, thumb = "", ""
        if last:
            fpath = remake.pdir(out_dir, pr["id"]) / last["file"]
            if fpath.is_file():
                video = remake._url(out_dir, fpath)
        th = next((p for p in sorted((remake.pdir(out_dir, pr["id"]) / "assets").glob("thumb_*.jpg"))), None)
        if th:
            thumb = remake._url(out_dir, th)
        out.append({"project": pr["id"], "title": pr["script"].get("title", ""), "ready": bool(video), "video_url": video,
                    "thumb": thumb, "duration": (last or {}).get("duration"), "updated": pr.get("updated", ""),
                    "description": pr["script"].get("description", ""), "hashtags": pr["script"].get("hashtags", []),
                    "style": (pr["settings"].get("b3d") or {}).get("style", "studio")})
        if len(out) >= limit:
            break
    return out


def plan_view(out_dir: Path, pid: str) -> dict:
    """Production plan + QC untuk ditampilkan sebelum/sesudah render."""
    from . import remake
    pr = remake.load(out_dir, pid)
    a3 = (pr.get("settings") or {}).get("anim3d") or {}
    last = (pr.get("renders") or [None])[-1]
    video = ""
    if last and (remake.pdir(out_dir, pid) / last["file"]).is_file():
        video = remake._url(out_dir, remake.pdir(out_dir, pid) / last["file"])
    lang = "en" if pr["settings"].get("audience") == "us" else "id"
    rows = []
    for i, sc in enumerate(pr["script"].get("scenes") or []):
        b3 = sc.get("b3d") or {}
        rows.append({"n": i + 1, "role": b3.get("role", ""), "narration": sc.get("narration", ""), "label": sc.get("heading", ""),
                     "visual": b3.get("visual") or sc.get("prompt", ""), "objects": b3.get("objects", []),
                     "camera": b3.get("camera", ""), "sfx": b3.get("sfx", ""),
                     "est": round(_words(sc.get("narration", "")) / WPS.get(lang, 2.4), 1)})
    return {"project": pid, "title": pr["script"].get("title", ""), "description": pr["script"].get("description", ""),
            "hashtags": pr["script"].get("hashtags", []), "analysis": a3.get("analysis") or {}, "qc": a3.get("qc") or [],
            "voice_style": a3.get("voice_style", ""), "music_prompt": a3.get("music_prompt", ""),
            "pronunciation": a3.get("pronunciation") or [], "scenes": rows, "video_url": video,
            "duration": (last or {}).get("duration"), "settings": pr["settings"].get("b3d") or {}}


def make(out_dir: Path, raw: dict) -> dict:
    """Riset -> naskah + production plan -> QC -> (bila tidak plan_only) suara, kode Blender, render, gabung."""
    from . import download, remake, webpage
    src_type = raw.get("source_type") if raw.get("source_type") in ("link", "topic", "script") else "topic"
    text = str(raw.get("source") or "").strip()
    if not text:
        raise ClipAgentError("Isi dulu topik, tautan rujukan, atau naskahnya.")
    try:
        seconds = int(raw.get("length") or 45)
    except (TypeError, ValueError):
        seconds = 45
    seconds = min(LENGTHS, key=lambda x: abs(x - seconds))
    lang = "en" if raw.get("lang") == "en" else "id"
    audience = "us" if lang == "en" else "id"
    from . import reels
    engine = raw.get("engine") if raw.get("engine") in reels.ENGINES else "auto"
    style = raw.get("style") if raw.get("style") in STYLES else "studio"
    quality = raw.get("quality") if raw.get("quality") in QUALITIES else "good"
    try:
        scale = int(raw.get("scale") or 100)
    except (TypeError, ValueError):
        scale = 100
    scale = scale if scale in SCALES else 100
    aspect = "16:9" if raw.get("aspect") == "16:9" else "9:16"
    url = text if re.match(r"https?://", text) else ""
    material: dict = {"angle": str(raw.get("angle") or "")[:600]}
    if src_type == "script" and not url:
        material["script"] = text[:6000]
    elif not url:
        material["topic"] = text[:1500]
    settings = {"length": seconds, "aspect": aspect, "audience": audience, "visual": "blender3d", "theme": "",
                "captions": True, "hook": False, "progress_bar": False, "music": "auto", "voice_mode": "one",
                "b3d": {"style": style, "quality": quality, "scale": scale, "engine": engine}}
    if raw.get("voice") in ("pria", "wanita"):
        settings["voice_gender"] = raw["voice"]
    proj = remake.new_project(out_dir, material.get("topic") or (material.get("script") or "")[:200] or url, settings,
                              blank=True)
    pid = proj["id"]
    progress(0.02, "Membaca rujukan")
    src_text = ""
    if url:
        log(f"Membaca rujukan {url}")
        try:
            if webpage.is_video_url(url):
                srcd = download.fetch_source_text(url, remake.pdir(out_dir, pid), lang)
                material["source"] = {"url": url, "title": srcd.get("title", ""), "site": srcd.get("channel", ""),
                                      "description": srcd.get("description", ""), "text": srcd.get("text", "")}
            else:
                material["source"] = webpage.fetch(url)
            src_text = (material["source"].get("text") or "") + "\n" + (material["source"].get("description") or "")
        except ClipAgentError as exc:
            log(f"  Rujukan tidak terbaca ({str(exc)[:160]}); naskah dibuat dari judul/topik saja.")
            material.setdefault("topic", str(raw.get("title") or url)[:300])
    progress(0.06, "AI membedah topik dan menulis naskah")
    log(f"Menulis naskah 3D ({seconds} detik, {'English' if lang == 'en' else 'Bahasa Indonesia'}).")
    plan = write_plan(material, seconds=seconds, lang=lang, engine=engine, out_dir=out_dir)
    qc = qc_report(plan, lang, seconds, src_text.strip())
    for c in qc:
        log(f"  QC {c['label']}: {c['detail'][:160]}")
    proj = remake.load(out_dir, pid)
    src = material.get("source") or {}
    proj["source"] = {"url": url, "title": src.get("title", ""), "channel": src.get("site", "")}
    proj["topic"] = material.get("topic") or src.get("title") or plan["title"]
    rows = []
    for sc in plan["scenes"]:
        row = {"id": uuid.uuid4().hex[:6], "narration": sc["narration"], "heading": sc["label"], "visual": "blender3d",
               "prompt": sc["visual"][:400], "stock": "", "camera": "static", "transition": "fade",
               "b3d": {k: sc[k] for k in ("role", "visual", "objects", "camera", "sfx")}}
        say = say_text(sc["narration"], plan["pronunciation"])
        if say != sc["narration"]:
            row["say"] = say
        rows.append(row)
    proj["settings"]["anim3d"] = {"analysis": plan["analysis"], "qc": qc, "voice_style": plan["voice_style"],
                                  "music_prompt": plan["music_prompt"], "pronunciation": plan["pronunciation"],
                                  "source_type": src_type}
    if plan["voice_style"]:
        proj["settings"]["voice_style"] = plan["voice_style"][:120]
    proj["script"].update(title=plan["title"], description=plan["description"], hashtags=plan["hashtags"],
                          mood=plan["mood"], scenes=rows)
    remake.save(out_dir, proj)
    if raw.get("plan_only"):
        progress(1.0, "Naskah dan production plan siap")
        return {"project": pid, "plan_only": True, **plan_view(out_dir, pid)}
    return render(out_dir, pid)


def render(out_dir: Path, pid: str) -> dict:
    from . import remake
    res = remake.render(out_dir, pid)
    view = plan_view(out_dir, pid)
    return {"project": pid, **view, "file": res.get("file"), "video_url": res.get("video_url"),
            "duration": res.get("duration")}


def validate(raw: dict) -> None:
    st = status()
    if not raw.get("plan_only") and not st["found"]:
        raise ClipAgentError(st["hint"] or "Blender belum ditemukan.")
    if len(str(raw.get("source") or "").strip()) < 3:
        raise ClipAgentError("Isi topik, tautan rujukan, atau naskahnya dulu.")


if __name__ == "__main__":                                       # python -m clipagent.anim3d  -> status Blender
    print(json.dumps(status(), indent=1))
    sys.exit(0)
