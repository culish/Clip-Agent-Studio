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
4. **Visual per adegan**: gambar tema (gratis, lihat di bawah), gambar AI (dengan karakter Anda), video stok (Pixabay/Pexels), kartu teks, atau video AI. Video AI memakai Gemini Omni Flash, berbayar sekitar US$0,10 per detik 720p, dan baru dipakai bila **Izinkan video AI berbayar** dicentang. Perkiraan biayanya tampil sebelum dibuat.
5. **Musik, caption, render**: musik bawaan atau file Anda, caption karaoke, dirender dengan Remotion.

**Siapkan suara & gambar** membuat aset per adegan agar bisa dicek (ada pemutar suara dan gambar kecil per adegan). Aset disimpan, jadi **Buat video** hanya membuat ulang adegan yang berubah. Hasil ada di `output/_projects/<id>/`.

### Tema video (stickman, lofi, dongeng, berita data, dan lainnya)

Saat membuat proyek, pilih **Tema video**. Tema mengatur format naskah yang ditulis AI, gaya suara narator, musik, caption, judul, dan visual tiap adegan sekaligus. Visual tema **digambar langsung oleh Remotion sebagai grafis bergerak**, jadi gratis dan tidak butuh API gambar. Bila ada Gemini API key, ganti *Visual default* ke **Gambar AI** untuk ilustrasi AI dengan gaya tema yang sama; efek seperti hujan, kunang-kunang, dan kilat tetap dipasang di atasnya.

| Tema | Visual | Cocok untuk |
|---|---|---|
| ✏️ Stickman | Stickman tangan di kertas putih: 12 pose, 33 benda (matahari, uang, grafik, jam, lampu ide...), tulisan spidol | Penjelasan sains, psikologi, uang, tips |
| 🌧️ Cerita lofi | Kamar malam dengan hujan di jendela, jalan basah, atap kota, di dalam bus; lampu hangat, butiran film | Monolog pelan soal perasaan sehari-hari |
| 🦌 Dongeng malam | Bulan purnama, bukit, danau, desa, laut; rusa, kelinci, burung hantu, rubah, kura-kura; kunang-kunang | Dongeng dengan pesan moral |
| 🗺️ Berita data | Peta bertitik (koordinat asli), angka besar yang menghitung naik, grafik batang, judul ala koran | Jurnalisme data; AI hanya memakai angka dari bahan riset |
| 🚪 Pilih pintu | Tiga pintu bernomor, pilihan di bawahnya, hitung mundur 3-2-1, pintu jawaban terbuka | Teka-teki dan tes pilihan yang memancing komentar |
| 📼 Kaset cerita | Nenek/kakek/ibu/ayah dengan balon kata, kaset dengan pita berputar, gelombang suara yang mengikuti narasi | Nasihat dan kenangan, nostalgia |
| 🌅 Senja minimalis | Matahari retro, laut, perahu nelayan, siluet, burung, sepeda | Kisah inspiratif dan filosofi |
| ⛈️ Misteri malam | Awan badai, kilat, hujan, kabut, rumah tua, menara, jalan sepi | Misteri dan legenda (disajikan sebagai legenda, bukan fakta) |

Setiap adegan punya kolom gambar tema yang bisa diubah di editor (pose dan benda stickman, tempat dan waktu lofi, titik peta, pilihan pintu, dan seterusnya). Musik bawaan bertambah dua: **Lo-fi hujan** (diredam, bunyi piringan hitam dan hujan) dan **Dongeng** (kotak musik). Tema bisa diganti kapan saja dari pengaturan proyek.

### Motion AI: video animasi yang kodenya ditulis Claude

Pilih kartu **✨ Motion AI** saat membuat proyek (atau *Visual default: Motion AI* di pengaturan proyek, bisa juga per adegan). Hasilnya seperti saat meminta Claude membuat video motion graphics dengan HTML + GSAP (HyperFrames) atau Remotion, tetapi langsung jadi MP4 tanpa menyalin kode:

1. AI menulis naskah yang tiap adegannya punya satu poin yang bisa divisualkan (angka, daftar, perbandingan, proses).
2. Narasi dibuat dulu, sehingga waktu tiap kata diketahui.
3. AI menulis HTML, CSS, dan timeline animasi untuk setiap adegan: tipografi bergerak, ikon dan ilustrasi SVG, penghitung angka, grafik, diagram. Setiap elemen muncul tepat saat kata itu diucapkan (`S.at("kata")`).
4. Clip Agent merender satu gambar per adegan di browser render untuk mengujinya: galat kode, layar kosong, serta teks yang bertumpuk atau terpotong dikirim balik ke AI untuk diperbaiki. Bila perbaikan gagal, adegan memakai animasi cadangan, jadi video tetap jadi.
5. Semua adegan dirender dengan Remotion bersama suara, musik, transisi, dan caption (caption mati secara bawaan karena teks sudah dianimasikan).

