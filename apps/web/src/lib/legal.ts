import type { AbstractIntlMessages } from "next-intl";

import { LEGAL, legalPath } from "@/lib/paths";

/**
 * The published legal documents, in the order a reader should meet them: the offer that
 * governs a purchase, the agreement that governs use of the site, the terms of selling skins
 * to us, then privacy, refunds and who the seller is.
 *
 * One list with three consumers — the index page, the per-document route's
 * `generateStaticParams` and the sitemap — so a document cannot ship to one and miss another.
 * Each slug is a key in the `legal` namespace (`packages/i18n/locales/<locale>/legal.json`)
 * holding `title`, `intro`, `updated` and `sections` (`{h, p}[]`).
 */
export const LEGAL_DOCS = ["terms", "agreement", "sell", "privacy", "refunds", "imprint"] as const;

export type LegalDoc = (typeof LEGAL_DOCS)[number];

export function isLegalDoc(value: string): value is LegalDoc {
  return (LEGAL_DOCS as readonly string[]).includes(value);
}

/** The index and every document, locale-less, for the sitemap. */
export function legalPaths(): string[] {
  return [LEGAL, ...LEGAL_DOCS.map(legalPath)];
}

/** The namespace of the documents' texts. */
export const LEGAL_NAMESPACE = "legal";

/**
 * The catalogue without the legal texts, for `NextIntlClientProvider`: the documents render
 * on the server only, so the tens of kilobytes of their text never ride every page's payload.
 */
export function clientMessages(messages: AbstractIntlMessages): AbstractIntlMessages {
  return Object.fromEntries(Object.entries(messages).filter(([ns]) => ns !== LEGAL_NAMESPACE));
}
