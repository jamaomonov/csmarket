# scripts/i18n/port-skins-copy.py — one-off; kept so the provenance is visible.
"""Copy YuPay's browse-only web.skins strings into csmarket's catalogs (M2 Task 12)."""
import json
import re
import sys
from pathlib import Path

YUPAY = Path("/Users/macbook_uz/Projects/yupay/packages/i18n/locales")
HERE = Path("packages/i18n/locales")
TOP = ["title", "searchPlaceholder", "filters", "price", "from", "to", "reset", "wear", "rarity",
       "stattrak", "sortLabel", "sort", "all", "category", "exterior", "soldOut", "loadMore",
       "loading", "empty", "fromPrice", "steamPrice", "offers", "inspect", "seed", "float",
       "stickers", "market", "otherWears", "noOffers", "vanilla", "resetFilters", "done",
       "inStock", "pieces", "close", "belowSteam", "landing", "team"]
FAQ = ["title", "priceQ", "priceA", "steamQ", "steamA", "floatQ", "floatA"]
META = ["title", "description", "itemTitle", "itemTitleNoPrice", "itemDescription", "itemDescriptionNoPrice"]


def fix_uz(text: str) -> str:
    # oʻ/gʻ take U+02BB; any other letter-apostrophe-letter is the tutuq belgisi U+02BC.
    text = re.sub(r"([oOgG])['’ʼ]", "\\1ʻ", text)
    return re.sub(r"(?<=\w)['’](?=\w)", "ʼ", text)


def walk(value, fn):
    if isinstance(value, dict):
        return {k: walk(v, fn) for k, v in value.items()}
    return fn(value) if isinstance(value, str) else value


for loc in ("ru", "uz", "en"):
    src = json.loads((YUPAY / loc / "web.json").read_text("utf-8"))["skins"]
    out = {"meta": {k: src["meta"][k] for k in META}, **{k: src[k] for k in TOP},
           "faq": {k: src["faq"][k] for k in FAQ}}
    out = walk(out, lambda s: s.replace("YuPay", "csmarket").replace("yupay", "csmarket"))
    if loc == "uz":
        out = walk(out, fix_uz)
    dst_path = HERE / loc / "web.json"
    dst = json.loads(dst_path.read_text("utf-8"))
    dst["skins"] = out
    dst_path.write_text(json.dumps(dst, ensure_ascii=False, indent=2) + "\n", "utf-8")
    assert "yupay" not in json.dumps(out).lower(), loc
print("ok", file=sys.stderr)
