// MotionKit: mesin timeline kecil bergaya GSAP untuk animasi adegan "Motion AI" di Clip Agent.
// Ditulis sendiri (bukan GSAP). Mendukung subset API yang paling sering ditulis AI: tl.to / from / fromTo / set,
// posisi ("<", ">", "+=0.3", "-=0.2", angka), stagger, ease ("power3.out", "back.out(1.7)", "elastic.out", ...),
// repeat/yoyo, transform (x, y, xPercent, yPercent, scale, rotation, skew), opacity/autoAlpha, warna, ukuran,
// atribut SVG (attr), drawSVG, textContent angka, objek biasa + onUpdate.
// Semuanya deterministik: seek(t) menghitung keadaan dari awal setiap kali, cocok untuk render per frame.

const TRANSFORM = new Set(["x", "y", "xPercent", "yPercent", "scale", "scaleX", "scaleY", "rotation", "rotate", "rotationZ",
  "skewX", "skewY"]);
const SPECIAL = new Set(["duration", "delay", "ease", "stagger", "repeat", "yoyo", "repeatDelay", "onUpdate", "onStart",
  "onComplete", "immediateRender", "overwrite", "snap", "roundProps", "transformOrigin", "id", "paused", "runBackwards",
  "keyframes", "inherit", "lazy", "callbackScope", "data", "force3D", "clearProps", "svgOrigin", "smoothOrigin"]);
const UNITLESS = new Set(["opacity", "zIndex", "fontWeight", "lineHeight", "flexGrow", "flexShrink", "order", "scale",
  "scaleX", "scaleY", "zoom", "fillOpacity", "strokeOpacity", "stopOpacity"]);

// ------------------------------------------------------------------ easing
const pow = (p) => ({ in: (t) => t ** p, out: (t) => 1 - (1 - t) ** p, inOut: (t) => (t < 0.5 ? (2 * t) ** p / 2 : 1 - (2 * (1 - t)) ** p / 2) });
const mk = (inF) => ({ in: inF, out: (t) => 1 - inF(1 - t), inOut: (t) => (t < 0.5 ? inF(2 * t) / 2 : 1 - inF(2 * (1 - t)) / 2) });
const bounceOut = (t) => {
  const n = 7.5625, d = 2.75;
  if (t < 1 / d) return n * t * t;
  if (t < 2 / d) return n * (t -= 1.5 / d) * t + 0.75;
  if (t < 2.5 / d) return n * (t -= 2.25 / d) * t + 0.9375;
  return n * (t -= 2.625 / d) * t + 0.984375;
};
const EASES = {
  none: { in: (t) => t, out: (t) => t, inOut: (t) => t }, linear: { in: (t) => t, out: (t) => t, inOut: (t) => t },
  power0: { in: (t) => t, out: (t) => t, inOut: (t) => t }, power1: pow(2), power2: pow(3), power3: pow(4), power4: pow(5),
  quad: pow(2), cubic: pow(3), quart: pow(4), quint: pow(5), strong: pow(5),
  sine: mk((t) => 1 - Math.cos((t * Math.PI) / 2)), expo: mk((t) => (t === 0 ? 0 : 2 ** (10 * t - 10))),
  circ: mk((t) => 1 - Math.sqrt(1 - t * t)),
  bounce: { in: (t) => 1 - bounceOut(1 - t), out: bounceOut, inOut: (t) => (t < 0.5 ? (1 - bounceOut(1 - 2 * t)) / 2 : (1 + bounceOut(2 * t - 1)) / 2) },
};
export function parseEase(e) {
  if (typeof e === "function") return e;
  if (!e) return EASES.power1.out;
  const s = String(e).trim();
  const m = s.match(/^([a-zA-Z0-9]+)(?:\.(in|out|inOut|easeIn|easeOut|easeInOut))?(?:\(([^)]*)\))?$/);
  if (!m) return EASES.power1.out;
  let [, name, dir, args] = m;
  name = name.toLowerCase();
  dir = (dir || (name === "none" || name === "linear" ? "in" : "out")).replace("easeInOut", "inOut").replace("easeIn", "in").replace("easeOut", "out");
  const nums = (args || "").split(",").map((x) => parseFloat(x)).filter((x) => !isNaN(x));
  if (name === "steps") { const n = Math.max(1, nums[0] || 1); return (t) => Math.min(1, Math.floor(t * n) / n); }
  if (name === "back") {
    const c = nums[0] ?? 1.70158;
    const bin = (t) => t * t * ((c + 1) * t - c);
    return dir === "in" ? bin : dir === "inOut" ? (t) => (t < 0.5 ? bin(2 * t) / 2 : 1 - bin(2 * (1 - t)) / 2) : (t) => 1 - bin(1 - t);
  }
  if (name === "elastic") {
    const a = Math.max(1, nums[0] ?? 1), p = nums[1] ?? 0.3;
    const s2 = (p / (2 * Math.PI)) * Math.asin(1 / a);
    const out = (t) => (t === 0 || t === 1 ? t : a * 2 ** (-10 * t) * Math.sin(((t - s2) * 2 * Math.PI) / p) + 1);
    return dir === "in" ? (t) => 1 - out(1 - t) : dir === "inOut" ? (t) => (t < 0.5 ? (1 - out(1 - 2 * t)) / 2 : (1 + out(2 * t - 1)) / 2) : out;
  }
  const fam = EASES[name] || EASES.power1;
  return fam[dir] || fam.out;
}

