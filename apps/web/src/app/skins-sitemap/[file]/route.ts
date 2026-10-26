import { fetchArticleLocales, fetchArticleSitemap } from "@/lib/articles-server";
import { articlesXml } from "@/lib/articles-sitemap";
import { legalPaths } from "@/lib/legal";
import { CHEAP, HOME, itemPath, MARKET, PAY_METHODS, payPath, REVIEWS, SELL } from "@/lib/paths";
import { reviewsPublic } from "@/lib/reviews-server";
import { landingPaths } from "@/lib/skin-landing";
import { fetchSkinSlugs, getSkinFacets } from "@/lib/skins";
import { SKINS_PER_SITEMAP, today, urlsetXml, xmlResponse } from "@/lib/skins-sitemap";

/** Per request, so a build never needs the API; the upstream reads are cached for an hour. */
export const dynamic = "force-dynamic";

const notFound = (): Response => new Response("Not found", { status: 404 });

/**
 * `/skins-sitemap/<n>.xml`: item pages `n × 5000` onwards, alphabetical;
 * `/skins-sitemap/landings.xml`: the home page, /market, /cheap, the payment-method pages, /sell and
 * the category and weapon landing pages, the legal documents and /reviews while it is on;
 * `/skins-sitemap/articles.xml`: the live articles and their lists (`lib/articles-sitemap`).
 * An API outage throws (a 500 the crawler retries), it is never a 404.
 */
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ file: string }> },
): Promise<Response> {
  const { file } = await params;
  if (file === "articles.xml") {
    const [entries, sections] = await Promise.all([fetchArticleSitemap(), fetchArticleLocales()]);
    return xmlResponse(articlesXml(entries, sections));
  }
  if (file === "landings.xml") {
    const [facets, reviewsOn] = await Promise.all([getSkinFacets(), reviewsPublic()]);
    if (!facets) return notFound();
    return xmlResponse(
      urlsetXml(
        [
          HOME,
          MARKET,
          CHEAP,
          ...PAY_METHODS.map(payPath),
          SELL,
          ...landingPaths(facets),
          ...legalPaths(),
          ...(reviewsOn ? [REVIEWS] : []),
        ],
        today(),
      ),
    );
  }
  const match = /^(\d{1,3})\.xml$/.exec(file);
  if (!match) return notFound();
  const { items } = await fetchSkinSlugs(Number(match[1]) * SKINS_PER_SITEMAP, SKINS_PER_SITEMAP);
  if (items.length === 0) return notFound();
  return xmlResponse(urlsetXml(items.map(itemPath), today()));
}
