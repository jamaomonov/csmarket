/**
 * An item's colours (spec 2026-10-14-skin-colors): the swatches it has now and, on «Цвет»,
 * a picker of twelve — one or two chosen, «Сохранить» sets them for every wear of the skin,
 * «Авто» gives them back to the job, which reads the picture again.
 */
import { Button } from "@csmarket/ui";
import { SKIN_COLORS, type SkinColor } from "@csmarket/utils/skins";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type AdminSkinItem, setColors } from "./api";

import { ApiError, formatApiError } from "@/lib/api";

const NAMES: Record<SkinColor, string> = {
  red: "Красный",
  orange: "Оранжевый",
  yellow: "Жёлтый",
  green: "Зелёный",
  blue: "Синий",
  purple: "Фиолетовый",
  pink: "Розовый",
  brown: "Коричневый",
  beige: "Бежевый",
  black: "Чёрный",
  white: "Белый",
  grey: "Серый",
};

const FILL: Record<SkinColor, string> = {
  red: "#d6312b",
  orange: "#ef7d22",
  yellow: "#f5cf3a",
  green: "#4f9a2e",
  blue: "#2f6fe8",
  purple: "#7a1785",
  pink: "#e24fd4",
  brown: "#7a5233",
  beige: "#c9b293",
  black: "#0b0b0b",
  white: "#ffffff",
  grey: "#9b9b9b",
};

const known = (list: readonly string[] | undefined): SkinColor[] =>
  SKIN_COLORS.filter((c) => (list ?? []).includes(c));

function Dot({ color }: { color: SkinColor }) {
  return (
    <span
      aria-hidden
      className="inline-block size-3.5 rounded-full shadow-[inset_0_0_0_1px_rgba(127,127,127,0.5)]"
      style={{ background: FILL[color] }}
    />
  );
}

export function ColorEditor({ item }: { item: AdminSkinItem }) {
  const qc = useQueryClient();
  const now = known(item.colors);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<SkinColor[]>(now);
  const save = useMutation({
    mutationFn: (colors: SkinColor[] | null) => setColors(item.slug, colors),
    onSuccess: () => {
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["catalogue", "items"] });
    },
  });
  const toggle = (c: SkinColor): void => {
    setPicked((p) => (p.includes(c) ? p.filter((x) => x !== c) : [...p, c].slice(-2)));
  };
  return (
    <div className="mt-1 text-sm">
      <div className="text-fg-muted flex flex-wrap items-center gap-2">
        {now.length > 0 ? (
          now.map((c) => (
            <span key={c} className="inline-flex items-center gap-1">
              <Dot color={c} />
              {NAMES[c]}
            </span>
          ))
        ) : (
          <span>цвет не определён</span>
        )}
        {item.colors_manual === true && <span className="text-fg-dim">· вручную</span>}
        <button
          type="button"
          className="text-accent hover:underline"
          onClick={() => {
            setPicked(now);
            setOpen((o) => !o);
          }}
        >
          Цвет
        </button>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Цвета скина">
            {SKIN_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                aria-pressed={picked.includes(c)}
                onClick={() => {
                  toggle(c);
                }}
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ${
                  picked.includes(c) ? "border-accent text-fg" : "border-border text-fg-muted"
                }`}
              >
                <Dot color={c} />
                {NAMES[c]}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={picked.length === 0 || save.isPending}
              onClick={() => {
                save.mutate(picked);
              }}
            >
              Сохранить
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={save.isPending}
              onClick={() => {
                save.mutate(null);
              }}
            >
              Авто
            </Button>
          </div>
          {save.isError && (
            <p role="alert" className="text-danger">
              {save.error instanceof ApiError ? formatApiError(save.error) : "Не получилось."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
