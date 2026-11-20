"""Klien LLM minimal: API kompatibel-OpenAI (Gemini, OpenRouter, Ollama, Groq, OpenAI) dan Anthropic.

Tahan gangguan: model sibuk (503) atau kena batas (429) dicoba ulang dengan jeda,
lalu otomatis pindah ke model cadangan.
"""
from __future__ import annotations

import json
import time

import requests

from .utils import ClipAgentError, extract_json, log


class LLMUnavailable(ClipAgentError):
    """Semua model sedang tidak tersedia (sibuk/kuota habis/jaringan). Bisa dicoba lagi nanti."""


class _Retryable(Exception):
    def __init__(self, msg: str, wait: float | None = None):
        super().__init__(msg)
        self.wait = wait


class _SkipModel(Exception):
    """Model ini tidak bisa dipakai (tidak ada / tidak didukung); lanjut ke model berikutnya."""


class LLMClient:
    def __init__(self, provider: str, model: str, base_url: str, api_key: str,
                 fallbacks: list[str] | None = None, timeout: int = 240):
        self.provider, self.base_url, self.api_key = provider, base_url, api_key
        self.models = [model] + [m for m in (fallbacks or []) if m and m != model]
        self.timeout = timeout
        if not model:
            raise ClipAgentError(
                f"Model untuk provider '{provider}' belum diisi. Set LLM_MODEL di file .env "
                "atau pakai --model."
            )
        if provider not in ("ollama",) and not api_key:
            raise ClipAgentError(
                f"API key untuk provider '{provider}' belum diisi. Isi di file .env "
                "(lihat .env.example), atau pakai --provider heuristic untuk mode tanpa AI."
            )

    @property
    def model(self) -> str:
        return self.models[0]

    def complete_json(self, system: str, user: str, attempts_per_model: int = 3, list_key: str = "") -> dict:
        """Jawaban JSON berupa objek. Bila model menjawab dengan daftar saja (mis. langsung [ {...}, ... ]),
        daftar itu dibungkus menjadi {list_key: [...]}; bentuk lain diminta ulang."""
        problems = []
        for mi, model in enumerate(list(self.models)):
            for attempt in range(1, attempts_per_model + 1):
                try:
                    text = (self._anthropic(model, system, user) if self.provider == "anthropic"
                            else self._openai(model, system, user))
                    result = _as_object(extract_json(text), list_key)
                    if mi > 0:
                        # Model cadangan berhasil: pakai model ini untuk permintaan berikutnya.
                        self.models = self.models[mi:] + self.models[:mi]
                    return result
                except _SkipModel as exc:
                    log(f"Model {model} tidak bisa dipakai ({exc}).")
                    problems.append(f"{model}: {exc}")
                    break
                except _Retryable as exc:
                    if attempt == attempts_per_model:
                        log(f"Model {model} masih tidak tersedia ({exc}).")
                        problems.append(f"{model}: {exc}")
                        break
                    wait = min(60.0, exc.wait if exc.wait else 5.0 * 3 ** (attempt - 1))
                    log(f"Model {model} {exc}; coba lagi dalam {wait:.0f} dtk "
                        f"(percobaan {attempt + 1}/{attempts_per_model})...")
                    time.sleep(wait)
                except ClipAgentError as exc:
                    if "bukan JSON" in str(exc) and attempt < attempts_per_model:
                        log(f"Jawaban {model} bukan JSON valid; meminta ulang...")
                        continue
                    raise
            if mi + 1 < len(self.models):
                log(f"Beralih ke model cadangan: {self.models[mi + 1]}")
        raise LLMUnavailable("Semua model LLM sedang tidak tersedia:\n  - " + "\n  - ".join(problems[-4:]))

    def complete_text(self, system: str, user: str, attempts_per_model: int = 3) -> str:
        """Jawaban teks bebas (Markdown), dengan coba ulang dan model cadangan seperti complete_json."""
        problems = []
        self._json_mode = False
        try:
            return self._complete_text(system, user, attempts_per_model, problems)
        finally:
            self._json_mode = True

    def _complete_text(self, system: str, user: str, attempts_per_model: int, problems: list) -> str:
        for mi, model in enumerate(list(self.models)):
            for attempt in range(1, attempts_per_model + 1):
                try:
                    text = (self._anthropic(model, system, user) if self.provider == "anthropic"
                            else self._openai(model, system, user))
                    if not (text or "").strip():
                        raise _Retryable("jawaban kosong")
                    if mi > 0:
                        self.models = self.models[mi:] + self.models[:mi]
                    return text.strip()
                except _SkipModel as exc:
                    log(f"Model {model} tidak bisa dipakai ({exc}).")
                    problems.append(f"{model}: {exc}")
                    break
                except _Retryable as exc:
                    if attempt == attempts_per_model:
                        log(f"Model {model} masih tidak tersedia ({exc}).")
                        problems.append(f"{model}: {exc}")
                        break
                    wait = min(60.0, exc.wait if exc.wait else 5.0 * 3 ** (attempt - 1))
                    log(f"Model {model} {exc}; coba lagi dalam {wait:.0f} dtk "
                        f"(percobaan {attempt + 1}/{attempts_per_model})...")
                    time.sleep(wait)
            if mi + 1 < len(self.models):
                log(f"Beralih ke model cadangan: {self.models[mi + 1]}")
        raise LLMUnavailable("Semua model LLM sedang tidak tersedia:\n  - " + "\n  - ".join(problems[-4:]))

    # ------------------------------------------------------------------ HTTP
    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.Timeout as exc:
            raise _Retryable("waktu habis menunggu jawaban") from exc
        except requests.ConnectionError as exc:
            raise _Retryable(f"gagal terhubung ({type(exc).__name__})") from exc
        if r.ok:
            return r.json()
        msg = _error_message(r)
        if r.status_code in (429, 500, 502, 503, 504, 529):
            label = {429: "kena batas kuota/permintaan", 503: "sedang sibuk",
                     529: "sedang sibuk"}.get(r.status_code, "error server")
            raise _Retryable(f"{label} (HTTP {r.status_code})", _retry_after(r))
        if r.status_code in (401, 403):
            raise ClipAgentError(f"API key ditolak oleh {self.provider} (HTTP {r.status_code}): {msg}")
        if r.status_code == 404 or "not found" in msg.lower() or "not supported" in msg.lower():
            raise _SkipModel(f"HTTP {r.status_code}: {msg[:160]}")
        raise ClipAgentError(f"HTTP {r.status_code} dari {self.provider}: {msg[:400]}")

    def _openai(self, model: str, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.provider == "openrouter":
            headers["X-Title"] = "YT Clip Agent"
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if getattr(self, "_json_mode", True):
            payload["response_format"] = {"type": "json_object"}
        url = f"{self.base_url}/chat/completions"
        try:
            data = self._post(url, headers, payload)
        except (ClipAgentError, _SkipModel) as exc:
            # Sebagian model tidak mendukung response_format; ulangi tanpa itu.
            if "response_format" in payload and ("response_format" in str(exc) or "json_object" in str(exc).lower()):
                payload.pop("response_format")
                data = self._post(url, headers, payload)
            else:
                raise
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ClipAgentError(f"Format jawaban tak terduga: {str(data)[:300]}") from exc

    def _anthropic(self, model: str, system: str, user: str) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 8000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._post(f"{self.base_url}/messages", headers, payload)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _error_message(r: requests.Response) -> str:
    """Ambil pesan error yang ringkas dari berbagai format (OpenAI, Gemini, Anthropic)."""
    try:
        data = r.json()
    except ValueError:
        return r.text.strip()[:300]
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message") or err.get("status") or json.dumps(err))[:300]
        return str(err)[:300]
    return str(data)[:300]


def _retry_after(r: requests.Response) -> float | None:
    try:
        return float(r.headers.get("retry-after", ""))
    except ValueError:
        return None


def _as_object(result, list_key: str = "") -> dict:
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        if len(result) == 1 and isinstance(result[0], dict) and (not list_key or list_key in result[0]):
            return result[0]
        if list_key:
            return {list_key: result}
    raise ClipAgentError("Jawaban LLM bukan JSON yang valid (bukan objek): " + str(result)[:300])
