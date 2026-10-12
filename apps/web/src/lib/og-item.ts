/**
 * The item page's share card (`/<locale>/item/<slug>/og.png`, 1200×630): what it says and
 * how big. Pure — the route fetches, `components/og/ItemOgCard` draws. No price on the card:
 * a preview lives for days in a chat, a price there would go stale.
 */

import { isVanilla, wearColor } from "@csmarket/utils/skins";

import type { Exterior, SkinItem } from "@csmarket/utils/skins";

import { rarityColor } from "@/components/landing/format";
import { SITE } from "@/lib/site";

export const OG_WIDTH = 1200;
export const OG_HEIGHT = 630;

/** The width the title may take: the left column, clear of the picture. */
export const TITLE_MAX_WIDTH = 600;

/** Title sizes tried in turn, largest first. */
const TITLE_SIZES = [96, 84, 72, 62, 54, 46, 40] as const;

/** A single line is preferred down to this size; below it two lines at a larger one win. */
const ONE_LINE_MIN = 62;

/** The title's letter spacing (em), negative: set tight like the site's headings. */
export const TITLE_TRACKING = -0.02;

/**
 * IBM Plex Sans Bold advance widths (em) of upper-case Latin, read from the font. Anything
 * else (Cyrillic, symbols) counts as 0.72 em — wider than most, so an estimate errs wide.
 */
const ADVANCE: Record<string, number> = {
  A: 0.685,
  B: 0.667,
  C: 0.651,
  D: 0.697,
  E: 0.607,
  F: 0.585,
  G: 0.719,
  H: 0.724,
  I: 0.432,
  J: 0.559,
  K: 0.696,
  L: 0.53,
  M: 0.819,
  N: 0.724,
  O: 0.714,
  P: 0.656,
  Q: 0.714,
  R: 0.674,
  S: 0.624,
  T: 0.584,
  U: 0.694,
  V: 0.65,
  W: 0.973,
  X: 0.673,
  Y: 0.649,
  Z: 0.607,
  " ": 0.236,
  "|": 0.402,
  "(": 0.338,
  ")": 0.338,
  "-": 0.403,
  ".": 0.31,
  ",": 0.31,
  "'": 0.25,
  "&": 0.72,
  "™": 0.614,
  "…": 0.9,
};
const DIGIT = 0.6;
const OTHER = 0.72;

/** Name prefixes of weaponless items that say what the thing is («Sticker | …»). */
const TYPE_PREFIX = /^((?:StatTrak™ )?Music Kit|Sealed Graffiti|Graffiti|Sticker|Patch|Charm) \| /;

/** Where the generated card lives: under the locale, ending in `.png` (no locale redirect). */
export function itemOgUrl(locale: string, slug: string): string {
  return `${SITE}/${locale}/item/${encodeURIComponent(slug)}/og.png`;
}

