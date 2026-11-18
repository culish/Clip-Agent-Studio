"""Endpoint web untuk fitur studio: riset viral, karakter, buat ulang video, musik, dan posting."""
from __future__ import annotations

import json
import os
import re
import time
from html import escape as html_escape
from pathlib import Path

from . import characters, kolase, music, publish, remake, tts, videogen, viral
from .utils import ClipAgentError

STUDIO_KINDS = ("remake_script", "remake_assets", "remake_render", "character_images", "kolase_storyboard", "kolase_render",
                "kolase_paket", "kolase_preview", "kolase_clip")


# ---------------------------------------------------------------- job
def validate_job(body: dict, out_dir: Path) -> None:
    kind = body.get("kind")
    if kind and kind.startswith("kolase_"):
        proj = kolase.load(out_dir, str(body.get("project") or ""))
        body["label"] = f"Kolase: {proj.get('title') or 'video'}"
        if kind == "kolase_storyboard":
            if proj["vo"].get("source") == "upload" and not proj.get("words") and not kolase._has_whisper():
                raise ValueError("Transkrip VO butuh faster-whisper. Jalankan: pip install -r requirements-whisper.txt")
            if proj["vo"].get("source") == "tts":
                tts.pick_engine(proj["settings"].get("voice_engine", "edge"))
        if kind in ("kolase_render", "kolase_preview", "kolase_clip"):
            from .animation import remotion_status
            if not remotion_status()["ready"]:
                raise ValueError(remotion_status()["hint"])
            if not proj.get("scenes"):
                raise ValueError("Storyboard masih kosong. Klik Buat storyboard dulu.")
        if kind == "kolase_paket" and not kolase.paket_status().get("found"):
            raise ValueError("Folder paket Kolase Editorial belum diatur atau tidak dikenali.")
        return
    if kind == "character_images":
        ch = characters.get(out_dir, str(body.get("character") or ""))
        body["label"] = f"Karakter {ch['name']}"
        return
    proj = remake.load(out_dir, str(body.get("project") or ""))
    body["label"] = (proj.get("script") or {}).get("title") or proj.get("source", {}).get("title") or "Video baru"
    if kind in ("remake_assets", "remake_render"):
        from .animation import remotion_status
        if kind == "remake_render" and not remotion_status()["ready"]:
            raise ValueError(remotion_status()["hint"])
        if not remake.clean_scenes(proj["script"].get("scenes")):
            raise ValueError("Naskah masih kosong. Isi narasi minimal satu adegan.")
        tts.pick_engine(proj["settings"].get("voice_engine", "gemini"))


def run_job(kind: str, opts: dict, out_dir: Path) -> dict:
    if kind.startswith("kolase_"):
        pid = str(opts["project"])
        if kind == "kolase_storyboard":
            proj = kolase.storyboard(out_dir, pid)
            return {"kind": kind, "project": pid, "scenes": len(proj["scenes"])}
        if kind == "kolase_paket":
            return {"kind": kind, "project": pid, **kolase.paket_prepare(out_dir, pid)}
        if kind == "kolase_preview":
            return {"kind": kind, "project": pid, **kolase.preview(out_dir, pid)}
        if kind == "kolase_clip":
            return {"kind": kind, "project": pid, **kolase.render(out_dir, pid, clip_from=str(opts.get("scene") or "x"))}
        return {"kind": kind, "project": pid, **kolase.render(out_dir, pid)}
    if kind == "character_images":
        ch = characters.generate_candidates(out_dir, str(opts["character"]))
        return {"kind": kind, "character": ch["id"], "count": len(ch["candidates"])}
    pid = str(opts["project"])
    if kind == "remake_script":
        proj = remake.write_script(out_dir, pid)
        return {"kind": kind, "project": pid, "scenes": len(proj["script"]["scenes"]), "similarity": proj["similarity"]}
    if kind == "remake_assets":
        res = remake.build_assets(out_dir, pid)
        return {"kind": kind, "project": pid, "duration": res["duration"]}
    return {"kind": kind, "project": pid, **remake.render(out_dir, pid)}


