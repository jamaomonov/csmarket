import { fetchSkinSlugs } from "@/lib/skins";
import { chunkCount, chunkUrl, sitemapIndexXml, today, xmlResponse } from "@/lib/skins-sitemap";

/** Per request, so a build never needs the API; the upstream read is cached for an hour. */
export const dynamic = "force-dynamic";

/** The sitemap index: one file per 5000 items, and the landing pages. */
export async function GET(): Promise<Response> {
  const { total } = await fetchSkinSlugs(0, 1);
  const files = Array.from({ length: chunkCount(total) }, (_, n) => chunkUrl(String(n)));
  return xmlResponse(sitemapIndexXml([...files, chunkUrl("landings")], today()));
}
