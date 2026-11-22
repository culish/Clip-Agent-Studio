const st = $(".stage")[0];
const kind = D.kind || "proof";
const shake = (el, t) => tl.to(el, { x: U * 1.2, duration: 0.05, yoyo: true, repeat: 5, ease: "none" }, t);
if (kind === "claim") {
  const box = make("div", "claim");
  box.appendChild(make("div", "lab", S.lang === "en" ? "THE CLAIM" : "KLAIMNYA"));
  const ct = make("div", "ctext"); const cin = make("div", "in", D.claim || D.heading || D.narration); ct.appendChild(cin); box.appendChild(ct);
  st.appendChild(box); fit(ct, U * 13, U * 7);
  const stp = make("div", "stamp big low", S.lang === "en" ? "REALLY?" : "BENARKAH?"); st.appendChild(stp);
  const w = S.splitWords(cin);
  const tS = Math.min(S.dur - 0.9, Math.max(1.2, T0 + 1.3));
  tl.from(".lab", { x: -U * 20, opacity: 0, duration: 0.4, ease: "power3.out" }, 0.1)
    .from(w, { y: U * 5, opacity: 0, stagger: 0.07, duration: 0.4, ease: "power3.out" }, Math.max(0.25, T0))
    .set(stp, { xPercent: -50, yPercent: -50, rotation: -12 }, 0)
    .fromTo(stp, { scale: 3.2, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.22, ease: "power4.in" }, tS);
  shake(box, tS + 0.22);
} else if (kind === "verdict") {
  const stp = make("div", "stamp big huge", D.verdict || "FAKTA"); st.appendChild(stp);
  for (let k = 0; k < 7; k++) { const d = make("div", "ink"); const r = U * (1 + S.rand(k) * 3);
    Object.assign(d.style, { width: r + "px", height: r + "px", left: (20 + S.rand(k + 9) * 60) + "%", top: (25 + S.rand(k + 19) * 40) + "%" }); st.appendChild(d); }
  const sub = make("div", "lab", S.lang === "en" ? "VERDICT" : "KESIMPULAN"); sub.style.position = "absolute"; sub.style.left = "0"; sub.style.top = "0"; st.appendChild(sub);
  const tS = Math.max(0.35, T0 + 0.2);
  tl.from(sub, { opacity: 0, x: -U * 10, duration: 0.4 }, 0.1)
    .set(stp, { xPercent: -50, yPercent: -50, rotation: -12 }, 0)
    .fromTo(stp, { scale: 3.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.24, ease: "power4.in" }, tS)
    .from(".ink", { scale: 0, duration: 0.25, stagger: 0.03, ease: "back.out(3)" }, tS + 0.22)
    .to(stp, { scale: 1.04, duration: 0.9, yoyo: true, repeat: -1, ease: "sine.inOut" }, tS + 0.8);
  shake(st, tS + 0.24);
} else {
  const card = make("div", "card");
  card.appendChild(make("div", "qm", "“"));
  const qt = make("div", "qt"); const qin = make("div", "in"); qt.appendChild(qin); card.appendChild(qt);
  const ws = wordsInto(qin, D.quote || D.narration, [D.stamp || ""]);
  const src = make("div", "src"); src.appendChild(make("i")); src.appendChild(make("span", "", D.source || (R.page && R.page.site) || "")); card.appendChild(src);
  st.appendChild(card);
  fit(qt, U * (ws.length > 22 ? 6.4 : ws.length > 14 ? 7.6 : 9), U * 4.8);
  const stp = make("div", "stamp s1", D.stamp || ""); card.appendChild(stp);
  const keys = ws.filter((w) => w.classList.contains("key"));
  const tK = Math.min(S.dur - 1, Math.max(1.4, T0 + 1.6));
  tl.from(card, { y: U * 40, rotation: 6, opacity: 0, duration: 0.6, ease: "back.out(1.3)" }, 0.05)
    .from(".qm", { scale: 0, duration: 0.4, ease: "back.out(2)" }, 0.4)
    .from(ws, { opacity: 0, duration: 0.25, stagger: Math.min(0.06, 1.2 / Math.max(1, ws.length)) }, 0.45)
    .from(".src", { opacity: 0, x: -U * 5, duration: 0.4 }, 0.9)
    .fromTo(keys, { backgroundSize: "0% 100%" }, { backgroundSize: "100% 100%", duration: 0.45, stagger: 0.08, ease: "power2.out" }, tK - 0.5);
  if (D.stamp) { tl.set(stp, { rotation: -11 }, 0).fromTo(stp, { scale: 3, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.2, ease: "power4.in" }, tK); shake(card, tK + 0.2); }
  else stp.remove();
  tl.to(card, { y: -U * 1, duration: 1.5, yoyo: true, repeat: -1, ease: "sine.inOut" }, tK + 0.6);
}
