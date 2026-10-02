/**
 * The rules form's editable copy: every number as the operator typed it, maps as rows.
 * `toRules` turns it back into the document the API takes; the API validates the shape.
 */
import { type PricingRules } from "./api";

export interface KeyRow {
  key: string;
  pp: string;
}

export interface RulesDraft {
  expenses_percent: string;
  min_margin_usd: string;
  price_floor_usd: string;
  uzs_round_to: string;
  cap_at_steam: boolean;
  retail: { from_usd: string; percent: string }[];
  liquidity: { min_count: string; pp: string }[];
  category_pp: KeyRow[];
  weapon_pp: KeyRow[];
}

const rows = (map: Record<string, string>): KeyRow[] =>
  Object.entries(map).map(([key, pp]) => ({ key, pp }));

const map = (list: KeyRow[]): Record<string, string> =>
  Object.fromEntries(
    list.filter((r) => r.key.trim() !== "").map((r) => [r.key.trim(), r.pp.trim()]),
  );

export function fromRules(rules: PricingRules): RulesDraft {
  return {
    expenses_percent: rules.expenses_percent,
    min_margin_usd: rules.min_margin_usd,
    price_floor_usd: rules.price_floor_usd,
    uzs_round_to: String(rules.uzs_round_to),
    cap_at_steam: rules.cap_at_steam,
    retail: rules.retail.map((b) => ({ ...b })),
    liquidity: rules.liquidity.map((b) => ({ min_count: String(b.min_count), pp: b.pp })),
    category_pp: rows(rules.category_pp),
    weapon_pp: rows(rules.weapon_pp),
  };
}

export function toRules(d: RulesDraft): PricingRules {
  return {
    expenses_percent: d.expenses_percent.trim(),
    min_margin_usd: d.min_margin_usd.trim(),
    price_floor_usd: d.price_floor_usd.trim(),
    uzs_round_to: Number.parseInt(d.uzs_round_to, 10),
    cap_at_steam: d.cap_at_steam,
    retail: d.retail.map((b) => ({ from_usd: b.from_usd.trim(), percent: b.percent.trim() })),
    liquidity: d.liquidity.map((b) => ({
      min_count: Number.parseInt(b.min_count, 10),
      pp: b.pp.trim(),
    })),
    category_pp: map(d.category_pp),
    weapon_pp: map(d.weapon_pp),
  };
}
