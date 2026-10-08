"use client";

import { buttonVariants, LogoMark } from "@csmarket/ui";
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

/** The banner: two soft glows over a fine grid that fades out, and the brand mark as a watermark. */
function Banner() {
  return (
    <div aria-hidden className="relative h-28 overflow-hidden sm:h-36">
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(70% 140% at 0% 0%, rgb(75 243 100 / 0.20), transparent 60%), " +
            "radial-gradient(60% 160% at 100% 0%, rgb(93 178 255 / 0.14), transparent 60%), " +
            "linear-gradient(135deg, #1b2335 0%, #161d2c 100%)",
        }}
      />
      <div
        className="absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            "linear-gradient(rgb(255 255 255 / 0.05) 1px, transparent 1px), " +
            "linear-gradient(90deg, rgb(255 255 255 / 0.05) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
          maskImage: "linear-gradient(180deg, black 0%, transparent 95%)",
        }}
      />
      <LogoMark className="text-accent/[0.06] absolute -right-8 -top-8 size-52 -rotate-6 sm:right-12" />
      <div className="from-surface absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t to-transparent" />
    </div>
  );
}

/** Who you are: banner, avatar, name, since when, Steam ID (copyable) and the Steam profile. */
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
    <section className="bg-surface overflow-hidden rounded-xl">
      <Banner />
      <div className="relative flex flex-col gap-5 px-4 pb-5 sm:px-6 md:flex-row md:items-end md:justify-between">
        <div className="flex min-w-0 items-end gap-4">
          <UserAvatar
            user={user}
            size={88}
            className="ring-surface -mt-12 rounded-full ring-4 sm:-mt-14"
          />
          <div className="min-w-0 pb-0.5">
            <h2 className="truncate text-[22px] font-bold leading-tight sm:text-[26px]">
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
