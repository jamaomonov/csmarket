"use client";

import { Dropdown, type DropdownEntry } from "@csmarket/ui";
import { skinQueryString, weaponParam, weaponsOf } from "@csmarket/utils/skins";
import { ChevronDown } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, useTransition } from "react";

import type { SkinCategory, SkinQuery, SkinQueryPatch, WeaponFacet } from "@csmarket/utils/skins";

import { useRouter } from "@/i18n/navigation";
import { HOME } from "@/lib/paths";
import { fetchSkinFacets } from "@/lib/skins";

interface WeaponMenuProps {
  category: SkinCategory;
  label: string;
  query: SkinQuery;
  /** The models already known (from the page's facets): no request on open. */
  initial?: WeaponFacet[];
}

/** A model's picture on a red glow (the Covert grade's colour), or the glow alone. */
function ModelPicture({ model }: { model: WeaponFacet }) {
  return (
    <span
      data-model-glow
      aria-hidden
      className="flex h-10 w-16 shrink-0 items-center justify-center bg-[radial-gradient(closest-side,rgba(235,75,75,0.55),rgba(235,75,75,0.18)_55%,transparent)]"
    >
      {model.image && (
        <Image
          src={model.image}
          alt=""
          width={64}
          height={48}
          className="h-10 w-16 object-contain drop-shadow"
        />
      )}
    </span>
  );
}

/**
 * The ▾ beside a weapon category chip: «Выбрать все» and the category's models, each with
 * a picture and a box. Ticking keeps the menu open and moves the grid at once; models of
 * several categories can be ticked together (the query then names no category).
 */
export function WeaponMenu({ category, label, query, initial }: WeaponMenuProps) {
  const t = useTranslations("web.skins");
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [models, setModels] = useState<WeaponFacet[] | null>(initial ?? null);
  const [failed, setFailed] = useState(false);
  const [picked, setPicked] = useState<string[]>(() => weaponsOf(query));
  const inflight = useRef<AbortController | null>(null);
  // A request still running when the menu goes away (a navigation) is dropped.
  useEffect(() => () => inflight.current?.abort(), []);
  // The URL is the truth once a navigation lands.
  useEffect(() => {
    setPicked(weaponsOf(query));
  }, [query]);

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
        if (!ctrl.signal.aborted) setFailed(true);
      })
      .finally(() => {
        inflight.current = null;
      });
  };

  const names = (models ?? []).map((m) => m.value);
  const ownsAll = (set: string[]) => names.length > 0 && names.every((n) => set.includes(n));

  /** The query for a ticked set: one category when the set is inside this one. */
  const patchFor = (next: string[]): SkinQueryPatch => {
    if (next.length === 0) return { category: undefined, weapon: undefined };
    if (!next.every((n) => names.includes(n))) {
      return { category: undefined, weapon: weaponParam(next) };
    }
    return { category, weapon: ownsAll(next) ? undefined : weaponParam(next) };
  };

  const go = (next: string[]) => {
    setPicked(next);
    startTransition(() => {
      router.replace(HOME + skinQueryString(query, patchFor(next)), { scroll: false });
    });
  };

  const allTicked = (query.category === category && picked.length === 0) || ownsAll(picked);
  const toggleAll = () => {
    go(
      allTicked
        ? picked.filter((n) => !names.includes(n))
        : [...picked.filter((n) => !names.includes(n)), ...names],
    );
  };
  const toggle = (name: string) => {
    // «All of the category» with nothing ticked: a tick narrows it to that model.
    go(picked.includes(name) ? picked.filter((n) => n !== name) : [...picked, name]);
  };

  const items: DropdownEntry[] = [
    {
      key: "__all",
      label: t("selectAll"),
      checked: allTicked,
      onSelect: toggleAll,
      tone: "accent",
    },
    { key: "__sep", separator: true },
    ...(models ?? []).map((m) => ({
      key: m.value,
      label: m.value,
      icon: <ModelPicture model={m} />,
      checked: picked.includes(m.value),
      onSelect: () => {
        toggle(m.value);
      },
    })),
  ];

  return (
    <Dropdown
      triggerLabel={t("models", { category: label })}
      triggerClassName="h-9 rounded-l-none bg-transparent py-0 pl-1 pr-2.5 text-inherit"
      label={<ChevronDown className="size-3.5" aria-hidden />}
      items={items}
      loading={models === null && !failed}
      status={failed ? t("modelsFailed") : undefined}
      onOpenChange={load}
      strategy="fixed"
      // Under the whole category chip, not just its ▾ (as the markets do).
      anchor="parent"
      maxHeight={420}
      menuClassName="min-w-[260px]"
    />
  );
}
