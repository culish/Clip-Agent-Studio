// Pembantu bersama template Reels (dijalankan MotionKit: tl, $, S, root tersedia). Data AI hanya lewat textContent.
const D = S.data || {};
const R = D.reel || {};
const U = Math.min(S.w, S.h) / 100;
const ICON = {
  idea: "M24 6a12 12 0 0 0-7 21.7V32h14v-4.3A12 12 0 0 0 24 6z M18 37h12 M20 42h8",
  money: "M6 14h36v20H6z M30 24a6 6 0 1 1-12 0a6 6 0 1 1 12 0 M12 18v12 M36 18v12",
  clock: "M42 24a18 18 0 1 1-36 0a18 18 0 1 1 36 0 M24 13v11l7 5",
  rocket: "M24 4c7 6 10 14 8 24H16C14 18 17 10 24 4z M16 28l-6 8h8 M32 28l6 8h-8 M20 40l4 6 4-6 M27 16a3 3 0 1 1-6 0a3 3 0 1 1 6 0",
  heart: "M24 41S6 30 6 17a9 9 0 0 1 18-2 9 9 0 0 1 18 2c0 13-18 24-18 24z",
  brain: "M22 8a7 7 0 0 0-11 6 7 7 0 0 0-3 12 7 7 0 0 0 5 11 7 7 0 0 0 9 3V8z M26 8a7 7 0 0 1 11 6 7 7 0 0 1 3 12 7 7 0 0 1-5 11 7 7 0 0 1-9 3V8z",
  phone: "M15 4h18a3 3 0 0 1 3 3v34a3 3 0 0 1-3 3H15a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3z M21 38h6",
  globe: "M42 24a18 18 0 1 1-36 0a18 18 0 1 1 36 0 M6 24h36 M24 6c6 6 6 30 0 36 M24 6c-6 6-6 30 0 36",
  chart_up: "M6 42h36 M10 34l9-10 7 6 14-16 M32 14h8v8",
  chart_down: "M6 42h36 M10 14l9 10 7-6 14 16 M32 34h8v-8",
  home: "M6 22L24 7l18 15 M11 19v22h26V19 M20 41V29h8v12",
  person: "M31 13a7 7 0 1 1-14 0a7 7 0 1 1 14 0 M10 42c0-9 6-15 14-15s14 6 14 15",
  people: "M23 15a6 6 0 1 1-12 0a6 6 0 1 1 12 0 M4 40c0-8 5-13 13-13s13 5 13 13 M38 16a5 5 0 1 1-10 0a5 5 0 1 1 10 0 M32 27c6 0 12 4 12 12",
  check: "M8 25l10 10L40 13",
  cross: "M12 12l24 24 M36 12L12 36",
  star: "M24 5l5.6 12.2 13.4 1.4-10 9 2.9 13.2L24 34l-11.9 6.8 2.9-13.2-10-9 13.4-1.4z",
  book: "M24 12c-5-4-12-4-18-2v28c6-2 13-2 18 2 5-4 12-4 18-2V10c-6-2-13-2-18 2z M24 12v28",
  gear: "M30 24a6 6 0 1 1-12 0a6 6 0 1 1 12 0 M36 24a12 12 0 1 1-24 0a12 12 0 1 1 24 0 M24 4v8 M24 36v8 M4 24h8 M36 24h8 M10 10l5 5 M33 33l5 5 M38 10l-5 5 M15 33l-5 5",
  lock: "M12 22h24v20H12z M17 22v-6a7 7 0 0 1 14 0v6 M24 30v5",
  sun: "M32 24a8 8 0 1 1-16 0a8 8 0 1 1 16 0 M24 4v6 M24 38v6 M4 24h6 M38 24h6 M10 10l4 4 M34 34l4 4 M38 10l-4 4 M14 34l-4 4",
  cloud: "M14 38h22a8 8 0 0 0 1-16 11 11 0 0 0-21-3 9 9 0 0 0-2 19z",
  bolt: "M27 4L10 27h12l-3 17 19-25H26z",
  leaf: "M8 40C8 18 22 8 42 8c0 20-10 34-32 32z M8 40L28 20",
  trophy: "M14 6h20v10a10 10 0 0 1-20 0z M14 10H7c0 7 3 10 8 10 M34 10h7c0 7-3 10-8 10 M24 26v8 M18 34h12v8H18z",
  warning: "M24 6L44 40H4z M24 18v11 M24 34v1",
  question: "M42 24a18 18 0 1 1-36 0a18 18 0 1 1 36 0 M18 18a6 6 0 1 1 9 5c-2 1-3 2-3 4v2 M24 34v1",
  fire: "M24 44c-8 0-14-6-14-13 0-8 7-12 8-20 4 3 6 7 6 11 2-2 3-4 3-7 6 5 11 10 11 16 0 7-6 13-14 13z",
  target: "M42 24a18 18 0 1 1-36 0a18 18 0 1 1 36 0 M34 24a10 10 0 1 1-20 0a10 10 0 1 1 20 0 M26 24a2 2 0 1 1-4 0a2 2 0 1 1 4 0",
  cart: "M4 8h6l5 22h22l5-16H13 M21 38a3 3 0 1 1-6 0a3 3 0 1 1 6 0 M37 38a3 3 0 1 1-6 0a3 3 0 1 1 6 0",
  car: "M6 30l4-11c1-3 3-4 6-4h16c3 0 5 1 6 4l4 11v8H6z M6 30h36 M14 38v4 M34 38v4",
  food: "M6 24h36c0 10-8 17-18 17S6 34 6 24z M16 18c0-4 4-4 4-8 M24 18c0-4 4-4 4-8 M32 18c0-4 4-4 4-8",
  water: "M24 5C17 15 11 22 11 30a13 13 0 0 0 26 0c0-8-6-15-13-25z",
  shield: "M24 4l16 6v12c0 10-7 18-16 22C15 40 8 32 8 22V10z M17 24l5 5 9-10",
  calendar: "M8 10h32v30H8z M8 18h32 M16 6v8 M32 6v8 M15 26h4 M23 26h4 M31 26h2 M15 33h4 M23 33h4",
  chat: "M6 10h36v22H20l-9 8v-8H6z M14 19h20 M14 25h12",
  search: "M30 20a11 11 0 1 1-22 0a11 11 0 1 1 22 0 M27 28l13 13",
  gift: "M6 18h36v8H6z M9 26h30v16H9z M24 18v24 M24 18c-4-8-12-8-12-3s8 3 12 3c4 0 12 2 12-3s-8-5-12 3",
  music: "M18 36V10l22-5v26 M18 36a5 5 0 1 1-10 0a5 5 0 1 1 10 0 M40 31a5 5 0 1 1-10 0a5 5 0 1 1 10 0",
};
function icon(name, cls, sw) {
  const d = ICON[name] || ICON.idea;
  const parts = d.split(" M").map((p, i) => `<path d="${i ? "M" + p : p}"/>`).join("");
  return `<svg class="${cls || "ic"}" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="${sw || 3.2}" stroke-linecap="round" stroke-linejoin="round">${parts}</svg>`;
}
function make(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}
function put(sel, text) { const e = $(sel)[0]; if (e) e.textContent = String(text || ""); return e; }
// Perkecil huruf sampai teks muat di kotaknya (teks dari AI panjangnya tidak pasti).
function fit(el, maxPx, minPx) {
  if (!el) return;
  let f = maxPx;
  el.style.fontSize = f + "px";
  // Tinggi: toleransi sebagian ukuran huruf (lekuk huruf tebal sedikit melewati baris), lebar: ketat.
  for (let k = 0; k < 40 && f > minPx && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + f * 0.3); k++) {
    f = Math.max(minPx, f * 0.93);
    el.style.fontSize = f + "px";
  }
}
// Waktu tiap kata teks (detik dari awal adegan), selaras dengan narasi bila jumlah katanya sama.
function wordTimes(text) {
  const toks = String(text || "").split(/\s+/).filter(Boolean);
  const W = (S.words || []).filter((w) => w && w.t);
  if (W.length && W.length === toks.length) return W.map((w) => w.s);
  const a = W.length ? W[0].s : 0.3, b = W.length ? W[W.length - 1].e : Math.max(a + 0.5, S.dur - 0.9);
  return toks.map((_, i) => a + (b - a) * i / Math.max(1, toks.length));
}
const norm = (t) => String(t || "").toLowerCase().replace(/[^\p{L}\p{N}%]+/gu, "");
function isKey(word, keys) {
  const w = norm(word);
  return !!w && (keys || []).some((k) => String(k).split(/\s+/).some((p) => norm(p) === w));
}
// Tulis kata demi kata ke dalam elemen; kembalikan span kata.
function wordsInto(el, text, keys, keyCls) {
  el.textContent = "";
  const out = [];
  String(text || "").split(/\s+/).filter(Boolean).forEach((w, i) => {
    if (i) el.appendChild(document.createTextNode(" "));
    const sp = make("span", "w" + (isKey(w, keys) ? " " + (keyCls || "key") : ""), w);
    sp.style.display = "inline-block";
    el.appendChild(sp);
    out.push(sp);
  });
  return out;
}
const T0 = S.words && S.words.length ? Math.max(0.05, S.words[0].s - 0.15) : 0.2;
