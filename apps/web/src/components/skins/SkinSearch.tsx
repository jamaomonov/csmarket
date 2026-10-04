"use client";

import { inputClass } from "@csmarket/ui";
import { skinQueryString, steamImageSize, wearColor } from "@csmarket/utils/skins";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { SkinItem, SkinQuery } from "@csmarket/utils/skins";

import { Link, useRouter } from "@/i18n/navigation";
import { HOME, itemPath } from "@/lib/paths";
import { displayPrice, fetchSuggest } from "@/lib/skins";

const DEBOUNCE_MS = 250;

/**
 * Search as you type: up to ten suggestions from `/skins/suggest` (Postgres
 * trigram, no Waxpeer call), Enter searches the grid via `?q=`. Each keystroke
 * aborts the previous request so a slow answer never overwrites a newer one.
 */
export function SkinSearch({
  initial,
  locale,
  query,
}: {
  initial: string;
  locale: string;
  query: SkinQuery;
}) {
  const t = useTranslations("web.skins");
  const router = useRouter();
  const [text, setText] = useState(initial);
  const [items, setItems] = useState<SkinItem[]>([]);
  const [open, setOpen] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = text.trim();
    abort.current?.abort();
    if (q.length < 2) {
      setItems([]);
      return undefined;
    }
    const controller = new AbortController();
    abort.current = controller;
    const timer = setTimeout(() => {
      fetchSuggest(q, controller.signal)
        .then((r) => {
          setItems(r.items);
        })
        .catch(() => {
          setItems([]);
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [text]);

  return (
    <form
      role="search"
      className="relative flex-1"
      onSubmit={(e) => {
        e.preventDefault();
        setOpen(false);
        const q = text.trim();
        router.push(HOME + skinQueryString(query, { q: q || undefined }));
      }}
    >
      <Search className="text-fg-dim pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
      <input
        type="search"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onBlur={() => {
          setTimeout(() => {
            setOpen(false);
          }, 150);
        }}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        className={`${inputClass} pl-9`}
      />
      {open && items.length > 0 && (
        <ul className="bg-surface-2 shadow-menu absolute inset-x-0 top-full z-20 mt-2 max-h-96 overflow-y-auto rounded-xl p-1.5">
          {items.map((i) => (
            <li key={i.slug}>
              <Link
                href={itemPath(i.slug)}
                className="hover:bg-border-strong flex items-center gap-3 rounded-md px-3 py-2"
              >
                {i.image_url ? (
                  // A Steam CDN thumbnail: next/image adds nothing at this size.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={steamImageSize(i.image_url, "128fx96f")}
                    alt=""
                    width={48}
                    height={36}
                    loading="lazy"
                    className="h-9 w-12 shrink-0 object-contain"
                  />
                ) : (
                  <span className="bg-surface h-9 w-12 shrink-0 rounded" aria-hidden />
                )}
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="text-fg-muted block truncate text-[12px]">
                    {i.stattrak && <span className="text-stattrak">StatTrak™ </span>}
                    {i.souvenir && <span className="text-rarity-contraband">Souvenir </span>}
                    {i.weapon}
                    {i.exterior && (
                      <>
                        {" · "}
                        <span
                          className="font-bold"
                          style={{ color: wearColor(i.exterior) ?? undefined }}
                        >
                          {i.exterior}
                        </span>
                      </>
                    )}
                  </span>
                  <span className="block truncate text-[14px] font-semibold">
                    {i.skin ?? i.name}
                    {i.phase && <span className="text-fg-muted"> · {i.phase}</span>}
                  </span>
                </span>
                <span className="shrink-0 whitespace-nowrap text-[13px] font-bold tabular-nums">
                  {displayPrice(locale, i.price_uzs, i.price_usd) ?? t("soldOut")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
