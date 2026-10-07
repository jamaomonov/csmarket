"use client";

import { chipVariants, cn, Dropdown, type DropdownEntry } from "@csmarket/ui";
import { skinQueryString } from "@csmarket/utils/skins";
import { Boxes, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { SkinCategoryIcon } from "./SkinCategoryIcon";

import type { SkinCategory, SkinQuery } from "@csmarket/utils/skins";

import { AppLink } from "@/components/header/AccountMenu";
import { HOME } from "@/lib/paths";

interface OtherCategoriesMenuProps {
  /** The non-weapon categories in stock (agents, cases, keys…), in display order. */
  categories: SkinCategory[];
  query: SkinQuery;
  /** One of `categories` when it is the chosen one: the chip names it and turns green. */
  active?: SkinCategory;
}

/** «Другое»: one chip with a menu of the categories that are not weapons. */
export function OtherCategoriesMenu({ categories, query, active }: OtherCategoriesMenuProps) {
  const t = useTranslations("web.skins");
  const items: DropdownEntry[] = categories.map((c) => ({
    key: c,
    label: (
      <span className="flex items-center gap-2">
        <SkinCategoryIcon category={c} size="sm" />
        {t(`category.${c}`)}
      </span>
    ),
    href: HOME + skinQueryString(query, { category: c, weapon: undefined }),
    current: c === active,
  }));
  return (
    <Dropdown
      label={
        <>
          {active ? (
            <SkinCategoryIcon category={active} size="sm" />
          ) : (
            <Boxes className="size-3.5" aria-hidden />
          )}
          {active ? t(`category.${active}`) : t("other")}
          <ChevronDown className="size-3.5" aria-hidden />
        </>
      }
      triggerClassName={cn(
        chipVariants({ active: active !== undefined }),
        active === undefined && "bg-transparent",
        "lg:w-full lg:justify-center",
      )}
      LinkComponent={AppLink}
      items={items}
      strategy="fixed"
      align="end"
    />
  );
}
