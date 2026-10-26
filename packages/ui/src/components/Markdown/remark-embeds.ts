/**
 * A remark plugin: a paragraph that is exactly `[[skin:<slug>]]` becomes an empty `div` with
 * `data-skin="<slug>"`, which {@link Markdown} renders through its `renderSkin`. Inline mentions
 * stay text, so only a line of its own embeds a card.
 */
const EMBED = /^\[\[skin:([a-z0-9-]+)\]\]$/;

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, string> };
}

function walk(node: MdNode): void {
  for (const child of node.children ?? []) {
    const only =
      child.type === "paragraph" && child.children?.length === 1 ? child.children[0] : null;
    const match = only?.type === "text" ? EMBED.exec(only.value?.trim() ?? "") : null;
    if (match?.[1]) {
      child.children = [];
      child.data = { hName: "div", hProperties: { dataSkin: match[1] } };
    } else {
      walk(child);
    }
  }
}

export function remarkSkinEmbeds() {
  return (tree: MdNode): void => {
    walk(tree);
  };
}
