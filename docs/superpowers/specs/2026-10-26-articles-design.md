# Articles: news, guides and top lists

Agreed in conversation with the owner on 2026-10-26.

## Goal

Rank for the queries a two-week-old shop cannot reach with its catalogue alone («где купить скины
кс2 в узбекистане», «топ бюджетных ножей», «тир-лист AK-47») and turn that reader into a buyer.
The owner writes and edits articles in the admin himself, in ru / uz / en, without a deploy.
Search Console on 2026-10-26: brand and long-tail item queries already rank; generic
commercial ones show no impressions at all.

Non-goals: comments, scheduled publishing, multiple named authors, a WYSIWYG editor, raw HTML in
articles. Anti-goal: a page that leaks a script, a PII-bearing log line, or a thin page that
Google indexes as a duplicate.

## Owner rulings

1. **Three sections:** «Новости» (`news`: CS2 updates, the market), «Гайды» (`guides`),
   «Подборки» (`tops`: «топ бюджетных ножей», «лучшие красные скины», tier lists).
2. **One article, up to three translations** (ru / uz / en). Switching the site language shows
   the same article in that language. A translation the admin has not written answers **404**.
3. **A cover image and images inside the text.**
4. **Draft → published**, and «Снять с публикации». No scheduling.
5. **Views and likes**, shown on the site. **Anyone may like**, sign-in is optional.

## Calls made by the agent (owner may overrule)

- **One slug for all languages**, Latin, lowercase, `[a-z0-9-]{3,80}`:
  `/articles/top-budget-knives`, `/uz/articles/top-budget-knives`, `/en/...`.
- On an article without a translation in the target language, the **language switcher** links to
  that language's article list instead of a 404; the URL itself still 404s.
- **Markdown, no raw HTML** (HTML in the source is rendered as text): no script can reach a page.
  Headings `##`–`###`, lists, bold / italic, links, quotes, tables, images, and two embeds:
  - `[[skin:<item-slug>]]` on its own line → a card from our catalogue: image, name, the live
    «от N сум» price, a link to the item page; an unknown or delisted slug renders nothing on the
    site (and a warning in the admin preview);
  - images as `![alt](/media/<hash>.webp)`, only our own media URLs (any other host is dropped).
- **Author** is «Редакция csmarket» (`Organization` in JSON-LD); no person names.
- **No deleting** an article: only unpublishing. The slug stays editable after publishing; every
  change of a published article's slug stores the old one in `article_slugs_old` → the article id,
  so any former slug 301s straight to the current one (no chains). A slug is unique across
  `articles.slug` and `article_slugs_old`: a former slug is never reused by another article. The
  editor warns «старый адрес будет перенаправлять на новый» when the article has been published.
- **Views** count real readers: a beacon sent by the browser after the article renders (bots that
  do not run JS do not count), at most once per article per visitor per UTC day, deduplicated in
  Redis by `sha256(daily_salt + ip + article_id)` with a TTL to the end of the day. The IP itself
  is never stored or logged; the salt lives only in Redis and rotates daily.
- **Likes**: a toggle. A signed-in user's like is keyed by `user_id`; an anonymous one by a random
  `csm_aid` cookie (UUID, `HttpOnly`, `SameSite=Lax`, 1 year, set by the API on the first like).
  One like per key per article; a second press removes it. Anti-abuse: an `ip_guard` bucket
  `article-like`, 30 per IP per hour. Clearing cookies allows another like — accepted as the
  price of anonymous likes.
- Counters are denormalised on the article row: a counted view is a direct
  `UPDATE articles SET views = views + 1` (traffic is small; no buffer, no flush job); a like or
  unlike updates `likes` in the same transaction as the `article_likes` row.
- **Empty lists:** a section or a whole language with no live article is `noindex`, left out of
  the sitemap, and its tab is hidden; the «Статьи» link in the header and footer shows only in a
  locale with at least one live article.
- **An anonymous like stays anonymous** when its visitor later signs in (no merge): `liked` is read
  by `user_id` when signed in, else by the cookie. A person may thus like once anonymously and once
  signed in — accepted.

## Data (`modules/articles`)

`articles`:

| Column                      | Meaning                                                  |
| --------------------------- | -------------------------------------------------------- |
| `id` PK                     |                                                          |
| `section`                   | `news` / `guides` / `tops`                               |
| `slug`                      | unique                                                   |
| `cover_media_id`            | FK `article_media`, nullable while a draft               |
| `status`                    | `draft` / `published`                                    |
| `published_at`              | first publication; set once, shown as the article's date |
| `updated_at`                | last edit of a published translation (shown «обновлено») |
| `views` / `likes`           | counters                                                 |
| `created_by` / `updated_by` | admin users                                              |
| `created_at`                |                                                          |

`article_translations` (PK `article_id, locale`): `title` (≤ 120), `description` (≤ 200, the
meta description and the list teaser), `body` (Markdown, ≤ 60 000 chars), `ready` (bool),
`updated_at`. A translation is **live** when the article is `published` and the translation is
`ready` with a non-empty title and body.

`article_slugs_old` (`slug` PK → `article_id`): former slugs for the 301.

