/**
 * Find one skin: type any words of its name in any order («redline mw», a pasted market name
 * with `|` and `★`), pick with the mouse or arrows + Enter. Each row shows the picture, the
 * name with its phase, our price and the stock, so two look-alike rows are told apart.
 */
import { cn } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, type ReactNode, useId, useState } from "react";

import { type AdminSkinItem } from "./api";

import { SkinThumb } from "@/components/SkinThumb";
import { useDebounced } from "@/lib/useDebounced";

const DEBOUNCE_MS = 250;
const MIN_CHARS = 2;

interface SkinSearchProps<T extends AdminSkinItem> {
  onPick: (item: T) => void;
  /** The search call (the admin's `GET /admin/skins/items?q=`). */
  find: (q: string) => Promise<{ items: T[] }>;
  label?: string;
  /** Extra words after a row's price, e.g. a manual price. */
  note?: (item: T) => ReactNode;
  autoFocus?: boolean;
}

export function SkinSearch<T extends AdminSkinItem>({
  onPick,
  find,
  label = "Найти скин",
  note,
  autoFocus = false,
}: SkinSearchProps<T>) {
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const q = useDebounced(text.trim(), DEBOUNCE_MS);
  const listId = useId();
  const found = useQuery({
    queryKey: ["admin", "skin-search", label, q],
    queryFn: () => find(q),
    enabled: q.length >= MIN_CHARS,
  });
  const items = q.length >= MIN_CHARS ? (found.data?.items ?? []) : [];

  function pick(item: T | undefined) {
    if (!item) return;
    onPick(item);
    setText("");
    setActive(0);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(items[active]);
    } else if (e.key === "Escape") {
      setText("");
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1 text-sm">
        {label}
        <input
          type="search"
          role="combobox"
          aria-expanded={items.length > 0}
          aria-controls={listId}
          aria-activedescendant={items.length > 0 ? `${listId}-${String(active)}` : undefined}
          value={text}
          autoFocus={autoFocus}
          onChange={(e) => {
            setText(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          placeholder="Например: redline mw или AK-47 | Redline (Field-Tested)"
          className="border-border bg-bg h-11 rounded-md border px-3"
        />
      </label>
      {q.length >= MIN_CHARS && found.isFetching && items.length === 0 && (
        <p className="text-fg-muted text-sm">Ищу…</p>
      )}
      {found.isError && (
        <p role="alert" className="text-danger text-sm">
          Поиск не ответил. Попробуйте ещё раз.
        </p>
      )}
      {q.length >= MIN_CHARS && found.isSuccess && items.length === 0 && (
        <p className="text-fg-muted text-sm">Ничего не нашлось. Попробуйте меньше слов.</p>
      )}
      {items.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Найденные скины"
          className="border-border max-h-80 overflow-y-auto rounded-md border"
        >
          {items.map((item, i) => (
            <li
              key={item.slug}
              id={`${listId}-${String(i)}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => {
                setActive(i);
              }}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(item);
              }}
              className={cn(
                "flex min-h-11 cursor-pointer items-center gap-3 px-2 py-1.5 text-sm",
                i === active && "bg-surface-2",
              )}
            >
              <SkinThumb url={item.image_url} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">
                  {item.name}
                  {item.phase ? <span className="text-fg-muted"> · {item.phase}</span> : null}
                </span>
                <span className="text-fg-muted block text-xs">
                  {item.price_usd ? `$${item.price_usd}` : "нет в продаже"} · {item.count} шт.
                  {item.hidden ? " · скрыт" : ""}
                  {note ? <> · {note(item)}</> : null}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
