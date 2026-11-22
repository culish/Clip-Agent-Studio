const shot = $(".shot")[0];
const page = R.page || {};
put(".st", page.site || (S.lang === "en" ? "Look what I found" : "Lihat yang kutemukan"));
if (R.shot) { shot.src = R.shot; } else {
  shot.remove(); $(".card")[0].style.display = "flex";
  put(".curl", page.site || ""); put(".ctitle", page.title || D.heading || ""); put(".cdesc", page.description || "");
}
put(".ct", D.callout || D.heading || "");
if (!D.callout && !D.heading) $(".callout")[0].style.display = "none";
// bagian halaman yang terlihat di layar = (tinggi/lebar layar) / (tinggi/lebar tangkapan layar)
const sr = $(".screen")[0].getBoundingClientRect();
const vis = Math.min(1, (sr.height / Math.max(1, sr.width)) / (R.shot_ratio || 6.3));
const toY = (p) => -Math.max(0, Math.min(1, p)) * (1 - vis) * 100;
const prev = D.prevScroll === undefined ? 0 : D.prevScroll;
if (R.shot) tl.fromTo(shot, { yPercent: toY(prev) }, { yPercent: toY(D.scroll || 0), duration: 1.4, ease: "power2.inOut" }, Math.max(0.1, T0 - 0.1));
const first = (D.i || 0) === 0;
tl.from(".grp", first ? { y: U * 90, rotation: 8, duration: 0.8, ease: "back.out(1.2)" } : { y: U * 2, duration: 0.4 }, 0)
  .from(".site", { y: -U * 10, opacity: 0, duration: 0.45, ease: "power3.out" }, 0.15)
  .from(".callout", { scale: 0, rotation: -12, duration: 0.5, ease: "back.out(2.2)" }, Math.max(0.4, T0 + 0.5))
  .to(".grp", { rotation: -1.6, y: -U * 1, duration: 1.6, yoyo: true, repeat: -1, ease: "sine.inOut" }, 0.9)
  .to(".callout", { y: -U * 1.2, duration: 1.1, yoyo: true, repeat: -1, ease: "sine.inOut" }, Math.max(0.4, T0 + 1.1));
