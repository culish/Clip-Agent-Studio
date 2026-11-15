#!/usr/bin/env python3
"""YT Clip Agent — ubah video YouTube panjang menjadi klip pendek otomatis.

Contoh:
  python clipper.py "https://www.youtube.com/watch?v=XXXX"
  python clipper.py "https://youtu.be/XXXX" -n 3 --max 45 --instructions "fokus ke pembahasan IoT"
  python clipper.py rekaman_kuliah.mp4 --provider heuristic
  python clipper.py "https://youtu.be/XXXX" --audience us --sub-lang en --anim bounce --zoom punch

Versi web (lebih mudah): python app.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clipagent.config import ANIMATIONS, FONTS, PROVIDERS, Settings, load_dotenv
from clipagent.pipeline import run_pipeline
from clipagent.utils import ClipAgentError


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="clipper.py",
        description="Agen AI pemotong video YouTube menjadi klip pendek (Shorts/Reels/TikTok).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Contoh:", 1)[1] if __doc__ else None,
    )
    p.add_argument("source", help="URL YouTube atau path file video lokal")
    g = p.add_argument_group("Pemilihan klip")
    g.add_argument("-n", "--num", type=int, default=5, help="jumlah klip (default 5)")
    g.add_argument("--min", type=float, default=20, help="durasi minimal klip, detik (default 20)")
    g.add_argument("--max", type=float, default=60, help="durasi maksimal klip, detik (default 60)")
    g.add_argument("--instructions", default="", help='arahan untuk agen, mis. "pilih bagian yang lucu"')
    g.add_argument("--audience", default="id", choices=["us", "id"],
                   help="target penonton: us = AS/global (Inggris, CPM tinggi), id = Indonesia (default)")
    g.add_argument("--output-language", default="",
                   help="bahasa judul & caption (default: English untuk --audience us, Indonesia untuk id)")
    g.add_argument("--provider", default="", choices=["", *PROVIDERS],
                   help="penyedia LLM (default dari .env, atau gemini)")
    g.add_argument("--model", default="", help="nama model LLM (menimpa .env)")

    g = p.add_argument_group("Transkrip")
    g.add_argument("--lang", default="", help='kode bahasa ucapan, mis. "id" atau "en" (default otomatis)')
    g.add_argument("--whisper-model", default="small",
                   help="ukuran Whisper bila video tanpa subtitle: tiny/base/small/medium/large-v3")
    g.add_argument("--force-whisper", action="store_true",
                   help="abaikan subtitle YouTube, selalu transkripsi dengan Whisper")

    g = p.add_argument_group("Tampilan klip")
    g.add_argument("--aspect", default="9:16", choices=["9:16", "1:1", "4:5", "original"],
                   help="rasio keluaran (default 9:16)")
    g.add_argument("--crop", default="face", choices=["face", "center", "blur"],
                   help="face = ikuti wajah, center = crop tengah, blur = video utuh + latar blur")
    g.add_argument("--no-subs", action="store_true", help="tanpa subtitle tertanam")
    g.add_argument("--sub-lang", default="auto", choices=["auto", "en", "id"],
                   help="bahasa subtitle: auto = sesuai ucapan, en = terjemahkan ke Inggris")
    g.add_argument("--anim", default="karaoke", choices=list(ANIMATIONS),
                   help="animasi subtitle: " + ", ".join(ANIMATIONS))
    g.add_argument("--font", default="Montserrat Black", choices=list(FONTS), help="font subtitle")
    g.add_argument("--font-size", type=int, default=0, help="ukuran font (0 = otomatis)")
    g.add_argument("--text-color", default="#FFFFFF", help="warna teks subtitle (default #FFFFFF)")
    g.add_argument("--color", default="#FFE500", help="warna sorotan kata aktif (default #FFE500)")
    g.add_argument("--words", type=int, default=3, help="jumlah kata per tampilan subtitle (default 3)")
    g.add_argument("--position", default="lower", choices=["lower", "middle", "upper"],
                   help="posisi subtitle (default lower)")
    g.add_argument("--no-uppercase", action="store_true", help="subtitle tidak huruf kapital")
    g.add_argument("--no-hook", action="store_true", help="tanpa judul/hook di atas pada detik awal")
    g.add_argument("--progress-bar", action="store_true", help="tampilkan progress bar di bawah")
    g.add_argument("--zoom", default="none", choices=["none", "punch"],
                   help="punch = zoom-in bergantian per kalimat")
    g.add_argument("--crf", type=int, default=20, help="kualitas video x264, makin kecil makin bagus (default 20)")

    g = p.add_argument_group("Unduhan & alur kerja")
    g.add_argument("-o", "--out", default="output", help="folder keluaran (default ./output)")
    g.add_argument("--max-height", type=int, default=1080, help="resolusi unduhan maksimal (default 1080)")
    g.add_argument("--cookies", default="", help="file cookies.txt (untuk video yang butuh login)")
    g.add_argument("--cookies-from-browser", default="",
                   help="ambil cookies dari browser: chrome, firefox, edge, brave, ...")
    g.add_argument("--plan-only", action="store_true",
                   help="hanya pilih klip & simpan plan.json, tanpa render")
    g.add_argument("--plan", default="", help="render dari plan.json (mis. setelah diedit manual)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    load_dotenv()
    a = parse_args(argv)
    if a.min <= 0 or a.max < a.min:
        print("Error: --min harus > 0 dan --max harus >= --min", file=sys.stderr)
        return 2
    cfg = Settings(
        source=a.source, out_dir=Path(a.out), num_clips=a.num, min_dur=a.min, max_dur=a.max,
        language=a.lang, output_language=a.output_language, instructions=a.instructions,
        audience=a.audience, sub_lang=a.sub_lang, anim=a.anim, text_color=a.text_color,
        position=a.position, hook_overlay=not a.no_hook, progress_bar=a.progress_bar, zoom=a.zoom,
        provider=a.provider, model=a.model,
        whisper_model=a.whisper_model, force_whisper=a.force_whisper,
        max_height=a.max_height, cookies=a.cookies, cookies_from_browser=a.cookies_from_browser,
        aspect=a.aspect, crop=a.crop, subtitles=not a.no_subs, font=a.font, font_size=a.font_size,
        uppercase=not a.no_uppercase, highlight_color=a.color, words_per_line=a.words, crf=a.crf,
        plan_only=a.plan_only, plan_file=a.plan,
    )
    try:
        cfg.resolve()
        run_pipeline(cfg)
    except ClipAgentError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nDibatalkan.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
