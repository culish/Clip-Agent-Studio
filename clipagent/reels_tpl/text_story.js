const cast = R.cast || { A: "Rina", B: "Dimas" };
put(".nm", cast.B || "Dimas");
put(".av", String(cast.B || "D").slice(0, 1).toUpperCase());
put(".on", S.lang === "en" ? "online" : "online");
const list = $(".list")[0];
(D.history || []).forEach((m) => list.appendChild(make("div", "b old " + (m.from === "B" ? "B" : "A"), m.text)));
const who = D.speaker === "B" ? "B" : "A";
const nb = make("div", "b " + who, D.narration); list.appendChild(nb);
const typing = $(".typing")[0]; typing.classList.add(who);
const h = nb.getBoundingClientRect().height / (root.getBoundingClientRect().height / S.h) + U * 1.6;
const tIn = Math.max(0.45, T0 - 0.05);
tl.set(list, { y: h }, 0)
  .from(typing, { scale: 0, opacity: 0, transformOrigin: who === "A" ? "100% 100%" : "0% 100%", duration: 0.25, ease: "back.out(2)" }, 0.05)
  .to(".typing i", { y: -U * 1.2, duration: 0.22, yoyo: true, repeat: -1, stagger: 0.1, ease: "sine.inOut" }, 0.1)
  .to(typing, { opacity: 0, scale: 0.6, duration: 0.15 }, tIn - 0.05)
  .to(list, { y: 0, duration: 0.3, ease: "power2.out" }, tIn)
  .from(nb, { scale: 0.5, opacity: 0, transformOrigin: who === "A" ? "100% 100%" : "0% 100%", duration: 0.35, ease: "back.out(1.8)" }, tIn);