# ---------------------------------------------------------------- data untuk UI
def studio_meta(out_dir: Path) -> dict:
    from .animation import PRESETS, remotion_status
    from . import broll
    return {
        "engines": tts.engines(), "voices": {"gemini": tts.GEMINI_VOICES, "edge": tts.EDGE_VOICES},
        "default_voice": tts.DEFAULT_VOICE, "visuals": remake.VISUALS, "lengths": remake.LENGTHS,
        "art_styles": {k: v[0] for k, v in characters.ART_STYLES.items()},
        "presets": {k: {"name": v["name"], "desc": v["desc"], "style": v["style"]} for k, v in PRESETS.items()},
        "music": music.choices(), "moods": {k: v["label"] for k, v in music.MOODS.items()},
        "keys": {"gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("IMAGE_API_KEY")),
                 "pexels": broll.available(), "youtube_api": bool(viral.api_key())},
        "video_price": {"per_second": videogen.PRICE_PER_SECOND, "seconds": videogen.EST_SECONDS},
        "defaults": remake.DEFAULT_SETTINGS, "remotion": remotion_status(),
        "cameras": remake.CAMERAS, "transitions": remake.TRANSITIONS,
    }


def all_videos(out_dir: Path) -> list[dict]:
    """Semua video hasil (klip, animasi, edit otomatis, video buatan ulang) + metadata saran untuk posting."""
    out = []
    for plan_path in out_dir.glob("*/plan.json"):
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        vid = plan_path.parent.name
        src = plan.get("source", {})
        credit = ""
        if "creative commons" in (src.get("license") or "").lower() and src.get("url"):
            credit = f"Source: {src.get('title', '')} by {src.get('channel', '')} ({src['url']}), licensed CC BY."
        for c in plan.get("clips", []):
            files = [(c.get("file"), "Klip")] + [(x.get("file"), x.get("label") or x.get("kind", ""))
                                                  for x in c.get("extras", [])]
            for f, label in files:
                p = plan_path.parent / "clips" / (f or "")
                if not f or not p.is_file():
                    continue
                desc = (c.get("caption") or "").strip()
                if credit:
                    desc = (desc + "\n\n" + credit).strip()
                out.append({"path": p.relative_to(out_dir).as_posix(), "group": src.get("title", vid),
                            "label": f"#{c.get('rank')} {c.get('title', '')} ({label})", "title": c.get("title", ""),
                            "description": desc, "hashtags": [h.lstrip("#") for h in c.get("hashtags", [])],
                            "ai": label != "Klip", "mtime": p.stat().st_mtime,
                            "url": f"/files/{p.relative_to(out_dir).as_posix()}"})
    for item in remake.list_projects(out_dir):
        proj = remake.load(out_dir, item["id"])
        d = remake.pdir(out_dir, item["id"])
        sc = proj.get("script") or {}
        for r in proj.get("renders", []):
            p = d / r["file"]
            if not p.is_file():
                continue
            desc = sc.get("description", "")
            if r.get("credits"):
                desc += "\n\nStock footage: " + ", ".join(r["credits"])
            out.append({"path": p.relative_to(out_dir).as_posix(), "group": "Video buatan ulang",
                        "label": f"{sc.get('title') or 'Video'} ({r['created'][5:16]})", "title": sc.get("title", ""),
                        "description": desc.strip(), "hashtags": sc.get("hashtags", []),
                        "ai": bool(r.get("ai_media", True)), "mtime": p.stat().st_mtime,
                        "url": f"/files/{p.relative_to(out_dir).as_posix()}"})
    for item in kolase.list_projects(out_dir):
        proj = kolase.load(out_dir, item["id"])
        d = kolase.pdir(out_dir, item["id"])
        for r in proj.get("renders", []):
            p = d / r["file"]
            if not p.is_file():
                continue
            desc = proj.get("title", "")
            if r.get("credits"):
                desc += "\n\n" + ", ".join(r["credits"])
            out.append({"path": p.relative_to(out_dir).as_posix(), "group": "Video kolase",
                        "label": f"{proj.get('title') or 'Kolase'} ({r['created'][5:16]})", "title": proj.get("title", ""),
                        "description": desc.strip(), "hashtags": [], "ai": bool(r.get("ai_media", True)),
                        "mtime": p.stat().st_mtime, "url": f"/files/{p.relative_to(out_dir).as_posix()}"})
    for v in kolase.paket_videos(out_dir):
        out.append({"path": v["path"], "group": "Kolase Editorial (paket lokal)", "label": f"{v['project']}: {v['name']}",
                    "title": "", "description": "", "hashtags": [], "ai": True, "mtime": v["mtime"],
                    "url": f"/files/{v['path']}"})
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


