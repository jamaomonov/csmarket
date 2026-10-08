"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button } from "@csmarket/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState, type SyntheticEvent } from "react";

import { ENTRIES_KEY } from "./EntriesList";

import {
  amountValue,
  caretAfterDigits,
  digitsBeforeCaret,
  groupDigits,
  toDigits,
} from "@/lib/amount-input";
import {
  BALANCE_KEY,
  CONVERT_MAX,
  CONVERT_MIN,
  convertToUsd,
  previewUsd,
  type UsdWallet,
} from "@/lib/balance";

interface UsdWalletCardProps {
  locale: string;
  usd: UsdWallet;
}

type Notice = "done" | "tooLow" | "failed" | "rateUnavailable" | null;

/** The USD wallet under the soʻm card: dollars on hand and a conversion from the soʻm balance. */
export function UsdWalletCard({ locale, usd }: UsdWalletCardProps) {
  const t = useTranslations("web.balance.usd");
  const client = useQueryClient();
  const fieldRef = useRef<HTMLInputElement>(null);
  const keyRef = useRef<string | null>(null);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const typed = amountValue(amount);
  const rate = usd.rate_uzs;
  const preview = rate !== null && typed > 0 ? previewUsd(typed, rate) : null;
  const valid = typed >= CONVERT_MIN && typed <= CONVERT_MAX;

  function onChange(raw: string, caret: number) {
    const digits = toDigits(raw);
    const grouped = groupDigits(digits, locale);
    const before = digitsBeforeCaret(raw, caret);
    // A different amount is a different request: it needs its own key.
    if (grouped !== amount) keyRef.current = null;
    setAmount(grouped);
    setNotice(null);
    requestAnimationFrame(() => {
      const pos = caretAfterDigits(grouped, before);
      fieldRef.current?.setSelectionRange(pos, pos);
    });
  }

  async function onSubmit(e: SyntheticEvent) {
    e.preventDefault();
    if (busy || !valid || rate === null) return;
    // One key per submitted form: a retry of the same amount replays, success resets it.
    keyRef.current ??= `web-convert-${crypto.randomUUID()}`;
    setBusy(true);
    setNotice(null);
    let converted = false;
    try {
      await convertToUsd(typed, keyRef.current);
      converted = true;
      keyRef.current = null;
      setAmount("");
      setNotice("done");
    } catch (err) {
      const code = err instanceof SessionApiError ? err.code : undefined;
      if (code === "balance_too_low") {
        setNotice("tooLow");
      } else if (code === "rate_unavailable") {
        setNotice("rateUnavailable");
      } else {
        setNotice("failed");
      }
      // A code-less failure (network) keeps the key so a retry replays; an answer drops it.
      if (code !== undefined) keyRef.current = null;
    } finally {
      setBusy(false);
    }
    if (converted) {
      // The money has moved; a failed re-read must not turn that into an error.
      await Promise.all([
        client.invalidateQueries({ queryKey: BALANCE_KEY }),
        client.invalidateQueries({ queryKey: ENTRIES_KEY }),
      ]).catch(() => undefined);
    }
  }

  const unavailable = rate === null;
  return (
    <section className="bg-surface flex flex-col gap-4 rounded-xl p-5">
      <div>
        <h2 className="text-fg-muted text-sm">{t("title")}</h2>
        <p className="mt-1 text-3xl font-bold tabular-nums">{`$${usd.balance_usd}`}</p>
        <p className="text-fg-dim mt-1 text-sm">{t("hint")}</p>
      </div>
      <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-2">
        <label htmlFor="usd-convert" className="text-fg-muted text-sm">
          {t("convertLabel")}
        </label>
        <div className="flex flex-wrap gap-3">
          <input
            id="usd-convert"
            ref={fieldRef}
            inputMode="numeric"
            autoComplete="off"
            disabled={unavailable}
            value={amount}
            onChange={(e) => {
              onChange(e.target.value, e.target.selectionStart ?? e.target.value.length);
            }}
            className="bg-surface-2 min-w-0 flex-1 rounded-md px-3 py-2 tabular-nums"
          />
          <Button type="submit" disabled={unavailable || busy || !valid}>
            {t("convertSubmit")}
          </Button>
        </div>
        {unavailable ? (
          <p className="text-fg-muted text-sm">{t("rateUnavailable")}</p>
        ) : preview !== null ? (
          <p className="text-fg-muted text-sm">
            {t("preview", {
              usd: preview,
              rate: new Intl.NumberFormat(locale, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              }).format(Number(rate)),
            })}
          </p>
        ) : null}
        {notice === "done" ? (
          <p role="status" className="text-success text-sm">
            {t("done")}
          </p>
        ) : notice !== null ? (
          <p role="alert" className="text-danger text-sm">
            {t(notice)}
          </p>
        ) : null}
      </form>
    </section>
  );
}
