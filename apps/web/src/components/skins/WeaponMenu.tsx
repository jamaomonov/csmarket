"use client";

import { Dropdown, type DropdownEntry } from "@csmarket/ui";
import { skinQueryString } from "@csmarket/utils/skins";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import type { SkinCategory, SkinQuery } from "@csmarket/utils/skins";

import { AppLink } from "@/components/header/AccountMenu";
import { HOME } from "@/lib/paths";
import { fetchSkinFacets } from "@/lib/skins";

interface Model {
  value: string;
  count: number;
}

interface WeaponMenuProps {
  category: SkinCategory;
  label: string;
  query: SkinQuery;
  /** The models already known (the active category's facets): no request on open. */
  initial?: Model[];
}

/** The ▾ beside a weapon category chip: «Все …» and the category's models with counts. */
export function WeaponMenu({ category, label, query, initial }: WeaponMenuProps) {
  const t = useTranslations("web.skins");
  const [models, setModels] = useState<Model[] | null>(initial ?? null);
  const [failed, setFailed] = useState(false);
  const inflight = useRef<AbortController | null>(null);

  const load = (open: boolean) => {
    if (!open || models !== null || inflight.current) return;
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setFailed(false);
    fetchSkinFacets(category, ctrl.signal)
      .then((f) => {
        setModels(f.weapons);
      })
      .catch(() => {
        setFailed(true);
      })
      .finally(() => {
        inflight.current = null;
      });
  };

  const href = (weapon: string | undefined) => HOME + skinQueryString(query, { category, weapon });
  const items: DropdownEntry[] = [
    { key: "__all", label: t(`allOf.${category}`), href: href(undefined), tone: "accent" },
    ...(models ?? []).map((m) => ({
      key: m.value,
      label: m.value,
      meta: m.count,
      href: href(m.value),
      current: query.category === category && query.weapon === m.value,
    })),
  ];

  return (
    <Dropdown
      triggerLabel={t("models", { category: label })}
      triggerClassName="h-full rounded-l-none bg-transparent px-2 text-inherit"
      label={<ChevronDown className="size-3.5" aria-hidden />}
      LinkComponent={AppLink}
      items={items}
      loading={models === null && !failed}
      status={failed ? t("modelsFailed") : undefined}
      onOpenChange={load}
      menuClassName="max-h-[360px] overflow-y-auto"
    />
  );
}
