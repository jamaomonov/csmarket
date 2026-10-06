"use client";

import { Dropdown, type DropdownLinkProps } from "@csmarket/ui";
import { ChevronDown, LogOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { ACCOUNT_NAV } from "./nav";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";

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
        ...ACCOUNT_NAV.map((entry) => ({
          key: entry.key,
          label: t(entry.key),
          href: entry.href,
          icon: <entry.icon className="text-fg-dim size-4 shrink-0" aria-hidden />,
        })),
        { key: "sep", separator: true },
        {
          key: "out",
          label: t("signOut"),
          tone: "danger",
          icon: <LogOut className="size-4 shrink-0" aria-hidden />,
          onSelect: () => void signOut(),
        },
      ]}
    />
  );
}
