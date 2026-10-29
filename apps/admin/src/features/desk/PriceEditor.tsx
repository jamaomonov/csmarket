/** A deal's price: the amount in soʻm (at a rate, the CBU's by default) or dollars. */
import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type Currency, type Deal, type DealPatch, DESK_KEY, getRate } from "./api";
import { cleanAmount, CurrencySwitch } from "./SellForm";

import { Money } from "@/components/Money";

interface PriceEditorProps {
  deal: Deal;
  onSave: (body: DealPatch) => void;
}

export function PriceEditor({ deal, onSave }: PriceEditorProps) {
  const [editing, setEditing] = useState(deal.paid_amount === null);
  const [amount, setAmount] = useState(deal.paid_amount ?? "");
  const [currency, setCurrency] = useState<Currency>(deal.paid_currency ?? "UZS");
  const [rate, setRate] = useState<string | null>(deal.rate);
  const cbu = useQuery({ queryKey: [...DESK_KEY, "rate"], queryFn: getRate });
  const shownRate = rate ?? cbu.data?.usd_uzs ?? "";
  if (!editing) {
    return (
      <p className="text-sm">
        Заплатил:{" "}
        {deal.paid_currency === "UZS" && deal.paid_amount ? (
          <>
            <Money uzs={deal.paid_amount} /> по курсу {deal.rate} ={" "}
          </>
        ) : null}
        {deal.paid_usd && <Money usd={deal.paid_usd} />}{" "}
        <button
          type="button"
          className="text-accent underline"
          onClick={() => {
            setEditing(true);
          }}
        >
          изменить
        </button>
      </p>
    );
  }
  const value = cleanAmount(amount);
  const ready = Number(value) > 0 && (currency === "USD" || Number(cleanAmount(shownRate)) > 0);
  return (
    <form
      className="flex flex-wrap items-end gap-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready) return;
        onSave({
          paid_amount: value,
          paid_currency: currency,
          ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
        });
        setEditing(false);
      }}
    >
      <label className="flex flex-col gap-1">
        Сколько заплатил
        <input
          inputMode="decimal"
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
          className="border-border bg-bg h-10 w-36 rounded-md border px-2"
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
            className="border-border bg-bg h-10 w-24 rounded-md border px-2"
          />
        </label>
      )}
      <Button type="submit" size="sm" disabled={!ready}>
        Сохранить цену
      </Button>
    </form>
  );
}
