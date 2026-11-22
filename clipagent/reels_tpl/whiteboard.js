const tin = $(".tin")[0]; tin.textContent = D.title || D.heading || "";
fit($(".ttl")[0], U * 10, U * 6);
const row = $(".row")[0];
const items = (D.items && D.items.length ? D.items : [{ icon: "idea", label: "" }]).slice(0, 3);
const link = D.link || "arrow";
const els = [];
items.forEach((it, k) => {
  if (k && link !== "none") {
    const lk = make("div", "lk");
    if (link === "arrow") lk.innerHTML = '<svg viewBox="0 0 56 40" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20 C18 14 32 26 50 20"/><path d="M38 10 L50 20 L38 30"/></svg>';
    else lk.textContent = link === "plus" ? "+" : "vs";
    row.appendChild(lk); els.push({ link: lk });
  }
  const box = make("div", "it");
  box.innerHTML = icon(it.icon, "ic", 2.6);
  const lb = make("div", "lb", it.label || ""); box.appendChild(lb); row.appendChild(box);
  els.push({ box, svg: box.querySelector("svg"), lb });
});
const n = items.length;
const sz = n === 1 ? 40 : n === 2 ? 30 : 22;
row.querySelectorAll(".it svg").forEach((s) => { s.style.width = s.style.height = (U * sz) + "px"; });
row.querySelectorAll(".lb").forEach((l) => { l.style.fontSize = (U * (n === 3 ? 6 : 7.5)) + "px"; });
// posisi di kanvas (piksel) untuk tangan yang menggambar
const R0 = root.getBoundingClientRect(); const kk = S.w / R0.width;
const rect = (el) => { const r = el.getBoundingClientRect(); return { x: (r.left - R0.left) * kk, y: (r.top - R0.top) * kk, w: r.width * kk, h: r.height * kk }; };
const segs = [];
const wiggle = (a, b) => (u) => [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u + Math.sin(u * Math.PI * 8) * U * 1.2];
const pathSeg = (svg, paths) => { const r = rect(svg); const sc = r.w / 48; const L = paths.map((p) => p.getTotalLength()); const tot = L.reduce((a, b) => a + b, 0) || 1;
  return (u) => { let l = u * tot; for (let k = 0; k < paths.length; k++) { if (l <= L[k] || k === paths.length - 1) { const pt = paths[k].getPointAtLength(Math.max(0, Math.min(l, L[k]))); return [r.x + pt.x * sc, r.y + pt.y * sc]; } l -= L[k]; } return [r.x, r.y]; }; };
let t = Math.max(0.25, T0);
const tr = rect(tin);
const tTitle = 0.75;
tl.fromTo(tin, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: tTitle, ease: "none" }, t);
segs.push({ t0: t, t1: t + tTitle, f: wiggle([tr.x, tr.y + tr.h * 0.6], [tr.x + tr.w, tr.y + tr.h * 0.6]) });
t += tTitle + 0.25;
const end = Math.max(t + 1.5, S.dur - 0.7);
const per = (end - t) / Math.max(1, n);
els.forEach((e) => {
  if (e.link) { const r = rect(e.link); const lp = e.link.querySelectorAll("path");
    if (lp.length) { tl.fromTo(lp, { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.3, stagger: 0.12, ease: "none" }, t - 0.05); segs.push({ t0: t - 0.05, t1: t + 0.35, f: pathSeg(e.link.querySelector("svg"), Array.from(lp)) }); }
    else { tl.from(e.link, { scale: 0, opacity: 0, duration: 0.3, ease: "back.out(2)" }, t - 0.05); segs.push({ t0: t - 0.05, t1: t + 0.25, f: wiggle([r.x, r.y + r.h / 2], [r.x + r.w, r.y + r.h / 2]) }); }
    t += 0.4; return; }
  const paths = Array.from(e.svg.querySelectorAll("path"));
  const L = paths.map((p) => p.getTotalLength()); const tot = L.reduce((a, b) => a + b, 0) || 1;
  const dDraw = Math.max(0.6, Math.min(1.5, per - 0.75));
  let acc = 0;
  paths.forEach((p, k) => { tl.fromTo(p, { drawSVG: "0%" }, { drawSVG: "100%", duration: dDraw * L[k] / tot, ease: "none" }, t + dDraw * acc / tot); acc += L[k]; });
  segs.push({ t0: t, t1: t + dDraw, f: pathSeg(e.svg, paths) });
  t += dDraw + 0.1;
  if (e.lb.textContent) { const lr = rect(e.lb);
    tl.fromTo(e.lb, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: 0.4, ease: "none" }, t);
    segs.push({ t0: t, t1: t + 0.4, f: wiggle([lr.x, lr.y + lr.h * 0.7], [lr.x + lr.w, lr.y + lr.h * 0.7]) }); t += 0.5; }
});
const hand = $(".hand")[0];
const off0 = [S.w * 1.05, S.h * 0.95], off1 = [S.w * 1.1, S.h * 1.05];
const lerp = (a, b, u) => [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];
const sm = (u) => u * u * (3 - 2 * u);
function pos(tt) {
  if (!segs.length) return off0;
  if (tt < segs[0].t0) return lerp(off0, segs[0].f(0), sm(Math.min(1, tt / Math.max(0.01, segs[0].t0))));
  for (let k = 0; k < segs.length; k++) {
    const s = segs[k];
    if (tt <= s.t1) return tt >= s.t0 ? s.f((tt - s.t0) / Math.max(0.01, s.t1 - s.t0)) : lerp(segs[k - 1].f(1), s.f(0), sm((tt - segs[k - 1].t1) / Math.max(0.01, s.t0 - segs[k - 1].t1)));
  }
  const last = segs[segs.length - 1];
  return lerp(last.f(1), off1, sm(Math.min(1, (tt - last.t1) / 0.6)));
}
const tipK = (U * 30) / 200;
const o = { t: 0 };
tl.to(o, { t: S.dur, duration: S.dur, ease: "none", onUpdate() { const p = pos(o.t); hand.style.transform = `translate(${p[0] - 10 * tipK}px,${p[1] - 10 * tipK}px)`; } }, 0);
tl.from(".board", { opacity: 0, scale: 0.96, duration: 0.4, ease: "power2.out" }, 0);
