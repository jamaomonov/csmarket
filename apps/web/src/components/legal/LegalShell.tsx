import { ChevronRight } from "lucide-react";
import { getTranslations } from "next-intl/server";

import type { ReactNode } from "react";

import { Link } from "@/i18n/navigation";
import { HOME, LEGAL } from "@/lib/paths";

interface Props {
  locale: string;
  title: string;
  /** «Обновлено: …» under the heading; the index has none. */
  updated?: string;
  intro: string;
  /** The document's own crumb; absent on the index itself. */
  isDoc: boolean;
  children: ReactNode;
}

/**
 * The frame of a legal page: breadcrumbs (Главная › Документы › the document), the heading,
 * the date of the version and the lead paragraph. A reading column, not the catalogue's width.
 */
export async function LegalShell({ locale, title, updated, intro, isDoc, children }: Props) {
  const t = await getTranslations({ locale, namespace: "legal" });
  return (
    <main id="main-content" className="mx-auto max-w-[760px] px-4 pb-28 pt-6 sm:px-6">
      <nav
        aria-label={t("breadcrumb")}
        className="text-fg-dim text-small mb-4 flex flex-wrap items-center gap-1"
      >
        <Link href={HOME} className="hover:text-fg">
          {t("home")}
        </Link>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        {isDoc ? (
          <>
            <Link href={LEGAL} className="hover:text-fg">
              {t("index.title")}
            </Link>
            <ChevronRight className="h-3.5 w-3.5" aria-hidden />
            <span aria-current="page" className="text-fg-muted">
              {title}
            </span>
          </>
        ) : (
          <span aria-current="page" className="text-fg-muted">
            {title}
          </span>
        )}
      </nav>
      <h1 className="text-2xl font-bold md:text-3xl">{title}</h1>
      {updated !== undefined && (
        <p className="text-fg-dim text-label mt-2">
          {t("updatedLabel")} {updated}
        </p>
      )}
      <p className="text-fg-muted text-lead mt-4 leading-relaxed">{intro}</p>
      {children}
    </main>
  );
}
