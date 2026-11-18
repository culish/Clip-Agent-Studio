import React from "react";
import { Composition } from "remotion";
import { CartoonStory } from "./CartoonStory";
import { Kolase, type KolaseProps } from "./Kolase";
import type { StoryProps } from "./types";

// Contoh props agar komposisi bisa dibuka di Remotion Studio (npm run studio).
// Clip Agent mengirim props sebenarnya (adegan, gambar, kata, gaya) saat merender.
const DEMO: StoryProps = {
  fps: 30,
  width: 1080,
  height: 1920,
  duration: 9,
  audioParts: [],
  progressBar: true,
  hook: "The habit that changed everything",
  words: "Nobody tells you how loud the launch really is. Your whole body shakes for eight minutes straight."
    .split(" ")
    .map((t, i) => ({ s: 0.4 + i * 0.42, e: 0.4 + i * 0.42 + 0.36, t })),
  scenes: [
    { start: 0, dur: 3, heading: "Launch day", bubble: "Nobody tells you how loud it is!", sfx: "BOOM!", camera: "zoom_in", transition: "slide" },
    { start: 3, dur: 3, heading: "Eight minutes", camera: "pan_right", transition: "wipe" },
    { start: 6, dur: 3, heading: "Then silence", sfx: "...", camera: "zoom_out", transition: "none" },
  ],
  style: {
    name: "Komik klasik", bg: "#FFF4D6", bg2: "#F2C14E", accent: "#FFD400", ink: "#111111", text: "#FFFFFF",
    font: "Bangers", captionFont: "Bangers", frame: "panel", captions: "bubble", texture: "halftone", motion: "smooth",
    sfx: true, videoFilter: "none", uppercase: true, transitionSec: 0.35,
  },
};


const KDEMO_WORDS = "Pada tahun 1998 harga beras naik 300 persen dalam beberapa bulan saja".split(" ")
  .map((t, i) => ({ s: 0.3 + i * 0.4, e: 0.3 + i * 0.4 + 0.32, t }));
const KDEMO: KolaseProps = {
  fps: 30, width: 1080, height: 1920, duration: 6, lang: "id", words: KDEMO_WORDS,
  theme: { name: "Kertas koran", paper: "#ECE5D3", paper2: "#DCD2BC", ink: "#161514", accent: "#D12A1F", marker: "#FFE14A", dark: "#1C1B19" },
  scenes: [
    { id: "a", idx: 0, start: 0, end: 3, layout: "judul", heading: "Harga beras melonjak", keyword: "beras", label: "", places: [], quote: "",
      image: "", cutout: false, tilt: -1, enter: "none", seed: 11, dark: false, captions: true, words: KDEMO_WORDS.slice(0, 7),
      mark: null, markAt: 1, reveal: [0.2, 1.5, 2.0], hot: 1 },
    { id: "b", idx: 1, start: 3, end: 6, layout: "angka", heading: "Dalam beberapa bulan", keyword: "", label: "kenaikan harga beras", places: [], quote: "",
      image: "", cutout: false, tilt: 1, enter: "kiri", seed: 23, dark: false, captions: true, words: KDEMO_WORDS.slice(7),
      mark: null, markAt: 3.5, number: { value: 300, decimals: 0, prefix: "", suffix: "persen", group: ".", dec: ",", year: false, at: 3.3 }, countEnd: 4.3 },
  ],
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
    <Composition
      id="CartoonStory"
      component={CartoonStory as unknown as React.FC<Record<string, unknown>>}
      durationInFrames={270}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={DEMO as unknown as Record<string, unknown>}
      calculateMetadata={({ props }) => {
        const p = props as unknown as StoryProps;
        return {
          durationInFrames: Math.max(1, Math.round(p.duration * p.fps)),
          fps: p.fps,
          width: p.width,
          height: p.height,
        };
      }}
      />
      <Composition
        id="Kolase"
        component={Kolase as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={180}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={KDEMO as unknown as Record<string, unknown>}
        calculateMetadata={({ props }) => {
          const p = props as unknown as KolaseProps;
          return { durationInFrames: Math.max(1, Math.round(p.duration * p.fps)), fps: p.fps, width: p.width, height: p.height };
        }}
      />
    </>
  );
};
