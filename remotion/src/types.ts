export type Camera = "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "static";
export type TransitionKind = "none" | "fade" | "slide" | "wipe" | "flip" | "clockwipe" | "iris";

export type Scene = {
  start: number; // detik, pada timeline video hasil
  dur: number; // detik
  image?: string; // URL gambar adegan (kartun lokal / AI / foto asli)
  video?: string; // URL klip bersih (mode video bergerak)
  videoFrom?: number; // detik di dalam klip bersih
  heading?: string; // teks judul besar
  bubble?: string; // balon kata (gaya komik)
  sfx?: string; // kata efek suara, mis. "BOOM!"
  camera: Camera;
  transition: TransitionKind; // transisi MENUJU adegan berikutnya
  focus?: [number, number]; // pusat wajah 0..1
  art?: Record<string, any>; // adegan bertema: digambar vektor oleh Themes.tsx
};

export type Word = { s: number; e: number; t: string };

export type AudioPart = { at: number; from: number; to: number };

export type Style = {
  name: string;
  bg: string;
  bg2: string;
  accent: string;
  ink: string;
  text: string;
  font: string;
  captionFont: string;
  frame: "full" | "panel" | "card" | "paper" | "plain";
  captions: "karaoke" | "pop" | "bubble" | "none";
  texture: "none" | "halftone" | "paper" | "grain" | "speedlines";
  motion: "smooth" | "stop";
  sfx: boolean;
  videoFilter: "none" | "posterize";
  uppercase: boolean;
  transitionSec: number;
  captionStroke?: number; // pengali tebal garis tepi caption (bawaan 1)
};

export type Music = {
  src: string;
  volume: number; // 0..1 saat tidak ada suara
  duck: number; // 0..1 pengali volume saat ada suara (mis. 0.3)
};

export type StoryProps = {
  fps: number;
  width: number;
  height: number;
  duration: number;
  audio?: string;
  audioParts: AudioPart[];
  scenes: Scene[];
  words: Word[];
  hook?: string;
  progressBar: boolean;
  style: Style;
  music?: Music;
  speech?: [number, number][]; // rentang detik berisi suara, untuk menurunkan musik (ducking)
  theme?: { id: string; overlays?: string[]; levels?: number[] }; // tema video (Buat video)
};
