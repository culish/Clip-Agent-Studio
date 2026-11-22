"""Agen coding di komputer pengguna sebagai penulis AI: Claude Code dan alternatifnya.

Semua dijalankan tanpa pengawasan lewat CLI masing-masing dan memakai login/langganan pengguna sendiri:
- Claude Code (`claude`)          langganan Claude atau API key
- Codex CLI (`codex`)             langganan ChatGPT atau API key OpenAI
- Gemini CLI (`gemini`)           gratis dengan akun Google (ada batas harian)
- Qwen Code (`qwen`)              akun Qwen atau API key yang didukung
- opencode (`opencode`)           model pilihan sendiri, termasuk model gratis

Dua cara pakai:
- text(): satu jawaban teks tanpa alat (naskah reels, kode Motion AI). Dijalankan di folder sementara yang kosong.
- agentic_cmd() + parse_event(): agen penuh untuk tab Film (membaca panduan, menjalankan perintah, merender).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .utils import ClipAgentError

AGENTS = {
    "claude": {"name": "Claude Code", "plan": "langganan Claude (Pro/Max) atau API key Anthropic",
               "install": "npm i -g @anthropic-ai/claude-code", "login": "claude", "film": True},
    "codex": {"name": "Codex CLI (OpenAI)", "plan": "langganan ChatGPT (Plus/Pro) atau API key OpenAI",
              "install": "npm i -g @openai/codex", "login": "codex login", "film": True},
    "gemini": {"name": "Gemini CLI (Google)", "plan": "gratis dengan akun Google, ada batas harian",
               "install": "npm i -g @google/gemini-cli", "login": "gemini (pilih Login with Google)", "film": True},
    "qwen": {"name": "Qwen Code", "plan": "akun Qwen atau API key yang didukung",
             "install": "npm i -g @qwen-code/qwen-code", "login": "qwen", "film": True},
    "opencode": {"name": "opencode", "plan": "model pilihan Anda, termasuk model gratis",
                 "install": "npm i -g opencode-ai", "login": "opencode auth login", "film": False},
}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _settings() -> dict:
    from . import film
    return film.get_settings()


def find(name: str) -> str | None:
    """Lokasi CLI agen (pengaturan film > PATH > lokasi pasang umum)."""
    if name not in AGENTS:
        return None
    st = _settings()
    custom = (st.get("bins") or {}).get(name) or (st.get("claude") if name == "claude" else "")
    if custom:
        p = os.path.expanduser(custom)
        return p if Path(p).is_file() else shutil.which(p)
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    cands = [home / ".local" / "bin" / name, Path(os.getenv("APPDATA", "")) / "npm" / f"{name}.cmd",
             home / ".npm-global" / "bin" / name]
    if name == "claude":
        cands.append(home / ".claude" / "local" / "claude")
    if name == "opencode":
        cands += [home / ".opencode" / "bin" / "opencode", home / ".opencode" / "bin" / "opencode.exe"]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def available() -> dict[str, str]:
    return {k: p for k in AGENTS if (p := find(k))}


def public() -> dict:
    av = available()
    return {k: {**v, "found": k in av} for k, v in AGENTS.items()}


def launch(exe: str) -> list:
    """Windows tidak bisa menjalankan .cmd/.bat langsung tanpa cmd.exe."""
    return ["cmd", "/c", exe] if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")) else [exe]


def _run(cmd: list, stdin: str, cwd: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=cwd, env={**os.environ, "NO_COLOR": "1"})


def _unknown_flag(r: subprocess.CompletedProcess, flag: str) -> bool:
    err = ((r.stderr or "") + (r.stdout or "")).lower()
    return r.returncode != 0 and flag.lower() in err and any(w in err for w in ("unknown", "unexpected", "unrecognized",
                                                                              "not a valid", "invalid"))


def _fail(name: str, r: subprocess.CompletedProcess, extra: str = "") -> ClipAgentError:
    msg = ANSI.sub("", (extra or r.stderr or r.stdout or "").strip())[-500:] or f"kode keluar {r.returncode}"
    low = msg.lower()
    if any(w in low for w in ("login", "auth", "credential", "api key", "unauthorized", "not logged")):
        msg += f" (login dulu: jalankan `{AGENTS[name]['login']}` sekali di terminal)"
    elif any(w in low for w in ("quota", "rate limit", "429", "usage limit", "exhausted")):
        msg += " (kuota/batas pemakaian habis; coba lagi nanti atau pilih penulis lain)"
    return ClipAgentError(f"{AGENTS[name]['name']} gagal: {msg}")


def text(name: str, system: str, prompt: str, *, timeout: int = 900, model: str = "") -> str:
    """Satu jawaban teks tanpa alat apa pun. Aturan lengkap dikirim lewat stdin atau file, bukan argumen
    (argumen panjang berisi < > & " rusak lewat cmd.exe di Windows)."""
    exe = find(name)
    if not exe:
        a = AGENTS.get(name) or {"name": name, "install": ""}
        raise ClipAgentError(f"{a['name']} tidak ditemukan di komputer ini. Pasang dengan `{a['install']}` lalu login.")
    full = f"{system}\n\n=== TASK ===\n{prompt}"
    short = "Follow the instructions you were given exactly and answer with one JSON object only, without commentary."
    with tempfile.TemporaryDirectory(prefix="clipagent-ai-") as tmp:
        try:
            if name == "claude":
                cmd = launch(exe) + ["-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
                                     "--system-prompt", "You are a senior creative technologist. " + short]
                if model:
                    cmd += ["--model", model]
                r = _run(cmd, full, tmp, timeout)
                if _unknown_flag(r, "--no-session-persistence"):
                    r = _run([x for x in cmd if x != "--no-session-persistence"], full, tmp, timeout)
                try:
                    res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
                except ValueError:
                    res = {}
                if r.returncode != 0 or res.get("is_error") or not res.get("result"):
                    raise _fail(name, r, str(res.get("result") or ""))
                return str(res["result"])
            if name == "codex":
                out = Path(tmp) / "answer.md"
                cmd = launch(exe) + ["exec", "-", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
                                     "-o", str(out)]
                if model:
                    cmd += ["-m", model]
                r = _run(cmd, full, tmp, timeout)
                if _unknown_flag(r, "--ephemeral"):
                    r = _run([x for x in cmd if x != "--ephemeral"], full, tmp, timeout)
                ans = out.read_text(encoding="utf-8", errors="replace") if out.is_file() else ""
                if r.returncode != 0 and not ans.strip():
                    raise _fail(name, r)
                return ans or ANSI.sub("", r.stdout)
            if name in ("gemini", "qwen"):
                cmd = launch(exe) + ["-p", short, "-o", "json"]
                if model:
                    cmd += ["-m", model]
                r = _run(cmd, full, tmp, timeout)
                if _unknown_flag(r, "-o") or _unknown_flag(r, "output-format"):
                    cmd = [x for x in cmd if x not in ("-o", "json")]
                    r = _run(cmd, full, tmp, timeout)
                raw = ANSI.sub("", r.stdout or "").strip()
                try:
                    res = json.loads(raw[raw.index("{"):]) if raw.startswith("{") or '"response"' in raw else {}
                except ValueError:
                    res = {}
                if res.get("error") and not res.get("response"):
                    raise _fail(name, r, json.dumps(res["error"])[:400])
                ans = str(res.get("response") or raw)
                if r.returncode != 0 and not ans.strip():
                    raise _fail(name, r)
                return ans
            if name == "opencode":
                (Path(tmp) / "PROMPT.md").write_text(full, encoding="utf-8")
                cmd = launch(exe) + ["run", "Read the file PROMPT.md in the current folder and do exactly what it says. "
                                            "Reply with the requested JSON only."]
                if model:
                    cmd += ["--model", model]
                r = _run(cmd, "", tmp, timeout)
                ans = ANSI.sub("", r.stdout or "")
                if r.returncode != 0 and not ans.strip():
                    raise _fail(name, r)
                return ans
        except subprocess.TimeoutExpired as exc:
            raise ClipAgentError(f"{AGENTS[name]['name']} tidak menjawab dalam {timeout // 60} menit.") from exc
        except OSError as exc:
            raise ClipAgentError(f"{AGENTS[name]['name']} tidak bisa dijalankan: {exc}") from exc
    raise ClipAgentError(f"Penulis '{name}' tidak dikenal.")


# ---------------------------------------------------------------- agen penuh (tab Film)
def agentic_cmd(name: str, *, lib: Path, cwd: Path, model: str = "") -> tuple[list, str]:
    """Perintah agen tanpa pengawasan yang boleh menjalankan perintah di komputer ini (dengan izin pengguna).
    Mengembalikan (perintah, catatan cara prompt dikirim)."""
    exe = find(name)
    if not exe:
        a = AGENTS[name]
        raise ClipAgentError(f"{a['name']} tidak ditemukan. Pasang dengan `{a['install']}` lalu login dengan `{a['login']}`.")
    if name == "codex":
        cmd = launch(exe) + ["exec", "-", "--json", "--sandbox", "danger-full-access", "--skip-git-repo-check",
                             "-C", str(cwd)]
        if model:
            cmd += ["-m", model]
        return cmd, "stdin"
    if name == "gemini":
        cmd = launch(exe) + ["-p", "Do the task described above, start to finish, without asking anything.",
                             "-o", "stream-json", "--approval-mode", "yolo", "--include-directories", str(lib)]
        if model:
            cmd += ["-m", model]
        return cmd, "stdin"
    if name == "qwen":
        cmd = launch(exe) + ["-p", "Do the task described above, start to finish, without asking anything.", "--yolo",
                             "--include-directories", str(lib)]
        if model:
            cmd += ["-m", model]
        return cmd, "stdin"
    raise ClipAgentError(f"{AGENTS[name]['name']} belum didukung untuk membuat film; pilih Claude Code, Codex, Gemini CLI, "
                         "atau Qwen Code.")


def parse_event(line: str) -> dict:
    """Satu baris keluaran agen (JSON Lines Codex/Gemini, atau teks biasa) -> peristiwa ringkas:
    {text, tool, session, final, error} (kunci yang tidak ada berarti tidak berlaku)."""
    s = ANSI.sub("", line).strip()
    if not s:
        return {}
    try:
        ev = json.loads(s)
    except ValueError:
        return {"text": s}
    if not isinstance(ev, dict):
        return {"text": s}
    t = str(ev.get("type") or "")
    out: dict = {}
    if t == "thread.started" or t == "init":
        out["session"] = ev.get("thread_id") or ev.get("session_id") or ""
        if ev.get("model"):
            out["text"] = f"model {ev['model']}"
    item = ev.get("item") if isinstance(ev.get("item"), dict) else None
    if item:                                                         # Codex
        it = item.get("type")
        if it in ("agent_message", "assistant_message") and t == "item.completed":
            out["text"] = item.get("text") or ""
        elif it == "command_execution" and t == "item.started":
            out["tool"] = "$ " + re.sub(r"\s+", " ", str(item.get("command") or ""))[:160]
        elif it == "file_change" and t == "item.completed":
            ch = item.get("changes") or []
            out["tool"] = "Tulis: " + ", ".join(str(c.get("path", "")) for c in ch[:3] if isinstance(c, dict))
        elif it == "error":
            out["error"] = item.get("message") or ""
    if t == "message" and ev.get("role") == "assistant":           # Gemini stream-json
        out["text"] = ev.get("content") or ""
        out["delta"] = bool(ev.get("delta"))
    if t == "tool_use":
        params = ev.get("parameters") or {}
        cmd = params.get("command") if isinstance(params, dict) else None
        out["tool"] = ("$ " + str(cmd)[:160]) if cmd else f"{ev.get('tool_name', '')} {json.dumps(params)[:140]}"
    if t in ("turn.completed", "result"):
        out["final"] = True
        if ev.get("status") == "error":
            out["error"] = json.dumps(ev.get("error") or ev)[:400]
    if t in ("turn.failed", "error"):
        err = ev.get("error") or ev.get("message") or ev
        out["error"] = (err.get("message") if isinstance(err, dict) else str(err))[:400]
        if t == "turn.failed":
            out["final"] = True
    return out
