/**
 * What a share card fetches before it draws: the site's font and the item's picture. Both
 * fail soft — a card without the picture, or in the renderer's built-in font, is still a card.
 */

import { steamImageSize } from "@csmarket/utils/skins";

/** A font as `ImageResponse` takes it. */
export interface OgFont {
  name: string;
  data: ArrayBuffer;
  weight: 500 | 700;
  style: "normal";
}

/**
 * The site's font, IBM Plex Sans (500 and 700), from Google Fonts as TrueType — the renderer
 * reads TTF, not the woff2 `next/font` ships. Asked without a browser User-Agent, the CSS API
 * answers one full TTF per weight (Latin and Cyrillic).
 */
const FONT_CSS = "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@500;700";
const FONT_FACE = /font-weight:\s*(\d+);[^}]*?src:\s*url\((https:\/\/[^)]+\.ttf)\)/g;
const TIMEOUT_MS = 4000;
/** A Steam skin picture is ~50–150 KB; anything far bigger is not one. */
const MAX_IMAGE_BYTES = 2_000_000;

let fonts: Promise<OgFont[]> | null = null;

async function fetchFonts(): Promise<OgFont[]> {
  const css = await fetch(FONT_CSS, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!css.ok) throw new Error(`font css ${String(css.status)}`);
  const faces = [...(await css.text()).matchAll(FONT_FACE)];
  const loaded = await Promise.all(
    faces.map(async ([, weight, url]): Promise<OgFont | null> => {
      if ((weight !== "500" && weight !== "700") || !url) return null;
      const res = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
      if (!res.ok) throw new Error(`font ${String(res.status)}`);
      return {
        name: "IBM Plex Sans",
        data: await res.arrayBuffer(),
        weight: weight === "500" ? 500 : 700,
        style: "normal",
      };
    }),
  );
  const ok = loaded.filter((f): f is OgFont => f !== null);
  if (ok.length === 0) throw new Error("no font faces");
  return ok;
}

/**
 * IBM Plex Sans, fetched once per process. On a failure the answer is `[]` (the renderer's
 * built-in font) and the next card tries again.
 */
export async function ogFonts(): Promise<OgFont[]> {
  fonts ??= fetchFonts();
  try {
    return await fonts;
  } catch {
    fonts = null;
    return [];
  }
}

/** Test hook: forget the cached fonts. */
export function resetOgFonts(): void {
  fonts = null;
}

/**
 * The item's Steam picture (512×384) as a data URI, or `null` when there is none, Steam
 * does not answer in 4 s, or the answer is not an image. Fetched here, not by the renderer:
 * a broken `<img>` URL would fail the whole card.
 */
export async function ogSkinImage(url: string | null): Promise<string | null> {
  if (!url) return null;
  try {
    const res = await fetch(steamImageSize(url, "512fx384f"), {
      signal: AbortSignal.timeout(TIMEOUT_MS),
      // Content-addressed, and the card itself is cached downstream: no data-cache copy.
      cache: "no-store",
    });
    const type = res.headers.get("content-type")?.split(";")[0]?.trim() ?? "";
    if (!res.ok || !/^image\/(png|jpeg|webp|gif)$/.test(type)) return null;
    const body = await res.arrayBuffer();
    if (body.byteLength === 0 || body.byteLength > MAX_IMAGE_BYTES) return null;
    return `data:${type};base64,${Buffer.from(body).toString("base64")}`;
  } catch {
    return null;
  }
}
