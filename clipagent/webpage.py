"""Halaman web sebagai bahan video: teks artikel, judul, situs, gambar, dan tangkapan layar ponsel.

Dipakai format Reels (Phone in hand, News brief, Proof Punch): teks untuk naskah dan kutipan asli, tangkapan layar
untuk ditampilkan di layar ponsel. Tangkapan layar memakai browser yang sama dengan Remotion (chrome-headless-shell).
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import PROJECT_DIR
from .utils import ClipAgentError, log

UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/131.0 Mobile Safari/537.36")
VIDEO_HOSTS = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com", "fb.watch", "x.com",
               "twitter.com", "vimeo.com", "dailymotion.com")


def is_video_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS)


def site_name(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def _meta(doc: str, *names: str) -> str:
    for n in names:
        m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']*)', doc, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']' + re.escape(n) + r'["\']', doc, re.I)
        if m and m.group(1).strip():
            return htmllib.unescape(m.group(1).strip())
    return ""


def extract(doc: str, url: str = "") -> dict:
    """Judul, deskripsi, gambar, dan teks utama dari HTML (tanpa pustaka tambahan)."""
    title = _meta(doc, "og:title", "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>([\s\S]*?)</title>", doc, re.I)
        title = htmllib.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    body = re.sub(r"<(script|style|noscript|svg|nav|footer|header|form|aside)[\s\S]*?</\1>", " ", doc, flags=re.I)
    art = re.search(r"<article[\s\S]*?</article>", body, re.I)
    scope = art.group(0) if art and len(art.group(0)) > 1500 else body
    paras = []
    for m in re.finditer(r"<(p|h1|h2|h3|li|blockquote)[^>]*>([\s\S]*?)</\1>", scope, re.I):
        t = htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 40 or (m.group(1).lower() in ("h1", "h2", "h3") and len(t) >= 8):
            paras.append(t)
    seen, uniq = set(), []
    for t in paras:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return {"url": url, "title": title[:300], "site": _meta(doc, "og:site_name") or site_name(url),
            "description": _meta(doc, "og:description", "description", "twitter:description")[:600],
            "image": _meta(doc, "og:image", "twitter:image"), "published": _meta(doc, "article:published_time", "date"),
            "text": "\n".join(uniq)[:20000]}


def _check_url(url: str) -> None:
    if not re.match(r"https?://[^\s/]+", url or "", re.I):
        raise ClipAgentError("Tautan harus diawali http:// atau https://.")


def fetch(url: str, timeout: int = 25) -> dict:
    _check_url(url)
    try:
        r = requests.get(url, headers={"User-Agent": UA_DESKTOP, "Accept-Language": "id,en;q=0.8"}, timeout=timeout)
    except requests.RequestException as exc:
        raise ClipAgentError(f"Halaman tidak bisa dibuka: {exc}") from exc
    if r.status_code >= 400:
        raise ClipAgentError(f"Halaman menjawab {r.status_code}: {url}")
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "xml" not in ctype and ctype:
        raise ClipAgentError(f"Tautan ini bukan halaman web ({ctype.split(';')[0]}).")
    r.encoding = r.encoding or r.apparent_encoding
    page = extract(r.text, r.url or url)
    if len(page["text"]) < 200 and not page["description"]:
        log("  Teks halaman sedikit (mungkin dibuat dengan JavaScript); naskah memakai judul dan deskripsinya.")
    return page


# ---------------------------------------------------------------- tangkapan layar
def browser_bin() -> str | None:
    """Browser Remotion (chrome-headless-shell) atau Chrome/Chromium yang terpasang."""
    env = os.getenv("REMOTION_BROWSER_EXECUTABLE")
    if env and Path(env).is_file():
        return env
    root = PROJECT_DIR / "remotion" / "node_modules" / ".remotion"
    if root.is_dir():
        for name in ("chrome-headless-shell.exe", "chrome-headless-shell", "chrome.exe", "chrome"):
            for p in root.rglob(name):
                if p.is_file():
                    return str(p)
    import shutil
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    if os.name == "nt":
        for base in (os.getenv("ProgramFiles", ""), os.getenv("ProgramFiles(x86)", ""), os.getenv("LOCALAPPDATA", "")):
            p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if base and p.is_file():
                return str(p)
    return None


def _ensure_browser() -> str | None:
    exe = browser_bin()
    if exe:
        return exe
    rdir = PROJECT_DIR / "remotion"
    if (rdir / "node_modules" / "@remotion" / "renderer").is_dir():
        try:
            subprocess.run(["node", "-e", "require('@remotion/renderer').ensureBrowser().then(()=>process.exit(0))"],
                           cwd=str(rdir), capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            return None
    return browser_bin()


def screenshot(url: str, out: Path, width: int = 412, height: int = 2600, scale: int = 2, wait_ms: int = 9000) -> Path:
    """Tangkapan layar halaman seperti di ponsel (lebar 412 px CSS, resolusi 2x)."""
    _check_url(url)                                   # juga mencegah tautan dibaca sebagai opsi browser
    exe = _ensure_browser()
    if not exe:
        raise ClipAgentError("Browser untuk tangkapan layar belum ada. Render satu video sekali agar Remotion memasangnya.")
    out.parent.mkdir(parents=True, exist_ok=True)
    headless = "--headless" if "headless-shell" in Path(exe).name else "--headless=new"
    cmd = [exe, headless, "--disable-gpu", "--hide-scrollbars", "--mute-audio", f"--window-size={width},{height}",
           f"--force-device-scale-factor={scale}", f"--user-agent={UA_MOBILE}", f"--virtual-time-budget={wait_ms}",
           "--run-all-compositor-stages-before-draw", f"--screenshot={out.resolve()}", "--lang=id-ID", url]
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    try:
        subprocess.run(cmd, capture_output=True, timeout=90, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClipAgentError(f"Tangkapan layar gagal: {exc}") from exc
    if not out.is_file() or out.stat().st_size < 2000:
        raise ClipAgentError("Tangkapan layar gagal (halaman tidak termuat).")
    _trim_bottom(out)
    return out


def _trim_bottom(path: Path) -> None:
    """Buang bagian bawah yang kosong (halaman pendek) agar gulirannya berhenti di isi halaman."""
    try:
        import cv2
        import numpy as np
        im = cv2.imread(str(path))
        if im is None:
            return
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.int16)
        busy = np.where(np.abs(g - g[:, :1]).max(axis=1) > 12)[0]       # baris yang tidak satu warna
        if len(busy):
            end = min(im.shape[0], int(busy[-1]) + int(im.shape[1] * 0.12))
            if end < im.shape[0] - 40:
                cv2.imwrite(str(path), im[:max(end, int(im.shape[1] * 1.6))])
    except Exception:                                                      # noqa: BLE001
        pass


def image_ratio(path: Path) -> float:
    """Tinggi / lebar gambar (untuk menghitung seberapa jauh layar ponsel bisa digulir)."""
    try:
        import cv2
        im = cv2.imread(str(path))
        return round(im.shape[0] / im.shape[1], 3) if im is not None else 0.0
    except Exception:                                                      # noqa: BLE001
        return 0.0


def page_card(page: dict) -> dict:
    """Ringkasan aman untuk ditampilkan di template (tanpa HTML)."""
    return {"title": page.get("title", "")[:160], "site": page.get("site", "")[:60], "url": page.get("url", ""),
            "description": page.get("description", "")[:300]}


def dump(page: dict) -> str:
    return json.dumps(page, ensure_ascii=False)
