# Articles

News, guides and top lists written in the admin's «Статьи» (spec `2026-10-26-articles-design.md`,
ADR-0025).

## Write and publish

1. «Статьи» → «Новая статья». Choose the section, the address (`top-budget-knives`: latin
   lowercase, digits, dashes) and upload a cover.
2. Fill a language tab: title (≤ 120), description (≤ 200, it is the Google snippet), the cover's
   caption, the text. «Картинка в текст» (or paste / drop a picture) puts an image at the caret;
   «Скин» finds a catalogue item and puts its live card on a line of its own.
3. Tick «Перевод готов» for each finished language, «Сохранить», then «Опубликовать». Only
   ready languages appear on the site; the others answer 404. The site shows edits within a
   minute (60 s cache).
4. «Статьи» appears in the header and footer of a language once it has a live article; the
   article lands in `/skins-sitemap/articles.xml`.

## Change the address

Allowed at any time. Once an article has been published, every old address answers a 301 to the
new one, forever; an old address can never be given to another article.

## Take an article down

«Снять с публикации»: it leaves the site at once (404), keeps its date, views and likes, and can
be published again. Articles are never deleted.

## A wrong or unwanted image

Images are stored once per content and their URL never changes. Replace it in the text (upload a
new one, delete the old line) and save. The old file stays reachable by its URL until removed from
`article_media` by hand — ask the owner before deleting anything on the server.

## Likes and views look wrong

Views count one per visitor per day and need Redis; with Redis down they simply stop counting.
Likes are one per signed-in account or per browser (`csm_aid` cookie); clearing cookies allows
another like — accepted by design (spec, «Calls»).
