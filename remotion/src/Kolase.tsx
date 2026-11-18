// Komposisi "Kolase": video explainer bergaya kolase editorial dari voice-over.
// Semua waktu (detik absolut) dihitung di Python (clipagent/kolase.py) dan dipakai juga untuk efek suara,
// sehingga gambar dan bunyi selalu jatuh di saat yang sama. Video dirender tanpa audio; audio digabung di Python.
import React, { useMemo } from "react";
import { AbsoluteFill, Easing, Img, Sequence, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { geoBounds, geoCentroid, geoGraticule10, geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import world from "world-atlas/countries-50m.json";
import { ensureFonts } from "./fonts";

ensureFonts();

// ------------------------------------------------------------------ tipe
export type KWord = { s: number; e: number; t: string };
export type KItem = { t: string; label?: string; at: number };
export type KNumber = { value: number; decimals: number; prefix: string; suffix: string; group: string; dec: string; year: boolean; at: number };
export type KScene = {
  id: string; idx: number; start: number; end: number; layout: string; heading: string; keyword: string; label: string;
  places: string[]; quote: string; image: string; cutout: boolean; tilt: number; enter: string; seed: number; dark: boolean;
  captions: boolean; words: KWord[]; mark: [number, number] | null; markAt: number; reveal?: number[]; hot?: number;
  number?: KNumber; countEnd?: number; items?: KItem[]; vsAt?: number; pinAt?: number;
};
export type KTheme = { name: string; paper: string; paper2: string; ink: string; accent: string; marker: string; dark: string };
// gaya huruf: wk = lebar rata-rata huruf tebal dibanding Anton (untuk menghitung ukuran agar muat), ts = skala label judul,
// hs = skala tulisan tangan
export type KFonts = { sans: string; serif: string; italic: string; type: string; hand: string; caption: string; wk: number; ts: number; hs: number };
export type KolaseProps = { fps: number; width: number; height: number; duration: number; theme: KTheme; scenes: KScene[]; words: KWord[]; lang: string; fonts?: KFonts };

const ENTER = 0.3;
const DEFAULT_FONTS: KFonts = { sans: "Anton", serif: "Playfair Display Black", italic: "Playfair Italic", type: "Special Elite",
  hand: "Permanent Marker", caption: "Montserrat Black", wk: 1, ts: 1, hs: 1 };

// ------------------------------------------------------------------ utilitas
const clamp = (x: number, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const ease = (t: number, at: number, dur: number, fn = Easing.out(Easing.cubic)) => fn(clamp((t - at) / Math.max(1e-3, dur)));
const back = (t: number, at: number, dur: number) => interpolate(clamp((t - at) / dur), [0, 1], [0, 1], { easing: Easing.out(Easing.back(1.7)) });
const hexRgb = (hex: string): [number, number, number] => {
  const n = parseInt((hex || "#000000").replace("#", "").padEnd(6, "0").slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const rgba = (hex: string, a: number) => {
  const [r, g, b] = hexRgb(hex);
  return `rgba(${r},${g},${b},${a})`;
};
const mulberry = (seed: number) => {
  let a = seed >>> 0 || 1;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};
const noise = (seed: number, freq: number, alpha: number) =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='360' height='360'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='${freq}' numOctaves='3' seed='${seed}' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(#n)' opacity='${alpha}'/></svg>`,
  )}")`;
// tepi sobek: poligon bergerigi (persen)
const torn = (seed: number, depth = 1.6, n = 26) => {
  const r = mulberry(seed);
  const pts: string[] = [];
  const side = (k: number, fn: (u: number, j: number) => [number, number]) => {
    for (let i = 0; i < k; i++) {
      const [x, y] = fn(i / k, r() * depth);
      pts.push(`${x.toFixed(2)}% ${y.toFixed(2)}%`);
    }
  };
  side(n, (u, j) => [u * 100, j]);
  side(n, (u, j) => [100 - j, u * 100]);
  side(n, (u, j) => [100 - u * 100, 100 - j]);
  side(n, (u, j) => [j, 100 - u * 100]);
  return `polygon(${pts.join(",")})`;
};
// garis tangan: kurva halus lewat titik-titik yang digoyang sedikit
const smooth = (pts: [number, number][]) => {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
};
const handEllipse = (cx: number, cy: number, rx: number, ry: number, seed: number) => {
  const r = mulberry(seed);
  const pts: [number, number][] = [];
  const turns = 1.18;
  for (let i = 0; i <= 28; i++) {
    const a = -2.2 + (i / 28) * Math.PI * 2 * turns;
    const k = 1 + (r() - 0.5) * 0.07 + i * 0.002;
    pts.push([cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k]);
  }
  return smooth(pts);
};
const handArrow = (x1: number, y1: number, x2: number, y2: number, seed: number, head: number) => {
  const r = mulberry(seed);
  const mx = (x1 + x2) / 2 + (y2 - y1) * (0.12 + r() * 0.1);
  const my = (y1 + y2) / 2 - (x2 - x1) * (0.12 + r() * 0.1);
  const body = smooth([[x1, y1], [mx, my], [x2, y2]]);
  const ang = Math.atan2(y2 - my, x2 - mx);
  const h1: [number, number] = [x2 - Math.cos(ang - 0.5) * head, y2 - Math.sin(ang - 0.5) * head];
  const h2: [number, number] = [x2 - Math.cos(ang + 0.5) * head, y2 - Math.sin(ang + 0.5) * head];
  return `${body} M${h1[0].toFixed(1)},${h1[1].toFixed(1)} L${x2.toFixed(1)},${y2.toFixed(1)} L${h2[0].toFixed(1)},${h2[1].toFixed(1)}`;
};
const fmtNum = (v: number, n: KNumber) => {
  const fixed = v.toFixed(n.decimals);
  const [ip, fp] = fixed.split(".");
  const grouped = n.year ? ip : ip.replace(/\B(?=(\d{3})+(?!\d))/g, n.group);
  return fp ? `${grouped}${n.dec}${fp}` : grouped;
};

type Ctx = { sc: KScene; t: number; W: number; H: number; u: number; wide: boolean; th: KTheme; ink: string; paper: string; f: KFonts };

// ------------------------------------------------------------------ elemen kolase
const Tag: React.FC<{ c: Ctx; text: string; at: number; style?: React.CSSProperties; size?: number; rot?: number }> = ({ c, text, at, style, size, rot = -2 }) => {
  const p = ease(c.t, at, 0.35);
  if (!text) return null;
  const fs = (size ?? c.u * (c.wide ? (text.length > 22 ? 5 : 6) : text.length > 22 ? 6 : 7.4)) * c.f.ts;
  return (
    <div style={{ position: "absolute", transform: `rotate(${rot}deg)`, clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`, ...style }}>
      <span style={{ background: c.ink, color: c.paper, fontFamily: c.f.sans, fontSize: fs, lineHeight: 1.18, textTransform: "uppercase",
        padding: `${c.u * 0.5}px ${c.u * 1.6}px`, boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone", letterSpacing: c.u * 0.06 }}>{text}</span>
    </div>
  );
};

const Tape: React.FC<{ c: Ctx; x: number; y: number; w: number; rot: number; seed: number }> = ({ c, x, y, w, rot, seed }) => (
  <div style={{ position: "absolute", left: x, top: y, width: w, height: w * 0.32, transform: `translate(-50%,-50%) rotate(${rot}deg)`,
    background: "rgba(236,226,196,0.78)", clipPath: torn(seed, 6, 6), boxShadow: "0 2px 6px rgba(0,0,0,0.12)", mixBlendMode: "normal" }} />
);

const Halftone: React.FC<{ c: Ctx; x: string; y: string; size: number; color: string; seed: number; alpha?: number }> = ({ c, x, y, size, color, seed, alpha = 0.32 }) => (
  <div style={{ position: "absolute", left: x, top: y, width: size, height: size, borderRadius: "50%", opacity: alpha,
    backgroundImage: `radial-gradient(${color} 26%, transparent 29%)`, backgroundSize: `${c.u * 1.5}px ${c.u * 1.5}px`,
    WebkitMaskImage: "radial-gradient(circle, black 30%, transparent 70%)", maskImage: "radial-gradient(circle, black 30%, transparent 70%)",
    transform: `rotate(${seed % 40}deg)` }} />
);

const Marker: React.FC<{ c: Ctx; on: boolean; at: number; children: React.ReactNode }> = ({ c, on, at, children }) => {
  if (!on) return <>{children}</>;
  const p = ease(c.t, at, 0.38, Easing.inOut(Easing.quad));
  return (
    <span style={{ backgroundImage: `linear-gradient(100deg, ${rgba(c.th.marker, 0.0)} 0%, ${rgba(c.th.marker, 0.92)} 2%, ${rgba(c.th.marker, 0.85)} 97%, ${rgba(c.th.marker, 0)} 100%)`,
      backgroundRepeat: "no-repeat", backgroundSize: `${p * 100}% 78%`, backgroundPosition: "0 70%", padding: `0 ${c.u * 0.25}px`,
      margin: `0 -${c.u * 0.25}px`, boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone", color: p > 0.3 ? "#141414" : undefined }}>{children}</span>
  );
};

const Draw: React.FC<{ d: string; p: number; color: string; width: number; style?: React.CSSProperties; W: number; H: number }> = ({ d, p, color, width, style, W, H }) => (
  <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", ...style }}>
    <path d={d} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" pathLength={1}
      strokeDasharray="1 1" strokeDashoffset={1 - p} />
  </svg>
);

// ------------------------------------------------------------------ tata letak
const LPotong: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const pIn = back(t, sc.start + 0.06, 0.5);
  const blob = ease(t, sc.start - 0.05, 0.4);
  const float = Math.sin((t - sc.start) * 1.4) * u * 0.35;
  const box = wide ? { left: W * 0.05, top: H * 0.08, w: W * 0.46, h: H * 0.86 } : { left: W * 0.06, top: H * 0.24, w: W * 0.88, h: H * 0.56 };
  const markP = ease(t, sc.markAt, 0.45);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: box.left + box.w * 0.08, top: box.top + box.h * 0.12, width: box.w * 0.84, height: box.h * 0.78,
        background: th.accent, clipPath: torn(sc.seed, 4, 14), transform: `rotate(${sc.tilt * 2}deg) scale(${0.7 + 0.3 * blob})`, opacity: blob }} />
      <Halftone c={c} x={`${(box.left + box.w * 0.5) / W * 100}%`} y={`${(box.top + box.h * 0.05) / H * 100}%`} size={box.w * 0.6} color={c.ink} seed={sc.seed} alpha={0.22} />
      {sc.image ? (
        <Img src={sc.image} style={{ position: "absolute", left: box.left, top: box.top, width: box.w, height: box.h, objectFit: "contain",
          objectPosition: "50% 100%", filter: `grayscale(1) contrast(1.14) drop-shadow(0 ${u * 1.1}px ${u * 1.4}px rgba(0,0,0,0.38))`,
          transform: `translateY(${(1 - pIn) * u * 10 + float}px) scale(${0.9 + 0.1 * pIn}) rotate(${sc.tilt * 0.6}deg)`, opacity: clamp(pIn * 3) }} />
      ) : null}
      <Tag c={c} text={sc.heading} at={sc.start + 0.2}
        style={wide ? { left: W * 0.55, top: H * 0.3, width: W * 0.4 } : { left: W * 0.07, top: H * 0.1, width: W * 0.86 }}
        size={u * (sc.heading.length > 24 ? 6.4 : 8)} />
      {sc.mark && sc.keyword ? (
        <>
          <div style={{ position: "absolute", fontFamily: c.f.hand, color: th.accent, fontSize: u * 6.2 * c.f.hs, lineHeight: 1,
            left: wide ? W * 0.58 : W * 0.56, top: wide ? H * 0.62 : H * 0.255, transform: `rotate(-6deg) scale(${0.6 + 0.4 * back(t, sc.markAt, 0.35)})`,
            opacity: clamp((t - sc.markAt) * 6), transformOrigin: "0 50%", whiteSpace: "nowrap" }}>{sc.keyword}</div>
          <Draw W={W} H={H} p={markP} color={th.accent} width={u * 0.7}
            d={wide ? handArrow(W * 0.58, H * 0.63, W * 0.44, H * 0.52, sc.seed, u * 2.6) : handArrow(W * 0.6, H * 0.3, W * 0.5, H * 0.38, sc.seed, u * 2.6)} />
        </>
      ) : null}
    </AbsoluteFill>
  );
};

const LFoto: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const p = back(t, sc.start + 0.02, 0.5);
  const k = clamp((t - sc.start) / Math.max(1, sc.end - sc.start));
  const box = wide ? { left: W * 0.06, top: H * 0.13, w: W * 0.52, h: H * 0.7 } : { left: W * 0.08, top: H * 0.2, w: W * 0.84, h: H * 0.48 };
  const pad = u * 1.6;
  return (
    <AbsoluteFill>
      <Halftone c={c} x={wide ? "62%" : "55%"} y={wide ? "8%" : "62%"} size={u * 46} color={th.accent} seed={sc.seed} alpha={0.28} />
      <div style={{ position: "absolute", left: box.left, top: box.top, width: box.w, height: box.h, background: "#F7F3EA", padding: pad,
        boxShadow: `0 ${u * 1.2}px ${u * 3}px rgba(0,0,0,0.35)`, transform: `rotate(${sc.tilt * 1.4 + (1 - p) * 6}deg) translateY(${(1 - p) * u * 8}px) scale(${0.94 + 0.06 * p})`,
        opacity: clamp(p * 3) }}>
        <div style={{ width: "100%", height: "100%", overflow: "hidden", background: "#222" }}>
          {sc.image ? <Img src={sc.image} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "grayscale(1) contrast(1.18) brightness(1.02)",
            transform: `scale(${1.1 - 0.08 * k}) translateX(${(k - 0.5) * u * 1.5}px)` }} /> : null}
        </div>
        <Tape c={c} x={box.w * 0.12} y={0} w={u * 14} rot={-32} seed={sc.seed + 1} />
        <Tape c={c} x={box.w * 0.88} y={0} w={u * 14} rot={28} seed={sc.seed + 2} />
      </div>
      <div style={{ position: "absolute", fontFamily: c.f.serif, color: c.ink, fontSize: u * (sc.heading.length > 26 ? 6.2 : 7.6), lineHeight: 1.05,
        left: wide ? W * 0.62 : W * 0.08, top: wide ? H * 0.32 : H * 0.72, width: wide ? W * 0.33 : W * 0.84,
        opacity: ease(t, sc.start + 0.25, 0.3), transform: `translateY(${(1 - ease(t, sc.start + 0.25, 0.35)) * u * 3}px)` }}>
        {sc.heading.split(/\s+/).map((w, i) => {
          const kw = sc.keyword.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "").slice(0, 5);
          const hot = !!sc.mark && kw.length > 2 && w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "").startsWith(kw);
          return <React.Fragment key={i}><Marker c={c} on={hot} at={sc.markAt}>{w}</Marker>{" "}</React.Fragment>;
        })}
      </div>
    </AbsoluteFill>
  );
};

const LDokumen: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const n = sc.words.length;
  const fs = u * (n <= 12 ? 6.4 : n <= 20 ? 5.4 : n <= 30 ? 4.6 : n <= 42 ? 3.9 : 3.3);
  const box = wide ? { left: W * 0.2, top: H * 0.07, w: W * 0.6, h: H * 0.86 } : { left: W * 0.06, top: H * 0.1, w: W * 0.88, h: H * 0.76 };
  const p = ease(t, sc.start - 0.1, 0.4);
  const mk = sc.mark;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: box.left, top: box.top, width: box.w, height: box.h, background: "#FBF8F0",
        boxShadow: `0 ${u * 1}px ${u * 3.4}px rgba(0,0,0,0.3)`, transform: `rotate(${-1.2 + sc.tilt * 0.3}deg) translateY(${(1 - p) * u * 4}px)`,
        backgroundImage: `${noise(sc.seed, 0.9, 0.12)}, repeating-linear-gradient(transparent 0, transparent ${fs * 1.62 - 1}px, rgba(70,110,170,0.16) ${fs * 1.62 - 1}px, rgba(70,110,170,0.16) ${fs * 1.62}px)`,
        backgroundPosition: `0 0, 0 ${u * 15}px`, padding: `${u * 5}px ${u * 6}px ${u * 4}px ${u * 9}px`, boxSizing: "border-box", overflow: "hidden" }}>
        <div style={{ position: "absolute", left: u * 6.4, top: 0, bottom: 0, width: Math.max(2, u * 0.25), background: rgba("#D33", 0.45) }} />
        <div style={{ fontFamily: c.f.type, fontSize: u * 2.8, color: rgba("#222", 0.7), letterSpacing: u * 0.2 }}>NO. {String(sc.idx + 1).padStart(3, "0")}</div>
        <div style={{ fontFamily: c.f.serif, fontSize: u * (sc.heading.length > 26 ? 5.2 : 6.4), lineHeight: 1.05, color: "#141414", margin: `${u * 1.2}px 0 ${u * 2.4}px`,
          borderBottom: `${u * 0.45}px solid ${th.accent}`, paddingBottom: u * 1.2 }}>{sc.heading}</div>
        <div style={{ fontFamily: c.f.type, fontSize: fs, lineHeight: 1.62, color: "#1a1a1a" }}>
          {sc.words.map((w, i) => {
            const vis = t >= w.s - 0.05;
            const inMark = mk && i >= mk[0] && i <= mk[1];
            return (
              <React.Fragment key={i}>
                <span style={{ opacity: vis ? 1 : 0 }}>
                  <Marker c={{ ...c, paper: "#FBF8F0" }} on={!!inMark} at={sc.markAt}>{w.t}</Marker>
                </span>{" "}
              </React.Fragment>
            );
          })}
        </div>
      </div>
      <svg width={u * 9} height={u * 20} viewBox="0 0 90 200" style={{ position: "absolute", left: box.left + box.w * 0.78, top: box.top - u * 5, transform: "rotate(8deg)" }}>
        <path d="M30 190 L30 40 A20 20 0 0 1 70 40 L70 160 A12 12 0 0 1 46 160 L46 60" fill="none" stroke="#8a8f96" strokeWidth={7} strokeLinecap="round" />
      </svg>
    </AbsoluteFill>
  );
};

type Geo = { type: string; features: any[] };
let WORLD: Geo | null = null;
const worldFC = (): Geo => {
  if (!WORLD) WORLD = feature(world as any, (world as any).objects.countries) as unknown as Geo;
  return WORLD;
};

const LPeta: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const geo = useMemo(() => {
    const fc = worldFC();
    const targets = fc.features.filter((f: any) => sc.places.includes(f.properties?.name));
    if (!targets.length) return null;
    const tfc = { type: "FeatureCollection", features: targets };
    const ext: [[number, number], [number, number]] = wide ? [[W * 0.36, H * 0.16], [W * 0.92, H * 0.88]] : [[W * 0.1, H * 0.25], [W * 0.9, H * 0.72]];
    let fitObj: any = tfc;
    const b = geoBounds(tfc as any);
    if (b[0][0] <= b[1][0]) {
      const cx = (b[0][0] + b[1][0]) / 2, cy = (b[0][1] + b[1][1]) / 2;
      const hw = Math.max(5, (b[1][0] - b[0][0]) / 2), hh = Math.max(3.5, (b[1][1] - b[0][1]) / 2);
      fitObj = { type: "MultiPoint", coordinates: [[cx - hw, cy - hh], [cx + hw, cy + hh]] };
    }
    const proj = geoMercator().fitExtent(ext, fitObj);
    const path = geoPath(proj);
    const land: { d: string; hit: boolean; name: string }[] = [];
    for (const f of fc.features) {
      const bb = path.bounds(f as any);
      if (!isFinite(bb[0][0]) || bb[1][0] < -W * 1.6 || bb[0][0] > W * 2.6 || bb[1][1] < -H * 1.6 || bb[0][1] > H * 2.6) continue;
      const d = path(f as any);
      if (d) land.push({ d, hit: sc.places.includes(f.properties?.name), name: f.properties?.name });
    }
    const centroid = proj(geoCentroid(targets[0] as any)) as [number, number];
    const grat = path(geoGraticule10() as any) || "";
    return { land, centroid, grat };
  }, [sc.id, W, H]);
  if (!geo) return <LJudul c={c} />;
  const z = ease(t, sc.start - 0.1, 1.5, Easing.inOut(Easing.cubic));
  const s = 0.42 + 0.58 * z;
  const [cx, cy] = geo.centroid;
  const outline = ease(t, sc.start + 0.4, 0.9, Easing.inOut(Easing.quad));
  const pin = back(t, sc.pinAt ?? sc.start + 1, 0.45);
  return (
    <AbsoluteFill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <pattern id={`hatch${sc.id}`} width={u * 1.4} height={u * 1.4} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1={0} y1={0} x2={0} y2={u * 1.4} stroke={rgba(c.ink, 0.28)} strokeWidth={u * 0.35} />
          </pattern>
        </defs>
        <g transform={`translate(${cx},${cy}) scale(${s}) translate(${-cx},${-cy})`}>
          <path d={geo.grat} fill="none" stroke={rgba(c.ink, 0.1)} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
          {geo.land.filter((l) => !l.hit).map((l, i) => (
            <path key={i} d={l.d} fill={rgba(c.ink, 0.1)} stroke={rgba(c.ink, 0.38)} strokeWidth={1.1} vectorEffect="non-scaling-stroke" />
          ))}
          {geo.land.filter((l) => l.hit).map((l, i) => (
            <g key={`h${i}`}>
              <path d={l.d} fill={th.accent} opacity={ease(t, sc.start + 0.5, 0.5)} />
              <path d={l.d} fill={`url(#hatch${sc.id})`} opacity={ease(t, sc.start + 0.5, 0.5)} />
              <path d={l.d} fill="none" stroke={c.ink} strokeWidth={u * 0.45} vectorEffect="non-scaling-stroke" pathLength={1}
                strokeDasharray="1 1" strokeDashoffset={1 - outline} strokeLinejoin="round" />
            </g>
          ))}
        </g>
        <g transform={`translate(${cx},${cy - (1 - pin) * u * 14})`} opacity={clamp(pin * 4)}>
          <circle r={u * 2.2} fill={c.paper} stroke={c.ink} strokeWidth={u * 0.7} />
          <circle r={u * 0.9} fill={c.ink} />
        </g>
      </svg>
      <Tag c={c} text={sc.heading} at={sc.start + 0.15}
        style={wide ? { left: W * 0.05, top: H * 0.38, width: W * 0.3 } : { left: W * 0.07, top: H * 0.1, width: W * 0.86 }} size={u * 6.8} />
      <div style={{ position: "absolute", left: wide ? W * 0.05 : W * 0.08, top: wide ? H * 0.66 : H * 0.79, fontFamily: c.f.type, color: c.ink,
        fontSize: u * 4, opacity: ease(t, (sc.pinAt ?? sc.start + 1) + 0.15, 0.3), letterSpacing: u * 0.1 }}>
        {sc.places.join(" · ").toUpperCase()}
      </div>
    </AbsoluteFill>
  );
};

const LJudul: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const words = sc.heading.split(/\s+/).filter(Boolean).slice(0, 8);
  const per = wide ? 18 : 11;
  const lines: { w: string; i: number }[][] = [];
  words.forEach((w, i) => {
    const cur = lines[lines.length - 1];
    const len = cur ? cur.reduce((a, x) => a + x.w.length + 1, 0) : 99;
    if (!cur || len + w.length > per) lines.push([{ w, i }]);
    else cur.push({ w, i });
  });
  const longest = Math.max(4, ...lines.map((l) => l.reduce((a, x) => a + x.w.length + 1, -1)));
  const base = Math.min(u * (wide ? 15 : 17), (W * 0.84) / (longest * 0.56 * c.f.wk));
  const variant = (i: number) => (i === sc.hot ? "hot" : ["sans", "italic", "outline", "sans"][i % 4]);
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div style={{ position: "absolute", left: "-5%", width: "110%", top: wide ? "56%" : "58%", height: base * 0.9, background: rgba(th.accent, 0.9),
        clipPath: torn(sc.seed, 8, 18), transform: `rotate(${sc.tilt * 1.5 - 3}deg) scaleX(${ease(t, sc.start, 0.45)})`, transformOrigin: "0 50%" }} />
      <Halftone c={c} x="68%" y="6%" size={u * 40} color={c.ink} seed={sc.seed} alpha={0.2} />
      <div style={{ position: "relative", textAlign: "center", width: W * 0.9, transform: `rotate(${sc.tilt * 0.6}deg)` }}>
        {lines.map((ln, li) => (
          <div key={li} style={{ lineHeight: 1.02, margin: `${base * 0.05}px 0` }}>
            {ln.map(({ w, i }) => {
              const at = sc.reveal?.[i] ?? sc.start + 0.15 + i * 0.2;
              const p = back(t, at, 0.32);
              const v = variant(i);
              const st: React.CSSProperties = { display: "inline-block", margin: `0 ${base * 0.12}px`, opacity: clamp((t - at) * 8),
                transform: `scale(${1.5 - 0.5 * p}) rotate(${(1 - p) * -6}deg)`, color: c.ink };
              if (v === "sans") Object.assign(st, { fontFamily: c.f.sans, fontSize: base, textTransform: "uppercase" });
              if (v === "italic") Object.assign(st, { fontFamily: c.f.italic, fontSize: base * 0.92 });
              if (v === "outline") Object.assign(st, { fontFamily: c.f.sans, fontSize: base, textTransform: "uppercase", color: "transparent",
                WebkitTextStroke: `${Math.max(2, u * 0.45)}px ${c.ink}` });
              if (v === "hot") Object.assign(st, { fontFamily: c.f.sans, fontSize: base * 1.08, textTransform: "uppercase", color: c.paper,
                background: c.ink, padding: `0 ${base * 0.14}px` });
              return <span key={i} style={st}>{w}</span>;
            })}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

const LAngka: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const n = sc.number;
  if (!n) return <LJudul c={c} />;
  const end = sc.countEnd ?? n.at + 1;
  const p = n.year ? (t >= n.at ? 1 : 0) : ease(t, n.at, Math.max(0.05, end - n.at), Easing.out(Easing.quad));
  const txt = fmtNum(n.value * p, n);
  const full = fmtNum(n.value, n);
  const size = Math.min(u * (wide ? 26 : 30), (W * 0.82) / (full.length * 0.5 * c.f.wk));
  const circ = ease(t, end, 0.45, Easing.inOut(Easing.quad));
  const cy = H * (wide ? 0.5 : 0.47);
  return (
    <AbsoluteFill>
      <Tag c={c} text={sc.heading} at={sc.start + 0.1} style={wide ? { left: W * 0.06, top: H * 0.1 } : { left: W * 0.07, top: H * 0.12, width: W * 0.86 }} />
      <Halftone c={c} x="10%" y={wide ? "40%" : "30%"} size={u * 50} color={th.accent} seed={sc.seed} alpha={0.25} />
      <div style={{ position: "absolute", left: 0, right: 0, top: cy - size * 0.62, textAlign: "center" }}>
        {n.prefix ? <div style={{ fontFamily: c.f.sans, fontSize: size * 0.28, color: th.accent, textTransform: "uppercase", lineHeight: 1 }}>{n.prefix}</div> : null}
        <div style={{ fontFamily: c.f.sans, fontSize: size, color: c.ink, lineHeight: 1.05, opacity: t >= n.at - 0.05 ? 1 : 0.18,
          transform: `scale(${1 + 0.06 * (1 - ease(t, end, 0.25))})` }}>{t >= n.at - 0.05 ? txt : fmtNum(0, n)}</div>
        {n.suffix ? <div style={{ fontFamily: c.f.italic, fontSize: size * 0.3, color: c.ink, lineHeight: 1.1 }}>{n.suffix}</div> : null}
        {sc.label ? <div style={{ fontFamily: c.f.type, fontSize: u * 4.4, color: c.ink, marginTop: u * 2, padding: `0 ${W * 0.1}px`,
          opacity: ease(t, n.at + 0.2, 0.3) }}>{sc.label}</div> : null}
      </div>
      <Draw W={W} H={H} p={circ} color={th.accent} width={u * 0.75}
        d={handEllipse(W / 2, cy + size * 0.02, Math.min(W * 0.46, full.length * size * 0.32 * c.f.wk + u * 6), size * 0.62, sc.seed)} />
    </AbsoluteFill>
  );
};

const LGarisWaktu: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const items = sc.items ?? [];
  const n = items.length || 1;
  const last = items.length ? items[items.length - 1].at : sc.start + 1;
  const grow = ease(t, sc.start + 0.1, Math.max(0.6, last - sc.start + 0.2), Easing.inOut(Easing.quad));
  if (wide) {
    const y = H * 0.55, x0 = W * 0.08, x1 = W * 0.92;
    return (
      <AbsoluteFill>
        <Tag c={c} text={sc.heading} at={sc.start + 0.1} style={{ left: W * 0.06, top: H * 0.1 }} />
        <div style={{ position: "absolute", left: x0, top: y - u * 0.4, width: (x1 - x0) * grow, height: u * 0.8, background: c.ink }} />
        {items.map((it, i) => {
          const x = x0 + ((x1 - x0) * (i + 0.5)) / n;
          const p = back(t, it.at, 0.4);
          return (
            <div key={i} style={{ position: "absolute", left: x - W * 0.12, width: W * 0.24, top: y - u * 16, textAlign: "center", opacity: clamp((t - it.at) * 6) }}>
              <div style={{ fontFamily: c.f.sans, fontSize: u * 11, color: th.accent, lineHeight: 1, transform: `scale(${0.6 + 0.4 * p})` }}>{it.t}</div>
              <div style={{ width: u * 3.4, height: u * 3.4, borderRadius: "50%", background: c.paper, border: `${u * 0.8}px solid ${c.ink}`, margin: `${u * 1.2}px auto` }} />
              <div style={{ fontFamily: c.f.type, fontSize: u * 4.6, color: c.ink, lineHeight: 1.25 }}>{it.label}</div>
            </div>
          );
        })}
      </AbsoluteFill>
    );
  }
  const x = W * 0.2, y0 = H * 0.24, y1 = H * 0.84;
  return (
    <AbsoluteFill>
      <Tag c={c} text={sc.heading} at={sc.start + 0.1} style={{ left: W * 0.07, top: H * 0.1, width: W * 0.86 }} />
      <div style={{ position: "absolute", left: x - u * 0.4, top: y0, width: u * 0.8, height: (y1 - y0) * grow, background: c.ink }} />
      {items.map((it, i) => {
        const y = y0 + ((y1 - y0) * (i + 0.5)) / n;
        const p = back(t, it.at, 0.4);
        return (
          <div key={i} style={{ position: "absolute", left: x - u * 2.1, top: y - u * 7, display: "flex", gap: u * 4, alignItems: "flex-start",
            opacity: clamp((t - it.at) * 6), transform: `translateX(${(1 - p) * u * 6}px)` }}>
            <div style={{ width: u * 4.2, height: u * 4.2, borderRadius: "50%", background: c.paper, border: `${u * 0.9}px solid ${c.ink}`, flex: "none", marginTop: u * 4 }} />
            <div style={{ width: W * 0.62 }}>
              <div style={{ fontFamily: c.f.sans, fontSize: u * 13, color: th.accent, lineHeight: 1 }}>{it.t}</div>
              <div style={{ fontFamily: c.f.type, fontSize: u * 4.4, color: c.ink, lineHeight: 1.25 }}>{it.label}</div>
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

const LBanding: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const items = (sc.items ?? []).slice(0, 2);
  const cards = wide
    ? [{ left: W * 0.06, top: H * 0.24, w: W * 0.38, h: H * 0.6 }, { left: W * 0.56, top: H * 0.24, w: W * 0.38, h: H * 0.6 }]
    : [{ left: W * 0.08, top: H * 0.22, w: W * 0.84, h: H * 0.26 }, { left: W * 0.08, top: H * 0.56, w: W * 0.84, h: H * 0.26 }];
  const vs = back(t, sc.vsAt ?? sc.end - 0.6, 0.35);
  return (
    <AbsoluteFill>
      <Tag c={c} text={sc.heading} at={sc.start + 0.05} style={wide ? { left: W * 0.06, top: H * 0.1 } : { left: W * 0.07, top: H * 0.1, width: W * 0.86 }} size={u * 6} />
      {items.map((it, i) => {
        const b = cards[i];
        const p = back(t, it.at, 0.45);
        const fs = Math.min(u * 11, (b.w * 0.86) / (Math.max(4, it.t.length) * 0.55 * c.f.wk));
        return (
          <div key={i} style={{ position: "absolute", left: b.left, top: b.top, width: b.w, height: b.h, background: i ? c.th.paper2 : "#F7F3EA",
            clipPath: torn(sc.seed + i, 2.2, 16), display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center",
            transform: `translate${wide ? "X" : "Y"}(${(1 - p) * (i ? 1 : -1) * u * 12}px) rotate(${(i ? 1.5 : -1.5) + sc.tilt * 0.4}deg)`,
            opacity: clamp((t - it.at) * 6), padding: u * 3, boxSizing: "border-box", color: "#141414" }}>
            <div style={{ fontFamily: c.f.sans, fontSize: fs, textTransform: "uppercase", lineHeight: 1.02 }}>{it.t}</div>
            {it.label ? <div style={{ fontFamily: c.f.type, fontSize: u * 4.2, marginTop: u * 1.5 }}>{it.label}</div> : null}
          </div>
        );
      })}
      <div style={{ position: "absolute", left: W / 2 - u * 9, top: (wide ? H * 0.54 : H * 0.515) - u * 9, width: u * 18, height: u * 18, borderRadius: "50%",
        background: th.accent, color: "#FFF", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: c.f.italic, fontSize: u * 8.5,
        transform: `scale(${1.6 - 0.6 * vs}) rotate(${-12 + 12 * vs}deg)`, opacity: clamp((t - (sc.vsAt ?? 0)) * 8), boxShadow: `0 ${u}px ${u * 2}px rgba(0,0,0,0.3)` }}>vs</div>
    </AbsoluteFill>
  );
};

const LAlur: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const items = (sc.items ?? []).slice(0, 4);
  const n = items.length || 1;
  const pos = items.map((_, i) => wide
    ? { x: W * (0.1 + (0.8 * (i + 0.5)) / n), y: H * 0.55 }
    : { x: W * 0.5, y: H * (0.24 + (0.6 * (i + 0.5)) / n) });
  const bw = wide ? (W * 0.78) / n - u * 6 : W * 0.7;
  const bh = wide ? H * 0.34 : (H * 0.6) / n - u * 7;
  return (
    <AbsoluteFill>
      <Tag c={c} text={sc.heading} at={sc.start + 0.05} style={wide ? { left: W * 0.06, top: H * 0.1 } : { left: W * 0.07, top: H * 0.1, width: W * 0.86 }} size={u * 6} />
      {items.map((it, i) => {
        if (i === 0) return null;
        const a = pos[i - 1], b = pos[i];
        const p = ease(t, items[i - 1].at + 0.15, Math.max(0.2, it.at - items[i - 1].at - 0.1), Easing.inOut(Easing.quad));
        const d = wide ? handArrow(a.x + bw / 2 + u, a.y, b.x - bw / 2 - u, b.y, sc.seed + i, u * 2.4)
          : handArrow(a.x, a.y + bh / 2 + u * 0.8, b.x, b.y - bh / 2 - u * 0.8, sc.seed + i, u * 2.4);
        return <Draw key={`a${i}`} W={W} H={H} p={p} d={d} color={th.accent} width={u * 0.75} />;
      })}
      {items.map((it, i) => {
        const p = back(t, it.at, 0.4);
        const fs = Math.min(u * (wide ? 6.5 : 7.4), (bw * 0.9) / (Math.max(5, it.t.length) * 0.55 * c.f.wk));
        return (
          <div key={i} style={{ position: "absolute", left: pos[i].x - bw / 2, top: pos[i].y - bh / 2, width: bw, height: bh,
            background: i % 2 ? "#F7F3EA" : c.th.marker, border: `${u * 0.4}px solid #141414`, boxSizing: "border-box", display: "flex",
            flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: u * 1.5, color: "#141414",
            transform: `rotate(${(i % 2 ? 1.6 : -1.4) + sc.tilt * 0.3}deg) scale(${0.7 + 0.3 * p})`, opacity: clamp((t - it.at) * 6),
            boxShadow: `${u * 0.6}px ${u * 0.7}px 0 #141414` }}>
            <div style={{ fontFamily: c.f.sans, fontSize: fs, textTransform: "uppercase", lineHeight: 1.02 }}>{it.t}</div>
            {it.label ? <div style={{ fontFamily: c.f.type, fontSize: u * 3.4, marginTop: u * 0.8 }}>{it.label}</div> : null}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

const LKutipan: React.FC<{ c: Ctx }> = ({ c }) => {
  const { sc, t, W, H, u, wide, th } = c;
  const words = sc.quote.split(/\s+/).filter(Boolean);
  const fs = u * (words.length <= 10 ? 8.6 : words.length <= 18 ? 7 : 5.8) * (wide ? 0.9 : 1);
  const mk = sc.mark;
  return (
    <AbsoluteFill style={{ justifyContent: "center", padding: `0 ${W * 0.1}px`, boxSizing: "border-box" }}>
      <Halftone c={c} x="62%" y="62%" size={u * 44} color={th.accent} seed={sc.seed} alpha={0.22} />
      <div style={{ position: "relative", marginTop: -H * 0.04 }}>
        <div style={{ fontFamily: c.f.serif, fontSize: u * 40, lineHeight: 0.8, height: u * 18, color: th.accent, marginLeft: -u * 2,
          opacity: ease(t, sc.start, 0.3), transform: `scale(${0.8 + 0.2 * back(t, sc.start, 0.4)})`, transformOrigin: "0 100%" }}>“</div>
        <div style={{ width: W * 0.24 * ease(t, sc.start + 0.3, 0.5), height: u * 0.6, background: c.ink, margin: `${u * 2}px 0 ${u * 3}px` }} />
        <div style={{ fontFamily: c.f.italic, fontSize: fs, lineHeight: 1.22, color: c.ink }}>
          {words.map((w, i) => {
            const at = sc.reveal?.[i] ?? sc.start + 0.2 + i * 0.2;
            const inMark = mk && i >= mk[0] && i <= mk[1];
            return (
              <React.Fragment key={i}>
                <span style={{ opacity: clamp((t - at + 0.05) * 7) }}><Marker c={c} on={!!inMark} at={sc.markAt}>{w}</Marker></span>{" "}
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const LAYOUTS: Record<string, React.FC<{ c: Ctx }>> = {
  potong: LPotong, foto: LFoto, dokumen: LDokumen, peta: LPeta, judul: LJudul, angka: LAngka,
  garis_waktu: LGarisWaktu, banding: LBanding, alur: LAlur, kutipan: LKutipan,
};

// ------------------------------------------------------------------ lembar adegan (masuk + dorongan kamera)
const SceneSheet: React.FC<{ sc: KScene; th: KTheme; t0: number; f: KFonts }> = ({ sc, th, t0, f }) => {
  const { fps, width: W, height: H } = useVideoConfig();
  const frame = useCurrentFrame();
  const t = t0 + frame / fps;
  const wide = W / H > 1.15;
  const u = Math.min(W, H) / 100;
  const darkSheet = sc.dark;
  // lembar terbalik: warna tinta jadi kertas (gelap di tema terang, terang di tema gelap)
  const paper = darkSheet ? th.ink : sc.idx % 2 ? th.paper2 : th.paper;
  const ink = darkSheet ? th.paper : th.ink;
  const p = sc.enter === "none" ? 1 : ease(t, sc.start - ENTER, ENTER, Easing.out(Easing.cubic));
  const dx = sc.enter === "kiri" ? -1 : sc.enter === "kanan" ? 1 : 0;
  const dy = sc.enter === "atas" ? -1 : sc.enter === "bawah" ? 1 : 0;
  const push = 1 + 0.04 * clamp((t - sc.start) / Math.max(1, sc.end - sc.start + 0.5));
  const c: Ctx = { sc, t, W, H, u, wide, th: { ...th, paper }, ink, paper, f };
  const Comp = LAYOUTS[sc.layout] ?? LJudul;
  const rnd = mulberry(sc.seed);
  const decoX = rnd() > 0.5;
  return (
    <AbsoluteFill style={{ transform: `translate(${dx * (1 - p) * W * 1.12}px, ${dy * (1 - p) * H * 1.12}px) rotate(${(1 - p) * sc.tilt * 3}deg)` }}>
      <div style={{ position: "absolute", left: "-7%", top: "-7%", width: "114%", height: "114%", background: paper,
        backgroundImage: `${noise(sc.seed % 50, 0.75, 0.22)}, radial-gradient(ellipse at 50% 45%, transparent 55%, ${rgba("#000", darkSheet ? 0.35 : 0.12)} 100%)`,
        clipPath: torn(sc.seed, 0.9, 40), boxShadow: "0 0 80px rgba(0,0,0,0.45)" }} />
      <AbsoluteFill style={{ transform: `scale(${push})` }}>
        {!darkSheet ? (
          <div style={{ position: "absolute", [decoX ? "right" : "left"]: u * 3, top: u * 3, fontFamily: c.f.type, fontSize: u * 2.4, color: rgba(ink, 0.45), letterSpacing: u * 0.25 }}>
            {`· ${String(sc.idx + 1).padStart(2, "0")} ·`}
          </div>
        ) : null}
        <Comp c={c} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ caption per frasa
const Captions: React.FC<{ words: KWord[]; scenes: KScene[]; th: KTheme; f: KFonts }> = ({ words, scenes, th, f }) => {
  const { fps, width: W, height: H } = useVideoConfig();
  const frame = useCurrentFrame();
  const t = frame / fps;
  const u = Math.min(W, H) / 100;
  const groups = useMemo(() => {
    const out: KWord[][] = [];
    let cur: KWord[] = [];
    for (const w of words) {
      const len = cur.reduce((a, x) => a + x.t.length + 1, 0);
      const gap = cur.length ? w.s - cur[cur.length - 1].e : 0;
      if (cur.length && (cur.length >= 4 || len + w.t.length > 22 || gap > 0.5 || /[.!?]$/.test(cur[cur.length - 1].t))) {
        out.push(cur);
        cur = [];
      }
      cur.push(w);
    }
    if (cur.length) out.push(cur);
    return out;
  }, [words]);
  const sc = scenes.find((s) => t >= s.start && t < s.end);
  if (!sc || !sc.captions) return null;
  const g = groups.find((gr, i) => t >= gr[0].s - 0.05 && t < (groups[i + 1]?.[0].s ?? gr[gr.length - 1].e + 0.6) - 0.05 && t < gr[gr.length - 1].e + 0.7);
  if (!g) return null;
  const wide = W / H > 1.15;
  const fs = u * (wide ? 5 : 5.6);
  const appear = ease(t, g[0].s - 0.05, 0.12);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: H * (wide ? 0.07 : 0.115), display: "flex", justifyContent: "center",
      transform: `translateY(${(1 - appear) * u * 1.5}px)`, opacity: appear }}>
      <div style={{ background: "#FBF8F0", padding: `${u * 0.9}px ${u * 2}px`, transform: "rotate(-1.2deg)", maxWidth: W * 0.88,
        boxShadow: `${u * 0.5}px ${u * 0.6}px 0 ${th.ink === "#F2EDE3" ? "#000" : th.ink}`, fontFamily: f.caption, fontSize: fs, color: "#141414",
        lineHeight: 1.2, textAlign: "center" }}>
        {g.map((w, i) => {
          const on = t >= w.s - 0.03 && t < w.e + 0.08;
          return (
            <React.Fragment key={i}>
              <span style={{ background: on ? th.marker : "transparent", padding: `0 ${u * 0.3}px`, opacity: t >= w.s - 0.08 ? 1 : 0.35 }}>{w.t}</span>{" "}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};

// ------------------------------------------------------------------ komposisi
export const Kolase: React.FC<KolaseProps> = (props) => {
  const { fps, durationInFrames, width: W, height: H } = useVideoConfig();
  const frame = useCurrentFrame();
  const th = props.theme;
  const darkTheme = th.name === "Malam";
  const f = { ...DEFAULT_FONTS, ...(props.fonts ?? {}) };
  return (
    <AbsoluteFill style={{ background: th.paper2 }}>
      {props.scenes.map((sc, i) => {
        const from = i === 0 ? 0 : Math.max(0, Math.round((sc.start - ENTER) * fps));
        const to = i === props.scenes.length - 1 ? durationInFrames : Math.min(durationInFrames, Math.round((sc.end + 0.05) * fps));
        return (
          <Sequence key={sc.id + i} from={from} durationInFrames={Math.max(1, to - from)}>
            <SceneSheet sc={sc} th={th} t0={from / fps} f={f} />
          </Sequence>
        );
      })}
      <AbsoluteFill style={{ backgroundImage: noise(1 + (Math.floor(frame / 2) % 7), 0.95, 0.5), opacity: darkTheme ? 0.07 : 0.09,
        mixBlendMode: darkTheme ? "screen" : "multiply", pointerEvents: "none" }} />
      <Captions words={props.words} scenes={props.scenes} th={th} f={f} />
    </AbsoluteFill>
  );
};
