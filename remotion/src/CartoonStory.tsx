import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { flip } from "@remotion/transitions/flip";
import { clockWipe } from "@remotion/transitions/clock-wipe";
import { iris } from "@remotion/transitions/iris";
import { ensureFonts } from "./fonts";
import { ThemeArt, ThemeOverlay, themeHidesHeading } from "./Themes";
import { MotionScene } from "./MotionScene";
import type { MotionDesign } from "./MotionScene";
import type { ThemeInfo } from "./Themes";
import type { Music, Scene, StoryProps, Style, Word } from "./types";

ensureFonts();

// ------------------------------------------------------------------ utilitas
const hexRgb = (hex: string): [number, number, number] => {
  const h = (hex || "#000000").replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h.padEnd(6, "0").slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const rgba = (hex: string, a: number) => {
  const [r, g, b] = hexRgb(hex);
  return `rgba(${r},${g},${b},${a})`;
};
const onColor = (hex: string) => {
  const [r, g, b] = hexRgb(hex);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.55 ? "#111111" : "#FFFFFF";
};
const clean = (s: string) => (s || "").replace(/\s+/g, " ").trim();
const isEmphasis = (w: string) => /[\d$%]/.test(w) || w.replace(/[^\p{L}]/gu, "").length >= 7;

const noiseUrl = (seed: number, freq = 0.85, alpha = 0.55) =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='${freq}' numOctaves='3' seed='${seed}' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(#n)' opacity='${alpha}'/></svg>`,
  )}")`;

const tornPath = (seed: number) => {
  const pts: string[] = [];
  const edge = (n: number, fn: (t: number, j: number) => [number, number]) => {
    for (let i = 0; i < n; i++) {
      const j = random(`${seed}-${pts.length}`) * 1.8;
      const [x, y] = fn(i / n, j);
      pts.push(`${x.toFixed(2)}% ${y.toFixed(2)}%`);
    }
  };
  edge(22, (t, j) => [t * 100, j]);
  edge(30, (t, j) => [100 - j, t * 100]);
  edge(22, (t, j) => [100 - t * 100, 100 - j]);
  edge(30, (t, j) => [j, 100 - t * 100]);
  return `polygon(${pts.join(",")})`;
};

// Ukuran elemen (huruf, garis, balon) mengikuti lebar layar portrait; untuk video lanskap/persegi
// lebar acuannya dibatasi agar teks tidak kebesaran.
const useSize = () => {
  const c = useVideoConfig();
  return { ...c, width: Math.min(c.width, c.height * 0.75) };
};

const presentation = (kind: string, width: number, height: number): any => {
  switch (kind) {
    case "slide":
      return slide({ direction: "from-right" });
    case "wipe":
      return wipe({ direction: "from-left" });
    case "flip":
      return flip({ direction: "from-right" });
    case "clockwipe":
      return clockWipe({ width, height });
    case "iris":
      return iris({ width, height });
    default:
      return fade();
  }
};

