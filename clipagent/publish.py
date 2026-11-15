"""Posting otomatis ke YouTube, Facebook Page (Reels), dan Instagram (Reels).

- YouTube: OAuth 2.0 untuk aplikasi desktop (redirect loopback ke Clip Agent), upload resumable lewat
  YouTube Data API v3. Bisa dijadwalkan dengan publishAt (YouTube yang menayangkan, laptop boleh mati).
- Facebook: Reels Publishing API (upload ke rupload.facebook.com). Jadwal native 10 menit–29 hari.
- Instagram: Content Publishing API, unggah resumable lalu media_publish. Jadwal dijalankan oleh
  Clip Agent sendiri (aplikasi harus menyala pada waktunya).
Token disimpan di data/accounts.json di folder aplikasi (jangan dibagikan).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
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
YT_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
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


# ---------------------------------------------------------------- akun
def load_accounts() -> dict:
    with _LOCK:
        if ACCOUNTS.is_file():
            try:
                return json.loads(ACCOUNTS.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return {}


def save_accounts(data: dict) -> None:
    with _LOCK:
        DATA_DIR.mkdir(exist_ok=True)
        ACCOUNTS.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(ACCOUNTS, 0o600)
        except OSError:
            pass


def status() -> dict:
    acc = load_accounts()
    yt = acc.get("youtube") or {}
    meta = acc.get("meta") or {}
    page = next((p for p in meta.get("pages", []) if p["id"] == meta.get("page_id")), None)
    return {
        "youtube": {"ready_client": bool(os.getenv("YT_CLIENT_ID") and os.getenv("YT_CLIENT_SECRET")),
                    "connected": bool(yt.get("refresh_token")), "channel": yt.get("channel_title", ""),
                    "channel_id": yt.get("channel_id", "")},
        "meta": {"connected": bool(page), "pages": [{"id": p["id"], "name": p["name"],
                                                    "instagram": (p.get("ig") or {}).get("username", "")}
                                                   for p in meta.get("pages", [])],
                 "page_id": meta.get("page_id", ""), "page": page["name"] if page else "",
                 "instagram": ((page or {}).get("ig") or {}).get("username", "")},
    }


def disconnect(platform: str) -> None:
    acc = load_accounts()
    acc.pop("youtube" if platform == "youtube" else "meta", None)
    save_accounts(acc)


# ---------------------------------------------------------------- YouTube OAuth
def yt_auth_url(redirect_uri: str) -> str:
    cid = os.getenv("YT_CLIENT_ID")
    if not cid or not os.getenv("YT_CLIENT_SECRET"):
        raise ClipAgentError("Isi YouTube OAuth Client ID dan Client Secret dulu.")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    _PENDING[state] = {"verifier": verifier, "redirect": redirect_uri, "t": time.time()}
    q = {"client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "scope": YT_SCOPES,
         "access_type": "offline", "prompt": "consent", "state": state, "code_challenge": challenge,
         "code_challenge_method": "S256"}
    return f"{g_auth()}?{urlencode(q)}"


def yt_callback(params: dict) -> str:
    state = params.get("state", "")
    pend = _PENDING.pop(state, None)
    if not pend:
        raise ClipAgentError("Sesi login kedaluwarsa. Ulangi 'Hubungkan YouTube'.")
    if params.get("error"):
        raise ClipAgentError(f"Login dibatalkan: {params['error']}")
    r = requests.post(g_token(), data={
        "code": params.get("code", ""), "client_id": os.getenv("YT_CLIENT_ID"),
        "client_secret": os.getenv("YT_CLIENT_SECRET"), "redirect_uri": pend["redirect"],
        "grant_type": "authorization_code", "code_verifier": pend["verifier"]}, timeout=30)
    if not r.ok:
        raise ClipAgentError(f"Gagal menukar kode login (HTTP {r.status_code}): {r.text[:200]}")
    tok = r.json()
    acc = load_accounts()
    yt = {"refresh_token": tok.get("refresh_token") or (acc.get("youtube") or {}).get("refresh_token", ""),
          "access_token": tok["access_token"], "expires": time.time() + int(tok.get("expires_in", 3600)) - 60}
    acc["youtube"] = yt
    save_accounts(acc)
    try:
        ch = requests.get(f"{yt_api()}/channels", params={"part": "snippet", "mine": "true"},
                          headers={"Authorization": f"Bearer {yt['access_token']}"}, timeout=30).json()
        item = (ch.get("items") or [{}])[0]
        yt["channel_title"] = (item.get("snippet") or {}).get("title", "")
        yt["channel_id"] = item.get("id", "")
        acc["youtube"] = yt
        save_accounts(acc)
    except (requests.RequestException, ValueError):
        pass
    return yt.get("channel_title") or "YouTube"


def _yt_token() -> str:
    acc = load_accounts()
    yt = acc.get("youtube") or {}
    if not yt.get("refresh_token"):
        raise ClipAgentError("YouTube belum dihubungkan (tab Posting).")
    if yt.get("access_token") and yt.get("expires", 0) > time.time():
        return yt["access_token"]
    r = requests.post(g_token(), data={"client_id": os.getenv("YT_CLIENT_ID"), "client_secret": os.getenv("YT_CLIENT_SECRET"),
                                       "refresh_token": yt["refresh_token"], "grant_type": "refresh_token"}, timeout=30)
    if not r.ok:
        raise ClipAgentError("Izin YouTube kedaluwarsa atau dicabut. Hubungkan ulang YouTube di tab Posting. "
                             "(Bila aplikasi OAuth masih berstatus 'Testing', izin berlaku 7 hari.)")
    tok = r.json()
    yt["access_token"] = tok["access_token"]
    yt["expires"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    acc["youtube"] = yt
    save_accounts(acc)
    return yt["access_token"]


def youtube_upload(path: Path, post: dict, on_progress=None) -> dict:
    token = _yt_token()
    info = probe(path)
    is_short = info["height"] > info["width"] and info["duration"] <= 180
    desc = post.get("description", "")
    tags = [t.lstrip("#") for t in post.get("hashtags", [])]
    if tags:
        desc = (desc + "\n\n" + " ".join("#" + t for t in tags[:8])).strip()
    status = {"privacyStatus": post.get("privacy") or "public", "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(post.get("ai"))}
    if post.get("schedule") and post["schedule"] > time.time() + 15 * 60:
        status["privacyStatus"] = "private"
        status["publishAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(post["schedule"]))
    meta = {"snippet": {"title": (post.get("title") or path.stem)[:100].replace("<", "").replace(">", ""),
                        "description": desc.replace("<", "").replace(">", "")[:4900], "tags": tags[:15],
                        "categoryId": str(post.get("category") or "22")},
            "status": status}
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
    return {"id": vid, "url": url, "scheduled": status.get("publishAt", "")}


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

    def __init__(self, fh, size, cb):
        self.fh, self.size, self.cb, self.done = fh, size, cb, 0

    def __len__(self):
        return self.size

    def read(self, n=-1):
        chunk = self.fh.read(1 << 20 if n is None or n < 0 else n)
        self.done += len(chunk)
        if self.cb:
            self.cb(self.done / max(1, self.size))
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
        "limit": 50}, timeout=30)
    if not r.ok:
        raise ClipAgentError(_meta_error(r))
    pages = []
    for p in r.json().get("data") or []:
        ig = p.get("instagram_business_account") or None
        pages.append({"id": p["id"], "name": p.get("name", ""), "access_token": p.get("access_token", ""),
                      "ig": {"id": ig["id"], "username": ig.get("username", "")} if ig else None})
    if not pages:
        raise ClipAgentError("Token valid, tetapi tidak ada Facebook Page. Pastikan izin pages_show_list dan "
                             "Page dipilih saat membuat token.")
    acc = load_accounts()
    acc["meta"] = {"pages": pages, "page_id": pages[0]["id"], "connected": time.time()}
    save_accounts(acc)
    return status()["meta"]


def meta_select(page_id: str) -> dict:
    acc = load_accounts()
    meta = acc.get("meta") or {}
    if not any(p["id"] == page_id for p in meta.get("pages", [])):
        raise ClipAgentError("Page tidak ditemukan.")
    meta["page_id"] = page_id
    acc["meta"] = meta
    save_accounts(acc)
    return status()["meta"]


def _page() -> dict:
    meta = load_accounts().get("meta") or {}
    page = next((p for p in meta.get("pages", []) if p["id"] == meta.get("page_id")), None)
    if not page:
        raise ClipAgentError("Facebook/Instagram belum dihubungkan (tab Posting).")
    return page


def _meta_error(r: requests.Response) -> str:
    try:
        err = r.json().get("error", {})
    except ValueError:
        return f"Meta: HTTP {r.status_code}"
    if err.get("code") == 190:
        return "Meta: token kedaluwarsa atau tidak valid. Hubungkan ulang di tab Posting."
    if err.get("code") in (10, 200):
        return f"Meta: izin kurang ({err.get('message', '')[:160]})."
    return f"Meta: {err.get('message') or f'HTTP {r.status_code}'}"


def _caption(post: dict) -> str:
    tags = " ".join("#" + t.lstrip("#") for t in post.get("hashtags", [])[:10])
    return (post.get("description", "") + ("\n\n" + tags if tags else "")).strip()[:2150]


def facebook_upload(path: Path, post: dict, on_progress=None) -> dict:
    page = _page()
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


def instagram_upload(path: Path, post: dict, on_progress=None) -> dict:
    page = _page()
    ig = page.get("ig")
    if not ig:
        raise ClipAgentError("Page ini belum terhubung ke akun Instagram profesional (Business/Creator).")
    tok = page["access_token"]
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
    return {"id": mid, "url": link or f"https://www.instagram.com/{ig.get('username', '')}"}


UPLOADERS = {"youtube": youtube_upload, "facebook": facebook_upload, "instagram": instagram_upload}
LABELS = {"youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram"}


# ---------------------------------------------------------------- antrean posting
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

    def _load(self) -> list[dict]:
        return self._items

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
        plats = [p for p in data.get("platforms") or [] if p in UPLOADERS]
        if not plats:
            raise ClipAgentError("Pilih minimal satu platform.")
        st = status()
        for p in plats:
            if p == "youtube" and not st["youtube"]["connected"]:
                raise ClipAgentError("YouTube belum dihubungkan.")
            if p in ("facebook", "instagram") and not st["meta"]["connected"]:
                raise ClipAgentError("Facebook/Instagram belum dihubungkan.")
            if p == "instagram" and not st["meta"]["instagram"]:
                raise ClipAgentError("Page yang dipilih belum terhubung ke akun Instagram profesional.")
        sch = int(data.get("schedule") or 0)
        if sch and sch < time.time() - 60:
            raise ClipAgentError("Waktu jadwal sudah lewat.")
        tags = [str(t).strip().lstrip("#") for t in (data.get("hashtags") or []) if str(t).strip()][:15]
        post = {"id": uuid.uuid4().hex[:10], "file": rel, "name": path.name, "created": time.time(),
                "title": str(data.get("title") or "")[:100], "description": str(data.get("description") or "")[:4800],
                "hashtags": tags, "privacy": data.get("privacy") if data.get("privacy") in ("public", "unlisted", "private") else "public",
                "ai": bool(data.get("ai")), "schedule": sch, "targets": {}}
        for p in plats:
            native = p in ("youtube", "facebook")              # dijadwalkan oleh platformnya sendiri
            due = time.time() if (not sch or native) else sch
            post["targets"][p] = {"status": "queued", "due": due, "error": "", "url": "", "progress": 0.0}
        with self.lock:
            self._items.append(post)
            self._save()
        self.wake.set()
        return post

    def cancel(self, pid: str) -> None:
        with self.lock:
            for p in self._load():
                if p["id"] == pid:
                    for t in p["targets"].values():
                        if t["status"] == "queued":
                            t["status"] = "canceled"
            self._save()

    def retry(self, pid: str) -> None:
        with self.lock:
            for p in self._load():
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
            for p in self._load():
                for name, t in p["targets"].items():
                    if t["status"] == "queued" and t["due"] <= now:
                        t["status"] = "running"
                        self._save()
                        return p, name
        return None

    def _loop(self) -> None:
        while True:
            job = self._next()
            if not job:
                self.wake.wait(15)
                self.wake.clear()
                continue
            post, name = job

            def prog(f, post=post, name=name):
                with self.lock:
                    post["targets"][name]["progress"] = round(f, 3)

            try:
                res = UPLOADERS[name](self.out_dir / post["file"], post, prog)
                upd = {"status": "done", "url": res.get("url", ""), "remote_id": res.get("id", ""),
                       "scheduled": res.get("scheduled", ""), "progress": 1.0, "finished": time.time()}
            except ClipAgentError as exc:
                upd = {"status": "error", "error": str(exc)}
            except requests.RequestException as exc:
                upd = {"status": "error", "error": f"Koneksi gagal ({type(exc).__name__}). Klik Coba lagi."}
            except Exception as exc:                        # bug tak terduga
                traceback.print_exc()
                upd = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            with self.lock:
                for p in self._load():
                    if p["id"] == post["id"]:
                        p["targets"][name].update(upd)
                self._save()
