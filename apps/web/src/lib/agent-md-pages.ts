/**
 * The Markdown twins of the indexable pages (spec: the owner's «Markdown for agents», 2026-10-13):
 * the home page, the market, a category, a weapon and an item. Each reads the same helpers its
 * HTML page reads; `null` means the page would answer 404.
 */
import { hasWear, parseSkinQuery, type SkinItem } from "@csmarket/utils/skins";
import { getTranslations } from "next-intl/server";

import { mdDoc, mdFaq, mdLink, mdText } from "@/lib/agent-md";
import {
  categoryContent,
  colorContent,
  type LandingContent,
  loadCategory,
  loadColor,
  loadWeapon,
  weaponContent,
} from "@/lib/landing-content";
import {
  categoryPath,
  CHEAP,
  colorPath,
  itemPath,
  MARKET,
  PAY_METHODS,
  PAY_NAMES,
  payPath,
  weaponPath,
} from "@/lib/paths";
import { localeUrl } from "@/lib/seo";
import { isSkinColor } from "@/lib/skin-colors";
import { isSkinCategory, weaponSlug } from "@/lib/skin-landing";
import { skinAbout, skinFaq, skinFullName } from "@/lib/skin-seo";
import { displayPrice, getSkinDetail, getSkinFacets, getSkinsPage } from "@/lib/skins";

function itemLine(locale: string, item: SkinItem, fromLabel: (price: string) => string): string {
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  const link = mdLink(skinFullName(item), localeUrl(locale, itemPath(item.slug)));
  return price ? `- ${link} — ${mdText(fromLabel(price))}` : `- ${link}`;
}

async function itemList(locale: string, items: SkinItem[]): Promise<string> {
  const t = await getTranslations({ locale, namespace: "web.skins" });
  return items.map((i) => itemLine(locale, i, (price) => t("fromPrice", { price }))).join("\n");
}

function landingMd(
  locale: string,
  c: LandingContent,
  faqTitle: string,
  allLabel: string,
  list: string,
): string {
  const crumbs = c.crumbs
    .slice(0, -1)
    .map((cr) => mdLink(cr.name, localeUrl(locale, cr.path)))
    .join(" › ");
  return mdDoc([
    crumbs,
    `# ${mdText(c.h1)}`,
    c.intro && mdText(c.intro),
    list,
    mdLink(allLabel, localeUrl(locale, c.allHref)),
    c.text && mdText(c.text),
    c.links &&
      c.links.items.length > 0 &&
      `## ${mdText(c.links.title)}\n\n${c.links.items
        .map((l) => `- ${mdLink(l.label, localeUrl(locale, l.path))} (${String(l.count)})`)
        .join("\n")}`,
    mdFaq(faqTitle, c.faq),
  ]);
}

export async function categoryMd(locale: string, category: string): Promise<string | null> {
  const data = await loadCategory(locale, category);
  if (!data) return null;
  const c = await categoryContent(locale, data);
  const t = await getTranslations({ locale, namespace: "web.skins" });
  return landingMd(locale, c, t("faq.title"), t("landing.all"), await itemList(locale, c.items));
}

export async function weaponMd(locale: string, slug: string): Promise<string | null> {
  const data = await loadWeapon(locale, slug);
  if (!data) return null;
  const c = await weaponContent(locale, data);
  const t = await getTranslations({ locale, namespace: "web.skins" });
  return landingMd(locale, c, t("faq.title"), t("landing.all"), await itemList(locale, c.items));
}

export async function colorMd(locale: string, color: string): Promise<string | null> {
  const data = await loadColor(locale, color);
  if (!data) return null;
  const c = await colorContent(locale, data);
  const t = await getTranslations({ locale, namespace: "web.skins" });
  return landingMd(locale, c, t("faq.title"), t("landing.all"), await itemList(locale, c.items));
}

