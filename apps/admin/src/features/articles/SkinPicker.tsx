/** Find a catalogue item by name and hand back its slug for a `[[skin:…]]` card. */
import { Input } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { findItems } from "@/features/catalogue/api";

interface SkinPickerProps {
  onPick: (slug: string) => void;
}

export function SkinPicker({ onPick }: SkinPickerProps) {
  const [q, setQ] = useState("");
  const query = q.trim();
  const found = useQuery({
    queryKey: ["admin", "articles", "skin-search", query],
    queryFn: () => findItems({ q: query }),
    enabled: query.length >= 2,
  });
  return (
    <div className="border-border bg-surface space-y-2 rounded-lg border p-3">
      <Input
        aria-label="Поиск скина"
        placeholder="Название, например AK-47 Redline"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
        }}
        autoFocus
      />
      <ul className="max-h-64 overflow-y-auto">
        {found.data?.items.map((i) => (
          <li key={i.slug}>
            <button
              type="button"
              className="hover:bg-surface-2 w-full rounded px-2 py-1.5 text-left text-sm"
              onClick={() => {
                onPick(i.slug);
              }}
            >
              {i.name}
            </button>
          </li>
        ))}
      </ul>
      {found.isSuccess && found.data.items.length === 0 ? (
        <p className="text-fg-muted text-sm">Ничего не нашлось.</p>
      ) : null}
    </div>
  );
}
