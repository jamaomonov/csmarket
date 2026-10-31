/** «Продажа…»: where a stock skin went and for how much (soʻm at a rate, or dollars). */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type SubmitEvent, useState } from "react";

import { type Currency, DESK_KEY, getRate, sellItem, type SellBody } from "./api";
import { deskErrorText } from "./labels";
import { cleanAmount, TAP } from "./Parts";

import { Money } from "@/components/Money";
import { MoneyInput } from "@/components/MoneyInput";

interface SellFormProps {
  itemId: string;
  /** The skin's cost, for the profit preview. */
  costUsd: string | null;
  onDone: () => void;
}

export function CurrencySwitch({
  value,
  onChange,
}: {
  value: Currency;
  onChange: (c: Currency) => void;
}) {
  return (
    <div className="flex gap-1" role="group" aria-label="Валюта">
      {(["UZS", "USD"] as const).map((c) => (
        <Button
          key={c}
          type="button"
          variant={value === c ? "primary" : "secondary"}
          aria-pressed={value === c}
          className={TAP}
          onClick={() => {
            onChange(c);
          }}
        >
          {c === "UZS" ? "сум" : "$"}
        </Button>
      ))}
    </div>
  );
}

/** The CBU rate, filled in and editable. */
export function RateField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      Курс (ЦБ на сегодня)
      <input
        aria-label="Курс (ЦБ на сегодня)"
        inputMode="decimal"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        className="border-border bg-bg h-11 w-32 rounded-md border px-2 sm:h-10"
      />
    </label>
  );
}

/** Dollars of `amount` in `currency` at `rate`; `null` when it cannot be told. */
export function toUsd(amount: string, currency: Currency, rate: string): number | null {
  const a = Number(cleanAmount(amount));
  if (!(a > 0)) return null;
  if (currency === "USD") return a;
  const r = Number(cleanAmount(rate));
  return r > 0 ? a / r : null;
}

export function SellForm({ itemId, costUsd, onDone }: SellFormProps) {
  const qc = useQueryClient();
  const [where, setWhere] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<Currency>("UZS");
  const [rate, setRate] = useState<string | null>(null);
  const cbu = useQuery({ queryKey: [...DESK_KEY, "rate"], queryFn: getRate });
  const shownRate = rate ?? cbu.data?.usd_uzs ?? "";
  const sell = useMutation({
    mutationFn: (body: SellBody) => sellItem(itemId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DESK_KEY });
      onDone();
    },
  });
  const usd = toUsd(amount, currency, shownRate);
  const ready = where.trim() !== "" && usd !== null;
  const submit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!ready) return;
    sell.mutate({
      where: where.trim(),
      amount: cleanAmount(amount),
      currency,
      ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
    });
  };
  return (
    <form className="mt-2 flex flex-wrap items-end gap-2 text-sm" onSubmit={submit}>
      <label className="flex flex-col gap-1">
        Где продано
        <input
          value={where}
          onChange={(e) => {
            setWhere(e.target.value);
          }}
          placeholder="Market.csgo, Buff, покупатель…"
          className="border-border bg-bg h-11 rounded-md border px-2 sm:h-10"
        />
      </label>
      <label className="flex flex-col gap-1">
        Сумма
        <MoneyInput
          label="Сумма"
          unit={currency === "UZS" ? "сум" : "$"}
          decimal={currency === "USD"}
          value={amount}
          onChange={setAmount}
          className="w-40"
        />
      </label>
      <CurrencySwitch value={currency} onChange={setCurrency} />
      {currency === "UZS" && <RateField value={shownRate} onChange={setRate} />}
      {usd !== null && costUsd !== null && (
        <p className="w-full">
          Прибыль: <Money usd={(usd - Number(costUsd)).toFixed(2)} signed />
        </p>
      )}
      <div className="flex w-full gap-2">
        <Button type="button" variant="secondary" className={TAP} onClick={onDone}>
          Отмена
        </Button>
        <Button type="submit" className={TAP} disabled={!ready || sell.isPending}>
          {sell.isPending ? "Записываем…" : "Записать продажу"}
        </Button>
      </div>
      {sell.isError && (
        <p role="alert" className="text-danger w-full">
          {deskErrorText(sell.error)}
        </p>
      )}
    </form>
  );
}
