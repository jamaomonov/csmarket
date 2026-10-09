"use client";

import { useTranslations } from "next-intl";

import { ApiKeyCard } from "./ApiKeyCard";
import { CardsList } from "./CardsList";
import { EmailForm } from "./EmailForm";
import { ProfileHero } from "./ProfileHero";
import { ProfileSetup, ReferralTeaser, type SetupStep } from "./ProfileSetup";
import { SettingsPanel } from "./SettingsCard";
import { TradeLinkForm } from "./TradeLinkForm";

import { useAuth } from "@/lib/auth";

interface ProfileViewProps {
  locale: string;
}

/**
 * «Профиль»: the hero (who you are), the settings in panels («Steam», «Ваш аккаунт») and, on the
 * side, what is left to set and the referral programme to come.
 */
export function ProfileView({ locale }: ProfileViewProps) {
  const t = useTranslations("web.account");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref, refreshMe } = useAuth();

  if (status === "loading") {
    return (
      <div aria-busy className="flex flex-col gap-6">
        <div className="bg-surface h-56 animate-pulse rounded-xl" />
        <div className="bg-surface h-40 animate-pulse rounded-xl" />
      </div>
    );
  }
  if (status === "suspended") {
    return <p className="text-danger">{auth("suspended")}</p>;
  }
  if (status !== "signed_in" || !user) {
    return (
      <div className="bg-surface flex flex-col items-start gap-4 rounded-xl p-6">
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
  const linkWorks =
    user.trade_link !== null &&
    user.trade_link_verdict !== "bad" &&
    user.trade_link_verdict !== "warn";
  const steps: SetupStep[] = [
    { key: "steam", done: true },
    { key: "tradeLink", done: linkWorks, href: "#trade-link" },
    { key: "email", done: user.email !== null && user.email_verified, href: "#email" },
  ];
  const refresh = () => {
    void refreshMe();
  };
  return (
    <div className="flex flex-col gap-6">
      <ProfileHero user={user} locale={locale} />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-6">
          <SettingsPanel title={t("profile.groupSteam")}>
            <div id="trade-link" className="scroll-mt-24">
              <TradeLinkForm
                collapseEmpty
                initial={{
                  trade_link: user.trade_link,
                  verdict: user.trade_link_verdict,
                  reason: user.trade_link_reason,
                }}
                onChange={refresh}
              />
            </div>
          </SettingsPanel>
          <SettingsPanel title={t("profile.yourAccount")}>
            <div id="email" className="scroll-mt-24">
              <EmailForm
                email={user.email}
                verified={user.email_verified}
                sentAt={user.email_verification_sent_at ?? null}
                onChange={refresh}
              />
            </div>
            <div className="border-border border-t">
              <CardsList locale={locale} />
            </div>
          </SettingsPanel>
          <SettingsPanel title={t("profile.groupDeveloper")}>
            <ApiKeyCard locale={locale} />
          </SettingsPanel>
        </div>
        <aside className="flex flex-col gap-6 lg:sticky lg:top-24">
          <ProfileSetup steps={steps} />
          <ReferralTeaser />
        </aside>
      </div>
    </div>
  );
}
