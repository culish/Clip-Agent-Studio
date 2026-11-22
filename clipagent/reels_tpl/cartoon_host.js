const bt = $(".bt .in")[0]; bt.textContent = D.board || D.heading || "";
fit($(".bt")[0], U * 9.5, U * 5.5);
$(".bi")[0].innerHTML = icon(D.icon, "ic", 3.4);
const bb = $(".bb")[0];
if (D.big) { bb.textContent = D.big; fit(bb, U * 13, U * 7); } else bb.innerHTML = icon(D.icon === "star" ? "idea" : "star", "ic", 3.6);
const mood = D.mood || "happy";
const open = $(".mouth.open")[0], shut = $(".mouth.shut")[0];
tl.set(open, { opacity: 0 }, 0);
(S.words || []).forEach((w) => { tl.set(open, { opacity: 1 }, w.s).set(shut, { opacity: 0 }, w.s)
  .set(open, { opacity: 0 }, Math.max(w.s + 0.08, w.e - 0.03)).set(shut, { opacity: 1 }, Math.max(w.s + 0.08, w.e - 0.03)); });
const brow = { happy: [0, 0, 0, 0], surprised: [-9, -9, 0, 0], thinking: [-8, 2, -8, 6], serious: [3, 3, 12, -12], excited: [-6, -6, -6, 6] }[mood] || [0, 0, 0, 0];
tl.set(".b1", { y: brow[0], rotation: brow[2] }, 0).set(".b2", { y: brow[1], rotation: brow[3] }, 0);
[1.1, 3.3, 5.6, 7.9].filter((t) => t < S.dur - 0.2).forEach((t) => tl.to(".eye", { scaleY: 0.12, duration: 0.07, yoyo: true, repeat: 1, ease: "none" }, t));
const first = (D.i || 0) === 0;
tl.from(".host", first ? { x: -U * 60, duration: 0.7, ease: "back.out(1.3)" } : { y: U * 2, duration: 0.3 }, 0)
  .from(".board", { y: -U * 30, opacity: 0, duration: 0.55, ease: "back.out(1.4)" }, 0.05)
  .fromTo(".bi path", { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.8, stagger: 0.12, ease: "power2.out" }, Math.max(0.3, T0))
  .from(bt, { clipPath: "inset(0 100% 0 0)", duration: 0.6, ease: "power2.out" }, Math.max(0.35, T0 + 0.15))
  .from(".badge", { scale: 0, rotation: -30, duration: 0.5, ease: "back.out(2)" }, Math.max(0.6, T0 + 0.7))
  .to(".badge", { y: -U * 2, duration: 1.1, yoyo: true, repeat: -1, ease: "sine.inOut" }, 1.3)
  .to(".armR", { rotation: -8, duration: 0.5, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.4)
  .to(".head", { rotation: 3, duration: 0.6, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.2)
  .to(".body", { y: -2, duration: 0.6, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.2);
if (mood === "surprised" || mood === "excited") tl.from(".head", { y: -10, duration: 0.25, ease: "back.out(3)" }, Math.max(0.2, T0));