// ------------------------------------------------------------------ nilai
const NUM = /[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g;
const NAMED = { transparent: [0, 0, 0, 0], white: [255, 255, 255, 1], black: [0, 0, 0, 1], red: [255, 0, 0, 1],
  green: [0, 128, 0, 1], blue: [0, 0, 255, 1], yellow: [255, 255, 0, 1], orange: [255, 165, 0, 1], gray: [128, 128, 128, 1],
  grey: [128, 128, 128, 1], purple: [128, 0, 128, 1], pink: [255, 192, 203, 1], cyan: [0, 255, 255, 1], magenta: [255, 0, 255, 1] };
function hslToRgb(h, s, l) {
  h = ((h % 360) + 360) % 360 / 360; s /= 100; l /= 100;
  if (!s) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => { t = (t + 1) % 1; return 255 * (t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p); };
  return [f(h + 1 / 3), f(h), f(h - 1 / 3)];
}
export function parseColor(v) {
  if (v == null) return null;
  const s = String(v).trim().toLowerCase();
  if (NAMED[s]) return NAMED[s].slice();
  let m = s.match(/^#([0-9a-f]{3,8})$/);
  if (m) {
    let h = m[1];
    if (h.length === 3 || h.length === 4) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h.slice(0, 6), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, h.length === 8 ? parseInt(h.slice(6), 16) / 255 : 1];
  }
  m = s.match(/^rgba?\(([^)]+)\)$/);
  if (m) { const p = m[1].split(/[\s,/]+/).filter(Boolean).map(parseFloat); return [p[0], p[1], p[2], p[3] ?? 1]; }
  m = s.match(/^hsla?\(([^)]+)\)$/);
  if (m) { const p = m[1].split(/[\s,/]+/).filter(Boolean).map(parseFloat); return [...hslToRgb(p[0], p[1], p[2]), p[3] ?? 1]; }
  return null;
}
const isColorProp = (k) => /color|fill|stroke$|^stroke$|background(?!Size|Position)/i.test(k) && !/width|opacity|dash/i.test(k);