**Penulis kode**: *Otomatis* memakai **Claude lewat Claude Code** bila perintah `claude` terpasang dan sudah login (memakai kuota langganan Claude Anda, tanpa API key, tanpa alat apa pun selain menulis teks), selain itu AI di Pengaturan (Gemini gratis, OpenRouter, Claude API, dll.). Bisa juga dipilih **Codex CLI**, **Gemini CLI** (gratis dengan akun Google), **Qwen Code**, atau **opencode**. Penulis selain Claude diberi dua adegan rujukan yang ditulis Claude (`clipagent/motion_examples.json`) sebagai standar kualitas, dan semua hasil melewati uji render, pemeriksaan teks bertumpuk, perbaikan otomatis, dan animasi cadangan yang sama. **Gaya**: 8 sistem desain (bersih minimal, teknologi gelap, pop berani, editorial koran, pastel lembut, neon malam, profesional, coretan tangan) yang mengatur warna dan huruf; kolom *Arahan animasi* di tiap adegan bisa diisi untuk mengarahkan tata letak.

Setelah **Siapkan suara & gambar**:

- **Putar animasi di browser**: pratinjau cepat dengan narasi, bisa digeser per detik.
- **Unduh HTML animasi**: satu file HTML mandiri (font dan suara di dalamnya) yang bisa dibuka di browser mana pun, diedit, atau dibagikan, seperti artifact Claude.
- **Salin blueprint untuk Claude**: prompt lengkap (aturan, sistem desain, naskah, waktu tiap kata) untuk ditempel di claude.ai bila ingin mengerjakan bersama Claude secara langsung.
- **Tulis ulang semua animasi**: minta versi baru. Kode disimpan per adegan, jadi mengubah satu adegan hanya menulis ulang adegan itu.

Animasi dijalankan **MotionKit** (`remotion/src/motionkit.js`), mesin timeline bergaya GSAP yang ditulis khusus untuk Clip Agent (bukan GSAP; lisensi GSAP tidak mengizinkan alat pembuat animasi tanpa kode). Kode AI berjalan terpisah: tidak boleh memakai jaringan, timer, atau `Math.random`, halaman ekspor dikunci dengan Content-Security-Policy, dan server Clip Agent menolak permintaan POST dari halaman lain.

### Karakter (Character Studio)

Buat karakter sekali (nama, persona, penampilan, gaya gambar, suara), lalu unggah gambar referensi atau klik **Buat dengan AI** dan pilih satu dari tiga gambar. Gambar referensi ikut dikirim ke AI setiap kali adegan digambar, sehingga wajah, rambut, dan pakaian tetap sama di semua video. Pilih karakter saat membuat proyek; suara karakter otomatis dipakai.

### Catatan agar tetap bisa dimonetisasi

Sejak Juli 2025 YouTube tidak memonetisasi konten "inauthentic": video massal yang mirip satu sama lain, atau konten orang lain yang diulang tanpa nilai tambah. Karena itu Clip Agent menulis naskah baru dan mengukur kemiripannya. Tetap tambahkan sudut pandang Anda sendiri (kolom **Sudut pandang / arahan**), variasikan format, dan jangan mengunggah puluhan video yang hampir sama.

## Layout streaming, reaction, dan podcast

Di Studio, bagian **Efek video → Layout**, pilih susunan klip vertikal (9:16 atau 4:5):

| Layout | Susunan | Cocok untuk |
|---|---|---|
| Satu layar | Seperti biasa, ikuti Pembingkaian | Vlog, podcast satu orang |
| Streaming/gameplay | Facecam di atas, game di bawah | Live stream GTA, Resident Evil, dan game lain |
| Reaction | Video yang ditonton utuh di atas, wajah di bawah | Video reaction |
| Facecam kecil di pojok | Game memenuhi layar, facecam di pojok atas | Gameplay yang butuh layar penuh |
| Podcast 2 orang | Dua wajah ditumpuk atas-bawah | Podcast, wawancara |

Facecam dicari otomatis: wajah yang posisinya tetap di banyak frame dianggap facecam (wajah karakter game yang muncul sesekali diabaikan), dan tepi kotak facecam dibaca dari garis yang menetap sehingga gameplay tidak ikut masuk ke panel wajah. Game di panel bawah digeser agar facecam tidak ikut terpotong; di layout Reaction, facecam di video atas diburamkan agar wajah tidak muncul dua kali. Caption otomatis diletakkan di garis batas dua panel.

Hasil deteksi bisa diatur per klip di tab **Kreatif → Layout klip**: geser kotak *Facecam / wajah* dan *Video utama* di frame, tarik pojok kanan-bawah untuk mengubah ukuran, atur tinggi panel wajah, lalu lihat pratinjaunya sebelum **Render ulang klip**. Pengaturan itu disimpan dan dipakai lagi saat klip dirender ulang.

Setelah klip jadi, layout bisa diubah dengan dua cara:

- **Satu layout untuk seluruh klip.** Centang **Pakai juga untuk semua klip video ini** untuk merender ulang semua klip dari video yang sama dengan kotak facecam dan video utama yang sama (cocok untuk stream yang posisi facecam-nya tetap).
- **Ganti layout per bagian (pilih frame).** Geser penggeser waktu (atau ±1 frame) ke titik layout harus berganti, klik **Pisah di frame ini**, lalu pilih layout untuk bagian itu. Contoh: satu layar saat membuka, streaming saat gameplay, facecam di pojok saat adegan penting. Caption ikut pindah ke garis batas panel di setiap bagian, dan bagian-bagian ini ikut bergeser bila awal klip diubah di **Cek frame & durasi**.

