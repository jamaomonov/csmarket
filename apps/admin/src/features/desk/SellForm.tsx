/** «Продал…»: where a stock skin went and for how much (soʻm at a rate, or dollars). */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type SubmitEvent, useState } from "react";

import { type Currency, DESK_KEY, getRate, sellItem, type SellBody } from "./api";
import { deskErrorText } from "./labels";

interface SellFormProps {
  itemId: string;
  onDone: () => void;
}

/** `"14 300 000"` / `"25,5"` → `"14300000"` / `"25.5"`. */
export function cleanAmount(raw: string): string {
  return raw.replace(/\s/g, "").replace(",", ".");
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
          size="sm"
          variant={value === c ? "primary" : "secondary"}
          aria-pressed={value === c}
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

export function SellForm({ itemId, onDone }: SellFormProps) {
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
  const value = cleanAmount(amount);
  const ready =
    where.trim() !== "" && Number(value) > 0 && (currency === "USD" || Number(shownRate) > 0);
  const submit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!ready) return;
    sell.mutate({
      where: where.trim(),
      amount: value,
      currency,
      ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
    });
  };
  const input = "border-border bg-bg h-10 rounded-md border px-2";
  return (
    <form className="mt-2 flex flex-wrap items-end gap-2 text-sm" onSubmit={submit}>
      <label className="flex flex-col gap-1">
        Где продал
        <input
          value={where}
          onChange={(e) => {
            setWhere(e.target.value);
          }}
          placeholder="Market.csgo, Buff…"
          className={input}
        />
      </label>
      <label className="flex flex-col gap-1">
        Сумма
        <input
          inputMode="decimal"
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
          className={`${input} w-32`}
        />
      </label>
      <CurrencySwitch value={currency} onChange={setCurrency} />
      {currency === "UZS" && (
        <label className="flex flex-col gap-1">
          Курс
          <input
            inputMode="decimal"
            value={shownRate}
            onChange={(e) => {
              setRate(e.target.value);
            }}
            className={`${input} w-24`}
          />
        </label>
      )}
      <Button type="submit" size="sm" disabled={!ready || sell.isPending}>
        Записать продажу
      </Button>
      {sell.isError && (
        <p role="alert" className="text-danger w-full">
          {deskErrorText(sell.error)}
        </p>
      )}
    </form>
  );
}
