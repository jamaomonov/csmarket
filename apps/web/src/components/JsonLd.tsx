import { serializeJsonLd } from "@csmarket/utils/skins";

/**
 * Injects a JSON-LD <script> into the page. Server component — the payload is
 * serialised at render time. Keep payloads small and defensible (no invented
 * ratings) so structured data stays trustworthy. Serialisation escapes `<` so
 * API-sourced strings (item names, FAQ answers) cannot close the tag.
 */
export function JsonLd({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