/** A well-formed rarity colour, or the landing tiles' fallback (Mil-Spec blue). */
export function ogRarityColor(color: string | null): string {
  return rarityColor(color !== null && /^#[0-9a-f]{6}$/i.test(color) ? color : null);
}

/** The title cut into lines at a size that fits. */
export interface TitleFit {
  lines: string[];
  fontSize: number;
}

/** Estimated width of `text` at `size` px, tracking included. */
export function textWidth(text: string, size: number): number {
  let em = 0;
  for (const c of text)
    em += (ADVANCE[c] ?? (c >= "0" && c <= "9" ? DIGIT : OTHER)) + TITLE_TRACKING;
  return em * size;
}

/** Greedy word wrap at `size`; a word longer than a line stays whole on its own line. */
export function wrapWords(text: string, size: number, maxWidth: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (line && textWidth(next, size) > maxWidth) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}

const fits = (lines: string[], size: number, maxWidth: number, maxLines: number): boolean =>
  lines.length <= maxLines && lines.every((l) => textWidth(l, size) <= maxWidth);

/** Cut the last line so it fits, ending in «…». */
function ellipsize(line: string, size: number, maxWidth: number): string {
  let cut = line;
  while (cut.length > 1 && textWidth(`${cut}…`, size) > maxWidth) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}…`;
}

/**
 * How the (upper-cased) title is set: on one line at the largest size down to 62 px, else on
 * two lines at the largest size that fits; at the smallest size three lines, and past that
 * the third line ends in «…».
 */
export function fitTitle(text: string, maxWidth = TITLE_MAX_WIDTH): TitleFit {
  const upper = text.trim().toUpperCase();
  for (const size of TITLE_SIZES) {
    if (size >= ONE_LINE_MIN && textWidth(upper, size) <= maxWidth) {
      return { lines: [upper], fontSize: size };
    }
  }
  for (const size of TITLE_SIZES) {
    const lines = wrapWords(upper, size, maxWidth);
    if (fits(lines, size, maxWidth, 2)) return { lines, fontSize: size };
  }
  const size = TITLE_SIZES[TITLE_SIZES.length - 1] ?? 40;
  const lines = wrapWords(upper, size, maxWidth)
    .slice(0, 4)
    .map((l) => (textWidth(l, size) > maxWidth ? ellipsize(l, size, maxWidth) : l));
  if (lines.length <= 3) return { lines, fontSize: size };
  const third = lines[2] ?? "";
  return {
    lines: [lines[0] ?? "", lines[1] ?? "", ellipsize(`${third} `, size, maxWidth)],
    fontSize: size,
  };
}

/** One marker under the title: StatTrak™, Souvenir, a Doppler phase, the wear. */
export interface OgTag {
  label: string;
  color: string;
  /** A coloured dot before the label (the wear's market colour). */
  dot?: string;
}

/** What the card says. */
export interface ItemOgModel {
  /** The small line above the title: the weapon, the item type or the category. */
  kicker: string;
  /** A ★ before the kicker: knives and gloves. */
  star: boolean;
  title: TitleFit;
  tags: OgTag[];
  rarity: { name: string; color: string } | null;
  /** The glow behind the picture. */
  glow: string;
  /** How much to zoom the picture: Steam draws stickers and the like small in a padded square. */
  pictureScale: number;
}

/** The localised words the card needs (`web.skins`). */
export interface ItemOgLabels {
  vanilla: string;
  /** The localised category, or `null` for one without a translation. */
  category: string | null;
  exterior: (exterior: Exterior) => string;
}

/** Categories whose Steam picture sits small in transparent padding. */
const PADDED = new Set(["stickers", "patches", "graffiti", "charms"]);
const PADDED_SCALE = 1.5;

const STATTRAK = "#e07a3f";
const SOUVENIR = "#facc15";
const MUTED = "#aab2c5";

/** Kicker and title: «AWP» over «Dragon Lore», «Sticker» over «Natus Vincere (Holo) | …». */
function headline(item: SkinItem, labels: ItemOgLabels): { kicker: string; title: string } {
  if (item.weapon) {
    const kicker = item.weapon.replace(/^★\s*/, "");
    if (isVanilla(item)) return { kicker, title: labels.vanilla };
    return { kicker, title: item.skin ?? item.name };
  }
  const name = item.name.replace(/^★\s*/, "");
  const prefix = TYPE_PREFIX.exec(name);
  if (prefix?.[1]) {
    return { kicker: prefix[1].replace(/^StatTrak™ /, ""), title: name.slice(prefix[0].length) };
  }
  return { kicker: labels.category ?? "CS2", title: name };
}

/** Everything the card shows for an item. */
export function itemOgModel(item: SkinItem, labels: ItemOgLabels): ItemOgModel {
  const { kicker, title } = headline(item, labels);
  const tags: OgTag[] = [];
  if (item.stattrak) tags.push({ label: "StatTrak™", color: STATTRAK });
  if (item.souvenir) tags.push({ label: "Souvenir", color: SOUVENIR });
  if (item.phase) tags.push({ label: item.phase, color: MUTED });
  if (item.exterior) {
    const dot = wearColor(item.exterior);
    tags.push({
      label: labels.exterior(item.exterior),
      color: MUTED,
      ...(dot ? { dot } : {}),
    });
  }
  const color = ogRarityColor(item.rarity_color);
  return {
    kicker,
    star: item.name.startsWith("★") || (item.weapon?.startsWith("★") ?? false),
    title: fitTitle(title),
    tags,
    rarity: item.rarity ? { name: item.rarity, color } : null,
    glow: color,
    pictureScale: PADDED.has(item.category) ? PADDED_SCALE : 1,
  };
}
