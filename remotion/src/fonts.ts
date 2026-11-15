import { continueRender, delayRender, staticFile } from "remotion";

// Font dibundel di public/fonts (lisensi SIL OFL). Nama keluarga = nama yang dipakai di gaya.
export const FONT_FILES: Record<string, string> = {
  "Anton": "Anton-Regular.ttf",
  "Bangers": "Bangers-Regular.ttf",
  "Bebas Neue": "BebasNeue-Regular.ttf",
  "Montserrat Black": "Montserrat-Black.ttf",
  "Patrick Hand": "PatrickHand-Regular.ttf",
  "Poppins": "Poppins-Bold.ttf",
};

let loading: Promise<void> | null = null;

export const ensureFonts = () => {
  if (loading || typeof document === "undefined") return;
  const handle = delayRender("Memuat font");
  loading = Promise.all(
    Object.entries(FONT_FILES).map(async ([family, file]) => {
      const face = new FontFace(family, `url(${staticFile(`fonts/${file}`)})`);
      await face.load();
      document.fonts.add(face);
    }),
  )
    .then(() => continueRender(handle))
    .catch((err) => {
      console.error("Font gagal dimuat", err);
      continueRender(handle);
    });
};