// ------------------------------------------------------------------ media + kamera
const Media: React.FC<{ sc: Scene; idx: number; durF: number; style: Style }> = ({ sc, idx, durF, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const f = style.motion === "stop" ? Math.floor(frame / 2) * 2 : frame;
  const e = Easing.inOut(Easing.cubic)(Math.min(1, f / Math.max(1, durF)));
  const fx = (sc.focus?.[0] ?? 0.5) * 100;
  const fy = (sc.focus?.[1] ?? 0.42) * 100;
  let s = 1;
  let tx = 0;
  let origin = `${fx}% ${fy}%`;
  if (sc.camera === "zoom_in") s = 1 + 0.14 * e;
  else if (sc.camera === "zoom_out") s = 1.14 - 0.14 * e;
  else if (sc.camera === "pan_left" || sc.camera === "pan_right") {
    s = 1.12;
    origin = `50% ${fy}%`;
    const m = ((1 - 1 / s) / 2) * 100 * 0.9;
    tx = (sc.camera === "pan_right" ? -1 : 1) * (e - 0.5) * 2 * m;
  } else s = 1.02 + 0.03 * e;
  let rot = 0;
  if (style.motion === "stop") {
    rot = (random(`r-${idx}-${f}`) - 0.5) * 1.1;
    tx += (random(`x-${idx}-${f}`) - 0.5) * 0.5;
  }
  const fill: React.CSSProperties = { width: "100%", height: "100%", objectFit: "cover", display: "block" };
  const filter = sc.video && style.videoFilter === "posterize" ? "url(#ca-posterize) saturate(1.35) contrast(1.08)" : undefined;
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: style.bg2 }}>
      <AbsoluteFill style={{ transform: `rotate(${rot}deg) scale(${s}) translateX(${tx}%)`, transformOrigin: origin }}>
        {sc.video ? (
          <OffthreadVideo src={sc.video} muted trimBefore={Math.round((sc.videoFrom ?? 0) * fps)} style={{ ...fill, filter }} />
        ) : sc.image ? (
          <Img src={sc.image} style={fill} />
        ) : (
          <AbsoluteFill style={{ background: `linear-gradient(160deg, ${style.bg2}, ${style.bg})` }} />
        )}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ elemen teks
const Heading: React.FC<{ text: string; style: Style; delay: number; layout: Style["frame"] }> = ({ text, style, delay, layout }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useSize();
  if (!text || frame < delay) return null;
  const t = style.uppercase ? text.toUpperCase() : text;
  const pop = spring({ frame: frame - delay, fps, config: { damping: 11, stiffness: 160 } });
  const size = width * (t.length < 14 ? 0.095 : t.length < 26 ? 0.078 : 0.062);
  const base: React.CSSProperties = {
    position: "absolute", left: "6%", right: "6%", top: "4.5%", display: "flex", justifyContent: "center",
    transform: `scale(${0.6 + 0.4 * pop})`, opacity: Math.min(1, pop * 1.4),
  };
  if (layout === "panel") {
    return (
      <div style={{ ...base, justifyContent: "flex-start" }}>
        <div style={{ background: style.accent, color: onColor(style.accent), border: `${width * 0.008}px solid ${style.ink}`,
          padding: `${width * 0.014}px ${width * 0.03}px`, fontFamily: style.font, fontSize: size, lineHeight: 1.05,
          transform: "rotate(-2deg)", boxShadow: `${width * 0.01}px ${width * 0.01}px 0 ${style.ink}`, maxWidth: "92%" }}>{t}</div>
      </div>
    );
  }
  if (layout === "paper") {
    return (
      <div style={base}>
        <div style={{ background: "#FFFDF6", color: style.ink, padding: `${width * 0.016}px ${width * 0.035}px`,
          fontFamily: style.font, fontSize: size, lineHeight: 1.08, transform: "rotate(-1.6deg)",
          boxShadow: "0 10px 24px rgba(0,0,0,.28)", maxWidth: "92%", textAlign: "center" }}>{t}</div>
      </div>
    );
  }
  if (layout === "plain") {
    const light = onColor(style.bg) === "#111111";
    return (
      <div style={{ ...base, flexDirection: "column", alignItems: "center", top: "5%" }}>
        <div style={{ color: style.text, fontFamily: style.font, fontSize: size * 1.05, lineHeight: 1.05, textAlign: "center", maxWidth: "94%",
          textShadow: light ? "none" : `0 ${width * 0.004}px ${width * 0.025}px rgba(0,0,0,0.55)` }}>{t}</div>
        <div style={{ width: `${Math.min(60, 8 + t.length * 2.2)}%`, height: width * 0.012, marginTop: width * 0.012, background: style.accent,
          borderRadius: width * 0.01, transform: `scaleX(${pop})`, opacity: 0.9 }} />
      </div>
    );
  }
  if (layout === "card") {
    return (
      <div style={base}>
        <div style={{ color: style.text, fontFamily: style.font, fontSize: size, lineHeight: 1.04, textAlign: "center",
          maxWidth: "94%" }}>{t}</div>
      </div>
    );
  }
  return (
    <div style={base}>
      <div style={{ background: style.accent, color: onColor(style.accent), padding: `${width * 0.012}px ${width * 0.03}px`,
        borderRadius: width * 0.016, fontFamily: style.font, fontSize: size, lineHeight: 1.05, textAlign: "center",
        maxWidth: "94%" }}>{t}</div>
    </div>
  );
};

