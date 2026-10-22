/** Pieces of «Настройки выкупа»: the limits block and the warnings' words. */
import { type SaleSettings, type SettingsWarning } from "./api";

import { MoneyField } from "@/components/MoneyInput";
import { Section } from "@/components/Section";

export const WARNING_TEXT: Record<SettingsWarning, string> = {
  balance_bonus_eats_margin:
    "Бонус за баланс съедает маржу верхнего диапазона: дорогая продажа на баланс в минус. Поднимите маржу или снизьте бонус.",
};

type LimitKey = "max_sale_usd" | "max_user_day_usd" | "max_day_usd";

const LIMITS: readonly { key: LimitKey; label: string }[] = [
  { key: "max_sale_usd", label: "Максимум одной продажи" },
  { key: "max_user_day_usd", label: "Максимум на продавца за 24 ч" },
  { key: "max_day_usd", label: "Максимум на всех за 24 ч" },
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

interface LimitsSectionProps {
  doc: SaleSettings;
  onChange: (patch: Partial<SaleSettings>) => void;
}

/** The three USD ceilings; an empty field is no limit. */
export function LimitsSection({ doc, onChange }: LimitsSectionProps) {
  return (
    <Section title="Лимиты">
      <p className="text-fg-muted mb-3 text-sm">По ценам Skinslink. Пусто — без лимита.</p>
      <div className="grid gap-4 sm:grid-cols-3">
        {LIMITS.map(({ key, label }) => (
          <MoneyField
            key={key}
            label={label}
            unit="$"
            decimal
            value={doc[key] ?? ""}
            onChange={(v) => {
              onChange({ [key]: v });
            }}
          />
        ))}
      </div>
    </Section>
  );
}
