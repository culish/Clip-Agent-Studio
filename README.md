# Clip Agent

Agen AI yang mengubah video YouTube panjang (podcast, wawancara, kuliah, webinar) menjadi klip pendek siap unggah untuk Shorts, Reels, atau TikTok. Tersedia sebagai **web app lokal** (paling mudah) dan **perintah terminal**.

## Mulai cepat (Windows)

1. Pasang **ffmpeg**, **Deno**, dan **Node.js** (sekali saja), lewat PowerShell:
   ```
   winget install Gyan.FFmpeg
   winget install DenoLand.Deno
   winget install OpenJS.NodeJS.LTS
   ```
   Node.js hanya dibutuhkan untuk animasi/kartun (Remotion). Tanpa Node.js, fitur lain tetap jalan.
2. Klik dua kali **`start.bat`**. Pada pemakaian pertama, skrip membuat virtual environment, memasang paket Python, dan memasang Remotion di folder `remotion` (beberapa menit). Setelah itu browser terbuka di `http://127.0.0.1:8765`.
3. Di tab **Pengaturan**, pilih penyedia AI dan isi API key (Gemini punya kuota gratis: aistudio.google.com/apikey), lalu klik **Tes koneksi AI**.
4. Di tab **Studio**, tempel link YouTube lalu klik **Buat klip**.

macOS/Linux: pasang ffmpeg, Deno, dan Node.js (`brew install ffmpeg deno node`), lalu jalankan `./start.sh`.

> Python 3.10–3.14 disarankan (3.13 paling aman). Di Python 3.15, aplikasi tetap berjalan, tetapi Whisper (untuk video tanpa subtitle) belum bisa dipasang karena onnxruntime belum tersedia.

## Riset video viral

Tab **Riset viral** mencari video yang sedang naik cepat untuk penonton AS. Setiap video diberi **skor 0–100**:

- **Views per jam** sejak diunggah (bobot 50%).
- **Outlier**: views dibanding jumlah subscriber channel (35%). Video dari channel kecil dengan views 20x subscriber berarti topiknya sedang disukai algoritma.
- **Interaksi**: (like + 2 × komentar) / views (15%).

Badge warna menunjukkan perkiraan CPM niche-nya. Tombol **Buat versi orisinal** membawa video itu ke tab **Buat video**. Tombol **Klip video ini** hanya muncul untuk video berlisensi Creative Commons.

Tanpa API key, data diambil lewat yt-dlp (20–40 detik). Dengan **YouTube Data API key** (gratis, isi di Pengaturan), hasilnya lebih cepat, data subscriber/like/komentar lengkap, dan tombol **Populer di AS sekarang** aktif.

## Buat video orisinal (pembuat ulang)

Tab **Buat video** membuat video baru dari video viral atau dari topik yang Anda ketik:

1. **Naskah orisinal.** AI membaca teks ucapan video sumber hanya sebagai riset (videonya tidak diunduh), lalu menulis naskah baru dengan sudut pandang dan kata-kata sendiri. Kemiripan dengan sumber diukur otomatis (5-kata berurutan yang sama). Bila lebih dari 8%, AI diminta menulis ulang. Angkanya tampil di editor.
2. **Edit per adegan**: narasi, judul di layar, jenis visual, deskripsi gambar, kata kunci stok, gerak kamera, transisi. Urutan adegan bisa diubah.
3. **Suara narasi**: Gemini TTS (30 suara, butuh Gemini API key) atau Edge (gratis, tanpa key).
4. **Visual per adegan**: gambar AI (dengan karakter Anda), video stok Pexels, kartu teks, atau video AI. Video AI memakai Gemini Omni Flash, berbayar sekitar US$0,10 per detik 720p, dan baru dipakai bila **Izinkan video AI berbayar** dicentang. Perkiraan biayanya tampil sebelum dibuat.
5. **Musik, caption, render**: musik bawaan atau file Anda, caption karaoke, dirender dengan Remotion.

**Siapkan suara & gambar** membuat aset per adegan agar bisa dicek (ada pemutar suara dan gambar kecil per adegan). Aset disimpan, jadi **Buat video** hanya membuat ulang adegan yang berubah. Hasil ada di `output/_projects/<id>/`.

### Karakter (Character Studio)

