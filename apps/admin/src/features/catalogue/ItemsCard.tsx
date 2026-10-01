/** Find an item by name and hide or show it in the public catalogue. */
import { Button } from "@csmarket/ui";
import { steamImageSize } from "@csmarket/utils/skins";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type AdminSkinItem, findItems, setHidden } from "./api";

import { ApiError, formatApiError } from "@/lib/api";
import { useDebounced } from "@/lib/useDebounced";

const MIN_QUERY = 2;
const DEBOUNCE_MS = 300;

function errorText(err: unknown): string {
  return err instanceof ApiError ? formatApiError(err) : "Не получилось. Попробуйте ещё раз.";
}

interface ItemRowProps {
  item: AdminSkinItem;
  pending: boolean;
  onToggle: (item: AdminSkinItem) => void;
}

function ItemRow({ item, pending, onToggle }: ItemRowProps) {
  return (
    <li className="border-border flex items-center gap-3 border-b py-2 last:border-b-0">
      {item.image_url ? (
        <img
          src={steamImageSize(item.image_url, "128fx96f")}
          alt=""
          width={64}
          height={48}
          loading="lazy"
          className="bg-surface-2 h-12 w-16 shrink-0 rounded object-contain"
        />
      ) : (
        <div className="bg-surface-2 h-12 w-16 shrink-0 rounded" aria-hidden="true" />
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{item.name}</div>
        <div className="text-fg-muted text-sm">
          {item.category ?? "—"}
          {item.price_usd ? ` · $${item.price_usd}` : ""}
          {item.hidden ? " · скрыт" : ""}
        </div>
      </div>
      <span
        className={`rounded px-2 py-0.5 text-xs ${item.active ? "bg-success text-success-fg" : "bg-surface-2 text-fg-muted"}`}
      >
        {item.active ? "в продаже" : "нет предложений"}
      </span>
      <Button
        variant="secondary"
        size="sm"
        disabled={pending}
        onClick={() => {
          onToggle(item);
        }}
      >
        {item.hidden ? "Показать" : "Скрыть"}
      </Button>
    </li>
  );
}

export function ItemsCard() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [onlyHidden, setOnlyHidden] = useState(false);
  const debounced = useDebounced(text.trim(), DEBOUNCE_MS);
  const q = debounced.length >= MIN_QUERY ? debounced : undefined;
  const hidden = onlyHidden ? true : undefined;
  const enabled = q !== undefined || onlyHidden;

  const list = useQuery({
    queryKey: ["catalogue", "items", q, hidden],
    queryFn: () => findItems({ ...(q !== undefined && { q }), ...(hidden && { hidden }) }),
    enabled,
  });
  const toggle = useMutation({
    mutationFn: (item: AdminSkinItem) => setHidden(item.slug, !item.hidden),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalogue"] }),
  });

  const items = list.data?.items ?? [];
  return (
    <section className="border-border bg-surface rounded-lg border p-5">
      <h2 className="mb-3 text-lg font-semibold">Скины</h2>
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex flex-1 flex-col gap-1 text-sm">
          Найти скин
          <input
            type="search"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            placeholder="Например: redline"
            className="border-border bg-bg h-10 rounded-md border px-3 text-base"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyHidden}
            onChange={(e) => {
              setOnlyHidden(e.target.checked);
            }}
          />
          Только скрытые
        </label>
      </div>
      {!enabled && <p className="text-fg-muted mt-3 text-sm">Введите от двух букв названия.</p>}
      {enabled && list.isPending && <p className="text-fg-muted mt-3">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger mt-3">
          {errorText(list.error)}
        </p>
      )}
      {toggle.isError && (
        <p role="alert" className="text-danger mt-3">
          {errorText(toggle.error)}
        </p>
      )}
      {list.data && items.length === 0 && <p className="text-fg-muted mt-3">Ничего не найдено.</p>}
      {items.length > 0 && (
        <ul className="mt-3">
          {items.map((item) => (
            <ItemRow
              key={item.slug}
              item={item}
              pending={toggle.isPending && toggle.variables.slug === item.slug}
              onToggle={(it) => {
                toggle.mutate(it);
              }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
