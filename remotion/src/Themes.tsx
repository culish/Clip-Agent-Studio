// Visual vektor untuk tema video di tab "Buat video" (lihat clipagent/themes.py).
// Semua digambar dengan SVG langsung di Remotion: gratis, tajam di resolusi apa pun, dan bergerak.
import React, { useMemo } from "react";
import { AbsoluteFill, Easing, random, useCurrentFrame, useVideoConfig } from "remotion";
import { geoBounds, geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import world from "world-atlas/countries-50m.json";
import type { Scene, Style } from "./types";

export type ThemeInfo = { id: string; overlays?: string[]; levels?: number[] };
type Pt = [number, number];
type Ctx = { f: number; fps: number; W: number; H: number; u: number; wide: boolean; idx: number; durF: number;
  art: any; style: Style; sc: Scene; startF: number; theme: ThemeInfo };

// ------------------------------------------------------------------ utilitas
const clamp = (x: number, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const ease = (f: number, start: number, len: number, fn: (t: number) => number = Easing.out(Easing.cubic)) =>
  fn(clamp((f - start) / Math.max(1, len)));
const back = (f: number, start: number, len: number) => ease(f, start, len, Easing.out(Easing.back(1.8)));
const R = (s: string) => random(s);
const hexRgb = (hex: string): [number, number, number] => {
  const h = (hex || "#000000").replace("#", "");
  const n = parseInt(h.padEnd(6, "0").slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const rgba = (hex: string, a: number) => {
  const [r, g, b] = hexRgb(hex);
  return `rgba(${r},${g},${b},${a})`;
};
const mix = (a: string, b: string, t: number) => {
  const x = hexRgb(a), y = hexRgb(b);
  const c = x.map((v, i) => Math.round(v + (y[i] - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
};
const poly = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("");
const noise = (seed: number, freq = 0.85, alpha = 0.5) =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='${freq}' numOctaves='3' seed='${seed}' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(#n)' opacity='${alpha}'/></svg>`,
  )}")`;
// garis "tangan": titik bergetar sedikit tiap 4 frame
const boil = (pts: Pt[], seed: string, f: number, amt: number): Pt[] =>
  pts.map((p, i) => [p[0] + (R(`${seed}x${i}-${Math.floor(f / 4)}`) - 0.5) * amt, p[1] + (R(`${seed}y${i}-${Math.floor(f / 4)}`) - 0.5) * amt]);
// garis bergelombang selebar layar (cakrawala, tanah)
const wavy = (x0: number, x1: number, y: number, amp: number, seed: string, n = 14): string => {
  const pts: Pt[] = [];
  for (let i = 0; i <= n; i++) pts.push([x0 + ((x1 - x0) * i) / n, y + (R(`${seed}${i}`) - 0.5) * amp]);
  return poly(pts);
};
const hills = (W: number, H: number, y: number, amp: number, seed: string, n = 5): string => {
  let d = `M0,${H} L0,${y}`;
  const step = W / n;
  for (let i = 0; i < n; i++) {
    const x1 = step * (i + 0.5), x2 = step * (i + 1);
    const y1 = y - amp * (0.4 + R(`${seed}a${i}`) * 0.8), y2 = y + (R(`${seed}b${i}`) - 0.5) * amp * 0.5;
    d += ` Q${x1.toFixed(1)},${y1.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
  }
  return d + ` L${W},${H} Z`;
};
const fmtNum = (v: number, decimals: number) =>
  v.toLocaleString("id-ID", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

// ------------------------------------------------------------------ STICKMAN
const SHOULDER: Pt = [0, -66];
const HIP: Pt = [0, -38];
type Pose = { arms: [Pt[], Pt[]]; legs: [Pt[], Pt[]]; head: Pt; mouth: string; lift: number; dx: number; neck?: Pt; hip?: Pt };

const pose = (name: string, f: number, fps: number): Pose => {
  const t = f / fps;
  const breath = Math.sin(t * 2.2) * 0.8;
  const S: Pt = [SHOULDER[0], SHOULDER[1] + breath * 0.3];
  const down: [Pt[], Pt[]] = [[S, [-8, -52], [-12, -40]], [S, [8, -52], [12, -40]]];
  const legs: [Pt[], Pt[]] = [[HIP, [-6, -19], [-12, 0]], [HIP, [6, -19], [12, 0]]];
  const base: Pose = { arms: down, legs, head: [0, -86], mouth: "smile", lift: breath * 0.3, dx: 0 };
  switch (name) {
    case "wave": {
      const a = Math.sin(t * 9) * 7;
      return { ...base, arms: [down[0], [S, [17, -76], [21 + a, -96]]], mouth: "big" };
    }
    case "point":
      return { ...base, arms: [down[0], [S, [20, -67 + breath], [44 + Math.sin(t * 3) * 1.5, -71]]] };
    case "think":
      return { ...base, arms: [[S, [-10, -54], [7, -52]], [S, [15, -54], [6, -79]]], head: [3, -86], mouth: "flat" };
    case "happy": {
      const b = Math.abs(Math.sin(t * 5)) * 3;
      return { ...base, arms: [[S, [-16, -80], [-26, -98]], [S, [16, -80], [26, -98]]], mouth: "big", lift: -b };
    }
    case "sad":
      return { ...base, arms: [[S, [-5, -52], [-7, -38]], [S, [5, -52], [7, -38]]], legs: [[HIP, [-4, -19], [-8, 0]], [HIP, [4, -19], [8, 0]]],
        head: [4, -83], mouth: "frown", lift: 1.5 };
    case "run": {
      const p = t * Math.PI * 2 * 1.6;
      const s1 = Math.sin(p), s2 = Math.sin(p + Math.PI);
      const leg = (s: number, c: number): Pt[] => [HIP, [s * 12 + 5, -21], [s * 20 - 3, -2 - Math.max(0, c) * 9]];
      const arm = (s: number): Pt[] => [[S[0] + 3, S[1]], [s * -12 + 4, -55], [s * -18 + 12, -50 - Math.max(0, s) * 8]];
      return { ...base, legs: [leg(s1, Math.cos(p)), leg(s2, -Math.cos(p))], arms: [arm(s1), arm(s2)], mouth: "open",
        lift: -Math.abs(Math.sin(p)) * 3, dx: 0, neck: [4, -75], head: [6, -86] };
    }
    case "shrug": {
      const s = Math.max(0, Math.sin(t * 2.5)) * 3;
      return { ...base, arms: [[S, [-18, -58 - s], [-29, -73 - s]], [S, [18, -58 - s], [29, -73 - s]]], mouth: "flat",
        head: [Math.sin(t * 2.5) * 2, -86] };
    }
    case "sit": {
      const Hs: Pt = [0, -30];
      const Ss: Pt = [0, -58 + breath * 0.3];
      return { ...base, neck: [0, -68], hip: Hs, arms: [[Ss, [6, -44], [16, -32]], [Ss, [10, -44], [20, -32]]],
        legs: [[Hs, [18, -30], [18, 0]], [Hs, [14, -30], [14, 0]]], head: [0, -78], mouth: "smile" };
    }
    case "celebrate": {
      const j = Math.abs(Math.sin(t * 6)) * 10;
      return { ...base, arms: [[S, [-14, -82], [-20, -103]], [S, [14, -82], [20, -103]]],
        legs: [[HIP, [-10, -24], [-15, -7]], [HIP, [10, -24], [15, -7]]], mouth: "big", lift: -j };
    }
    case "scared": {
      const sh = Math.sin(t * 40) * 0.9;
      return { ...base, arms: [[S, [-15, -74], [-7, -89]], [S, [15, -74], [7, -89]]],
        legs: [[HIP, [-11, -20], [-14, 0]], [HIP, [11, -20], [14, 0]]], mouth: "o", dx: sh, lift: 3 };
    }
    case "idea":
      return { ...base, arms: [down[0], [S, [15, -80], [15, -101]]], mouth: "big" };
    default:
      return base;
  }
};

const Face: React.FC<{ head: Pt; mouth: string; sw: number; ink: string }> = ({ head, mouth, sw, ink }) => {
  const [x, y] = head;
  const m: Record<string, string> = {
    smile: `M${x - 4},${y + 3} Q${x},${y + 6.5} ${x + 4},${y + 3}`,
    big: `M${x - 5},${y + 2} Q${x},${y + 9} ${x + 5},${y + 2} Z`,
    flat: `M${x - 3.5},${y + 4} L${x + 3.5},${y + 4}`,
    frown: `M${x - 4},${y + 6} Q${x},${y + 2.5} ${x + 4},${y + 6}`,
    open: `M${x - 2.5},${y + 3} Q${x},${y + 8} ${x + 2.5},${y + 3} Z`,
  };
  return (
    <g>
      <circle cx={x - 4} cy={y - 2} r={1.3} fill={ink} />
      <circle cx={x + 4} cy={y - 2} r={1.3} fill={ink} />
      {mouth === "o" ? <ellipse cx={x} cy={y + 4.5} rx={2.2} ry={3} fill="none" stroke={ink} strokeWidth={sw * 0.7} />
        : <path d={m[mouth] ?? m.smile} fill={mouth === "big" || mouth === "open" ? ink : "none"} stroke={ink} strokeWidth={sw * 0.7}
            strokeLinecap="round" strokeLinejoin="round" />}
    </g>
  );
};

const StickFigure: React.FC<{ name: string; f: number; fps: number; x: number; y: number; k: number; flip?: boolean; seed: string;
  delay: number }> = ({ name, f, fps, x, y, k, flip, seed, delay }) => {
  const p = pose(name, f, fps);
  const ink = "#161616";
  const sw = 1.7;
  const draw = ease(f, delay, 16, Easing.inOut(Easing.quad));
  const neckTop: Pt = p.neck ?? [0, -75];
  const hip: Pt = p.hip ?? HIP;
  const lines: Pt[][] = [[neckTop, hip], ...p.arms, ...p.legs];
  const dash = { pathLength: 1, strokeDasharray: "1 1", strokeDashoffset: 1 - draw };
  return (
    <g transform={`translate(${x + p.dx * k},${y + p.lift * k}) scale(${flip ? -k : k},${k})`}>
      {name === "sit" ? <path d={poly(boil([[-13, 0], [-13, -29], [12, -29], [12, 0]], `${seed}ch`, f, 0.6))} fill="none" stroke="#8B5A2B"
        strokeWidth={sw * 1.1} strokeLinecap="round" strokeLinejoin="round" {...dash} /> : null}
      {lines.map((l, i) => (
        <path key={i} d={poly(boil(l, `${seed}${i}`, f, 0.9))} fill="none" stroke={ink} strokeWidth={sw} strokeLinecap="round"
          strokeLinejoin="round" {...dash} />
      ))}
      <circle cx={p.head[0]} cy={p.head[1]} r={11} fill="#FFFFFF" stroke={ink} strokeWidth={sw} {...dash} />
      <g opacity={clamp((draw - 0.6) * 3)}>
        <Face head={p.head} mouth={p.mouth} sw={sw} ink={ink} />
        {name === "scared" ? <path d="M13,-96 q2,4 0,6 q-2,-2 0,-6" fill="#7EC8F2" stroke={ink} strokeWidth={0.6} /> : null}
        {name === "think" ? (
          <g fill={ink}>{[0, 1, 2].map((i) => <circle key={i} cx={18 + i * 6} cy={-104 - i * 5} r={1.2 + i * 0.6}
            opacity={clamp(((f / fps) * 2 - i) % 3)} />)}</g>
        ) : null}
      </g>
    </g>
  );
};

const C = { yellow: "#F5B700", blue: "#3D8BFD", sky: "#BFE3F7", green: "#2E9E5B", red: "#E4572E", gray: "#9AA0A6",
  brown: "#8B5A2B", ink: "#161616", orange: "#F28C28", purple: "#7B5CC4" };

// Benda: digambar di kotak -50..50, lalu diskalakan
const Prop: React.FC<{ name: string; f: number; fps: number; seed: string }> = ({ name, f, fps, seed }) => {
  const t = f / fps;
  const sw = 3.2;
  const st = { stroke: C.ink, strokeWidth: sw, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const b = (pts: Pt[]) => poly(boil(pts, seed + name, f, 1.6));
  switch (name) {
    case "sun":
      return (
        <g>
          <g transform={`rotate(${t * 20})`}>{Array.from({ length: 10 }, (_, i) => {
            const a = (i / 10) * Math.PI * 2;
            return <path key={i} d={b([[Math.cos(a) * 30, Math.sin(a) * 30], [Math.cos(a) * 44, Math.sin(a) * 44]])} {...st} stroke={C.yellow} strokeWidth={4} />;
          })}</g>
          <circle r={22} fill={C.yellow} {...st} />
        </g>
      );
    case "cloud":
    case "rain":
      return (
        <g>
          <path d="M-36,8 a14,14 0 0 1 6,-26 a18,18 0 0 1 32,-6 a14,14 0 0 1 24,8 a12,12 0 0 1 -2,24 Z" fill="#FFFFFF" {...st} />
          {name === "rain" ? Array.from({ length: 5 }, (_, i) => {
            const y = ((t * 60 + i * 13) % 34);
            return <path key={i} d={`M${-26 + i * 13},${16 + y} l-3,8`} stroke={C.blue} strokeWidth={3} strokeLinecap="round" />;
          }) : null}
        </g>
      );
    case "moon":
      return <path d="M10,-34 a34,34 0 1 0 22,58 a28,28 0 1 1 -22,-58 Z" fill="#FFE9A6" {...st} />;
    case "star": {
      const pts: Pt[] = Array.from({ length: 10 }, (_, i) => {
        const a = -Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? 15 : 36;
        return [Math.cos(a) * r, Math.sin(a) * r];
      });
      return <path d={poly(pts) + "Z"} fill={C.yellow} {...st} transform={`scale(${1 + Math.sin(t * 4) * 0.06})`} />;
    }
    case "house":
      return (
        <g>
          <path d={b([[-32, 40], [-32, -4], [32, -4], [32, 40], [-32, 40]])} fill="#FFF3E0" {...st} />
          <path d={b([[-42, -2], [0, -40], [42, -2]])} fill={C.red} {...st} />
          <path d="M-8,40 v-24 h16 v24" fill={C.brown} {...st} />
          <rect x={14} y={6} width={12} height={12} fill={C.sky} {...st} strokeWidth={2.4} />
        </g>
      );
    case "tree":
      return (
        <g>
          <path d={b([[-5, 46], [-5, 6], [5, 6], [5, 46]])} fill={C.brown} {...st} />
          <path d="M0,-44 a20,20 0 0 1 20,18 a18,18 0 0 1 4,34 a20,20 0 0 1 -48,0 a18,18 0 0 1 4,-34 a20,20 0 0 1 20,-18 Z"
            fill={C.green} {...st} transform={`rotate(${Math.sin(t * 1.5) * 2})`} />
        </g>
      );
    case "money":
      return (
        <g transform={`rotate(${-8 + Math.sin(t * 2) * 3})`}>
          <rect x={-42} y={-22} width={84} height={44} rx={5} fill="#A8E6B8" {...st} />
          <circle r={12} fill="#FFFFFF" {...st} strokeWidth={2.4} />
          <text y={6} textAnchor="middle" fontFamily="Caveat Bold" fontSize={20} fill={C.ink}>$</text>
        </g>
      );
    case "coin":
      return (
        <g>{[0, 1, 2].map((i) => (
          <g key={i} transform={`translate(${(i - 1) * 4},${20 - i * 12})`}>
            <ellipse rx={28} ry={10} fill={C.yellow} {...st} />
          </g>
        ))}<ellipse cy={-4} rx={18} ry={5} fill="none" stroke={C.ink} strokeWidth={2} /></g>
      );
    case "clock":
      return (
        <g>
          <circle r={36} fill="#FFFFFF" {...st} />
          <path d={`M0,0 L${Math.cos(t * 2 - 1.57) * 24},${Math.sin(t * 2 - 1.57) * 24}`} {...st} />
          <path d={`M0,0 L${Math.cos(t * 0.2) * 15},${Math.sin(t * 0.2) * 15}`} {...st} />
          {[0, 1, 2, 3].map((i) => <circle key={i} cx={Math.cos(i * 1.5708) * 29} cy={Math.sin(i * 1.5708) * 29} r={2.2} fill={C.ink} />)}
        </g>
      );
    case "heart":
      return <path d="M0,34 C-46,4 -34,-34 0,-14 C34,-34 46,4 0,34 Z" fill={C.red} {...st} transform={`scale(${1 + Math.max(0, Math.sin(t * 6)) * 0.1})`} />;
    case "bulb":
      return (
        <g>
          {Array.from({ length: 7 }, (_, i) => {
            const a = -Math.PI + (i / 6) * Math.PI;
            const r0 = 34 + Math.sin(t * 6) * 2;
            return <path key={i} d={`M${Math.cos(a) * r0},${Math.sin(a) * r0 - 8} L${Math.cos(a) * (r0 + 10)},${Math.sin(a) * (r0 + 10) - 8}`} stroke={C.yellow} strokeWidth={4} strokeLinecap="round" />;
          })}
          <path d="M-12,22 C-12,8 -24,4 -24,-10 A24,24 0 1 1 24,-10 C24,4 12,8 12,22 Z" fill="#FFE97A" {...st} />
          <path d="M-10,28 h20 M-8,34 h16" {...st} />
        </g>
      );
    case "question":
    case "exclaim":
      return <text y={30} textAnchor="middle" fontFamily="Caveat Bold" fontSize={96} fill={C.red}
        transform={`rotate(${Math.sin(t * 3) * 6})`}>{name === "question" ? "?" : "!"}</text>;
    case "chart_up":
    case "chart_down": {
      const up = name === "chart_up";
      const p = clamp(t / 1.2);
      const pts: Pt[] = up ? [[-36, 26], [-16, 10], [-2, 18], [18, -8], [36, -28]] : [[-36, -26], [-16, -6], [-2, -14], [18, 10], [36, 28]];
      return (
        <g>
          <path d="M-42,-40 L-42,38 L44,38" fill="none" {...st} />
          <path d={poly(pts)} fill="none" stroke={up ? C.green : C.red} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round"
            pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - p} />
          {p > 0.95 ? <path d={up ? "M24,-30 L37,-29 L33,-16" : "M24,30 L37,29 L33,16"} fill="none" stroke={up ? C.green : C.red} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" /> : null}
        </g>
      );
    }
    case "book":
      return (
        <g>
          <path d="M0,-20 C-14,-30 -32,-30 -44,-24 L-44,26 C-32,20 -14,20 0,30 Z" fill="#FFFFFF" {...st} />
          <path d="M0,-20 C14,-30 32,-30 44,-24 L44,26 C32,20 14,20 0,30 Z" fill="#FFF3E0" {...st} />
          <path d="M-34,-12 h22 M-34,-2 h22 M12,-12 h22 M12,-2 h22" stroke={C.gray} strokeWidth={2} />
        </g>
      );
    case "phone":
      return (
        <g transform={`rotate(${Math.sin(t * 2) * 4})`}>
          <rect x={-20} y={-38} width={40} height={76} rx={7} fill="#FFFFFF" {...st} />
          <rect x={-14} y={-28} width={28} height={50} rx={2} fill={C.sky} stroke="none" />
          <circle cy={30} r={2.5} fill={C.ink} />
        </g>
      );
    case "laptop":
      return (
        <g>
          <rect x={-34} y={-30} width={68} height={44} rx={4} fill={C.sky} {...st} />
          <path d={b([[-46, 22], [46, 22], [38, 14], [-38, 14], [-46, 22]])} fill="#FFFFFF" {...st} />
        </g>
      );
    case "globe":
      return (
        <g>
          <circle r={36} fill={C.sky} {...st} />
          <path d="M-20,-24 q10,6 4,16 q-8,6 2,14 q8,4 0,14 M10,-28 q12,10 18,4 M6,6 q12,-4 18,10" fill="none" stroke={C.green} strokeWidth={5} strokeLinecap="round" />
          <ellipse rx={16} ry={36} fill="none" stroke={C.ink} strokeWidth={1.8} transform={`scale(${Math.cos(t)},1)`} />
        </g>
      );
    case "mountain":
      return (
        <g>
          <path d={b([[-48, 38], [-12, -30], [10, 4], [24, -14], [48, 38], [-48, 38]])} fill="#C9D3DD" {...st} />
          <path d="M-22,-12 L-12,-30 L-2,-12 L-8,-16 L-14,-10 Z" fill="#FFFFFF" stroke={C.ink} strokeWidth={2} />
        </g>
      );
    case "trophy":
      return (
        <g transform={`rotate(${Math.sin(t * 3) * 4})`}>
          <path d="M-24,-36 h48 v14 a24,24 0 0 1 -48,0 Z" fill={C.yellow} {...st} />
          <path d="M-24,-30 h-10 a10,10 0 0 0 12,18 M24,-30 h10 a10,10 0 0 1 -12,18" fill="none" {...st} />
          <path d="M-5,0 h10 v18 h-10 Z M-20,18 h40 v12 h-40 Z" fill={C.yellow} {...st} />
        </g>
      );
    case "fire": {
      const fl = Math.sin(t * 14) * 3;
      return (
        <g>
          <path d={`M0,38 C-30,36 -34,6 -16,-12 C-14,2 -6,4 -4,-6 C-6,-24 4,-38 10,${-44 + fl} C10,-24 34,-14 30,12 C28,30 16,38 0,38 Z`} fill={C.orange} {...st} />
          <path d={`M0,34 C-12,32 -14,16 -4,6 C-2,14 4,14 6,${4 + fl * 0.5} C12,14 14,30 0,34 Z`} fill={C.yellow} stroke="none" />
        </g>
      );
    }
    case "water":
      return <path d="M0,-40 C14,-18 30,0 30,14 A30,30 0 0 1 -30,14 C-30,0 -14,-18 0,-40 Z" fill="#7EC8F2" {...st}
        transform={`translate(0,${Math.sin(t * 3) * 3})`} />;
    case "food":
      return (
        <g>
          {[-12, 0, 12].map((x, i) => <path key={i} d={`M${x},-14 q-6,-8 0,-16 q6,-8 0,-16`} fill="none" stroke={C.gray} strokeWidth={2.5}
            strokeLinecap="round" opacity={0.5 + 0.5 * Math.sin(t * 3 + i)} />)}
          <path d="M-40,-6 h80 a40,34 0 0 1 -80,0 Z" fill="#FFFFFF" {...st} />
          <path d="M-30,-6 q15,-10 30,0 q15,-10 30,0" fill="none" stroke={C.orange} strokeWidth={4} />
        </g>
      );
    case "car":
      return (
        <g transform={`translate(${Math.sin(t * 2) * 3},0)`}>
          <path d={b([[-46, 18], [-46, -2], [-30, -4], [-18, -24], [16, -24], [30, -4], [46, 0], [46, 18], [-46, 18]])} fill={C.blue} {...st} />
          <path d="M-14,-18 h12 v12 h-20 Z M4,-18 h10 l10,12 h-20 Z" fill={C.sky} stroke={C.ink} strokeWidth={2} />
          {[-26, 26].map((x) => <circle key={x} cx={x} cy={20} r={9} fill={C.ink} />)}
        </g>
      );
    case "check":
      return <path d="M-30,0 L-8,24 L32,-26" fill="none" stroke={C.green} strokeWidth={9} strokeLinecap="round" strokeLinejoin="round"
        pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - clamp(t * 2)} />;
    case "cross":
      return <path d="M-26,-26 L26,26 M26,-26 L-26,26" fill="none" stroke={C.red} strokeWidth={9} strokeLinecap="round" />;
    case "rainbow":
      return (
        <g>{[C.red, C.orange, C.yellow, C.green, C.blue, C.purple].map((c, i) => (
          <path key={i} d={`M${-46 + i * 5},20 A${46 - i * 5},${46 - i * 5} 0 0 1 ${46 - i * 5},20`} fill="none" stroke={c} strokeWidth={5}
            pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - clamp(t * 1.4 - i * 0.05)} />
        ))}</g>
      );
    case "bed":
      return (
        <g>
          <path d={b([[-46, 24], [-46, -18], [-40, -18], [-40, 4], [46, 4], [46, 24]])} fill="none" {...st} />
          <rect x={-40} y={-8} width={84} height={14} rx={4} fill={C.sky} {...st} strokeWidth={2.4} />
          <rect x={-36} y={-18} width={22} height={12} rx={5} fill="#FFFFFF" {...st} strokeWidth={2.4} />
          <text x={30} y={-20 - (t * 10) % 14} fontFamily="Caveat Bold" fontSize={18} fill={C.blue}>z</text>
        </g>
      );
    case "gift":
      return (
        <g transform={`rotate(${Math.sin(t * 5) * 3})`}>
          <rect x={-32} y={-14} width={64} height={48} fill={C.red} {...st} />
          <rect x={-36} y={-26} width={72} height={14} fill={C.red} {...st} />
          <path d="M0,-26 v60" stroke={C.yellow} strokeWidth={8} />
          <path d="M0,-26 q-20,-22 -24,-6 q4,8 24,6 q20,2 24,-6 q-4,-16 -24,6" fill={C.yellow} stroke={C.ink} strokeWidth={2.4} />
        </g>
      );
    case "calendar": {
      const done = Math.floor(clamp(t / 2) * 9);
      return (
        <g>
          <rect x={-38} y={-34} width={76} height={72} rx={5} fill="#FFFFFF" {...st} />
          <rect x={-38} y={-34} width={76} height={16} rx={5} fill={C.red} {...st} strokeWidth={2.4} />
          {Array.from({ length: 9 }, (_, i) => {
            const x = -24 + (i % 3) * 24, y = -4 + Math.floor(i / 3) * 14;
            return i < done ? <path key={i} d={`M${x - 5},${y} l4,4 l7,-8`} fill="none" stroke={C.green} strokeWidth={3} strokeLinecap="round" />
              : <rect key={i} x={x - 5} y={y - 5} width={10} height={9} fill="none" stroke={C.gray} strokeWidth={1.6} />;
          })}
        </g>
      );
    }
    case "arrow":
      return <path d="M-40,20 C-20,-30 20,-30 34,-4 M34,-4 L36,-24 M34,-4 L16,-8" fill="none" stroke={C.red} strokeWidth={6} strokeLinecap="round"
        strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - clamp(t * 1.5)} />;
    default:
      return null;
  }
};

const SKY_PROPS = new Set(["sun", "cloud", "rain", "moon", "star", "rainbow"]);
const GROUND_PROPS = new Set(["house", "tree", "mountain", "car", "bed", "gift", "food", "trophy", "book", "laptop"]);

const Stickman: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, fps, W, H, wide, art, idx } = c;
  const groundY = wide ? H * 0.64 : H * 0.6;
  const figH = wide ? H * 0.32 : H * 0.22;
  const k = figH / 100;
  const two = art.people === 2;
  const xs = two ? [W * (wide ? 0.38 : 0.3), W * (wide ? 0.62 : 0.7)] : [W * (wide ? 0.44 : 0.5)];
  const props: string[] = art.props || [];
  const skyL: Pt[] = wide ? [[W * 0.22, H * 0.3], [W * 0.78, H * 0.3], [W * 0.5, H * 0.24]]
    : [[W * 0.25, groundY - figH * 1.55], [W * 0.75, groundY - figH * 1.55], [W * 0.5, groundY - figH * 1.95]];
  const groundL: Pt[] = wide ? [[W * 0.78, groundY], [W * 0.2, groundY]] : [[W * (two ? 0.5 : 0.8), groundY], [W * 0.2, groundY]];
  const handL: Pt[] = [[two ? W * 0.5 : W * (wide ? 0.66 : 0.76), groundY - figH * (two ? 1.35 : 0.95)], [W * 0.24, groundY - figH * 1.0],
    [W * (wide ? 0.8 : 0.8), groundY - figH * (two ? 1.9 : 1.7)]];
  const used = { sky: 0, ground: 0, hand: 0 };
  const placed = props.map((p) => {
    const kind = SKY_PROPS.has(p) ? "sky" : GROUND_PROPS.has(p) ? "ground" : "hand";
    const list = kind === "sky" ? skyL : kind === "ground" ? groundL : handL;
    const pos = list[used[kind as keyof typeof used]++ % list.length];
    return { p, kind, pos };
  });
  if (art.pose === "idea" && !props.includes("bulb")) placed.push({ p: "bulb", kind: "hand", pos: [xs[0], groundY - figH * 1.45] });
  const ps = figH * (wide ? 0.42 : 0.52);
  const label: string = art.label || "";
  const lab = ease(f, fps * 0.7, fps * 0.6, Easing.inOut(Easing.quad));
  const labY = wide ? groundY + H * 0.085 : groundY + figH * 0.32;
  const labSize = wide ? H * (label.length > 16 ? 0.05 : 0.06) : W * (label.length > 16 ? 0.06 : 0.08);
  return (
    <AbsoluteFill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <path d={wavy(W * 0.06, W * 0.94, groundY + 2, figH * 0.03, `g${idx}`)} fill="none" stroke="#B9B9B2" strokeWidth={figH * 0.012}
          strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - ease(f, 0, fps * 0.5)} />
        {placed.map(({ p, kind, pos }, i) => {
          const d = fps * (0.35 + i * 0.25);
          const s = back(f, d, fps * 0.45);
          const y = kind === "ground" ? pos[1] - ps * 0.42 : pos[1];
          return (
            <g key={i} transform={`translate(${pos[0]},${y}) scale(${(ps / 100) * s})`} opacity={clamp(s * 3)}>
              <Prop name={p} f={Math.max(0, f - d)} fps={fps} seed={`${idx}-${i}`} />
            </g>
          );
        })}
        {xs.map((x, i) => (
          <StickFigure key={i} name={i === 0 ? art.pose : art.pose2} f={f} fps={fps} x={x} y={groundY} k={k} flip={i === 1}
            seed={`f${idx}-${i}`} delay={i * fps * 0.25} />
        ))}
        {art.pose === "run" ? [0, 1, 2].map((i) => (
          <path key={i} d={`M${xs[0] - figH * (0.35 + i * 0.06)},${groundY - figH * (0.3 + i * 0.18)} h${-figH * 0.25}`} stroke="#B9B9B2"
            strokeWidth={figH * 0.014} strokeLinecap="round" opacity={0.5 + 0.5 * Math.sin(f / 3 + i)} />
        )) : null}
        {art.pose === "celebrate" ? Array.from({ length: 14 }, (_, i) => {
          const a = R(`cf${idx}${i}`) * Math.PI * 2;
          const r = figH * (0.5 + ((f / fps) * 0.6 + R(`cr${i}`)) % 1 * 0.9);
          return <rect key={i} x={xs[0] + Math.cos(a) * r} y={groundY - figH * 0.9 + Math.sin(a) * r * 0.7} width={figH * 0.03}
            height={figH * 0.05} fill={[C.red, C.yellow, C.blue, C.green][i % 4]} transform={`rotate(${f * 6 + i * 40} ${xs[0] + Math.cos(a) * r} ${groundY - figH * 0.9 + Math.sin(a) * r * 0.7})`} />;
        }) : null}
        {label ? (
          <g>
            <clipPath id={`lab${idx}`}>
              <rect x={W / 2 - labSize * label.length * 0.3} y={labY - labSize} width={labSize * label.length * 0.6 * lab} height={labSize * 1.4} />
            </clipPath>
            <text x={W / 2} y={labY} textAnchor="middle" fontFamily="Caveat Bold" fontSize={labSize} fill="#1A1A1A"
              clipPath={`url(#lab${idx})`}>{label}</text>
            <path d={wavy(W / 2 - labSize * label.length * 0.22, W / 2 + labSize * label.length * 0.22, labY + labSize * 0.22, labSize * 0.08, `u${idx}`, 6)}
              fill="none" stroke={c.style.accent} strokeWidth={labSize * 0.09} strokeLinecap="round" pathLength={1} strokeDasharray="1 1"
              strokeDashoffset={1 - ease(f, fps * 1.1, fps * 0.4)} opacity={0.85} />
          </g>
        ) : null}
      </svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ LOFI
const LOFI_PAL: Record<string, { sky: [string, string]; wall: [string, string]; city: string; warm: string; moon: boolean }> = {
  malam: { sky: ["#0E1430", "#2C3566"], wall: ["#1E1A2B", "#2A2338"], city: "#121a33", warm: "#F5C27A", moon: true },
  hujan: { sky: ["#151C29", "#3A4A5E"], wall: ["#1A1D26", "#252A35"], city: "#141b26", warm: "#F2B86B", moon: false },
  senja: { sky: ["#3B2A55", "#F08A5D"], wall: ["#2A1F2E", "#3A2A3A"], city: "#2a1d33", warm: "#F7C98A", moon: false },
  pagi: { sky: ["#9EC5E8", "#F7D9B5"], wall: ["#4A3F44", "#5B4E52"], city: "#7d8fa6", warm: "#FFE2B0", moon: false },
};

const City: React.FC<{ x0: number; x1: number; base: number; h: number; color: string; seed: string; f: number; lit: string; n?: number }> = ({
  x0, x1, base, h, color, seed, f, lit, n = 14 }) => {
  const w = (x1 - x0) / n;
  return (
    <g>
      {Array.from({ length: n }, (_, i) => {
        const bh = h * (0.35 + R(`${seed}h${i}`) * 0.65);
        const x = x0 + i * w;
        const cols = 3, rows = Math.max(2, Math.floor(bh / (w * 0.45)));
        return (
          <g key={i}>
            <rect x={x} y={base - bh} width={w * 0.96} height={bh} fill={color} />
            {Array.from({ length: cols * rows }, (_, j) => {
              const on = R(`${seed}${i}w${j}`) > 0.62;
              if (!on) return null;
              const tw = 0.65 + 0.35 * Math.sin(f / 20 + j + i);
              return <rect key={j} x={x + w * (0.15 + (j % cols) * 0.27)} y={base - bh + w * 0.25 + Math.floor(j / cols) * w * 0.45}
                width={w * 0.14} height={w * 0.18} fill={lit} opacity={tw} />;
            })}
          </g>
        );
      })}
    </g>
  );
};

const Person: React.FC<{ x: number; y: number; s: number; color: string; rim: string; hood?: boolean; f: number }> = ({ x, y, s, color, rim, hood = true, f }) => {
  const b = Math.sin(f / 40) * s * 0.006;
  return (
    <g transform={`translate(${x},${y + b})`}>
      <path d={`M${-s * 0.42},0 C${-s * 0.42},${-s * 0.42} ${-s * 0.28},${-s * 0.58} 0,${-s * 0.6} C${s * 0.28},${-s * 0.58} ${s * 0.42},${-s * 0.42} ${s * 0.42},0 Z`} fill={color} />
      {hood ? <path d={`M${-s * 0.2},${-s * 0.56} C${-s * 0.26},${-s * 0.86} ${-s * 0.12},${-s * 0.97} 0,${-s * 0.97} C${s * 0.12},${-s * 0.97} ${s * 0.26},${-s * 0.86} ${s * 0.2},${-s * 0.56} Z`} fill={color} /> : null}
      <circle cx={0} cy={-s * 0.75} r={s * 0.165} fill={hood ? mix(color, "#000000", 0.25) : "#1a1410"} />
      {hood ? <path d={`M${-s * 0.21},${-s * 0.72} C${-s * 0.22},${-s * 0.98} ${s * 0.22},${-s * 0.98} ${s * 0.21},${-s * 0.72}`} fill="none" stroke={rim} strokeWidth={s * 0.012} opacity={0.6} />
        : <path d={`M${-s * 0.2},${-s * 0.78} C${-s * 0.18},${-s * 0.98} ${s * 0.18},${-s * 0.98} ${s * 0.2},${-s * 0.78}`} fill="#2a2018" />}
      <path d={`M${-s * 0.42},0 C${-s * 0.42},${-s * 0.42} ${-s * 0.28},${-s * 0.58} 0,${-s * 0.6}`} fill="none" stroke={rim} strokeWidth={s * 0.016} opacity={0.55} />
    </g>
  );
};

const Steam: React.FC<{ x: number; y: number; s: number; f: number; color?: string }> = ({ x, y, s, f, color = "#FFFFFF" }) => (
  <g>{[0, 1, 2].map((i) => {
    const ph = ((f / 50 + i / 3) % 1);
    return <path key={i} d={`M${x + (i - 1) * s * 0.18},${y - ph * s} q${s * 0.12},${-s * 0.2} 0,${-s * 0.4} q${-s * 0.12},${-s * 0.2} 0,${-s * 0.4}`}
      fill="none" stroke={color} strokeWidth={s * 0.05} strokeLinecap="round" opacity={(1 - ph) * 0.45} />;
  })}</g>
);

const Lofi: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, W, H, wide, art, idx, durF } = c;
  const pal = LOFI_PAL[art.time] || LOFI_PAL.malam;
  const zoom = 1 + 0.05 * clamp(f / Math.max(1, durF));
  const id = `lf${idx}`;
  const u = Math.min(W, H) / 100;
  let body: React.ReactNode;
  const sky = (
    <linearGradient id={`${id}sky`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={pal.sky[0]} /><stop offset="1" stopColor={pal.sky[1]} /></linearGradient>
  );
  const bokeh = (x0: number, y0: number, w: number, h: number, n: number, drift = 0) => Array.from({ length: n }, (_, i) => {
    const x = x0 + ((R(`${id}bx${i}`) * w + f * drift * (0.5 + R(`${id}bs${i}`))) % w + w) % w;
    const y = y0 + R(`${id}by${i}`) * h;
    const r = u * (0.8 + R(`${id}br${i}`) * 2.6);
    const col = R(`${id}bc${i}`) > 0.5 ? pal.warm : "#9FC4FF";
    return <circle key={i} cx={x} cy={y} r={r} fill={col} opacity={0.18 + 0.25 * (0.5 + 0.5 * Math.sin(f / 25 + i))} filter={`url(#${id}blur)`} />;
  });
  if (art.place === "jalan") {
    const ground = H * (wide ? 0.66 : 0.62);
    const walk = clamp(f / Math.max(1, durF));
    const px = W * (0.78 - walk * 0.3);
    body = (
      <g>
        <rect width={W} height={H} fill={`url(#${id}sky)`} />
        {pal.moon ? <circle cx={W * 0.78} cy={H * 0.16} r={u * 5} fill="#F3E9C6" opacity={0.9} /> : null}
        <g opacity={0.55}><City x0={-W * 0.05} x1={W * 1.05} base={ground} h={H * 0.34} color={mix(pal.city, pal.sky[1], 0.35)} seed={`${id}c1`} f={f} lit={pal.warm} n={11} /></g>
        <City x0={-W * 0.1} x1={W * 1.1} base={ground} h={H * 0.24} color={pal.city} seed={`${id}c2`} f={f} lit={pal.warm} n={8} />
        <rect y={ground} width={W} height={H - ground} fill={mix(pal.wall[0], "#000000", 0.25)} />
        {Array.from({ length: 9 }, (_, i) => (
          <rect key={i} x={W * (0.05 + i * 0.11)} y={ground + u} width={u * 1.4} height={H * 0.18} fill={i % 2 ? pal.warm : "#9FC4FF"}
            opacity={0.12 + 0.06 * Math.sin(f / 9 + i)} filter={`url(#${id}blur)`} />
        ))}
        <g>
          <rect x={W * 0.16} y={ground - H * 0.36} width={u * 1.1} height={H * 0.36} fill="#0b0d14" />
          <path d={`M${W * 0.16},${ground - H * 0.36} q${u * 6},${-u * 2} ${u * 8},${u * 2}`} fill="none" stroke="#0b0d14" strokeWidth={u * 1.1} />
          <circle cx={W * 0.16 + u * 8} cy={ground - H * 0.355} r={u * 9} fill={`url(#${id}glow)`} />
          <ellipse cx={W * 0.16 + u * 8} cy={ground + H * 0.08} rx={u * 10} ry={u * 2} fill={pal.warm} opacity={0.18} filter={`url(#${id}blur)`} />
        </g>
        <g transform={`translate(${px},${ground + H * 0.05})`}>
          <path d={`M${-u * 9},${-u * 15} a${u * 9},${u * 6} 0 0 1 ${u * 18},0 Z`} fill="#3a3f55" />
          <path d={`M0,${-u * 15} v${u * 3}`} stroke="#0b0d14" strokeWidth={u * 0.4} />
          <rect x={-u * 2.2} y={-u * 12} width={u * 4.4} height={u * 9} rx={u * 1.6} fill="#0b0d14" />
          <circle cy={-u * 13} r={u * 1.8} fill="#0b0d14" />
          <path d={`M${-u * 1.2},${-u * 3} l${Math.sin(f / 5) * u},${u * 4} M${u * 1.2},${-u * 3} l${-Math.sin(f / 5) * u},${u * 4}`} stroke="#0b0d14" strokeWidth={u * 1.2} strokeLinecap="round" />
        </g>
      </g>
    );
  } else if (art.place === "atap") {
    const ledge = H * (wide ? 0.72 : 0.66);
    body = (
      <g>
        <rect width={W} height={H} fill={`url(#${id}sky)`} />
        {pal.moon ? <g><circle cx={W * 0.72} cy={H * 0.18} r={u * 9} fill={`url(#${id}glow)`} opacity={0.5} /><circle cx={W * 0.72} cy={H * 0.18} r={u * 4.5} fill="#F3E9C6" /></g> : null}
        <g opacity={0.6}><City x0={-W * 0.05} x1={W * 1.05} base={ledge - H * 0.04} h={H * 0.22} color={mix(pal.city, pal.sky[1], 0.4)} seed={`${id}a1`} f={f} lit={pal.warm} n={16} /></g>
        <City x0={-W * 0.1} x1={W * 1.1} base={ledge - H * 0.02} h={H * 0.14} color={pal.city} seed={`${id}a2`} f={f} lit={pal.warm} n={12} />
        {bokeh(0, ledge - H * 0.2, W, H * 0.18, 16)}
        <rect y={ledge} width={W} height={H - ledge} fill="#0d0f17" />
        <rect y={ledge - u * 1.2} width={W} height={u * 1.6} fill="#1c2030" />
        <Person x={W * 0.42} y={ledge} s={wide ? H * 0.26 : W * 0.3} color="#2c3346" rim={pal.warm} f={f} />
        {art.prop === "kucing" ? <g transform={`translate(${W * 0.64},${ledge})`}>
          <path d={`M0,0 c0,${-u * 7} ${u * 2},${-u * 9} ${u * 4},${-u * 9} c${u * 2},0 ${u * 4},${u * 2} ${u * 4},${u * 9} Z`} fill="#141722" />
          <circle cx={u * 4} cy={-u * 10} r={u * 2.6} fill="#141722" />
          <path d={`M${u * 2},${-u * 11.5} l${u * 0.6},${-u * 2.6} l${u * 1.4},${u * 1.8} M${u * 4.6},${-u * 11.8} l${u * 1.2},${-u * 2.4} l${u * 0.8},${u * 2.4}`} fill="#141722" />
          <path d={`M${u * 7},${-u * 1} q${u * 5},${Math.sin(f / 14) * u * 2} ${u * 4},${-u * 6}`} fill="none" stroke="#141722" strokeWidth={u * 1.1} strokeLinecap="round" />
        </g> : null}
      </g>
    );
  } else if (art.place === "bus") {
    const top = H * (wide ? 0.14 : 0.2), bot = H * (wide ? 0.62 : 0.52);
    body = (
      <g>
        <rect width={W} height={H} fill={mix(pal.wall[0], "#000000", 0.2)} />
        <clipPath id={`${id}win`}><rect x={W * 0.04} y={top} width={W * 0.92} height={bot - top} rx={u * 3} /></clipPath>
        <g clipPath={`url(#${id}win)`}>
          <rect x={0} y={top} width={W} height={bot - top} fill={`url(#${id}sky)`} />
          <g opacity={0.7}><City x0={-((f * 3) % (W * 0.5))} x1={W * 1.6 - ((f * 3) % (W * 0.5))} base={bot} h={(bot - top) * 0.6} color={pal.city} seed={`${id}bc`} f={f} lit={pal.warm} n={20} /></g>
          {Array.from({ length: 22 }, (_, i) => {
            const x = W * 1.2 - ((f * (8 + R(`${id}v${i}`) * 10) + R(`${id}w${i}`) * W * 2) % (W * 1.5));
            return <rect key={i} x={x} y={top + (bot - top) * (0.55 + R(`${id}q${i}`) * 0.4)} width={u * (6 + R(`${id}l${i}`) * 14)} height={u * 0.9}
              rx={u * 0.4} fill={i % 3 ? pal.warm : "#FF6B6B"} opacity={0.55} filter={`url(#${id}blur)`} />;
          })}
          {bokeh(0, top, W, bot - top, 14, -6)}
        </g>
        <rect x={W * 0.04} y={top} width={W * 0.92} height={bot - top} rx={u * 3} fill="none" stroke="#2a2d3a" strokeWidth={u * 1.6} />
        <rect x={W * 0.48} y={top} width={u * 1.6} height={bot - top} fill="#2a2d3a" />
        <rect y={bot + u * 1.5} width={W} height={H - bot} fill="#151722" />
        <g transform={`translate(${W * 0.7},${bot + H * 0.18})`}><Person x={0} y={0} s={wide ? H * 0.3 : W * 0.38} color="#2c3346" rim={pal.warm} hood={false} f={f} /></g>
        <rect x={W * 0.02} y={bot + H * 0.12} width={W * 0.38} height={H * 0.4} rx={u * 4} fill="#1d2030" />
      </g>
    );
  } else {
    // kamar: jendela, meja, lampu, orang dari belakang
    const wx0 = wide ? W * 0.3 : W * 0.12, wx1 = wide ? W * 0.7 : W * 0.88;
    const wy0 = wide ? H * 0.08 : H * 0.11, wy1 = wide ? H * 0.58 : H * 0.48;
    const desk = wide ? H * 0.7 : H * 0.6;
    const lampX = wide ? W * 0.22 : W * 0.16;
    const flick = 0.92 + 0.08 * Math.sin(f / 7) * Math.sin(f / 13);
    body = (
      <g>
        <rect width={W} height={H} fill={pal.wall[0]} />
        <rect width={W} height={desk} fill={`url(#${id}wall)`} />
        <clipPath id={`${id}win`}><rect x={wx0} y={wy0} width={wx1 - wx0} height={wy1 - wy0} /></clipPath>
        <g clipPath={`url(#${id}win)`}>
          <rect x={wx0} y={wy0} width={wx1 - wx0} height={wy1 - wy0} fill={`url(#${id}sky)`} />
          {pal.moon ? <circle cx={wx1 - (wx1 - wx0) * 0.22} cy={wy0 + (wy1 - wy0) * 0.22} r={u * 4} fill="#F3E9C6" opacity={0.85} /> : null}
          <g opacity={0.65}><City x0={wx0} x1={wx1} base={wy1} h={(wy1 - wy0) * 0.45} color={pal.city} seed={`${id}k1`} f={f} lit={pal.warm} n={9} /></g>
          {bokeh(wx0, wy0 + (wy1 - wy0) * 0.45, wx1 - wx0, (wy1 - wy0) * 0.5, 12)}
          {art.time === "hujan" || art.time === "malam" ? Array.from({ length: 26 }, (_, i) => {
            const x = wx0 + R(`${id}d${i}`) * (wx1 - wx0);
            const sp = 0.6 + R(`${id}s${i}`) * 1.4;
            const y = wy0 + ((R(`${id}e${i}`) * (wy1 - wy0) + f * sp * u * 0.25) % (wy1 - wy0));
            return <g key={i}><circle cx={x} cy={y} r={u * 0.35} fill="#cfe3ff" opacity={0.5} />
              <path d={`M${x},${y} v${-u * 2.5 * sp}`} stroke="#cfe3ff" strokeWidth={u * 0.18} opacity={0.3} /></g>;
          }) : null}
        </g>
        <rect x={wx0} y={wy0} width={wx1 - wx0} height={wy1 - wy0} fill="none" stroke="#120f18" strokeWidth={u * 1.6} />
        <path d={`M${(wx0 + wx1) / 2},${wy0} V${wy1} M${wx0},${(wy0 + wy1) / 2} H${wx1}`} stroke="#120f18" strokeWidth={u * 1.1} />
        <rect x={wx0 - u * 2} y={wy1} width={wx1 - wx0 + u * 4} height={u * 1.6} fill="#2a2030" />
        <path d={`M${wx1 - u * 2},${wy0 - u * 2} C${wx1 + u * 4},${wy0 + (wy1 - wy0) * 0.3} ${wx1 - u * 4},${wy0 + (wy1 - wy0) * 0.7} ${wx1 + u * 2},${wy1 + u * 6} L${W},${wy1 + u * 6} L${W},${wy0 - u * 2} Z`}
          fill={mix(pal.wall[1], pal.warm, 0.12)} opacity={0.9} />
        {/* cahaya lampu */}
        <circle cx={lampX + u * 7} cy={desk - u * 10} r={u * 36 * flick} fill={`url(#${id}glow)`} opacity={0.75} />
        <rect y={desk} width={W} height={u * 2.2} fill="#4a3427" />
        <rect y={desk + u * 2.2} width={W} height={H - desk} fill="#2b1f19" />
        <g>
          <rect x={lampX - u * 4} y={desk - u * 1.4} width={u * 8} height={u * 1.4} rx={u * 0.6} fill="#1b1714" />
          <path d={`M${lampX},${desk - u} L${lampX + u * 2},${desk - u * 13} L${lampX + u * 8},${desk - u * 17}`} fill="none" stroke="#1b1714" strokeWidth={u * 0.9} strokeLinecap="round" />
          <path d={`M${lampX + u * 4},${desk - u * 21} l${u * 9},${u * 3} l${-u * 3},${u * 6} Z`} fill="#2d2622" />
          <ellipse cx={lampX + u * 7.5} cy={desk - u * 14.5} rx={u * 2.2} ry={u * 1} fill={pal.warm} opacity={flick} />
        </g>
        {art.prop === "mug" ? <g><rect x={W * 0.34} y={desk - u * 6} width={u * 5} height={u * 6} rx={u * 1} fill="#c9a27a" />
          <path d={`M${W * 0.34 + u * 5},${desk - u * 4.5} a${u * 1.6},${u * 1.6} 0 0 1 0,${u * 3.2}`} fill="none" stroke="#c9a27a" strokeWidth={u * 0.8} />
          <Steam x={W * 0.34 + u * 2.5} y={desk - u * 7} s={u * 7} f={f} /></g> : null}
        {art.prop === "tanaman" ? <g transform={`translate(${W * (wide ? 0.78 : 0.86)},${desk})`}>
          <path d={`M${-u * 3},0 l${u * 0.6},${-u * 5} h${u * 4.8} l${u * 0.6},${u * 5} Z`} fill="#a0583a" />
          {[-30, -10, 12, 32].map((a, i) => <ellipse key={i} cx={0} cy={-u * 9} rx={u * 1.6} ry={u * 4.5} fill="#3f7a4f"
            transform={`rotate(${a + Math.sin(f / 30 + i) * 3} 0 ${-u * 5})`} />)}</g> : null}
        {art.prop === "buku" ? <g transform={`translate(${W * 0.3},${desk})`}>{["#7a4b3a", "#3f5a7a", "#a08a5a"].map((col, i) =>
          <rect key={i} x={-u * 6 + i * u * 0.6} y={-u * 1.6 * (i + 1)} width={u * 12} height={u * 1.6} fill={col} />)}</g> : null}
        {art.prop === "headphone" ? <g transform={`translate(${W * 0.32},${desk})`}>
          <path d={`M${-u * 4},${-u * 1.5} a${u * 4},${u * 4.5} 0 0 1 ${u * 8},0`} fill="none" stroke="#1b1714" strokeWidth={u * 0.9} />
          <rect x={-u * 5} y={-u * 3} width={u * 2.4} height={u * 3} rx={u * 0.8} fill="#2d2622" /><rect x={u * 2.6} y={-u * 3} width={u * 2.4} height={u * 3} rx={u * 0.8} fill="#2d2622" /></g> : null}
        {art.prop === "kucing" ? <g transform={`translate(${W * 0.3},${desk})`}>
          <ellipse cx={0} cy={-u * 3} rx={u * 6} ry={u * 3.2} fill="#16131c" />
          <circle cx={-u * 5} cy={-u * 5} r={u * 2.6} fill="#16131c" />
          <path d={`M${-u * 7},${-u * 6.5} l${u * 0.4},${-u * 2.6} l${u * 1.6},${u * 1.8} M${-u * 4.2},${-u * 7} l${u * 1},${-u * 2.4} l${u * 0.8},${u * 2.4}`} fill="#16131c" />
          <path d={`M${u * 5.5},${-u * 2} q${u * 4},${Math.sin(f / 16) * u * 2} ${u * 2},${-u * 5}`} fill="none" stroke="#16131c" strokeWidth={u * 1} strokeLinecap="round" />
        </g> : null}
        <Person x={wide ? W * 0.56 : W * 0.64} y={desk + u * 2} s={wide ? H * 0.34 : W * 0.38} color="#3d4a3c" rim={pal.warm} f={f} />
        {art.time === "pagi" ? null : <rect width={W} height={H} fill="#0a0814" opacity={0.12} />}
      </g>
    );
  }
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ transform: `scale(${zoom})`, transformOrigin: "50% 45%" }}>
        <defs>
          {sky}
          <linearGradient id={`${id}wall`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={pal.wall[0]} /><stop offset="1" stopColor={pal.wall[1]} /></linearGradient>
          <radialGradient id={`${id}glow`}><stop offset="0" stopColor={pal.warm} stopOpacity={0.55} /><stop offset="1" stopColor={pal.warm} stopOpacity={0} /></radialGradient>
          <filter id={`${id}blur`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation={u * 0.6} /></filter>
        </defs>
        {body}
      </svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ DONGENG
const TALE_PAL: Record<string, { sky: [string, string]; hills: [string, string, string]; light: string; moon: boolean; sun: boolean }> = {
  malam: { sky: ["#0B1630", "#25467A"], hills: ["#2A4C6B", "#21485A", "#173A33"], light: "#FFE7A3", moon: true, sun: false },
  fajar: { sky: ["#2B2F5E", "#F4A28C"], hills: ["#5A4F7A", "#3E4F6A", "#26453E"], light: "#FFD3A1", moon: false, sun: true },
  siang: { sky: ["#7CC3EC", "#DFF4FF"], hills: ["#8CC7A5", "#5FAE7E", "#3E8C5E"], light: "#FFF3C4", moon: false, sun: true },
};

const Deer: React.FC<{ s: number; f: number; c: string }> = ({ s, f, c }) => {
  const head = Math.sin(f / 22) * 4;
  const tail = Math.sin(f / 6) * 10;
  const leg = "#6b4423";
  return (
    <g transform={`scale(${s / 100})`}>
      {[[-26, 0], [-16, 0], [18, 0], [28, 0]].map(([x], i) => (
        <path key={i} d={`M${x},-28 L${x + (i % 2 ? 2 : -1)},0`} stroke={leg} strokeWidth={5} strokeLinecap="round" />
      ))}
      <path d={`M-34,-40 q-8,${-6 + tail * 0.3} -10,${-12 + tail * 0.2}`} stroke="#F4E6D0" strokeWidth={6} strokeLinecap="round" />
      <ellipse cx={0} cy={-38} rx={36} ry={15} fill={c} />
      <ellipse cx={2} cy={-31} rx={28} ry={7} fill="#E8C9A0" opacity={0.8} />
      {[[-18, -44], [-6, -47], [6, -45], [-12, -38], [12, -40], [20, -46]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r={2.2} fill="#F7EBD8" />)}
      <g transform={`rotate(${head} 28 -46)`}>
        <path d="M24,-50 L36,-74 L46,-70 L34,-44 Z" fill={c} />
        <ellipse cx={44} cy={-78} rx={11} ry={8} fill={c} />
        <ellipse cx={54} cy={-75} rx={5} ry={4} fill="#E8C9A0" />
        <circle cx={56.5} cy={-76} r={1.6} fill="#2a1a10" />
        <circle cx={44} cy={-80} r={1.8} fill="#2a1a10" />
        <path d={`M38,-84 q-10,-6 -12,${-4 + Math.sin(f / 30) * 2}`} stroke={c} strokeWidth={5} strokeLinecap="round" fill="none" />
        <path d="M42,-86 l-4,-16 m2,8 l-6,-6 M48,-86 l4,-16 m-2,8 l6,-6" stroke="#8a6440" strokeWidth={2.4} strokeLinecap="round" fill="none" />
      </g>
    </g>
  );
};

const Creature: React.FC<{ kind: string; s: number; f: number }> = ({ kind, s, f }) => {
  const k = s / 100;
  if (kind === "rusa") return <Deer s={s} f={f} c="#C08A55" />;
  if (kind === "kelinci") {
    const hop = Math.max(0, Math.sin(f / 18)) * 6;
    return (
      <g transform={`scale(${k}) translate(0,${-hop})`}>
        <ellipse cx={0} cy={-16} rx={22} ry={16} fill="#EDE6DA" />
        <circle cx={18} cy={-30} r={11} fill="#EDE6DA" />
        <ellipse cx={14} cy={-52} rx={4} ry={14} fill="#EDE6DA" transform={`rotate(${-10 + Math.sin(f / 20) * 6} 14 -40)`} />
        <ellipse cx={22} cy={-52} rx={4} ry={14} fill="#EDE6DA" transform="rotate(12 22 -40)" />
        <circle cx={22} cy={-32} r={1.6} fill="#2a1a10" />
        <circle cx={-22} cy={-18} r={6} fill="#FFFFFF" />
      </g>
    );
  }
  if (kind === "burung_hantu") {
    const blink = (f % 110) < 5 ? 0.15 : 1;
    return (
      <g transform={`scale(${k})`}>
        <path d="M-70,6 Q0,-6 70,10" stroke="#3b2a1e" strokeWidth={8} fill="none" strokeLinecap="round" />
        <ellipse cx={0} cy={-26} rx={22} ry={30} fill="#8a6240" />
        <ellipse cx={0} cy={-18} rx={14} ry={20} fill="#C9A77E" />
        <path d="M-18,-50 l-4,-12 l12,8 M18,-50 l4,-12 l-12,8" fill="#8a6240" />
        {[-9, 9].map((x) => <g key={x}><circle cx={x} cy={-40} r={8} fill="#F5E9C8" /><ellipse cx={x} cy={-40} rx={4.5} ry={4.5 * blink} fill="#E8B23A" />
          <circle cx={x} cy={-40} r={2 * blink} fill="#1a120c" /></g>)}
        <path d="M-3,-32 l3,5 l3,-5 Z" fill="#E8B23A" />
      </g>
    );
  }
  if (kind === "rubah") {
    const t = Math.sin(f / 14) * 8;
    return (
      <g transform={`scale(${k})`}>
        <path d={`M-20,-6 C-50,-4 -60,${-30 + t} -44,${-44 + t} C-38,-30 -30,-20 -14,-16 Z`} fill="#E07A2E" />
        <path d={`M-52,${-38 + t} C-50,${-46 + t} -42,${-48 + t} -44,${-44 + t} Z`} fill="#FFFFFF" />
        <path d="M-18,0 C-22,-30 -4,-46 10,-40 C22,-34 20,-10 14,0 Z" fill="#E07A2E" />
        <path d="M-2,-22 C2,-30 12,-30 12,-12 L4,0 Z" fill="#F7EBD8" />
        <path d="M2,-40 C6,-58 28,-58 30,-46 C30,-38 20,-34 10,-36 Z" fill="#E07A2E" />
        <path d="M6,-52 l-2,-14 l10,8 Z M20,-54 l6,-12 l2,12 Z" fill="#C25F1E" />
        <circle cx={22} cy={-46} r={1.8} fill="#1a120c" /><circle cx={31} cy={-43} r={2.2} fill="#1a120c" />
      </g>
    );
  }
  if (kind === "kura") {
    const peek = 0.5 + 0.5 * Math.sin(f / 30);
    return (
      <g transform={`scale(${k})`}>
        <ellipse cx={24 + peek * 8} cy={-10} rx={9} ry={7} fill="#7FA35A" />
        <circle cx={28 + peek * 8} cy={-12} r={1.4} fill="#1a120c" />
        <path d="M-30,0 C-30,-34 30,-34 30,0 Z" fill="#4E7A3A" />
        {[[-14, -12], [0, -20], [14, -12], [0, -6]].map(([x, y], i) => <path key={i} d={`M${x - 6},${y} l6,-5 l6,5 l-6,5 Z`} fill="#6E9A4E" />)}
        {[-20, 18].map((x) => <ellipse key={x} cx={x} cy={0} rx={6} ry={3.5} fill="#7FA35A" />)}
      </g>
    );
  }
  if (kind === "anak") {
    return (
      <g transform={`scale(${k})`}>
        <path d="M-18,0 C-18,-26 18,-26 18,0 Z" fill="#2B3A55" />
        <circle cx={0} cy={-34} r={11} fill="#2a1d16" />
        <path d="M-11,-36 C-10,-48 10,-48 11,-36" fill="#2a1d16" />
        <path d="M-18,-6 L-30,4 M18,-6 L30,4" stroke="#2B3A55" strokeWidth={6} strokeLinecap="round" />
      </g>
    );
  }
  return null;
};

const Tree: React.FC<{ x: number; y: number; h: number; color: string; kind: "pine" | "round"; sway: number }> = ({ x, y, h, color, kind, sway }) => (
  <g transform={`translate(${x},${y}) rotate(${sway})`}>
    <rect x={-h * 0.03} y={-h * 0.25} width={h * 0.06} height={h * 0.25} fill={color} />
    {kind === "pine" ? [0, 1, 2].map((i) => (
      <path key={i} d={`M${-h * (0.28 - i * 0.06)},${-h * (0.2 + i * 0.25)} L0,${-h * (0.55 + i * 0.22)} L${h * (0.28 - i * 0.06)},${-h * (0.2 + i * 0.25)} Z`} fill={color} />
    )) : <circle cx={0} cy={-h * 0.55} r={h * 0.32} fill={color} />}
  </g>
);

const Dongeng: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, W, H, wide, art, idx, durF } = c;
  const pal = TALE_PAL[art.time] || TALE_PAL.malam;
  const id = `dg${idx}`;
  const u = Math.min(W, H) / 100;
  const pan = clamp(f / Math.max(1, durF));
  const hz = H * (wide ? 0.6 : 0.56);
  const ground = H * (wide ? 0.82 : 0.74);
  const moonX = W * (wide ? 0.72 : 0.62), moonY = H * (wide ? 0.2 : 0.2);
  const water = art.place === "danau" || art.place === "laut";
  const layer = (n: number) => `translate(${(pan - 0.5) * W * 0.03 * n},0)`;
  const sway = Math.sin(f / 35) * 1.2;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <defs>
          <linearGradient id={`${id}sky`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={pal.sky[0]} /><stop offset="1" stopColor={pal.sky[1]} /></linearGradient>
          <radialGradient id={`${id}halo`}><stop offset="0.35" stopColor={pal.light} stopOpacity={0.45} /><stop offset="1" stopColor={pal.light} stopOpacity={0} /></radialGradient>
          <linearGradient id={`${id}water`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={mix(pal.hills[1], pal.sky[1], 0.5)} /><stop offset="1" stopColor={pal.hills[2]} /></linearGradient>
        </defs>
        <rect width={W} height={H} fill={`url(#${id}sky)`} />
        {pal.moon || pal.sun ? (
          <g transform={layer(0.4)}>
            <circle cx={moonX} cy={art.time === "fajar" ? hz - u * 4 : moonY} r={u * 22} fill={`url(#${id}halo)`} />
            <circle cx={moonX} cy={art.time === "fajar" ? hz - u * 4 : moonY} r={u * 9} fill={pal.light} />
            {pal.moon ? <g fill="#E9D99A" opacity={0.5}><circle cx={moonX - u * 3} cy={moonY - u * 2} r={u * 1.6} /><circle cx={moonX + u * 2.5} cy={moonY + u * 3} r={u * 1.1} /></g> : null}
          </g>
        ) : null}
        {art.time === "siang" ? [0, 1].map((i) => (
          <g key={i} transform={`translate(${((W * (0.2 + i * 0.5) + f * u * 0.08) % (W * 1.3)) - W * 0.1},${H * (0.14 + i * 0.07)})`} fill="#FFFFFF" opacity={0.9}>
            <ellipse rx={u * 9} ry={u * 3} /><ellipse cx={u * 4} cy={-u * 2.5} rx={u * 5} ry={u * 3.5} /><ellipse cx={-u * 3} cy={-u * 1.5} rx={u * 4} ry={u * 2.5} />
          </g>
        )) : null}
        <g transform={layer(0.8)}><path d={hills(W * 1.1, H, hz - u * 2, H * 0.08, `${id}h1`, 4)} transform={`translate(${-W * 0.05},0)`} fill={pal.hills[0]} /></g>
        {art.place === "laut" ? (
          <g>
            <rect y={hz} width={W} height={H - hz} fill={`url(#${id}water)`} />
            <path d={`M${W * 0.08},${hz} q${W * 0.1},${-H * 0.05} ${W * 0.22},0 Z`} fill={pal.hills[1]} />
            {Array.from({ length: 10 }, (_, i) => (
              <path key={i} d={wavy(-W * 0.1 + ((f * 0.6 + i * 37) % (W * 0.2)), W * 1.1, hz + (H - hz) * (0.1 + i * 0.09), u * 0.8, `${id}w${i}`, 10)}
                fill="none" stroke={pal.light} strokeWidth={u * 0.25} opacity={0.25} />
            ))}
            <g transform={`translate(${W * 0.32},${hz + H * 0.04 + Math.sin(f / 18) * u * 0.8}) rotate(${Math.sin(f / 22) * 3})`}>
              <path d={`M${-u * 7},0 h${u * 14} l${-u * 3},${u * 3} h${-u * 8} Z`} fill="#2a1d16" />
              <path d={`M0,0 v${-u * 12} l${u * 7},${u * 10} Z`} fill={pal.light} opacity={0.9} />
            </g>
          </g>
        ) : (
          <g transform={layer(1.2)}>
            <path d={hills(W * 1.1, H, hz + H * 0.04, H * 0.07, `${id}h2`, 3)} transform={`translate(${-W * 0.05},0)`} fill={pal.hills[1]} />
          </g>
        )}
        {art.place === "danau" ? (
          <g>
            <path d={`M0,${hz + H * 0.08} Q${W * 0.5},${hz + H * 0.05} ${W},${hz + H * 0.08} L${W},${ground} L0,${ground} Z`} fill={`url(#${id}water)`} />
            {Array.from({ length: 8 }, (_, i) => {
              const y = hz + H * 0.09 + i * (ground - hz - H * 0.09) / 8;
              const w = u * (10 - i) * (0.8 + 0.2 * Math.sin(f / 9 + i));
              return <rect key={i} x={moonX - w / 2} y={y} width={w} height={u * 0.5} rx={u * 0.25} fill={pal.light} opacity={0.5 - i * 0.04} />;
            })}
            {[0.08, 0.13, 0.86, 0.9].map((x, i) => <path key={i} d={`M${W * x},${ground} q${u},${-u * 6} ${u * 0.3},${-u * 10}`} stroke={pal.hills[2]} strokeWidth={u * 0.5} fill="none" />)}
          </g>
        ) : null}
        {art.place === "desa" ? (
          <g transform={layer(1.2)}>
            {[0.18, 0.34, 0.52, 0.7].map((x, i) => {
              const hx = W * x, hy = hz + H * (0.05 + (i % 2) * 0.015), s = u * (6 + (i % 2) * 1.5);
              return (
                <g key={i}>
                  <rect x={hx - s} y={hy - s * 1.2} width={s * 2} height={s * 1.2} fill="#2c3a52" />
                  <path d={`M${hx - s * 1.25},${hy - s * 1.15} L${hx},${hy - s * 2.2} L${hx + s * 1.25},${hy - s * 1.15} Z`} fill="#1f2a3d" />
                  <rect x={hx - s * 0.35} y={hy - s * 0.8} width={s * 0.7} height={s * 0.5} fill={pal.light} opacity={0.75 + 0.25 * Math.sin(f / 15 + i)} />
                  {i === 1 ? <Steam x={hx + s * 0.6} y={hy - s * 2} s={s * 1.2} f={f} color={pal.light} /> : null}
                </g>
              );
            })}
          </g>
        ) : null}
        {art.place === "hutan" ? (
          <g transform={layer(1.4)}>
            {Array.from({ length: 9 }, (_, i) => (
              <Tree key={i} x={W * (0.04 + i * 0.12) + R(`${id}t${i}`) * u * 3} y={hz + H * 0.07 + R(`${id}ty${i}`) * H * 0.03}
                h={H * (0.13 + R(`${id}th${i}`) * 0.08)} color={mix(pal.hills[1], "#000000", 0.25)} kind={i % 3 ? "pine" : "round"} sway={sway} />
            ))}
          </g>
        ) : null}
        <path d={hills(W * 1.2, H, ground, H * 0.05, `${id}h3`, 3)} transform={`translate(${-W * 0.1},0)`} fill={pal.hills[2]} />
        {art.place === "bukit" ? <Tree x={W * 0.8} y={ground - H * 0.01} h={H * 0.3} color={mix(pal.hills[2], "#000000", 0.35)} kind="round" sway={sway} /> : null}
        {art.place === "hutan" ? <Tree x={W * 0.1} y={ground} h={H * 0.34} color={mix(pal.hills[2], "#000000", 0.4)} kind="pine" sway={sway} /> : null}
        {art.creature && art.creature !== "none" ? (
          art.creature === "burung_hantu" ? (
            <g transform={`translate(${W * 0.62},${H * 0.42})`}><Creature kind="burung_hantu" s={wide ? H * 0.22 : W * 0.32} f={f} /></g>
          ) : (
            <g transform={`translate(${W * (art.creature === "anak" ? 0.42 : 0.4)},${ground + H * 0.01})`}>
              <Creature kind={art.creature} s={wide ? H * 0.3 : W * (art.creature === "rusa" ? 0.42 : 0.3)} f={f} />
            </g>
          )
        ) : null}
        <linearGradient id={`${id}fade`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#000000" stopOpacity={0} /><stop offset="1" stopColor="#000000" stopOpacity={0.35} /></linearGradient>
        <rect y={ground} width={W} height={H - ground} fill={`url(#${id}fade)`} />
      </svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ BERITA DATA
let WORLD: any = null;
const worldFC = () => {
  if (!WORLD) WORLD = feature(world as any, (world as any).objects.countries) as any;
  return WORLD;
};
const parseNum = (s: string): { value: number; decimals: number; prefix: string; suffix: string } | null => {
  const m = String(s || "").match(/^(.*?)(-?\d[\d.,]*)(.*)$/);
  if (!m) return null;
  let raw = m[2];
  let decimals = 0;
  // format Indonesia: titik = ribuan, koma = desimal; format Inggris: koma = ribuan, titik = desimal
  if (/,\d{1,2}$/.test(raw)) { decimals = raw.split(",")[1].length; raw = raw.replace(/\./g, "").replace(",", "."); }
  else if (/\.\d{1,2}$/.test(raw) && !/\.\d{3}/.test(raw)) { decimals = raw.split(".")[1].length; raw = raw.replace(/,/g, ""); }
  else raw = raw.replace(/[.,]/g, "");
  const value = parseFloat(raw);
  return isFinite(value) ? { value, decimals, prefix: m[1], suffix: m[3] } : null;
};

const DataScene: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, fps, W, H, wide, art, idx, durF, style } = c;
  const u = Math.min(W, H) / 100;
  const ink = "#1D1A16", red = style.accent, paper = style.bg;
  const kind = art.kind;
  const geo = useMemo(() => {
    if (kind !== "map") return null;
    const fc = worldFC();
    const target = fc.features.find((x: any) => x.properties?.name === art.country) || fc.features.find((x: any) => x.properties?.name === "Indonesia");
    const pts: { name: string; lat: number; lon: number }[] = art.points || [];
    const ext: [[number, number], [number, number]] = wide ? [[W * 0.08, H * 0.2], [W * 0.92, H * 0.74]] : [[W * 0.06, H * 0.22], [W * 0.94, H * 0.68]];
    let fitObj: any = target;
    if (pts.length >= 2) {
      const lons = pts.map((p) => p.lon), lats = pts.map((p) => p.lat);
      const cx = (Math.min(...lons) + Math.max(...lons)) / 2, cy = (Math.min(...lats) + Math.max(...lats)) / 2;
      const hw = Math.max(3, (Math.max(...lons) - Math.min(...lons)) * 0.65), hh = Math.max(2, (Math.max(...lats) - Math.min(...lats)) * 0.65);
      fitObj = { type: "MultiPoint", coordinates: [[cx - hw, cy - hh], [cx + hw, cy + hh]] };
    } else if (target) {
      const b = geoBounds(target as any);
      if (b[0][0] > b[1][0]) fitObj = { type: "MultiPoint", coordinates: [[b[0][0], b[0][1]], [b[1][0] + 360, b[1][1]]] };
    }
    const proj = geoMercator().fitExtent(ext, fitObj);
    const path = geoPath(proj);
    const land: { d: string; hit: boolean }[] = [];
    for (const x of fc.features) {
      const bb = path.bounds(x as any);
      if (!isFinite(bb[0][0]) || bb[1][0] < -W || bb[0][0] > W * 2 || bb[1][1] < -H || bb[0][1] > H * 2) continue;
      const d = path(x as any);
      if (d) land.push({ d, hit: x === target });
    }
    const dots = pts.map((p) => ({ ...p, xy: proj([p.lon, p.lat]) as [number, number] })).filter((p) => p.xy && isFinite(p.xy[0]));
    return { land, dots };
  }, [kind, art.country, JSON.stringify(art.points), W, H]);
  let body: React.ReactNode = null;
  if (kind === "map" && geo) {
    const n = geo.dots.length;
    body = (
      <g>
        {geo.land.map((l, i) => (
          <path key={i} d={l.d} fill={l.hit ? "#DCC79C" : "#E9E0CB"} stroke={l.hit ? ink : rgba(ink, 0.3)} strokeWidth={l.hit ? u * 0.28 : u * 0.15}
            strokeLinejoin="round" pathLength={l.hit ? 1 : undefined} strokeDasharray={l.hit ? "1 1" : undefined}
            strokeDashoffset={l.hit ? 1 - ease(f, 0, fps * 1.2, Easing.inOut(Easing.quad)) : undefined} />
        ))}
        {geo.dots.map((d, i) => {
          const at = fps * 0.8 + (i * Math.max(4, (durF - fps * 1.6) * 0.6)) / Math.max(1, n);
          const p = back(f, at, fps * 0.3);
          const ring = clamp((f - at) / (fps * 0.8));
          const showLabel = n <= 8 || i < 6;
          const right = d.xy[0] < W * 0.7;
          return (
            <g key={i} opacity={clamp(p * 3)}>
              {ring < 1 ? <circle cx={d.xy[0]} cy={d.xy[1]} r={u * (1 + ring * 3)} fill="none" stroke={red} strokeWidth={u * 0.3} opacity={1 - ring} /> : null}
              <circle cx={d.xy[0]} cy={d.xy[1]} r={u * 1.1 * p} fill={ink} />
              {showLabel && d.name ? <text x={d.xy[0] + (right ? u * 1.8 : -u * 1.8)} y={d.xy[1] + (i % 2 ? -u * 1.4 : u * 2.6)} textAnchor={right ? "start" : "end"}
                fontFamily="Special Elite" fontSize={u * (n > 6 ? 3 : 3.6)} fill={ink} stroke={paper} strokeWidth={u * 0.7} paintOrder="stroke">{d.name}</text> : null}
            </g>
          );
        })}
        <g transform={`translate(${W * 0.06},${H * (wide ? 0.82 : 0.73)})`} opacity={ease(f, fps * 0.4, fps * 0.5)}>
          <rect width={u * 3} height={u * 3} fill={ink} />
          <text x={u * 4.4} y={u * 2.5} fontFamily="Special Elite" fontSize={u * 3.2} fill={ink}>{art.label || art.country}</text>
        </g>
      </g>
    );
  } else if (kind === "number") {
    const num = parseNum(art.value);
    const p = ease(f, fps * 0.3, fps * 1.4, Easing.out(Easing.cubic));
    const shown = num ? `${num.prefix}${fmtNum(num.value * p, num.decimals)}${num.suffix}` : art.value;
    const len = shown.length;
    const size = (wide ? H * 0.3 : W * 0.26) * (len > 7 ? 7 / len : 1);
    const cy = H * (wide ? 0.48 : 0.44);
    body = (
      <g>
        {Array.from({ length: 12 }, (_, i) => <line key={i} x1={0} x2={W} y1={H * 0.12 + i * H * 0.065} y2={H * 0.12 + i * H * 0.065} stroke={rgba(ink, 0.06)} strokeWidth={u * 0.15} />)}
        <text x={W / 2} y={cy} textAnchor="middle" fontFamily="Archivo Black" fontSize={size} fill={ink}
          style={{ fontVariantNumeric: "tabular-nums" }}>{shown}</text>
        <path d={wavy(W * 0.5 - size * len * 0.3, W * 0.5 + size * len * 0.3, cy + size * 0.18, u * 0.8, `${idx}n`, 8)} fill="none" stroke={red}
          strokeWidth={u * 1.4} strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - ease(f, fps * 1.4, fps * 0.5)} />
        {art.unit ? <text x={W / 2} y={cy + size * 0.55} textAnchor="middle" fontFamily="Archivo Black" fontSize={size * 0.32} fill={red}
          opacity={ease(f, fps * 1.0, fps * 0.4)}>{art.unit}</text> : null}
        {art.label ? <text x={W / 2} y={cy + size * (art.unit ? 0.95 : 0.6)} textAnchor="middle" fontFamily="Special Elite" fontSize={u * 4.2} fill={ink}
          opacity={ease(f, fps * 1.3, fps * 0.4)}>{art.label}</text> : null}
      </g>
    );
  } else if (kind === "bars") {
    const items: { label: string; value: number }[] = art.items || [];
    const max = Math.max(...items.map((x) => Math.abs(x.value)), 1);
    const top = H * (wide ? 0.2 : 0.24), rowH = (H * (wide ? 0.5 : 0.42)) / Math.max(1, items.length);
    const x0 = W * (wide ? 0.3 : 0.08), barMax = W * (wide ? 0.5 : 0.62);
    const best = items.reduce((b, x, i) => (x.value > items[b].value ? i : b), 0);
    body = (
      <g>
        {items.map((it, i) => {
          const p = ease(f, fps * (0.3 + i * 0.18), fps * 0.9, Easing.out(Easing.cubic));
          const y = top + i * rowH;
          const w = (barMax * Math.abs(it.value) * p) / max;
          const dec = Math.abs(it.value % 1) > 0 ? 1 : 0;
          return (
            <g key={i}>
              <text x={wide ? x0 - u * 2 : x0} y={wide ? y + rowH * 0.45 : y + rowH * 0.22} textAnchor={wide ? "end" : "start"} fontFamily="Special Elite"
                fontSize={u * 3.2} fill={ink}>{it.label}</text>
              <rect x={x0} y={wide ? y + rowH * 0.18 : y + rowH * 0.32} width={w} height={rowH * (wide ? 0.42 : 0.4)} fill={i === best ? red : ink} />
              <text x={x0 + w + u * 1.5} y={(wide ? y + rowH * 0.18 : y + rowH * 0.32) + rowH * (wide ? 0.32 : 0.3)} fontFamily="Archivo Black" fontSize={u * 3.4}
                fill={ink} opacity={clamp(p * 2 - 0.5)}>{fmtNum(it.value * p, dec)}</text>
            </g>
          );
        })}
        <line x1={x0} x2={x0} y1={top} y2={top + rowH * items.length} stroke={ink} strokeWidth={u * 0.3} />
      </g>
    );
  } else {
    const text: string = art.label || c.sc.heading || "";
    const words = text.split(/\s+/);
    const lines: string[] = [];
    const per = wide ? 24 : 12;
    for (const w of words) {
      const last = lines[lines.length - 1];
      if (last && (last + " " + w).length <= per) lines[lines.length - 1] = last + " " + w;
      else lines.push(w);
    }
    const longest = Math.max(...lines.map((l) => l.length), 1);
    const size = Math.min(wide ? H * 0.11 : W * 0.12, (W * 0.84) / (longest * 0.64)) * (lines.length > 4 ? 0.85 : 1);
    const y0 = H * 0.45 - (lines.length * size * 1.05) / 2;
    body = (
      <g>
        <rect x={W * 0.08} y={y0 - size * 1.4} width={u * 14} height={u * 4.6} fill={red} opacity={ease(f, 0, fps * 0.3)} />
        <text x={W * 0.08 + u * 7} y={y0 - size * 1.4 + u * 3.3} textAnchor="middle" fontFamily="Archivo Black" fontSize={u * 2.8} fill="#FFFFFF">DATA</text>
        <line x1={W * 0.08} x2={W * 0.92} y1={y0 - size * 0.75} y2={y0 - size * 0.75} stroke={ink} strokeWidth={u * 0.5} />
        {lines.map((ln, i) => (
          <text key={i} x={W * 0.08} y={y0 + i * size * 1.05 + size * 0.2} fontFamily="Archivo Black" fontSize={size} fill={ink}
            opacity={ease(f, fps * (0.15 + i * 0.12), fps * 0.4)}>{ln}</text>
        ))}
        <line x1={W * 0.08} x2={W * 0.92} y1={y0 + lines.length * size * 1.05} y2={y0 + lines.length * size * 1.05} stroke={ink} strokeWidth={u * 0.2} />
      </g>
    );
  }
  return (
    <AbsoluteFill style={{ background: paper }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{body}</svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ PILIH PINTU
const Door: React.FC<{ x: number; y: number; w: number; h: number; n: number; open: number; dim: boolean; glow: number; u: number; f: number }> = ({
  x, y, w, h, n, open, dim, glow, u }) => {
  const leafW = w * (1 - open * 0.82);
  return (
    <g opacity={dim ? 0.45 : 1}>
      {glow > 0 ? <rect x={x - w * 0.12} y={y - w * 0.12} width={w * 1.24} height={h + w * 0.12} rx={w * 0.08} fill="#FFD25A" opacity={glow * 0.35} /> : null}
      <rect x={x - w * 0.06} y={y - w * 0.06} width={w * 1.12} height={h + w * 0.06} fill="#3B2412" />
      <rect x={x} y={y} width={w} height={h} fill={open > 0 ? "#FFE8A8" : "#1a1208"} />
      {open > 0 ? <g opacity={open}>
        <rect x={x} y={y} width={w} height={h} fill="#FFF4CC" />
        {Array.from({ length: 6 }, (_, i) => <path key={i} d={`M${x + w * 0.5},${y + h * 0.5} L${x + w * (i / 5)},${y + h * 1.4}`} stroke="#FFFFFF" strokeWidth={w * 0.04} opacity={0.5} />)}
      </g> : null}
      <g>
        <path d={`M${x},${y} L${x + leafW},${y + h * 0.03 * open} L${x + leafW},${y + h - h * 0.03 * open} L${x},${y + h} Z`} fill="#9A6234" />
        <rect x={x + leafW * 0.14} y={y + h * 0.08} width={leafW * 0.72} height={h * 0.34} fill="none" stroke="#7A4A22" strokeWidth={w * 0.03} />
        <rect x={x + leafW * 0.14} y={y + h * 0.52} width={leafW * 0.72} height={h * 0.38} fill="none" stroke="#7A4A22" strokeWidth={w * 0.03} />
        <circle cx={x + leafW * 0.84} cy={y + h * 0.5} r={w * 0.045} fill="#E8B23A" />
      </g>
      <rect x={x + w * 0.3} y={y - w * 0.42} width={w * 0.4} height={w * 0.32} rx={w * 0.06} fill="#E8B23A" stroke="#7A4A22" strokeWidth={w * 0.02} />
      <text x={x + w * 0.5} y={y - w * 0.17} textAnchor="middle" fontFamily="Anton" fontSize={w * 0.26} fill="#3B2412">{n}</text>
    </g>
  );
};

const Doors: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, fps, W, H, wide, art, durF, style } = c;
  const u = Math.min(W, H) / 100;
  const kind = art.kind;
  const ans = art.answer || 0;
  const dw = wide ? H * 0.2 : W * 0.24;
  const dh = dw * 1.85;
  const gap = wide ? W * 0.045 : W * 0.06;
  const x0 = (wide ? W * 0.38 : W / 2) - (dw * 3 + gap * 2) / 2;
  const y0 = H * (wide ? 0.22 : 0.3);
  const reveal = kind === "reveal" || kind === "explain";
  const mid = x0 + (dw * 3 + gap * 2) / 2;
  const open = reveal ? (kind === "explain" ? 1 : ease(f, fps * 0.5, fps * 0.9, Easing.inOut(Easing.cubic))) : 0;
  const cycle = kind === "doors" ? Math.floor(f / (fps * 0.6)) % 3 : -1;
  const third = Math.floor((f / Math.max(1, durF)) * 3);
  const cd = 3 - Math.min(2, third);
  const cdP = ((f / Math.max(1, durF)) * 3) % 1;
  const lights = Array.from({ length: 34 }, (_, i) => {
    const t = i / 34;
    const per = 2 * (W * 0.9 + H * 0.7);
    let d = t * per, x = 0, y = 0;
    const bw = W * 0.9, bh = H * 0.7, bx = W * 0.05, by = H * 0.12;
    if (d < bw) { x = bx + d; y = by; } else if ((d -= bw) < bh) { x = bx + bw; y = by + d; } else if ((d -= bh) < bw) { x = bx + bw - d; y = by + bh; } else { d -= bw; x = bx; y = by + bh - d; }
    return <circle key={i} cx={x} cy={y} r={u * 0.6} fill="#FFE9A6" opacity={0.4 + 0.6 * Math.abs(Math.sin(f / 10 + i))} />;
  });
  return (
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${style.bg}, ${style.bg2})` }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: 46 }, (_, i) => (
          <circle key={`st${i}`} cx={R(`ds${i}`) * W} cy={R(`dy${i}`) * H} r={u * (0.12 + R(`dr${i}`) * 0.25)} fill="#FFF7DA"
            opacity={0.2 + 0.5 * Math.abs(Math.sin(f / (16 + R(`dt${i}`) * 18) + i))} />
        ))}
        {lights}
        {[0, 1, 2].map((i) => {
          const x = x0 + i * (dw + gap);
          const isAns = ans === i + 1;
          const pop = back(f, i * 4, fps * 0.4);
          return (
            <g key={i} transform={`translate(${x + dw / 2},${y0 + dh}) scale(${pop}) translate(${-(x + dw / 2)},${-(y0 + dh)})`}>
              <Door x={x} y={y0} w={dw} h={dh} n={i + 1} open={isAns ? open : 0} dim={reveal && !isAns} glow={cycle === i ? 1 : isAns && reveal ? open : 0} u={u} f={f} />
              {reveal && !isAns ? <path d={`M${x + dw * 0.25},${y0 + dh * 0.35} l${dw * 0.5},${dw * 0.5} m0,${-dw * 0.5} l${-dw * 0.5},${dw * 0.5}`} stroke="#E05A4F"
                strokeWidth={dw * 0.07} strokeLinecap="round" opacity={ease(f, fps * 1.2, fps * 0.3)} /> : null}
              {reveal && isAns ? <g opacity={ease(f, fps * 1.2, fps * 0.3)} transform={`translate(${x + dw / 2},${y0 - dw * 0.75})`}>
                <circle r={dw * 0.2} fill="#2E9E5B" /><path d={`M${-dw * 0.09},0 l${dw * 0.06},${dw * 0.07} l${dw * 0.12},${-dw * 0.13}`} fill="none" stroke="#FFFFFF" strokeWidth={dw * 0.04} strokeLinecap="round" />
              </g> : null}
              {(kind === "doors" || reveal) && art.options?.[i] ? (
                <foreignObject x={x - gap * 0.4} y={y0 + dh + u * 2.5} width={dw + gap * 0.8} height={dh * 0.5}>
                  <div style={{ background: "#FFFFFF", color: "#141B3D", borderRadius: u * 1.6, padding: `${u * 1.2}px ${u * 1}px`, fontFamily: "Montserrat Black",
                    fontSize: u * (wide ? 2.6 : 3.1), lineHeight: 1.1, textAlign: "center", opacity: ease(f, fps * (0.3 + i * 0.15), fps * 0.3) }}>{art.options[i]}</div>
                </foreignObject>
              ) : null}
            </g>
          );
        })}
        {kind === "question" ? [0, 1, 2].map((i) => (
          <text key={i} x={x0 + i * (dw + gap) + dw / 2} y={y0 + dh * 0.62 + Math.sin(f / 8 + i) * u} textAnchor="middle" fontFamily="Anton" fontSize={dw * 0.6}
            fill="#FFD25A" stroke="#3B2412" strokeWidth={dw * 0.02}>?</text>
        )) : null}
        {kind === "countdown" ? (
          <g>
            <rect width={W} height={H} fill="#000000" opacity={0.35} />
            <circle cx={mid} cy={y0 + dh * 0.5} r={dw * 0.75} fill="#141B3D" stroke="#FFD25A" strokeWidth={u * 0.8} />
            <circle cx={mid} cy={y0 + dh * 0.5} r={dw * 0.75} fill="none" stroke="#FFFFFF" strokeWidth={u * 0.8} pathLength={1}
              strokeDasharray="1 1" strokeDashoffset={cdP} transform={`rotate(-90 ${mid} ${y0 + dh * 0.5})`} />
            <text x={mid} y={y0 + dh * 0.5 + dw * 0.32} textAnchor="middle" fontFamily="Anton" fontSize={dw * 0.95} fill="#FFD25A"
              transform={`translate(${mid},${y0 + dh * 0.5}) scale(${1.25 - 0.25 * Easing.out(Easing.back(2))(clamp(cdP * 4))}) translate(${-mid},${-(y0 + dh * 0.5)})`}>{cd}</text>
          </g>
        ) : null}
        {art.label && kind !== "doors" ? (
          <foreignObject x={wide ? W * 0.7 : W * 0.08} y={wide ? H * 0.3 : y0 + dh + (reveal ? dh * 0.42 : u * 4)} width={wide ? W * 0.26 : W * 0.84}
            height={wide ? H * 0.4 : H * 0.14}>
            <div style={{ textAlign: wide ? "left" : "center", fontFamily: "Anton", fontSize: u * (wide ? 5.2 : 5.4), color: "#FFD25A", lineHeight: 1.05,
              opacity: ease(f, fps * 0.4, fps * 0.4) }}>{art.label}</div>
          </foreignObject>
        ) : null}
      </svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ KASET
const level = (c: Ctx, off = 0) => {
  const lv = c.theme.levels;
  if (!lv || !lv.length) return 0.35 + 0.35 * Math.abs(Math.sin((c.f + off) / 3.3) * Math.sin((c.f + off) / 7.1));
  return lv[clamp(c.startF + c.f + off, 0, lv.length - 1)] ?? 0;
};

const Speaker: React.FC<{ who: string; s: number; f: number; talk: number }> = ({ who, s, f, talk }) => {
  const k = s / 100;
  const skin = who === "anak" ? "#F2C49B" : "#EBC29A";
  const hair = who === "nenek" || who === "kakek" ? "#B9B6B0" : "#3A2A22";
  const shirt = ({ nenek: "#8A6A5C", kakek: "#5C6B7A", ibu: "#C46A5A", ayah: "#4A6A8A", anak: "#E8B23A" } as Record<string, string>)[who] || "#8A6A5C";
  const blink = (f % 140) < 5 ? 0.15 : 1;
  const old = who === "nenek" || who === "kakek";
  return (
    <g transform={`scale(${k})`}>
      <path d="M-46,40 C-46,6 -26,-6 0,-6 C26,-6 46,6 46,40 Z" fill={shirt} />
      {who === "nenek" ? <path d="M-14,-4 L0,14 L14,-4" fill="none" stroke="#F3EBDD" strokeWidth={3} /> : null}
      <rect x={-7} y={-16} width={14} height={14} fill={skin} />
      {who === "nenek" || who === "ibu" ? <circle cx={0} cy={-62} r={who === "nenek" ? 10 : 9} fill={hair} /> : null}
      <ellipse cx={0} cy={-36} rx={22} ry={24} fill={skin} />
      {who === "kakek" ? <path d="M-22,-38 C-24,-52 -18,-58 -12,-58 M22,-38 C24,-52 18,-58 12,-58" stroke={hair} strokeWidth={6} fill="none" strokeLinecap="round" />
        : who === "ayah" || who === "anak" ? <path d="M-22,-38 C-24,-62 24,-62 22,-38 C16,-50 -10,-54 -22,-38 Z" fill={hair} />
        : <path d="M-23,-34 C-26,-62 26,-62 23,-34 C18,-48 -14,-52 -23,-34 Z" fill={hair} />}
      {old ? <g fill="none" stroke="#3A3330" strokeWidth={1.6}><circle cx={-8} cy={-38} r={6} /><circle cx={8} cy={-38} r={6} /><path d="M-2,-38 h4" /></g> : null}
      <ellipse cx={-8} cy={-38} rx={1.8} ry={1.8 * blink} fill="#2A2420" />
      <ellipse cx={8} cy={-38} rx={1.8} ry={1.8 * blink} fill="#2A2420" />
      {who === "kakek" || who === "ayah" ? <path d="M-8,-25 q8,-5 16,0" stroke={who === "kakek" ? "#E6E3DE" : "#3A2A22"} strokeWidth={3.5} fill="none" strokeLinecap="round" /> : null}
      <ellipse cx={0} cy={-21} rx={5} ry={0.8 + talk * 4} fill="#7A3A2E" />
      <circle cx={-14} cy={-28} r={3.5} fill="#E8908A" opacity={0.35} /><circle cx={14} cy={-28} r={3.5} fill="#E8908A" opacity={0.35} />
    </g>
  );
};

const Kaset: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, fps, W, H, wide, art, idx, durF } = c;
  const u = Math.min(W, H) / 100;
  const ink = "#2A2420", red = c.style.accent;
  const talk = level(c);
  if (art.kind === "tape") {
    const cw = wide ? W * 0.34 : W * 0.78, ch = cw * 0.62;
    const cx = W / 2 - cw / 2, cy = H * (wide ? 0.2 : 0.26);
    const prog = clamp((c.startF + f) / Math.max(1, (c.theme.levels?.length || durF * 4)));
    const rot = f * 4;
    const reel = (x: number, amt: number) => (
      <g transform={`translate(${x},${cy + ch * 0.44})`}>
        <circle r={ch * (0.085 + amt * 0.07)} fill="#3A2E28" />
        <circle r={ch * 0.075} fill="#F3EBDD" stroke={ink} strokeWidth={u * 0.3} />
        <g transform={`rotate(${rot})`}>{[0, 60, 120, 180, 240, 300].map((a) => <rect key={a} x={-u * 0.3} y={-ch * 0.09} width={u * 0.6} height={ch * 0.05} fill={ink} transform={`rotate(${a})`} />)}</g>
      </g>
    );
    const bars = 48, bw = (wide ? W * 0.4 : W * 0.84) / bars;
    const wy = cy + ch + H * (wide ? 0.05 : 0.06), wx = W / 2 - (bars * bw) / 2, wh = H * (wide ? 0.1 : 0.08);
    return (
      <AbsoluteFill>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
          <g transform={`translate(0,${Math.sin(f / 25) * u * 0.3})`}>
            <rect x={cx} y={cy} width={cw} height={ch} rx={u * 2.4} fill="#E9DFCC" stroke={ink} strokeWidth={u * 0.5} />
            <rect x={cx + cw * 0.06} y={cy + ch * 0.08} width={cw * 0.88} height={ch * 0.62} rx={u * 1.4} fill="#FBF6EC" stroke={ink} strokeWidth={u * 0.3} />
            <rect x={cx + cw * 0.06} y={cy + ch * 0.08} width={cw * 0.88} height={ch * 0.1} fill={red} />
            <text x={cx + cw * 0.5} y={cy + ch * 0.27} textAnchor="middle" fontFamily="Special Elite" fontSize={ch * 0.08} fill={ink}>{art.label || "Kaset kenangan"}</text>
            <rect x={cx + cw * 0.24} y={cy + ch * 0.35} width={cw * 0.52} height={ch * 0.19} rx={ch * 0.095} fill="#4A3E36" stroke={ink} strokeWidth={u * 0.3} />
            {reel(cx + cw * 0.34, 1 - prog)}
            {reel(cx + cw * 0.66, prog)}
            <path d={`M${cx + cw * 0.2},${cy + ch} L${cx + cw * 0.27},${cy + ch * 0.78} L${cx + cw * 0.73},${cy + ch * 0.78} L${cx + cw * 0.8},${cy + ch} Z`} fill="#DDD1BA" stroke={ink} strokeWidth={u * 0.3} />
            {[0.33, 0.45, 0.55, 0.67].map((x, i) => <circle key={i} cx={cx + cw * x} cy={cy + ch * 0.9} r={u * 0.7} fill={ink} />)}
            {[[0.04, 0.06], [0.96, 0.06], [0.04, 0.94], [0.96, 0.94]].map(([x, y], i) => <circle key={i} cx={cx + cw * x} cy={cy + ch * y} r={u * 0.6} fill="#B8AA92" />)}
          </g>
          <rect x={wx - u * 2} y={wy} width={bars * bw + u * 4} height={wh} rx={u * 1.2} fill="#1E1A17" />
          {Array.from({ length: bars }, (_, i) => {
            const v = level(c, (i - bars / 2) * 2);
            const bh = Math.max(u * 0.4, v * wh * 0.8);
            return <rect key={i} x={wx + i * bw + bw * 0.2} y={wy + wh / 2 - bh / 2} width={bw * 0.6} height={bh} rx={bw * 0.3}
              fill={i < bars / 2 ? "#F3EBDD" : "#8B8178"} />;
          })}
          <rect x={W / 2 - u * 0.25} y={wy - u} width={u * 0.5} height={wh + u * 2} fill={red} />
          <circle cx={W / 2} cy={wy - u} r={u * 0.9} fill={red} />
        </svg>
      </AbsoluteFill>
    );
  }
  // pencerita + balon kata coretan
  const s = wide ? H * 0.36 : W * 0.5;
  const px = W * (wide ? 0.34 : 0.5), py = H * (wide ? 0.58 : 0.62);
  const bx = wide ? W * 0.52 : W * 0.12, by = H * (wide ? 0.14 : 0.16), bw = wide ? W * 0.36 : W * 0.76, bh = H * (wide ? 0.3 : 0.17);
  const lines = 3;
  const t = f / fps;
  const prog = clamp(t / Math.max(0.5, durF / fps - 0.4));
  const squig = (row: number) => {
    const y = by + bh * (0.28 + row * 0.24);
    const x0 = bx + bw * 0.1, x1 = bx + bw * 0.9;
    const pts: string[] = [];
    const n = 26;
    for (let i = 0; i <= n; i++) {
      const x = x0 + ((x1 - x0) * i) / n;
      const y2 = y + Math.sin(i * 1.7 + row * 2 + idx) * bh * 0.05 * (0.6 + R(`sq${row}${i}`) * 0.8);
      pts.push(`${i ? "L" : "M"}${x.toFixed(1)},${y2.toFixed(1)}`);
    }
    const p = clamp(prog * lines - row);
    return <path key={row} d={pts.join("")} fill="none" stroke={ink} strokeWidth={u * 0.55} strokeLinecap="round" strokeLinejoin="round"
      pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - p} />;
  };
  const pop = back(f, 2, fps * 0.4);
  return (
    <AbsoluteFill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <g transform={`translate(${bx + bw * 0.3},${by + bh}) scale(${pop}) translate(${-(bx + bw * 0.3)},${-(by + bh)})`}>
          <rect x={bx} y={by} width={bw} height={bh} rx={bh * 0.22} fill="#FFFFFF" stroke={ink} strokeWidth={u * 0.5} />
          <path d={`M${bx + bw * (wide ? 0.12 : 0.34)},${by + bh - u * 0.3} l${-u * 2},${u * 7} l${u * 6},${-u * 7}`} fill="#FFFFFF" stroke={ink} strokeWidth={u * 0.5} strokeLinejoin="round" />
          <rect x={bx + bw * (wide ? 0.12 : 0.34) - u * 1.6} y={by + bh - u * 1.2} width={u * 6.4} height={u * 1.6} fill="#FFFFFF" />
          {Array.from({ length: lines }, (_, r) => squig(r))}
        </g>
        <g transform={`translate(${px},${py})`}><Speaker who={art.speaker} s={s} f={f} talk={talk} /></g>
      </svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ SENJA
const Senja: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, W, H, wide, art, idx, durF } = c;
  const u = Math.min(W, H) / 100;
  const id = `sj${idx}`;
  const hz = H * (wide ? 0.62 : 0.56);
  const sil = "#1E1430";
  const r = wide ? H * 0.2 : W * 0.24;
  const sunY = art.sun === "half" ? hz : hz - r * 0.55;
  const prog = clamp(f / Math.max(1, durF));
  const land = art.subject === "orang" || art.subject === "sepeda" || art.subject === "pohon";
  const groundY = H * (wide ? 0.8 : 0.72);
  const birds = (n: number, x0: number, y0: number, s: number) => Array.from({ length: n }, (_, i) => {
    const flap = Math.sin(f / 4 + i) * s * 0.4;
    const x = x0 + i * s * 2.6 + prog * W * 0.12, y = y0 + (i % 2) * s * 1.2 - i * s * 0.3;
    return <path key={i} d={`M${x - s},${y - flap} Q${x - s * 0.4},${y - s * 0.2} ${x},${y} Q${x + s * 0.4},${y - s * 0.2} ${x + s},${y - flap}`} fill="none" stroke={sil} strokeWidth={s * 0.22} strokeLinecap="round" />;
  });
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <defs>
          <linearGradient id={`${id}sky`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#2B1E3F" /><stop offset="0.45" stopColor="#7A3E6B" /><stop offset="0.8" stopColor="#E86A5C" /><stop offset="1" stopColor="#F7B267" />
          </linearGradient>
          <linearGradient id={`${id}sun`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FFE9A8" /><stop offset="1" stopColor="#FF9E6B" /></linearGradient>
          <linearGradient id={`${id}sea`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5A2E5E" /><stop offset="1" stopColor="#1E1430" /></linearGradient>
          <clipPath id={`${id}clip`}><rect width={W} height={hz} /></clipPath>
        </defs>
        <rect width={W} height={hz + 2} fill={`url(#${id}sky)`} />
        <g clipPath={`url(#${id}clip)`}>
          <circle cx={W / 2} cy={sunY + prog * u * 2} r={r} fill={`url(#${id}sun)`} />
          {[0, 1, 2, 3, 4].map((i) => <rect key={i} x={W / 2 - r} y={sunY + prog * u * 2 + r * (0.18 + i * 0.17)} width={r * 2} height={r * (0.03 + i * 0.022)} fill="#E86A5C" />)}
        </g>
        {birds(3, W * 0.18, H * 0.22, u * 2.2)}
        {art.subject === "kota" ? <City x0={-W * 0.02} x1={W * 1.02} base={hz} h={H * 0.16} color={sil} seed={`${id}k`} f={f} lit="#FFD27A" n={13} /> : null}
        {art.subject === "gunung" ? <g>
          <path d={`M0,${hz} L${W * 0.22},${hz - H * 0.14} L${W * 0.4},${hz - H * 0.05} L${W * 0.62},${hz - H * 0.2} L${W},${hz - H * 0.04} L${W},${hz} Z`} fill="#4A2850" />
          <path d={`M0,${hz} L${W * 0.12},${hz - H * 0.07} L${W * 0.3},${hz} Z M${W * 0.5},${hz} L${W * 0.78},${hz - H * 0.1} L${W},${hz} Z`} fill={sil} />
        </g> : null}
        <rect y={hz} width={W} height={H - hz} fill={`url(#${id}sea)`} />
        {Array.from({ length: 9 }, (_, i) => {
          const w = r * (1.5 - i * 0.12) * (0.75 + 0.25 * Math.sin(f / 10 + i * 1.3));
          return <rect key={i} x={W / 2 - w / 2} y={hz + u * (1.4 + i * 2.6)} width={w} height={u * 0.7} rx={u * 0.35} fill="#FFC48A" opacity={0.6 - i * 0.05} />;
        })}
        {art.subject === "perahu" ? (
          <g transform={`translate(${W * 0.62},${hz + H * 0.05 + Math.sin(f / 20) * u * 0.6}) rotate(${Math.sin(f / 26) * 2.5})`}>
            <path d={`M${-u * 12},0 h${u * 24} l${-u * 4},${u * 4} h${-u * 16} Z`} fill={sil} />
            <rect x={-u * 1.2} y={-u * 7} width={u * 2.4} height={u * 7} rx={u} fill={sil} />
            <circle cy={-u * 8.4} r={u * 1.5} fill={sil} />
            <path d={`M${-u * 3},${-u * 9} h${u * 6} l${-u * 1},${-u * 1.4} h${-u * 4} Z`} fill={sil} />
            <path d={`M${u * 1},${-u * 5} L${u * 10},${-u * 12}`} stroke={sil} strokeWidth={u * 0.4} />
            <path d={`M${u * 10},${-u * 12} q${u},${u * 6} ${u * 0.4},${u * 12}`} fill="none" stroke={sil} strokeWidth={u * 0.15} opacity={0.7} />
          </g>
        ) : null}
        {land ? <path d={`M0,${groundY} Q${W * 0.5},${groundY - H * 0.03} ${W},${groundY + H * 0.01} L${W},${H} L0,${H} Z`} fill={sil} /> : null}
        {art.subject === "orang" ? (
          <g transform={`translate(${W * 0.36},${groundY - H * 0.005})`}>
            <rect x={-u * 1.8} y={-u * 14} width={u * 3.6} height={u * 9} rx={u * 1.4} fill={sil} />
            <circle cy={-u * 16} r={u * 2} fill={sil} />
            <path d={`M${-u},${-u * 5} l${-u * 0.6},${u * 5} M${u},${-u * 5} l${u * 0.6},${u * 5}`} stroke={sil} strokeWidth={u * 1.3} strokeLinecap="round" />
          </g>
        ) : null}
        {art.subject === "pohon" ? <g transform={`translate(${W * 0.74},${groundY - H * 0.01}) rotate(${Math.sin(f / 30) * 1.2})`}>
          <path d={`M${-u},0 L${-u * 0.6},${-u * 16} L${-u * 6},${-u * 22} M${-u * 0.6},${-u * 12} L${u * 5},${-u * 20}`} stroke={sil} strokeWidth={u * 1.6} strokeLinecap="round" fill="none" />
          <circle cx={-u * 6} cy={-u * 25} r={u * 6} fill={sil} /><circle cx={u * 4} cy={-u * 24} r={u * 7} fill={sil} /><circle cx={-u * 1} cy={-u * 30} r={u * 6.5} fill={sil} />
        </g> : null}
        {art.subject === "sepeda" ? (
          <g transform={`translate(${W * (0.2 + prog * 0.45)},${groundY - H * 0.012})`}>
            {[-u * 4.5, u * 4.5].map((x, i) => <g key={i} transform={`translate(${x},${-u * 3.2})`}><circle r={u * 3.2} fill="none" stroke={sil} strokeWidth={u * 0.6} />
              <path d={`M0,${-u * 3.2} V${u * 3.2} M${-u * 3.2},0 H${u * 3.2}`} stroke={sil} strokeWidth={u * 0.3} transform={`rotate(${f * 6})`} /></g>)}
            <path d={`M${-u * 4.5},${-u * 3.2} L${-u * 1},${-u * 3.2} L${u * 4.5},${-u * 3.2} L${u * 2.5},${-u * 7.5} L${-u * 2},${-u * 7.5} Z M${-u * 1},${-u * 3.2} L${-u * 2.5},${-u * 8.6}`} fill="none" stroke={sil} strokeWidth={u * 0.6} />
            <rect x={-u * 3.6} y={-u * 15} width={u * 3} height={u * 7} rx={u} fill={sil} transform={`rotate(12 ${-u * 2} ${-u * 11})`} />
            <circle cx={-u * 0.6} cy={-u * 16.5} r={u * 1.7} fill={sil} />
          </g>
        ) : null}
        {art.subject === "burung" ? birds(6, W * 0.25, H * 0.34, u * 3.4) : null}
      </svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ MISTERI
const flashAt = (gf: number, fps: number) => {
  const t = gf / fps, period = 6.5;
  const k = t % period;
  if (t < 1.5) return 0;
  return k < 0.08 ? 1 : k < 0.16 ? 0.25 : k < 0.24 ? 0.8 : k < 0.6 ? 0.8 * (1 - (k - 0.24) / 0.36) : 0;
};

const Misteri: React.FC<{ c: Ctx }> = ({ c }) => {
  const { f, fps, W, H, wide, art, idx, durF } = c;
  const u = Math.min(W, H) / 100;
  const id = `ms${idx}`;
  const ground = H * (wide ? 0.78 : 0.68);
  const sil = "#07090D";
  const flash = art.storm ? flashAt(c.startF + f, fps) : 0;
  const lit = "#F2C46B";
  const flick = 0.75 + 0.25 * Math.sin(f / 5) * Math.sin(f / 11);
  const zoom = 1 + 0.04 * clamp(f / Math.max(1, durF));
  const cloud = (x: number, y: number, s: number, col: string, k: number) => (
    <g key={k} transform={`translate(${x + ((f * (0.2 + k * 0.08)) % (W * 0.3))},${y})`} fill={col}>
      <ellipse rx={s * 1.6} ry={s * 0.5} /><ellipse cx={-s * 0.6} cy={-s * 0.35} rx={s * 0.7} ry={s * 0.5} /><ellipse cx={s * 0.5} cy={-s * 0.45} rx={s * 0.8} ry={s * 0.6} />
    </g>
  );
  let subject: React.ReactNode = null;
  const s = wide ? H * 0.3 : W * 0.42;
  const cx = W * 0.5;
  if (art.subject === "menara") {
    subject = (
      <g>
        <path d={`M${cx - s * 0.08},${ground} V${ground - s * 0.9} L${cx},${ground - s * 1.45} L${cx + s * 0.08},${ground - s * 0.9} V${ground} Z`} fill={sil} />
        <rect x={cx - s * 0.03} y={ground - s * 0.75} width={s * 0.06} height={s * 0.1} fill={lit} opacity={flick * 0.7} />
        <g transform={`translate(${cx + s * 0.55},0)`}>
          <rect x={-s * 0.18} y={ground - s * 0.24} width={s * 0.36} height={s * 0.24} fill={sil} />
          <path d={`M${-s * 0.24},${ground - s * 0.22} L0,${ground - s * 0.42} L${s * 0.24},${ground - s * 0.22} Z`} fill={sil} />
          <rect x={-s * 0.05} y={ground - s * 0.16} width={s * 0.1} height={s * 0.08} fill={lit} opacity={flick} />
        </g>
      </g>
    );
  } else if (art.subject === "hutan") {
    subject = (
      <g stroke={sil} strokeLinecap="round" fill="none">
        {Array.from({ length: 6 }, (_, i) => {
          const x = W * (0.08 + i * 0.17), h = s * (0.8 + R(`${id}h${i}`) * 0.6);
          return (
            <g key={i} strokeWidth={u * (1.6 - (i % 2) * 0.5)}>
              <path d={`M${x},${ground} V${ground - h}`} />
              <path d={`M${x},${ground - h * 0.55} l${-h * 0.2},${-h * 0.25} M${x},${ground - h * 0.7} l${h * 0.22},${-h * 0.2} M${x},${ground - h * 0.85} l${-h * 0.12},${-h * 0.15} M${x - h * 0.1},${ground - h * 0.68} l${-h * 0.08},${-h * 0.1}`} strokeWidth={u * 0.6} />
            </g>
          );
        })}
      </g>
    );
  } else if (art.subject === "jalan") {
    subject = (
      <g>
        <path d={`M${W * 0.47},${ground} L${W * 0.53},${ground} L${W * 0.95},${H} L${W * 0.05},${H} Z`} fill="#141922" />
        {Array.from({ length: 6 }, (_, i) => {
          const t = ((i + (f / fps) * 0.4) % 6) / 6;
          const y = ground + (H - ground) * t * t, w = u * (0.3 + t * 2.2);
          return <rect key={i} x={W / 2 - w / 2} y={y} width={w} height={u * (0.6 + t * 4)} fill="#C9C2AE" opacity={0.5} />;
        })}
        <rect x={W * 0.7} y={ground - s * 0.9} width={u * 0.9} height={s * 0.9 + (H - ground) * 0.2} fill={sil} />
        <circle cx={W * 0.7 - u * 2} cy={ground - s * 0.88} r={u * 12} fill={lit} opacity={0.12 * flick} />
        <circle cx={W * 0.7 - u * 2} cy={ground - s * 0.88} r={u * 1.4} fill={lit} opacity={flick} />
      </g>
    );
  } else if (art.subject === "pintu") {
    const open = ease(f, fps * 1.2, fps * 2, Easing.inOut(Easing.quad)) * 0.25;
    subject = (
      <g>
        <rect x={0} y={ground - s * 1.1} width={W} height={s * 1.1} fill="#151A22" />
        {Array.from({ length: 14 }, (_, i) => <rect key={i} x={(i % 7) * W / 7 + (Math.floor(i / 7) % 2) * W / 14} y={ground - s * 1.1 + Math.floor(i / 7) * s * 0.18 + s * 0.1}
          width={W / 7 - u} height={s * 0.16} fill="#1B212B" />)}
        <rect x={cx - s * 0.22} y={ground - s * 0.7} width={s * 0.44} height={s * 0.7} fill={lit} opacity={0.85 * flick} />
        <path d={`M${cx - s * 0.22},${ground - s * 0.7} L${cx + s * 0.22 - s * 0.44 * open},${ground - s * 0.7 + u * open * 3} L${cx + s * 0.22 - s * 0.44 * open},${ground - u * open * 3} L${cx - s * 0.22},${ground} Z`} fill="#0B0E13" />
        <path d={`M${cx - s * 0.22},${ground} L${cx + s * 0.22},${ground} L${cx + s * 0.6},${H} L${cx - s * 0.6},${H} Z`} fill={lit} opacity={0.08 * flick} />
      </g>
    );
  } else if (art.subject === "jendela") {
    const shadow = Math.sin(f / 30) > 0.2;
    subject = (
      <g>
        <rect x={0} y={ground - s * 1.3} width={W} height={s * 1.3} fill="#141922" />
        <rect x={cx - s * 0.3} y={ground - s * 1.05} width={s * 0.6} height={s * 0.7} fill={lit} opacity={0.8 * flick} />
        {shadow ? <g fill="#2A2018" opacity={0.85}><circle cx={cx + s * 0.05} cy={ground - s * 0.75} r={s * 0.07} /><rect x={cx - s * 0.06} y={ground - s * 0.68} width={s * 0.22} height={s * 0.3} rx={s * 0.08} /></g> : null}
        <path d={`M${cx},${ground - s * 1.05} V${ground - s * 0.35} M${cx - s * 0.3},${ground - s * 0.7} H${cx + s * 0.3}`} stroke="#0B0E13" strokeWidth={u * 0.9} />
        <rect x={cx - s * 0.3} y={ground - s * 1.05} width={s * 0.6} height={s * 0.7} fill="none" stroke="#0B0E13" strokeWidth={u * 1.4} />
      </g>
    );
  } else {
    subject = (
      <g>
        <rect x={cx - s * 0.36} y={ground - s * 0.5} width={s * 0.72} height={s * 0.5} fill={sil} />
        <path d={`M${cx - s * 0.44},${ground - s * 0.48} L${cx - s * 0.1},${ground - s * 0.9} L${cx + s * 0.44},${ground - s * 0.48} Z`} fill={sil} />
        <rect x={cx + s * 0.18} y={ground - s * 0.84} width={s * 0.08} height={s * 0.2} fill={sil} />
        <rect x={cx - s * 0.2} y={ground - s * 0.36} width={s * 0.12} height={s * 0.12} fill={lit} opacity={flick} />
        <rect x={cx + s * 0.1} y={ground - s * 0.36} width={s * 0.12} height={s * 0.12} fill="#1B2230" />
        <path d={`M${cx - s * 0.55},${ground} L${cx - s * 0.5},${ground - s * 0.6} M${cx - s * 0.52},${ground - s * 0.4} l${-s * 0.1},${-s * 0.12}`} stroke={sil} strokeWidth={u * 0.8} strokeLinecap="round" />
      </g>
    );
  }
  const boltX = W * (0.25 + R(`${id}b${Math.floor((c.startF + f) / (fps * 6.5))}`) * 0.5);
  const bolt: Pt[] = [[boltX, H * 0.08], [boltX - u * 3, H * 0.18], [boltX + u * 2, H * 0.2], [boltX - u * 4, H * 0.32], [boltX + u, H * 0.34], [boltX - u * 2, H * 0.44]];
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ transform: `scale(${zoom})`, transformOrigin: "50% 60%" }}>
        <defs>
          <linearGradient id={`${id}sky`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#0B0F16" /><stop offset="1" stopColor="#2A3445" /></linearGradient>
          <linearGradient id={`${id}fog`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#9AA6B8" stopOpacity={0} /><stop offset="0.5" stopColor="#9AA6B8" stopOpacity={0.16} /><stop offset="1" stopColor="#9AA6B8" stopOpacity={0} /></linearGradient>
        </defs>
        <rect width={W} height={H} fill={`url(#${id}sky)`} />
        <circle cx={W * 0.74} cy={H * 0.17} r={u * 20} fill="#9FB3D6" opacity={0.12} />
        <circle cx={W * 0.74} cy={H * 0.17} r={u * 6} fill="#C9D3E3" opacity={0.55} />
        {flash > 0 ? <rect width={W} height={H * 0.7} fill="#C9D6F0" opacity={flash * 0.35} /> : null}
        {[cloud(W * 0.1, H * 0.1, u * 14, "#1A2130", 0), cloud(W * 0.6, H * 0.14, u * 17, "#202939", 1), cloud(W * 0.25, H * 0.22, u * 12, "#2A3445", 2), cloud(W * 0.8, H * 0.28, u * 10, "#273041", 3)]}
        {flash > 0.5 ? <path d={poly(bolt)} fill="none" stroke="#F4F7FF" strokeWidth={u * 0.7} strokeLinejoin="round" opacity={flash} /> : null}
        <path d={hills(W * 1.2, H, ground, H * 0.03, `${id}gr`, 3)} transform={`translate(${-W * 0.1},0)`} fill="#0A0E14" />
        {subject}
        <rect x={-W * 0.2 + ((f * 0.6) % (W * 0.2))} y={ground - H * 0.08} width={W * 1.4} height={H * 0.16} fill={`url(#${id}fog)`} />
      </svg>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ lapisan efek di atas semua adegan
export const ThemeOverlay: React.FC<{ theme: ThemeInfo; style: Style }> = ({ theme }) => {
  const f = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const u = Math.min(W, H) / 100;
  const ov = new Set(theme.overlays || []);
  const heavy = theme.id === "misteri";
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {ov.has("stars") ? (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", inset: 0, mixBlendMode: "screen" }}>
          {Array.from({ length: 50 }, (_, i) => (
            <circle key={i} cx={R(`sx${i}`) * W} cy={R(`sy${i}`) * H * 0.45} r={u * (0.12 + R(`ss${i}`) * 0.28)} fill="#FFF7DA"
              opacity={0.25 + 0.6 * Math.abs(Math.sin(f / (14 + R(`st${i}`) * 20) + i))} />
          ))}
        </svg>
      ) : null}
      {ov.has("fireflies") ? (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", inset: 0 }}>
          <defs><radialGradient id="ff"><stop offset="0" stopColor="#FFF4A8" stopOpacity={1} /><stop offset="0.25" stopColor="#E9F27A" stopOpacity={0.7} /><stop offset="1" stopColor="#E9F27A" stopOpacity={0} /></radialGradient></defs>
          {Array.from({ length: 22 }, (_, i) => {
            const t = f / fps;
            const x = (R(`fx${i}`) * W + Math.sin(t * 0.5 + i) * u * 6 + t * u * 0.6 * (R(`fd${i}`) - 0.5)) % W;
            const y = H * (0.4 + R(`fy${i}`) * 0.42) + Math.cos(t * 0.7 + i * 2) * u * 4;
            const o = clamp(0.2 + 0.8 * Math.abs(Math.sin(t * (0.8 + R(`fp${i}`)) + i)));
            return <circle key={i} cx={x} cy={y} r={u * 2.2} fill="url(#ff)" opacity={o} />;
          })}
        </svg>
      ) : null}
      {ov.has("rain") ? (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", inset: 0 }}>
          {Array.from({ length: heavy ? 110 : 60 }, (_, i) => {
            const sp = (heavy ? 2.4 : 1.6) * (0.7 + R(`rs${i}`) * 0.6);
            const len = u * (heavy ? 5 : 3.5) * sp;
            const y = ((R(`ry${i}`) * H * 1.3 + f * u * sp * 1.4) % (H * 1.3)) - H * 0.15;
            const x = (R(`rx${i}`) * W * 1.2 - y * 0.12) % (W * 1.2);
            return <line key={i} x1={x} y1={y} x2={x - len * 0.12} y2={y + len} stroke="#CFE0FF" strokeWidth={u * 0.14}
              opacity={(heavy ? 0.28 : 0.2) * (0.5 + R(`ro${i}`))} strokeLinecap="round" />;
          })}
        </svg>
      ) : null}
      {ov.has("lightning") ? <AbsoluteFill style={{ background: "#DDE6FF", opacity: flashAt(f, fps) * 0.22, mixBlendMode: "screen" }} /> : null}
      {ov.has("vignette") ? <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.5) 100%)" }} /> : null}
      {ov.has("paper") ? <AbsoluteFill style={{ backgroundImage: noise(11, 0.9, 0.5), opacity: 0.08, mixBlendMode: "multiply" }} /> : null}
      {ov.has("grain") ? <AbsoluteFill style={{ backgroundImage: noise(Math.floor(f / 2) % 6, 0.95, 0.55), opacity: 0.07, mixBlendMode: "overlay" }} /> : null}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ satu adegan bertema
const SCENES: Record<string, React.FC<{ c: Ctx }>> = {
  stickman: Stickman, lofi: Lofi, dongeng: Dongeng, berita_data: DataScene, pilih_pintu: Doors, kaset: Kaset, senja: Senja, misteri: Misteri,
};

export const ThemeArt: React.FC<{ sc: Scene; idx: number; durF: number; style: Style; theme: ThemeInfo; startF: number }> = ({
  sc, idx, durF, style, theme, startF }) => {
  const f = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const Comp = SCENES[theme.id];
  if (!Comp) return null;
  const c: Ctx = { f, fps, W, H, u: Math.min(W, H) / 100, wide: W / H > 1.15, idx, durF, art: (sc as any).art || {}, style, sc, startF, theme };
  return <AbsoluteFill style={{ background: style.bg, overflow: "hidden" }}><Comp c={c} /></AbsoluteFill>;
};

// Judul besar di atas tidak perlu bila adegan sudah menampilkan teksnya sendiri.
export const themeHidesHeading = (theme: ThemeInfo | undefined, sc: Scene) => {
  const a: any = (sc as any).art;
  if (!theme || !a) return false;
  return (theme.id === "berita_data" && a.kind === "title") || (theme.id === "pilih_pintu" && a.kind === "countdown");
};
