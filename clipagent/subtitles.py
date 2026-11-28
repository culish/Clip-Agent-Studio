"""Subtitle beranimasi (format ASS untuk libass/ffmpeg) + SRT biasa.

Gaya animasi:
  karaoke    kata yang sedang diucapkan berganti warna
  pop        baris muncul dengan efek membesar, kata aktif disorot
  bounce     satu kata sekali tampil, besar dan memantul (gaya "Hormozi")
  box        kata aktif diberi kotak warna
  typewriter kata muncul satu per satu
  fade       baris muncul halus sambil naik (tanpa sorotan)
  static     tanpa animasi
Tambahan: judul/hook di bagian atas pada detik awal dan progress bar di bawah.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .transcript import Word

# Perkiraan lebar rata-rata huruf (× ukuran font) dan skala ukuran per font.
_FONT_METRICS = {
    "Montserrat Black": (0.74, 1.00),
    "Anton": (0.50, 1.18),
    "Bebas Neue": (0.44, 1.30),
    "Poppins": (0.66, 1.00),
    "Arial": (0.62, 1.00),
}


@dataclass
class CaptionStyle:
    anim: str = "karaoke"
    font: str = "Montserrat Black"
    fake_bold: bool = False
    size: int = 0
    uppercase: bool = True
    text_color: str = "#FFFFFF"
    highlight: str = "#FFE500"
    max_words: int = 3
    position: str = "lower"       # lower | middle | upper
    captions: bool = True
    hook_text: str = ""
    progress_bar: bool = False
    y_frac: float = 0.0            # >0: caption di tengah garis ini (mis. batas dua panel layout streaming)
    y_steps: tuple = ()            # layout per bagian: ((detik, y_frac), ...); y_frac 0 = posisi biasa


# ---------------------------------------------------------------- utilitas
def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _rgb(hex_rgb: str, default: str = "FFE500") -> tuple[int, int, int]:
    h = (hex_rgb or "").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = default
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _tag_color(hex_rgb: str, default: str = "FFE500") -> str:
    """'#RRGGBB' -> '&HBBGGRR&' (untuk tag override)."""
    r, g, b = _rgb(hex_rgb, default)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _style_color(hex_rgb: str, default: str = "FFFFFF", alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (untuk definisi Style)."""
    r, g, b = _rgb(hex_rgb, default)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _contrast(hex_rgb: str) -> str:
    r, g, b = _rgb(hex_rgb)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#111111" if lum > 0.55 else "#FFFFFF"


