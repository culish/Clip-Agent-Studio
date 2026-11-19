"""Unduh video + subtitle dari YouTube memakai yt-dlp (dengan cache per video)."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .utils import ClipAgentError, check_cancel, log, probe, progress

VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov")


class _QuietLogger:
    """Bungkam log yt-dlp; error tetap ditangkap dan dijelaskan oleh agen."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


_YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")


def youtube_id(url: str) -> str | None:
    m = _YT_ID.search(url)
    return m.group(1) if m else None


def _cached(out_root: Path, url: str) -> tuple[Path, dict, dict | None, str] | None:
    """Pakai hasil unduhan sebelumnya tanpa menghubungi YouTube (render ulang, offline)."""
    vid = youtube_id(url)
    if not vid:
        return None
    workdir = out_root / vid
    video = _find_video(workdir)
    meta_path = workdir / "meta.json"
    has_text = (workdir / "transcript.json").is_file() or (workdir / "captions.json3").is_file()
    if not (video and meta_path.is_file() and has_text):
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # unduhan lama beresolusi rendah karena dulu belum ada Deno: unduh ulang videonya sekarang
    try:
        short = meta.get("source_height") or min(probe(video)["width"], probe(video)["height"])
    except ClipAgentError:
        short = 9999
    if short < 720 and not meta.get("js_runtime") and shutil.which("deno"):
        log(f"Video di cache hanya {short}p dan diunduh sebelum Deno terpasang; mengunduh ulang dengan kualitas penuh.")
        video.unlink(missing_ok=True)
        return None
    captions, cap_source = None, ""
    if (workdir / "captions.json3").is_file():
        captions = json.loads((workdir / "captions.json3").read_text(encoding="utf-8"))
        src_file = workdir / "captions.source"
        cap_source = src_file.read_text().strip() if src_file.is_file() else "youtube"
    log(f"Memakai video & transkrip dari cache: {workdir}")
    return video, meta, captions, cap_source


def _pick_caption(info: dict, lang: str) -> tuple[str, str] | None:
    """Pilih trek subtitle terbaik: manual (bahasa diminta) > ASR asli (-orig) > ASR bahasa video."""
    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}

    def json3(tracks):
        return next((t["url"] for t in tracks or [] if t.get("ext") == "json3" and t.get("url")), None)

    candidates: list[tuple[str, dict, str]] = []
    vlang = info.get("language")
    if lang:
        candidates += [(k, subs, "manual") for k in subs if k == lang or k.startswith(lang + "-")]
    if vlang:
        candidates += [(k, subs, "manual") for k in subs if k == vlang or k.startswith(vlang + "-")]
    candidates += [(k, autos, "auto") for k in autos if k.endswith("-orig")]
    if vlang:
        candidates += [(k, autos, "auto") for k in autos if k == vlang]
    if lang:
        candidates += [(k, autos, "auto") for k in autos if k == lang]
    for key, table, kind in candidates:
        url = json3(table.get(key))
        if url:
            return url, f"youtube-{kind}:{key}"
    return None