# ---------------------------------------------------------------- routing
def handle_get(h, p: str, q) -> bool:
    out = h.out_dir
    if p == "/api/viral":
        h._json(viral.research(q("q"), period=q("period", "week"), length=q("length", "short"),
                               cc=q("cc") == "1", enrich=q("enrich", "1") == "1",
                               limit=max(5, min(30, int(q("limit", "20") or 20)))))
        return True
    if p == "/api/viral/trending":
        items = viral.score(viral.trending_chart(q("category")))
        h._json({"query": "Populer di AS", "source": "youtube-api", "items": items})
        return True
    if p == "/api/studio/meta":
        h._json(studio_meta(out))
        return True
    if p == "/api/characters":
        h._json({"items": characters.list_all(out)})
        return True
    if p == "/api/projects":
        h._json({"items": remake.list_projects(out)})
        return True
    m = re.fullmatch(r"/api/projects/([a-f0-9]{10})", p)
    if m:
        h._json(remake.public(out, remake.load(out, m.group(1))))
        return True
    if p == "/api/videos":
        h._json({"items": all_videos(out)})
        return True
    if p == "/api/kolase":
        h._json({"items": kolase.list_projects(out), "meta": kolase.meta(out), "local": h.is_local})
        return True
    m = re.fullmatch(r"/api/kolase/([a-f0-9]{10})", p)
    if m:
        h._json(kolase.public(out, kolase.load(out, m.group(1))))
        return True
    if p == "/api/posts":
        h._json({"items": h.posts.list(), "accounts": publish.status(), "now": time.time()})
        return True
    if p in ("/oauth/youtube", "/oauth/tiktok", "/oauth/tiktok/"):
        params = {k: v[0] for k, v in h._qs.items()}
        plat = "YouTube" if "youtube" in p else "TikTok"
        try:
            name = publish.yt_callback(params) if plat == "YouTube" else publish.tt_callback(params)
            msg = (f"{plat} terhubung: <b>{html_escape(name)}</b>. Tab ini boleh ditutup, lalu kembali ke Clip Agent. "
                   f"Untuk menambah akun {plat} lain, keluar dulu dari akun ini di browser (atau pilih akun lain "
                   f"saat login), lalu klik Tambah akun lagi.")
        except ClipAgentError as exc:
            msg = f"Gagal menghubungkan {plat}: {html_escape(str(exc))}"
        h._html(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{plat}</title><body style="font:16px system-ui;margin:40px;max-width:560px;line-height:1.5">
<p>{msg}</p><p><a href="/#posting">Kembali ke Clip Agent</a></p></body>""".encode())
        return True
    if p == "/api/publish/tiktok/creator":
        h._json(publish.tiktok_creator(q("account")))
        return True
    return False


def handle_post(h, p: str, body: dict) -> bool:
    out = h.out_dir
    # ---- karakter
    if p == "/api/characters":
        h._json(characters.save(out, body))
        return True
    m = re.fullmatch(r"/api/characters/([a-f0-9]{8,16})/(ref|choose|delete)", p)
    if m:
        cid, act = m.groups()
        if act == "ref":
            h._json(characters.set_reference_upload(out, cid, str(body.get("image") or "")))
        elif act == "choose":
            h._json(characters.choose_candidate(out, cid, str(body.get("file") or "")))
        else:
            characters.delete(out, cid)
            h._json({"ok": True})
        return True
    # ---- proyek buat ulang
    if p == "/api/projects":
        src = str(body.get("source") or "").strip()
        if not src and not body.get("blank"):
            raise ValueError("Tempel link video viral atau tulis topiknya.")
        proj = remake.new_project(out, src, body.get("settings") or {}, blank=bool(body.get("blank")))
        h._json(remake.public(out, proj))
        return True
    m = re.fullmatch(r"/api/projects/([a-f0-9]{10})(/delete)?", p)
    if m:
        if m.group(2):
            remake.delete(out, m.group(1))
            h._json({"ok": True})
        else:
            h._json(remake.public(out, remake.update(out, m.group(1), body)))
        return True
    # ---- video kolase
    if p == "/api/kolase":
        h._json(kolase.public(out, kolase.new_project(out, body)), 201)
        return True
    if p == "/api/kolase/paket":
        if not h.is_local:
            raise ValueError("Lokasi paket hanya bisa diatur dari laptop.")
        from .webapp import save_env
        path = str(body.get("path") or "").strip().strip('"')
        save_env({kolase.PAKET_ENV: path})
        os.environ[kolase.PAKET_ENV] = path
        h._json(kolase.paket_status())
        return True
    m = re.fullmatch(r"/api/kolase/([a-f0-9]{10})/foto", p)
    if m:
        h._json(kolase.set_scene_photo(out, m.group(1), str(body.get("scene") or ""), str(body.get("image") or ""),
                                       bool(body.get("remove"))))
        return True
    m = re.fullmatch(r"/api/kolase/([a-f0-9]{10})(/delete)?", p)
    if m:
        if m.group(2):
            kolase.delete(out, m.group(1))
            h._json({"ok": True})
        else:
            upd = kolase.update(out, m.group(1), body)
            h._json(dict(kolase.public(out, upd), notices=upd.get("notices", [])))
        return True
    # ---- posting
    if p in ("/api/publish/youtube/client", "/api/publish/tiktok/client"):
        if not h.is_local:
            raise ValueError("Hanya bisa diatur dari laptop.")
        from .webapp import save_env
        names = (("client_id", "YT_CLIENT_ID"), ("client_secret", "YT_CLIENT_SECRET")) if "youtube" in p else \
                (("client_key", "TIKTOK_CLIENT_KEY"), ("client_secret", "TIKTOK_CLIENT_SECRET"))
        upd = {env: str(body[k]).strip() for k, env in names if str(body.get(k) or "").strip()}
        if upd:
            save_env(upd)
        h._json(publish.status())
        return True
    if p in ("/api/publish/youtube/connect", "/api/publish/tiktok/connect"):
        if not h.is_local:
            raise ValueError("Tambahkan akun dari browser di laptop (login kembali ke alamat 127.0.0.1).")
        if "youtube" in p:
            url = publish.yt_auth_url(f"http://127.0.0.1:{h.port}/oauth/youtube")
        else:
            url = publish.tt_auth_url(f"http://127.0.0.1:{h.port}/oauth/tiktok/")
        h._json({"url": url})
        return True
    if p == "/api/publish/meta/connect":
        h._json({"added": publish.meta_connect(str(body.get("token") or ""), str(body.get("app_id") or "").strip(),
                                               str(body.get("app_secret") or "").strip()), **publish.status()})
        return True
    if p == "/api/publish/account/remove":
        publish.remove_account(str(body.get("platform") or ""), str(body.get("id") or ""))
        h._json(publish.status())
        return True
    if p == "/api/posts":
        h._json(h.posts.add(body), 201)
        return True
    m = re.fullmatch(r"/api/posts/([a-f0-9]{10})/(cancel|retry|delete)", p)
    if m:
        getattr(h.posts, {"cancel": "cancel", "retry": "retry", "delete": "remove"}[m.group(2)])(m.group(1))
        h._json({"items": h.posts.list()})
        return True
    return False
