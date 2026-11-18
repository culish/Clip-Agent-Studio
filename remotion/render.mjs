// Dipanggil oleh Clip Agent (Python): node render.mjs <job.json>
// job.json: { mode: "video" | "stills", composition?, props, output, stills: [{frame, output, props?}], concurrency }
// Setiap still boleh membawa props sendiri (dipakai untuk galeri contoh gaya).
// Mencetak baris "PROGRESS <0..1>" dan "STAGE <teks>" ke stdout agar bisa dibaca aplikasi.
import { bundle } from "@remotion/bundler";
import { openBrowser, renderMedia, renderStill, selectComposition } from "@remotion/renderer";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const say = (k, v) => process.stdout.write(`${k} ${v}\n`);

// Bundle di-cache berdasarkan isi kode sumber, agar render berikutnya tidak perlu bundling ulang.
const hashFiles = () => {
  const h = crypto.createHash("sha1");
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir).sort()) {
      const p = path.join(dir, name);
      if (fs.statSync(p).isDirectory()) walk(p);
      else h.update(name).update(fs.readFileSync(p));
    }
  };
  walk(path.join(here, "src"));
  walk(path.join(here, "public"));
  h.update(fs.readFileSync(path.join(here, "package.json")));
  return h.digest("hex").slice(0, 12);
};

const cacheDir = path.join(here, ".bundle", hashFiles());
let serveUrl = cacheDir;
if (!fs.existsSync(path.join(cacheDir, "index.html"))) {
  say("STAGE", "Menyiapkan Remotion (sekali saja)");
  fs.rmSync(path.join(here, ".bundle"), { recursive: true, force: true });
  serveUrl = await bundle({
    entryPoint: path.join(here, "src", "index.ts"),
    outDir: cacheDir,
    publicDir: path.join(here, "public"),
    onProgress: (p) => say("BUNDLE", (p / 100).toFixed(3)),
  });
}

const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE || job.browserExecutable || null;
const chromeMode = browserExecutable && !/headless[_-]?shell/i.test(browserExecutable) ? "chrome-for-testing" : "headless-shell";
// Satu browser dipakai bersama untuk semua langkah (lebih cepat daripada membuka browser per frame).
const puppeteerInstance = await openBrowser("chrome", { browserExecutable, chromeMode, logLevel: "error" });
const common = { serveUrl, inputProps: job.props, browserExecutable, chromeMode, logLevel: "error", puppeteerInstance };

say("STAGE", "Membuka komposisi");
const compId = job.composition || "CartoonStory";
const composition = await selectComposition({ ...common, id: compId });

if (job.mode === "stills") {
  let i = 0;
  for (const s of job.stills) {
    const own = s.props ? { ...common, inputProps: s.props } : common;
    const comp = s.props ? await selectComposition({ ...own, id: compId }) : composition;
    await renderStill({ ...own, composition: comp, frame: Math.max(0, Math.min(s.frame, comp.durationInFrames - 1)),
      output: s.output, imageFormat: "jpeg", jpegQuality: 85, scale: job.scale ?? 0.5 });
    i += 1;
    say("PROGRESS", (i / job.stills.length).toFixed(3));
  }
} else {
  say("STAGE", "Merender video");
  await renderMedia({
    ...common,
    composition,
    codec: "h264",
    crf: job.crf ?? 20,
    outputLocation: job.output,
    concurrency: job.concurrency ?? null,
    onProgress: ({ progress }) => say("PROGRESS", progress.toFixed(3)),
  });
}
await puppeteerInstance.close({ silent: true });
say("DONE", "1");
