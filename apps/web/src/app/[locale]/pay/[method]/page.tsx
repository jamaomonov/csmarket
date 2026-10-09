import { skinQueryString } from "@csmarket/utils/skins";
import Image from "next/image";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { Link } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { getPopular } from "@/lib/landing";
import { MARKET, PAY_METHODS, PAY_NAMES, type PayMethod, payPath } from "@/lib/paths";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS, shareImage } from "@/lib/seo";

interface Props {
  params: Promise<{ locale: string; method: string }>;
}

/*
 * «Купить скины КС2 через Click / Payme / Uzum»: a landing per payment method for the queries
 * people type with the app's name. Real 404 for any other method, before anything streams.
 */

function method(locale: string, raw: string): PayMethod {
  if (!hasLocale(routing.locales, locale)) notFound();
  const m = PAY_METHODS.find((p) => p === raw);
  if (m === undefined) notFound();
  return m;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, method: raw } = await params;
  const m = method(locale, raw);
  const t = await getTranslations({ locale, namespace: "web.seoPages.pay" });
  const title = t("title", { method: PAY_NAMES[m] });
  const description = t("description", { method: PAY_NAMES[m] });
  const path = payPath(m);
  return {
    title,
    description,
    alternates: alternates(locale, path),
    robots: ROBOTS,
    other: GEO_META,
    openGraph: {
      type: "website",
      siteName: "csmarket",
      title,
      description,
      url: localeUrl(locale, path),
      ...ogLocale(locale),
      images: shareImage(locale, title).openGraph,
    },
    twitter: shareImage(locale, title).twitter,
  };
}

interface FaqItem {
  q: string;
  a: string;
}

export default async function PayPage({ params }: Props) {
  const { locale, method: raw } = await params;
  const m = method(locale, raw);
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "web.seoPages.pay" });
  const tSkins = await getTranslations({ locale, namespace: "web.skins" });
  const name = PAY_NAMES[m];
  const query = { sort: "popular" as const };
  // The landing's mix (rifles, knives, gloves, pistols, SMGs), not the raw top of keys and cases.
  const items = await getPopular("popular");
  // The catalogue's own array; `{method}` is filled here, the same text on the page and in the LD.
  const faq = (t.raw("faq") as FaqItem[]).map((f) => ({
    question: f.q.replaceAll("{method}", name),
    answer: f.a.replaceAll("{method}", name),
  }));
  const steps = [t("s1"), t("s2"), t("s3", { method: name }), t("s4")];
  return (
    <SkinLanding
      locale={locale}
      h1={t("h1", { method: name })}
      intro={t("intro", { method: name })}
      items={items}
      allHref={MARKET + skinQueryString(query)}
      crumbs={[
        { name: tSkins("market"), path: MARKET },
        { name: t("crumb", { method: name }), path: payPath(m) },
      ]}
      faq={{ title: tSkins("faq.title"), entries: faq }}
      before={
        <section className="mt-6" aria-labelledby="pay-steps">
          <h2 id="pay-steps" className="mb-3 flex items-center gap-2.5 text-[17px] font-bold">
            <Image src={`/pay/${m}.png`} alt="" width={28} height={28} className="rounded-md" />
            {t("stepsTitle", { method: name })}
          </h2>
          <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((s, i) => (
              <li
                key={s}
                className="border-border bg-surface flex items-start gap-3 rounded-xl border p-3.5 text-[14px]"
              >
                <span className="bg-accent/15 text-accent flex size-7 shrink-0 items-center justify-center rounded-full text-[13px] font-bold">
                  {i + 1}
                </span>
                {s}
              </li>
            ))}
          </ol>
        </section>
      }
      after={
        <nav className="mt-8" aria-label={t("other")}>
          <h2 className="mb-3 text-[17px] font-bold">{t("other")}</h2>
          <ul className="flex flex-wrap gap-2">
            {PAY_METHODS.filter((p) => p !== m).map((p) => (
              <li key={p}>
                <Link
                  href={payPath(p)}
                  className="border-border hover:border-border-strong inline-flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3.5 text-[13px] font-semibold"
                >
                  <Image src={`/pay/${p}.png`} alt="" width={22} height={22} className="rounded" />
                  {t("crumb", { method: PAY_NAMES[p] })}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      }
    />
  );
}