## Video kolase editorial (tab Kolase)

Dari satu voice-over menjadi video explainer bergaya kolase: foto arsip hitam-putih yang digunting dan ditempel, dokumen yang distabilo tepat saat kata itu diucapkan, peta, tipografi besar, angka yang berhitung naik, garis waktu, perbandingan, dan diagram alur. Efek suara (kertas, stempel, spidol, ketikan, transisi) disintesis sendiri dan jatuh tepat di animasinya; musik otomatis mengecil saat ada suara.

1. **Proyek baru**: unggah file VO (MP3/WAV/M4A), atau tulis narasi untuk dibacakan suara AI (Edge gratis / Gemini). Pilih format (9:16, 16:9, 1:1, 4:5), tema warna, dan sumber foto: foto stok gratis (Pixabay/Pexels bila key diisi, Openverse tanpa key), gambar AI Gemini (berbayar; subjek otomatis digunting dari latar putih), atau tanpa foto.
2. **Storyboard**: transkrip per kata dengan Whisper (`pip install -r requirements-whisper.txt`), lalu AI memilih tata letak tiap adegan. Angka, tahun, dan negara hanya tampil bila benar-benar diucapkan di VO; kalau tidak, adegan diganti tipografi. Tanpa penyedia AI, storyboard dibuat dengan aturan sederhana.
3. **Ubah** tata letak, judul layar, kata yang distabilo, deskripsi foto, atau isi garis waktu/alur bila perlu.
   - **Foto sendiri**: di adegan foto, klik *Salin prompt AI*, buat gambarnya di generator apa saja (Google Flow, ChatGPT, Midjourney), lalu *Unggah foto sendiri*. Gambar berlatar putih polos otomatis digunting; foto biasa dipakai sebagai foto tempel. Foto unggahan tidak pernah diganti saat render.
   - **Pratinjau gambar adegan**: satu gambar diam per adegan dalam hitungan detik, untuk dicek sebelum render penuh.
4. **Render cuplikan** 12 detik dari adegan mana pun untuk cek gerak dan suara, lalu **Render video**. Setiap render penuh menjadi versi baru (v1, v2, ...), berisi video final, versi tanpa musik, file WAV terpisah (narasi, efek suara, musik), lembar tinjau per adegan, catatan kreatif (daftar adegan dan fakta yang perlu dicek), serta pemeriksaan durasi dan loudness (target -14 LUFS). Video langsung muncul di tab Posting.

Tema warna: Kertas koran, Sepia, Cetak biru, Hijau lumut, Arsip, Laut, Hutan, Jingga, Ungu, Malam. Gaya huruf: *Editorial* (Playfair Display, Anton, Special Elite, Permanent Marker) atau *Klasik* (Fraunces, Archivo Black, Caveat, Plus Jakarta Sans). Efek suara bawaan bisa diganti sampel Anda sendiri lewat folder `sfx/` (lihat `sfx/BACA-SAYA.txt`).

Agent tidak bisa mendengar: dengarkan sendiri hasilnya sebelum mengunggah, periksa fakta yang tampil di layar (daftarnya ada di bawah video), dan nyalakan label konten AI bila memakai gambar atau suara AI.

### Paket Kolase Editorial (lokal)

Bila Anda membeli paket "Kolase Editorial" dan memasangnya di komputer, isi lokasi foldernya di tab Kolase (bagian *Paket Kolase Editorial (lokal)*) atau `KOLASE_PAKET_DIR` di `.env`. Di setiap proyek muncul tombol **Siapkan proyek paket**: Clip Agent menjalankan skrip paket untuk membuat proyek dari VO yang sama, menjalankan transkripnya, lalu memberi perintah yang tinggal disalin ke AI agent Anda (Claude Code, Codex, Gemini CLI, dan sejenisnya). Video di folder `hasil/` proyek paket otomatis muncul di tab Kolase dan Posting. Isi paket tetap di komputer Anda dan tidak pernah disalin ke repo ini, sesuai lisensinya.

## Media stok gratis (Pixabay, Pexels, Openverse)

Pexels sedang menghentikan sementara pembuatan API key baru. Clip Agent memakai beberapa penyedia secara berurutan; yang tidak punya key dilewati:

| Penyedia | Untuk | Key | Catatan |
|---|---|---|---|
| Pexels | video + foto | `PEXELS_API_KEY` | Hanya bila Anda sudah punya key lama |
| Pixabay | video + foto | `PIXABAY_API_KEY` | Daftar gratis di pixabay.com, key ada di pixabay.com/api/docs. Batas 100 permintaan per menit |
| Openverse | foto saja | tidak perlu | Hanya lisensi CC0, Domain publik, dan CC BY. Kredit (judul, pembuat, lisensi, tautan) otomatis masuk ke deskripsi video; untuk CC BY ini wajib |

Video stok untuk b-roll (Buat video, Edit otomatis) butuh Pixabay atau Pexels. Foto stok untuk tab Kolase sudah jalan tanpa key lewat Openverse; isi Pixabay key agar pilihan fotonya lebih banyak. Matikan Openverse dengan `OPENVERSE_ENABLED=0`.

