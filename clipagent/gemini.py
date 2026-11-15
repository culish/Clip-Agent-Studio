"""Klien kecil untuk Gemini Interactions API (POST /v1beta/interactions).

Dipakai untuk suara narasi (model TTS) dan video AI (Gemini Omni Flash). Kunci API memakai
GEMINI_API_KEY (atau IMAGE_API_KEY); alamat dasar bisa diganti lewat GEMINI_BASE_URL.
"""
from __future__ import annotations

import base64
import os
import time

import requests

from .utils import ClipAgentError, check_cancel, log

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


def api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("IMAGE_API_KEY") or ""


def base_url() -> str:
    return (os.getenv("GEMINI_BASE_URL") or DEFAULT_BASE).rstrip("/")


def interact(body: dict, timeout: int = 300, tries: int = 3) -> dict:
    """Kirim satu permintaan Interactions API dengan coba ulang untuk 429/5xx."""
    key = api_key()
    if not key:
        raise ClipAgentError("Butuh GEMINI_API_KEY (isi di tab Pengaturan).")
    url = f"{base_url()}/interactions"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    last = ""
    for attempt in range(tries):
        check_cancel()
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as exc:
            last = f"koneksi gagal ({type(exc).__name__})"
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code} (sibuk/kuota)"
            log(f"  Gemini {body.get('model')}: {last}, mencoba lagi...")
            time.sleep(6 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise ModelMissing(f"Model {body.get('model')} tidak ditemukan.")
        if not r.ok:
            raise ClipAgentError(f"Gemini menolak permintaan (HTTP {r.status_code}): {r.text[:240]}")
        return r.json()
    raise ClipAgentError(f"Gemini tidak tersedia: {last}")


class ModelMissing(ClipAgentError):
    pass


def output_blob(resp: dict, kind: str) -> dict | None:
    """Ambil konten keluaran terakhir bertipe `kind` ('audio' / 'video' / 'image') dari respons."""
    found = None
    for step in resp.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == kind and (item.get("data") or item.get("uri")):
                found = item
    return found


def blob_bytes(item: dict) -> bytes:
    if item.get("data"):
        return base64.b64decode(item["data"])
    uri = item["uri"]
    sep = "&" if "?" in uri else "?"
    for _ in range(60):                                    # file mungkin masih diproses
        check_cancel()
        r = requests.get(f"{uri}{sep}key={api_key()}", timeout=300)
        if r.ok and r.content:
            return r.content
        time.sleep(5)
    raise ClipAgentError("Gagal mengunduh hasil dari Gemini.")


def with_fallbacks(models: list[str], make_body, kind: str, timeout: int = 300) -> tuple[bytes, dict, str]:
    """Coba model satu per satu (model hilang/usang dilewati). Mengembalikan (bytes, item, model)."""
    err: Exception | None = None
    for m in [x for i, x in enumerate(models) if x and x not in models[:i]]:
        try:
            resp = interact(make_body(m), timeout=timeout)
        except ModelMissing as exc:
            err = exc
            continue
        item = output_blob(resp, kind)
        if not item:
            raise ClipAgentError(f"Gemini tidak mengembalikan {kind} (mungkin ditolak filter keamanan).")
        return blob_bytes(item), item, m
    raise ClipAgentError(str(err or "Tidak ada model yang bisa dipakai."))
