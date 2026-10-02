"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import type { Locale } from "@csmarket/i18n";

import { PaymentPicker } from "@/components/skins/PaymentPicker";
import { usePayMethods } from "@/components/skins/usePayMethods";
import { BALANCE_KEY } from "@/lib/balance";
import { mintPayKey } from "@/lib/order-key";
import {
  BalanceTooLowError,
  devPayOrder,
  OrderNotPayableError,
  payOrder,
  type OrderOut,
  type PayProvider,
} from "@/lib/orders";
import { WALLET } from "@/lib/prefer-balance";

interface OrderPayProps {
  /** A `pending`, payable order. */
  order: OrderOut;
  locale: Locale;
  /** The kassa the buyer chose on the item page, pre-selected. */
  initial: PayProvider | null;
  /** Re-read the order: the page never trusts what a pay call answered. */
  onPaid: () => void;
}

/**
 * Pay a pending order from its page: the method picker and one button. The balance pays
 * at once; a kassa opens its page in this tab; the test kassa settles here
 * («Оплатить (тест)») and never navigates away.
 */
export function OrderPay({ order, locale, initial, onPaid }: OrderPayProps) {
  const t = useTranslations("web.orders");
  const buy = useTranslations("web.buy");
  const common = useTranslations("common");
  const qc = useQueryClient();
  const { kassas, chosen, provider, wallet, pick } = usePayMethods(
    locale,
    order.price_uzs,
    initial,
  );
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  // `busy` disables the button from the next render; this blocks a click that lands first.
  const inFlight = useRef(false);
  const test = provider === "mock";

  async function run(method: PayProvider): Promise<void> {
    if (method === "mock") {
      await devPayOrder(order.number);
      onPaid();
      return;
    }
    const out = await payOrder(order.number, { provider: method, locale }, mintPayKey());
    if (method !== WALLET && out.intent_url !== null) {
      window.location.assign(out.intent_url);
      return;
    }
    void qc.invalidateQueries({ queryKey: BALANCE_KEY });
    onPaid();
  }

  async function pay(): Promise<void> {
    if (inFlight.current || provider === null) return;
    inFlight.current = true;
    setBusy(true);
    setFailed(false);
    try {
      await run(provider);
    } catch (err) {
      if (err instanceof BalanceTooLowError) {
        // The tile turns red with what is missing once the balance is read again.
        void qc.invalidateQueries({ queryKey: BALANCE_KEY });
      } else if (err instanceof OrderNotPayableError) {
        // Paid or expired meanwhile: the order, read again, says which.
        onPaid();
      } else {
        setFailed(true);
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <PaymentPicker
        providers={kassas}
        method={chosen}
        onPick={pick}
        labels={{
          legend: buy("methodTitle"),
          test: buy("methodTest"),
          none: buy("methodNone"),
        }}
        {...(wallet ? { wallet } : {})}
      />
      {failed ? (
        <p role="alert" className="text-danger text-sm">
          {common("errors.generic")}
        </p>
      ) : null}
      <Button
        type="button"
        size="lg"
        className="self-start"
        disabled={busy || provider === null}
        onClick={() => {
          void pay();
        }}
      >
        {test ? t("payTest") : t("payNow", { price: formatUzs(locale, order.price_uzs) })}
      </Button>
    </div>
  );
}
