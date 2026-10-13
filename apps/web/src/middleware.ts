import { isFilteredQuery, parseSkinQuery } from "@csmarket/utils/skins";
import { type NextRequest, NextResponse } from "next/server";
import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";
import { MD_HEADER, mdTarget, prefersMarkdown } from "./lib/agent-md";
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

/** The default locale spelled out: `/ru`, `/ru/market?…`. */
const DEFAULT_PREFIX = new RegExp(`^/${routing.defaultLocale}(/.*)?$`);

/**
 * `/ru/…` answers **308** to the unprefixed URL. next-intl would send a 307, which search
 * engines read as temporary and keep the `/ru` URL around; the move is for good.
 */
export function defaultLocaleRedirect(request: NextRequest): NextResponse | null {
  const match = DEFAULT_PREFIX.exec(request.nextUrl.pathname);
  if (match === null) return null;
  const target = new URL(`${match[1] ?? "/"}${request.nextUrl.search}`, request.nextUrl.origin);
  return NextResponse.redirect(target, 308);
}

/**
 * An AI agent asking for `text/markdown` gets the page's Markdown twin (`app/md`) at the same
 * URL; everyone else the HTML. Neither is stored (`no-store`), so no cache mixes them up.
 */
export function agentMarkdown(request: NextRequest): NextResponse | null {
  const target = mdTarget(request.nextUrl.pathname);
  if (target === null || !prefersMarkdown(request.headers.get("accept"))) return null;
  const path = [target.locale, ...target.segments].map(encodeURIComponent).join("/");
  const headers = new Headers(request.headers);
  headers.set(MD_HEADER, "1");
  return NextResponse.rewrite(new URL(`/md/${path}`, request.nextUrl.origin), {
    request: { headers },
  });
}

export default function middleware(request: NextRequest): NextResponse {
  const redirect = defaultLocaleRedirect(request) ?? marketRedirect(request);
  if (redirect) return redirect;
  const md = agentMarkdown(request);
  if (md) return md;
  return intl(request);
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
