"use client";

import { buttonVariants } from "@csmarket/ui";
import { CalendarDays, Check, Copy, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { UserAvatar } from "./UserAvatar";

interface ProfileHeroProps {
  user: {
    steam_id: string;
    display_name: string | null;
    avatar_url: string | null;
    created_at: string;
  };
  locale: string;
}

/** Who you are: avatar, name, since when, Steam ID (copyable) and the Steam profile. */
export function ProfileHero({ user, locale }: ProfileHeroProps) {
  const t = useTranslations("web.account.profile");
  const [copied, setCopied] = useState(false);
  const joined = new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
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
    <section className="bg-surface border-border rounded-xl border">
      <div className="flex flex-col gap-5 p-5 sm:p-6 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-4">
          <UserAvatar user={user} size={64} className="rounded-full" />
          <div className="min-w-0 pb-0.5">
            <h2 className="text-h3 truncate font-semibold leading-tight tracking-tight">
              {user.display_name ?? "Steam"}
            </h2>
            <p className="text-fg-muted mt-1 flex items-start gap-1.5 text-sm">
              <CalendarDays className="text-fg-dim mt-0.5 size-4 shrink-0" aria-hidden />
              <span>{t("joined", { date: joined })}</span>
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="border-border bg-bg/50 flex h-10 items-center gap-2 rounded-lg border pl-3 pr-1">
            {copied ? (
              <span role="status" className="text-accent text-xs font-semibold">
                {t("copied")}
              </span>
            ) : (
              <span className="text-fg-dim text-xs font-semibold">{t("steamId")}</span>
            )}
            <span className="num flex-1 text-sm">{user.steam_id}</span>
            <button
              type="button"
              onClick={copy}
              aria-label={t("copy")}
              className="text-fg-muted hover:bg-surface-2 hover:text-fg focus-visible:ring-accent grid size-8 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2"
            >
              {copied ? (
                <Check className="text-accent size-4" aria-hidden />
              ) : (
                <Copy className="size-4" aria-hidden />
              )}
            </button>
          </div>
          <a
            href={`https://steamcommunity.com/profiles/${user.steam_id}`}
            target="_blank"
            rel="noreferrer"
            className={buttonVariants({ variant: "secondary", size: "md" })}
          >
            {t("steamProfile")}
            <ExternalLink className="size-4" aria-hidden />
          </a>
        </div>
      </div>
    </section>
  );
}
