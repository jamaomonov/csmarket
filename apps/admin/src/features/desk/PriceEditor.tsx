/** A deal's price: soʻm at a rate (the CBU's filled in) or dollars. Closes once it is saved. */
import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type Currency, type Deal, type DealPatch, DESK_KEY, getRate } from "./api";
import { deskErrorText } from "./labels";
import { cleanAmount, grouped, TAP } from "./Parts";
import { CurrencySwitch, RateField, toUsd } from "./SellSheet";

import { Money } from "@/components/Money";
import { MoneyInput } from "@/components/MoneyInput";

interface PriceEditorProps {
  deal: Deal;
  /** Resolves when saved; a rejection keeps the form open with its reason. */
  onSave: (body: DealPatch) => Promise<unknown>;
}

export function PriceEditor({ deal, onSave }: PriceEditorProps) {
  const [editing, setEditing] = useState(deal.paid_amount === null);
  const [amount, setAmount] = useState(deal.paid_amount ?? "");
  const [currency, setCurrency] = useState<Currency>(deal.paid_currency ?? "UZS");
  const [rate, setRate] = useState<string | null>(deal.rate);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const cbu = useQuery({ queryKey: [...DESK_KEY, "rate"], queryFn: getRate });
  const shownRate = rate ?? cbu.data?.usd_uzs ?? "";
  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          Оплачено:{" "}
          {deal.paid_currency === "UZS" && deal.paid_amount ? (
            <>
              <Money uzs={deal.paid_amount} /> по курсу {grouped(deal.rate ?? "0")} ={" "}
            </>
          ) : null}
          {deal.paid_usd && <Money usd={deal.paid_usd} />}
        </span>
        <Button
          variant="secondary"
          className={TAP}
          onClick={() => {
            setEditing(true);
          }}
        >
          Изменить цену
        </Button>
      </div>
    );
  }
  const ready = toUsd(amount, currency, shownRate) !== null;
  const save = () => {
    if (!ready) return;
    setBusy(true);
    setError(null);
    onSave({
      paid_amount: cleanAmount(amount),
      paid_currency: currency,
      ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
    })
      .then(() => {
        setEditing(false);
      })
      .catch(setError)
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <form
      className="flex flex-wrap items-end gap-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <label className="flex flex-col gap-1">
        Сколько заплачено
        <MoneyInput
          label="Сколько заплачено"
          unit={currency === "UZS" ? "сум" : "$"}
          decimal={currency === "USD"}
          value={amount}
          onChange={setAmount}
          className="w-44"
        />
      </label>
      <CurrencySwitch value={currency} onChange={setCurrency} />
      {currency === "UZS" && <RateField value={shownRate} onChange={setRate} />}
      <div className="flex w-full gap-2">
        {deal.paid_amount !== null && (
          <Button
            type="button"
            variant="secondary"
            className={TAP}
            onClick={() => {
              setEditing(false);
              setError(null);
            }}
          >
            Отмена
          </Button>
        )}
        <Button type="submit" className={TAP} disabled={!ready || busy}>
          {busy ? "Сохраняем…" : "Сохранить цену"}
        </Button>
      </div>
      {error !== null && (
        <p role="alert" className="text-danger w-full">
          {deskErrorText(error)}
        </p>
      )}
    </form>
  );
}
