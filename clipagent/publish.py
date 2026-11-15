"""Posting otomatis ke banyak akun: YouTube, Facebook Page (Reels), Instagram (Reels), dan TikTok.

Setiap platform bisa punya banyak akun. Satu posting bisa dikirim ke kombinasi akun mana pun, misalnya
2 channel YouTube + 3 akun TikTok sekaligus; masing-masing jadi target terpisah di antrean.

- YouTube: OAuth 2.0 aplikasi desktop (redirect loopback ke Clip Agent). Setiap login = satu channel.
  Jadwal memakai publishAt, jadi YouTube yang menayangkan.
- Facebook & Instagram: token Meta; semua Page (dan akun Instagram yang terhubung ke Page) ikut ditambahkan.
- TikTok: Login Kit for Desktop (OAuth v2 + PKCE) lalu Content Posting API: Direct Post (langsung terbit)
  atau kirim ke draf/inbox TikTok. Aplikasi TikTok yang belum diaudit hanya boleh memposting sebagai privat.
Token disimpan di data/accounts.json di folder aplikasi (jangan dibagikan).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import string
import threading
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import urlencode

import requests

from .config import PROJECT_DIR
from .utils import ClipAgentError, probe

DATA_DIR = PROJECT_DIR / "data"
ACCOUNTS = DATA_DIR / "accounts.json"
PLATFORMS = ("youtube", "facebook", "instagram", "tiktok")
LABELS = {"youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok"}
YT_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TT_DEFAULT_SCOPES = "user.info.basic,video.publish,video.upload"
_LOCK = threading.RLock()
_PENDING: dict[str, dict] = {}


def _env(name: str, default: str) -> str:
    return (os.getenv(name) or default).rstrip("/")


def g_auth() -> str:
    return _env("GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")


def g_token() -> str:
    return _env("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")


def yt_api() -> str:
    return _env("YT_API_BASE", "https://www.googleapis.com/youtube/v3")


def yt_upload() -> str:
    return _env("YT_UPLOAD_BASE", "https://www.googleapis.com/upload/youtube/v3")


def graph() -> str:
    return _env("META_GRAPH_BASE", "https://graph.facebook.com") + "/" + (os.getenv("META_GRAPH_VERSION") or "v26.0")


def rupload() -> str:
    return _env("META_RUPLOAD_BASE", "https://rupload.facebook.com")


def tt_auth() -> str:
    return os.getenv("TIKTOK_AUTH_URL") or "https://www.tiktok.com/v2/auth/authorize/"


def tt_api() -> str:
    return _env("TIKTOK_API_BASE", "https://open.tiktokapis.com")


def tt_scopes() -> str:
    return os.getenv("TIKTOK_SCOPES") or TT_DEFAULT_SCOPES


# ---------------------------------------------------------------- penyimpanan akun
def _migrate(old: dict) -> dict:
    """Format lama (satu akun per platform) -> format baru (daftar akun per platform)."""
    new = {"version": 2, "youtube": [], "facebook": [], "instagram": [], "tiktok": []}
    yt = old.get("youtube") or {}
    if isinstance(yt, dict) and yt.get("refresh_token"):
        new["youtube"].append({"id": yt.get("channel_id") or "youtube-1", "name": yt.get("channel_title") or "YouTube",
                               "refresh_token": yt["refresh_token"], "access_token": yt.get("access_token", ""),
                               "expires": yt.get("expires", 0), "added": time.time()})
    for p in (old.get("meta") or {}).get("pages", []):
        new["facebook"].append({"id": p["id"], "name": p.get("name", ""), "access_token": p.get("access_token", ""),
                                "added": time.time()})
        if p.get("ig"):
            new["instagram"].append({"id": p["ig"]["id"], "name": p["ig"].get("username", ""), "page_id": p["id"],
                                     "page_name": p.get("name", ""), "access_token": p.get("access_token", ""),
                                     "added": time.time()})
    return new


def load_accounts() -> dict:
    with _LOCK:
        data = {}
        if ACCOUNTS.is_file():
            try:
                data = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
        if data and data.get("version") != 2:
            data = _migrate(data)
            save_accounts(data)
        data.setdefault("version", 2)
        for p in PLATFORMS:
            data.setdefault(p, [])
        return data


def save_accounts(data: dict) -> None:
    with _LOCK:
        DATA_DIR.mkdir(exist_ok=True)
        ACCOUNTS.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(ACCOUNTS, 0o600)
        except OSError:
            pass


def _upsert(platform: str, item: dict) -> None:
    with _LOCK:
        acc = load_accounts()
        lst = acc[platform]
        old = next((x for x in lst if x["id"] == item["id"]), None)
        if old:
            old.update(item)
        else:
            item.setdefault("added", time.time())
            lst.append(item)
        save_accounts(acc)


def get_account(platform: str, aid: str | None) -> dict:
    lst = load_accounts().get(platform) or []
    if not lst:
        raise ClipAgentError(f"Belum ada akun {LABELS.get(platform, platform)} yang terhubung (tab Posting).")
    if aid is None:                                     # posting lama tanpa ID akun
        return lst[0]
    acc = next((x for x in lst if x["id"] == aid), None)
    if not acc:
        raise ClipAgentError(f"Akun {LABELS.get(platform, platform)} ini sudah dihapus dari Clip Agent.")
    return acc


def remove_account(platform: str, aid: str) -> None:
    if platform not in PLATFORMS:
        raise ClipAgentError("Platform tidak dikenal.")
    with _LOCK:
        acc = load_accounts()
        gone = next((x for x in acc[platform] if x["id"] == aid), None)
        acc[platform] = [x for x in acc[platform] if x["id"] != aid]
        save_accounts(acc)
    if platform == "tiktok" and gone and gone.get("access_token"):
        try:                                            # cabut izin di TikTok juga (tidak wajib berhasil)
            requests.post(f"{tt_api()}/v2/oauth/revoke/", timeout=15, data={
                "client_key": os.getenv("TIKTOK_CLIENT_KEY", ""), "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", ""),
                "token": gone["access_token"]})
        except requests.RequestException:
            pass


def status() -> dict:
    acc = load_accounts()
    out = {"clients": {"youtube": bool(os.getenv("YT_CLIENT_ID") and os.getenv("YT_CLIENT_SECRET")),
                       "tiktok": bool(os.getenv("TIKTOK_CLIENT_KEY") and os.getenv("TIKTOK_CLIENT_SECRET"))},
           "accounts": {}}
    for p in PLATFORMS:
        items = []
        for a in acc[p]:
            it = {"id": a["id"], "name": a.get("name") or a["id"], "key": f"{p}:{a['id']}"}
            if p == "instagram":
                it["detail"] = f"lewat Page {a.get('page_name', '')}"
            if p == "tiktok":
                sc = a.get("scope", "")
                it.update(username=a.get("username", ""), avatar=a.get("avatar", ""),
                          modes=[m for m, s in (("direct", "video.publish"), ("inbox", "video.upload")) if s in sc])
            items.append(it)
        out["accounts"][p] = items
    return out


# ---------------------------------------------------------------- PKCE / OAuth util
def _new_state(kind: str, **extra) -> str:
    now = time.time()
    for k in [k for k, v in _PENDING.items() if now - v["t"] > 1800]:
        _PENDING.pop(k, None)
    state = secrets.token_urlsafe(18)
    _PENDING[state] = {"kind": kind, "t": now, **extra}
    return state


def _take_state(kind: str, params: dict) -> dict:
    pend = _PENDING.pop(params.get("state", ""), None)
    if not pend or pend["kind"] != kind:
        raise ClipAgentError("Sesi login kedaluwarsa. Ulangi dari tab Posting.")
    if params.get("error"):
        raise ClipAgentError(f"Login dibatalkan: {params.get('error_description') or params['error']}")
    return pend


# ---------------------------------------------------------------- YouTube
def yt_auth_url(redirect_uri: str) -> str:
    cid = os.getenv("YT_CLIENT_ID")
    if not cid or not os.getenv("YT_CLIENT_SECRET"):
        raise ClipAgentError("Isi YouTube OAuth Client ID dan Client Secret dulu.")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = _new_state("youtube", verifier=verifier, redirect=redirect_uri)
    q = {"client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "scope": YT_SCOPES,
         "access_type": "offline", "prompt": "consent select_account", "state": state, "code_challenge": challenge,
         "code_challenge_method": "S256"}
    return f"{g_auth()}?{urlencode(q)}"


def yt_callback(params: dict) -> str:
    pend = _take_state("youtube", params)
    r = requests.post(g_token(), data={
        "code": params.get("code", ""), "client_id": os.getenv("YT_CLIENT_ID"),
        "client_secret": os.getenv("YT_CLIENT_SECRET"), "redirect_uri": pend["redirect"],
        "grant_type": "authorization_code", "code_verifier": pend["verifier"]}, timeout=30)
    if not r.ok:
        raise ClipAgentError(f"Gagal menukar kode login (HTTP {r.status_code}): {r.text[:200]}")
    tok = r.json()
    access = tok["access_token"]
    ch = requests.get(f"{yt_api()}/channels", params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {access}"}, timeout=30)
    items = (ch.json().get("items") or []) if ch.ok else []
    if not items:
        raise ClipAgentError("Akun Google ini belum punya channel YouTube, atau channel tidak dipilih saat login.")
    item = items[0]
    old = next((x for x in load_accounts()["youtube"] if x["id"] == item["id"]), {})
    _upsert("youtube", {"id": item["id"], "name": (item.get("snippet") or {}).get("title", "YouTube"),
                        "refresh_token": tok.get("refresh_token") or old.get("refresh_token", ""),
                        "access_token": access, "expires": time.time() + int(tok.get("expires_in", 3600)) - 60})
    return (item.get("snippet") or {}).get("title", "YouTube")


def _yt_token(acct: dict) -> str:
    if acct.get("access_token") and acct.get("expires", 0) > time.time():
        return acct["access_token"]
    if not acct.get("refresh_token"):
        raise ClipAgentError(f"Izin channel {acct.get('name')} tidak lengkap. Hubungkan ulang channel ini.")
    r = requests.post(g_token(), data={"client_id": os.getenv("YT_CLIENT_ID"), "client_secret": os.getenv("YT_CLIENT_SECRET"),
                                       "refresh_token": acct["refresh_token"], "grant_type": "refresh_token"}, timeout=30)
    if not r.ok:
        raise ClipAgentError(f"Izin YouTube untuk {acct.get('name')} kedaluwarsa atau dicabut. Tambahkan ulang channel ini "
                             "di tab Posting. (Bila aplikasi OAuth masih berstatus 'Testing', izin berlaku 7 hari.)")
    tok = r.json()
    _upsert("youtube", {"id": acct["id"], "access_token": tok["access_token"],
                        "expires": time.time() + int(tok.get("expires_in", 3600)) - 60})
    return tok["access_token"]


def youtube_upload(path: Path, post: dict, target: dict, on_progress=None) -> dict:
    acct = get_account("youtube", target.get("account"))
    token = _yt_token(acct)
    info = probe(path)
    is_short = info["height"] > info["width"] and info["duration"] <= 180
    desc = post.get("description", "")
    tags = [t.lstrip("#") for t in post.get("hashtags", [])]
    if tags:
        desc = (desc + "\n\n" + " ".join("#" + t for t in tags[:8])).strip()
    status_ = {"privacyStatus": post.get("privacy") or "public", "selfDeclaredMadeForKids": False,
               "containsSyntheticMedia": bool(post.get("ai"))}
    if post.get("schedule") and post["schedule"] > time.time() + 15 * 60:
        status_["privacyStatus"] = "private"
        status_["publishAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(post["schedule"]))
    meta = {"snippet": {"title": (post.get("title") or path.stem)[:100].replace("<", "").replace(">", ""),
                        "description": desc.replace("<", "").replace(">", "")[:4900], "tags": tags[:15],
                        "categoryId": str(post.get("category") or "22")},
            "status": status_}
    size = path.stat().st_size
    r = requests.post(f"{yt_upload()}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
                      json=meta, timeout=60)
    if not r.ok:
        raise ClipAgentError(_yt_error(r))
    loc = r.headers.get("Location")
    if not loc:
        raise ClipAgentError("YouTube tidak memberi alamat upload.")
    with path.open("rb") as fh:
        up = requests.put(loc, data=_Reader(fh, size, on_progress), timeout=3600,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4",
                                   "Content-Length": str(size)})
    if not up.ok:
        raise ClipAgentError(_yt_error(up))
    vid = up.json().get("id", "")
    url = f"https://youtube.com/shorts/{vid}" if is_short else f"https://www.youtube.com/watch?v={vid}"
    return {"id": vid, "url": url, "scheduled": status_.get("publishAt", "")}


def _yt_error(r: requests.Response) -> str:
    try:
        err = r.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "")
    except ValueError:
        reason, msg = "", r.text[:200]
    hints = {"quotaExceeded": "Kuota upload YouTube API hari ini habis.",
             "uploadLimitExceeded": "Channel mencapai batas upload harian YouTube.",
             "youtubeSignupRequired": "Akun Google ini belum punya channel YouTube.",
             "invalidTitle": "Judul tidak valid.", "invalidDescription": "Deskripsi tidak valid."}
    return f"YouTube: {hints.get(reason, msg or f'HTTP {r.status_code}')}"


class _Reader:
    """Pembaca file untuk upload yang melaporkan progres."""

    def __init__(self, fh, size, cb, base: int = 0, total: int | None = None):
        self.fh, self.size, self.cb, self.done = fh, size, cb, 0
        self.base, self.total = base, total or size

    def __len__(self):
        return self.size

    def read(self, n=-1):
        want = 1 << 20 if n is None or n < 0 else n
        chunk = self.fh.read(min(want, self.size - self.done))
        self.done += len(chunk)
        if self.cb:
            self.cb((self.base + self.done) / max(1, self.total))
        return chunk


# ---------------------------------------------------------------- Meta (Facebook & Instagram)
def meta_connect(user_token: str, app_id: str = "", app_secret: str = "") -> dict:
    token = (user_token or "").strip()
    if not token:
        raise ClipAgentError("Tempel access token Meta.")
    if app_id and app_secret:
        r = requests.get(f"{graph()}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
            "fb_exchange_token": token}, timeout=30)
        if r.ok and r.json().get("access_token"):
            token = r.json()["access_token"]
    r = requests.get(f"{graph()}/me/accounts", params={
        "fields": "id,name,access_token,instagram_business_account{id,username}", "access_token": token,
        "limit": 100}, timeout=30)
    if not r.ok:
        raise ClipAgentError(_meta_error(r))
    pages = r.json().get("data") or []
    if not pages:
        raise ClipAgentError("Token valid, tetapi tidak ada Facebook Page. Pastikan izin pages_show_list dan "
                             "Page dipilih saat membuat token.")
    added = {"facebook": 0, "instagram": 0}
    for p in pages:
        _upsert("facebook", {"id": p["id"], "name": p.get("name", ""), "access_token": p.get("access_token", "")})
        added["facebook"] += 1
        ig = p.get("instagram_business_account")
        if ig:
            _upsert("instagram", {"id": ig["id"], "name": ig.get("username", ""), "page_id": p["id"],
                                  "page_name": p.get("name", ""), "access_token": p.get("access_token", "")})
            added["instagram"] += 1
    return added


def _meta_error(r: requests.Response) -> str:
    try:
        err = r.json().get("error", {})
    except ValueError:
        return f"Meta: HTTP {r.status_code}"
    if err.get("code") == 190:
        return "Meta: token kedaluwarsa atau tidak valid. Tambahkan ulang akun ini di tab Posting."
    if err.get("code") in (10, 200):
        return f"Meta: izin kurang ({err.get('message', '')[:160]})."
    return f"Meta: {err.get('message') or f'HTTP {r.status_code}'}"


def _caption(post: dict, limit: int = 2150) -> str:
    tags = " ".join("#" + t.lstrip("#") for t in post.get("hashtags", [])[:10])
    text = post.get("description", "") or post.get("title", "")
    return (text + ("\n\n" + tags if tags else "")).strip()[:limit]


def facebook_upload(path: Path, post: dict, target: dict, on_progress=None) -> dict:
    page = get_account("facebook", target.get("account"))
    tok = page["access_token"]
    info = probe(path)
    if not 3 <= info["duration"] <= 90:
        raise ClipAgentError("Facebook Reels harus 3–90 detik.")
    r = requests.post(f"{graph()}/{page['id']}/video_reels", json={"upload_phase": "start", "access_token": tok}, timeout=60)
    if not r.ok:
        raise ClipAgentError(_meta_error(r))
    vid = r.json()["video_id"]
    url = r.json().get("upload_url") or f"{rupload()}/video-upload/{graph().rsplit('/', 1)[-1]}/{vid}"
    size = path.stat().st_size
    with path.open("rb") as fh:
        up = requests.post(url, data=_Reader(fh, size, on_progress), timeout=3600,
                           headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size),
                                    "Content-Type": "application/octet-stream"})
    if not up.ok:
        raise ClipAgentError(_meta_error(up))
    params = {"access_token": tok, "video_id": vid, "upload_phase": "finish", "video_state": "PUBLISHED",
              "description": _caption(post), "title": (post.get("title") or "")[:100]}
    sch = post.get("schedule") or 0
    if sch and 10 * 60 + 30 < sch - time.time() < 29 * 86400:
        params.update(video_state="SCHEDULED", scheduled_publish_time=str(int(sch)))
    fin = requests.post(f"{graph()}/{page['id']}/video_reels", params=params, timeout=60)
    if not fin.ok or not fin.json().get("success", True):
        raise ClipAgentError(_meta_error(fin))
    return {"id": vid, "url": f"https://www.facebook.com/reel/{vid}",
            "scheduled": time.strftime("%Y-%m-%d %H:%M", time.localtime(sch)) if params["video_state"] == "SCHEDULED" else ""}


def instagram_upload(path: Path, post: dict, target: dict, on_progress=None) -> dict:
    ig = get_account("instagram", target.get("account"))
    tok = ig["access_token"]
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": _caption(post), "access_token": tok}
    if post.get("ai"):
        params["is_ai_generated"] = "true"
    r = requests.post(f"{graph()}/{ig['id']}/media", params=params, timeout=60)
    if not r.ok:
        raise ClipAgentError(_meta_error(r))
    cid, uri = r.json()["id"], r.json().get("uri")
    uri = uri or f"{rupload()}/ig-api-upload/{graph().rsplit('/', 1)[-1]}/{cid}"
    size = path.stat().st_size
    with path.open("rb") as fh:
        up = requests.post(uri, data=_Reader(fh, size, on_progress), timeout=3600,
                           headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
    if not up.ok:
        raise ClipAgentError(_meta_error(up))
    for _ in range(40):                                    # Instagram memproses video dulu
        st = requests.get(f"{graph()}/{cid}", params={"fields": "status_code,status", "access_token": tok}, timeout=30)
        code = st.json().get("status_code") if st.ok else ""
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise ClipAgentError(f"Instagram gagal memproses video: {st.json().get('status', code)}")
        time.sleep(float(os.getenv("IG_POLL_SECONDS") or 10))
    else:
        raise ClipAgentError("Instagram terlalu lama memproses video. Coba lagi nanti.")
    pub = requests.post(f"{graph()}/{ig['id']}/media_publish", params={"creation_id": cid, "access_token": tok}, timeout=60)
    if not pub.ok:
        raise ClipAgentError(_meta_error(pub))
    mid = pub.json()["id"]
    link = ""
    try:
        link = requests.get(f"{graph()}/{mid}", params={"fields": "permalink", "access_token": tok}, timeout=30).json().get("permalink", "")
    except (requests.RequestException, ValueError):
        pass
    return {"id": mid, "url": link or f"https://www.instagram.com/{ig.get('name', '')}"}


# ---------------------------------------------------------------- TikTok
TT_ERRORS = {
    "access_token_invalid": "izin akun TikTok kedaluwarsa atau dicabut. Tambahkan ulang akun ini di tab Posting.",
    "scope_not_authorized": "akun TikTok ini belum memberi izin posting. Tambahkan ulang akun ini.",
    "spam_risk_too_many_posts": "akun ini sudah mencapai batas posting harian TikTok.",
    "spam_risk_user_banned_from_posting": "akun ini sedang dilarang memposting oleh TikTok.",
    "spam_risk_too_many_pending_share": "sudah ada 5 video menunggu di draf TikTok dalam 24 jam. Selesaikan dulu di aplikasi TikTok.",
    "reached_active_user_cap": "kuota harian aplikasi TikTok Anda (jumlah akun yang memposting) sudah habis.",
    "unaudited_client_can_only_post_to_private_accounts": "aplikasi TikTok Anda belum diaudit, jadi hanya bisa "
        "memposting ke akun TikTok yang diset privat, dengan privasi 'Hanya saya'. Ajukan audit di developers.tiktok.com, "
        "atau pakai mode 'Kirim ke draf TikTok'.",
    "privacy_level_option_mismatch": "pilihan privasi tidak cocok dengan pengaturan akun TikTok. Pilih ulang privasinya.",
    "rate_limit_exceeded": "terlalu banyak permintaan ke TikTok. Coba lagi beberapa menit lagi.",
    "invalid_param": "parameter tidak valid",
}
TT_FAIL = {
    "file_format_check_failed": "format video tidak didukung", "duration_check_failed": "durasi video tidak diizinkan",
    "frame_rate_check_failed": "frame rate video tidak didukung", "picture_size_check_failed": "ukuran video tidak didukung",
    "publish_cancelled": "posting dibatalkan", "auth_removed": "izin akun dicabut",
    "spam_risk_too_many_posts": "batas posting harian tercapai", "spam_risk_text": "teks caption ditandai spam",
    "spam_risk": "ditandai berisiko spam oleh TikTok", "internal": "kesalahan internal TikTok",
}


def _tt_err(data: dict, http: int = 200) -> str:
    err = (data or {}).get("error") or {}
    code = err.get("code") or f"HTTP {http}"
    msg = TT_ERRORS.get(code)
    if code == "invalid_param" and err.get("message"):
        msg = f"parameter tidak valid ({err['message'][:160]})"
    return f"TikTok: {msg or err.get('message') or code}"


def _verifier() -> str:
    chars = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(chars) for _ in range(64))


def tt_auth_url(redirect_uri: str) -> str:
    key = os.getenv("TIKTOK_CLIENT_KEY")
    if not key or not os.getenv("TIKTOK_CLIENT_SECRET"):
        raise ClipAgentError("Isi TikTok Client Key dan Client Secret dulu.")
    verifier = _verifier()
    if (os.getenv("TIKTOK_PKCE_ENCODING") or "hex").lower() == "base64url":
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    else:                                               # dokumentasi Login Kit for Desktop: hex SHA256
        challenge = hashlib.sha256(verifier.encode()).hexdigest()
    state = _new_state("tiktok", verifier=verifier, redirect=redirect_uri)
    q = {"client_key": key, "response_type": "code", "scope": tt_scopes(), "redirect_uri": redirect_uri,
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "disable_auto_auth": "1"}
    return f"{tt_auth()}?{urlencode(q)}"


def _tt_post(path: str, token: str, body: dict, timeout: int = 60) -> dict:
    r = requests.post(f"{tt_api()}{path}", json=body, timeout=timeout,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"})
    try:
        data = r.json()
    except ValueError:
        data = {}
    if not r.ok or ((data.get("error") or {}).get("code") not in (None, "ok")):
        raise ClipAgentError(_tt_err(data, r.status_code))
    return data.get("data") or {}


def tt_callback(params: dict) -> str:
    pend = _take_state("tiktok", params)
    r = requests.post(f"{tt_api()}/v2/oauth/token/", timeout=30, data={
        "client_key": os.getenv("TIKTOK_CLIENT_KEY"), "client_secret": os.getenv("TIKTOK_CLIENT_SECRET"),
        "code": params.get("code", ""), "grant_type": "authorization_code", "redirect_uri": pend["redirect"],
        "code_verifier": pend["verifier"]})
    tok = r.json() if r.content else {}
    if not r.ok or not tok.get("access_token"):
        raise ClipAgentError(f"TikTok menolak login: {tok.get('error_description') or tok.get('error') or r.status_code}")
    item = {"id": tok["open_id"], "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token", ""),
            "expires": time.time() + int(tok.get("expires_in", 86400)) - 120,
            "refresh_expires": time.time() + int(tok.get("refresh_expires_in", 31536000)),
            "scope": tok.get("scope", "")}
    name, username, avatar = "", "", ""
    if "video.publish" in item["scope"]:
        try:
            ci = _tt_post("/v2/post/publish/creator_info/query/", item["access_token"], {})
            name, username, avatar = ci.get("creator_nickname", ""), ci.get("creator_username", ""), ci.get("creator_avatar_url", "")
        except ClipAgentError:
            pass
    if not name:
        try:
            u = requests.get(f"{tt_api()}/v2/user/info/", params={"fields": "open_id,avatar_url,display_name"},
                             headers={"Authorization": f"Bearer {item['access_token']}"}, timeout=30).json()
            user = (u.get("data") or {}).get("user") or {}
            name, avatar = user.get("display_name", ""), user.get("avatar_url", "")
        except (requests.RequestException, ValueError):
            pass
    item.update(name=name or "Akun TikTok", username=username, avatar=avatar)
    _upsert("tiktok", item)
    return item["name"]


def _tt_token(acct: dict) -> str:
    if acct.get("access_token") and acct.get("expires", 0) > time.time():
        return acct["access_token"]
    r = requests.post(f"{tt_api()}/v2/oauth/token/", timeout=30, data={
        "client_key": os.getenv("TIKTOK_CLIENT_KEY"), "client_secret": os.getenv("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": acct.get("refresh_token", "")})
    tok = r.json() if r.content else {}
    if not r.ok or not tok.get("access_token"):
        raise ClipAgentError(f"Izin TikTok untuk {acct.get('name')} kedaluwarsa. Tambahkan ulang akun ini di tab Posting.")
    upd = {"id": acct["id"], "access_token": tok["access_token"],
           "expires": time.time() + int(tok.get("expires_in", 86400)) - 120}
    if tok.get("refresh_token"):                       # TikTok bisa memberi refresh token baru
        upd["refresh_token"] = tok["refresh_token"]
        upd["refresh_expires"] = time.time() + int(tok.get("refresh_expires_in", 31536000))
    _upsert("tiktok", upd)
    return tok["access_token"]


def tiktok_creator(aid: str) -> dict:
    """Info kreator terbaru (nama, pilihan privasi, batas durasi). Wajib diambil tiap kali halaman posting dibuka."""
    acct = get_account("tiktok", aid)
    if "video.publish" not in acct.get("scope", ""):
        return {"direct": False, "nickname": acct.get("name", ""), "username": acct.get("username", "")}
    ci = _tt_post("/v2/post/publish/creator_info/query/", _tt_token(acct), {})
    if ci.get("creator_nickname") and ci["creator_nickname"] != acct.get("name"):
        _upsert("tiktok", {"id": acct["id"], "name": ci["creator_nickname"], "username": ci.get("creator_username", ""),
                           "avatar": ci.get("creator_avatar_url", "")})
    return {"direct": True, "nickname": ci.get("creator_nickname", ""), "username": ci.get("creator_username", ""),
            "avatar": ci.get("creator_avatar_url", ""), "privacy_options": ci.get("privacy_level_options") or [],
            "comment_disabled": bool(ci.get("comment_disabled")), "duet_disabled": bool(ci.get("duet_disabled")),
            "stitch_disabled": bool(ci.get("stitch_disabled")),
            "max_duration": int(ci.get("max_video_post_duration_sec") or 0)}


def _tt_chunks(size: int) -> tuple[int, int]:
    """Aturan TikTok: potongan 5–64 MB; file ≤ 64 MB boleh satu potongan; sisa digabung ke potongan terakhir."""
    if size <= 64 * 1024 * 1024:
        return size, 1
    chunk = 10 * 1024 * 1024
    return chunk, size // chunk


def tiktok_upload(path: Path, post: dict, target: dict, on_progress=None) -> dict:
    acct = get_account("tiktok", target.get("account"))
    token = _tt_token(acct)
    opts = target.get("opts") or {}
    scope = acct.get("scope", "")
    mode = opts.get("mode") or ("direct" if "video.publish" in scope else "inbox")
    size = path.stat().st_size
    chunk, count = _tt_chunks(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}
    if mode == "direct":
        ci = tiktok_creator(acct["id"])
        dur = probe(path)["duration"]
        if ci.get("max_duration") and dur > ci["max_duration"]:
            raise ClipAgentError(f"TikTok: video {dur:.0f} detik melebihi batas akun ini ({ci['max_duration']} detik).")
        privacy = opts.get("privacy")
        if privacy not in ci.get("privacy_options", []):
            raise ClipAgentError("TikTok: pilih privasi posting (pilihan harus sesuai pengaturan akun).")
        if opts.get("brand_content") and privacy == "SELF_ONLY":
            raise ClipAgentError("TikTok: konten bermerek (branded content) tidak boleh berprivasi 'Hanya saya'.")
        body = {"post_info": {"title": _caption(post, 2200), "privacy_level": privacy,
                              "disable_comment": ci["comment_disabled"] or not opts.get("allow_comment"),
                              "disable_duet": ci["duet_disabled"] or not opts.get("allow_duet"),
                              "disable_stitch": ci["stitch_disabled"] or not opts.get("allow_stitch"),
                              "brand_content_toggle": bool(opts.get("brand_content")),
                              "brand_organic_toggle": bool(opts.get("brand_organic")),
                              "is_aigc": bool(post.get("ai"))},
                "source_info": source}
        init = _tt_post("/v2/post/publish/video/init/", token, body)
    else:
        if "video.upload" not in scope:
            raise ClipAgentError("TikTok: akun ini belum memberi izin 'kirim ke draf' (video.upload).")
        init = _tt_post("/v2/post/publish/inbox/video/init/", token, {"source_info": source})
    pub_id, url = init.get("publish_id"), init.get("upload_url")
    if not pub_id or not url:
        raise ClipAgentError("TikTok tidak memberi alamat upload.")
    with path.open("rb") as fh:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            n = end - start + 1
            r = requests.put(url, data=_Reader(fh, n, on_progress, base=start, total=size), timeout=3600,
                             headers={"Content-Type": "video/mp4", "Content-Length": str(n),
                                      "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code not in (200, 201, 206):
                raise ClipAgentError(f"TikTok: upload potongan {i + 1}/{count} gagal (HTTP {r.status_code}).")
    wait = float(os.getenv("TT_POLL_SECONDS") or 5)
    for _ in range(int(900 / max(wait, 0.1))):         # tunggu TikTok selesai memproses (maks. 15 menit)
        st = _tt_post("/v2/post/publish/status/fetch/", _tt_token(get_account("tiktok", acct["id"])), {"publish_id": pub_id})
        s = st.get("status")
        if s == "FAILED":
            reason = st.get("fail_reason", "")
            raise ClipAgentError(f"TikTok gagal memproses video: {TT_FAIL.get(reason, reason or 'tidak diketahui')}.")
        if s == "SEND_TO_USER_INBOX":
            return {"id": pub_id, "url": "", "note": "Terkirim ke draf TikTok. Buka notifikasi di aplikasi TikTok untuk "
                                                     "mengedit dan memposting."}
        if s == "PUBLISH_COMPLETE":
            ids = st.get("publicaly_available_post_id") or []
            user = acct.get("username")
            link = (f"https://www.tiktok.com/@{user}/video/{ids[0]}" if ids and user
                    else f"https://www.tiktok.com/@{user}" if user else "")
            note = "" if ids else ("Terbit. Tautan publik muncul setelah TikTok selesai meninjau, atau tidak ada bila "
                                   "privasinya 'Hanya saya'.")
            return {"id": str(ids[0]) if ids else pub_id, "url": link, "note": note}
        time.sleep(wait)
    return {"id": pub_id, "url": "", "note": "TikTok masih memproses. Cek profil TikTok beberapa menit lagi."}


UPLOADERS = {"youtube": youtube_upload, "facebook": facebook_upload, "instagram": instagram_upload,
             "tiktok": tiktok_upload}
NATIVE_SCHEDULE = ("youtube", "facebook")              # dijadwalkan oleh platformnya; sisanya oleh Clip Agent


# ---------------------------------------------------------------- antrean posting
def _clean_tiktok_opts(raw: dict | None) -> dict:
    raw = raw or {}
    return {"mode": raw.get("mode") if raw.get("mode") in ("direct", "inbox") else "",
            "privacy": raw.get("privacy") if raw.get("privacy") in ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS",
                                                                    "FOLLOWER_OF_CREATOR", "SELF_ONLY") else "",
            "allow_comment": bool(raw.get("allow_comment")), "allow_duet": bool(raw.get("allow_duet")),
            "allow_stitch": bool(raw.get("allow_stitch")), "brand_organic": bool(raw.get("brand_organic")),
            "brand_content": bool(raw.get("brand_content")), "consent": bool(raw.get("consent"))}


class PostQueue:
    """Antrean posting yang tersimpan di <output>/_posts.json dan dijalankan oleh satu thread."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.path = out_dir / "_posts.json"
        self.wake = threading.Event()
        self.lock = threading.RLock()
        self._items = self._read()
        for p in self._items:                               # posting yang terputus saat aplikasi ditutup
            for t in p["targets"].values():
                if t["status"] == "running":
                    t.update(status="error", error="Terputus karena aplikasi ditutup. Klik Coba lagi.")
        if self._items:
            self._save()
        threading.Thread(target=self._loop, daemon=True).start()

    def _read(self) -> list[dict]:
        if self.path.is_file():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return []

    def _save(self) -> None:
        with self.lock:
            self.path.write_text(json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self) -> list[dict]:
        with self.lock:
            return json.loads(json.dumps(self._items[::-1][:100]))

    def add(self, data: dict) -> dict:
        rel = str(data.get("file") or "")
        path = (self.out_dir / rel).resolve()
        try:
            path.relative_to(self.out_dir.resolve())
        except ValueError:
            raise ClipAgentError("File tidak valid.")
        if not path.is_file() or path.suffix.lower() != ".mp4":
            raise ClipAgentError("Video tidak ditemukan.")
        keys = [str(k) for k in data.get("accounts") or []]
        if not keys and data.get("platforms"):              # formulir lama: akun pertama tiap platform
            acc = load_accounts()
            keys = [f"{p}:{acc[p][0]['id']}" for p in data["platforms"] if p in PLATFORMS and acc[p]]
        if not keys:
            raise ClipAgentError("Pilih minimal satu akun tujuan.")
        sch = int(data.get("schedule") or 0)
        if sch and sch < time.time() - 60:
            raise ClipAgentError("Waktu jadwal sudah lewat.")
        tt_opts = data.get("tiktok") or {}
        targets = {}
        for key in dict.fromkeys(keys):
            plat, _, aid = key.partition(":")
            if plat not in PLATFORMS:
                raise ClipAgentError("Platform tidak dikenal.")
            acct = get_account(plat, aid)
            t = {"platform": plat, "account": aid, "label": f"{LABELS[plat]}: {acct.get('name') or aid}",
                 "status": "queued", "due": time.time() if (not sch or plat in NATIVE_SCHEDULE) else sch,
                 "error": "", "url": "", "note": "", "progress": 0.0}
            if plat == "tiktok":
                o = _clean_tiktok_opts(tt_opts.get(aid))
                if not o["consent"]:
                    raise ClipAgentError(f"TikTok {acct.get('name')}: centang persetujuan sebelum posting.")
                mode = o["mode"] or ("direct" if "video.publish" in acct.get("scope", "") else "inbox")
                if mode == "direct" and not o["privacy"]:
                    raise ClipAgentError(f"TikTok {acct.get('name')}: pilih siapa yang bisa menonton.")
                if o["brand_content"] and o["privacy"] == "SELF_ONLY":
                    raise ClipAgentError(f"TikTok {acct.get('name')}: konten bermerek tidak boleh 'Hanya saya'.")
                o["mode"] = mode
                t["opts"] = o
            targets[key] = t
        tags = [str(t).strip().lstrip("#") for t in (data.get("hashtags") or []) if str(t).strip()][:15]
        post = {"id": uuid.uuid4().hex[:10], "file": rel, "name": path.name, "created": time.time(),
                "title": str(data.get("title") or "")[:100], "description": str(data.get("description") or "")[:4800],
                "hashtags": tags, "privacy": data.get("privacy") if data.get("privacy") in ("public", "unlisted", "private") else "public",
                "ai": bool(data.get("ai")), "schedule": sch, "targets": targets}
        with self.lock:
            self._items.append(post)
            self._save()
        self.wake.set()
        return post

    def cancel(self, pid: str) -> None:
        with self.lock:
            for p in self._items:
                if p["id"] == pid:
                    for t in p["targets"].values():
                        if t["status"] == "queued":
                            t["status"] = "canceled"
            self._save()

    def retry(self, pid: str) -> None:
        with self.lock:
            for p in self._items:
                if p["id"] == pid:
                    for t in p["targets"].values():
                        if t["status"] in ("error", "canceled"):
                            t.update(status="queued", error="", due=time.time(), progress=0.0)
            self._save()
        self.wake.set()

    def remove(self, pid: str) -> None:
        with self.lock:
            self._items = [p for p in self._items if not (p["id"] == pid and not any(
                t["status"] == "running" for t in p["targets"].values()))]
            self._save()

    def _next(self):
        with self.lock:
            now = time.time()
            for p in self._items:
                for key, t in p["targets"].items():
                    if t["status"] == "queued" and t["due"] <= now:
                        t["status"] = "running"
                        self._save()
                        return p, key
        return None

    def _loop(self) -> None:
        while True:
            job = self._next()
            if not job:
                self.wake.wait(15)
                self.wake.clear()
                continue
            post, key = job
            target = post["targets"][key]
            plat = target.get("platform") or key.split(":")[0]          # posting format lama: kunci = platform

            def prog(f, post=post, key=key):
                with self.lock:
                    post["targets"][key]["progress"] = round(min(1.0, f), 3)

            try:
                res = UPLOADERS[plat](self.out_dir / post["file"], post, target, prog)
                upd = {"status": "done", "url": res.get("url", ""), "remote_id": res.get("id", ""),
                       "scheduled": res.get("scheduled", ""), "note": res.get("note", ""), "progress": 1.0,
                       "finished": time.time()}
            except ClipAgentError as exc:
                upd = {"status": "error", "error": str(exc)}
            except requests.RequestException as exc:
                upd = {"status": "error", "error": f"Koneksi gagal ({type(exc).__name__}). Klik Coba lagi."}
            except Exception as exc:                        # bug tak terduga
                traceback.print_exc()
                upd = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            with self.lock:
                post["targets"][key].update(upd)
                self._save()
