#!/usr/bin/env bash
# Clip Agent - jalankan versi web (macOS/Linux): ./start.sh
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
if [ ! -f .venv/installed.ok ]; then
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip install -r requirements-whisper.txt || echo "Whisper dilewati (opsional)."
  touch .venv/installed.ok
fi
if [ ! -f .venv/extra.ok ]; then
  .venv/bin/python -m pip install -r requirements-extra.txt || echo "Suara gratis Edge dilewati (opsional)."
  touch .venv/extra.ok
fi
[ -f .env ] || cp .env.example .env
# Remotion (animasi/kartun) butuh Node.js; fitur lain tetap jalan tanpanya.
if command -v node >/dev/null 2>&1; then
  [ -d remotion/node_modules/remotion ] || (cd remotion && npm install --no-audit --no-fund) || echo "Gagal memasang Remotion."
else
  echo "Node.js belum terpasang: fitur animasi Remotion nonaktif (https://nodejs.org)."
fi
exec .venv/bin/python app.py "$@"
