/** The pricing document as a form: the numbers, the brackets, the bands and the markups. */
import { Button } from "@csmarket/ui";

import { RowsTable } from "./RowsTable";
import { type KeyRow, type RulesDraft } from "./rules-draft";

interface RulesFormProps {
  draft: RulesDraft;
  dirty: boolean;
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

const NUMBERS: [NumberField, string][] = [
  ["expenses_percent", "Расходы, %"],
  ["min_margin_usd", "Мин. маржа, $"],
  ["price_floor_usd", "Нижняя цена, $"],
  ["uzs_round_to", "Округление, сум"],
];

/** The cheap tail: under the bound, these replace the sticker and the thinnest band. */
const TAIL: [NumberField, string][] = [
  ["tail_max_cost_usd", "Хвост: себестоимость до, $"],
  ["tail_sticker_pp", "Хвост: наклейки, п.п."],
  ["tail_low_liquidity_pp", "Хвост: мало лотов, п.п."],
];

const keyRows = (rows: Record<string, string>[]): KeyRow[] =>
  rows.map((r) => ({ key: r.key ?? "", pp: r.pp ?? "" }));

export function RulesForm({
  draft,
  dirty,
  saving,
  error,
  onChange,
  onReset,
  onSave,
}: RulesFormProps) {
  const set = (patch: Partial<RulesDraft>): void => {
    onChange({ ...draft, ...patch });
  };
  return (
    <section className="border-border bg-surface flex flex-col gap-5 rounded-lg border p-5">
      <h2 className="text-lg font-semibold">Правила</h2>
      {[NUMBERS, TAIL].map((fields) => (
        <div key={fields[0]?.[0]} className="flex flex-wrap items-end gap-4">
          {fields.map(([field, label]) => (
            <label key={field} className="flex flex-col gap-1 text-sm">
              {label}
              <input
                inputMode="decimal"
                value={draft[field]}
                onChange={(e) => {
                  set({ [field]: e.target.value });
                }}
                className="border-border bg-bg h-10 w-32 rounded-md border px-3"
              />
            </label>
          ))}
          {fields === NUMBERS && (
            <label className="flex h-10 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={draft.cap_at_steam}
                onChange={(e) => {
                  set({ cap_at_steam: e.target.checked });
                }}
              />
              Не дороже Steam
            </label>
          )}
        </div>
      ))}
      <div className="grid gap-5 md:grid-cols-2">
        <RowsTable
          title="Брекеты маржи (доля себестоимости в каждом диапазоне)"
          columns={[
            { field: "from_usd", label: "от $" },
            { field: "percent", label: "%" },
          ]}
          rows={draft.retail}
          addLabel="Добавить брекет"
          removeLabel="Удалить брекет"
          onChange={(rows) => {
            set({
              retail: rows.map((r) => ({ from_usd: r.from_usd ?? "", percent: r.percent ?? "" })),
            });
          }}
        />
        <RowsTable
          title="Ликвидность (лотов у Waxpeer → п.п.)"
          columns={[
            { field: "min_count", label: "от N лотов", inputMode: "numeric" },
            { field: "pp", label: "п.п." },
          ]}
          rows={draft.liquidity}
          addLabel="Добавить полосу"
          removeLabel="Удалить полосу"
          onChange={(rows) => {
            set({ liquidity: rows.map((r) => ({ min_count: r.min_count ?? "", pp: r.pp ?? "" })) });
          }}
        />
        <RowsTable
          title="Надбавки по категориям"
          columns={[
            { field: "key", label: "Категория (slug)", inputMode: "text" },
            { field: "pp", label: "Надбавка категории, п.п." },
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
            { field: "key", label: "Оружие", inputMode: "text" },
            { field: "pp", label: "Надбавка оружия, п.п." },
          ]}
          rows={draft.weapon_pp.map((r) => ({ key: r.key, pp: r.pp }))}
          addLabel="Добавить оружие"
          removeLabel="Удалить оружие"
          onChange={(rows) => {
            set({ weapon_pp: keyRows(rows) });
          }}
        />
      </div>
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" disabled={saving} onClick={onSave}>
          Сохранить
        </Button>
        <Button type="button" variant="secondary" disabled={!dirty || saving} onClick={onReset}>
          Сбросить
        </Button>
        {dirty && <span className="text-warning text-sm">Есть несохранённые изменения</span>}
      </div>
    </section>
  );
}
