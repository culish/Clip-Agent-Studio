@echo off
REM Clip Agent - klik dua kali untuk menjalankan versi web.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Membuat virtual environment...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Python tidak ditemukan. Install Python 3.13 dari python.org lalu jalankan lagi.
  pause
  exit /b 1
)
if not exist ".venv\installed.ok" (
  echo Memasang paket, tunggu sebentar...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Gagal memasang paket. Periksa koneksi internet lalu jalankan lagi.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -r requirements-whisper.txt
  if errorlevel 1 echo Whisper dilewati, hanya dibutuhkan untuk video tanpa subtitle.
  echo ok> ".venv\installed.ok"
)
if not exist ".venv\extra.ok" (
  echo Memasang suara narasi gratis, opsional...
  ".venv\Scripts\python.exe" -m pip install -r requirements-extra.txt
  if errorlevel 1 echo Suara gratis Edge dilewati, fitur lain tetap jalan.
  echo ok> ".venv\extra.ok"
)
if not exist ".env" copy ".env.example" ".env" >nul
REM Remotion (animasi/kartun) butuh Node.js. Lewati bila Node belum terpasang; fitur lain tetap jalan.
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js belum terpasang: fitur animasi Remotion nonaktif. Pasang dengan: winget install OpenJS.NodeJS.LTS
) else (
  if not exist "remotion\node_modules\remotion" (
    echo Memasang Remotion untuk animasi, sekali saja...
    pushd remotion
    call npm install --no-audit --no-fund
    popd
  )
)
".venv\Scripts\python.exe" app.py %*
pause
