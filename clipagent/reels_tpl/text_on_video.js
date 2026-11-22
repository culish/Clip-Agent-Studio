if (D.hasVideo) $(".orbs")[0].style.display = "none";
const box = $(".txt")[0];
const ws = wordsInto(box, D.narration, D.key);
const n = ws.length;
fit(box, U * (n <= 4 ? 13 : n <= 8 ? 10.5 : 8.6), U * 6);
const times = wordTimes(D.narration);
tl.from(box, { opacity: 0, y: U * 2, duration: 0.6, ease: "power2.out" }, 0.05);
ws.forEach((w, i) => tl.fromTo(w, { opacity: 0.32 }, { opacity: 1, duration: 0.35, ease: "sine.out" }, Math.max(0.2, times[i])));
ws.forEach((w, i) => { if (w.classList.contains("key")) tl.fromTo(w, { scale: 1 }, { scale: 1.06, duration: 0.5, ease: "sine.out" }, times[i]); });
tl.fromTo(".line", { scaleX: 0 }, { scaleX: 1, duration: 0.8, ease: "power2.out" }, 0.4)
  .to(".orbs i:nth-child(1)", { x: U * 10, y: U * 6, duration: S.dur, ease: "sine.inOut" }, 0)
  .to(".orbs i:nth-child(2)", { x: -U * 12, y: -U * 5, duration: S.dur, ease: "sine.inOut" }, 0)
  .to(".orbs i:nth-child(3)", { x: U * 6, y: -U * 8, duration: S.dur, ease: "sine.inOut" }, 0);