## Reels viral: 11 format faceless (tab Film)

Mode **🎬 Reels viral** di tab Film membuat reel vertikal (Reels, Shorts, TikTok, Facebook) dalam beberapa menit, seperti layanan pembuat reel faceless. Pilih asal ceritanya: **tautan** (artikel, produk, aplikasi, atau video YouTube), **topik**, **naskah sendiri** (kata-katanya dipakai, hanya dipotong per adegan), atau **lagi ramai** (Google News, Google Trends, Hacker News, dan YouTube bila ada `YOUTUBE_API_KEY`). Lalu pilih format, durasi 15/30/45/60 detik, suara, bahasa, dan penulisnya. Hasilnya MP4 dengan suara, caption, musik, serta judul, deskripsi, dan hashtag yang tinggal disalin. Setiap reel juga menjadi proyek di **Buat video** untuk diedit per adegan.

| Format | Tampilan | Cocok untuk |
|---|---|---|
| 🧑‍🏫 Cartoon Host | Presenter kartun (berkedip, mulut bergerak mengikuti narasi) di depan papan berisi kata kunci, ikon, dan angka | Cerita, fakta unik, penjelasan ringan |
| ✍️ Whiteboard | Tangan memegang spidol menggambar ikon dan menulis label sambil narasi berjalan | Penjelasan, sains, cara kerja |
| 🕺 Stickman | Dua tokoh stickman memerankan ceritanya (tema Stickman) | Situasi sehari-hari, dua sisi |
| 🥊 Proof Punch | Kutipan asli dan sumbernya, stempel besar mendarat di kata kunci, lalu stempel kesimpulan | Klaim yang butuh bukti |
| 📰 News brief | Label TERKINI/LIVE, judul berita, fakta kunci dengan angka berjalan, ticker di bawah, halaman sumber samar di latar | Berita minggu ini, peluncuran |
| 📱 Phone in hand | Tangkapan layar halaman asli di ponsel yang dipegang dan digulir, dengan keterangan yang muncul | Aplikasi, situs, produk, promo |
| 💬 Text story | Obrolan chat, dua suara bergantian (pria dan wanita), indikator mengetik | Reaksi "Serius?", mitos vs fakta |
| 🅰️ Bold text | Kata-kata besar di warna kuat, muncul tepat saat diucapkan | Satu klaim yang menghentak |
| 🎞️ Text on video | Video stok yang tenang, kata menyala saat dibaca, tanpa suara, hanya musik | Kutipan, motivasi |
| ❓ One-liner | Satu pertanyaan besar dan ajakan berkomentar | Polling, opini |
| 🔢 Countdown | Daftar 3 teratas dihitung mundur sampai nomor satu | Alat terbaik, tips teratas |

**Hasil yang sama siapa pun penulisnya.** AI hanya menulis isi dalam bentuk data (kalimat narasi, judul papan, ikon, kutipan, urutan); tampilan dan gerak setiap format adalah template animasi yang sudah ditulis tetap (`clipagent/reels_tpl/`, dijalankan MotionKit di Remotion). Isinya juga diperiksa sebelum dirender: panjang narasi sesuai durasi, kait di adegan pertama, ikon yang valid, urutan 3-2-1 di Countdown, dan **kutipan Proof Punch harus benar-benar ada di sumber** (bila tidak, AI diminta memperbaiki; kutipan yang tetap tidak cocok diganti kalimat asli yang paling mirip atau dibuang). Setiap prompt menyertakan contoh tulisan untuk format itu sebagai standar.

**Penulis isi:** *Otomatis* (AI di Pengaturan, lalu agen yang terpasang), **AI di Pengaturan** (Gemini gratis, OpenRouter, Groq, Ollama, Claude API, dll.), atau agen coding di komputer Anda yang dipakai lewat login/langganan masing-masing tanpa API key:

| Agen | Perintah | Akun |
|---|---|---|
| Claude Code | `claude` | Langganan Claude atau API key |
| Codex CLI | `codex` (`npm i -g @openai/codex`, lalu `codex login`) | Langganan ChatGPT atau API key OpenAI |
| Gemini CLI | `gemini` (`npm i -g @google/gemini-cli`, lalu login dengan akun Google) | Gratis dengan batas harian |
| Qwen Code | `qwen` (`npm i -g @qwen-code/qwen-code`) | Akun Qwen atau API key yang didukung |
| opencode | `opencode` (`npm i -g opencode-ai`) | Model pilihan Anda, termasuk model gratis |

Tangkapan layar Phone in hand dan News brief memakai browser yang sama dengan Remotion. Format yang butuh tautan (Phone in hand) atau sumber berisi teks (Proof Punch) diberi tanda di galerinya.

## Film bergaya: 99 gaya Lemo-Opuscar (tab Film)

