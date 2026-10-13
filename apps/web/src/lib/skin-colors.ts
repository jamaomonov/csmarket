/**
 * The colour swatches (spec 2026-10-14-skin-colors): each group drawn as the owner's picture
 * draws it — two tones where the group spans shades (blue to sky, maroon to red, gold to
 * yellow), one where it does not.
 */
import { SKIN_COLORS, type SkinColor } from "@csmarket/utils/skins";

const TONES: Record<SkinColor, readonly [string, string]> = {
  red: ["#7a1810", "#ea3e2b"],
  orange: ["#ee6e26", "#f2943c"],
  yellow: ["#f6c64a", "#fff35a"],
  green: ["#3d8a2a", "#b9d24c"],
  blue: ["#2457f5", "#5ccdf5"],
  purple: ["#7a1785", "#7a1785"],
  pink: ["#e24fd4", "#e24fd4"],
  brown: ["#5b3f2a", "#a8774f"],
  beige: ["#c9b293", "#c9b293"],
  black: ["#0b0b0b", "#0b0b0b"],
  white: ["#ffffff", "#ffffff"],
  grey: ["#999999", "#d2d2d2"],
};

/** The swatch's CSS background: a diagonal split for a two-tone group. */
export function swatchBackground(color: SkinColor): string {
  const [a, b] = TONES[color];
  return a === b ? a : `linear-gradient(135deg, ${a} 50%, ${b} 50%)`;
}

export function isSkinColor(value: string): value is SkinColor {
  return (SKIN_COLORS as readonly string[]).includes(value);
}