Buat karakter sekali (nama, persona, penampilan, gaya gambar, suara), lalu unggah gambar referensi atau klik **Buat dengan AI** dan pilih satu dari tiga gambar. Gambar referensi ikut dikirim ke AI setiap kali adegan digambar, sehingga wajah, rambut, dan pakaian tetap sama di semua video. Pilih karakter saat membuat proyek; suara karakter otomatis dipakai.

### Catatan agar tetap bisa dimonetisasi

Sejak Juli 2025 YouTube tidak memonetisasi konten "inauthentic": video massal yang mirip satu sama lain, atau konten orang lain yang diulang tanpa nilai tambah. Karena itu Clip Agent menulis naskah baru dan mengukur kemiripannya. Tetap tambahkan sudut pandang Anda sendiri (kolom **Sudut pandang / arahan**), variasikan format, dan jangan mengunggah puluhan video yang hampir sama.

## Video kolase editorial (tab Kolase)

Dari satu voice-over menjadi video explainer bergaya kolase: foto arsip hitam-putih yang digunting dan ditempel, dokumen yang distabilo tepat saat kata itu diucapkan, peta, tipografi besar, angka yang berhitung naik, garis waktu, perbandingan, dan diagram alur. Efek suara (kertas, stempel, spidol, ketikan, transisi) disintesis sendiri dan jatuh tepat di animasinya; musik otomatis mengecil saat ada suara.

1. **Proyek baru**: unggah file VO (MP3/WAV/M4A), atau tulis narasi untuk dibacakan suara AI (Edge gratis / Gemini). Pilih format (9:16, 16:9, 1:1, 4:5), tema warna, dan sumber foto: foto stok Pexels (gratis), gambar AI Gemini (berbayar; subjek otomatis digunting dari latar putih), atau tanpa foto.
2. **Storyboard**: transkrip per kata dengan Whisper (`pip install -r requirements-whisper.txt`), lalu AI memilih tata letak tiap adegan. Angka, tahun, dan negara hanya tampil bila benar-benar diucapkan di VO; kalau tidak, adegan diganti tipografi. Tanpa penyedia AI, storyboard dibuat dengan aturan sederhana.
3. **Ubah** tata letak, judul layar, kata yang distabilo, deskripsi foto, atau isi garis waktu/alur bila perlu.
4. **Render**: hasilnya video final, versi tanpa musik, file suara terpisah, lembar tinjau per adegan, dan pemeriksaan durasi serta loudness (target -14 LUFS). Video langsung muncul di tab Posting.

Agent tidak bisa mendengar: dengarkan sendiri hasilnya sebelum mengunggah, periksa fakta yang tampil di layar (daftarnya ada di bawah video), dan nyalakan label konten AI bila memakai gambar atau suara AI.

### Paket Kolase Editorial (lokal)

Bila Anda membeli paket "Kolase Editorial" dan memasangnya di komputer, isi lokasi foldernya di tab Kolase (bagian *Paket Kolase Editorial (lokal)*) atau `KOLASE_PAKET_DIR` di `.env`. Di setiap proyek muncul tombol **Siapkan proyek paket**: Clip Agent menjalankan skrip paket untuk membuat proyek dari VO yang sama, menjalankan transkripnya, lalu memberi perintah yang tinggal disalin ke AI agent Anda (Claude Code, Codex, Gemini CLI, dan sejenisnya). Video di folder `hasil/` proyek paket otomatis muncul di tab Kolase dan Posting. Isi paket tetap di komputer Anda dan tidak pernah disalin ke repo ini, sesuai lisensinya.

## Edit otomatis: b-roll, musik, caption

Di tab **Edit & animasi**, bagian **Edit otomatis** merender ulang klip yang sudah jadi:

- **B-roll**: AI memilih 2–5 momen (tidak di 2,5 detik pertama), lalu menyisipkan video stok Pexels yang cocok atau gambar AI.
- **Musik latar** yang otomatis mengecil saat ada orang bicara (ducking).
- **Caption karaoke** dengan gaya pilihan, ditambah judul di awal dan progress bar.

Hasilnya `clips/<klip>__edit.mp4`. Kredit pembuat video stok otomatis ditambahkan ke deskripsi saat posting.

**Musik.** Ada 6 musik bawaan yang dibuat oleh aplikasi sendiri, sehingga bebas royalti: Santai, Semangat, Inspiratif, Dramatis, Misteri, dan Teknologi. Untuk musik yang lebih kaya, taruh MP3 sendiri di folder `music/` (misalnya dari YouTube Audio Library).

