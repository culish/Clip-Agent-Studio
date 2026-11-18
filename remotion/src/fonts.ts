import { continueRender, delayRender, staticFile } from "remotion";

// Font dibundel di public/fonts (lisensi SIL OFL; Special Elite dan Permanent Marker: Apache 2.0). Nama keluarga = nama yang dipakai di gaya.
export const FONT_FILES: Record<string, string> = {
  "Anton": "Anton-Regular.ttf",
  "Bangers": "Bangers-Regular.ttf",
  "Bebas Neue": "BebasNeue-Regular.ttf",
  "Montserrat Black": "Montserrat-Black.ttf",
  "Patrick Hand": "PatrickHand-Regular.ttf",
  "Poppins": "Poppins-Bold.ttf",
  "Playfair Display Black": "PlayfairDisplay-Black.woff2",
  "Playfair Italic": "PlayfairDisplay-BoldItalic.woff2",
  "Special Elite": "SpecialElite-Regular.woff2",
  "Permanent Marker": "PermanentMarker-Regular.woff2",
  "Fraunces Black": "Fraunces-Black.woff2",
  "Fraunces Italic": "Fraunces-BoldItalic.woff2",
  "Caveat Bold": "Caveat-Bold.woff2",
  "Archivo Black": "ArchivoBlack-Regular.woff2",
  "Plus Jakarta Sans": "PlusJakartaSans-ExtraBold.woff2",
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
