const shot = $(".shot")[0];
if (R.shot) shot.src = R.shot; else shot.remove();
put(".tag", R.tag || "TERKINI");
put(".site", (R.page && R.page.site) || "");
put(".tkl", (S.lang === "en") ? "NEWS" : "BERITA");
const tk = (R.ticker || []).filter(Boolean);
const run = $(".tkr")[0];
run.textContent = (tk.length ? tk : [D.headline || D.fact || D.narration]).concat(tk.length ? tk : []).join("   •   ") + "   •   ";
const main = $(".main")[0];
const kind = D.kind || "fact";
if (kind === "headline") {
  main.appendChild(make("div", "kick", S.lang === "en" ? "Top story" : "Berita utama"));
  const hl = make("div", "hl"); const hin = make("div", "in", D.headline || D.heading || D.narration); hl.appendChild(hin); main.appendChild(hl);
  fit(hl, U * 9.4, U * 5.6);
  const w = S.splitWords(hin);
  tl.from(".kick", { x: -U * 20, opacity: 0, duration: 0.45, ease: "power3.out" }, 0.15)
    .from(hl, { clipPath: "inset(0 100% 0 0)", duration: 0.55, ease: "power3.inOut" }, 0.3)
    .from(w, { y: U * 4, opacity: 0, stagger: 0.05, duration: 0.35, ease: "power2.out" }, 0.6);
} else {
  main.appendChild(make("div", "kick", kind === "outro" ? (S.lang === "en" ? "What next" : "Selanjutnya") : (S.lang === "en" ? "Key fact" : "Fakta kunci")));
  const box = make("div", "fact");
  box.appendChild(make("div", "bul"));
  if (D.number) box.appendChild(make("div", "num", D.number));
  const ft = make("div", "ft"); const fin = make("div", "in", D.fact || D.narration); ft.appendChild(fin); box.appendChild(ft);
  main.appendChild(box);
  fit(ft, U * (D.number ? 7 : 8.4), U * 5);
  tl.from(".kick", { x: -U * 20, opacity: 0, duration: 0.45, ease: "power3.out" }, 0.1)
    .from(box, { x: U * 60, opacity: 0, duration: 0.55, ease: "expo.out" }, Math.max(0.25, T0))
    .from(".bul", { scaleY: 0, transformOrigin: "50% 0%", duration: 0.4 }, Math.max(0.25, T0) + 0.3)
    .from(fin, { opacity: 0, y: U * 2, duration: 0.4 }, Math.max(0.25, T0) + 0.35);
  if (D.number) {
    const num = $(".num")[0]; const m = String(D.number).match(/^(\D*)([\d.,]+)(.*)$/);
    if (m) { const target = parseFloat(m[2].replace(/\./g, "").replace(",", ".")) || 0; const o = { v: 0 };
      const dec = /,\d/.test(m[2]) ? 1 : 0;
      tl.to(o, { v: target, duration: 1.1, ease: "power2.out", onUpdate() { num.textContent = m[1] + o.v.toLocaleString("id-ID", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + m[3]; } }, Math.max(0.25, T0) + 0.3); }
    tl.from(num, { scale: 0.4, duration: 0.5, ease: "back.out(2)" }, Math.max(0.25, T0) + 0.3);
  }
}
tl.from(".tag", { scaleX: 0, transformOrigin: "0% 50%", duration: 0.35, ease: "power3.out" }, 0)
  .from(".live", { opacity: 0, duration: 0.3 }, 0.2)
  .to(".live i", { opacity: 0.2, duration: 0.5, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.4)
  .from(".ticker", { y: U * 12, opacity: 0, duration: 0.45, ease: "power3.out" }, 0.2)
  .fromTo(run, { x: U * 8 * ((D.i || 0) % 3) }, { x: -U * 12 * S.dur, duration: S.dur, ease: "none" }, 0)
  .fromTo(".bg", { scale: 1.02 }, { scale: 1.12, duration: S.dur, ease: "none" }, 0);
