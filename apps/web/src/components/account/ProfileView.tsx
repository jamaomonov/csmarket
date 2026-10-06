"use client";

import { Badge, buttonVariants, cn } from "@csmarket/ui";
import { Check, Copy, ExternalLink, Gift } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { EmailForm } from "./EmailForm";
import { SettingsCard } from "./SettingsCard";
import { TradeLinkForm } from "./TradeLinkForm";
import { UserAvatar } from "./UserAvatar";

import { useAuth } from "@/lib/auth";

interface ProfileViewProps {
  locale: string;
}

/** «Профиль»: who you are (avatar, name, since when, Steam ID) and «Ваш аккаунт» settings. */
export function ProfileView({ locale }: ProfileViewProps) {
  const t = useTranslations("web.account");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const soon = useTranslations("web.soon");
  const { status, user, signInHref, refreshMe } = useAuth();
  const [copied, setCopied] = useState(false);

  if (status === "loading") {
    return <div aria-busy className="bg-surface h-40 animate-pulse rounded-xl" />;
  }
  if (status === "suspended") {
    return <p className="text-danger">{auth("suspended")}</p>;
  }
  if (status !== "signed_in" || !user) {
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
  const joined = new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(
    new Date(user.created_at),
  );
  const copy = () => {
    void navigator.clipboard.writeText(user.steam_id).then(() => {
      setCopied(true);
      window.setTimeout(() => {
        setCopied(false);
      }, 2000);
    });
  };
  return (
    <div className="flex flex-col gap-8">
      <section className="bg-surface flex flex-wrap items-center gap-4 rounded-xl p-5">
        <UserAvatar user={user} size={64} className="rounded-xl" />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-xl font-bold">{user.display_name ?? "Steam"}</h2>
          <p className="text-fg-muted text-sm">{t("profile.joined", { date: joined })}</p>
          <p className="mt-2 flex flex-wrap items-center gap-x-2 text-sm">
            <span className="text-fg-dim whitespace-nowrap">{t("profile.steamId")}</span>
            <span className="inline-flex items-center gap-1">
              <span className="num">{user.steam_id}</span>
              <button
                type="button"
                onClick={copy}
                aria-label={t("profile.copy")}
                className="text-fg-dim hover:text-fg focus-visible:ring-accent rounded p-1 focus-visible:outline-none focus-visible:ring-2"
              >
                {copied ? (
                  <Check className="text-accent size-4" aria-hidden />
                ) : (
                  <Copy className="size-4" aria-hidden />
                )}
              </button>
            </span>
            {copied ? (
              <span role="status" className="text-accent">
                {t("profile.copied")}
              </span>
            ) : null}
          </p>
        </div>
        <a
          href={`https://steamcommunity.com/profiles/${user.steam_id}`}
          target="_blank"
          rel="noreferrer"
          className={cn(buttonVariants({ variant: "secondary", size: "md" }), "w-full sm:w-auto")}
        >
          {t("profile.steamProfile")}
          <ExternalLink className="size-4" aria-hidden />
        </a>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-fg-dim text-xs font-semibold uppercase tracking-wider">
          {t("profile.yourAccount")}
        </h2>
        <TradeLinkForm
          initial={{
            trade_link: user.trade_link,
            verdict: user.trade_link_verdict,
            reason: user.trade_link_reason,
          }}
          onChange={() => {
            void refreshMe();
          }}
        />
        <EmailForm
          email={user.email}
          verified={user.email_verified}
          sentAt={user.email_verification_sent_at ?? null}
          onChange={() => {
            void refreshMe();
          }}
        />
        <SettingsCard
          icon={Gift}
          title={t("profile.referralTitle")}
          hint={t("profile.referralHint")}
          aside={<Badge tone="neutral">{soon("badge")}</Badge>}
        />
      </section>
    </div>
  );
}
