/**
 * «Продал»: a sheet with the skin and its cost on top, «Продал за» first (soʻm at a rate, or
 * dollars), then where — the last place remembered on this device.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type Currency, DESK_KEY, getRate, sellItem, type SellBody } from "./api";
import { deskErrorText } from "./labels";
import { cleanAmount, TAP } from "./Parts";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { Money } from "@/components/Money";
import { MoneyInput } from "@/components/MoneyInput";

const WHERE_KEY = "desk.sold_where";

function lastWhere(): string {
  try {
    return localStorage.getItem(WHERE_KEY) ?? "";
  } catch {
    return "";
  }
}

function rememberWhere(where: string): void {
  try {
    localStorage.setItem(WHERE_KEY, where);
  } catch {
    // A private window: the field just starts empty next time.
  }
}

interface SellSheetProps {
  item: { id: string; name: string; cost_usd: string | null };
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

export function SellSheet({ item, onDone }: SellSheetProps) {
  const qc = useQueryClient();
  const [where, setWhere] = useState(lastWhere);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<Currency>("UZS");
  const [rate, setRate] = useState<string | null>(null);
  const cbu = useQuery({ queryKey: [...DESK_KEY, "rate"], queryFn: getRate });
  const shownRate = rate ?? cbu.data?.usd_uzs ?? "";
  const sell = useMutation({
    mutationFn: (body: SellBody) => sellItem(item.id, body),
    onSuccess: (_, body) => {
      rememberWhere(body.where);
      void qc.invalidateQueries({ queryKey: DESK_KEY });
      onDone();
    },
  });
  const usd = toUsd(amount, currency, shownRate);
  const ready = where.trim() !== "" && usd !== null;
  const submit = () => {
    if (!ready) return;
    sell.mutate({
      where: where.trim(),
      amount: cleanAmount(amount),
      currency,
      ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
    });
  };
  return (
    <ConfirmSheet title="Продал" busy={sell.isPending} onClose={onDone}>
      <div className="text-sm">
        <p className="font-medium">{item.name}</p>
        {item.cost_usd !== null && (
          <p className="text-fg-muted">
            Себестоимость <Money usd={item.cost_usd} />
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col gap-1">
          Продал за
          <MoneyInput
            label="Продал за"
            unit={currency === "UZS" ? "сум" : "$"}
            decimal={currency === "USD"}
            value={amount}
            onChange={setAmount}
            className="w-40"
          />
        </label>
        <CurrencySwitch value={currency} onChange={setCurrency} />
        {currency === "UZS" && <RateField value={shownRate} onChange={setRate} />}
      </div>
      <label className="flex flex-col gap-1 text-sm">
        Где продано
        <input
          value={where}
          onChange={(e) => {
            setWhere(e.target.value);
          }}
          placeholder="Market.csgo, Buff, покупатель…"
          className="border-border bg-bg h-11 rounded-md border px-3"
        />
      </label>
      {usd !== null && item.cost_usd !== null && (
        <p className="text-sm">
          Прибыль: <Money usd={(usd - Number(item.cost_usd)).toFixed(2)} signed />
        </p>
      )}
      {sell.isError && (
        <p role="alert" className="text-danger text-sm">
          {deskErrorText(sell.error)}
        </p>
      )}
      <div className={CONFIRM_BUTTONS}>
        <Button variant="secondary" className={TAP} disabled={sell.isPending} onClick={onDone}>
          Отмена
        </Button>
        <Button className={TAP} disabled={!ready || sell.isPending} onClick={submit}>
          {sell.isPending ? "Записываем…" : "Записать продажу"}
        </Button>
      </div>
    </ConfirmSheet>
  );
}
