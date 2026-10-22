/**
 * «Проверить цену»: price a skin (by name) or a made-up one (cost + category) under the
 * rules as they stand in the form — unsaved changes included. Writes nothing.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { findPricedItems, type PreviewIn, previewPrice, type PricingRules } from "./api";
import { errorText } from "./labels";
import { QuoteView } from "./QuoteView";

import { MoneyField } from "@/components/MoneyInput";
import { Section } from "@/components/Section";
import { useDebounced } from "@/lib/useDebounced";

const DEBOUNCE_MS = 300;

interface PreviewCardProps {
  rules: PricingRules;
}

function bodyOf(
  rules: PricingRules,
  slug: string | null,
  cost: string,
  category: string,
  weapon: string,
): PreviewIn | null {
  if (slug !== null) return { rules, slug };
  if (cost.trim() === "" || category.trim() === "") return null;
  return {
    rules,
    cost_usd: cost.trim(),
    category: category.trim(),
    ...(weapon.trim() !== "" && { weapon: weapon.trim() }),
  };
}

export function PreviewCard({ rules }: PreviewCardProps) {
  const [search, setSearch] = useState("");
  const [slug, setSlug] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [cost, setCost] = useState("");
  const [category, setCategory] = useState("");
  const [weapon, setWeapon] = useState("");
  const q = useDebounced(search.trim(), DEBOUNCE_MS);
  const body = useDebounced(
    JSON.stringify(bodyOf(rules, slug, cost, category, weapon)),
    DEBOUNCE_MS,
  );
  // Our own JSON.stringify of a PreviewIn (or null), parsed back.
  const parsed = JSON.parse(body) as PreviewIn | null;

  const found = useQuery({
    queryKey: ["pricing", "preview-items", q],
    queryFn: () => findPricedItems(q, false),
    enabled: slug === null && q.length >= 2,
  });
  const quote = useQuery({
    queryKey: ["pricing", "preview", body],
    queryFn: () => previewPrice(parsed ?? {}),
    enabled: parsed !== null,
  });

  const input = "border-border bg-bg h-11 rounded-md border px-3";
  return (
    <Section title="Проверить цену">
      <div className="flex flex-col gap-4">
        <p className="text-fg-muted text-sm">Считает по правилам из формы, даже несохранённым.</p>
        {slug === null ? (
          <label className="flex flex-col gap-1 text-sm">
            Найти скин
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              placeholder="Например: asiimov"
              className={input}
            />
          </label>
        ) : (
          <p className="text-sm">
            Скин: <span className="font-medium">{name ?? slug}</span>{" "}
            <button
              type="button"
              className="text-accent underline"
              onClick={() => {
                setSlug(null);
              }}
            >
              выбрать другой
            </button>
          </p>
        )}
        {slug === null && (found.data?.items.length ?? 0) > 0 && (
          <ul className="flex flex-col gap-1">
            {found.data?.items.slice(0, 8).map((item) => (
              <li key={item.slug}>
                <button
                  type="button"
                  className="text-accent min-h-11 text-left text-sm hover:underline sm:min-h-0 sm:py-1"
                  onClick={() => {
                    setSlug(item.slug);
                    setName(item.name);
                  }}
                >
                  {item.name}
                </button>
              </li>
            ))}
          </ul>
        )}
        {slug === null && (
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
            <MoneyField label="Себестоимость" unit="$" decimal value={cost} onChange={setCost} />
            <label className="flex flex-col gap-1 text-sm">
              Категория
              <input
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value);
                }}
                placeholder="rifles"
                className={`${input} w-full`}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Оружие
              <input
                value={weapon}
                onChange={(e) => {
                  setWeapon(e.target.value);
                }}
                placeholder="AK-47"
                className={`${input} w-full`}
              />
            </label>
          </div>
        )}
        {quote.isError && (
          <p role="alert" className="text-danger">
            {errorText(quote.error)}
          </p>
        )}
        {quote.data && <QuoteView quote={quote.data} />}
      </div>
    </Section>
  );
}
