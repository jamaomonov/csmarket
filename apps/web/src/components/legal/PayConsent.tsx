import { useTranslations } from "next-intl";

import type { LegalDoc } from "@/lib/legal";

import { Link } from "@/i18n/navigation";
import { legalPath } from "@/lib/paths";

/** The documents a pay or sell button binds the user to. */
type ConsentDoc = Extract<LegalDoc, "terms" | "sell">;

interface PayConsentProps {
  /** `terms` under a pay button (the public offer), `sell` under «Продать» (buyback terms). */
  doc: ConsentDoc;
}

const KEYS = { terms: "pay", sell: "sell" } as const satisfies Record<ConsentDoc, string>;

/**
 * One muted line next to a pay or sell button: pressing it accepts the linked document.
 * The link sits inside the sentence (`t.rich`), so each locale words it naturally.
 */
export function PayConsent({ doc }: PayConsentProps) {
  const t = useTranslations("web.consent");
  return (
    <p className="text-fg-dim text-xs">
      {t.rich(KEYS[doc], {
        link: (chunks) => (
          <Link href={legalPath(doc)} className="hover:text-fg underline underline-offset-2">
            {chunks}
          </Link>
        ),
      })}
    </p>
  );
}
