/**
 * The item page's share card, drawn by `next/og` (Satori): only inline styles and flex
 * boxes. A dark card in the site's colours, the logo, the weapon over the skin name, the
 * markers below, the picture on the right lit by its rarity colour. No price.
 */
import { LOGO_ON_DARK } from "./logo";

import type { ItemOgModel, OgTag } from "@/lib/og-item";

import { OG_HEIGHT, OG_WIDTH, TITLE_MAX_WIDTH, TITLE_TRACKING } from "@/lib/og-item";

const BG = "#0d111b";
const SURFACE = "#1d2434";
const BORDER = "#2c3449";
const MUTED = "#aab2c5";
const GOLD = "#e4ae39";

/** The brand mark's outlines (`@csmarket/ui` `LogoMark`). */
const MARK = [
  "M6.24 7 L31.24 7 L32.18 3.25 L40.43 10.25 L28.69 17.25 L29.62 13.5 L24.5 13.5 L22.19 11.2 L18.75 13.5 L4.62 13.5 Z",
  "M33.76 33 L8.76 33 L7.82 36.75 L-0.43 29.75 L11.31 22.75 L10.38 26.5 L15.5 26.5 L17.81 28.8 L21.25 26.5 L35.38 26.5 Z",
  "M21.62 13.5 L28.1 20 L18.38 26.5 L11.9 20 Z",
];

interface ItemOgCardProps {
  model: ItemOgModel;
  /** The skin's picture as a data URI; `null` draws the faded brand mark instead. */
  image: string | null;
}

function Star() {
  return (
    <svg width="30" height="30" viewBox="0 0 24 24" style={{ marginRight: 12 }}>
      <path
        d="M12 2l2.94 6.26 6.86.8-5.07 4.7 1.35 6.78L12 17.17l-6.08 3.37 1.35-6.78-5.07-4.7 6.86-.8z"
        fill={GOLD}
      />
    </svg>
  );
}

function Tag({ tag }: { tag: OgTag }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        height: 52,
        padding: "0 20px",
        marginRight: 12,
        marginBottom: 12,
        borderRadius: 14,
        background: SURFACE,
        border: `1px solid ${BORDER}`,
        color: tag.color,
        fontSize: 26,
        fontWeight: 500,
      }}
    >
      {tag.dot && (
        <div
          style={{
            width: 12,
            height: 12,
            borderRadius: 6,
            background: tag.dot,
            marginRight: 12,
          }}
        />
      )}
      {tag.label}
    </div>
  );
}

function Picture({ image, scale }: { image: string | null; scale: number }) {
  const box = { position: "absolute", right: 40, top: 110, width: 560, height: 420 } as const;
  if (image) {
    // A zoomed picture grows around the same centre; the card's overflow clips it.
    const w = Math.round(560 * scale);
    const h = Math.round(420 * scale);
    const zoomed = {
      ...box,
      right: 40 - (w - 560) / 2,
      top: 110 - (h - 420) / 2,
      width: w,
      height: h,
    };
    return (
      // eslint-disable-next-line @next/next/no-img-element -- Satori draws plain <img> only
      <img src={image} alt="" width={w} height={h} style={{ ...zoomed, objectFit: "contain" }} />
    );
  }
  return (
    <div style={{ ...box, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <svg width="260" height="260" viewBox="-1.43 -1.43 42.86 42.86" style={{ opacity: 0.18 }}>
        {MARK.map((d) => (
          <path key={d} d={d} fill="#ffffff" />
        ))}
      </svg>
    </div>
  );
}

export function ItemOgCard({ model, image }: ItemOgCardProps) {
  const { kicker, star, title, tags, rarity, glow, pictureScale } = model;
  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        width: OG_WIDTH,
        height: OG_HEIGHT,
        background: BG,
        color: "#ffffff",
        fontFamily: "IBM Plex Sans",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: OG_WIDTH,
          height: OG_HEIGHT,
          backgroundImage: `radial-gradient(circle at 77% 52%, ${glow}66 0%, ${glow}26 26%, ${glow}00 52%), radial-gradient(circle at 4% 0%, rgba(75, 243, 100, 0.13) 0%, rgba(75, 243, 100, 0) 34%)`,
        }}
      />
      <Picture image={image} scale={pictureScale} />
      {/* The SVG carries 20 px of padding: the lockup itself starts at 72 / 64. */}
      {/* eslint-disable-next-line @next/next/no-img-element -- Satori draws plain <img> only */}
      <img
        src={LOGO_ON_DARK.src}
        alt=""
        width={Math.round((LOGO_ON_DARK.width * 64) / LOGO_ON_DARK.height)}
        height={64}
        style={{ position: "absolute", left: 66, top: 44 }}
      />
      <div
        style={{
          position: "absolute",
          left: 72,
          top: 130,
          bottom: 110,
          width: TITLE_MAX_WIDTH + 20,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            fontSize: 34,
            fontWeight: 500,
            color: MUTED,
          }}
        >
          {star && <Star />}
          {kicker}
        </div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 10 }}>
          {title.lines.map((line, i) => (
            <div
              key={`${String(i)}-${line}`}
              style={{
                fontSize: title.fontSize,
                fontWeight: 700,
                lineHeight: 1.04,
                letterSpacing: `${String(TITLE_TRACKING)}em`,
              }}
            >
              {line}
            </div>
          ))}
        </div>
        {tags.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", marginTop: 28 }}>
            {tags.map((tag) => (
              <Tag key={tag.label} tag={tag} />
            ))}
          </div>
        )}
      </div>
      {rarity && (
        <div
          style={{
            position: "absolute",
            left: 72,
            bottom: 60,
            display: "flex",
            alignItems: "center",
            fontSize: 26,
            fontWeight: 500,
            color: rarity.color,
          }}
        >
          <div
            style={{
              width: 36,
              height: 6,
              borderRadius: 3,
              background: rarity.color,
              marginRight: 14,
            }}
          />
          {rarity.name}
        </div>
      )}
    </div>
  );
}
