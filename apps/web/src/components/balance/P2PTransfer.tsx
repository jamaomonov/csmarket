"use client";

import { buttonVariants } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { Clock, CreditCard } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { P2PTransferInfo } from "@/lib/balance";

import { Link } from "@/i18n/navigation";
import { DEPOSIT } from "@/lib/paths";

interface P2PTransferProps {
  locale: string;
  /** The top-up's number, for support. */
  number: string;
  transfer: P2PTransferInfo;
  /** The Telegram support link; empty hides it. */
  supportUrl: string;
  /** The clock (tests); the live time otherwise. */
  now?: Date;
}

/** `9860000000004321` → `9860 0000 0000 4321`. */
function byFours(digits: string): string {
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

/** `8:30` from milliseconds. */
function minutesSeconds(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60).toString()}:${(total % 60).toString().padStart(2, "0")}`;
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const t = useTranslations("web.balance.p2p");
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const id = setTimeout(() => {
      setDone(false);
    }, 2_000);
    return () => {
      clearTimeout(id);
    };
  }, [done]);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setDone(true);
        });
      }}
      className="border-border-strong bg-surface hover:bg-surface-hover h-10 shrink-0 rounded-lg border px-3 text-sm font-medium"
    >
      {done ? t("copied") : label}
    </button>
  );
}

/**
 * A P2P top-up awaiting its transfer: the card and the exact amount, each with «Скопировать»,
 * the holder and the time left; once the time is out, a new request and the support link.
 */
export function P2PTransfer({ locale, number, transfer, supportUrl, now }: P2PTransferProps) {
  const t = useTranslations("web.balance.p2p");
  const [live, setLive] = useState(() => now ?? new Date());
  useEffect(() => {
    if (now !== undefined) return;
    const id = setInterval(() => {
      setLive(new Date());
    }, 1_000);
    return () => {
      clearInterval(id);
    };
  }, [now]);
  const at = now ?? live;
  const left = new Date(transfer.expires_at).getTime() - at.getTime();
  const amount = formatUzs(locale, transfer.amount_uzs);
  const panel = "bg-surface border-border flex flex-col gap-5 rounded-xl border p-5 sm:p-6";

  if (transfer.status !== "pending" || left <= 0) {
    return (
      <section className={panel}>
        <h1 className="text-h3 font-semibold">{t("expiredTitle")}</h1>
        <p className="text-fg-muted">{t("expiredNote", { number })}</p>
        <div className="flex flex-wrap gap-3">
          <Link href={DEPOSIT} className={buttonVariants({ size: "lg" })}>
            {t("newRequest")}
          </Link>
          {supportUrl ? (
            <a
              href={supportUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ size: "lg", variant: "secondary" })}
            >
              {t("support")}
            </a>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section className={panel}>
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-h3 flex items-center gap-2 font-semibold">
          <CreditCard className="text-accent size-6" aria-hidden />
          {t("title")}
        </h1>
        <span className="text-fg-muted flex items-center gap-1.5 text-sm tabular-nums">
          <Clock className="size-4" aria-hidden />
          {t("left")} <span data-testid="p2p-left">{minutesSeconds(left)}</span>
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-fg-muted text-sm">{t("cardLabel")}</span>
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-xl font-semibold tracking-wider sm:text-2xl">
            {byFours(transfer.card_number)}
          </span>
          <CopyButton text={transfer.card_number} label={t("copyCard")} />
        </div>
        <span className="text-fg-muted text-sm">
          {t("holderLabel")}: <span className="text-fg">{transfer.holder}</span>
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-fg-muted text-sm">{t("amountLabel")}</span>
        <div className="flex items-center justify-between gap-3">
          <span data-testid="p2p-amount" className="text-accent text-2xl font-bold tabular-nums">
            {amount}
          </span>
          <CopyButton text={transfer.amount_uzs} label={t("copyAmount")} />
        </div>
        <p className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm font-medium">
          {t("exact", { amount })}
        </p>
      </div>
      <p className="text-fg-muted text-sm">{t("waiting")}</p>
    </section>
  );
}
