"""wallet: a currency per account, the USD wallet switch on users

Accounts carry ``UZS`` or ``USD`` (milli-USD units); the five new kinds hold dollars and the
conversion's counter-accounts. ``users.usd_wallet_enabled`` is the admin's switch.

Revision ID: 0026_wallet_currency
Revises: 0025_order_float_seed
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_wallet_currency"
down_revision: str | None = "0025_order_float_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_OLD = (
    "'user_wallet', 'provider_clearing', 'house_payments_received', 'house_adjustments', "
    "'house_skin_buys'"
)
_KINDS_NEW = (
    _KINDS_OLD
    + ", 'user_wallet_usd', 'house_payments_received_usd', 'house_adjustments_usd', "
    + "'house_fx_uzs', 'house_fx_usd'"
)


def upgrade() -> None:
    """Add the currency column and its checks, and the user switch."""
    op.add_column(
        "wallet_accounts",
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'UZS'")),
    )
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_KINDS_NEW})")
    op.create_check_constraint("currency", "wallet_accounts", "currency IN ('UZS', 'USD')")
    op.add_column(
        "users",
        sa.Column(
            "usd_wallet_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    """Reverse; refused while a dollar or conversion account exists."""
    bind = op.get_bind()
    found = bind.execute(
        sa.text(
            "SELECT count(*) FROM wallet_accounts WHERE kind LIKE '%\\_usd' OR kind LIKE 'house\\_fx\\_%'"
        )
    ).scalar_one()
    if found:
        raise RuntimeError("cannot downgrade: USD / house_fx wallet accounts exist")
    op.drop_column("users", "usd_wallet_enabled")
    op.drop_constraint("currency", "wallet_accounts", type_="check")
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_KINDS_OLD})")
    op.drop_column("wallet_accounts", "currency")
