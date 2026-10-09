"use client";

/**
 * The hero showcase: one skin on a stage glowing in its rarity colour, a strip of thumbnails,
 * rotating every 6 s and pausing while hovered. Without JS (or with reduced motion) the first
 * skin simply stays.
 */
import Image from "next/image";
import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react";

import { cx } from "./format";
import { CartIcon, CheckIcon, SteamGlyph } from "./Icons";

import { Link } from "@/i18n/navigation";

export interface StageItem {
  slug: string;
  href: string;
  /** «Karambit», «AK-47» */
  model: string;
  /** «Fade», «Fire Serpent» (or the full name for a vanilla item) */
  title: string;
  /** «FN», «FT»… */
  wear: string | null;
  rarity: string | null;
  color: string;
  star: boolean;
  price: string | null;
  image: string;
  thumb: string;
  alt: string;
}

interface Props {
  items: StageItem[];
  buy: string;
  showcase: string;
  toastTitle: string;
  toastText: string;
}

const ROTATE_MS = 6000;

export function HeroStage({ items, buy, showcase, toastTitle, toastText }: Props) {
  const [cur, setCur] = useState(0);
  const [out, setOut] = useState(false);
  const [paused, setPaused] = useState(false);
  const swap = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(
    (n: number) => {
      if (n === cur) return;
      setOut(true);
      if (swap.current) clearTimeout(swap.current);
      swap.current = setTimeout(() => {
        setCur(n);
        setOut(false);
      }, 280);
    },
    [cur],
  );

  useEffect(() => {
    if (paused || items.length < 2) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setTimeout(() => {
      show((cur + 1) % items.length);
    }, ROTATE_MS);
    return () => {
      clearTimeout(id);
    };
  }, [cur, paused, items.length, show]);

  useEffect(
    () => () => {
      if (swap.current) clearTimeout(swap.current);
    },
    [],
  );

  const item = items[cur];
  if (item === undefined) return null;
  const glow = { "--hr": item.color } as CSSProperties; // a CSS custom property

  return (
    <div
      className={cx("stage-col", paused && "paused")}
      style={glow}
      onMouseEnter={() => {
        setPaused(true);
      }}
      onMouseLeave={() => {
        setPaused(false);
      }}
    >
      <div className="stage" aria-live="polite">
        <span className="bar-a" aria-hidden />
        <span className="bar-b" aria-hidden />
        <span className="ring" aria-hidden />
        <span className="r2 ring" aria-hidden />
        {item.rarity !== null && (
          <span className="rarity-tag">
            <i />
            {item.rarity}
            {item.star ? " · ★" : ""}
          </span>
        )}
        <Image
          key={item.slug}
          className={cx("stage-img", out && "out")}
          src={item.image}
          alt={item.alt}
          width={512}
          height={384}
          priority={cur === 0}
          unoptimized
        />
        <div className="plate">
          <div className="plate-meta">
            <div className="plate-w">
              {item.wear !== null && <span className="wear">{item.wear}</span>}
              <span>{item.model}</span>
            </div>
            <div className="plate-n">{item.title}</div>
          </div>
          {item.price !== null && <div className="plate-p num">{item.price}</div>}
          <Link
            className="btn btn-primary btn-sm"
            href={item.href}
            aria-label={`${buy}: ${item.alt}`}
          >
            <CartIcon />
            <span className="t-long">{buy}</span>
          </Link>
        </div>
      </div>
      <div className="toast" aria-hidden>
        <span className="toast-ic">
          <SteamGlyph />
        </span>
        <span>
          <b>{toastTitle}</b>
          <span>{toastText}</span>
        </span>
        <span className="ok">
          <CheckIcon />
        </span>
      </div>
      <div className="thumbs" role="group" aria-label={showcase}>
        {items.map((it, i) => (
          <button
            key={it.slug}
            type="button"
            className={cx("thumb", i === cur && "on")}
            style={{ "--r": it.color } as CSSProperties /* a CSS custom property */}
            aria-pressed={i === cur}
            aria-label={it.alt}
            onClick={() => {
              show(i);
            }}
          >
            <Image src={it.thumb} alt="" width={84} height={63} unoptimized />
            <span>{it.price ?? it.model}</span>
            <i />
          </button>
        ))}
      </div>
    </div>
  );
}
