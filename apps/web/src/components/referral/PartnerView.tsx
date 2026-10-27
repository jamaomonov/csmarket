"use client";

import { Badge, Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { RewardsList } from "./RewardsList";

import { useAuth } from "@/lib/auth";
import { type Counts, getPartner, PARTNER_KEY, type PartnerMe, partnerLink } from "@/lib/referrals";

interface PartnerViewProps {
  locale: string;
}

/** «Реферал»: the partner's link, terms, numbers and rewards; auth states as on the account pages. */
export function PartnerView({ locale }: PartnerViewProps) {
  const t = useTranslations("web.referral");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const partner = useQuery({ queryKey: PARTNER_KEY, queryFn: getPartner, enabled: signedIn });
  if (status === "loading" || (signedIn && partner.isPending)) {
    return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
  }
  if (status === "suspended") return <p className="text-danger">{auth("suspended")}</p>;
  if (!signedIn) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">{t("signedOut")}</p>
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg rounded-md px-5 py-3 font-semibold"
        >
          {nav("signIn")}
        </a>
      </div>
    );
  }
  if (partner.isError) return <p className="text-fg-muted">{t("error")}</p>;
  if (partner.data === null || partner.data === undefined) {
    return <p className="text-fg-muted max-w-prose">{t("invite")}</p>;
  }
  return <PartnerPage locale={locale} me={partner.data} />;
}

function PartnerPage({ locale, me }: { locale: string; me: PartnerMe }) {
  const t = useTranslations("web.referral");
  const percent = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(
    Number(me.percent),
  );
  const term = me.term_months === null ? t("forever") : t("months", { count: me.term_months });
  const day = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });
  return (
    <div className="flex flex-col gap-6">
      <section className="bg-surface border-border flex flex-col gap-3 rounded-xl border p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lead font-semibold">{t("link")}</h2>
          {me.active ? null : <Badge tone="neutral">{t("off")}</Badge>}
        </div>
        <CopyLink link={partnerLink(me.code)} />
        <p className="text-fg-muted text-sm">{t("terms", { percent, term })}</p>
        <p className="text-fg-dim text-sm">{me.active ? t("linkHint") : t("offHint")}</p>
      </section>
      <div className="grid gap-4 sm:grid-cols-2">
        <Money label={t("held")} sum={formatUzs(locale, me.held_uzs)}>
          {me.next_available_at
            ? t("nextAt", { date: day.format(new Date(me.next_available_at)) })
            : null}
        </Money>
        <Money label={t("credited")} sum={formatUzs(locale, me.credited_uzs)}>
          {t("creditedHint")}
        </Money>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Stats title={t("month")} counts={me.month} locale={locale} />
        <Stats title={t("allTime")} counts={me.all_time} locale={locale} />
      </div>
      <RewardsList locale={locale} />
    </div>
  );
}

function CopyLink({ link }: { link: string }) {
  const t = useTranslations("web.referral");
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex gap-2">
      <input
        readOnly
        value={link}
        aria-label={t("link")}
        className="bg-surface-2 border-border min-w-0 flex-1 rounded-md border px-3 py-2 font-mono text-sm"
        onFocus={(e) => {
          e.currentTarget.select();
        }}
      />
      <Button
        variant="secondary"
        onClick={() => {
          void navigator.clipboard.writeText(link).then(() => {
            setCopied(true);
          });
        }}
      >
        {copied ? (
          <Check className="size-4" aria-hidden />
        ) : (
          <Copy className="size-4" aria-hidden />
        )}
        {copied ? t("copied") : t("copy")}
      </Button>
    </div>
  );
}

function Money({
  label,
  sum,
  children,
}: {
  label: string;
  sum: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-surface border-border rounded-xl border p-5">
      <p className="text-fg-muted text-sm">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{sum}</p>
      {children ? <p className="text-fg-dim mt-1 text-sm">{children}</p> : null}
    </div>
  );
}

function Stats({ title, counts, locale }: { title: string; counts: Counts; locale: string }) {
  const t = useTranslations("web.referral");
  const rows: [string, string][] = [
    [t("visits"), String(counts.visits)],
    [t("accounts"), String(counts.accounts)],
    [t("purchases"), String(counts.purchases)],
    [t("earned"), formatUzs(locale, counts.earned_uzs)],
  ];
  return (
    <section className="bg-surface border-border rounded-xl border p-5">
      <h3 className="font-semibold">{title}</h3>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-fg-muted">{label}</dt>
            <dd className="text-right font-medium tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
