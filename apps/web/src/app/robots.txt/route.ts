/**
 * robots.txt as a route handler (not the typed `robots.ts` metadata file) so we
 * can emit Content-Signal directives — a preference declaration the typed
 * MetadataRoute.Robots API can't express.
 *
 * Content-Signal (contentsignals.org): search=yes and ai-input=yes welcome our
 * catalog into search and into live AI answers (ChatGPT, Perplexity, AI
 * Overviews) — that's the goal. ai-train=no reserves model-training rights: it
 * isn't needed to be cited in answers, bakes stale prices into weights, and is
 * irreversible. Flip ai-train to yes here if that stance ever changes.
 *
 * The catalogue is open to search engines from the M2 deploy (owner decision D2).
 */
import { SITE } from "@/lib/site";

const CONTENT_SIGNAL = "Content-Signal: search=yes, ai-input=yes, ai-train=no";

/** AI assistant / answer-engine crawlers we explicitly welcome to the public
 *  site (never /api, the account or the sign-in callback), so csmarket can be
 *  surfaced and cited. */
const AI_CRAWLERS = [
  "GPTBot",
  "OAI-SearchBot",
  "ChatGPT-User",
  "ClaudeBot",
  "anthropic-ai",
  "Claude-User",
  "Claude-SearchBot",
  "PerplexityBot",
  "Perplexity-User",
  "Google-Extended",
  "Applebot-Extended",
  "CCBot",
  "cohere-ai",
  "Amazonbot",
  "Meta-ExternalAgent",
];

/**
 * Never fetched by a crawler: the API, the signed-in account and the Steam sign-in
 * callback (which carries a one-time token in its query string). The `/*` twins cover
 * the locale prefixes (`/en/account`, `/uz/auth/…`) — ru has none.
 */
const DISALLOW = ["/api/", "/account", "/*/account", "/auth/", "/*/auth/"];

/** One robots.txt group: its user-agent lines, access rules, and content signal. */
function group(agents: string[]): string {
  return [
    ...agents.map((a) => `User-Agent: ${a}`),
    "Allow: /",
    ...DISALLOW.map((d) => `Disallow: ${d}`),
    CONTENT_SIGNAL,
  ].join("\n");
}

/** Per request, like the sitemaps it names. */
export const dynamic = "force-dynamic";

export function GET(): Response {
  const body = [
    group(["*"]),
    "",
    group(AI_CRAWLERS),
    "",
    `Host: ${SITE}`,
    `Sitemap: ${SITE}/sitemap.xml`,
    "",
  ].join("\n");

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
