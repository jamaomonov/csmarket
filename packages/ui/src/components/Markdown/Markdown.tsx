import { type ReactElement, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { remarkSkinEmbeds } from "./remark-embeds";

/**
 * An article body (ADR-0025): Markdown with GFM tables, no raw HTML (it shows as text), links
 * only `http(s):`, `mailto:` or relative, images only from our own `/media/` path, and
 * `[[skin:<slug>]]` on a line of its own as a skin card. The page owns the H1, so `#` renders
 * as `h2`. Shared by the storefront and the admin preview, so both show the same thing.
 */
export interface MarkdownImage {
  src: string;
  alt: string;
  /** From the stored `?w=&h=` the admin writes on insert; absent on a hand-typed path. */
  width?: number;
  height?: number;
}

export interface MarkdownProps {
  source: string;
  /** Maps a stored `/media/<hash>.<ext>` path to a full URL; other image sources are dropped. */
  mediaUrl: (path: string) => string;
  /** Renders `[[skin:<slug>]]`; return null to drop it. */
  renderSkin: (slug: string) => ReactNode;
  /** The storefront passes `next/image`; a plain `img` otherwise. */
  renderImage?: (image: MarkdownImage) => ReactNode;
  className?: string;
}

const SAFE_LINK = /^(https?:|mailto:|\/|#)/i;

function dimension(params: URLSearchParams, key: string): number | undefined {
  const n = Number(params.get(key));
  return Number.isInteger(n) && n > 0 ? n : undefined;
}

export function Markdown({
  source,
  mediaUrl,
  renderSkin,
  renderImage,
  className,
}: MarkdownProps): ReactElement {
  const components: Components = {
    h1: ({ children }) => <h2>{children}</h2>,
    a: ({ href, children }) => {
      if (!href || !SAFE_LINK.test(href)) return <span>{children}</span>;
      const external = /^https?:/i.test(href);
      return external ? (
        <a href={href} rel="noopener noreferrer nofollow" target="_blank">
          {children}
        </a>
      ) : (
        <a href={href}>{children}</a>
      );
    },
    img: ({ src, alt }) => {
      if (typeof src !== "string" || !src.startsWith("/media/")) return null;
      const params = new URLSearchParams(src.split("?")[1] ?? "");
      const image: MarkdownImage = { src: mediaUrl(src), alt: alt ?? "" };
      const width = dimension(params, "w");
      const height = dimension(params, "h");
      if (width !== undefined) image.width = width;
      if (height !== undefined) image.height = height;
      if (renderImage) return <>{renderImage(image)}</>;
      return <img src={image.src} alt={image.alt} width={width} height={height} loading="lazy" />;
    },
    div: ({ node, children, ...rest }) => {
      const slug = node?.properties.dataSkin;
      if (typeof slug === "string") return <>{renderSkin(slug)}</>;
      return <div {...rest}>{children}</div>;
    },
  };
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkSkinEmbeds]} components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
