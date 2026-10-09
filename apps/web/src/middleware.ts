import { isFilteredQuery, parseSkinQuery } from "@csmarket/utils/skins";
import { type NextRequest, NextResponse } from "next/server";
import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";
import { MARKET } from "./lib/paths";

const intl = createMiddleware(routing);

/** A locale root: `/`, `/uz`, `/en` (with or without a trailing slash) → the locale prefix. */
const ROOT = new RegExp(`^/(?:(${routing.locales.join("|")})/?)?$`);

/**
 * The catalogue used to live at the locale root; its filtered URLs (`/?category=knives`)
 * are indexed and shared. They now answer 301 to the same query on `/market`. A clean or
 * merely tracked visit (`utm_*`, `gclid`) stays on the landing.
 */
export function marketRedirect(request: NextRequest): NextResponse | null {
  const { pathname, searchParams, search } = request.nextUrl;
  const match = ROOT.exec(pathname);
  if (match === null) return null;
  if (!isFilteredQuery(parseSkinQuery(Object.fromEntries(searchParams)))) return null;
  const prefix = match[1] !== undefined && match[1] !== routing.defaultLocale ? `/${match[1]}` : "";
  const target = new URL(`${prefix}${MARKET}${search}`, request.nextUrl.origin);
  return NextResponse.redirect(target, 301);
}

export default function middleware(request: NextRequest): NextResponse {
  return marketRedirect(request) ?? intl(request);
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
