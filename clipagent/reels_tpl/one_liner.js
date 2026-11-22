const box = $(".txt")[0];
const inner = make("div", "in", D.narration); box.appendChild(inner);
fit(box, U * 11, U * 6.5);
put(".subt", D.sub || "Jawab di komentar");
const ch = S.splitChars(inner);
const typeDur = Math.min(2.2, Math.max(0.9, ch.length * 0.035));
tl.from(".glow", { scale: 0.6, opacity: 0, duration: 1.2, ease: "power2.out", stagger: 0.2 }, 0)
  .from(".q", { y: U * 20, opacity: 0, rotation: 30, duration: 1.2, ease: "power3.out" }, 0.1)
  .from(ch, { opacity: 0, y: U * 1.5, duration: 0.08, stagger: typeDur / Math.max(1, ch.length), ease: "none" }, 0.35)
  .from(".subt", { scale: 0, duration: 0.5, ease: "back.out(2)" }, 0.35 + typeDur + 0.25)
  .from(".arr", { opacity: 0, y: -U * 3, duration: 0.4, ease: "power2.out" }, 0.35 + typeDur + 0.5)
  .to(".arr", { y: U * 2.5, duration: 0.45, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.35 + typeDur + 0.9)
  .to(".q", { rotation: 6, duration: S.dur, ease: "sine.inOut" }, 1.3)
  .to(".g1", { x: U * 12, y: U * 8, duration: S.dur, ease: "sine.inOut" }, 0)
  .to(".subt", { scale: 1.06, duration: 0.6, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.35 + typeDur + 1);
