/**
 * Pre-launch: nothing is indexed. M2 replaces this with the real policy
 * (Allow + Content-Signal + sitemap index) when the catalogue opens.
 */
export const dynamic = "force-static";

export function GET(): Response {
  return new Response("User-Agent: *\nDisallow: /\n", {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
