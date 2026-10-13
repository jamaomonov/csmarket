/**
 * Markdown for AI agents: content negotiation and the small writing helpers. An agent that
 * asks for `text/markdown` over `text/html` gets the page's Markdown twin (`app/md`); browsers
 * and search crawlers never do. The Markdown says what the HTML says, from the same data.
 */
import { routing } from "@/i18n/routing";

/** The header the middleware sets on its rewrite; `app/md` answers 404 without it. */
export const MD_HEADER = "x-csmarket-md";

/** The `q` of each media range in an `Accept` header (missing `q` = 1). */
function weights(accept: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const part of accept.split(",")) {
    const [type = "", ...params] = part.trim().toLowerCase().split(";");
    const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
    const value = q === undefined ? 1 : Number(q.slice(2));
    if (type) out.set(type, Number.isFinite(value) ? value : 0);
  }
  return out;
}

/**
 * Whether the client asks for Markdown before HTML: `text/markdown` named with a weight above
 * zero and above `text/html`'s. A wildcard never counts — browsers send `*\/*`.
 */
export function prefersMarkdown(accept: string | null): boolean {
  if (!accept) return false;
  const w = weights(accept);
  const md = w.get("text/markdown") ?? 0;
  return md > 0 && md > (w.get("text/html") ?? 0);
}

export interface MdTarget {
  locale: string;
  /** The locale-less path segments (`["item", "ak-47-…"]`; `[]` for the home page). */
  segments: string[];
}

const KINDS = new Set(["market", "category", "weapon", "item"]);

/** The page a path names, when it has a Markdown twin; `null` otherwise. */
export function mdTarget(pathname: string): MdTarget | null {
  const parts = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const first = parts[0];
  const prefixed = first !== undefined && (routing.locales as readonly string[]).includes(first);
  const locale = prefixed ? first : routing.defaultLocale;
  const segments = prefixed ? parts.slice(1) : parts;
  const [kind, slug, ...rest] = segments;
  if (rest.length > 0) return null;
  if (kind === undefined) return { locale, segments };
  if (!KINDS.has(kind)) return null;
  if (kind === "market" ? slug !== undefined : slug === undefined) return null;
  return { locale, segments };
}

/** Text with Markdown's link and emphasis characters escaped. */
export function mdText(text: string): string {
  return text.replace(/([\\`*_[\]<>])/g, "\\$1");
}

export function mdLink(text: string, url: string): string {
  return `[${mdText(text)}](${url})`;
}

/** Blocks joined by a blank line, empty ones dropped, ending with a newline. */
export function mdDoc(blocks: (string | null | false | undefined)[]): string {
  return `${blocks.filter((b): b is string => typeof b === "string" && b !== "").join("\n\n")}\n`;
}

export function mdFaq(title: string, entries: { question: string; answer: string }[]): string {
  if (entries.length === 0) return "";
  return mdDoc([
    `## ${mdText(title)}`,
    ...entries.map((e) => `### ${mdText(e.question)}\n\n${mdText(e.answer)}`),
  ]).trimEnd();
}

export function mdResponse(body: string): Response {
  return new Response(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      Vary: "Accept",
      // Like the HTML: never stored, so no cache can hand one version to the other client.
      "Cache-Control": "no-store",
      // The HTML page is the one to index; this is its twin for agents.
      "X-Robots-Tag": "noindex",
    },
  });
}
