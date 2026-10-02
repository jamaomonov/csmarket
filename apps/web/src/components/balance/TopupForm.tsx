"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button, cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useTranslations } from "next-intl";
import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useTransition,
  type SyntheticEvent,
} from "react";

import type { Locale } from "@csmarket/i18n";

import { offeredKassas, PaymentPicker } from "@/components/skins/PaymentPicker";
import { useRouter } from "@/i18n/navigation";
import {
  amountValue,
  caretAfterDigits,
  digitsBeforeCaret,
  groupDigits,
  pastedDigits,
  toDigits,
} from "@/lib/amount-input";
import {
  createTopup,
  QUICK_AMOUNTS,
  TOPUP_MAX,
  TOPUP_MIN,
  topupAttemptKey,
  type AttemptStore,
  type Provider,
} from "@/lib/balance";

type FormError = "badAmount" | "failed";

/**
 * The field's length, separators included. Past ~16 digits `Number()` rounds and the
 * field would show digits nobody typed; a paste is clamped to the same count.
 */
const FIELD_MAX = String(TOPUP_MAX).length + 4;

interface TopupFormProps {
  locale: Locale;
  /** The kassas open now; `undefined` while the list loads. */
  providers: Provider[] | undefined;
}

/**
 * Amount (grouped as typed, quick chips), kassa tiles, submit. On success the visitor
 * goes to the top-up's page with `?go=1`, which opens the kassa once.
 */
export function TopupForm({ locale, providers }: TopupFormProps) {
  const t = useTranslations("web.balance");
  const router = useRouter();
  const fieldId = useId();
  const rangeId = useId();
  const [amount, setAmount] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  // `busy` disables the button from the next render; this blocks a second submit
  // that lands before it.
  const inFlight = useRef(false);
  // Pending while the router moves to the top-up's page: the button stays disabled
  // for exactly as long as the page is changing, and no longer.
  const [navigating, startNavigation] = useTransition();
  // Survives re-renders so a second submit after a failed first one replays that
  // request instead of opening another top-up.
  const attempt = useRef<AttemptStore["current"]>(null);
  const fieldRef = useRef<HTMLInputElement>(null);
  // Regrouping rewrites the field and throws the caret to the end; put it back
  // beside the digit being edited.
  const caretDigits = useRef<number | null>(null);

  useLayoutEffect(() => {
    const el = fieldRef.current;
    const wanted = caretDigits.current;
    if (!el || wanted === null) return;
    caretDigits.current = null;
    const at = caretAfterDigits(el.value, wanted);
    el.setSelectionRange(at, at);
  });

  const offered = offeredKassas(providers);
  const method = offered.find((p) => p.slug === chosen)?.slug ?? offered[0]?.slug ?? null;
  const typed = amountValue(amount);
  const bounds = { min: formatUzs(locale, TOPUP_MIN), max: formatUzs(locale, TOPUP_MAX) };
  const outOfRange = typed > TOPUP_MAX || (error === "badAmount" && typed < TOPUP_MIN);

  const edit = (digits: string): void => {
    setAmount(digits.slice(0, FIELD_MAX));
    setError(null);
  };

  async function submit(e: SyntheticEvent): Promise<void> {
    e.preventDefault();
    if (inFlight.current || busy || navigating || method === null || typed === 0) return;
    if (typed < TOPUP_MIN || typed > TOPUP_MAX) {
      setError("badAmount");
      return;
    }
    setError(null);
    inFlight.current = true;
    setBusy(true);
    try {
      const topup = await createTopup(
        { amount_uzs: typed, provider: method, locale },
        topupAttemptKey(attempt, `${typed.toString()}:${method}`),
      );
      startNavigation(() => {
        router.push(`/account/balance/topups/${encodeURIComponent(topup.number)}?go=1`);
      });
    } catch (err) {
      const code = err instanceof SessionApiError ? err.code : undefined;
      setError(code === "topup_amount" ? "badAmount" : "failed");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <section className="border-border rounded-lg border p-5">
      <h2 className="text-lg font-bold">{t("topUpTitle")}</h2>
      <form
        noValidate
        onSubmit={(e) => {
          void submit(e);
        }}
        className="mt-4 flex flex-col gap-5"
      >
        <div>
          <label htmlFor={fieldId} className="text-fg-muted mb-2 block text-sm font-semibold">
            {t("amountLabel")}
          </label>
          <input
            id={fieldId}
            ref={fieldRef}
            inputMode="numeric"
            autoComplete="off"
            placeholder="0"
            value={groupDigits(amount, locale)}
            onChange={(e) => {
              caretDigits.current = digitsBeforeCaret(
                e.target.value,
                e.target.selectionStart ?? e.target.value.length,
              );
              edit(toDigits(e.target.value));
            }}
            onPaste={(e) => {
              // A pasted "50000.00" carries a fraction to drop; a typed comma is the
              // field's own grouping. Only the paste knows which it is.
              e.preventDefault();
              edit(pastedDigits(e.clipboardData.getData("text")));
            }}
            maxLength={FIELD_MAX}
            aria-invalid={outOfRange}
            aria-describedby={rangeId}
            className="border-border bg-surface focus:border-accent h-14 w-full rounded-md border px-4 text-2xl font-bold tabular-nums outline-none"
          />
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {QUICK_AMOUNTS.map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={typed === v}
                onClick={() => {
                  edit(String(v));
                }}
                className={cn(
                  "h-11 rounded-md border px-3 text-sm font-bold tabular-nums",
                  typed === v
                    ? "border-accent bg-accent/10"
                    : "border-border bg-surface hover:border-border-strong",
                )}
              >
                {groupDigits(String(v), locale)}
              </button>
            ))}
          </div>
          <p
            id={rangeId}
            className={cn("mt-3 text-sm", outOfRange ? "text-danger" : "text-fg-dim")}
          >
            {t("amountRange", bounds)}
          </p>
        </div>

        <PaymentPicker
          providers={providers}
          method={method}
          onPick={(slug) => {
            setChosen(slug);
            setError(null);
          }}
          labels={{ legend: t("methodLabel"), test: t("methodTest"), none: t("methodNone") }}
        />

        {error ? (
          <p role="alert" className="text-danger text-sm">
            {error === "badAmount" ? t("badAmount", bounds) : t("failed")}
          </p>
        ) : null}

        <Button
          type="submit"
          size="lg"
          disabled={busy || navigating || method === null || typed === 0}
        >
          {typed === 0 ? t("enterAmount") : t("submit", { amount: formatUzs(locale, typed) })}
        </Button>
      </form>
    </section>
  );
}
