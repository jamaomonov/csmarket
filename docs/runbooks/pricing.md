# Runbook — Prices (the admin pricing editor)

The sell price of every item is `pricing.quote` over the item's cost (the cheapest Waxpeer
auto listing) and the **pricing document**: expenses %, margin brackets, liquidity bands,
category and weapon markups, minimum margin, floor price, soʻm rounding, the Steam cap, the
cheap tail. The admin page «Цены» edits it (M4b, ADR-0008 R8).

**The cheap tail** (ADR-0015) applies to items whose cost is under «Хвост: себестоимость до, $»
(1 $). For them, a sticker gets «Хвост: наклейки, п.п.» (2) instead of its category markup
(5), and an item with under 4 lots gets «Хвост: мало лотов, п.п.» (1) instead of +3. Every
other band and category is unchanged. Clear the bound to switch the tail off. Code: `skins.pricing_admin`,
`skins/README.md` «Pricing editor».

## Before saving: preview

«Проверить цену» prices a real item (search by name) or a made-up one (cost + category)
under the rules **as they stand in the form**, unsaved changes included, and shows every
component and «как посчитано» (formula / ручная цена / мин. маржа / не дороже Steam / нижняя
цена). It writes nothing. Check two or three items across the price range before saving.

## What a save does

«Сохранить» → «Сохранить и пересчитать цены всех скинов?» → one transaction: the advisory
pricing lock (the 5-minute price sync waits for it), the document, every active item
repriced, an audit row `skins.pricing.save {items_repriced}`. Only after the commit is the
document published to Redis (`skins:pricing`) and the catalogue cache version bumped, so
every public page shows the new prices at once. A failure before the commit changes
nothing anywhere. A refused document (brackets not ascending from $0, liquidity bands not
descending to 0, a number out of range) is explained in Russian; nothing is saved.

## One item

«Цена одного скина»: a margin override (п.п., −100…500, added on top of the rules) or a
pinned price ($, honoured only while it covers cost + minimum margin). «Сбросить ручную
цену» clears both. It reprices that item only; audit `skins.item.override`. «Только с ручной
ценой» lists every item with an override.

## Rolling back

Every save is in the audit log («Журнал», action `skins.pricing.save`) with who and when,
but the document itself is not stored there. To roll back, re-enter the previous numbers
and save; for a large change, copy the current document first:
`curl -H "Authorization: Bearer …" https://api.csmarket.uz/api/v1/admin/skins/pricing`
(keep the `rules` object), then `PUT` it back with a fresh `Idempotency-Key` if needed.

## Watch afterwards

The dashboard's margin over the next hours, and the competitor comparison the owner keeps
(date every comparison; never claim «всегда дешевле»).