Mode **🎞️ Film 99 gaya** di tab **Film** membuat film pendek dalam salah satu dari 99 gaya [Lemo-Opuscar](https://github.com/lemomo-ai/lemo-opuscar) karya Lemomo (LemoLab): cat air, ukiyo-e, papan tulis, stickman, pixel RPG, berita, peta 3D, dan lainnya. Library itu dibuat untuk agen coding: agen di komputer Anda (**Claude Code**, atau penggantinya **Codex CLI**, **Gemini CLI**, dan **Qwen Code**) menulis treatment, menggambar setiap frame dengan kode, mengisi suara, membuat musik, me-mix, lalu memeriksa hasilnya. Clip Agent mengatur semuanya dari satu formulir: pilih gaya, tulis topik, pilih durasi dan format (16:9, 9:16, 4:5, 1:1), bahasa dan narator, lalu lampirkan bahan sendiri bila ada (foto, logo, musik, rekaman suara).

- **Agen:** pilih di Pengaturan agen. Claude Code memakai plugin library langsung; Codex (`codex exec`), Gemini CLI, dan Qwen Code membaca panduan yang sama (`AGENTS.md` dan skill library) dan bekerja dengan langkah yang sama. Hasil paling konsisten biasanya dari Claude Code dan Codex; Gemini CLI gratis dengan akun Google.
- **Yang dibutuhkan:** agen pilihan terpasang dan sudah login (perintahnya jalan di terminal), Node.js 20+, ffmpeg 7+, Python 3.11+ atau uv, dan git (di Windows: Git for Windows untuk Git Bash). Tab Film memeriksa semuanya dan menulis cara memperbaiki yang kurang.
- **Pasang library** dari tab itu: Clip Agent mengunduh library ke `~/lemo-opuscar` (bisa diganti) memakai skrip pemasang library itu sendiri, lalu memasang paket rendernya. Paket suara dan musik dipasang agen bila filmnya butuh.
- **Membuat film** memakan sekitar 30–60 menit dan kuota Claude Anda; Clip Agent menjalankan Claude Code tanpa pengawasan (`claude -p` dengan skill lemo-opuscar, effort high), menampilkan kemajuan dan langkahnya, dan bisa dibatalkan. Film berjalan di antrean sendiri, jadi Studio dan tab lain tetap bisa dipakai. Pengguna API key bisa memasang batas biaya per film.
- **Izin:** agen menjalankan perintah (Node, ffmpeg, Python, pemasangan paket) dan menulis file di folder film dan library. Anda harus mencentang izin ini sekali di Pengaturan agen.
- **Revisi:** tulis catatan, dan agen melanjutkan sesi yang sama dan hanya mengubah yang diminta.
- **Hasil:** folder proyek di `output/_film/<nama>/` berisi film MP4, poster, subtitle, `TREATMENT.md`, `CREDITS`, dan sumber dengan `build.sh`. Filmnya langsung muncul di Posting.
- Gaya bertanda ✦ (Manga Panels, Text Flash Cuts, Comic History Cartoon) menggambar tokohnya dengan generator gambar milik Anda sendiri (mis. Codex CLI); tanpa itu filmnya tidak bisa dimulai. Narasi bahasa Indonesia memakai suara edge-tts dan butuh internet.

Clip Agent **tidak menyertakan** isi library itu; library diunduh ke komputer Anda dari repo resminya. Panduan dan prompt gayanya berlisensi CC BY-NC 4.0, kodenya MIT. Film yang Anda buat sepenuhnya milik Anda, termasuk untuk komersial, tanpa wajib mencantumkan kredit; aset pihak ketiga di dalamnya mengikuti lisensinya masing-masing (lihat `CREDITS` tiap film). Lihat [LICENSE library](https://github.com/lemomo-ai/lemo-opuscar/blob/main/LICENSE).

## Animasi 3D "cara kerja": Blender (tab Film)

Mode **🧊 Animasi 3D · Blender** di tab **Film** membuat video edukasi 3D seperti septic tank dibelah, kolam renang dikuras, rem cakram, atau mesin yang dibongkar. Alurnya mengikuti pola video 3D engineering yang sering viral:

1. **Riset dan bedah.** Mulai dari topik, naskah sendiri, atau tautan video YouTube/TikTok atau artikel rujukan. AI memetakan *hook*, masalah, langkah solusi teknik, dan CTA rujukan, lalu menulis naskah baru dengan sudut pandang sendiri.
2. **Naskah dan production plan.** Rumusnya Hook (satu kalimat) → Masalah → Solusi teknik langkah demi langkah → CTA yang mengundang komentar. Tiap adegan punya narasi, aksi visual 3D, daftar objek, kamera, efek suara, dan label di layar. Tombol **Buat naskah dulu** menampilkan tabel ini sebelum merender; naskahnya bisa diedit per adegan di **Buat video**.
3. **QC naskah.** Panjang hook, urutan struktur, tempo kata per detik terhadap durasi target, istilah teknis yang rawan salah dibaca suara AI (dieja fonetik khusus untuk suara, mis. PVC → "pe-ve-ce", sedangkan caption tetap ejaan asli), dan kemiripan dengan rujukan agar tidak dianggap konten duplikat.
4. **Suara dan musik.** Narasi memakai suara Gemini atau Edge (gratis). Musik latar dibuat generator bawaan sesuai suasana video dan otomatis mengecil saat narasi.
5. **Kode Blender.** Penulis yang dipilih (Claude Code bila terpasang, atau Codex, Gemini CLI, Qwen Code, opencode, atau AI di Pengaturan) menulis fungsi `build(k)` untuk tiap adegan memakai kit `clipagent/anim3d_kit/kit.py`: tangki berongga, dinding, pipa, roda gigi, pegas, label infografis, panah, potongan penampang (cutaway), air yang naik/turun, partikel yang mengalir atau mengendap, tampilan urai, dan gerak kamera yang disinkronkan ke kata-kata narasi. Kode diperiksa aturan keamanannya (tanpa akses file, tanpa impor selain math/random/mathutils/bpy), diuji di Blender, dan diperbaiki otomatis bila error atau framenya kosong. Adegan yang tetap gagal diganti animasi cadangan agar video tetap jadi.
6. **Render dan gabung.** Blender di komputer Anda merender tiap adegan, lalu Remotion menggabungkannya dengan suara, caption, musik, dan transisi.

Pilihan render: **Cepat** (Workbench, hitungan detik per adegan), **Bagus** (EEVEE, butuh kartu grafis), atau **Terbaik** (Cycles, paling realistis dan paling lama), dengan resolusi 1080p, 720p, atau 540p untuk draf. Gaya visual: Studio terang, Cetak biru, atau Hangat. Rasio 9:16 atau 16:9. Video berbahasa Inggris biasanya mendapat RPM lebih tinggi.

**Yang dibutuhkan:** [Blender](https://www.blender.org/download/) 4.2 atau lebih baru (gratis). Clip Agent mencarinya di PATH dan lokasi pemasangan biasa (`C:\Program Files\Blender Foundation\…`, `/Applications/Blender.app`, `/usr/bin/blender`); bila dipasang di tempat lain, isi lokasinya di kotak Blender pada mode ini. Naskah bisa dibuat tanpa Blender. Pilihan visual **Animasi 3D (Blender)** juga ada per adegan di **Buat video**.

## Kanal: naskah, judul, SEO, Shorts, retensi (tab Kanal)

Tab **Kanal** memasang seluruh [youtube-agent-skill](https://github.com/jakeschincariol/youtube-agent-skill) (MIT, Jake Schincariol): sebelas skill beserta alat Python-nya, dijalankan langsung oleh Clip Agent. Skor dan angka dihitung oleh alatnya (bukan dikarang AI), dengan kosakata bahasa Indonesia tambahan (kata pengisi seperti *eh, jadi, nah*; kata kabur seperti *luar biasa, gila*; sapaan *kamu, lo, kalian* dan akhiran *-mu*; 21 rumus hook versi Indonesia).

| Alat | Skill | Yang Anda dapat | Tambahan di Clip Agent |
|---|---|---|---|
| Naskah video | yt-script | 5 hook dari 21 rumus, dinilai, lalu naskah per beat dengan catatan layar | Naskah ucapannya bisa langsung dijadikan video **Kolase** (suara AI) |
| Judul & thumbnail | yt-package | 10 pasangan judul + teks thumbnail, dicek panjang, potongan di ponsel, kekaburan, duplikasi; brief thumbnail | Judul pemenang langsung ke **Posting** |
| Deskripsi & SEO | yt-seo | Dua baris pertama, tag secukupnya, 3 kueri yang diuji terhadap judul + dua baris pertama | Deskripsi dan tag langsung ke **Posting** |
| Bab video | yt-chapters | Bab dari transkrip, divalidasi dengan aturan YouTube (0:00, minimal 3, minimal 10 dtk) | Blok bab langsung masuk ke Deskripsi & SEO |
| Cari Shorts | yt-shorts | Momen 20–55 dtk yang berdiri sendiri + kalimat pembuka baru yang dinilai | **Render dengan Clip Agent**: momen itu langsung dipotong dengan gaya Studio Anda |
| Potong jeda & ulangan | yt-edit | Daftar potong: jeda kosong, kata pengisi, kalimat yang diulang | **Terapkan potongan ke video**: hasilnya video baru tanpa jeda, siap diposting |
| Baca retensi | yt-retention | Hook leak, cliff, slide dari CSV YouTube Studio, dan satu kebocoran terbesar | Kurva retensi interaktif + kalimat yang diucapkan di tiap cliff |
| Riset outlier | yt-viral | Video yang mengalahkan median channelnya sendiri + rumus judulnya | Daftar video diambil sendiri lewat yt-dlp (tanpa API key), bisa dari kata kunci; satu klik jadi naskah |
| Balas komentar | yt-comment | Komentar dipilah 4 kelompok, balasan di bawah 30 kata, yang perlu disematkan | Komentar diambil langsung dari URL video |
| Rencana mingguan | yt-plan | Jadwal yang muat di jam Anda | Memakai video yang sudah ada di Clip Agent sebagai bahan |
| Audit channel | yt-audit | Satu perbaikan terpenting, tiga hal yang sudah jalan | 10 video terakhir dibaca otomatis: skor judul, skor hook 15 dtk pertama, ritme upload, grid thumbnail ukuran feed |

Sumber transkrip bisa video di **Klip saya**, URL YouTube (subtitle diambil tanpa mengunduh video; Whisper bila tidak ada), file SRT/VTT, atau teks tempelan. **Profil suara** (`data/voice.md`) dibaca semua alat agar hasilnya terdengar seperti Anda; isi sendiri atau biarkan AI menyusunnya dari 1–3 video Anda. **Uji hook** dan **Cek judul** jalan tanpa AI. Judul di tab Posting juga dicek langsung saat diketik, dan setiap klip baru diberi skor kalimat pembuka dan skor judul (juga di `RINGKASAN.md`).

Seperti repo aslinya, tidak ada yang diposting otomatis dari tab ini. Alat yang menulis butuh penyedia AI (Gemini gratis cukup); Bab, Potong jeda, Retensi, dan Riset outlier tetap jalan tanpa AI, hanya tanpa ringkasan.

## Edit otomatis: b-roll, musik, caption

Di tab **Edit & animasi**, bagian **Edit otomatis** merender ulang klip yang sudah jadi:

- **B-roll**: AI memilih 2–5 momen (tidak di 2,5 detik pertama), lalu menyisipkan video stok (Pixabay/Pexels) yang cocok atau gambar AI.
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

## Cek frame dan atur panjang klip

Tiap klip hasil Auto clip punya tombol **Cek frame & durasi** (juga di **Klip saya** dan di tab **Kreatif**). Bagian ini memakai cara kerja [AutoClip](https://github.com/zhouxiaoka/autoclip) (lisensi MIT) yang diadaptasi untuk transkrip per kata Clip Agent:

- **Perpanjang atau pendekkan**: geser pegangan di garis waktu, ketik detiknya, atau pakai tombol −1 dtk / −1 frame / +1 frame / +1 dtk. Frame video sumber di titik awal dan akhir ikut diperbarui, dan tombol **3 dtk awal**, **3 dtk akhir**, serta **Lewat akhir** memutar potongannya dari video sumber sebelum dirender.
- **Klik kata untuk memotong**: kata-kata di sekitar awal dan akhir klip ditampilkan dengan garis potong. Kata yang terpotong ditandai merah bergelombang. Klik kata untuk memulai klip di kata itu, atau mengakhirinya setelah kata itu.
- **Rapikan ke kalimat** (tanpa AI): awal klip mundur ke awal kalimat utuh, akhir klip maju sampai kalimatnya selesai (paling jauh 20 dtk ke belakang dan 25 dtk ke depan), pertanyaan topik berikutnya di ujung klip dibuang, lalu kedua potongan ditempelkan ke jeda bicara di audio (ffmpeg silencedetect, atau celah antar kata bila audio penuh musik).
- **Rapikan dengan AI**: model AI membaca kalimat di sekitar klip dan memilih awal pertanyaan dan akhir jawaban. Jawaban yang tidak masuk akal (klip jadi terlalu pendek, atau melompat ke topik lain) diabaikan.
- **Render ulang klip** memakai crop, layout, subtitle, dan terjemahan yang sama, lalu menyimpan rentang baru ke `plan.json`. Rentang pilihan agen disimpan, jadi **Rentang asli** selalu bisa dipakai lagi.

**Cek frame** memeriksa klip hasil render dan menampilkan 12 frame contoh (frame pertama, frame terakhir, dan di antaranya). Frame yang bermasalah diberi tanda; klik frame atau waktunya untuk melompat ke titik itu.

| Pemeriksaan | Kapan ditandai |
|---|---|
| Awal / akhir kalimat | Kata masih tersisa lebih dari 80 md (terpotong di tengah kata), atau kata berikutnya mulai dalam 0,6 dtk padahal kalimatnya belum selesai |
| Potongan adegan | Ada pergantian shot dalam 0,75 dtk pertama/terakhir, sehingga beberapa frame shot lain "berkedip" di tepi klip. Sarannya memotong tepat di frame pergantian |
| Frame hitam / gambar beku | ffmpeg blackdetect dan freezedetect. Frame hitam di tepi bisa langsung dipotong |
| Wajah di bingkai | Wajah terpotong tepi bingkai, subtitle menutupi lebih dari 35% wajah, atau orang yang ada di video sumber tidak masuk crop |
| Getar gambar | Crop bolak-balik melompat lebih dari sekali per menit, atau gambar diam bergetar lebih dari 0,30 px |
| Keras suara | Di luar -14 LUFS ± 1 atau puncak di atas -1 dBTP. Tombol **Samakan keras suara** menormalkan audio tanpa merender ulang gambar |
| Durasi | Di luar batas durasi di pengaturan Studio |

Tiap masalah yang bisa diperbaiki dengan memotong punya tombol **Terapkan saran**: rentang baru dipasang di editor, Anda dengarkan dulu, lalu render ulang. Setelah render ulang, cek frame dijalankan lagi otomatis.

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

**Kanal**: lihat bagian di atas. **Klip saya** menampilkan semua klip yang pernah dibuat. **Pengaturan** berisi penyedia AI, model, model cadangan, cookies browser untuk YouTube, kunci API tambahan (Gemini untuk suara/gambar/video, Pixabay/Pexels, YouTube Data API), dan pemeriksaan sistem.

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
- **Klip buram / hanya 480p**: penyebab paling umum adalah Deno belum terpasang. Sejak yt-dlp 2025.11.12, tanpa Deno YouTube hanya memberi format terbatas (sering 360p/480p), apalagi bila memakai cookies browser. Pasang dengan `winget install DenoLand.Deno`, buka ulang terminal, jalankan ulang app, lalu buat ulang klipnya; video yang dulu terunduh beresolusi rendah akan diunduh ulang otomatis. Log job menulis resolusi sumber, dan kartu klip diberi tanda *Sumber 480p* bila sumbernya rendah. Kalau file klipnya sudah 1080x1920 tapi YouTube masih menampilkan 480p, tunggu: YouTube memproses versi HD beberapa menit sampai beberapa jam setelah upload.
- **Gagal unduh / format tidak tersedia**: perbarui yt-dlp dengan `pip install -U "yt-dlp[default]"` dan pastikan Deno terpasang. YouTube sering berubah.
- **HTTP 503 / 429 dari AI**: agen otomatis mencoba ulang lalu pindah ke model cadangan. Jika semua gagal, klip tetap dibuat dengan mode heuristic. Jalankan ulang nanti; video dan transkrip tidak diunduh ulang.
- **Google Trends tidak bisa dimuat**: periksa koneksi. Ide topik dan niche CPM tinggi tetap bisa dipakai.
- **Video tanpa subtitle**: perlu Whisper (`pip install -r requirements-whisper.txt`). Pemakaian pertama mengunduh model (±500 MB untuk `small`).
- **Dua orang berjauhan di layar**: pakai pembingkaian "Video utuh dengan latar blur".
- **"Remotion belum siap" di tab Edit & animasi atau Buat video**: pasang Node.js (`winget install OpenJS.NodeJS.LTS`), tutup lalu jalankan ulang `start.bat`. Bisa juga manual: `cd remotion` lalu `npm install`.
- **"Kuota Gemini untuk gambar = 0" atau HTTP 429 saat membuat visual**: paket gratis Gemini API tidak memberi kuota untuk model pembuat gambar (dan video AI). Aktifkan billing (Tier 1) di aistudio.google.com pada project yang sama dengan API key; biayanya dihitung per gambar. Tanpa billing, pilih visual **Video stok (Pexels/Pixabay)** atau **Kartu teks**. Clip Agent otomatis berhenti memanggil model gambar setelah kuota habis dan memakai video stok (bila Pixabay atau Pexels API key diisi) atau kartu teks untuk sisa adegan. Batas per menit ditunggu otomatis; kuota harian direset tengah malam waktu Pasifik (sekitar pukul 14.00–15.00 WIB).
- **Suara narasi gagal**: dengan Gemini, cek API key dan kuota. Model TTS bisa diganti di Pengaturan > Model lanjutan. Tanpa key, pasang suara gratis: `pip install edge-tts`, lalu pilih mesin suara Edge.
- **YouTube: "Izin kedaluwarsa"**: tambahkan ulang channel itu di tab Posting. Ini terjadi tiap 7 hari selama aplikasi OAuth masih berstatus Testing.
- **YouTube: "Error 403: access_denied"**: email akun Google yang dipakai login belum ada di Test users (Google Auth Platform → Audience). Tambahkan email itu, atau klik Publish app.
- **TikTok: "unaudited_client_can_only_post_to_private_accounts"**: aplikasi TikTok belum diaudit. Set akun TikTok ke privat dan pilih privasi "Hanya saya", pakai mode Kirim ke draf, atau ajukan audit.
- **TikTok: login gagal / redirect_uri tidak cocok**: daftarkan Redirect URI persis `http://127.0.0.1:*/oauth/tiktok/` di Login Kit (platform Desktop). Bila token tetap ditolak, coba tambahkan `TIKTOK_PKCE_ENCODING=base64url` di `.env`.
- **Meta: "token kedaluwarsa"**: buat token baru di Graph API Explorer. Isi App ID dan App Secret agar token jangka panjang.
- **Remotion gagal mengunduh browser**: render pertama mengunduh Chrome Headless Shell (±90 MB). Bila jaringan memblokirnya, arahkan ke Chrome yang sudah ada lewat `.env`: `REMOTION_BROWSER_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`.

## Lisensi komponen

Pustaka QR `segno` berlisensi BSD. Font di `fonts/` dan `remotion/public/fonts/` berlisensi SIL Open Font License 1.1 (lihat file `OFL-*.txt`), termasuk Fraunces, Caveat, Archivo Black, dan Plus Jakarta Sans, kecuali Special Elite dan Permanent Marker yang berlisensi Apache 2.0 (`LICENSE-*.txt`). Peta memakai data Natural Earth (domain publik) lewat paket `world-atlas`, `topojson-client`, dan `d3-geo` (lisensi ISC). Remotion memakai Remotion License: gratis untuk perorangan dan perusahaan dengan maksimal 3 karyawan. Model deteksi wajah YuNet (`models/`) berasal dari OpenCV Zoo (lisensi MIT). Folder `clipagent/ytkit/vendor/` berisi salinan utuh youtube-agent-skill (lisensi MIT, © 2026 Jake Schincariol, lihat `LICENSE` di folder itu). Folder `clipagent/autoclip/` berisi kode yang diadaptasi dari AutoClip (lisensi MIT, © 2024 AutoClip Team, lihat `LICENSE` di folder itu). Ikon antarmuka digambar dalam gaya [Lucide](https://lucide.dev) (lisensi ISC). Perapian UI/UX mengikuti panduan [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) (lisensi MIT).
