/** Pieces of «Настройки выкупа»: a number field, the limits block and the warnings' words. */
import { type SaleSettings, type SettingsWarning } from "./api";

export const WARNING_TEXT: Record<SettingsWarning, string> = {
  balance_bonus_eats_margin:
    "Бонус за баланс съедает маржу верхнего диапазона: дорогая продажа на баланс в минус. Поднимите маржу или снизьте бонус.",
};

type LimitKey = "max_sale_usd" | "max_user_day_usd" | "max_day_usd";

const LIMITS: readonly { key: LimitKey; label: string }[] = [
  { key: "max_sale_usd", label: "Максимум одной продажи, $" },
  { key: "max_user_day_usd", label: "Максимум на продавца за 24 ч, $" },
  { key: "max_day_usd", label: "Максимум на всех за 24 ч, $" },
];

/** An emptied limit field is «no limit» (`null`), never `""`. */
export function withLimits(doc: SaleSettings): SaleSettings {
  const out = { ...doc };
  for (const { key } of LIMITS) {
    const v = (doc[key] ?? "").trim();
    out[key] = v === "" ? null : v;
  }
  return out;
}

interface NumberFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
}

export function NumberField({ label, value, onChange }: NumberFieldProps) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <input
        aria-label={label}
        inputMode="decimal"
        value={value}
        onChange={(e) => {
          onChange(e.target.value.trim());
        }}
        className="border-border bg-bg w-full rounded-md border px-3 py-1.5 tabular-nums sm:w-40"
      />
    </label>
  );
}

interface LimitsSectionProps {
  doc: SaleSettings;
  onChange: (patch: Partial<SaleSettings>) => void;
}

/** The three USD ceilings; an empty field is no limit. */
export function LimitsSection({ doc, onChange }: LimitsSectionProps) {
  return (
    <section className="border-border bg-surface flex flex-col gap-2 rounded-lg border p-4">
      <h2 className="font-semibold">Лимиты (по ценам Skinslink; пусто — без лимита)</h2>
      <div className="flex flex-wrap gap-4">
        {LIMITS.map(({ key, label }) => (
          <NumberField
            key={key}
            label={label}
            value={doc[key] ?? ""}
            onChange={(v) => {
              onChange({ [key]: v });
            }}
          />
        ))}
      </div>
    </section>
  );
}
