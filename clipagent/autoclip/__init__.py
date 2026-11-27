"""Potongan AutoClip (https://github.com/zhouxiaoka/autoclip) yang diadaptasi untuk Clip Agent.

MIT License, Copyright (c) 2024 AutoClip Team; teks lisensinya ada di clipagent/autoclip/LICENSE.
- boundaries.py: merapikan awal/akhir klip ke kalimat utuh dan jeda audio (services/studio/boundaries.py).
- qa.py: pemeriksaan mutu klip hasil render (services/studio/qa/: ending, loudness, jitter, face).
Dipakai oleh clipagent/trim.py (fitur "Cek frame & durasi" di Auto clip).
"""
