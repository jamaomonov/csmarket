/**
 * The pricing document as a form: the main numbers, cheap skins, the margin by cost and the
 * markups. Markups are percentage points added to the margin, shown with «%».
 */
import { Switch } from "@csmarket/ui";

import { RowsTable } from "./RowsTable";
import { type KeyRow, type RulesDraft } from "./rules-draft";

import { MoneyField } from "@/components/MoneyInput";
import { SaveBar } from "@/components/SaveBar";
import { Section } from "@/components/Section";

interface RulesFormProps {
  draft: RulesDraft;
  /** Fields that differ from the saved rules; the save bar shows only above 0. */
  changed: number;
  saving: boolean;
  error: string | null;
  onChange: (draft: RulesDraft) => void;
  onReset: () => void;
  onSave: () => void;
}

type NumberField =
  | "expenses_percent"
  | "min_margin_usd"
  | "price_floor_usd"
  | "uzs_round_to"
  | "tail_max_cost_usd"
  | "tail_sticker_pp"
  | "tail_low_liquidity_pp";

interface Numeric {
  field: NumberField;
  label: string;
  unit: string;
  whole?: boolean;
}

const NUMBERS: Numeric[] = [
  { field: "expenses_percent", label: "Расходы", unit: "%" },
  { field: "min_margin_usd", label: "Минимальная маржа", unit: "$" },
  { field: "price_floor_usd", label: "Нижняя цена", unit: "$" },
  { field: "uzs_round_to", label: "Округление", unit: "сум", whole: true },
];

/** Cheap skins: under the bound, these replace the sticker and the thinnest band. */
const CHEAP: Numeric[] = [
  { field: "tail_max_cost_usd", label: "Себестоимость до", unit: "$" },
  { field: "tail_sticker_pp", label: "Надбавка наклейкам", unit: "%" },
  { field: "tail_low_liquidity_pp", label: "Надбавка за мало лотов", unit: "%" },
];

const keyRows = (rows: Record<string, string>[]): KeyRow[] =>
  rows.map((r) => ({ key: r.key ?? "", pp: r.pp ?? "" }));

export function RulesForm({
  draft,
  changed,
  saving,
  error,
  onChange,
  onReset,
  onSave,
}: RulesFormProps) {
  const set = (patch: Partial<RulesDraft>): void => {
    onChange({ ...draft, ...patch });
  };
  const numbers = (fields: Numeric[]) => (
    <div className="grid gap-4 sm:grid-cols-3">
      {fields.map(({ field, label, unit, whole }) => (
        <MoneyField
          key={field}
          label={label}
          unit={unit}
          decimal={whole !== true}
          value={draft[field]}
          onChange={(v) => {
            set({ [field]: v });
          }}
        />
      ))}
    </div>
  );
  return (
    <div className="flex flex-col gap-4">
      <Section title="Основное">
        {numbers(NUMBERS)}
        <Switch
          label="Не дороже Steam"
          states={["да", "нет"]}
          className="mt-3"
          checked={draft.cap_at_steam}
          onCheckedChange={(on) => {
            set({ cap_at_steam: on });
          }}
        />
      </Section>
      <Section title="Дешёвые скины">
        <p className="text-fg-muted mb-3 text-sm">
          Дешевле этой суммы — свои надбавки вместо надбавки категории «Наклейки» и за мало лотов.
          Пусто — как у всех.
        </p>
        {numbers(CHEAP)}
      </Section>
      <Section title="Маржа и надбавки">
        <div className="grid gap-6 md:grid-cols-2">
          <RowsTable
            title="Маржа по себестоимости"
            hint="Доля себестоимости в каждом диапазоне цены."
            columns={[
              { field: "from_usd", label: "Цена от", unit: "$" },
              { field: "percent", label: "Маржа", unit: "%" },
            ]}
            rows={draft.retail}
            addLabel="Добавить диапазон"
            removeLabel="Удалить диапазон"
            onChange={(rows) => {
              set({
                retail: rows.map((r) => ({ from_usd: r.from_usd ?? "", percent: r.percent ?? "" })),
              });
            }}
          />
          <RowsTable
            title="Надбавка за мало лотов"
            hint="Сколько предложений на Waxpeer — столько и надбавка."
            columns={[
              { field: "min_count", label: "Лотов от", unit: "шт", whole: true },
              { field: "pp", label: "Надбавка за лоты", unit: "%" },
            ]}
            rows={draft.liquidity}
            addLabel="Добавить строку"
            removeLabel="Удалить строку"
            onChange={(rows) => {
              set({
                liquidity: rows.map((r) => ({ min_count: r.min_count ?? "", pp: r.pp ?? "" })),
              });
            }}
          />
          <RowsTable
            title="Надбавки по категориям"
            hint="Категория — как в адресе каталога: rifles, knives, stickers."
            columns={[
              { field: "key", label: "Категория", placeholder: "rifles" },
              { field: "pp", label: "Надбавка категории", unit: "%" },
            ]}
            rows={draft.category_pp.map((r) => ({ key: r.key, pp: r.pp }))}
            addLabel="Добавить категорию"
            removeLabel="Удалить категорию"
            onChange={(rows) => {
              set({ category_pp: keyRows(rows) });
            }}
          />
          <RowsTable
            title="Надбавки по оружию"
            columns={[
              { field: "key", label: "Оружие", placeholder: "AK-47" },
              { field: "pp", label: "Надбавка оружия", unit: "%" },
            ]}
            rows={draft.weapon_pp.map((r) => ({ key: r.key, pp: r.pp }))}
            addLabel="Добавить оружие"
            removeLabel="Удалить оружие"
            onChange={(rows) => {
              set({ weapon_pp: keyRows(rows) });
            }}
          />
        </div>
      </Section>
      <SaveBar changed={changed} saving={saving} onSave={onSave} onReset={onReset}>
        {error && (
          <p role="alert" className="text-danger text-sm">
            {error}
          </p>
        )}
      </SaveBar>
    </div>
  );
}
