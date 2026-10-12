import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";

import type { SkinDetail } from "@csmarket/utils/skins";

import { routing } from "@/i18n/routing";
import { ogFonts, ogSkinImage } from "@/lib/og-assets";
import { itemOgModel } from "@/lib/og-item";
import { itemOgResponse } from "@/lib/og-render";
import { apiGetOrNull } from "@/lib/server-api";
import { isSkinCategory } from "@/lib/skin-landing";

/**
 * `/<locale>/item/<slug>/og.png`: the item page's generated share card (1200×630). Per
 * request, so a build never needs the API; the item is data-cached for a day and the PNG
 * itself is cached at the edge (`OG_CACHE_CONTROL`). The `.png` keeps the path out of the
 * locale middleware, so `/ru/…` answers as is. The page itself stays as it was.
 */
export const dynamic = "force-dynamic";

const ITEM_TTL = 86_400;

const notFound = (): Response => new Response("Not found", { status: 404 });

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ locale: string; slug: string }> },
): Promise<Response> {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) return notFound();
  let item: SkinDetail | null;
  try {
    item = await apiGetOrNull<SkinDetail>(`/skins/${encodeURIComponent(slug)}`, {
      revalidate: ITEM_TTL,
    });
  } catch {
    // The API is down: the site's generic card for now, not cached.
    return new Response(null, {
      status: 302,
      headers: { Location: `/og/${locale}.jpg`, "Cache-Control": "no-store" },
    });
  }
  if (!item) return notFound();
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const model = itemOgModel(item, {
    vanilla: t("vanilla"),
    category: isSkinCategory(item.category) ? t(`category.${item.category}`) : null,
    exterior: (e) => t(`exterior.${e}`),
  });
  const [fonts, image] = await Promise.all([ogFonts(), ogSkinImage(item.image_url)]);
  return itemOgResponse(model, image, fonts);
}
