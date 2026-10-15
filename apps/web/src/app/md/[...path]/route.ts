import { headers } from "next/headers";

import { MD_HEADER, mdResponse, mdTarget } from "@/lib/agent-md";
import {
  categoryMd,
  colorMd,
  homeMd,
  itemMd,
  marketMd,
  sellMd,
  weaponMd,
} from "@/lib/agent-md-pages";

/** Per request: prices move; a build never needs the API. */
export const dynamic = "force-dynamic";

const notFound = (): Response => new Response("Not found\n", { status: 404 });

/**
 * The Markdown twin of a page, reached only through the middleware's rewrite of a request that
 * asks for `text/markdown` (`lib/agent-md.ts`); `/md/…` opened directly is a 404, so it never
 * shows up as a second copy of a page. The path is the page's own: `/md/<locale>/<path>`.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  if ((await headers()).get(MD_HEADER) !== "1") return notFound();
  const { path } = await params;
  const target = mdTarget(`/${path.join("/")}`);
  if (target === null) return notFound();
  const { locale, segments } = target;
  const [kind, slug] = segments;
  let body: string | null;
  switch (kind) {
    case undefined:
      body = await homeMd(locale);
      break;
    case "market":
      body = await marketMd(locale);
      break;
    case "sell":
      body = await sellMd(locale);
      break;
    case "category":
      body = slug === undefined ? null : await categoryMd(locale, slug);
      break;
    case "weapon":
      body = slug === undefined ? null : await weaponMd(locale, slug);
      break;
    case "color":
      body = slug === undefined ? null : await colorMd(locale, slug);
      break;
    case "item":
      body = slug === undefined ? null : await itemMd(locale, slug);
      break;
    default:
      body = null;
  }
  return body === null ? notFound() : mdResponse(body);
}
