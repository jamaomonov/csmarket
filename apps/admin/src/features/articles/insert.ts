/** Text the editor's toolbar puts into an article's Markdown. */
import type { Media } from "./api";

export interface Inserted {
  text: string;
  /** Where the caret goes after the insert. */
  caret: number;
}

/**
 * `snippet` at `pos`. A block (a skin card) stands on a line of its own with a blank line around
 * it, which is what makes `[[skin:…]]` an embed and not text.
 */
export function insertAt(text: string, pos: number, snippet: string, block: boolean): Inserted {
  const before = text.slice(0, pos);
  const after = text.slice(pos);
  if (!block) return { text: before + snippet + after, caret: pos + snippet.length };
  const lead =
    before === "" || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  const head = `${before}${lead}${snippet}\n\n`;
  return { text: head + after.replace(/^\n+/, ""), caret: head.length };
}

/** An image line; `?w=&h=` lets the storefront reserve its space (ADR-0025). */
export function imageMarkdown(media: Media): string {
  return `![](${media.url}?w=${String(media.width)}&h=${String(media.height)})`;
}
