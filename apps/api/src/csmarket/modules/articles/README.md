# `articles`

News, guides and top lists («Новости», «Гайды», «Подборки») the owner writes in the admin, in
ru / uz / en (spec `docs/superpowers/specs/2026-10-26-articles-design.md`, ADR-0025).

## Owns

- `articles` — section, slug (one for every language), cover, `draft` / `published`, the first
  publication date, the counters `views` and `likes`.
- `article_translations` — title, description, cover alt and Markdown body per locale; _live_
  when the article is published and the translation is ready with a title and a body. A locale
  without a live translation answers 404.
- `article_slugs_old` — former slugs of a published article; each 301s to the current slug.
- `article_media` — uploaded images (JPEG / PNG / WebP ≤ 5 MB), bytes in the row like payout
  receipts (ADR-0024), served immutable at `/api/v1/media/<sha256>.<ext>`.
- `article_likes` — one like per signed-in user or per anonymous `csm_aid` cookie.

## Talks to

- `skins.api.item_cards` — the live cards behind `[[skin:<slug>]]` embeds.
- `auth.api` — `optional_user` for likes, `guard_ip` (bucket `article-like`).
- `admin.api` — `require_admin`, idempotent replay, audit rows `articles.*`.

## Not here

- Rendering Markdown: `@csmarket/ui` `Markdown`, shared by the storefront and the admin preview.
- No IP is stored: views are deduplicated in Redis by a daily-salted hash
  (`docs/architecture/cache-keys.md`).
