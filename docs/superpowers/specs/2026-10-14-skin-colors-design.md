# Skin colours: a colour filter and colour landings

Approved in conversation with the owner on 2026-10-14. Builds the idea parked in
`docs/product/color-filter-later.md`. Decision on the new dependency: ADR-0019.

## Goal

Players look for skins by colour («красные скины кс2», «синие скины на AK-47»). The market gets a
colour filter like cs.money's, and each colour gets an indexable landing.

## Owner rulings

1. **Twelve broad groups**, each holding all its shades (the owner's picture, 2026-10-14):

   | Key      | RU         | Holds                                       |
   | -------- | ---------- | ------------------------------------------- |
   | `blue`   | Синий      | blue, light blue, sky, sapphire, cyan, teal |
   | `brown`  | Коричневый | brown, chocolate, copper                    |
   | `green`  | Зелёный    | green, lime, olive, emerald                 |
   | `orange` | Оранжевый  | orange, carrot, coral                       |
   | `grey`   | Серый      | grey, silver, graphite                      |
   | `pink`   | Розовый    | pink, raspberry, fuchsia                    |
   | `red`    | Красный    | red, maroon, scarlet, cherry                |
   | `yellow` | Жёлтый     | yellow, gold, lemon, mustard                |
   | `purple` | Фиолетовый | purple, lilac, violet                       |
   | `black`  | Чёрный     | black, very dark tones                      |
   | `beige`  | Бежевый    | beige, sand, khaki, ivory                   |
   | `white`  | Белый      | white, cream                                |

2. Teal goes to blue.
3. A skin has one or two colours.
4. Swatches in the filter look like the owner's picture: a two-tone circle where the group
   spans shades.

## How a colour is found

`modules/skins/colors.py`, pure: the Steam picture shrunk to 96 px, its transparent background
dropped, each pixel put in a group by hue, saturation and brightness. Once at least 12 % of the
item is coloured, grey and black (the weapon's metal and shadows) stop counting and white counts
only from 25 %. The first group is named; a second only if it holds ≥ 18 % of the counted pixels
and ≥ 35 % of the first. A skin without real colour gets its neutrals.

Wears of one skin share one picture in ByMykel, so the job works per distinct `image_url`.

## Data

`skin_items` gets:

- `colors text[]` (GIN index) — the one or two keys, `{}` until computed;
- `colors_image text` — the `image_url` they were computed from (a new picture is read again);
- `colors_manual boolean` default false — the admin set them; the job never overwrites.

## Job

`skins.colors` in the scheduler, every 5 minutes, first run 420 s after start: up to 300
distinct pictures whose rows have `colors_image` ≠ `image_url` and are not manual, fetched from
the Steam CDN (6 s timeout, 4 at a time), computed, written to every row with that picture. A
picture that fails to load is skipped and tried next tick. The first backfill is a few hours.

## API

- `GET /skins/catalog?color=red,blue` — any of the named colours (at most 3, unknown → 422).
- `GET /skins/facets` — `colors: [{value, count}]` in the fixed order above, scoped like the
  other facets.
- `PUT /admin/skins/items/{id}/colors {colors: [...] | null}` — set by hand (1–2 keys) or
  `null` to give it back to the job; audited.

## Storefront

- Filters: «Цвет» with twelve swatches, several at once, counts in the tooltip; `color` in
  `SkinQuery` and the URL.
- Landings `/color/<key>` («Красные скины КС2 (CS2)», `uz` / `en` too): the popular items of
  that colour, intro with live numbers, links to the other colours, FAQ; in `landings.xml`;
  noindex under 10 items like the other landings.
- Item page: the colours as a fact with links to their landings.

## Out of scope

Weapon × colour pages (later, after the colour landings show traffic); recomputing on a
schedule (only new pictures are read).

## Testing

Unit: `classify` on reference pixels per group, `pick` on histograms (metal ignored, white on
colour, neutrals only, a weak second colour dropped), `colors_of` on synthetic images.
Integration: the job writes colours per picture and skips manual rows; the `color` filter and
facets; the admin override and its audit. Web: the filter writes `color` to the URL, the landing
renders and is noindex when thin.

## Quality check

Before the filter is shown: the 102 most popular skins reviewed by the owner on a contact sheet,
the buckets tuned from the review.
