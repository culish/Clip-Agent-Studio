const P = [["#FF3B30","#FFFFFF","#111111","#FFE14D"],["#111111","#FFFFFF","#FFE14D","#111111"],["#2D5BFF","#FFFFFF","#FFE14D","#111111"],
           ["#FFE14D","#111111","#FF3B30","#FFFFFF"],["#00A85A","#FFFFFF","#111111","#FFE14D"]];
const c = P[(D.i || 0) % P.length];
root.style.background = c[0]; root.style.color = c[1];
root.style.setProperty("--hl", c[2]); root.style.setProperty("--hlink", c[3]);
$(".bg")[0].style.background = "radial-gradient(circle at 25% 18%, rgba(255,255,255,.22), transparent 52%), radial-gradient(circle at 85% 92%, rgba(0,0,0,.22), transparent 50%)";
const box = $(".txt")[0];
const ws = wordsInto(box, D.narration, D.key);
const n = ws.length;
fit(box, U * (n <= 3 ? 24 : n <= 6 ? 18 : n <= 9 ? 14.5 : 12), U * 7);
const times = wordTimes(D.narration);
ws.forEach((w, i) => tl.from(w, { opacity: 0, scale: 1.7, y: U * 3, duration: 0.24, ease: "back.out(2.4)" }, Math.max(0.04, times[i] - 0.07)));
ws.forEach((w, i) => { if (w.classList.contains("key")) tl.to(w, { scale: 1.1, rotation: -3, duration: 0.22, yoyo: true, repeat: 1, ease: "sine.inOut" }, times[i] + 0.3); });
tl.fromTo(".bg", { scale: 1, rotation: 0 }, { scale: 1.14, rotation: 4, duration: S.dur, ease: "none" }, 0)
  .fromTo(".bar", { scaleX: 0 }, { scaleX: 1, duration: S.dur, ease: "none" }, 0)
  .to(box, { scale: 1.03, duration: S.dur, ease: "none" }, 0);
