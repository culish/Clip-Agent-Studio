#!/usr/bin/env python3
"""Clip Agent — versi web. Jalankan: python app.py  (browser terbuka otomatis)."""
from __future__ import annotations

import argparse

from clipagent.config import load_dotenv
from clipagent.webapp import serve


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="Web app lokal Clip Agent")
    p.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    p.add_argument("--host", default="127.0.0.1",
                   help="alamat (default 127.0.0.1 = hanya komputer ini)")
    p.add_argument("-o", "--out", default="output", help="folder hasil (default ./output)")
    p.add_argument("--no-browser", action="store_true", help="jangan buka browser otomatis")
    a = p.parse_args()
    serve(a.host, a.port, a.out, open_browser=not a.no_browser)


if __name__ == "__main__":
    main()
