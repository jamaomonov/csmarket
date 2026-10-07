import { Badge, buttonVariants } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import type { NavIcon } from "@/components/header/nav";

import { Link } from "@/i18n/navigation";
import { HOME } from "@/lib/paths";

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
      <span className="bg-accent-subtle text-accent grid size-16 place-items-center rounded-2xl">
        <Icon className="size-8" aria-hidden />
      </span>
      <Badge>{t("badge")}</Badge>
      <h1 className="text-2xl font-bold">{nav(section)}</h1>
      <p className="text-fg-muted">{t("text")}</p>
      <Link href={HOME} className={buttonVariants({ size: "md" })}>
        {t("toMarket")}
      </Link>
    </main>
  );
}
