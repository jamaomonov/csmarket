import { Badge, buttonVariants } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import type { NavIcon } from "@/components/header/nav";

import { Link } from "@/i18n/navigation";
import { MARKET } from "@/lib/paths";

interface ComingSoonProps {
  /** The section's key under `web.nav`. */
  section: "sell" | "steamTopup" | "reviews" | "referral";
  icon: NavIcon;
}

/** A section that is on its way: its name, «Скоро» and the way back to the market. */
export function ComingSoon({ section, icon: Icon }: ComingSoonProps) {
  const nav = useTranslations("web.nav");
  const t = useTranslations("web.soon");
  return (
    <main
      id="main-content"
      className="mx-auto flex max-w-md flex-col items-center gap-4 px-6 py-20 text-center"
    >
      <span className="bg-surface border-border text-fg-muted grid size-16 place-items-center rounded-2xl border">
        <Icon className="size-8" aria-hidden />
      </span>
      <Badge tone="neutral">{t("badge")}</Badge>
      <h1 className="text-h2 font-semibold tracking-tight">{nav(section)}</h1>
      <p className="text-fg-muted">{t("text")}</p>
      <Link href={MARKET} className={buttonVariants({ size: "md" })}>
        {t("toMarket")}
      </Link>
    </main>
  );
}