// nilai -> {kind, ...}
function toVal(raw, prop, unitHint) {
  if (raw && typeof raw === "object" && raw.kind) return raw;
  if (typeof raw === "number") return { kind: "num", n: raw, unit: unitHint ?? "" };
  if (raw == null) return { kind: "num", n: 0, unit: unitHint ?? "" };
  const s = String(raw).trim();
  if (isColorProp(prop)) { const c = parseColor(s); if (c) return { kind: "color", c }; }
  const m = s.match(/^([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)([a-z%]*)$/i);
  if (m) return { kind: "num", n: parseFloat(m[1]), unit: m[2] || (unitHint ?? "") };
  const c = parseColor(s);
  if (c) return { kind: "color", c };
  const nums = s.match(NUM);
  if (nums) return { kind: "tpl", tpl: s.split(NUM), nums: nums.map(Number) };
  return { kind: "raw", s };
}
function lerpVal(a, b, p) {
  if (a.kind === "num" && b.kind === "num") return { kind: "num", n: a.n + (b.n - a.n) * p, unit: b.unit || a.unit };
  if (a.kind === "color" && b.kind === "color") return { kind: "color", c: a.c.map((v, i) => v + (b.c[i] - v) * p) };
  if (a.kind === "tpl" && b.kind === "tpl" && a.nums.length === b.nums.length)
    return { kind: "tpl", tpl: b.tpl, nums: a.nums.map((v, i) => v + (b.nums[i] - v) * p) };
  return p >= 1 ? b : a;
}
function valStr(v, prop) {
  if (v.kind === "num") {
    const unit = v.unit || (UNITLESS.has(prop) || prop.startsWith("--") ? "" : "px");
    return `${+v.n.toFixed(4)}${unit}`;
  }
  if (v.kind === "color") { const [r, g, b, a] = v.c; return `rgba(${Math.round(r)},${Math.round(g)},${Math.round(b)},${+(a ?? 1).toFixed(3)})`; }
  if (v.kind === "tpl") return v.tpl.reduce((acc, part, i) => acc + part + (i < v.nums.length ? +v.nums[i].toFixed(4) : ""), "");
  return v.s;
}
function relative(base, raw, prop) {
  if (typeof raw === "string") {
    const m = raw.match(/^([-+*/])=\s*([-+]?(?:\d*\.\d+|\d+\.?))([a-z%]*)$/i);
    if (m && base.kind === "num") {
      const d = parseFloat(m[2]);
      const n = m[1] === "+" ? base.n + d : m[1] === "-" ? base.n - d : m[1] === "*" ? base.n * d : base.n / d;
      return { kind: "num", n, unit: m[3] || base.unit };
    }
  }
  return toVal(raw, prop, base.kind === "num" ? base.unit : undefined);
}

// ------------------------------------------------------------------ target
function resolveTargets(t, root) {
  if (t == null) return [];
  if (typeof t === "string") {
    try { return Array.from((root || document).querySelectorAll(t)); } catch (e) { throw new Error(`Selector tidak valid: ${t}`); }
  }
  if (Array.isArray(t)) return t.flatMap((x) => resolveTargets(x, root));
  if (typeof NodeList !== "undefined" && (t instanceof NodeList || t instanceof HTMLCollection)) return Array.from(t);
  return [t];
}
const isEl = (o) => typeof Element !== "undefined" && o instanceof Element;

function readBase(el, prop) {
  if (!isEl(el)) return toVal(el[prop] ?? 0, prop);
  if (TRANSFORM.has(prop)) return { kind: "num", n: prop.startsWith("scale") ? 1 : 0, unit: prop.endsWith("Percent") ? "" : prop.startsWith("rot") || prop.startsWith("skew") ? "deg" : "px" };
  if (prop === "autoAlpha") prop = "opacity";
  if (prop === "textContent" || prop === "innerText") return toVal(parseFloat(String(el.textContent).replace(/[^\d.-]/g, "")) || 0, prop);
  const cs = getComputedStyle(el);
  const css = prop.startsWith("--") ? cs.getPropertyValue(prop) : cs[prop];
  if (css === undefined || css === "") return toVal(el.style[prop] || 0, prop);
  return toVal(css, prop);
}

// ------------------------------------------------------------------ tween & timeline
let TWEEN_ID = 0;
class Track { // satu (target, properti): daftar segmen terurut
  constructor(target, prop) { this.target = target; this.prop = prop; this.segs = []; }
}

export class Timeline {
  constructor(root, opts = {}) {
    this.root = root; this.items = []; this.end = 0; this.last = { start: 0, end: 0 }; this.labels = {};
    this.defaults = opts.defaults || {}; this.built = false; this.callbacks = [];
  }
  _pos(position) {
    if (position == null || position === "") return this.end;
    if (typeof position === "number") return position;
    const s = String(position).trim();
    let m;
    if ((m = s.match(/^([<>])([-+]=)?\s*([-+]?\d*\.?\d+)?$/))) {
      const base = m[1] === "<" ? this.last.start : this.last.end;
      const n = m[3] ? parseFloat(m[3]) : 0;
      return base + (m[2] === "-=" ? -n : n);
    }
    if ((m = s.match(/^([-+])=\s*(\d*\.?\d+)$/))) return this.end + (m[1] === "-" ? -1 : 1) * parseFloat(m[2]);
    if ((m = s.match(/^([A-Za-z_][\w-]*)\s*(?:([-+])=\s*(\d*\.?\d+))?$/))) {
      const base = this.labels[m[1]] ?? this.end;
      return base + (m[2] ? (m[2] === "-" ? -1 : 1) * parseFloat(m[3]) : 0);
    }
    const f = parseFloat(s);
    return isNaN(f) ? this.end : f;
  }
  addLabel(name, position) { this.labels[name] = this._pos(position); return this; }
  add(what, position) {
    if (typeof what === "string") return this.addLabel(what, position);
    if (typeof what === "function") return this.call(what, null, position);
    if (what instanceof Timeline) { const at = this._pos(position); for (const it of what.items) this.items.push({ ...it, start: it.start + at }); this.end = Math.max(this.end, at + what.end); }
    return this;
  }
  call(fn, args, position) { this.callbacks.push({ fn, args: args || [], at: this._pos(position) }); return this; }
  to(targets, vars, position) { return this._add("to", targets, null, vars, position); }
  from(targets, vars, position) { return this._add("from", targets, vars, null, position); }
  fromTo(targets, fromVars, toVars, position) { return this._add("fromTo", targets, fromVars, toVars, position); }
  set(targets, vars, position) { return this._add("set", targets, null, { ...vars, duration: 0 }, position); }
  duration() { return this.end; }
  totalDuration() { return this.end; }
  timeScale() { return this; } play() { return this; } pause() { return this; } restart() { return this; } progress() { return 0; }
  kill() { return this; } eventCallback() { return this; } then() { return Promise.resolve(this); }
  _add(type, targets, fromVars, toVars, position) {
    const main = { ...this.defaults, ...(toVars || fromVars || {}) };
    if (type === "fromTo") Object.assign(main, toVars || {});
    const els = resolveTargets(targets, this.root);
    const dur = type === "set" ? 0 : Math.max(0, Number(main.duration ?? 0.5));
    const start = this._pos(position) + Math.max(0, Number(main.delay || 0));
    const ease = parseEase(main.ease);
    const repeat = main.repeat === -1 ? Infinity : Math.max(0, Math.floor(Number(main.repeat || 0)));
    const repeatDelay = Number(main.repeatDelay || 0), yoyo = !!main.yoyo;
    const st = main.stagger;
    const offs = staggerOffsets(els.length, st);
    let maxEnd = start;
    const id = ++TWEEN_ID;
    els.forEach((el, i) => {
      const s0 = start + offs[i];
      const it = { id, type, el, start: s0, dur, ease, repeat, repeatDelay, yoyo, from: fromVars ? { ...fromVars } : null,
        to: type === "from" ? null : { ...(toVars || {}) }, snap: main.snap, onUpdate: main.onUpdate, idx: i, els };
      if (type === "from") it.from = { ...(fromVars || {}) };
      if (main.transformOrigin && isEl(el)) el.style.transformOrigin = main.transformOrigin;
      this.items.push(it);
      const span = repeat === Infinity ? dur : dur * (repeat + 1) + repeatDelay * repeat;
      maxEnd = Math.max(maxEnd, s0 + span);
    });
    if (!els.length) maxEnd = start + dur;
    this.last = { start, end: maxEnd };
    this.end = Math.max(this.end, maxEnd);
    this.built = false;
    return this;
  }
  _build() {
    // urutkan per (target, properti) dan hitung nilai awal/akhir secara kronologis
    const tracks = new Map();
    const key = (el, p) => { let m = tracks.get(el); if (!m) { m = new Map(); tracks.set(el, m); } let t = m.get(p); if (!t) { t = new Track(el, p); m.set(p, t); } return t; };
    const order = this.items.map((it, n) => ({ it, n })).sort((a, b) => a.it.start - b.it.start || a.n - b.n);
    for (const { it } of order) {
      const props = new Set([...Object.keys(it.from || {}), ...Object.keys(it.to || {})].filter((k) => !SPECIAL.has(k)));
      for (const p of props) {
        if (p === "attr" || p === "css") {
          const src = { ...((it.from || {})[p] || {}) }, dst = { ...((it.to || {})[p] || {}) };
          for (const a of new Set([...Object.keys(src), ...Object.keys(dst)])) key(it.el, `${p}:${a}`).segs.push({ it, f: src[a], t: dst[a] });
          continue;
        }
        key(it.el, p).segs.push({ it, f: (it.from || {})[p], t: (it.to || {})[p] });
      }
    }
    this.tracks = [];
    for (const m of tracks.values()) for (const tr of m.values()) {
      const base = this._base(tr.target, tr.prop);
      tr.base = base;
      let cur = base;
      for (const sg of tr.segs) {
        const ty = sg.it.type;
        if (ty === "to" || ty === "set") { sg.v0 = cur; sg.v1 = this._parse(tr, sg.t, cur); }
        else if (ty === "from") { sg.v0 = this._parse(tr, sg.f, cur); sg.v1 = cur; }
        else { sg.v0 = sg.f !== undefined ? this._parse(tr, sg.f, cur) : cur; sg.v1 = sg.t !== undefined ? this._parse(tr, sg.t, sg.v0) : cur; }
        cur = sg.v1;
      }
      this.tracks.push(tr);
    }
    this.built = true;
  }
  _base(target, prop) {
    if (prop.startsWith("attr:")) { const a = prop.slice(5); return toVal(isEl(target) ? target.getAttribute(a) ?? 0 : 0, a); }
    if (prop.startsWith("css:")) return readBase(target, prop.slice(4));
    if (prop === "drawSVG") return { kind: "draw", a: 0, b: 100 };
    return readBase(target, prop);
  }
  _parse(tr, raw, cur) {
    if (tr.prop === "drawSVG") return parseDraw(raw);
    if (tr.prop === "autoAlpha") return relative(cur, raw, "opacity");
    const p = tr.prop.includes(":") ? tr.prop.split(":")[1] : tr.prop;
    if (TRANSFORM.has(p) && typeof raw === "number") return { kind: "num", n: raw, unit: cur.unit };
    return relative(cur, raw, p);
  }
  seek(t) {
    if (!this.built) this._build();
    const transforms = new Map();
    for (const tr of this.tracks) {
      let val = tr.base, active = null, prog = 0;
      // segmen terakhir yang sudah dimulai pada waktu t menentukan nilainya
      for (const sg of tr.segs) {
        const it = sg.it;
        if (it.start <= t + 1e-9) { active = sg; }
      }
      if (!active) {
        const first = tr.segs[0];
        if (first && (first.it.type === "from" || first.it.type === "fromTo")) val = first.v0; // immediateRender
      } else {
        prog = localProgress(active.it, t);
        val = active.v0.kind === "draw" ? lerpDraw(active.v0, active.v1, prog) : lerpVal(active.v0, active.v1, prog);
      }
      if (active && active.it.snap && typeof active.it.snap === "object" && active.it.snap[tr.prop] != null && val.kind === "num") {
        const q = Number(active.it.snap[tr.prop]) || 1; val = { ...val, n: Math.round(val.n / q) * q };
      }
      this._apply(tr, val, transforms);
    }
    for (const [el, st] of transforms) el.style.transform = transformStr(st);
    // onUpdate dipanggil untuk tween yang sedang/sudah berjalan, urut waktu (deterministik)
    const seen = new Set();
    for (const it of this.items) {
      if (!it.onUpdate || seen.has(`${it.id}:${it.idx}`) || it.start > t + 1e-9) continue;
      seen.add(`${it.id}:${it.idx}`);
      const p = localProgress(it, t);
      const self = { progress: () => p, targets: () => it.els, time: () => p * it.dur, duration: () => it.dur, ratio: p, vars: it.to || it.from };
      try { it.onUpdate.call(self, self); } catch (e) { reportError(e, this.sceneId); }
    }
    for (const cb of this.callbacks) if (cb.at <= t + 1e-9) { try { cb.fn(...cb.args); } catch (e) { reportError(e, this.sceneId); } }
    return this;
  }
  _apply(tr, v, transforms) {
    const el = tr.target, p = tr.prop;
    if (!isEl(el)) { el[p] = v.kind === "num" ? v.n : valStr(v, p); return; }
    if (p.startsWith("attr:")) { el.setAttribute(p.slice(5), v.kind === "num" ? +v.n.toFixed(4) + (v.unit || "") : valStr(v, p)); return; }
    if (p === "drawSVG") { applyDraw(el, v); return; }
    if (TRANSFORM.has(p)) {
      let st = transforms.get(el); if (!st) { st = {}; transforms.set(el, st); }
      st[p === "rotate" || p === "rotationZ" ? "rotation" : p] = v.kind === "num" ? v : toVal(valStr(v, p), p);
      return;
    }
    if (p === "textContent" || p === "innerText") {
      const n = v.kind === "num" ? v.n : parseFloat(valStr(v, p));
      el.textContent = Number.isInteger(n) ? String(n) : String(+n.toFixed(2));
      return;
    }
    const prop = p.startsWith("css:") ? p.slice(4) : p;
    if (prop === "autoAlpha") { el.style.opacity = valStr(v, "opacity"); el.style.visibility = v.kind === "num" && v.n <= 0.001 ? "hidden" : "inherit"; return; }
    const str = valStr(v, prop);
    if (prop.startsWith("--")) el.style.setProperty(prop, str);
    else el.style[prop] = str;
  }
}

function transformStr(st) {
  const n = (k, d) => (st[k] ? st[k].n : d);
  const u = (k, def) => (st[k] && st[k].unit) || def;
  const parts = [];
  if (st.xPercent || st.yPercent) parts.push(`translate(${n("xPercent", 0)}%, ${n("yPercent", 0)}%)`);
  if (st.x || st.y) parts.push(`translate(${n("x", 0)}${u("x", "px")}, ${n("y", 0)}${u("y", "px")})`);
  if (st.rotation) parts.push(`rotate(${n("rotation", 0)}${u("rotation", "deg")})`);
  if (st.skewX || st.skewY) parts.push(`skew(${n("skewX", 0)}deg, ${n("skewY", 0)}deg)`);
  const s = n("scale", 1);
  if (st.scale || st.scaleX || st.scaleY) parts.push(`scale(${s * n("scaleX", 1)}, ${s * n("scaleY", 1)})`);
  return parts.join(" ") || "none";
}

function localProgress(it, t) {
  const local = t - it.start;
  if (it.dur <= 0) return local >= 0 ? 1 : 0;
  if (local <= 0) return it.ease(0);
  const cycle = it.dur + it.repeatDelay;
  let n = Math.floor(local / cycle);
  if (n > it.repeat) return it.ease(it.yoyo && it.repeat % 2 === 1 ? 0 : 1);
  let within = local - n * cycle;
  if (n === it.repeat && within >= it.dur) within = it.dur;
  let p = Math.min(1, within / it.dur);
  if (it.yoyo && n % 2 === 1) p = 1 - p;
  return it.ease(p);
}

function staggerOffsets(count, st) {
  if (!st || count <= 1) return new Array(count).fill(0);
  const o = typeof st === "object" ? st : { each: Number(st) };
  let each = Number(o.each ?? 0);
  if (o.amount != null) each = count > 1 ? Number(o.amount) / (count - 1) : 0;
  const from = o.from ?? "start";
  const idx = [...Array(count).keys()];
  const center = (count - 1) / 2;
  const dist = idx.map((i) => (from === "center" ? Math.abs(i - center) : from === "end" ? count - 1 - i
    : from === "edges" ? center - Math.abs(i - center) : typeof from === "number" ? Math.abs(i - from)
      : from === "random" ? rand(`st${count}`, i) * (count - 1) : i));
  const ease = o.ease ? parseEase(o.ease) : null;
  const max = Math.max(...dist, 1);
  return dist.map((d) => (ease ? ease(d / max) * max : d) * each);
}

// drawSVG: "0%" | "0% 100%" | "100%" | true
function parseDraw(raw) {
  if (raw === true || raw == null) return { kind: "draw", a: 0, b: 100 };
  const parts = String(raw).trim().split(/\s+/).map((x) => parseFloat(x));
  if (parts.length === 1) return { kind: "draw", a: 0, b: isNaN(parts[0]) ? 100 : parts[0] };
  return { kind: "draw", a: parts[0] || 0, b: isNaN(parts[1]) ? 100 : parts[1] };
}
const lerpDraw = (a, b, p) => ({ kind: "draw", a: a.a + (b.a - a.a) * p, b: a.b + (b.b - a.b) * p });
function applyDraw(el, v) {
  let len = 0;
  try { len = el.getTotalLength ? el.getTotalLength() : 0; } catch (e) { len = 0; }
  if (!len) len = 1000;
  const a = (Math.min(v.a, v.b) / 100) * len, b = (Math.max(v.a, v.b) / 100) * len;
  el.style.strokeDasharray = `0 ${a} ${Math.max(0.0001, b - a)} ${len}`;
  el.style.strokeDashoffset = "0";
}

// ------------------------------------------------------------------ bantuan untuk kode adegan
export function rand(seed, i = 0) {
  let h = 2166136261;
  const s = `${seed}:${i}`;
  for (let k = 0; k < s.length; k++) { h ^= s.charCodeAt(k); h = Math.imul(h, 16777619); }
  h ^= h >>> 13; h = Math.imul(h, 0x5bd1e995); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}
function split(root, selector, mode) {
  // Pecah teks menjadi span per kata/huruf tanpa membuang elemen di dalamnya (mis. <span class="accent">).
  const out = [];
  const cls = mode === "chars" ? "ch" : "w";
  for (const el of resolveTargets(selector, root)) {
    if (el.dataset && el.dataset.mkSplit === mode) { out.push(...el.querySelectorAll("." + cls)); continue; }
    const walker = document.createTreeWalker(el, 4 /* NodeFilter.SHOW_TEXT */);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const frag = document.createDocumentFragment();
      const text = node.textContent || "";
      const tokens = mode === "chars" ? Array.from(text) : text.split(/(\s+)/);
      for (const tok of tokens) {
        if (!tok) continue;
        if (/^\s+$/.test(tok)) { frag.appendChild(document.createTextNode(tok)); continue; }
        const sp = document.createElement("span");
        sp.className = cls;
        sp.style.display = "inline-block";
        sp.textContent = tok;
        frag.appendChild(sp);
        out.push(sp);
      }
      node.parentNode.replaceChild(frag, node);
    }
    if (el.dataset) el.dataset.mkSplit = mode;
  }
  return out;
}

