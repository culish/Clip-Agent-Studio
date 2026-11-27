"""Rapikan awal/akhir klip ke kalimat utuh dan jeda nyata di audio.

Diadaptasi dari AutoClip (backend/services/studio/boundaries.py, MIT, Copyright (c) 2024 AutoClip Team,
https://github.com/zhouxiaoka/autoclip). Aturannya sama dengan aslinya:

1. `sentence_bounds` (tanpa AI): bila baris transkrip memuat akhir kalimat, potong tepat di sana
   ("...tanggung jawab. Nah jadi" berhenti setelah "jawab."); bila tidak, perpanjang sampai baris yang
   menyelesaikan kalimatnya. Awal klip mulai di kalimat utuh pertama dengan cara yang sama. Jeda dihitung
   sebagai akhir kalimat hanya bila transkripnya tanpa tanda baca (mis. subtitle otomatis YouTube).
   Pertanyaan di ujung klip dibuang: itu topik berikutnya, bukan jawaban ini.
2. `refine_with_model` (bila ada model teks): tampilkan baris di sekitar kedua potongan dan biarkan model
   memilih di mana pertanyaan dimulai dan di mana jawabannya selesai. Pilihan model diperiksa dan
   dirapikan lagi oleh langkah 1; jawaban yang tidak masuk akal memakai hasil langkah 1.

Perbedaan dengan aslinya: baris AutoClip adalah subtitle tanpa waktu per kata, jadi waktu di dalam baris
ditaksir dari jumlah huruf. Clip Agent punya waktu per kata, jadi `Row` menyimpan kata-katanya dan
`_time_at` memakai waktu kata yang sebenarnya. Pencari jeda memakai ffmpeg silencedetect dan, bila audio
tidak punya jeda yang terbaca (mis. ada musik latar), celah di antara kata.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

TERMINAL = re.compile(r'[.?!。？！…」』"”]\s*$')
INNER_END = re.compile(r'[.?!。？！…]+["”」』]?(?=\s|$)|[。？！]')
PUNCT = re.compile(r'[.,?!。，？！、]')
QUESTION = re.compile(r'(\?|？|ですか|ますか|でしょうか|吗|呢)["”」』]?\s*$')
JA_END = re.compile(r'(です|ます|ました|でした|ございます|ません|でしょう|ですね|ますね|ですよ|ますよ)\s*$')
TRAILING_QUESTION_SEC = 20  # sejauh ini dari akhir klip dicari pertanyaan topik berikutnya
ANSWER_STUB_SEC = 12        # jawaban sesingkat ini setelah pertanyaan = pembuka topik berikutnya
PAUSE_SEC = 0.6
MAX_LEAD_SEC = 20      # awal klip boleh mundur sejauh ini untuk mencapai awal kalimat
MAX_TAIL_SEC = 25      # akhir klip boleh maju sejauh ini untuk menyelesaikan kalimat
CONTEXT_BEFORE, CONTEXT_AFTER = 40, 75
MODEL_MAX_EXTEND = 60  # model boleh memperpanjang akhir klip paling jauh sejauh ini


class Row(tuple):
    """(start, end, text) seperti baris subtitle AutoClip, ditambah waktu tiap kata di dalamnya."""

    def __new__(cls, start: float, end: float, text: str, marks: list[tuple[int, int, float, float]] | None = None):
        row = super().__new__(cls, (float(start), float(end), text))
        row.marks = marks or []          # (offset huruf awal, offset huruf akhir, detik awal, detik akhir) tiap kata
        return row


SilenceFinder = Callable[[float, float], list[tuple[float, float]]]


def rows_from_words(words, max_gap: float = 0.8, max_len: float = 9.0, max_chars: int = 140) -> list[Row]:
    """Baris transkrip dari daftar Word Clip Agent (dikelompokkan seperti transcript.group_segments)."""
    from ..transcript import group_segments
    rows = []
    for seg in group_segments(list(words), max_gap=max_gap, max_len=max_len, max_chars=max_chars):
        text, marks = "", []
        for w in seg.words:
            t = str(w.text).strip()
            if not t:
                continue
            if text:
                text += " "
            marks.append((len(text), len(text) + len(t), float(w.start), float(w.end)))
            text += t
        if text:
            rows.append(Row(seg.start, seg.end, text, marks))
    return rows


def punctuated(rows: list[Row]) -> bool:
    return bool(rows) and sum(bool(PUNCT.search(r[2])) for r in rows) >= len(rows) * 0.3


def ends_sentence(rows: list[Row], index: int, has_punct: bool | None = None) -> bool:
    text = rows[index][2]
    if index + 1 < len(rows) and rows[index + 1][2].lstrip().startswith('>>'):
        return True  # pergantian pembicara (>>) mengakhiri jawaban walau tanpa tanda baca
    if TERMINAL.search(text) or (JA_END.search(text) and not QUESTION.search(text)):
        return True
    if has_punct is None:
        has_punct = punctuated(rows)
    if has_punct:
        return index + 1 >= len(rows)
    return index + 1 >= len(rows) or rows[index + 1][0] - rows[index][1] >= PAUSE_SEC


def _inner_ends(text: str) -> list[int]:
    """Offset huruf tepat setelah tiap akhir kalimat di dalam `text` (bukan di ujungnya)."""
    return [m.end() for m in INNER_END.finditer(text) if text[m.end():].strip()]


def _time_at(row: Row, offset: int) -> float:
    s, e, text = row
    marks = getattr(row, "marks", None)
    if marks:
        for a, b, ws, we in marks:
            if offset <= a:
                return ws                 # potongan sebelum kata ini: kata dimulai di sini
            if offset <= b:
                return we if offset >= b else ws + (we - ws) * (offset - a) / max(b - a, 1)
        return marks[-1][3]
    return s + (e - s) * offset / max(len(text), 1)


def _index_at(rows: list[Row], t: float) -> int | None:
    for i, (s, e, _) in enumerate(rows):
        if s <= t < e or (i + 1 < len(rows) and e <= t < rows[i + 1][0]):
            return i
    return None


def _end_cut(rows: list[Row], last: int, end: float, has_punct: bool) -> tuple[int, int]:
    """(indeks baris, offset huruf) tempat kalimat yang melewati `end` selesai."""
    i = last
    while True:
        text = rows[i][2]
        if ends_sentence(rows, i, has_punct):
            return i, len(text)
        inner = _inner_ends(text)
        if inner:
            return i, inner[-1]
        if i + 1 < len(rows) and rows[i + 1][1] - end <= MAX_TAIL_SEC:
            i += 1
            continue
        return i, len(text)


def _drop_trailing_question(rows: list[Row], i: int, offset: int, first: int, has_punct: bool,
                            end_time: float) -> tuple[int, int]:
    """Berhenti sebelum topik berikutnya: pertanyaan dekat akhir yang hanya diikuti awal jawabannya."""
    for j in range(i, first, -1):
        if rows[j][0] < end_time - TRAILING_QUESTION_SEC:
            break
        if not rows[j][2].lstrip().startswith('>>'):
            continue
        turn = []
        for k in range(j, len(rows)):
            if rows[k][0] > end_time + MAX_TAIL_SEC or (k > j and rows[k][2].lstrip().startswith('>>')):
                break
            turn.append(rows[k])
        questions = [r for r in turn if QUESTION.search(r[2]) or re.search(r'[?？]', r[2])]
        if questions and end_time - questions[-1][1] <= ANSWER_STUB_SEC:
            return j - 1, len(rows[j - 1][2])
    for j in range(i, first, -1):
        if rows[j][1] < end_time - TRAILING_QUESTION_SEC:
            break
        text = rows[j][2][:offset] if j == i else rows[j][2]
        if QUESTION.search(text.rstrip()):
            q_off = len(text.rstrip())
        else:
            marks = [m.end() for m in re.finditer(r'[?？]', text)]
            if not marks:
                continue
            q_off = marks[-1]
        if end_time - _time_at(rows[j], q_off) > ANSWER_STUB_SEC:
            break  # pertanyaan diikuti jawaban sungguhan: biarkan
        inner = _inner_ends(text[:q_off])
        if inner:
            return j, inner[-1]
        k = j - 1
        while k > first:
            if ends_sentence(rows, k, has_punct):
                return k, len(rows[k][2])
            inner = _inner_ends(rows[k][2])
            if inner:
                return k, inner[-1]
            k -= 1
        break
    return i, offset


def _start_cut(rows: list[Row], first: int, start: float, has_punct: bool) -> tuple[int, int]:
    """(indeks baris, offset huruf) kalimat utuh pertama pada atau sebelum `start`."""
    if first == 0 or ends_sentence(rows, first - 1, has_punct):
        return first, 0
    inner = _inner_ends(rows[first][2])
    if inner:  # baris diawali ekor kalimat sebelumnya: mulai di kalimat berikutnya
        text = rows[first][2]
        offset = inner[0]
        while offset < len(text) and text[offset] == ' ':
            offset += 1
        return first, offset
    i = first
    while i > 0 and start - rows[i - 1][1] <= MAX_LEAD_SEC:
        i -= 1
        inner = _inner_ends(rows[i][2])
        if not inner and (i == 0 or ends_sentence(rows, i - 1, has_punct)):
            return (i, 0) if start - rows[i][0] <= MAX_LEAD_SEC else (first, 0)
        if inner:
            offset = inner[-1] + (1 if rows[i][2][inner[-1]:inner[-1] + 1] == ' ' else 0)
            return (i, offset) if start - _time_at(rows[i], offset) <= MAX_LEAD_SEC else (first, 0)
    return first, 0


def sentence_bounds(rows: list[Row], start: float, end: float,
                    silences: SilenceFinder | None = None) -> tuple[float, float]:
    """(start, end) di kalimat utuh, dalam batas MAX_LEAD_SEC / MAX_TAIL_SEC.

    Dengan `silences`, kedua potongan menempel ke jeda nyata di audio.
    """
    if not rows:
        return start, end
    first = _index_at(rows, start + 0.05)
    if first is None:
        first = next((i for i, r in enumerate(rows) if r[0] >= start), None)
    last = _index_at(rows, end - 0.05)
    if first is None or last is None or last < first:
        return start, end
    has_punct = punctuated(rows)
    s_row, s_off = _start_cut(rows, first, start, has_punct)
    e_row, e_off = _end_cut(rows, last, end, has_punct)
    cut_end = rows[e_row][1] if e_off >= len(rows[e_row][2]) else _time_at(rows[e_row], e_off)
    q_row, q_off = _drop_trailing_question(rows, e_row, e_off, s_row, has_punct, cut_end)
    q_end = rows[q_row][1] if q_off >= len(rows[q_row][2]) else _time_at(rows[q_row], q_off)
    if q_end - (rows[s_row][0]) >= (end - start) * 0.6:  # jangan mengosongkan klip demi membuang pertanyaan
        e_row, e_off = q_row, q_off
    new_start = rows[s_row][0] if s_off == 0 else _time_at(rows[s_row], s_off)
    if e_off >= len(rows[e_row][2]):
        # Ekor pendek supaya kata terakhir tidak terpotong, tanpa masuk ke baris berikutnya.
        nxt = rows[e_row + 1][0] if e_row + 1 < len(rows) else rows[e_row][1] + 0.4
        new_end = max(rows[e_row][1], min(rows[e_row][1] + 0.4, nxt))
    else:
        new_end = _time_at(rows[e_row], e_off) + 0.25
    if new_end - new_start < 1:
        return start, end
    if silences is not None:
        min_end = new_start + (end - start) * 0.6
        estimate = rows[e_row][1] if e_off >= len(rows[e_row][2]) else _time_at(rows[e_row], e_off)
        new_end = _snap_end(rows, e_row, e_off, estimate, min_end, silences) or new_end
        new_start = _snap_start(new_start, silences, inner=s_off > 0)
    return round(new_start, 3), round(new_end, 3)


MATCH_SEC = 1.3          # akhir kalimat yang ditaksir di dalam baris bisa meleset sejauh ini
MIN_CHAR_SEC = 0.03      # ucapan butuh paling sedikit selama ini per huruf
BREATH_SEC = 0.5         # jeda sepanjang ini = tarikan napas yang jelas di antara kalimat
PARAGRAPH_SEC = 1.2      # jeda sepanjang ini tepat setelah baris = satu bagian selesai
END_SEARCH_FORWARD = 10.0
PARAGRAPH_REACH = 4.0


def _cut_window(rows: list[Row], row: int, offset: int, estimate: float) -> tuple[float, float]:
    """Di mana jeda setelah potongan ini bisa berada: teks sebelum potongan diucapkan sebelum jeda."""
    s, e, text = rows[row]
    if offset >= len(text):
        nxt = rows[row + 1][0] if row + 1 < len(rows) else e + 0.9
        next_turn = row + 1 < len(rows) and rows[row + 1][2].lstrip().startswith('>>')
        return e - 0.4, max(e, nxt) + (0 if next_turn else .5)
    before, after = len(text[:offset].replace(' ', '')), len(text[offset:].replace(' ', ''))
    return (max(s + before * MIN_CHAR_SEC, estimate - MATCH_SEC),
            min(e - after * MIN_CHAR_SEC, estimate + MATCH_SEC))


def _later_ends(rows: list[Row], row: int, offset: int, limit: float):
    """(baris, offset, taksiran detik) tiap akhir kalimat berikutnya, berhenti sebelum pertanyaan berikutnya."""
    for i in range(row, len(rows)):
        if rows[i][0] > limit:
            return
        text = rows[i][2]
        if i > row and text.lstrip().startswith('>>'):
            return
        offsets = [o for o in _inner_ends(text) if i > row or o > offset]
        if ends_sentence(rows, i, None) and (i > row or offset < len(text)):
            offsets.append(len(text))
        for o in offsets:
            if re.search(r'[?？]["”」』]?\s*$', text[:o]) or (o == len(text) and QUESTION.search(text)):
                return
            yield i, o, _time_at(rows[i], o)


def _pause_in(gaps, lo: float, hi: float, near: float, min_sec: float = 0.0):
    fit = [(s, e) for s, e in gaps if lo <= s <= hi and e - s >= min_sec]
    return min(fit, key=lambda g: (g[1] - g[0] < BREATH_SEC, abs(g[0] - near))) if fit else None


def _snap_end(rows: list[Row], row: int, offset: int, estimate: float, min_end: float,
              silences: SilenceFinder) -> float | None:
    """Akhiri di dalam jeda nyata setelah kalimat selesai, utamakan akhir satu bagian utuh."""
    gaps = [g for g in silences(estimate - MATCH_SEC, estimate + END_SEARCH_FORWARD + PARAGRAPH_REACH + 2)
            if g[0] >= min_end]
    lo, hi = _cut_window(rows, row, offset, estimate)
    pause, end_row = _pause_in(gaps, lo, hi, estimate), row
    if pause is None:
        later = list(_later_ends(rows, row, offset, estimate + END_SEARCH_FORWARD))
        for min_sec in (BREATH_SEC, 0.0):
            for i, o, t in later:
                pause = _pause_in(gaps, *_cut_window(rows, i, o, t), t, min_sec)
                if pause:
                    end_row = i
                    break
            if pause:
                break
    if pause is None:
        return None
    for s, e in gaps:  # bagian ini selesai dengan jeda panjang tepat sesudahnya: ambil utuh
        if pause[0] < s <= pause[0] + PARAGRAPH_REACH and e - s >= PARAGRAPH_SEC:
            rows_before = [r for r in rows[end_row:] if r[0] < s]
            if rows_before and abs(rows_before[-1][1] - s) <= 0.6 and not any(
                    r[2].lstrip().startswith('>>') or QUESTION.search(r[2]) or re.search(r'[?？]', r[2])
                    for r in rows_before[1:]):
                pause = (s, e)
            break
    return pause[0] + min(0.3, (pause[1] - pause[0]) / 2)


def _snap_start(estimate: float, silences: SilenceFinder, *, inner: bool) -> float:
    """Mulai di ujung jeda tepat sebelum kata pertama, supaya ekor kalimat sebelumnya tidak ikut."""
    ahead = 0.8 if inner else 0.35
    gaps = [g for g in silences(estimate - 1.5, estimate + 1.0) if estimate - 1.2 <= g[1] <= estimate + ahead]
    if not gaps:
        return estimate
    s, e = min(gaps, key=lambda g: abs(g[1] - estimate))
    return max(s, e - min(0.12, (e - s) / 2))


def audio_silences(video, noise_db: int = -32, min_sec: float = 0.2) -> SilenceFinder:
    """Rentang hening (detik absolut) di jendela audio sumber, lewat ffmpeg silencedetect."""
    cache: dict[tuple[float, float], list[tuple[float, float]]] = {}

    def find(lo: float, hi: float) -> list[tuple[float, float]]:
        lo = max(0.0, lo)
        key = (round(lo, 2), round(hi, 2))
        if key in cache:
            return cache[key]
        cmd = ['ffmpeg', '-hide_banner', '-nostats', '-ss', f'{lo:.3f}', '-t', f'{max(0.5, hi - lo):.3f}',
               '-i', str(video), '-vn', '-af', f'silencedetect=noise={noise_db}dB:d={min_sec}', '-f', 'null', '-']
        try:
            log = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                 timeout=60, check=False).stderr or ''
        except (OSError, subprocess.SubprocessError):
            return []
        out, begin = [], None
        for line in log.splitlines():
            if 'silence_start:' in line:
                try:
                    begin = lo + float(line.split('silence_start:')[1].split()[0])
                except ValueError:
                    begin = None
            elif 'silence_end:' in line and begin is not None:
                try:
                    out.append((max(lo, begin), lo + float(line.split('silence_end:')[1].split('|')[0])))
                except ValueError:
                    pass
                begin = None
        cache[key] = out
        return out

    return find


def word_gaps(words, min_sec: float = 0.2) -> SilenceFinder:
    """Celah di antara kata sebagai pengganti jeda audio (bila audio penuh musik)."""
    ws = sorted(((float(w.start), float(w.end)) for w in words), key=lambda x: x[0])
    gaps = [(a[1], b[0]) for a, b in zip(ws, ws[1:]) if b[0] - a[1] >= min_sec]

    def find(lo: float, hi: float) -> list[tuple[float, float]]:
        return [g for g in gaps if g[1] >= lo and g[0] <= hi]

    return find


def combined_silences(video, words) -> SilenceFinder:
    """Jeda audio bila terbaca di jendela itu; kalau tidak, celah antar kata."""
    audio, gaps = audio_silences(video), word_gaps(words)

    def find(lo: float, hi: float) -> list[tuple[float, float]]:
        return audio(lo, hi) or gaps(lo, hi)

    return find


BOUNDARY_PROMPT = (
    "Anda editor klip video pendek. `lines` adalah transkrip asli di sekitar sebuah klip (urut waktu, sering "
    "terpotong setengah kalimat); `start_line` dan `end_line` adalah baris pertama dan terakhir klip saat ini. "
    "Geser awal dan akhirnya supaya klip mulai di awal pertanyaan atau gagasan yang utuh, dan baru berhenti "
    "setelah jawaban atau gagasan itu benar-benar selesai: jangan berhenti di tengah kalimat, jangan berhenti "
    "saat lawan bicara baru mulai menjawab, dan jangan diakhiri pertanyaan berikutnya dari pembawa acara. "
    "Boleh maju atau mundur, tetapi jangan menggabungkan topik berikutnya. "
    'Jawab JSON saja: {"start_line":0,"end_line":0,"reason":"alasan singkat dalam bahasa Indonesia"}.'
)


def refine_with_model(rows: list[Row], start: float, end: float, call: Callable[[str, dict], dict],
                      silences: SilenceFinder | None = None) -> tuple[float, float, str] | None:
    """(start, end, alasan) pilihan model yang sudah dirapikan, atau None bila jawabannya tidak masuk akal."""
    window = [(i, r) for i, r in enumerate(rows) if start - CONTEXT_BEFORE <= r[0] <= end + CONTEXT_AFTER]
    if len(window) < 3:
        return None
    ids = {i: n for n, (i, _) in enumerate(window)}
    first, last = _index_at(rows, start + 0.05), _index_at(rows, end - 0.05)
    if first not in ids or last not in ids:
        return None
    result = call(BOUNDARY_PROMPT, {'lines': [{'id': n, 'text': r[2]} for n, (_, r) in enumerate(window)],
                                    'start_line': ids[first], 'end_line': ids[last]})
    s_id, e_id = (result or {}).get('start_line'), (result or {}).get('end_line')
    if isinstance(s_id, str) and s_id.strip().isdigit():
        s_id = int(s_id)
    if isinstance(e_id, str) and e_id.strip().isdigit():
        e_id = int(e_id)
    if not (isinstance(s_id, int) and isinstance(e_id, int) and 0 <= s_id <= e_id < len(window)):
        return None
    new_start, new_end = window[s_id][1][0], window[e_id][1][1]
    length, original = new_end - new_start, end - start
    # Tolak perubahan besar: model hanya merapikan tepi, bukan memilih klip lain.
    if (new_end > end + MODEL_MAX_EXTEND or new_start < start - CONTEXT_BEFORE or length < original * 0.6
            or length > original + MODEL_MAX_EXTEND + 15):
        return None
    s, e = sentence_bounds(rows, new_start, new_end, silences)
    return s, e, str((result or {}).get('reason') or '')[:300]