def fetch_youtube(url: str, out_root: Path, lang: str, max_height: int = 1080,
                  cookies: str = "", cookies_from_browser: str = "") -> tuple[Path, dict, dict | None, str]:
    """Kembalikan (path_video, metadata, data_json3_atau_None, label_sumber_subtitle)."""
    hit = _cached(out_root, url)
    if hit:
        return hit
    try:
        import yt_dlp
    except ImportError as exc:
        raise ClipAgentError('yt-dlp belum terpasang. Jalankan: pip install -U "yt-dlp[default]"') from exc

    opts = {
        "format": (f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/"
                   f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"),
        "merge_output_format": "mp4",
        "outtmpl": str(out_root / "%(id)s" / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "progress_hooks": [_progress_hook],
    }
    if cookies:
        opts["cookiefile"] = cookies
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as exc:  # yt_dlp.utils.DownloadError, dll.
            raise ClipAgentError(_explain_ytdlp_error(str(exc))) from exc
        if info.get("_type") == "playlist":
            raise ClipAgentError("URL berupa playlist. Berikan URL satu video saja.")
        workdir = out_root / info["id"]
        workdir.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": info["id"], "title": info.get("title", ""),
            "description": (info.get("description") or "")[:1500],
            "channel": info.get("channel") or info.get("uploader") or "",
            "duration": info.get("duration") or 0, "url": info.get("webpage_url") or url,
            "license": info.get("license") or "",
        }
        (workdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        video = _find_video(workdir)
        if video:
            log(f"Video sudah ada di cache: {video}")
        else:
            if not shutil.which("deno"):
                log("PERINGATAN: Deno belum terpasang. Tanpa Deno, YouTube hanya memberi format terbatas "
                    "(sering 360p/480p). Pasang: winget install DenoLand.Deno, lalu jalankan ulang app.")
            log(f"Mengunduh: {meta['title']} ({meta['duration']} detik)")
            try:
                ydl.process_ie_result(info, download=True)
            except Exception as exc:
                raise ClipAgentError(_explain_ytdlp_error(str(exc))) from exc
            video = _find_video(workdir)
            if not video:
                raise ClipAgentError("Unduhan selesai tetapi file video tidak ditemukan.")
            _check_quality(video, meta, workdir, max_height, info)

        captions, cap_source = None, ""
        cache = workdir / "captions.json3"
        picked = _pick_caption(info, lang)
        if cache.is_file():
            captions = json.loads(cache.read_text(encoding="utf-8"))
            cap_source = (workdir / "captions.source").read_text().strip() if (workdir / "captions.source").is_file() else "youtube"
        elif picked:
            cap_url, cap_source = picked
            try:
                raw = ydl.urlopen(cap_url).read().decode("utf-8")
                captions = json.loads(raw)
                cache.write_text(raw, encoding="utf-8")
                (workdir / "captions.source").write_text(cap_source)
            except Exception as exc:
                log(f"Gagal mengambil subtitle YouTube ({exc}); akan memakai Whisper.")
                captions, cap_source = None, ""
    return video, meta, captions, cap_source


def _check_quality(video: Path, meta: dict, workdir: Path, max_height: int, info: dict) -> None:
    """Catat resolusi hasil unduhan dan jelaskan bila lebih rendah dari yang diminta."""
    try:
        v = probe(video)
    except ClipAgentError:
        return
    short = min(v["width"], v["height"])
    best = max([f.get("height") or 0 for f in info.get("formats") or [] if f.get("vcodec") not in (None, "none")] or [0])
    meta.update(source_height=short, js_runtime=bool(shutil.which("deno")))
    (workdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Resolusi video sumber: {v['width']}x{v['height']}")
    if short >= min(720, max_height):
        return
    if not meta["js_runtime"]:
        log(f"PERINGATAN: video terunduh hanya {short}p karena Deno belum terpasang (YouTube membatasi format). "
            "Klip akan buram. Pasang Deno (winget install DenoLand.Deno), jalankan ulang app, lalu buat ulang klipnya; "
            "video akan diunduh ulang otomatis.")
    elif best and best <= short:
        log(f"Catatan: video aslinya memang hanya {short}p, jadi klipnya tidak bisa lebih tajam.")
    else:
        log(f"PERINGATAN: video terunduh {short}p padahal tersedia sampai {best}p. Perbarui yt-dlp: "
            'pip install -U "yt-dlp[default]", lalu buat ulang klipnya.')


def fetch_source_text(url: str, workdir: Path, lang: str = "en", cookies_from_browser: str = "") -> dict:
    """Ambil metadata + teks ucapan video TANPA mengunduh videonya (untuk riset/naskah orisinal).

    Urutan: subtitle YouTube (json3) -> Whisper dari audio saja (bila terpasang) -> judul+deskripsi.
    Hasil di-cache di workdir/source.json.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    cache = workdir / "source.json"
    if cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("url") == url:
            return data
    try:
        import yt_dlp
    except ImportError as exc:
        raise ClipAgentError('yt-dlp belum terpasang. Jalankan: pip install -U "yt-dlp[default]"') from exc
    from .transcript import words_from_json3, words_from_whisper

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": _QuietLogger(), "skip_download": True}
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as exc:
            raise ClipAgentError(_explain_ytdlp_error(str(exc))) from exc
        if info.get("_type") == "playlist":
            raise ClipAgentError("URL berupa playlist. Berikan URL satu video saja.")
        data = {"url": url, "id": info.get("id", ""), "title": info.get("title", ""),
                "channel": info.get("channel") or info.get("uploader") or "",
                "description": (info.get("description") or "")[:2000], "duration": info.get("duration") or 0,
                "views": info.get("view_count") or 0, "tags": (info.get("tags") or [])[:15],
                "license": info.get("license") or "", "text": "", "text_source": ""}
        picked = _pick_caption(info, lang)
        if picked:
            try:
                raw = json.loads(ydl.urlopen(picked[0]).read().decode("utf-8"))
                data["text"] = " ".join(w.text for w in words_from_json3(raw))
                data["text_source"] = picked[1]
            except Exception as exc:
                log(f"Subtitle tidak bisa diambil ({type(exc).__name__}).")
    if not data["text"]:
        import importlib.util
        if importlib.util.find_spec("faster_whisper") and (data["duration"] or 0) <= 1800:
            log("Video tanpa subtitle: mengunduh audionya saja untuk Whisper...")
            aopts = {**opts, "skip_download": False, "format": "ba/bestaudio/b",
                     "outtmpl": str(workdir / "source_audio.%(ext)s")}
            with yt_dlp.YoutubeDL(aopts) as ydl:
                ydl.download([url])
            audio = next(iter(sorted(workdir.glob("source_audio.*"))), None)
            if audio:
                words, _ = words_from_whisper(audio, "base", None)
                data["text"] = " ".join(w.text for w in words)
                data["text_source"] = "whisper-base"
                audio.unlink(missing_ok=True)
        if not data["text"]:
            log("Teks ucapan tidak tersedia; naskah disusun dari judul dan deskripsi saja.")
            data["text_source"] = "deskripsi"
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def prepare_local(path: str, out_root: Path) -> tuple[Path, dict]:
    """Pakai file video lokal (mis. rekaman kuliah sendiri) tanpa mengunduh."""
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise ClipAgentError(f"File tidak ditemukan: {src}")
    from .utils import slugify
    vid = slugify(src.stem, 50)
    workdir = out_root / vid
    workdir.mkdir(parents=True, exist_ok=True)
    meta = {"id": vid, "title": src.stem, "description": "", "channel": "",
            "duration": probe(src)["duration"], "url": str(src)}
    (workdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return src, meta


def _progress_hook(d: dict) -> None:
    check_cancel()
    if d.get("status") == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if total:
            # video & audio diunduh terpisah; cukup tampilkan progres file yang sedang berjalan
            progress(0.02 + 0.28 * min(1.0, d.get("downloaded_bytes", 0) / total), "Mengunduh video")


def _find_video(workdir: Path) -> Path | None:
    for ext in VIDEO_EXTS:
        p = workdir / f"source{ext}"
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def _explain_ytdlp_error(msg: str) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)               # buang kode warna terminal dari yt-dlp
    low = msg.lower()
    hint = ""
    browser = (os.getenv("COOKIES_FROM_BROWSER") or "").lower()
    on_windows = os.name == "nt"
    if any(k in low for k in ("failed to decrypt", "dpapi", "could not copy", "cookie database", "app-bound")):
        hint = ("Cookies browser tidak bisa dibaca. Chrome, Edge, dan Brave versi baru di Windows mengenkripsi "
                "cookies sehingga yt-dlp tidak bisa membacanya. Di tab Pengaturan, ganti 'Cookies browser' ke Firefox, "
                "lalu login YouTube di Firefox.")
    elif "not a bot" in low or ("sign in to confirm you" in low and "age" not in low):
        if browser == "firefox":
            hint = ("Cookies Firefox sudah dipakai tetapi masih ditolak. Buka youtube.com di Firefox dan pastikan "
                    "sudah login, lalu coba lagi. Bila tetap gagal: matikan VPN, dan perbarui yt-dlp "
                    '(pip install -U "yt-dlp[default]").')
        elif browser and on_windows:
            hint = (f"Cookies {browser.title()} di Windows tidak bisa dibaca yt-dlp (enkripsi Chrome 127+). "
                    "Di tab Pengaturan, ganti 'Cookies browser' ke Firefox, lalu login YouTube di Firefox.")
        else:
            hint = ("YouTube meminta verifikasi bot. Pasang Firefox, login YouTube di Firefox (akun cadangan lebih aman), "
                    "lalu di tab Pengaturan pilih 'Cookies browser untuk YouTube' = Firefox dan simpan. "
                    "Di terminal: --cookies-from-browser firefox.")
    elif "private" in low or "members-only" in low or "confirm your age" in low or "age-restricted" in low:
        hint = ("Video privat/khusus member/terbatas usia: di tab Pengaturan pilih 'Cookies browser' = Firefox "
                "dan login di Firefox dengan akun yang punya akses.")
    elif "javascript" in low or "js runtime" in low or "n challenge" in low:
        hint = ('yt-dlp butuh runtime JavaScript. Install Deno (https://deno.com) lalu '
                'jalankan: pip install -U "yt-dlp[default]"')
    elif "requested format is not available" in low:
        hint = 'Perbarui yt-dlp: pip install -U "yt-dlp[default]", dan pastikan Deno terpasang.'
    elif "unable to connect" in low or "timed out" in low or "getaddrinfo" in low:
        hint = "Tidak bisa terhubung ke YouTube. Periksa koneksi internet/proxy."
    elif shutil.which("ffmpeg") is None:
        hint = "ffmpeg tidak ditemukan; yt-dlp butuh ffmpeg untuk menggabungkan video+audio."
    else:
        hint = 'Coba perbarui yt-dlp: pip install -U "yt-dlp[default]".'
    first = msg.strip().splitlines()[0] if msg.strip() else "error tidak diketahui"
    first = first.replace("ERROR: ", "").split("; please report")[0][:300]
    return f"Gagal mengambil video dari YouTube: {first}\nSaran: {hint}"
