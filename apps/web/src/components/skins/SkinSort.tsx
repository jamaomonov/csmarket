"use client";

import { skinQueryString } from "@csmarket/utils/skins";
import { useTranslations } from "next-intl";

import type { SkinQuery, SkinSort as Sort } from "@csmarket/utils/skins";

import { useRouter } from "@/i18n/navigation";
import { HOME } from "@/lib/paths";

const SORTS: Sort[] = ["-price", "price", "popular", "discount"];

/** The one control that needs JS to feel right: a select that navigates on change. */
export function SkinSort({ query }: { query: SkinQuery }) {
  const t = useTranslations("web.skins");
  const router = useRouter();
  return (
    <label className="shrink-0">
      <span className="sr-only">{t("sortLabel")}</span>
      <select
        value={query.sort}
        onChange={(e) => {
          const sort = e.target.value as Sort; // one of SORTS, rendered below
          router.push(HOME + skinQueryString(query, { sort }));
        }}
        className="border-border bg-surface h-full rounded-xl border px-3 py-2.5 text-[13px] font-semibold"
      >
        {SORTS.map((s) => (
          <option key={s} value={s}>
            {t(`sort.${s}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