const Bubble: React.FC<{ text: string; style: Style; top: string; up?: boolean }> = ({ text, style, top, up }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useSize();
  const t = clean(text);
  if (!t) return null;
  const shown = Math.floor(interpolate(frame, [4, 4 + t.length * 0.9], [0, t.length], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const pop = spring({ frame: frame - 2, fps, config: { damping: 12 } });
  const bw = width * 0.008;
  return (
    <div style={{ position: "absolute", top, left: "9%", right: "9%", display: "flex", justifyContent: "center",
      transform: `scale(${0.7 + 0.3 * pop})`, transformOrigin: up ? "30% 0%" : "30% 100%", opacity: Math.min(1, pop * 1.5) }}>
      <div style={{ position: "relative", background: "#FFFFFF", color: "#111", border: `${bw}px solid ${style.ink}`,
        borderRadius: width * 0.06, padding: `${width * 0.03}px ${width * 0.045}px`, fontFamily: style.captionFont,
        fontSize: width * 0.052, lineHeight: 1.18, textAlign: "center", boxShadow: `${bw}px ${bw}px 0 ${style.ink}` }}>
        <span>{t.slice(0, shown)}</span>
        <span style={{ visibility: "hidden" }}>{t.slice(shown)}</span>
        {/* ekor balon: ke bawah bila balon di atas wajah, ke atas bila balon di bawah wajah */}
        <div style={{ position: "absolute", left: "22%", [up ? "top" : "bottom"]: -width * 0.05, width: 0, height: 0,
          borderLeft: `${width * 0.03}px solid transparent`, borderRight: `${width * 0.03}px solid transparent`,
          [up ? "borderBottom" : "borderTop"]: `${width * 0.055}px solid ${style.ink}` }} />
        <div style={{ position: "absolute", left: "calc(22% + 6px)", [up ? "top" : "bottom"]: -width * 0.034, width: 0, height: 0,
          borderLeft: `${width * 0.022}px solid transparent`, borderRight: `${width * 0.022}px solid transparent`,
          [up ? "borderBottom" : "borderTop"]: `${width * 0.04}px solid #FFFFFF` }} />
      </div>
    </div>
  );
};

const Sfx: React.FC<{ text: string; style: Style }> = ({ text, style }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useSize();
  const start = 8;
  if (!text || frame < start || frame > start + fps * 1.6) return null;
  const pop = spring({ frame: frame - start, fps, config: { damping: 7, stiffness: 180 } });
  const out = interpolate(frame, [start + fps * 1.2, start + fps * 1.6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const pts = Array.from({ length: 24 }, (_, i) => {
    const a = (i / 24) * Math.PI * 2;
    const r = i % 2 === 0 ? 50 : 34;
    return `${50 + r * Math.cos(a)},${50 + r * Math.sin(a)}`;
  }).join(" ");
  const size = width * 0.34;
  return (
    <div style={{ position: "absolute", right: "6%", top: "50%", width: size, height: size,
      transform: `rotate(-12deg) scale(${pop})`, opacity: out }}>
      <svg viewBox="0 0 100 100" width={size} height={size} style={{ position: "absolute", inset: 0 }}>
        <polygon points={pts} fill={style.accent} stroke={style.ink} strokeWidth={2.4} strokeLinejoin="round" />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "Bangers", fontSize: size * (text.length > 6 ? 0.2 : 0.27), color: onColor(style.accent), textAlign: "center",
        lineHeight: 0.95, padding: "18%" }}>{text.toUpperCase()}</div>
    </div>
  );
};

const SpeedLines: React.FC<{ style: Style }> = ({ style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const o = interpolate(frame, [0, 4, fps * 0.7], [0, 0.55, 0], { extrapolateRight: "clamp" });
  if (o <= 0) return null;
  const lines = Array.from({ length: 48 }, (_, i) => {
    const a = (i / 48) * Math.PI * 2 + random(`sl${i}`) * 0.1;
    const r0 = 30 + random(`sr${i}`) * 12;
    return <line key={i} x1={50 + r0 * Math.cos(a)} y1={50 + r0 * Math.sin(a)} x2={50 + 90 * Math.cos(a)} y2={50 + 90 * Math.sin(a)}
      stroke={style.ink} strokeWidth={0.4 + random(`sw${i}`) * 0.6} />;
  });
  return (
    <AbsoluteFill style={{ opacity: o, pointerEvents: "none" }}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" width="100%" height="100%">{lines}</svg>
    </AbsoluteFill>
  );
};

const TitleCard: React.FC<{ text: string; style: Style }> = ({ text, style }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useSize();
  const t = style.uppercase ? text.toUpperCase() : text;
  const pop = spring({ frame, fps, config: { damping: 13, stiffness: 140 } });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: "0 8%" }}>
      <div style={{ width: width * 0.16, height: width * 0.018, background: style.accent, marginBottom: width * 0.05,
        transform: `scaleX(${pop})` }} />
      <div style={{ color: style.text, fontFamily: style.font, fontSize: width * (t.length < 18 ? 0.12 : t.length < 34 ? 0.095 : 0.075),
        lineHeight: 1.04, textAlign: "center", transform: `translateY(${(1 - pop) * 40}px)`, opacity: Math.min(1, pop * 1.4),
        textShadow: `0 ${width * 0.006}px 0 ${rgba(style.ink, 0.5)}` }}>{t}</div>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ satu adegan
const SceneView: React.FC<{ sc: Scene; idx: number; durF: number; style: Style; headingDelay: number; bubbleText: string;
  theme?: ThemeInfo; startF: number; design?: MotionDesign }> = ({ sc, idx, durF, style, headingDelay, bubbleText, theme, startF, design }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useSize();
  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 120 } });
  const themed = !!(theme && sc.art && !sc.image && !sc.video);
  const motion = !!((sc as any).motion && design && !sc.image);
  const motionEl = motion ? <MotionScene sc={sc} idx={idx} durF={durF} design={design as MotionDesign} overlay={!!sc.video} /> : null;
  const media = motion ? (sc.video ? <AbsoluteFill><Media sc={sc} idx={idx} durF={durF} style={style} />{motionEl}</AbsoluteFill> : motionEl)
    : themed ? <ThemeArt sc={sc} idx={idx} durF={durF} style={style} theme={theme as ThemeInfo} startF={startF} />
    : <Media sc={sc} idx={idx} durF={durF} style={style} />;
  const showBubble = style.captions === "bubble" && !!bubbleText;
  // Adegan tanpa gambar/video: judul besar di tengah layar (kartu teks).
  const cardOnly = !sc.image && !sc.video && !themed && !motion && !!sc.heading;
  const hideHeading = motion || (themed && themeHidesHeading(theme, sc));
  // Tanpa caption di bawah, bingkai boleh lebih tinggi agar layar tidak kosong.
  const tall = style.captions === "bubble" || style.captions === "none";
  // Wajah di bagian atas gambar: balon kata dipindah ke bawah agar tidak menutupi wajah.
  const faceHigh = !!sc.focus && sc.focus[1] < 0.55;
  let body: React.ReactNode;
  if (motion) {
    body = media;                                  // motion graphics selalu layar penuh
  } else if (style.frame === "panel") {
    const bw = width * 0.012;
    body = (
      <div style={{ position: "absolute", left: "5%", right: "5%", top: "15%", height: tall ? "74%" : "58%",
        border: `${bw}px solid ${style.ink}`, boxShadow: `${bw}px ${bw}px 0 ${style.ink}`, background: style.bg2,
        transform: `rotate(${idx % 2 ? 1.2 : -1.2}deg) scale(${0.92 + 0.08 * enter})`, overflow: "hidden" }}>{media}</div>
    );
  } else if (style.frame === "card") {
    body = (
      <div style={{ position: "absolute", left: "7%", right: "7%", top: "17%", height: tall ? "70%" : "55%", borderRadius: width * 0.05,
        overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,.35)",
        transform: `translateY(${(1 - enter) * 80}px)`, opacity: Math.min(1, enter * 1.3) }}>{media}</div>
    );
  } else if (style.frame === "paper") {
    const tilt = idx % 2 ? 2.2 : -2.4;
    body = (
      <div style={{ position: "absolute", left: "7%", right: "7%", top: "16%", height: tall ? "72%" : "56%",
        transform: `rotate(${tilt}deg) scale(${0.94 + 0.06 * enter})`, filter: "drop-shadow(0 14px 18px rgba(0,0,0,.35))" }}>
        <div style={{ position: "absolute", inset: 0, background: "#FFFDF6", clipPath: tornPath(idx + 3) }} />
        <div style={{ position: "absolute", inset: "3.2%", overflow: "hidden", clipPath: tornPath(idx + 11) }}>{media}</div>
        <div style={{ position: "absolute", top: -width * 0.02, left: "38%", width: "24%", height: width * 0.06,
          background: rgba(style.accent, 0.75), transform: "rotate(-4deg)" }} />
      </div>
    );
  } else {
    body = media;
  }
  return (
    <AbsoluteFill>
      {body}
      {style.texture === "speedlines" && !motion ? <SpeedLines style={style} /> : null}
      {cardOnly ? <TitleCard text={sc.heading || ""} style={style} />
        : hideHeading ? null : <Heading text={sc.heading || ""} style={style} delay={headingDelay} layout={style.frame} />}
      {showBubble ? <Bubble text={bubbleText} style={style} up={faceHigh}
        top={faceHigh ? (style.frame === "full" ? "68%" : "66%") : style.frame === "full" ? "16%" : "19%"} /> : null}
      {style.sfx && sc.sfx ? <Sfx text={sc.sfx} style={style} /> : null}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ caption global
type Group = { s: number; e: number; words: Word[] };
const makeGroups = (words: Word[], maxWords: number, maxChars: number): Group[] => {
  const groups: Group[] = [];
  let cur: Word[] = [];
  for (const w of words) {
    if (cur.length) {
      const chars = cur.reduce((n, x) => n + x.t.length + 1, 0) + w.t.length;
      const last = cur[cur.length - 1];
      if (cur.length >= maxWords || chars > maxChars || w.s - last.e > 0.6 || /[.?!,]$/.test(last.t)) {
        groups.push({ s: cur[0].s, e: last.e, words: cur });
        cur = [];
      }
    }
    cur.push(w);
  }
  if (cur.length) groups.push({ s: cur[0].s, e: cur[cur.length - 1].e, words: cur });
  return groups;
};

const Captions: React.FC<{ words: Word[]; style: Style }> = ({ words, style }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useSize();
  const groups = useMemo(
    () => (style.captions === "pop" ? makeGroups(words, 1, 30) : makeGroups(words, 3, 20)),
    [words, style.captions],
  );
  if (style.captions === "none" || style.captions === "bubble") return null;
  const t = frame / fps;
  const gi = groups.findIndex((g, i) => t >= g.s - 0.05 && t < Math.min(groups[i + 1]?.s ?? Infinity, g.e + 0.35));
  if (gi < 0) return null;
  const g = groups[gi];
  const pop = spring({ frame: frame - Math.round(g.s * fps), fps, config: { damping: 10, stiffness: 200 } });
  const size = width * (style.captions === "pop" ? 0.11 : 0.072);
  const stroke = Math.max(2, Math.max(4, size * 0.09) * (style.captionStroke ?? 1));
  return (
    <div style={{ position: "absolute", left: "6%", right: "6%", top: style.captions === "pop" ? "74%" : "77%",
      display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `0 ${size * 0.25}px`,
      transform: `scale(${0.8 + 0.2 * pop})` }}>
      {g.words.map((w, i) => {
        const active = t >= w.s && (i === g.words.length - 1 || t < g.words[i + 1].s);
        const color = style.captions === "pop" ? (isEmphasis(w.t) ? style.accent : style.text) : active ? style.accent : style.text;
        return (
          <span key={i} style={{ fontFamily: style.captionFont, fontSize: size, lineHeight: 1.1, color,
            WebkitTextStroke: `${stroke}px ${style.ink}`, paintOrder: "stroke fill",
            textShadow: `0 ${stroke * 0.6}px 0 ${rgba(style.ink, 0.6)}` }}>{style.uppercase ? w.t.toUpperCase() : w.t}</span>
        );
      })}
    </div>
  );
};

const Hook: React.FC<{ text: string; style: Style }> = ({ text, style }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useSize();
  const end = Math.round(fps * 3.2);
  if (!text || frame > end) return null;
  const slam = spring({ frame, fps, config: { damping: 9, stiffness: 170 } });
  const out = interpolate(frame, [end - 8, end], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const t = style.uppercase ? text.toUpperCase() : text;
  return (
    <div style={{ position: "absolute", top: "4.5%", left: "6%", right: "6%", display: "flex", justifyContent: "center",
      transform: `scale(${1.5 - 0.5 * slam})`, opacity: out * Math.min(1, slam * 2) }}>
      <div style={{ background: style.accent, color: onColor(style.accent), fontFamily: style.font,
        fontSize: width * (t.length < 24 ? 0.07 : 0.056), lineHeight: 1.08, padding: `${width * 0.016}px ${width * 0.032}px`,
        textAlign: "center", border: style.frame === "panel" ? `${width * 0.008}px solid ${style.ink}` : undefined,
        borderRadius: style.frame === "panel" ? 0 : width * 0.016 }}>{t}</div>
    </div>
  );
};

// ------------------------------------------------------------------ komposisi utama
// ------------------------------------------------------------------ musik latar dengan ducking
const MusicBed: React.FC<{ music: Music; speech: [number, number][] }> = ({ music, speech }) => {
  const { fps, durationInFrames } = useVideoConfig();
  // Selubung "ada suara" per frame, dihaluskan agar musik turun-naik dengan lembut.
  const env = React.useMemo(() => {
    const raw = new Float32Array(durationInFrames);
    for (const [s, e] of speech) {
      const a = Math.max(0, Math.floor((s - 0.2) * fps));
      const b = Math.min(durationInFrames, Math.ceil((e + 0.35) * fps));
      for (let f = a; f < b; f++) raw[f] = 1;
    }
    const out = new Float32Array(durationInFrames);
    const k = Math.max(1, Math.round(fps * 0.25));
    let acc = 0;
    for (let f = 0; f < durationInFrames + k; f++) {
      if (f < durationInFrames) acc += raw[f];
      if (f - 2 * k >= 0) acc -= raw[f - 2 * k];
      const c = f - k;
      if (c >= 0 && c < durationInFrames) out[c] = acc / (2 * k);
    }
    return out;
  }, [speech, fps, durationInFrames]);
  return (
    <Audio src={music.src} volume={(f) => {
      const fadeIn = Math.min(1, f / (fps * 0.6));
      const d = env[Math.min(env.length - 1, Math.max(0, f))] ?? 0;
      return music.volume * fadeIn * (1 - (1 - music.duck) * d);
    }} />
  );
};

export const CartoonStory: React.FC<StoryProps> = (props) => {
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const { scenes, style, words } = props;
  const tf = Math.max(2, Math.round(style.transitionSec * fps));
  const hookF = props.hook ? Math.round(fps * 3.2) : 0;

  const frames = scenes.map((sc) => Math.round((sc.start + sc.dur) * fps) - Math.round(sc.start * fps));
  const children: React.ReactNode[] = [];
  scenes.forEach((sc, i) => {
    const d = Math.max(1, frames[i]);
    const next = i + 1 < scenes.length ? Math.max(1, frames[i + 1]) : 0;
    const tr = next && sc.transition !== "none" && tf < Math.min(d, next) ? tf : 0;
    const sceneStart = Math.round(sc.start * fps);
    const bubbleText = clean(sc.bubble || words.filter((w) => w.s >= sc.start - 0.05 && w.s < sc.start + sc.dur).map((w) => w.t).slice(0, 16).join(" "));
    children.push(
      <TransitionSeries.Sequence key={`s${i}`} durationInFrames={d + tr}>
        <SceneView sc={sc} idx={i} durF={d + tr} style={style} bubbleText={bubbleText} theme={props.theme} startF={sceneStart}
          design={(props as any).motionDesign}
          headingDelay={Math.max(0, hookF - sceneStart)} />
      </TransitionSeries.Sequence>,
    );
    if (tr) {
      children.push(
        <TransitionSeries.Transition key={`t${i}`} presentation={presentation(sc.transition, width, height)}
          timing={linearTiming({ durationInFrames: tr })} />,
      );
    }
  });

  const tex = style.texture;
  const bgLayer: React.CSSProperties = { background: style.bg };
  if (tex === "halftone") {
    bgLayer.backgroundImage = `radial-gradient(${rgba(style.ink, 0.16)} 22%, transparent 24%)`;
    bgLayer.backgroundSize = `${width * 0.022}px ${width * 0.022}px`;
  } else if (tex === "paper") {
    bgLayer.backgroundImage = noiseUrl(7, 0.9, 0.35);
  }

  return (
    <AbsoluteFill style={bgLayer}>
      <svg width={0} height={0} style={{ position: "absolute" }}>
        <filter id="ca-posterize" colorInterpolationFilters="sRGB">
          {/* sedikit blur sebelum kuantisasi: tepi warna tidak berkedip dan file jauh lebih kecil */}
          <feGaussianBlur stdDeviation="1.6" />
          <feComponentTransfer>
            <feFuncR type="discrete" tableValues="0 0.22 0.45 0.7 0.92 1" />
            <feFuncG type="discrete" tableValues="0 0.22 0.45 0.7 0.92 1" />
            <feFuncB type="discrete" tableValues="0 0.22 0.45 0.7 0.92 1" />
          </feComponentTransfer>
        </filter>
      </svg>
      <TransitionSeries>{children}</TransitionSeries>
      {props.theme ? <ThemeOverlay theme={props.theme} style={style} /> : null}
      {tex === "grain" ? (
        <AbsoluteFill style={{ backgroundImage: noiseUrl(Math.floor(frame / 3) % 5, 0.9, 0.5), opacity: 0.07, mixBlendMode: "overlay" }} />
      ) : null}
      <Captions words={words} style={style} />
      {props.hook ? <Hook text={props.hook} style={style} /> : null}
      {props.progressBar ? (
        <div style={{ position: "absolute", left: 0, bottom: 0, height: Math.max(6, height * 0.006),
          width: `${(frame / Math.max(1, durationInFrames - 1)) * 100}%`, background: style.accent }} />
      ) : null}
      {props.music ? <MusicBed music={props.music} speech={props.speech ?? words.map((w) => [w.s, w.e] as [number, number])} /> : null}
      {props.audio
        ? props.audioParts.map((a, i) => (
            <Sequence key={`a${i}`} from={Math.round(a.at * fps)} durationInFrames={Math.max(1, Math.round((a.to - a.from) * fps))}>
              <Audio src={props.audio as string} trimBefore={Math.round(a.from * fps)} />
            </Sequence>
          ))
        : null}
    </AbsoluteFill>
  );
};
