"use client";

import { Dropdown, type DropdownLinkProps } from "@csmarket/ui";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { ACCOUNT, BALANCE, ORDERS } from "@/lib/paths";

/** next-intl's locale-aware Link, shaped for `Dropdown`. */
export function AppLink({ href, children, ...rest }: DropdownLinkProps) {
  return (
    <Link href={href} {...rest}>
      {children}
    </Link>
  );
}

export function AccountMenu() {
  const t = useTranslations("web.nav");
  const { user, signOut } = useAuth();
  if (!user) return null;
  return (
    <Dropdown
      align="end"
      LinkComponent={AppLink}
      triggerClassName="py-1.5 pl-1.5"
      label={
        <>
          {user.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- Steam CDN avatars; next/image would need remotePatterns per CDN host
            <img src={user.avatar_url} alt="" width={28} height={28} className="rounded-md" />
          ) : (
            <span aria-hidden className="bg-accent/30 size-7 rounded-md" />
          )}
          <span className="max-w-[120px] truncate">{user.display_name ?? t("account")}</span>
          <ChevronDown className="text-fg-dim size-4" aria-hidden />
        </>
      }
      items={[
        { key: "profile", label: t("profile"), href: ACCOUNT },
        { key: "orders", label: t("orders"), href: ORDERS },
        { key: "balance", label: t("balance"), href: BALANCE },
        { key: "sep", separator: true },
        { key: "out", label: t("signOut"), tone: "danger", onSelect: () => void signOut() },
      ]}
    />
  );
}