// Pemeriksaan tata letak (dipakai saat menguji adegan): teks yang saling menimpa atau terpotong tepi kanvas.
export function checkLayout(root, W, H) {
  const base = root.getBoundingClientRect();
  const sx = base.width ? W / base.width : 1, sy = base.height ? H / base.height : 1;
  const alpha = (el) => {
    let a = 1;
    for (let e = el; e && e !== root.parentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.visibility === "hidden" || cs.display === "none") return 0;
      a *= parseFloat(cs.opacity || "1");
    }
    return a;
  };
  const texts = [];
  for (const el of root.querySelectorAll("*")) {
    if (el.closest("svg") && el.tagName.toLowerCase() !== "text") continue;
    const own = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own || alpha(el) < 0.35) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    texts.push({ el, txt: el.textContent.trim().replace(/\s+/g, " ").slice(0, 40),
      x0: (r.left - base.left) * sx, y0: (r.top - base.top) * sy, x1: (r.right - base.left) * sx, y1: (r.bottom - base.top) * sy });
  }
  const issues = [];
  for (const t of texts) {
    const m = 4;
    if (t.x0 < -m || t.y0 < -m || t.x1 > W + m || t.y1 > H + m) issues.push(`text "${t.txt}" is cut off by the canvas edge`);
  }
  for (let i = 0; i < texts.length && issues.length < 6; i++) {
    for (let j = i + 1; j < texts.length; j++) {
      const a = texts[i], b = texts[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      if (a.el.parentElement === b.el.parentElement && a.el.classList.contains("w") && b.el.classList.contains("w")) continue;
      if (a.el.parentElement === b.el.parentElement && a.el.classList.contains("ch") && b.el.classList.contains("ch")) continue;
      const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0), h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
      if (w <= 0 || h <= 0) continue;
      const small = Math.min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0));
      if ((w * h) / small > 0.18) issues.push(`text "${a.txt}" overlaps text "${b.txt}"`);
    }
  }
  return Array.from(new Set(issues)).slice(0, 6);
}