export async function itemMd(locale: string, slug: string): Promise<string | null> {
  const item = await getSkinDetail(slug);
  if (!item) return null;
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const category = isSkinCategory(item.category) ? t(`category.${item.category}`) : item.category;
  const parent = item.weapon
    ? { label: item.weapon, path: weaponPath(weaponSlug(item.weapon)) }
    : { label: category, path: categoryPath(item.category) };
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  const worn = hasWear(item.category);
  const facts = [
    item.exterior && `- ${t("wear")}: ${t(`exterior.${item.exterior}`)}`,
    item.rarity && `- ${t("rarity")}: ${mdText(item.rarity)}`,
    worn &&
      item.min_float !== null &&
      item.max_float !== null &&
      `- ${t("float")}: ${Number(item.min_float).toFixed(2)}–${Number(item.max_float).toFixed(2)}`,
    item.collection && `- ${t("collection")}: ${mdText(item.collection)}`,
    (item.colors ?? []).length > 0 &&
      `- ${t("color.item")}: ${(item.colors ?? [])
        .filter(isSkinColor)
        .map((c) => mdLink(t(`color.names.${c}`), localeUrl(locale, colorPath(c))))
        .join(", ")}`,
    item.crates.length > 0 &&
      `- ${t("cases")}: ${item.crates.map((c) => mdText(c.name)).join(", ")}`,
  ].filter((f): f is string => typeof f === "string");
  const stock =
    item.count > 0 ? `${t("inStock")}: ${t("pieces", { count: item.count })}` : t("soldOut");
  const wears =
    worn && item.family.length > 1
      ? `## ${t("otherWears")}\n\n${item.family
          .filter((m) => m.slug !== item.slug && m.exterior)
          .map((m) => {
            const p = displayPrice(locale, m.price_uzs, m.price_usd);
            const label = `${m.stattrak ? "StatTrak™ " : ""}${m.souvenir ? "Souvenir " : ""}${m.exterior ? t(`exterior.${m.exterior}`) : ""}`;
            const link = mdLink(label, localeUrl(locale, itemPath(m.slug)));
            return p ? `- ${link} — ${mdText(t("fromPrice", { price: p }))}` : `- ${link}`;
          })
          .join("\n")}`
      : null;
  return mdDoc([
    `${mdLink(t("market"), localeUrl(locale, MARKET))} › ${mdLink(parent.label, localeUrl(locale, parent.path))}`,
    `# ${mdText(skinFullName(item))}`,
    [price && mdText(t("fromPrice", { price })), stock].filter(Boolean).join(" · "),
    facts.join("\n"),
    wears,
    `## ${t("about.title")}\n\n${mdText(skinAbout(item, t, locale, category))}`,
    locale === "en" && item.description && `> ${mdText(item.description).replace(/\n/g, "\n> ")}`,
    mdFaq(t("faq.title"), skinFaq(item, t, locale)),
    localeUrl(locale, itemPath(item.slug)),
  ]);
}

export async function marketMd(locale: string): Promise<string> {
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const [page, facets] = await Promise.all([
    getSkinsPage(parseSkinQuery({}), true),
    getSkinFacets(undefined, true),
  ]);
  const cats = (facets?.categories ?? []).filter((c) => c.count > 0 && isSkinCategory(c.value));
  return mdDoc([
    `# ${mdText(t("title"))}`,
    mdText(t("meta.description")),
    cats.length > 0 &&
      cats
        .map(
          (c) =>
            `- ${mdLink(t(`category.${c.value}`), localeUrl(locale, categoryPath(c.value)))} (${String(c.count)})`,
        )
        .join("\n"),
    await itemList(locale, page.items),
  ]);
}

interface FaqItem {
  q: string;
  a: string;
}

interface AboutBlock {
  h: string;
  p: string;
}

export async function homeMd(locale: string): Promise<string> {
  const t = await getTranslations({ locale, namespace: "web.landing" });
  const tCat = await getTranslations({ locale, namespace: "web.skins.category" });
  const tBuy = await getTranslations({ locale, namespace: "web.seoPages.footer" });
  const facets = await getSkinFacets();
  const cats = (facets?.categories ?? []).filter((c) => c.count > 0 && isSkinCategory(c.value));
  // `raw` reads the arrays as written in the catalogue (`landing.faq.items`, `about.blocks`).
  const faq = t.raw("faq.items") as FaqItem[]; // the catalogue's shape, checked by the i18n parity test
  const about = t.raw("about.blocks") as AboutBlock[]; // same
  return mdDoc([
    `# ${mdText(t("about.title"))}`,
    mdText(t("about.intro")),
    `- ${mdLink(t("openMarket"), localeUrl(locale, MARKET))}\n${cats
      .map(
        (c) =>
          `- ${mdLink(tCat(c.value), localeUrl(locale, categoryPath(c.value)))} (${String(c.count)})`,
      )
      .join("\n")}`,
    `## ${mdText(tBuy("title"))}\n\n${[
      ...PAY_METHODS.map(
        (m) => `- ${mdLink(tBuy("pay", { method: PAY_NAMES[m] }), localeUrl(locale, payPath(m)))}`,
      ),
      `- ${mdLink(tBuy("cheap"), localeUrl(locale, CHEAP))}`,
    ].join("\n")}`,
    ...about.map((b) => `## ${mdText(b.h)}\n\n${mdText(b.p)}`),
    mdFaq(
      t("faq.title"),
      faq.map((f) => ({ question: f.q, answer: f.a })),
    ),
  ]);
}
