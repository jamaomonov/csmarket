"use client";

import { Badge, buttonVariants, cn } from "@csmarket/ui";
import { Check, Copy, ExternalLink, Gift } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { CardsList } from "./CardsList";
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
      <section className="bg-surface overflow-hidden rounded-2xl">
        {/* The banner: a dotted field lit by the accent, as a backdrop for the avatar. */}
        <div
          aria-hidden
          className="h-24 sm:h-32"
          style={{
            backgroundImage:
              "radial-gradient(rgb(255 255 255 / 0.09) 1px, transparent 1.2px), " +
              "radial-gradient(120% 140% at 0% 0%, rgb(75 243 100 / 0.16), transparent 55%), " +
              "linear-gradient(180deg, #232b3e, #1d2434)",
            backgroundSize: "14px 14px, auto, auto",
          }}
        />
        <div className="flex flex-col gap-4 px-5 pb-5 sm:flex-row sm:items-end sm:justify-between sm:px-6">
          <div className="flex min-w-0 items-end gap-4">
            <UserAvatar
              user={user}
              size={88}
              className="ring-surface -mt-12 rounded-full ring-4 sm:-mt-14"
            />
            <div className="min-w-0 pb-1">
              <h2 className="truncate text-2xl font-bold">{user.display_name ?? "Steam"}</h2>
              <p className="text-fg-muted text-sm">{t("profile.joined", { date: joined })}</p>
            </div>
          </div>
          <div className="flex flex-col gap-3 sm:items-end">
            <p className="flex flex-wrap items-center gap-x-2 text-sm">
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
            <a
              href={`https://steamcommunity.com/profiles/${user.steam_id}`}
              target="_blank"
              rel="noreferrer"
              className={cn(
                buttonVariants({ variant: "secondary", size: "md" }),
                "w-full sm:w-auto",
              )}
            >
              {t("profile.steamProfile")}
              <ExternalLink className="size-4" aria-hidden />
            </a>
          </div>
        </div>
      </section>

      <section className="flex flex-col">
        <h2 className="text-fg-dim text-xs font-semibold uppercase tracking-wider">
          {t("profile.groupSteam")}
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
      </section>

      <section className="flex flex-col">
        <h2 className="text-fg-dim text-xs font-semibold uppercase tracking-wider">
          {t("profile.yourAccount")}
        </h2>
        <EmailForm
          email={user.email}
          verified={user.email_verified}
          sentAt={user.email_verification_sent_at ?? null}
          onChange={() => {
            void refreshMe();
          }}
        />
        <CardsList locale={locale} />
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