## Posting otomatis ke banyak akun

Tab **Posting** mengunggah video ke **YouTube**, **Facebook Reels**, **Instagram Reels**, dan **TikTok**, langsung atau terjadwal. Setiap platform bisa punya **banyak akun**, misalnya 3 channel YouTube, 4 Page Facebook, 2 akun Instagram, dan 5 akun TikTok. Saat posting, centang akun tujuan mana saja. Setiap akun jadi target terpisah di antrean, lengkap dengan status, tautan hasil, dan tombol **Coba lagi** bila gagal. Tombol **Posting** juga ada di setiap kartu klip dan hasil video.

### Menambah akun

- **YouTube**
  - Butuh satu OAuth Client jenis *Desktop app* dari Google Cloud Console (langkahnya ada di tab Posting). Satu Client dipakai untuk semua channel.
  - Klik **Tambah channel YouTube** dari browser di laptop, lalu pilih akun dan channel. Ulangi untuk channel lain dengan memilih akun atau channel lain di layar login Google.
  - Selama aplikasi OAuth berstatus Testing, semua email pemilik channel harus didaftarkan di Test users, dan izinnya berlaku 7 hari. Klik **Publish app** agar tidak kedaluwarsa.
- **Facebook & Instagram**
  - Tempel User access token dari Graph API Explorer lalu klik **Tambah dari token**. Semua Page beserta akun Instagram profesional yang terhubung langsung ditambahkan.
  - Untuk akun Facebook lain, buat token dari akun itu dan tambahkan lagi.
  - Izin yang dibutuhkan: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management`.
- **TikTok**
  - Buat aplikasi di developers.tiktok.com dengan produk **Login Kit** (platform Desktop) dan **Content Posting API** (aktifkan Direct Post).
  - Scope: `user.info.basic`, `video.publish`, `video.upload`. Redirect URI: `http://127.0.0.1:*/oauth/tiktok/`.
  - Isi Client Key dan Client Secret, lalu klik **Tambah akun TikTok**. Untuk akun berikutnya, keluar dulu dari TikTok di browser, lalu tambah lagi.

Akun yang tidak dipakai bisa dihapus satu per satu. Semua token tersimpan di `data/accounts.json`. Jangan bagikan folder `data/`, dan folder ini tidak ikut ke repo Git.

### TikTok

- **Langsung terbit (Direct Post)**: video langsung diposting ke profil. Sesuai aturan TikTok, Clip Agent menampilkan info akun terbaru setiap kali form posting dibuka. Isian yang diminta:
  - pilihan **siapa yang bisa menonton**, tanpa nilai bawaan;
  - izin Komentar, Duet, dan Stitch (bawaannya mati, dan dikunci bila dimatikan di akun);
  - pengungkapan konten komersial (*Merek Anda* / *Konten bermerek*);
  - persetujuan Music Usage Confirmation.

  Durasi video juga dicek terhadap batas akun.
- **Kirim ke draf TikTok**: video masuk ke kotak masuk aplikasi TikTok, lalu Anda menyelesaikan posting di HP. Maksimal 5 video menunggu dalam 24 jam.
- **Sebelum aplikasi TikTok Anda diaudit**: Direct Post hanya bisa ke akun TikTok yang diset privat, dengan privasi "Hanya saya". Ajukan audit di developers.tiktok.com agar bisa terbit untuk publik, atau pakai mode **Kirim ke draf** sementara itu.
- **Jadwal TikTok** dijalankan oleh Clip Agent, jadi aplikasi harus menyala pada waktunya.
- **File besar**: video di atas 64 MB diunggah per potongan 10 MB, sesuai aturan TikTok.

### Catatan

- **Jadwal YouTube dan Facebook** memakai fitur jadwal platformnya (laptop boleh mati). **Jadwal Instagram dan TikTok** dijalankan Clip Agent.
- **Tandai sebagai konten buatan AI** mengisi label resmi di setiap platform: `containsSyntheticMedia` (YouTube), `is_ai_generated` (Instagram), dan `is_aigc` (TikTok).
- **Video yang sama di banyak channel**: hati-hati mengunggah video yang persis sama ke banyak channel. YouTube dan TikTok bisa menganggapnya spam atau konten "reused". Variasikan judul, caption, dan videonya.

## Cover dan versi kartun