`article_media`: `id`, `hash` (sha256 of the bytes, unique — the same file uploaded twice is one
row), `content_type`, `width`, `height`, `size`, `data` (deferred `LargeBinary`), `uploaded_by`,
`created_at`. JPEG / PNG / WebP by magic bytes, ≤ 5 MB, the same reading as payout receipts
(ADR-0024). Every image needs an alt text, which lives in the Markdown (`![alt](…)`) and, for
the cover, in each translation as `cover_alt` (≤ 160).

`article_likes` (unique `article_id, user_id` and `article_id, anon_id`; exactly one of the two).

Indices: `(status, section, published_at desc)`, `article_likes(article_id)`.

## API

Public (no auth; cached):

| Route                                    | What                                                                               |
| ---------------------------------------- | ---------------------------------------------------------------------------------- |
| `GET /articles?locale=&section=&cursor=` | live articles in that locale, newest first, 12 a page                              |
| `GET /articles/{slug}?locale=`           | one live translation + `locales` that are live; 404 else; 301 body for an old slug |
| `GET /media/{hash}.{ext}`                | the image; `Cache-Control: public, max-age=31536000, immutable`                    |
| `POST /articles/{slug}/view`             | the beacon; keyless (writes only a counter, documented)                            |
| `PUT` / `DELETE /articles/{slug}/like`   | like / unlike; idempotent by nature (state, not delta)                             |

The article response carries the skin embeds resolved server-side (`embeds: {slug: card}`) so the
page renders in one request, the counters, and `liked` for the caller.

Admin (`admin` role, `Idempotency-Key` on writes, audit rows `articles.*`):

| Route                                                        | What                                                              |
| ------------------------------------------------------------ | ----------------------------------------------------------------- |
| `GET /admin/articles?section=&status=`                       | list with views, likes, live locales                              |
| `POST /admin/articles`, `GET` / `PATCH /admin/articles/{id}` | create, read, edit (section, slug, cover, translations)           |
| `POST /admin/articles/{id}/publish` / `unpublish`            | publish needs ≥ 1 ready translation and a cover                   |
| `POST /admin/articles/media`                                 | raw-body upload as receipts; returns `{hash, url, width, height}` |
| `GET /admin/skins?q=` (existing, `search_items`)             | catalogue search for the embed picker                             |

Caddy: the media upload path gets the same 6 MB `request_body` exception as receipts.
`/media/*` on `csmarket.uz` proxies to the API (or the web app proxies it) so images are
same-origin and cached by Cloudflare.

## Storefront (`apps/web`)

- `/[locale]/articles` (all), `/[locale]/articles/news|guides|tops` — tabs, cards (cover, title,
  teaser, date, views, likes), cursor pagination as plain links (indexable pages `?page=` are a
  later concern, as for categories).
- `/[locale]/articles/[slug]` — cover (`next/image`, sizes for phone and desktop), H1, date and
  «обновлено», views, the body, skin cards with a «Купить» link, the like button, «Ещё в разделе»
  (3 newest in the same section). 404 via `notFound()` for a missing translation (non-streaming,
  real 404 status as AGENTS.md §4 requires).
- SEO: `<title>` and description from the translation; canonical to itself; `hreflang` only for
  live translations (+ `x-default` to ru when ru is live); JSON-LD `Article` (headline, image,
  datePublished, dateModified, author/publisher Organization); `BreadcrumbList`.
- Sitemap: every live translation with `lastmod`; section pages too.
- «Статьи» in the header and the footer, in all three locales.
- ISR: article and list pages revalidate on publish / edit (on-demand revalidation called by the
  API after a write, falling back to a 5-minute `revalidate`). Counters and `liked` load client-side
  so the page itself stays cacheable.

## Admin (`apps/admin`, «Статьи»)

- List: title (ru, else the first live), section, status, live locales as chips, views, likes,
  dates; filters by section and status.
- Editor: section, slug, cover (upload, preview, per-language alt), three tabs ru / uz / en, each
  with title, description (with a character counter and a Google-snippet preview), the Markdown
  body with a side-by-side preview (the same renderer as the site), «Перевод готов».
  Toolbar: insert image (upload or drop / paste into the body), insert skin (catalogue search),
  heading, list, link. Unsaved changes are kept as a local draft in the browser and warned on
  leave.
- «Опубликовать» / «Снять с публикации» with a confirm; a published article's edits go live on
  save.

## Rendering

One Markdown renderer shared by the site and the admin preview (a new dependency — ADR-0025 to
choose it; `react-markdown` + `remark-gfm` with HTML disabled is the expected pick). The skin
embed and the image rules are a small remark plugin in the shared package.

## Docs and tests

- ADR-0025 (renderer + media storage reuse), module `README.md`, `module-map.md`,
  `pii-handling.md` (anonymous like cookie, the hashed-IP view dedup), `cache-keys.md` (view
  dedup and salt keys), runbook `articles.md` (publishing, unpublishing, a bad image).
- `articles` joins the ≥ 95 % module coverage list.
- Tests: translations and 404s, slug change and 301 from every former slug, publish rules, sanitising (HTML as text, foreign
  image hosts dropped, `javascript:` links dropped), embeds of a delisted skin, view dedup, like
  toggle for user and anonymous, the IP bucket, media upload limits and type sniffing, sitemap and
  hreflang only for live translations.

## Left to the builder

Component structure, the exact remark plugin, how on-demand revalidation is authenticated (a
shared secret header like the storefront secret), the admin toolbar's look, pagination size.
