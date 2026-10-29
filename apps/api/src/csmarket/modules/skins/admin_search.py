"""The admin's skin search: every typed word, in any order, best match and most stock first.

The storefront ranks by trigram similarity alone; the operator types fragments («redline mw»,
«karambit phase 2», a pasted market name with ``|`` and ``★``) and wants the one item. Each
word, folded like ``skin_items.search_text`` and expanded by the search aliases, must appear;
an exterior or StatTrak abbreviation also matches its long form.
"""

from __future__ import annotations

from sqlalchemy import Select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.service import expand_aliases

#: Short forms operators type, matched as well as the words they stand for.
ABBREVIATIONS = {
    "fn": "factory new",
    "mw": "minimal wear",
    "ft": "field tested",
    "ww": "well worn",
    "bs": "battle scarred",
    "st": "stattrak",
}


def _like(text: str) -> ColumnElement[bool]:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return SkinItem.search_text.ilike(f"%{escaped}%", escape="\\")


def _word(word: str) -> ColumnElement[bool]:
    long = ABBREVIATIONS.get(word)
    return _like(word) if long is None else or_(_like(word), _like(long))


async def match(db: AsyncSession, stmt: Select[SkinItem], q: str) -> Select[SkinItem] | None:
    """``stmt`` narrowed to ``q`` and ordered best first; ``None`` when ``q`` folds to nothing."""
    needle = await expand_aliases(db, q)
    words = needle.split()
    if not words:
        return None
    stock = SkinItem.count_auto + SkinItem.skinslink_count + SkinItem.lisskins_count
    return stmt.where(and_(*(_word(w) for w in words))).order_by(
        func.similarity(SkinItem.search_text, needle).desc(), stock.desc(), SkinItem.slug
    )


__all__ = ["ABBREVIATIONS", "match"]
