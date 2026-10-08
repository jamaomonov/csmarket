/**
 * «Изменить баланс»: a signed amount (whole soʻm, or dollars with up to three decimals) and a reason, then a confirm
 * step that says the outcome out loud («Начислить 50 000 сум» / «Списать …»).
 */
import { Button } from "@csmarket/ui";
import { useMutation } from "@tanstack/react-query";
import { type SubmitEvent, useRef, useState } from "react";

import { adjustBalance, adjustUsdBalance, type AdminUserCard } from "./api";
import { errorText } from "./labels";
import { parseAmount, parseUsd } from "./parseAmount";
import { type IdempotencyKey } from "./useIdempotencyKey";

import { formatSum, formatUsd } from "@/lib/format";

/** The API's per-adjustment ceiling (`wallet.ADMIN_ADJUST_MAX`). */
const ADJUST_MAX = 100_000_000;
/** The API's dollar ceiling (`wallet.ADMIN_ADJUST_USD_MAX`, milli-USD / 1000). */
const ADJUST_USD_MAX = 100_000;
const REASON_MIN = 4;
const REASON_MAX = 500;

type Currency = "UZS" | "USD";

interface Draft {
  currency: Currency;
  /** Whole soʻm, or the API's dollar string (`"250.000"`). */
  amount: string;
  reason: string;
}

function validate(currency: Currency, amountText: string, reasonText: string): Draft | string {
  const reason = reasonText.trim();
  if (currency === "USD") {
    const usd = parseUsd(amountText);
    if (usd === null) return "Введите сумму в долларах, до трёх знаков: 250 или -30.5.";
    if (Number(usd) === 0) return "Сумма не может быть нулём.";
    if (Math.abs(Number(usd)) > ADJUST_USD_MAX) {
      return `Не больше ${formatUsd(String(ADJUST_USD_MAX))} за раз.`;
    }
    if (reason.length < REASON_MIN) return "Напишите причину — от 4 символов.";
    return { currency, amount: usd, reason };
  }
  const amount = parseAmount(amountText);
  if (amount === null) return "Введите целую сумму в сумах, например 50 000 или -10 000.";
  if (amount === 0) return "Сумма не может быть нулём.";
  if (Math.abs(amount) > ADJUST_MAX) return `Не больше ${formatSum(ADJUST_MAX)} за раз.`;
  if (reason.length < REASON_MIN) return "Напишите причину — от 4 символов.";
  return { currency, amount: String(amount), reason };
}

/** `Начислить 50 000 сум` / `Списать $10.000`. */
function outcome(draft: Draft): string {
  const credit = !draft.amount.startsWith("-");
  const abs = draft.amount.replace(/^-/, "");
  const sum = draft.currency === "USD" ? formatUsd(abs) : formatSum(abs);
  return `${credit ? "Начислить" : "Списать"} ${sum}`;
}

interface AdjustFormProps {
  userId: string;
  /** Owned by the card so a lost response retried after reopening still replays. */
  idem: IdempotencyKey;
  onDone: (card: AdminUserCard) => void;
  onClose: () => void;
}

export function AdjustForm({ userId, idem, onDone, onClose }: AdjustFormProps) {
  const [currency, setCurrency] = useState<Currency>("UZS");
  const [amountText, setAmountText] = useState("");
  const [reasonText, setReasonText] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const inFlight = useRef(false);
  const mutation = useMutation({
    mutationFn: (v: Draft & { key: string }) =>
      v.currency === "USD"
        ? adjustUsdBalance(userId, v.amount, v.reason, v.key)
        : adjustBalance(userId, Number(v.amount), v.reason, v.key),
    onSuccess: (card) => {
      idem.reset();
      onDone(card);
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });

  const onReview = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    const result = validate(currency, amountText, reasonText);
    if (typeof result === "string") {
      setFormError(result);
      return;
    }
    setFormError(null);
    mutation.reset();
    setDraft(result);
  };

  const onConfirm = () => {
    if (draft === null || inFlight.current) return;
    inFlight.current = true;
    mutation.mutate({ ...draft, key: idem.keyFor(JSON.stringify({ userId, ...draft })) });
  };

  const box = "border-border bg-surface space-y-4 rounded-lg border p-5";
  if (draft !== null) {
    return (
      <div className={box} data-testid="adjust-confirm-step">
        <p>Причина: {draft.reason}</p>
        {mutation.isError && (
          <p role="alert" className="text-danger text-sm">
            {errorText(mutation.error)}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            variant={draft.amount.startsWith("-") ? "danger" : "primary"}
            disabled={mutation.isPending}
            onClick={onConfirm}
            data-testid="adjust-confirm"
          >
            {outcome(draft)}
          </Button>
          <Button
            variant="ghost"
            disabled={mutation.isPending}
            onClick={() => {
              setDraft(null);
            }}
          >
            Назад
          </Button>
        </div>
      </div>
    );
  }

  const input = "border-border bg-bg rounded-md border px-3 text-base";
  return (
    <form onSubmit={onReview} className={box} data-testid="adjust-form">
      <div role="group" aria-label="Валюта" className="flex gap-2">
        {(["UZS", "USD"] as const).map((c) => (
          <Button
            key={c}
            variant={currency === c ? "primary" : "secondary"}
            aria-pressed={currency === c}
            onClick={() => {
              setCurrency(c);
              setFormError(null);
            }}
          >
            {c === "UZS" ? "Сум" : "USD"}
          </Button>
        ))}
      </div>
      <label className="flex max-w-xs flex-col gap-1 text-sm">
        {currency === "USD" ? "Сумма, USD" : "Сумма, сум"}
        <input
          value={amountText}
          inputMode="numeric"
          maxLength={20}
          onChange={(e) => {
            setAmountText(e.target.value);
          }}
          className={`${input} h-10`}
        />
      </label>
      <p className="text-fg-muted text-xs">Со знаком минус — списать.</p>
      <label className="flex flex-col gap-1 text-sm">
        Причина изменения
        <textarea
          value={reasonText}
          maxLength={REASON_MAX}
          rows={2}
          onChange={(e) => {
            setReasonText(e.target.value);
          }}
          className={`${input} py-2`}
        />
      </label>
      <p className="text-fg-muted text-xs">Её увидят в журнале. Без личных данных.</p>
      {formError !== null && (
        <p role="alert" className="text-danger text-sm">
          {formError}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit">Продолжить</Button>
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
      </div>
    </form>
  );
}
