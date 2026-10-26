# 0025. Articles: Markdown rendering and media

- **Status**: Accepted
- **Date**: 2026-10-26
- **Deciders**: owner
- **Tags**: frontend | backend | data

## Context and problem statement

The owner writes news, guides and top lists in the admin, in ru / uz / en, with a cover and
pictures in the text and live skin cards (spec `2026-10-26-articles-design.md`). The text must
render the same in the admin preview and on the storefront, never carry a script onto a page,
and its images must be served fast and cached. The project renders no user-authored rich text yet
and has no Markdown library.

## Decision drivers

- No raw HTML reaches a page: an article is admin-written, but a pasted snippet must not run.
- One renderer for the storefront (React Server Components) and the admin (Vite SPA).
- Images survive the server and need no new infrastructure.

## Considered options

1. **`react-markdown` + `remark-gfm`** in `@csmarket/ui`.
2. **`markdown-it` + a sanitizer** (DOMPurify / sanitize-html), rendering an HTML string.
3. **MDX.**
4. Media: **bytes in Postgres** (as receipts, ADR-0024) vs **R2** with public links.

## Decision outcome

**Chosen:** 1, and media in Postgres.

- `react-markdown` builds React elements from the syntax tree and never parses HTML without
  `rehype-raw`: raw HTML cannot become markup, so no sanitizer to configure. It renders in a
  server component and in the browser alike. `remark-gfm` adds tables and strikethrough.
- Our own remark plugin turns a line that is exactly `[[skin:<slug>]]` into a card the caller
  renders (`renderSkin`); the API resolves those slugs in the same request (`embeds`).
- Images: only `/media/<sha256>.<ext>` paths render; anything else is dropped. The admin writes
  `?w=&h=` into the path on insert so the storefront's `next/image` reserves the space.
- Media rows live in `article_media` (bytes `deferred`), served at
  `/api/v1/media/<hash>.<ext>` with `Cache-Control: public, max-age=31536000, immutable`; the name
  is the content hash, so a URL never changes what it shows and Cloudflare keeps it.
- The storefront reads articles with a 60 s revalidate (tag `articles`) instead of an on-demand
  hook from the API: an edit shows within a minute and no internal webhook is needed.

### Positive consequences

- No HTML sanitising code of our own; the preview is the page.
- Images are in the nightly backup with the article that uses them.

### Negative consequences

- Two new dependencies in `@csmarket/ui` (`react-markdown`, `remark-gfm`) and their unified
  sub-tree in both apps.
- The database and backups grow by the images; a few hundred KB each. Move them to R2 if it
  ever matters; the URL shape need not change.
- An image removed from every article stays reachable by its URL until deleted by hand.

## Validation

`packages/ui/src/components/Markdown/Markdown.test.tsx` (no script, unsafe URLs dropped, embeds
only on their own line), `test_articles_media.py` (types, size, immutable headers).