Tab **Edit & animasi** (atau tombol **Edit & animasi** di kartu klip) bekerja pada klip yang sudah dibuat.

**Cover.** Agen memilih tiga frame terbaik: tajam, wajah terlihat, dan pencahayaan cukup. AI lalu menulis teks cover pendek, atau Anda bisa mengetik sendiri. Setiap varian dibuat dalam dua ukuran: 9:16 (1080×1920) untuk Shorts, Reels, dan TikTok, serta 16:9 (1280×720, di bawah 2 MB) untuk thumbnail YouTube. Varian yang tersedia: tiga foto asli, satu versi kartun, dan satu versi AI (opsional).

**Kartun dan animasi dengan [Remotion](https://www.remotion.dev).** Video animasi dirender oleh Remotion (React) di laptop Anda. Alurnya empat langkah:

1. **Storyboard.** Pilih salah satu cara:
   - **Buat pilihan storyboard**: AI menyusun tiga pilihan dari isi klip, yaitu *Per kalimat* (satu adegan per kalimat), *Per poin utama* (3–6 poin dengan judul besar), dan *Panel komik* (4–8 panel dengan balon kata dan efek suara). Klik **Pakai storyboard ini** pada pilihan yang cocok.
   - **Tulis sendiri**: adegan kosong dibuat per kalimat, lalu Anda isi sendiri.
2. **Edit adegan.** Setiap adegan bisa diubah: waktu mulai dan selesai, judul di layar, balon kata, efek suara (mis. `BOOM!`), gerak kamera, transisi ke adegan berikutnya, dan deskripsi gambar untuk AI. Tombol **Bagi**, **Gabung**, **Hapus**, dan **Tambah adegan** tersedia. Bagian klip yang tidak masuk adegan mana pun dipotong dari video.
3. **Gaya animasi.** Pilih preset, atau nyalakan **Atur gaya sendiri** untuk mengubah semuanya:

   | Preset | Isi |
   |---|---|
   | Komik klasik | Panel bergaris tebal, latar halftone, balon kata, efek suara |
   | Anime cerah | Gambar penuh bergaya anime, garis kecepatan, caption karaoke |
   | Stop-motion kertas | Potongan kertas sobek, gerak patah-patah 12 fps |
   | Explainer bersih | Foto dalam kartu, judul per poin, satu kata besar sebagai caption |
   | Video kartun bergerak | Video asli tetap bergerak dengan warna poster |
   | Ilustrasi AI | Setiap adegan digambar ulang oleh AI (Gemini) |

   Gaya kustom mengatur sumber gambar (kartun lokal, gambar AI, foto dari video, atau video bergerak), gaya kartun, arahan gaya untuk AI, bingkai (layar penuh, panel komik, kartu, kertas), caption (karaoke, satu kata besar, balon kata, tanpa caption), tekstur, gerak halus atau stop-motion, font, lima warna, huruf kapital, efek suara, dan durasi transisi. **Lihat contoh semua gaya** merender satu frame per preset dari klip Anda.
4. **Pratinjau, lalu buat video.** **Pratinjau 3 frame** merender tiga frame contoh dengan storyboard dan gaya pilihan Anda. Bila sudah cocok, klik **Buat video**.

Storyboard yang sedang diedit dan gaya pilihan Anda tersimpan otomatis di browser untuk setiap klip. Audio asli tetap dipakai, dan subtitle bisa diterjemahkan ke bahasa Inggris. Hasilnya tersimpan di folder `clips` dengan akhiran `__remotion-<gaya>.mp4`.

Catatan:
- Render pertama butuh sekitar setengah menit tambahan untuk menyiapkan Remotion. Klip 20–30 detik biasanya selesai dalam 1–3 menit; gaya *Video kartun bergerak* paling lama.
- Gambar AI dibuat sekali per adegan lalu disimpan, jadi pratinjau dan video memakai gambar yang sama dan tidak ditagih dua kali. Bila AI gagal, adegan itu otomatis memakai kartun lokal.
- Remotion gratis untuk perorangan dan perusahaan dengan maksimal 3 karyawan. Perusahaan yang lebih besar butuh lisensi perusahaan dari remotion.dev.
- Desain komposisi ada di `remotion/src/CartoonStory.tsx`. Untuk mengutak-atiknya secara visual: `cd remotion && npm run studio`.

## Aplikasi Android

APK ada di `android/ClipAgent.apk` (Android 7.0 ke atas). Aplikasi ini adalah **remote**: unduhan YouTube, AI, dan render tetap berjalan di laptop, sedangkan HP dipakai untuk membuat klip, memantau progres, dan menyimpan hasilnya. HP dan laptop harus memakai Wi-Fi yang sama.

**Memasang (sekali saja)**
1. Di laptop, buka tab **Pengaturan**, lalu nyalakan **Akses dari HP**. Jika Windows menampilkan peringatan firewall untuk Python, centang **Private networks** lalu pilih **Allow**. Pastikan profil Wi-Fi laptop diatur sebagai Private.
2. Pindai QR yang tampil dengan kamera HP. Halaman "HP sudah terhubung" terbuka; pilih **Unduh aplikasi Android (APK)**. Cara lain: kirim file `android/ClipAgent.apk` ke HP.
3. Pasang APK. Android akan meminta izin "Instal aplikasi tidak dikenal" untuk browser atau file manager. Play Protect mungkin memberi peringatan karena aplikasi tidak berasal dari Play Store; pilih **Tetap instal**.
4. Buka **Clip Agent** di HP, lalu masukkan alamat dan kode akses dari laptop. Cara lain: pindai QR lagi lalu pilih **Buka di aplikasi Clip Agent**.

**Memakai**
- Di aplikasi YouTube, ketuk **Bagikan**, lalu pilih **Clip Agent**. Link langsung masuk ke Studio.
- Ketuk **Unduh MP4** pada klip yang sudah jadi. File tersimpan di **Download/ClipAgent** dan muncul di galeri, siap diunggah ke TikTok, Reels, atau Shorts.
- Tanpa APK pun, web app bisa dibuka di browser HP setelah memindai QR.

**Keamanan.** Akses dari HP hanya terbuka di jaringan lokal dan butuh kode akses. Percobaan kode yang salah dibatasi, dan **Buat kode baru** memutus HP yang sudah terhubung. Matikan Akses dari HP saat memakai Wi-Fi publik.

**Membangun ulang APK** (opsional, untuk pengembang): `python android/build_apk.py --android-jar android.jar --aapt2 aapt2 --bundletool bundletool-all.jar --dx dx.jar`. Kode sumbernya ada di `android/src`. Keystore penanda tangan (`android/keystore/clipagent-release.p12`, sandi `clipagent`) tidak disimpan di repo publik. Bila belum ada, skrip membuat keystore baru dengan `keytool`. Simpan cadangannya, karena APK dengan kunci berbeda tidak bisa memperbarui aplikasi yang sudah terpasang (harus uninstall dulu).

## Isi web app

**Studio.** Tempel URL, pilih target penonton, atur gaya, lalu buat klip. Progres, log, dan hasil (bisa diputar, diunduh, dan caption-nya disalin) tampil di halaman yang sama. Pratinjau ponsel di sebelah kanan memperlihatkan animasi subtitle secara langsung.

- **Target penonton "Amerika & global (Inggris)"**: agen memilih momen yang relevan untuk penonton AS (pasar iklan CPM tinggi). Judul, caption, dan hashtag ditulis dalam bahasa Inggris, dan subtitle diterjemahkan ke Inggris bila video berbahasa lain. Waktu per kata hasil terjemahan diperkirakan dari kalimat aslinya.
- **Animasi subtitle**: `karaoke` (kata aktif berganti warna), `pop` (baris muncul membesar), `bounce` (satu kata besar memantul, gaya "Hormozi"), `box` (kata aktif diberi kotak warna), `typewriter` (kata muncul satu per satu), `fade` (muncul halus sambil naik), `static`.
- **Font bundel**: Montserrat Black, Anton, Bebas Neue, Poppins (lisensi SIL OFL, di folder `fonts/`), plus Arial. Warna teks, warna sorotan, jumlah kata per tampilan, huruf kapital, dan posisi (atas/tengah/bawah) bisa diatur.
- **Efek video**: judul/hook di bagian atas pada 3 detik pertama, progress bar, zoom bergantian per kalimat (gaya jump-cut), rasio 9:16 / 4:5 / 1:1 / asli, serta pembingkaian yang mengikuti wajah, potong tengah, atau video utuh dengan latar blur.
- **Render ulang dengan gaya saat ini**: memakai klip yang sudah dipilih tanpa memanggil AI dan tanpa mengunduh ulang. Cocok untuk mencoba animasi lain.

**Riset viral** (dulu Trend Radar).
- **Riset video viral**: lihat bagian di atas.
- **Lagi ramai dicari**: pencarian yang sedang naik di Google Trends (AS, Inggris, Kanada, Australia, atau Indonesia). Tiap topik diberi label niche dan perkiraan CPM-nya. Topik tragedi/bencana ditandai "Hindari" karena iklannya dibatasi.
- **Buat ide topik**: AI menggabungkan tren hari ini dengan niche CPM tinggi, lalu memberi hook pembuka dan kata kunci untuk mencari video sumber.
- **Cari video sumber**: pencarian YouTube dengan filter lisensi Creative Commons, periode unggah, durasi, dan urutan. Tombol **Pakai video ini** langsung mengisi Studio.

**Buat video**, **Edit & animasi**, dan **Posting**: lihat bagian-bagian di atas.

**Klip saya** menampilkan semua klip yang pernah dibuat. **Pengaturan** berisi penyedia AI, model, model cadangan, cookies browser untuk YouTube, kunci API tambahan (Gemini untuk suara/gambar/video, Pexels, YouTube Data API), dan pemeriksaan sistem.

### Catatan monetisasi

- Kisaran CPM di aplikasi berasal dari data vidIQ 2026 untuk **video panjang**. Pendapatan Shorts per tayangan jauh lebih kecil, jadi angka itu hanya untuk membandingkan niche.
- Memotong video orang lain tanpa izin berisiko kena klaim hak cipta, dan YouTube umumnya tidak memonetisasi konten pakai-ulang tanpa tambahan orisinal. Pilihan paling aman: video Anda sendiri, video yang Anda punya izinnya, atau video berlisensi **Creative Commons (CC BY)**. Untuk video CC BY, kredit sumber ditambahkan otomatis di `RINGKASAN.md` dan di caption pada web app; cantumkan kredit itu saat mengunggah.

## Penyedia AI

Atur di tab Pengaturan, atau di file `.env` (salin dari `.env.example`).

| Pilihan | Biaya | Catatan |
|---|---|---|
| `gemini` (default) | Ada kuota gratis | Bila model sibuk (503), agen pindah ke model cadangan |
| `openrouter` | Ada model gratis (`:free`) | Wajib isi model |
| `ollama` | Gratis, offline | Butuh RAM ±8 GB; `ollama pull qwen2.5:7b` |
| `anthropic` | Berbayar | Model Claude |
| `groq`, `openai` | Bervariasi | |
| `heuristic` | Gratis, tanpa AI | Memilih bagian dengan bicara paling padat; tanpa judul/caption, tanpa terjemahan |

## Perintah terminal

```bash
# Klip untuk penonton AS, subtitle Inggris, animasi bounce + zoom
python clipper.py "https://youtu.be/XXXX" --audience us --sub-lang en --anim bounce --zoom punch

# 3 klip maks. 45 detik dengan arahan untuk agen
python clipper.py "https://youtu.be/XXXX" -n 3 --max 45 --instructions "fokus pada tips investasi"

# Tinjau dulu, edit output/<id>/plan.json, lalu render
python clipper.py "https://youtu.be/XXXX" --plan-only
python clipper.py "https://youtu.be/XXXX" --plan output/<id>/plan.json

# File video lokal tanpa AI
python clipper.py rekaman.mp4 --provider heuristic
```

Opsi gaya: `--anim`, `--font`, `--text-color`, `--color` (sorotan), `--words`, `--position`, `--no-uppercase`, `--no-hook`, `--progress-bar`, `--zoom punch`, `--aspect`, `--crop`. Lihat semuanya dengan `python clipper.py -h`. Web app dijalankan dengan `python app.py` (opsi: `--port`, `-o`, `--no-browser`).

## Hasil

```
output/<id_video>/
├── source.mp4              video asli (cache)
├── transcript.json         transkrip per kata (cache)
├── translations_en.json    terjemahan subtitle (cache)
├── plan.json               daftar klip pilihan agen (bisa diedit)
└── clips/
    ├── 01_judul-klip.mp4   klip siap unggah
    ├── 01_judul-klip.srt   subtitle biasa (untuk CapCut/Premiere/platform)
    ├── 01_judul-klip.ass   subtitle beranimasi (yang ditanam ke video)
    └── RINGKASAN.md        judul, hook, alasan, caption, hashtag, kredit
```

## Pemecahan masalah

- **"Sign in to confirm you're not a bot"**: di Pengaturan, pilih cookies browser (Firefox paling andal), atau di terminal tambahkan `--cookies-from-browser firefox`.
- **Gagal unduh / format tidak tersedia**: perbarui yt-dlp dengan `pip install -U "yt-dlp[default]"` dan pastikan Deno terpasang. YouTube sering berubah.
- **HTTP 503 / 429 dari AI**: agen otomatis mencoba ulang lalu pindah ke model cadangan. Jika semua gagal, klip tetap dibuat dengan mode heuristic. Jalankan ulang nanti; video dan transkrip tidak diunduh ulang.
- **Google Trends tidak bisa dimuat**: periksa koneksi. Ide topik dan niche CPM tinggi tetap bisa dipakai.
- **Video tanpa subtitle**: perlu Whisper (`pip install -r requirements-whisper.txt`). Pemakaian pertama mengunduh model (±500 MB untuk `small`).
- **Dua orang berjauhan di layar**: pakai pembingkaian "Video utuh dengan latar blur".
- **"Remotion belum siap" di tab Edit & animasi atau Buat video**: pasang Node.js (`winget install OpenJS.NodeJS.LTS`), tutup lalu jalankan ulang `start.bat`. Bisa juga manual: `cd remotion` lalu `npm install`.
- **"Kuota Gemini untuk gambar = 0" atau HTTP 429 saat membuat visual**: paket gratis Gemini API tidak memberi kuota untuk model pembuat gambar (dan video AI). Aktifkan billing (Tier 1) di aistudio.google.com pada project yang sama dengan API key; biayanya dihitung per gambar. Tanpa billing, pilih visual **Video stok (Pexels)** atau **Kartu teks**. Clip Agent otomatis berhenti memanggil model gambar setelah kuota habis dan memakai video stok (bila Pexels API key diisi) atau kartu teks untuk sisa adegan. Batas per menit ditunggu otomatis; kuota harian direset tengah malam waktu Pasifik (sekitar pukul 14.00–15.00 WIB).
- **Suara narasi gagal**: dengan Gemini, cek API key dan kuota. Model TTS bisa diganti di Pengaturan > Model lanjutan. Tanpa key, pasang suara gratis: `pip install edge-tts`, lalu pilih mesin suara Edge.
- **YouTube: "Izin kedaluwarsa"**: tambahkan ulang channel itu di tab Posting. Ini terjadi tiap 7 hari selama aplikasi OAuth masih berstatus Testing.
- **YouTube: "Error 403: access_denied"**: email akun Google yang dipakai login belum ada di Test users (Google Auth Platform → Audience). Tambahkan email itu, atau klik Publish app.
- **TikTok: "unaudited_client_can_only_post_to_private_accounts"**: aplikasi TikTok belum diaudit. Set akun TikTok ke privat dan pilih privasi "Hanya saya", pakai mode Kirim ke draf, atau ajukan audit.
- **TikTok: login gagal / redirect_uri tidak cocok**: daftarkan Redirect URI persis `http://127.0.0.1:*/oauth/tiktok/` di Login Kit (platform Desktop). Bila token tetap ditolak, coba tambahkan `TIKTOK_PKCE_ENCODING=base64url` di `.env`.
- **Meta: "token kedaluwarsa"**: buat token baru di Graph API Explorer. Isi App ID dan App Secret agar token jangka panjang.
- **Remotion gagal mengunduh browser**: render pertama mengunduh Chrome Headless Shell (±90 MB). Bila jaringan memblokirnya, arahkan ke Chrome yang sudah ada lewat `.env`: `REMOTION_BROWSER_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`.

## Lisensi komponen

Pustaka QR `segno` berlisensi BSD. Font di `fonts/` dan `remotion/public/fonts/` berlisensi SIL Open Font License 1.1 (lihat file `OFL-*.txt`), kecuali Special Elite dan Permanent Marker yang berlisensi Apache 2.0 (`LICENSE-*.txt`). Peta memakai data Natural Earth (domain publik) lewat paket `world-atlas`, `topojson-client`, dan `d3-geo` (lisensi ISC). Remotion memakai Remotion License: gratis untuk perorangan dan perusahaan dengan maksimal 3 karyawan. Model deteksi wajah YuNet (`models/`) berasal dari OpenCV Zoo (lisensi MIT).
