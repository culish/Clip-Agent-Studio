// Adegan "Motion AI": HTML + CSS + kode animasi (gaya GSAP) yang ditulis AI, dijalankan MotionKit dan di-seek per frame.
import React, { useLayoutEffect, useRef, useState } from "react";
import { AbsoluteFill, continueRender, delayRender, useCurrentFrame, useVideoConfig } from "remotion";
import { buildScene, checkLayout, reportError, reportLayout, Timeline } from "./motionkit";
import type { Scene } from "./types";

export type MotionDesign = {
  bg: string; surface: string; ink: string; muted: string; accent: string; accent2: string;
  head: string; body: string; radius?: number;
};
export type MotionCode = { html: string; css: string; js: string };

export const baseCss = (d: MotionDesign, W: number, H: number) => `
  --bg:${d.bg};--surface:${d.surface};--ink:${d.ink};--muted:${d.muted};--accent:${d.accent};--accent2:${d.accent2};
  --font-head:"${d.head}";--font-body:"${d.body}";--radius:${d.radius ?? 28}px;--W:${W}px;--H:${H}px;--u:${Math.min(W, H) / 100}px;
  position:absolute;inset:0;width:${W}px;height:${H}px;overflow:hidden;background:var(--bg);color:var(--ink);
  font-family:var(--font-body),sans-serif;font-size:${Math.round(Math.min(W, H) * 0.04)}px;line-height:1.2;
  * { box-sizing:border-box; }
  .center { position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:calc(var(--u)*3); }
  .stack { display:flex;flex-direction:column;gap:calc(var(--u)*2); }
  .row { display:flex;align-items:center;gap:calc(var(--u)*2); }
  .title { font-family:var(--font-head),sans-serif;font-size:calc(var(--u)*11);line-height:0.98;letter-spacing:-0.01em; }
  .subtitle { font-size:calc(var(--u)*5);color:var(--muted);line-height:1.2; }
  .kicker { font-size:calc(var(--u)*3.4);letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);font-weight:800; }
  .big { font-family:var(--font-head),sans-serif;font-size:calc(var(--u)*24);line-height:0.9;color:var(--accent); }
  .card { background:var(--surface);border-radius:var(--radius);padding:calc(var(--u)*4);box-shadow:0 calc(var(--u)*1.2) calc(var(--u)*4) rgba(0,0,0,0.12); }
  .pill { display:inline-flex;align-items:center;gap:calc(var(--u)*1.2);padding:calc(var(--u)*1.2) calc(var(--u)*3);border-radius:999px;background:var(--accent);color:var(--bg);font-weight:800; }
  .accent { color:var(--accent); } .accent2 { color:var(--accent2); } .muted { color:var(--muted); }
  .hl { background:linear-gradient(transparent 58%, var(--accent2) 58%); padding:0 0.08em; }
`;

const Fallback: React.FC<{ text: string; d: MotionDesign }> = ({ text, d }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const words = (text || "").split(/\s+/).filter(Boolean).slice(0, 10);
  return (
    <AbsoluteFill style={{ background: d.bg, alignItems: "center", justifyContent: "center", padding: "8%" }}>
      <div style={{ fontFamily: d.head, color: d.ink, fontSize: width * 0.1, lineHeight: 1, textAlign: "center" }}>
        {words.map((w, i) => {
          const p = Math.min(1, Math.max(0, (frame - i * 3) / (fps * 0.35)));
          return <span key={i} style={{ display: "inline-block", marginRight: "0.25em", opacity: p, transform: `translateY(${(1 - p) * 40}px)`,
            color: i === words.length - 1 ? d.accent : d.ink }}>{w}</span>;
        })}
      </div>
    </AbsoluteFill>
  );
};

export const MotionScene: React.FC<{ sc: Scene; idx: number; durF: number; design: MotionDesign; validate?: boolean }> = ({
  sc, idx, durF, design }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const ref = useRef<HTMLDivElement>(null);
  const tl = useRef<Timeline | null>(null);
  const [failed, setFailed] = useState(false);
  const [handle] = useState(() => delayRender(`Motion adegan ${idx + 1}`));
  const code = (sc as any).motion as MotionCode;
  const sid = `ms-${idx}`;
  const mid = String((sc as any).motionId || `s${idx + 1}`);   // nama adegan di laporan galat
  useLayoutEffect(() => {
    let done = false;
    const finish = () => { if (!done) { done = true; continueRender(handle); } };
    const run = async () => {
      try {
        if (typeof document !== "undefined" && (document as any).fonts?.ready) await (document as any).fonts.ready;
      } catch { /* abaikan */ }
      try {
        if (!ref.current) throw new Error("wadah adegan tidak ada");
        const words = ((sc as any).sceneWords || []) as { s: number; e: number; t: string }[];
        tl.current = buildScene(ref.current, code, { id: mid, w: W, h: H, dur: durF / fps, words, lang: (sc as any).lang || "id",
          heading: sc.heading || "" });
        tl.current.seek(frame / fps);
        if ((sc as any).motionCheck) reportLayout(mid, checkLayout(ref.current, W, H), +(frame / fps).toFixed(2));
      } catch (e) {
        reportError(e, mid);
        setFailed(true);
      }
      finish();
    };
    run();
    const guard = setTimeout(finish, 20000);
    return () => clearTimeout(guard);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useLayoutEffect(() => {
    if (!tl.current) return;
    try { tl.current.seek(frame / fps); } catch (e) { reportError(e, mid); }
  }, [frame, fps]);
  if (failed || !code) return <Fallback text={sc.heading || ""} d={design} />;
  return (
    <AbsoluteFill style={{ background: design.bg }}>
      <style>{`#${sid}{${baseCss(design, W, H)}}\n#${sid}{${code.css || ""}}`}</style>
      <div id={sid} ref={ref} />
    </AbsoluteFill>
  );
};