const ERRORS = [];
export function reportError(e, scene) {
  const msg = String(e && (e.message || e)).slice(0, 400);
  if (ERRORS.some((x) => x.scene === scene && x.msg === msg)) return;   // galat per frame cukup dilaporkan sekali
  ERRORS.push({ scene, msg });
  try { console.error("MOTION_ERROR " + JSON.stringify({ scene, msg })); } catch (_) { /* abaikan */ }
}

// Bangun satu adegan: isi HTML, jalankan kode adegan, kembalikan timeline-nya.
export function buildScene(root, motion, S) {
  root.innerHTML = motion.html || "";
  const tl = new Timeline(root);
  tl.sceneId = S.id;
  const $ = (sel) => resolveTargets(sel, root);
  const helpers = {
    ...S,
    rand: (i = 0) => rand(`${S.id}`, i),
    splitWords: (sel) => split(root, sel, "words"),
    splitChars: (sel) => split(root, sel, "chars"),
    at: (word, fallback = 0) => {
      const w = String(word).toLowerCase();
      const hit = (S.words || []).find((x) => x.t.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "").startsWith(w.replace(/[^\p{L}\p{N}]/gu, "")));
      return hit ? hit.s : fallback;
    },
  };
  const gsapShim = { timeline: (o) => tl, to: (a, b, c) => tl.to(a, b, c ?? 0), from: (a, b, c) => tl.from(a, b, c ?? 0),
    fromTo: (a, b, c, d) => tl.fromTo(a, b, c, d ?? 0), set: (a, b) => tl.set(a, b, 0), utils: { toArray: (x) => $(x), random: (a, b, i = 0) => a + (b - a) * rand(`${S.id}r`, i) },
    registerPlugin: () => {}, defaults: () => {} };
  try {
    // eslint-disable-next-line no-new-func
    const fn = new Function("tl", "$", "S", "gsap", "root", `"use strict";\n${motion.js || ""}`);
    fn(tl, $, helpers, gsapShim, root);
  } catch (e) {
    reportError(e, S.id);
    throw e;
  }
  return tl;
}

export function sceneErrors() { return ERRORS.slice(); }

export function reportLayout(scene, issues, t) {
  if (!issues.length) return;
  try { console.error("MOTION_LAYOUT " + JSON.stringify({ scene, t, issues })); } catch (_) { /* abaikan */ }
}
