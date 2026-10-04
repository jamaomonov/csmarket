"use client";

import { inputClass } from "@csmarket/ui";
import { DEFAULT_SORT, skinQueryString } from "@csmarket/utils/skins";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { SkinQuery } from "@csmarket/utils/skins";

import { useRouter } from "@/i18n/navigation";
import { HOME } from "@/lib/paths";

/** Long enough to type a number, short enough not to feel like waiting. */
export const PRICE_APPLY_DELAY_MS = 500;

const bound = (v: string) => (v.trim() === "" ? undefined : Math.max(0, Number(v)));
const boundsKey = (min: number | undefined, max: number | undefined) =>
  `${String(min ?? "")}-${String(max ?? "")}`;

/**
 * The price range, applied as the buyer types — half a second after they stop, no
 * «Применить» to press. Still a GET form, so Enter (or a page without JS) submits it.
 *
 * When the URL's bounds change from elsewhere (Reset, back, the other copy of the panel)
 * the boxes take them; when the change is the one this box just pushed they are left
 * alone, so the buyer keeps focus and whatever they typed meanwhile.
 */
export function SkinPriceFilter({ query }: { query: SkinQuery }) {
  const t = useTranslations("web.skins");
  const router = useRouter();
  const [min, setMin] = useState(query.minUzs?.toString() ?? "");
  const [max, setMax] = useState(query.maxUzs?.toString() ?? "");
  const typed = useRef(false);
  const urlBounds = boundsKey(query.minUzs, query.maxUzs);
  const [seen, setSeen] = useState(urlBounds);
  const [pushed, setPushed] = useState<string | null>(null);
  if (seen !== urlBounds) {
    // Adjusting state to a prop change during render (react.dev "you might not need an effect").
    setSeen(urlBounds);
    if (urlBounds !== pushed) {
      setMin(query.minUzs?.toString() ?? "");
      setMax(query.maxUzs?.toString() ?? "");
    }
  }

  useEffect(() => {
    if (!typed.current) return;
    const timer = setTimeout(() => {
      const next = boundsKey(bound(min), bound(max));
      if (next === urlBounds) return;
      setPushed(next);
      router.replace(HOME + skinQueryString(query, { minUzs: bound(min), maxUzs: bound(max) }), {
        scroll: false,
      });
    }, PRICE_APPLY_DELAY_MS);
    return () => {
      clearTimeout(timer);
    };
    // `query` describes the page this box sits on; only typing re-arms it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [min, max]);

  const input = (
    name: "min" | "max",
    value: string,
    set: (v: string) => void,
    placeholder: string,
  ) => (
    <input
      type="number"
      name={name}
      min={0}
      inputMode="numeric"
      placeholder={placeholder}
      value={value}
      onChange={(e) => {
        typed.current = true;
        set(e.target.value);
      }}
      aria-label={placeholder}
      className={inputClass}
    />
  );

  // The form has no `action`: a GET form submits to the page it sits on, locale prefix included.
  return (
    <form method="get">
      {query.category && <input type="hidden" name="category" value={query.category} />}
      {query.weapon && <input type="hidden" name="weapon" value={query.weapon} />}
      {query.exterior && <input type="hidden" name="exterior" value={query.exterior} />}
      {query.rarity && <input type="hidden" name="rarity" value={query.rarity} />}
      {query.team && <input type="hidden" name="team" value={query.team} />}
      {query.stattrak && <input type="hidden" name="stattrak" value="1" />}
      {query.q && <input type="hidden" name="q" value={query.q} />}
      {query.sort !== DEFAULT_SORT && <input type="hidden" name="sort" value={query.sort} />}
      <div className="flex items-center gap-2">
        {input("min", min, setMin, t("from"))}
        <span className="text-fg-dim">—</span>
        {input("max", max, setMax, t("to"))}
      </div>
    </form>
  );
}
