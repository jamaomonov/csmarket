/**
 * «Цена одного скина»: a margin override (п.п.) or a pinned price for one item, with the
 * price it would sell at. «Сбросить ручную цену» sends both as `null`.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  findPricedItems,
  type ItemPricingIn,
  type PricedItem,
  previewPrice,
  saveItemPricing,
} from "./api";
import { errorText } from "./labels";

import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatSum } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";

const DEBOUNCE_MS = 300;
const blank = (v: string): string | null => (v.trim() === "" ? null : v.trim());

interface EditorProps {
  item: PricedItem;
  onSaved: (item: PricedItem) => void;
}

function Editor({ item, onSaved }: EditorProps) {
  const [pp, setPp] = useState(item.margin_override_pp ?? "");
  const [fixed, setFixed] = useState(item.fixed_price_usd ?? "");
  const idem = useIdempotencyKey("item-pricing");
  const inFlight = useRef(false);
  const body: ItemPricingIn = { margin_override_pp: blank(pp), fixed_price_usd: blank(fixed) };
  const shown = useDebounced(JSON.stringify(body), DEBOUNCE_MS);
  const quote = useQuery({
    queryKey: ["pricing", "item-preview", item.slug, shown],
    queryFn: () => {
      // Our own JSON.stringify of an ItemPricingIn, parsed back.
      const b = JSON.parse(shown) as ItemPricingIn;
      return previewPrice({
        slug: item.slug,
        ...(b.margin_override_pp !== null && { item_pp: b.margin_override_pp }),
        ...(b.fixed_price_usd !== null && { fixed_price_usd: b.fixed_price_usd }),
      });
    },
  });
  const save = useMutation({
    mutationFn: (b: ItemPricingIn) =>
      saveItemPricing(item.slug, b, idem.keyFor(`${item.slug}:${JSON.stringify(b)}`)),
    onSuccess: (saved) => {
      idem.reset();
      onSaved(saved);
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });
  const submit = (b: ItemPricingIn): void => {
    if (inFlight.current) return;
    inFlight.current = true;
    save.mutate(b);
  };
  const input = "border-border bg-bg h-10 w-36 rounded-md border px-3";
  return (
    <div className="border-border flex flex-col gap-3 rounded-md border p-4">
      <div className="font-medium">{item.name}</div>
      <div className="text-fg-muted text-sm">
        Себестоимость: {item.cost_usd ? `$${item.cost_usd}` : "нет предложений"} · сейчас:{" "}
        {item.price_usd ? `$${item.price_usd}` : "—"}
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Наценка, п.п.
          <input
            inputMode="decimal"
            value={pp}
            onChange={(e) => {
              setPp(e.target.value);
            }}
            className={input}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Фиксированная цена, $
          <input
            inputMode="decimal"
            value={fixed}
            onChange={(e) => {
              setFixed(e.target.value);
            }}
            className={input}
          />
        </label>
      </div>
      {quote.data && (
        <p className="text-sm">
          Будет продаваться за ${quote.data.price_usd}
          {quote.data.price_uzs !== null && ` / ${formatSum(quote.data.price_uzs)}`}
        </p>
      )}
      {(save.isError || quote.isError) && (
        <p role="alert" className="text-danger">
          {errorText(save.error ?? quote.error)}
        </p>
      )}
      <div className="flex gap-3">
        <Button
          type="button"
          disabled={save.isPending}
          onClick={() => {
            submit(body);
          }}
        >
          Сохранить цену
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={save.isPending}
          onClick={() => {
            setPp("");
            setFixed("");
            submit({ margin_override_pp: null, fixed_price_usd: null });
          }}
        >
          Сбросить ручную цену
        </Button>
      </div>
    </div>
  );
}

export function OverrideCard() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [onlyOverridden, setOnlyOverridden] = useState(false);
  const [chosen, setChosen] = useState<PricedItem | null>(null);
  const debounced = useDebounced(text.trim(), DEBOUNCE_MS);
  const q = debounced.length >= 2 ? debounced : undefined;
  const list = useQuery({
    queryKey: ["pricing", "items", q, onlyOverridden],
    queryFn: () => findPricedItems(q, onlyOverridden),
    enabled: q !== undefined || onlyOverridden,
  });
  return (
    <section className="border-border bg-surface flex flex-col gap-4 rounded-lg border p-5">
      <h2 className="text-lg font-semibold">Цена одного скина</h2>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-1 flex-col gap-1 text-sm">
          Найти скин
          <input
            type="search"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            placeholder="Например: asiimov"
            className="border-border bg-bg h-10 rounded-md border px-3"
          />
        </label>
        <label className="flex h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyOverridden}
            onChange={(e) => {
              setOnlyOverridden(e.target.checked);
            }}
          />
          Только с ручной ценой
        </label>
      </div>
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.data?.items.length === 0 && <p className="text-fg-muted">Ничего не найдено.</p>}
      {(list.data?.items.length ?? 0) > 0 && (
        <ul className="flex flex-col gap-1">
          {list.data?.items.map((item) => (
            <li key={item.slug}>
              <button
                type="button"
                className="text-left text-sm underline"
                onClick={() => {
                  setChosen(item);
                }}
              >
                {item.name}
                {item.margin_override_pp ? ` · ${item.margin_override_pp} п.п.` : ""}
                {item.fixed_price_usd ? ` · $${item.fixed_price_usd}` : ""}
              </button>
            </li>
          ))}
        </ul>
      )}
      {chosen && (
        <Editor
          key={chosen.slug}
          item={chosen}
          onSaved={(saved) => {
            setChosen(saved);
            void qc.invalidateQueries({ queryKey: ["pricing"] });
          }}
        />
      )}
    </section>
  );
}
