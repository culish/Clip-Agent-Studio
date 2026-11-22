const st = $(".stage")[0];
const kind = D.kind || "item";
const chips = $(".chips b");
const rank = D.rank || 3;
chips.forEach((b) => { const r = +b.dataset.r; if (kind === "item" && r === rank) b.classList.add("on"); else if ((kind === "item" && r > rank) || kind === "outro") b.classList.add("done"); });
tl.from(".grid", { opacity: 0, duration: 0.6 }, 0).to(".grid", { y: U * 8, duration: S.dur, ease: "none" }, 0)
  .from(chips, { scale: 0, duration: 0.35, stagger: 0.08, ease: "back.out(2)" }, 0.05);
if (kind === "item") {
  const rk = make("div", "rank", String(rank)); st.appendChild(rk);
  st.appendChild(make("div", "hash", "#"));
  const card = make("div", "card");
  const ib = make("div", "ib"); ib.innerHTML = icon(D.icon, "ic", 3); card.appendChild(ib);
  const tx = make("div", "tx"); const nm = make("div", "nm", D.name || D.heading); const rs = make("div", "rs", D.reason || "");
  tx.appendChild(nm); tx.appendChild(rs); card.appendChild(tx); st.appendChild(card);
  fit(nm, U * 8.5, U * 5); fit(rs, U * 5.2, U * 3.6);
  const t1 = Math.max(0.15, T0 + 0.5);
  tl.from(rk, { x: -U * 40, opacity: 0, duration: 0.6, ease: "expo.out" }, 0.1)
    .from(".hash", { scale: 0, rotation: -40, duration: 0.4, ease: "back.out(2)" }, 0.35)
    .from(card, { y: U * 30, opacity: 0, duration: 0.6, ease: "back.out(1.4)" }, t1)
    .fromTo(".ib path", { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.7, stagger: 0.12, ease: "power2.out" }, t1 + 0.25)
    .from(nm, { clipPath: "inset(0 100% 0 0)", duration: 0.5, ease: "power3.out" }, t1 + 0.3)
    .from(rs, { opacity: 0, y: U * 2, duration: 0.4 }, t1 + 0.7)
    .to(rk, { y: -U * 2, duration: 1.4, yoyo: true, repeat: -1, ease: "sine.inOut" }, 1)
    .to(".ib", { rotation: 6, duration: 0.8, yoyo: true, repeat: -1, ease: "sine.inOut" }, t1 + 1.2);
  if (rank === 1) tl.to(".chips b.on", { scale: 1.2, duration: 0.4, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.6);
} else {
  const box = make("div", "intro" + (kind === "outro" ? " cta" : ""));
  if (kind === "intro") { const b = make("div", "badge"); b.innerHTML = 'TOP <span>3</span>'; box.appendChild(b); }
  else { const ib = make("div", "ib"); ib.innerHTML = icon("chat", "ic", 3); box.appendChild(ib); }
  const tt = make("div", "ttl"); const tin = make("div", "in", D.title || D.heading || D.narration); tt.appendChild(tin);
  box.appendChild(tt); st.appendChild(box);
  fit(tt, U * 10, U * 6);
  const w = S.splitWords(tin);
  tl.from(box.firstChild, { scale: 0.3, opacity: 0, duration: 0.6, ease: "back.out(1.8)" }, 0.1)
    .from(w, { y: U * 6, opacity: 0, duration: 0.45, stagger: 0.07, ease: "back.out(1.6)" }, Math.max(0.3, T0))
    .to(box.firstChild, { scale: 1.05, duration: 0.8, yoyo: true, repeat: -1, ease: "sine.inOut" }, 1.2);
  if (kind === "outro") tl.fromTo(".ib path", { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.7, stagger: 0.1 }, 0.3);
}
