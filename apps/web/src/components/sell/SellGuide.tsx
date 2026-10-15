import { CreditCard, Wallet } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { SkinFaq } from "@/components/skins/SkinFaq";
import { Link } from "@/i18n/navigation";
import { legalPath } from "@/lib/paths";
import { sellFaq } from "@/lib/sell-seo";

/**
 * «Как продать скины КС2 (CS2) в Узбекистане», under the sale app and rendered on the server
 * for everyone — what a search engine or an assistant reads on `/sell`, where a visitor's app
 * shows only the sign-in: the steps, where the money goes and
 * the questions people ask, as FAQPage JSON-LD. Only what the buy-back terms say, and no
 * percents or fees (owner, 2026-10-15): assistants quote this page; the sale form shows them.
 */
export async function SellGuide({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.sell.guide" });
  const steps = t.raw("steps") as string[]; // a string array in every locale (the parity test)
  return (
    <section aria-labelledby="sell-guide" className="mt-14 max-w-4xl">
      <h2 id="sell-guide" className="text-h3 font-semibold tracking-tight">
        {t("title")}
      </h2>
      <ol className="mt-5 grid gap-3 sm:grid-cols-2">
        {steps.map((step, i) => (
          <li
            key={step}
            className="bg-surface border-border text-body flex gap-3 rounded-xl border p-4"
          >
            <span className="bg-surface-2 text-fg text-small grid size-7 shrink-0 place-items-center rounded-full font-semibold">
              {i + 1}
            </span>
            <span className="text-fg-muted">{step}</span>
          </li>
        ))}
      </ol>

      <h3 className="text-title mt-10 font-semibold">{t("payoutTitle")}</h3>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <p className="bg-surface border-border text-body text-fg-muted flex gap-3 rounded-xl border p-4">
          <Wallet className="text-fg mt-0.5 size-5 shrink-0" aria-hidden />
          <span>{t("balancePlain")}</span>
        </p>
        <p className="bg-surface border-border text-body text-fg-muted flex gap-3 rounded-xl border p-4">
          <CreditCard className="text-fg mt-0.5 size-5 shrink-0" aria-hidden />
          <span>{t("cardPlain")}</span>
        </p>
      </div>
      <p className="text-small mt-4">
        <Link
          href={legalPath("sell")}
          className="text-fg-muted hover:text-fg underline underline-offset-2"
        >
          {t("terms")}
        </Link>
      </p>

      <SkinFaq title={t("faqTitle")} entries={sellFaq(t.raw("faq"))} />
    </section>
  );
}
