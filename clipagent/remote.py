"""Akses dari HP: server kedua di IP Wi-Fi/LAN laptop, dilindungi kode akses.

- Permintaan dari laptop sendiri (127.0.0.1) tidak perlu kode.
- Permintaan dari HP harus membawa cookie `ca_token` (didapat lewat /connect?code=...).
- Kode berbentuk 8 karakter (mis. K7P2-9QXA), disimpan di .env agar HP tetap terhubung
  setelah laptop dinyalakan ulang. Percobaan kode salah dibatasi per alamat IP.
"""
from __future__ import annotations

import hmac
import html
import os
import re
import secrets
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import quote

from .utils import ClipAgentError

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # tanpa 0/O/1/I agar mudah diketik
APP_PACKAGE = "id.clipagent.app"
COOKIE = "ca_token"


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def lan_ip() -> str | None:
    """Alamat IP laptop di jaringan lokal (tanpa mengirim paket ke internet)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


class Remote:
    def __init__(self) -> None:
        self.httpd: ThreadingHTTPServer | None = None
        self.ip: str | None = None
        self.port: int | None = None
        self.code = os.getenv("LAN_ACCESS_CODE", "")
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.httpd is not None

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}:{self.port}" if self.enabled else ""

    @property
    def server_addr(self) -> str:
        return f"{self.ip}:{self.port}" if self.enabled else ""

    def start(self, handler_cls, port: int) -> None:
        if self.enabled:
            return
        ip = lan_ip()
        if not ip:
            raise ClipAgentError("Laptop belum terhubung ke jaringan Wi-Fi atau LAN.")
        if not self.code:
            self.code = new_code()
        try:
            httpd = ThreadingHTTPServer((ip, port), handler_cls)
        except OSError as exc:
            raise ClipAgentError(f"Tidak bisa membuka akses di {ip}:{port} ({exc}).") from exc
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True, name="clip-lan").start()
        self.httpd, self.ip, self.port = httpd, ip, port

    def stop(self) -> None:
        httpd, self.httpd = self.httpd, None
        if httpd:
            httpd.shutdown()
            httpd.server_close()

    def regenerate(self) -> str:
        self.code = new_code()
        return self.code

    # ---------------- autentikasi
    def check(self, token: str) -> bool:
        return bool(self.code) and hmac.compare_digest(normalize(token), normalize(self.code))

    def blocked(self, ip: str) -> bool:
        with self._lock:
            count, t0 = self._fails.get(ip, (0, 0.0))
            if time.time() - t0 > 900:
                self._fails.pop(ip, None)
                return False
            return count >= 8

    def record_fail(self, ip: str) -> None:
        with self._lock:
            count, t0 = self._fails.get(ip, (0, time.time()))
            self._fails[ip] = (count + 1, t0)

    def clear_fail(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)

    # ---------------- tautan & QR
    def connect_url(self) -> str:
        return f"{self.base_url}/connect?code={quote(self.code)}&welcome=1" if self.enabled else ""

    def app_link(self) -> str:
        """Tautan intent Android: buka aplikasi Clip Agent; jika belum terpasang, lanjut di browser."""
        fallback = quote(f"{self.base_url}/", safe="")
        return (f"intent://pair?server={quote(self.server_addr)}&code={quote(self.code)}"
                f"#Intent;scheme=clipagent;package={APP_PACKAGE};S.browser_fallback_url={fallback};end")

    def qr_svg(self) -> str:
        if not self.enabled:
            return ""
        try:
            import segno
        except ImportError:
            return ""
        return segno.make(self.connect_url(), error="m").svg_inline(scale=5, border=4, dark="#1B1836",
                                                                  light="#FFFFFF")


# ====================================================================== halaman HTML kecil
_PAGE = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Clip Agent</title>
<style>
@font-face {{ font-family: "Anton"; src: url("/fonts/Anton-Regular.ttf"); }}
:root {{ --paper:#EDEFF5; --panel:#fff; --ink:#1B1836; --ink2:#57547A; --line:#D6D8E6; --violet:#4A2FE6; --marker:#FFE24A; --bad:#C02A3F; }}
@media (prefers-color-scheme: dark) {{ :root {{ --paper:#121128; --panel:#1B1938; --ink:#EFEEFF; --ink2:#A9A6CF; --line:#312E5A; --violet:#8F7DFF; --bad:#FF6B7F; }} }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.5 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif; }}
main {{ max-width:440px; margin:0 auto; padding:40px 20px; display:grid; gap:18px; }}
h1 {{ font-family:Anton,Impact,sans-serif; font-weight:400; font-size:40px; line-height:1.05; margin:0; }}
p {{ margin:0; }} .muted {{ color:var(--ink2); font-size:14px; }} .err {{ color:var(--bad); font-weight:600; }}
input {{ width:100%; font:inherit; font-size:22px; letter-spacing:.12em; text-transform:uppercase; padding:12px 14px; border:2px solid var(--ink); border-radius:12px; background:var(--panel); color:var(--ink); }}
.btn {{ display:flex; align-items:center; justify-content:center; min-height:50px; border-radius:12px; font-weight:700; text-decoration:none; border:1px solid var(--line); background:var(--panel); color:var(--ink); font-size:16px; cursor:pointer; width:100%; }}
.btn.primary {{ background:var(--violet); border-color:var(--violet); color:#fff; }}
.brand {{ font-family:Anton,Impact,sans-serif; font-size:22px; display:flex; gap:10px; align-items:center; }}
.mark {{ width:14px; height:22px; border-radius:4px; background:var(--violet); position:relative; }}
.mark::after {{ content:""; position:absolute; left:3px; right:3px; bottom:5px; height:3px; background:var(--marker); }}
[hidden] {{ display:none !important; }}
</style></head><body><main><div class="brand"><span class="mark"></span>Clip Agent</div>{body}</main></body></html>"""


