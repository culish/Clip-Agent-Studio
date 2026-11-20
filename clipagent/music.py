"""Musik latar: generator musik bawaan (bebas royalti karena dibuat oleh aplikasi ini) + folder music/ milik Anda.

Generator menyusun progresi akor, bass, petikan melodi, dan drum dengan numpy sesuai suasana (mood).
Taruh file MP3/M4A/WAV sendiri (mis. dari YouTube Audio Library) di folder `music/` agar ikut bisa dipilih.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .config import PROJECT_DIR
from .utils import ClipAgentError

SR = 44100
MUSIC_DIR = PROJECT_DIR / "music"
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac")

MOODS = {
    "santai": {"label": "Santai (lo-fi)", "bpm": 80, "key": 57, "minor": False, "swing": 0.12,
               "prog": [[0, 4, 7, 11], [-3, 0, 4, 7], [-7, -3, 0, 4], [-5, -1, 2, 5]],
               "kick": [0, 2.5], "snare": [1, 3], "hat": 0.5, "arp": 1.0, "pad": 0.55, "lead": 0.5},
    "semangat": {"label": "Semangat (upbeat)", "bpm": 118, "key": 60, "minor": False, "swing": 0.0,
                 "prog": [[0, 4, 7], [7, 11, 14], [9, 12, 16], [5, 9, 12]],
                 "kick": [0, 1, 2, 3], "snare": [1, 3], "hat": 0.25, "arp": 0.25, "pad": 0.4, "lead": 0.55},
    "inspiratif": {"label": "Inspiratif", "bpm": 96, "key": 62, "minor": False, "swing": 0.0,
                   "prog": [[0, 4, 7], [-3, 0, 4], [5, 9, 12], [7, 11, 14]],
                   "kick": [0, 2], "snare": [], "hat": 0.5, "arp": 0.5, "pad": 0.6, "lead": 0.45},
    "dramatis": {"label": "Dramatis (sinematik)", "bpm": 70, "key": 50, "minor": True, "swing": 0.0,
                 "prog": [[0, 3, 7], [-4, 0, 3], [3, 7, 10], [-2, 2, 5]],
                 "kick": [0], "snare": [], "hat": 0, "arp": 0.5, "pad": 0.85, "lead": 0.0},
    "misteri": {"label": "Misteri", "bpm": 90, "key": 52, "minor": True, "swing": 0.0,
                "prog": [[0, 3, 7], [0, 3, 8], [-2, 2, 5], [-1, 3, 6]],
                "kick": [0, 2.5], "snare": [], "hat": 0.5, "arp": 0.5, "pad": 0.7, "lead": 0.35},
    "teknologi": {"label": "Teknologi (synth)", "bpm": 110, "key": 57, "minor": True, "swing": 0.0,
                  "prog": [[0, 3, 7], [-4, 0, 3], [3, 7, 10], [-2, 2, 5]],
                  "kick": [0, 1, 2, 3], "snare": [1, 3], "hat": 0.25, "arp": 0.25, "pad": 0.45, "lead": 0.4},
    # lo-fi hujan: lebih pelan, nada diredam (low-pass), bunyi piringan hitam dan hujan tipis
    "lofi": {"label": "Lo-fi hujan", "bpm": 72, "key": 53, "minor": False, "swing": 0.2,
             "prog": [[0, 4, 7, 11, 14], [-3, 0, 4, 7], [2, 5, 9, 12], [-5, -1, 2, 5]],
             "kick": [0, 2.5], "snare": [1, 3], "hat": 0.5, "arp": 0.0, "pad": 0.7, "lead": 0.35,
             "lowpass": 1500, "crackle": 0.5, "rain": 0.35},
    # dongeng: kotak musik dan pad lembut, tanpa drum
    "dongeng": {"label": "Dongeng (kotak musik)", "bpm": 84, "key": 64, "minor": False, "swing": 0.0,
                "prog": [[0, 4, 7], [-3, 0, 4], [-7, -3, 0], [-5, -1, 2]],
                "kick": [], "snare": [], "hat": 0, "arp": 0.5, "pad": 0.5, "lead": 0.55, "musicbox": True},
}


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    e = np.ones(n)
    a, r = min(a, n), min(r, n)
    e[:a] = np.linspace(0, 1, a)
    e[n - r:] *= np.linspace(1, 0, r)
    return e


def _pad(freqs: list[float], n: int, bright: float) -> np.ndarray:
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):
            ff = f * 2 ** (det / 12)
            for h, amp in ((1, 1.0), (2, 0.35 * bright), (3, 0.18 * bright), (4, 0.08 * bright)):
                out += amp * np.sin(2 * np.pi * ff * h * t + det * 7)
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.25 * t)
    return out * lfo * _env(n, 0.35, 0.45) / (len(freqs) * 3 * 1.6)


def _pluck(f: float, n: int, bright: float = 1.0) -> np.ndarray:
    t = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * f * t) + 0.45 * bright * np.sin(4 * np.pi * f * t)
            + 0.2 * bright * np.sin(6 * np.pi * f * t) * np.exp(-t * 9))
    return tone * np.exp(-t * 5.5) * _env(n, 0.004, 0.05)


def _bass(f: float, n: int) -> np.ndarray:
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)) * _env(n, 0.01, 0.08) * np.exp(-t * 1.2)


def _kick(n: int, deep: bool) -> np.ndarray:
    t = np.arange(n) / SR
    f = (40 if deep else 48) + 90 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * (5 if deep else 9))


def _noise_hit(n: int, decay: float, rng: np.random.Generator, hp: bool) -> np.ndarray:
    x = rng.standard_normal(n)
    if hp:                                      # high-pass lembut: selisih noise yang sedikit dihaluskan
        x = np.diff(x, prepend=0.0)
        x = (x + np.roll(x, 1)) * 0.5
    t = np.arange(n) / SR
    return x * np.exp(-t * decay)


def _bell(f: float, n: int) -> np.ndarray:
    """Nada kotak musik: parsial tak harmonis yang cepat meluruh."""
    t = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 6)
            + 0.25 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t * 12))
    return tone * np.exp(-t * 3.2) * _env(n, 0.002, 0.05)


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """Filter low-pass lembut di domain frekuensi (tanpa scipy)."""
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / np.sqrt(1 + (freqs / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def _reverb(x: np.ndarray, seconds: float, rng: np.random.Generator, wet: float) -> np.ndarray:
    n_ir = int(seconds * SR)
    ir = rng.standard_normal(n_ir) * np.exp(-np.arange(n_ir) / SR * (6.0 / seconds))
    ir[0] = 0
    size = 1 << int(np.ceil(np.log2(len(x) + n_ir)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    y /= (np.abs(y).max() + 1e-9)
    return x + wet * y * (np.abs(x).max() + 1e-9)


def generate(mood: str, seconds: float, seed: int = 7) -> np.ndarray:
    """Hasilkan musik stereo (n, 2) float32 sepanjang `seconds`."""
    m = MOODS.get(mood) or MOODS["santai"]
    rng = np.random.default_rng(seed + sum(map(ord, mood)))
    beat = 60.0 / m["bpm"]
    bar = 4 * beat
    bars = int(np.ceil((seconds + 2) / bar))
    total = int((bars * bar + 3) * SR)
    pad, bass, lead, drums = (np.zeros(total) for _ in range(4))
    scale = [0, 3, 5, 7, 10] if m["minor"] else [0, 2, 4, 7, 9]
    motif = rng.integers(0, len(scale), 8)
    for b in range(bars):
        chord = m["prog"][b % len(m["prog"])]
        root = m["key"] + chord[0]
        start = int(b * bar * SR)
        n = int(bar * SR * 1.08)
        seg = slice(start, start + n)
        # pad
        pad[seg] += _pad([hz(m["key"] + c) for c in chord], n, 0.8 if m["minor"] else 1.0)[: total - start]
        # bass: akar akor tiap ketukan 1 dan 3
        for k in (0, 2):
            s = start + int(k * beat * SR)
            nb = int(beat * 1.9 * SR)
            bass[s:s + nb] += _bass(hz(root - 24), nb)[: total - s]
        # arpeggio petikan
        if m["arp"]:
            step = m["arp"] * beat
            steps = int(round(bar / step))
            notes = sorted(chord) + [chord[0] + 12]
            for i in range(steps):
                if mood == "dramatis" and i % 2:
                    continue
                s = start + int(i * step * SR + (m["swing"] * step * SR if i % 2 else 0))
                f = hz(m["key"] + (24 if m.get("musicbox") else 12) + notes[i % len(notes)])
                np_ = int(min(1.2, step * 3) * SR)
                lead[s:s + np_] += 0.22 * (_bell(f, np_) if m.get("musicbox") else _pluck(f, np_, 0.6))[: total - s]
        # melodi sederhana pentatonik di bar genap
        if m["lead"] and b % 2 == 1:
            for i in range(4):
                if rng.random() < 0.35:
                    continue
                s = start + int(i * beat * SR)
                note = m["key"] + 24 + scale[int(motif[(b + i) % 8])]
                nl = int(beat * 1.6 * SR)
                tone = _bell(hz(note + 12), nl) if m.get("musicbox") else _pluck(hz(note), nl, 1.0)
                lead[s:s + nl] += 0.3 * m["lead"] * tone[: total - s]
        # drum (masuk setelah 1 bar intro)
        if b == 0 and mood not in ("dramatis",):
            continue
        for k in m["kick"]:
            s = start + int(k * beat * SR)
            nk = int(0.5 * SR)
            drums[s:s + nk] += (0.8 if mood in ("santai", "lofi") else 1.0) * _kick(nk, mood == "dramatis")[: total - s]
        for k in m["snare"]:
            s = start + int(k * beat * SR)
            ns = int(0.25 * SR)
            hit = 0.35 * _noise_hit(ns, 22, rng, False) + 0.25 * np.sin(2 * np.pi * 190 * np.arange(ns) / SR) * np.exp(-np.arange(ns) / SR * 30)
            drums[s:s + ns] += (0.5 if mood in ("santai", "lofi") else 0.7) * hit[: total - s]
        if m["hat"]:
            steps = int(round(4 / m["hat"]))
            for i in range(steps):
                s = start + int(i * m["hat"] * beat * SR + (m["swing"] * m["hat"] * beat * SR if i % 2 else 0))
                nh = int(0.06 * SR)
                vel = 0.05 if i % 2 else 0.08
                if mood == "teknologi" and i % 2 == 0:
                    vel = 0.03
                drums[s:s + nh] += vel * _noise_hit(nh, 70, rng, True)[: total - s]
    music = 0.9 * _reverb(pad * m["pad"], 2.4, rng, 0.35) + 0.8 * bass + _reverb(lead, 1.6, rng, 0.25) + 0.75 * drums
    n_out = int(seconds * SR)
    music = music[:n_out]
    if m.get("lowpass"):
        music = _lowpass(music, m["lowpass"])
    if m.get("crackle") or m.get("rain"):
        lvl = np.abs(music).max() + 1e-9
        if m.get("rain"):                                  # hujan tipis: noise yang diredam
            music = music + _lowpass(rng.standard_normal(len(music)), 2600) * 0.05 * m["rain"] * lvl
        if m.get("crackle"):                               # bunyi piringan hitam: letupan kecil acak
            pops = np.zeros(len(music))
            idx = rng.integers(0, len(music), int(len(music) / SR * 9))
            pops[idx] = rng.standard_normal(len(idx)) * 0.6
            pops += rng.standard_normal(len(music)) * 0.012
            music = music + _lowpass(pops, 5000) * 0.25 * m["crackle"] * lvl
    fade = min(n_out, int(2.0 * SR))
    music[-fade:] *= np.linspace(1, 0, fade)
    music[: int(0.02 * SR)] *= np.linspace(0, 1, int(0.02 * SR))
    music = np.tanh(music / (np.abs(music).max() + 1e-9) * 1.4) * 0.7
    # stereo lebar sederhana: geser sedikit kanal kanan
    d = int(0.012 * SR)
    right = np.concatenate([np.zeros(d), music[:-d]]) * 0.92 + music * 0.08
    return np.stack([music, right], axis=1).astype(np.float32)


def write_wav(path: Path, stereo: np.ndarray) -> None:
    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def user_tracks() -> list[str]:
    MUSIC_DIR.mkdir(exist_ok=True)
    return sorted(p.name for p in MUSIC_DIR.iterdir() if p.suffix.lower() in AUDIO_EXT)


def choices() -> dict:
    out = {"auto": "Otomatis (dipilih AI sesuai isi)", "none": "Tanpa musik"}
    out.update({f"gen:{k}": f"Bawaan: {v['label']}" for k, v in MOODS.items()})
    out.update({f"file:{n}": f"File saya: {n}" for n in user_tracks()})
    return out


def track(choice: str, seconds: float, cache_dir: Path, mood_hint: str = "santai") -> Path | None:
    """Kembalikan file musik untuk durasi `seconds` (WAV hasil generator, atau file dari folder music/)."""
    if not choice or choice == "none":
        return None
    if choice == "auto":
        choice = f"gen:{mood_hint if mood_hint in MOODS else 'santai'}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if choice.startswith("file:"):
        name = Path(choice[5:]).name
        src = MUSIC_DIR / name
        if not src.is_file():
            raise ClipAgentError(f"File musik '{name}' tidak ada di folder music/.")
        out = cache_dir / f"music_{Path(name).stem[:40]}_{int(seconds)}.wav"
        if not out.is_file():
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(src), "-t",
                                f"{seconds:.2f}", "-af", f"afade=t=out:st={max(0, seconds - 2):.2f}:d=2",
                                "-ac", "2", "-ar", str(SR), str(out)], capture_output=True, text=True)
            if r.returncode != 0:
                raise ClipAgentError(f"Gagal membaca file musik: {r.stderr[-200:]}")
        return out
    mood = choice.split(":", 1)[1] if ":" in choice else choice
    if mood not in MOODS:
        mood = "santai"
    out = cache_dir / f"music_gen_{mood}_{int(np.ceil(seconds))}.wav"
    if not out.is_file():
        write_wav(out, generate(mood, float(np.ceil(seconds))))
    return out
