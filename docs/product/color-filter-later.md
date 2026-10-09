# Filter by skin colour — parked idea (2026-10-10)

> Not planned. On 2026-10-10 the owner asked to keep it as a feature for later.
> This note keeps the design discussed in chat, so it does not have to be discussed again.

## Why

Players search by colour: «красные скины кс2», «белые скины на AK-47». cs.money has colour
filters. ByMykel has no palette: its `rarity.color` is the rarity, not the skin's own colours.
So we would compute the colour ourselves.

## Design

1. **Compute once per picture** in a background job after the import, not on the request path.
   - Fetch the Steam CDN image at a small size (~128×96) and drop the transparent background.
   - Bucket the pixels in HSV into 12–13 named colours: red, orange, yellow, green, teal, blue,
     purple, pink, brown, gold, black, white, grey.
   - The trap is the weapon's grey metal. When at least ~15 % of pixels are coloured, ignore
     the grey ones (AK-47 | Redline is red, not grey). Black, white and grey are given only to
     colourless skins.
   - Store the top one or two colours with a share above ~20 % in a new `skin_items.colors`
     column with a GIN index.
   - The first backfill is ~20 000 pictures, throttled for the Steam CDN. After it, only new or
     changed pictures are processed.
   - It needs Pillow, a new dependency, so an ADR comes first.
2. **API:**
   - `color=<name>` on the catalogue;
   - colour counts in the facets;
   - an admin override per item when the algorithm gets one wrong.
3. **Storefront:**
   - colour swatches in the market's filters;
   - landings `/color/<name>` («Красные скины КС2 (CS2)») in ru / uz / en, added to the sitemap;
   - later, weapon × colour pages.
4. **Quality check before launch:** run it on ~100 popular skins and review the result by eye.
   Tune the buckets, e.g. so that gold does not land in yellow.

**Open question:** keep the full set, or a shorter 9–10 colours like cs.money (no brown, teal,
gold)?

**Effort:** about a day.