def page(body: str) -> bytes:
    return _PAGE.format(body=body).encode("utf-8")


def login_page(error: str = "", next_path: str = "/") -> bytes:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return page(f"""<h1>Masukkan kode akses</h1>
<p class="muted">Kode tampil di laptop: buka Clip Agent, tab <b>Pengaturan</b>, bagian <b>Akses dari HP</b>.</p>
{err}
<form method="post" action="/connect" style="display:grid;gap:12px">
  <input name="code" autocomplete="one-time-code" placeholder="XXXX-XXXX" required autofocus>
  <input type="hidden" name="next" value="{html.escape(next_path)}">
  <button class="btn primary" type="submit">Hubungkan</button>
</form>
<button class="btn" type="button" id="chg" hidden onclick="ClipAgentApp.changeServer()">Ganti alamat laptop</button>
<script>if (window.ClipAgentApp) document.getElementById("chg").hidden = false;</script>""")


def welcome_page(remote: Remote, has_apk: bool) -> bytes:
    apk = ('<a class="btn" href="/app/ClipAgent.apk">Unduh aplikasi Android (APK)</a>'
           '<p class="muted">Setelah terpasang, pindai QR di laptop sekali lagi lalu pilih '
           '"Buka di aplikasi".</p>') if has_apk else ""
    return page(f"""<h1>HP sudah terhubung ke laptop</h1>
<p class="muted">Pakai Clip Agent lewat aplikasi Android atau langsung di browser ini.</p>
<a class="btn primary" href="{html.escape(remote.app_link())}">Buka di aplikasi Clip Agent</a>
<a class="btn" href="/">Lanjut di browser</a>
{apk}""")


def blocked_page() -> bytes:
    return page("""<h1>Terlalu banyak percobaan</h1>
<p class="muted">Kode salah dimasukkan berkali-kali. Tunggu 15 menit lalu coba lagi,
atau pindai ulang kode QR di laptop.</p>""")
