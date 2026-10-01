"""The CI guard against YuPay-specific tokens leaking into csmarket source (spec §4.3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "check-no-yupay.sh"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(root)], capture_output=True, text=True, check=False
    )


def _plant(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def clean_tree(tmp_path: Path) -> Path:
    _plant(tmp_path, "apps/api/src/csmarket/core/config.py", "class Settings:\n    pass\n")
    _plant(tmp_path, "apps/web/src/lib/site.ts", 'export const SITE = "https://csmarket.uz";\n')
    _plant(tmp_path, "packages/i18n/src/index.ts", 'export const LOCALES = ["ru", "uz", "en"];\n')
    return tmp_path


def test_a_clean_tree_passes(clean_tree: Path) -> None:
    result = _run(clean_tree)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_token_in_a_comment_fails_case_insensitively(clean_tree: Path) -> None:
    _plant(clean_tree, "apps/api/src/csmarket/x.py", "# ported from YuPay, see there\n")
    result = _run(clean_tree)
    assert result.returncode == 1
    assert "apps/api/src/csmarket/x.py:1" in result.stdout
    assert "yupay" in result.stdout.lower()


def test_a_token_inside_an_identifier_fails(clean_tree: Path) -> None:
    _plant(clean_tree, "apps/web/src/lib/item.ts", "export type SkuId = string;\n")
    result = _run(clean_tree)
    assert result.returncode == 1
    assert "apps/web/src/lib/item.ts:1" in result.stdout


@pytest.mark.parametrize(
    "token",
    [
        "brand_slug",
        "supplier_id",
        "guest_email",
        "Fulfiller",
        "merchants",
        "merchant_api",
        "voucher_code",
        "game_id",
    ],
)
def test_every_listed_token_is_caught(clean_tree: Path, token: str) -> None:
    _plant(clean_tree, "packages/utils/src/leak.ts", f"const {token.replace('.', '_')} = 1;\n")
    assert _run(clean_tree).returncode == 1


def test_the_acquirer_field_merchant_trans_id_is_allowed(clean_tree: Path) -> None:
    """Click's Prepare/Complete payload really is called ``merchant_trans_id`` (M3)."""
    _plant(clean_tree, "apps/api/src/csmarket/modules/click/schemas.py", "merchant_trans_id: str\n")
    result = _run(clean_tree)
    assert result.returncode == 0, result.stdout


def test_directories_outside_the_scope_are_not_scanned(clean_tree: Path) -> None:
    _plant(clean_tree, "docs/notes.md", "ported from yupay\n")
    _plant(clean_tree, "apps/api/tests/unit/test_x.py", "# yupay\n")
    assert _run(clean_tree).returncode == 0


def test_the_word_sku_does_not_match_skull_or_skunk(clean_tree: Path) -> None:
    _plant(
        clean_tree, "apps/web/src/lib/names.ts", 'const skull = "Skull Case"; const skunk = 1;\n'
    )
    assert _run(clean_tree).returncode == 0


@pytest.mark.parametrize(
    "ident", ["sku", "skus", "sku_id", "SkuId", "mySkuId", "SKU_ID", "skuCode"]
)
def test_sku_in_any_identifier_style_is_caught(clean_tree: Path, ident: str) -> None:
    _plant(clean_tree, "apps/web/src/lib/leak.ts", f"const {ident} = 1;\n")
    result = _run(clean_tree)
    assert result.returncode == 1, ident
    assert "apps/web/src/lib/leak.ts:1" in result.stdout


@pytest.mark.parametrize("word", ["skull", "Skull Case", "skunk", "SKULL", "Skunk"])
def test_skull_and_skunk_are_not_sku(clean_tree: Path, word: str) -> None:
    _plant(clean_tree, "apps/web/src/lib/names.ts", f'const label = "{word}";\n')
    result = _run(clean_tree)
    assert result.returncode == 0, word + result.stdout
