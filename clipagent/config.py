"""Konfigurasi agen: baca file .env dan preset penyedia LLM."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Preset penyedia LLM. Semua kecuali "anthropic" memakai API yang kompatibel OpenAI.
PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-flash-latest",
        # Dicoba berurutan bila model utama sibuk (503) atau kena batas kuota (429).
        "fallbacks": ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model": "",  # wajib diisi lewat LLM_MODEL, mis. model berakhiran ':free'
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": "",
        "model": "qwen2.5:7b",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model": "openai/gpt-oss-120b",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "model": "gpt-5-mini",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "key_env": "ANTHROPIC_API_KEY",
        "model": "claude-sonnet-5-5",
    },
    # Tanpa AI: memilih bagian berdasarkan kepadatan bicara. Gratis & offline.
    "heuristic": {"base_url": "", "key_env": "", "model": "heuristic"},
}


# Gaya animasi subtitle (nama -> keterangan untuk UI/CLI).
ANIMATIONS = {
    "karaoke": "Kata yang diucapkan berganti warna",
    "pop": "Tiap baris muncul dengan efek membesar, kata aktif disorot",
    "bounce": "Satu kata sekali tampil, besar dan memantul",
    "box": "Kata aktif diberi kotak warna",
    "typewriter": "Kata muncul satu per satu seperti diketik",
    "fade": "Baris muncul halus sambil naik",
    "static": "Tanpa animasi",
}

# Font yang dibundel (nama keluarga -> (file, tebal-semu?)). Arial memakai font sistem.
FONTS = {
    "Montserrat Black": ("Montserrat-Black.ttf", False),
    "Anton": ("Anton-Regular.ttf", False),
    "Bebas Neue": ("BebasNeue-Regular.ttf", False),
    "Poppins": ("Poppins-Bold.ttf", True),
    "Arial": (None, True),
}


def load_dotenv() -> None:
    """Pemuat .env sederhana (tanpa dependensi). Variabel yang sudah ada tidak ditimpa."""
    for path in (Path.cwd() / ".env", PROJECT_DIR / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


@dataclass
class Settings:
    source: str
    out_dir: Path = Path("output")
    num_clips: int = 5
    min_dur: float = 20.0
    max_dur: float = 60.0
    language: str = ""              # kode bahasa ucapan (mis. "id"); kosong = deteksi otomatis
    output_language: str = ""       # bahasa judul/caption AI; kosong = ikut audiens
    instructions: str = ""          # arahan tambahan untuk agen
    # LLM
    provider: str = ""              # kosong = ambil dari LLM_PROVIDER di .env
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    fallback_models: list = field(default_factory=list)
    # Transkripsi
    whisper_model: str = "small"
    force_whisper: bool = False
    # Unduhan
    max_height: int = 1080
    cookies: str = ""
    cookies_from_browser: str = ""
    # Audiens & bahasa
    audience: str = "id"            # "us" = penonton AS/global (bahasa Inggris), "id" = Indonesia
    sub_lang: str = "auto"          # "auto" = sesuai ucapan, "en" = terjemahkan ke Inggris
    # Render
    aspect: str = "9:16"            # 9:16 | 1:1 | 4:5 | original
    crop: str = "face"              # face | center | blur
    subtitles: bool = True
    anim: str = "karaoke"           # lihat ANIMATIONS
    font: str = "Montserrat Black"  # lihat FONTS (dibundel di folder fonts/)
    font_size: int = 0              # 0 = otomatis sesuai tinggi video
    uppercase: bool = True
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFE500"
    words_per_line: int = 3
    position: str = "lower"         # lower | middle | upper
    hook_overlay: bool = True       # judul/hook di bagian atas pada detik-detik awal
    progress_bar: bool = False
    zoom: str = "none"              # none | punch (zoom-in bergantian per kalimat)
    crf: int = 20
    preset: str = "veryfast"
    # Alur kerja
    plan_only: bool = False
    plan_file: str = ""
    extra: dict = field(default_factory=dict)

    def resolve(self) -> None:
        """Lengkapi pengaturan turunan (LLM, bahasa output, validasi pilihan)."""
        self.resolve_llm()
        self.audience = (self.audience or "id").lower()
        if not self.output_language:
            self.output_language = "English" if self.audience == "us" else "Indonesia"
        if self.anim not in ANIMATIONS:
            raise ValueError(f"Animasi '{self.anim}' tidak dikenal. Pilihan: {', '.join(ANIMATIONS)}")
        if self.anim == "bounce":
            self.words_per_line = 1

    def resolve_llm(self) -> None:
        """Lengkapi base_url, model, dan api_key dari preset + variabel lingkungan."""
        self.provider = (self.provider or os.getenv("LLM_PROVIDER") or "gemini").lower()
        if self.provider not in PROVIDERS:
            raise ValueError(
                f"Provider '{self.provider}' tidak dikenal. Pilihan: {', '.join(PROVIDERS)}"
            )
        preset = PROVIDERS[self.provider]
        self.base_url = (self.base_url or os.getenv("LLM_BASE_URL") or preset["base_url"]).rstrip("/")
        self.model = self.model or os.getenv("LLM_MODEL") or preset["model"]
        env_fb = os.getenv("LLM_FALLBACK_MODELS")
        if env_fb is not None:
            fallbacks = [m.strip() for m in env_fb.split(",") if m.strip()]
        else:
            fallbacks = preset.get("fallbacks", [])
        self.fallback_models = [m for m in fallbacks if m != self.model]
        key_env = preset["key_env"]
        self.api_key = (self.api_key or os.getenv("LLM_API_KEY")
                        or (os.getenv(key_env) if key_env else "") or "")
