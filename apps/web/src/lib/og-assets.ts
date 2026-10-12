/**
 * What a share card fetches before it draws: the site's font and the item's picture. Both
 * fail soft — a card without the picture, or in the renderer's built-in font, is still a card.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { steamImageSize } from "@csmarket/utils/skins";

/** A font as `ImageResponse` takes it. */
export interface OgFont {
  name: string;
  data: ArrayBuffer;
  weight: 500 | 700;
  style: "normal";
}

/**
 * The site's font, IBM Plex Sans (500 and 700), as TrueType from the repo (`assets/og/`): the
 * renderer reads TTF, not the woff2 `next/font` ships. `next start` runs in `apps/web`, so the
 * files resolve from the working directory (the image copies the whole tree).
 */
const FONT_FILES: readonly [500 | 700, string][] = [
  [500, "IBMPlexSans-Medium.ttf"],
  [700, "IBMPlexSans-Bold.ttf"],
];
const TIMEOUT_MS = 4000;
/** A Steam skin picture is ~50–150 KB; anything far bigger is not one. */
const MAX_IMAGE_BYTES = 2_000_000;

let fonts: Promise<OgFont[]> | null = null;

async function readFonts(): Promise<OgFont[]> {
  return Promise.all(
    FONT_FILES.map(async ([weight, file]): Promise<OgFont> => {
      const buf = await readFile(join(process.cwd(), "assets", "og", file));
      const data = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
      return { name: "IBM Plex Sans", data, weight, style: "normal" };
    }),
  );
}

/**
 * IBM Plex Sans, read once per process. On a failure the answer is `[]` (the renderer's
 * built-in font) and the next card tries again.
 */
export async function ogFonts(): Promise<OgFont[]> {
  fonts ??= readFonts();
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
