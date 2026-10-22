/** Words and number formats of the analytics page. */
import { formatMoneyUsd } from "@/components/Money";
import { formatSum } from "@/lib/format";

export const SOURCE_LABELS: Record<string, string> = {
  waxpeer: "Waxpeer",
  skinslink: "Skinslink",
  lisskins: "LIS-SKINS",
};

export const PAYMENT_LABELS: Record<string, string> = {
  wallet: "Баланс",
  usd_wallet: "USD-кошелёк",
  click: "Click",
  payme: "Payme",
  uzum: "Uzum",
  mock: "Тест",
  other: "Другое",
};

export const CATEGORY_LABELS: Record<string, string> = {
  rifles: "Винтовки",
  pistols: "Пистолеты",
  smgs: "ПП",
  heavy: "Тяжёлое",
  knives: "Ножи",
  gloves: "Перчатки",
  agents: "Агенты",
  cases: "Кейсы",
  keys: "Ключи",
  "music-kits": "Музыка",
  charms: "Брелоки",
  stickers: "Наклейки",
  graffiti: "Граффити",
  patches: "Нашивки",
  collectibles: "Коллекционное",
  highlights: "Хайлайты",
  other: "Другое",
};

export const REASON_LABELS: Record<string, string> = { other: "Без причины" };

export function labelOf(labels: Record<string, string>, key: string): string {
  return labels[key] ?? key;
}

/** Soʻm with a typographic minus for a loss: `−6 264 сум`. */
export function som(value: string | number): string {
  const n = Number(value);
  return n < 0 ? `−${formatSum(-n)}` : formatSum(n);
}

const MILLIONS = new Intl.NumberFormat("ru", { notation: "compact", maximumFractionDigits: 1 });
const THOUSANDS = new Intl.NumberFormat("ru", { notation: "compact", maximumFractionDigits: 0 });

/** A short sum for a narrow cell or an axis: `3,7 млн`, `−493 тыс`, `950`. */
export function compactSom(value: string | number): string {
  const n = Number(value);
  const text = (Math.abs(n) >= 1_000_000 ? MILLIONS : THOUSANDS).format(Math.abs(n));
  return `${n < 0 ? "−" : ""}${text.replace(/\.$/, "")}`;
}

/** Dollars with two decimals and a typographic minus. */
export function dollars(value: string): string {
  const n = Number(value);
  return n < 0 ? `−${formatMoneyUsd(-n)}` : formatMoneyUsd(n);
}

export interface Delta {
  text: string;
  /** `up` / `down` against the previous period; `none` when it had nothing. */
  dir: "up" | "down" | "flat" | "none";
}

/** `▲ +12,5 %` against the previous period (whole percent from 100 on). */
export function delta(current: string | number, previous: string | number): Delta {
  const cur = Number(current);
  const prev = Number(previous);
  if (prev === 0) return { text: "—", dir: "none" };
  const pct = ((cur - prev) / Math.abs(prev)) * 100;
  if (Math.abs(pct) < 0.05) return { text: "0 %", dir: "flat" };
  const digits = Math.abs(pct) >= 100 ? 0 : 1;
  const shown = new Intl.NumberFormat("ru", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Math.abs(pct));
  return pct > 0 ? { text: `▲ +${shown} %`, dir: "up" } : { text: `▼ −${shown} %`, dir: "down" };
}
