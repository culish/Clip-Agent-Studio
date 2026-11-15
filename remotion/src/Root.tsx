import React from "react";
import { Composition } from "remotion";
import { CartoonStory } from "./CartoonStory";
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

export const RemotionRoot: React.FC = () => {
  return (
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
  );
};