def _clean(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _emphasis(word: str) -> bool:
    core = re.sub(r"[^\w$%]", "", word)
    return bool(re.search(r"[\d$%]", core)) or len(core) >= 7


def _group(words: list[Word], max_words: int, max_chars: int = 22, max_gap: float = 0.6) -> list[list[Word]]:
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            ends_sentence = cur[-1].text[-1:] in ".?!,"
            if (len(cur) >= max_words or chars > max_chars
                    or w.start - cur[-1].end > max_gap or ends_sentence):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def _wrap(text: str, max_chars: int) -> str:
    lines, cur = [], ""
    for tok in text.split():
        if cur and len(cur) + 1 + len(tok) > max_chars:
            lines.append(cur)
            cur = tok
        else:
            cur = f"{cur} {tok}".strip()
    if cur:
        lines.append(cur)
    return r"\N".join(lines[:3])


# ---------------------------------------------------------------- ASS
def build_ass(words: list[Word], clip_start: float, clip_end: float, width: int, height: int,
              style: CaptionStyle, vertical: bool = True) -> str:
    """Isi file .ass untuk satu klip (waktu relatif terhadap awal klip)."""
    char_w, scale = _FONT_METRICS.get(style.font, (0.62, 1.0))
    base = style.size or int(height * (0.045 if vertical else 0.065) * scale)
    size = int(base * (1.35 if style.anim == "bounce" else 1.0))
    outline = max(2, round(size * 0.08))
    shadow = max(1, outline // 2)
    margin_h = int(width * 0.07)
    bold = -1 if style.fake_bold else 0
    text_c = _style_color(style.text_color)
    hl = _tag_color(style.highlight)
    base_c = _tag_color(style.text_color, "FFFFFF")
    clip_dur = clip_end - clip_start

    # Posisi teks: anchor bawah/tengah/atas (atau garis batas panel, bisa berganti per bagian layout).
    x = width // 2

    def place(t: float) -> tuple[int, int, str]:
        yf = style.y_frac
        for t0, f in style.y_steps or ():
            if t >= t0 - 1e-3:
                yf = f
        if yf > 0:
            a_, y_ = 5, int(height * yf)
        elif style.position == "upper":
            a_, y_ = 8, int(height * (0.20 if vertical else 0.10))
        elif style.position == "middle":
            a_, y_ = 5, int(height * (0.58 if vertical else 0.55))
        else:
            a_, y_ = 2, int(height * (0.76 if vertical else 0.92))
        return a_, y_, rf"\an{a_}\pos({x},{y_})"
    an, y, pos = place(0.0)

    hook_size = max(18, int(height * (0.031 if vertical else 0.045) * scale))
    hook_box = style.highlight
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font},{size},{text_c},{text_c},&H00000000,&H78000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,{margin_h},{margin_h},0,1
Style: Hook,{style.font},{hook_size},{_style_color(_contrast(hook_box))},&H00FFFFFF,{_style_color(hook_box)},&H00000000,{bold},0,0,0,100,100,0,0,3,{max(6, int(hook_size * 0.38))},0,8,{margin_h},{margin_h},0,1
Style: Bar,Arial,10,{_style_color(style.highlight)},&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    def add(start: float, end: float, text: str, layer: int = 0, st: str = "Default"):
        if end - start >= 0.02:
            events.append(f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{st},,0,0,0,,{text}")

    if style.captions:
        max_chars = max(6, int((width - 2 * margin_h) / (char_w * size)))
        inside = [w for w in words if w.end > clip_start + 0.02 and w.start < clip_end - 0.02]
        groups = _group(inside, style.max_words, max_chars=max_chars)
        pop_in = r"\fscx75\fscy75\t(0,90,\fscx108\fscy108)\t(90,170,\fscx100\fscy100)"
        bounce_in = r"\fscx55\fscy55\t(0,80,\fscx115\fscy115)\t(80,160,\fscx100\fscy100)"
        box_pad = max(6, int(size * 0.22))
        box_txt = _tag_color(_contrast(style.highlight))

        for gi, group in enumerate(groups):
            next_start = groups[gi + 1][0].start if gi + 1 < len(groups) else clip_end
            g_start = group[0].start - clip_start
            g_end = min(next_start, group[-1].end + 0.35, clip_end) - clip_start
            an, y, pos = place(g_start)
            toks = [_clean(w.text.upper() if style.uppercase else w.text) for w in group]

            if style.anim in ("static", "fade"):
                text = " ".join(toks)
                if style.anim == "fade":
                    tag = rf"\an{an}\move({x},{y + int(size * 0.35)},{x},{y},0,180)\fad(160,90)"
                else:
                    tag = pos
                add(g_start, g_end, f"{{{tag}}}{text}")
                continue

            for wi, w in enumerate(group):
                start = g_start if wi == 0 else w.start - clip_start
                end = (group[wi + 1].start - clip_start) if wi + 1 < len(group) else g_end
                if end <= start:
                    continue
                anim_tag = ""
                if style.anim == "pop" and wi == 0:
                    anim_tag = pop_in
                elif style.anim == "bounce":
                    anim_tag = bounce_in
                parts = []
                for k, tok in enumerate(toks):
                    if style.anim == "bounce":
                        color = hl if _emphasis(tok) else base_c
                        parts.append(rf"{{\c{color}}}{tok}")
                    elif style.anim == "box" and k == wi:
                        parts.append(rf"{{\c{box_txt}\3c{hl}\bord{box_pad}\shad0}}{tok}"
                                     rf"{{\c{base_c}\3c&H000000&\bord{outline}\shad{shadow}}}")
                    elif style.anim == "typewriter" and k > wi:
                        parts.append(rf"{{\alpha&HFF&}}{tok}")
                    elif k == wi and style.anim != "box":
                        parts.append(rf"{{\c{hl}}}{tok}{{\c{base_c}}}")
                    else:
                        parts.append(tok)
                add(start, end, f"{{{pos}{anim_tag}}}" + " ".join(parts))

    if style.hook_text.strip():
        hook = _clean(style.hook_text.strip())
        hook_chars = max(10, int((width * 0.86) / (char_w * hook_size)))
        hook_y = int(height * (0.075 if vertical else 0.06))
        dur = min(3.4, clip_dur)
        tag = (rf"\an8\pos({x},{hook_y})\fscx70\fscy70\t(0,140,\fscx104\fscy104)"
               rf"\t(140,220,\fscx100\fscy100)\fad(0,220)")
        add(0, dur, f"{{{tag}}}{_wrap(hook, hook_chars)}", layer=2, st="Hook")

    if style.progress_bar:
        bh = max(6, round(height * 0.006))
        ms = int(clip_dur * 1000)
        add(0, clip_dur,
            rf"{{\an7\pos(0,{height - bh})\p1\clip(0,0,0,{height})\t(0,{ms},\clip(0,0,{width},{height}))}}"
            rf"m 0 0 l {width} 0 {width} {bh} 0 {bh}{{\p0}}", layer=3, st="Bar")

    return header + "\n".join(events) + "\n"


# ---------------------------------------------------------------- SRT
def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list[Word], clip_start: float, clip_end: float, max_words: int = 7) -> str:
    """SRT biasa (tanpa sorotan) untuk diunggah ke platform atau diedit di CapCut/Premiere."""
    inside = [w for w in words if w.end > clip_start + 0.02 and w.start < clip_end - 0.02]
    groups = _group(inside, max_words, max_chars=42, max_gap=0.8)
    out = []
    for i, g in enumerate(groups, 1):
        nxt = groups[i][0].start if i < len(groups) else clip_end
        end = min(nxt, g[-1].end + 0.3, clip_end)
        out.append(f"{i}\n{_srt_time(g[0].start - clip_start)} --> {_srt_time(end - clip_start)}\n"
                   f"{' '.join(w.text for w in g)}\n")
    return "\n".join(out)
