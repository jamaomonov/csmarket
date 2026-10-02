"use client";

import { Button } from "@csmarket/ui";
import { ChevronRight, Package, Wallet } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmailForm } from "./EmailForm";
import { TradeLinkForm } from "./TradeLinkForm";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { BALANCE, ORDERS } from "@/lib/paths";

const TILE =
  "border-border hover:border-border-strong flex items-center gap-3 rounded-lg border p-5 font-bold";

interface AccountViewProps {
  locale: string;
}

export function AccountView({ locale }: AccountViewProps) {
  const t = useTranslations("web.account");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const balance = useTranslations("web.balance");
  const orders = useTranslations("web.orders");
  const { status, user, signInHref, signOut, refreshMe } = useAuth();

  if (status === "loading") {
    return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
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
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-4">
        {user.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- Steam CDN avatar, 56px; next/image would need a remote-pattern allow-list for no gain
          <img src={user.avatar_url} alt="" width={56} height={56} className="rounded-full" />
        ) : null}
        <p className="text-xl font-bold">{user.display_name ?? "Steam"}</p>
      </div>
      <div className="flex flex-col gap-3">
        <Link href={BALANCE} className={TILE}>
          <Wallet aria-hidden className="text-accent h-5 w-5" />
          <span className="flex-1">{balance("title")}</span>
          <ChevronRight aria-hidden className="text-fg-dim h-5 w-5" />
        </Link>
        <Link href={ORDERS} className={TILE}>
          <Package aria-hidden className="text-accent h-5 w-5" />
          <span className="flex-1">{orders("title")}</span>
          <ChevronRight aria-hidden className="text-fg-dim h-5 w-5" />
        </Link>
      </div>
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
        onChange={() => {
          void refreshMe();
        }}
      />
      <Button
        variant="ghost"
        onClick={() => {
          void signOut();
        }}
        className="self-start"
      >
        {t("signOut")}
      </Button>
    </div>
  );
}
