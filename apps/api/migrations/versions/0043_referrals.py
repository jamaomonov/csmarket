"""Referrals: partners, the accounts they bring, their rewards and link visits (ADR-0026).

Also widens ``wallet_accounts.kind`` with ``house_referrals``, the credit partner of a reward.

Revision ID: 0043_referrals
Revises: 0042_articles
"""

from collections.abc import Sequence
from typing import Any  # Column[Any]: a column spec of any type

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_referrals"
down_revision: str | None = "0042_articles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_KINDS_OLD = (
    "'user_wallet', 'provider_clearing', 'house_payments_received', 'house_adjustments', "
    "'house_skin_buys', 'user_wallet_usd', 'house_payments_received_usd', "
    "'house_adjustments_usd', 'house_fx_uzs', 'house_fx_usd'"
)
_KINDS_NEW = _KINDS_OLD + ", 'house_referrals'"


def _ts(name: str) -> sa.Column[Any]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _at(name: str, *, nullable: bool = False) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _partners() -> None:
    op.create_table(
        "referral_partners",
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("percent", sa.Numeric(4, 1), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("percent >= 0.1 AND percent <= 20", name="percent"),
        sa.CheckConstraint(
            "term_months IS NULL OR (term_months >= 1 AND term_months <= 120)",
            name="term_months",
        ),
        sa.CheckConstraint("code ~ '^[a-z0-9-]{3,32}$'", name="code"),
    )
    op.create_table(
        "referral_attributions",
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "partner_id",
            _UUID,
            sa.ForeignKey("referral_partners.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        _ts("attributed_at"),
    )
    op.create_index("ix_referral_attributions_partner", "referral_attributions", ["partner_id"])


def _rewards() -> None:
    op.create_table(
        "referral_rewards",
        sa.Column(
            "order_id", _UUID, sa.ForeignKey("orders.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column(
            "partner_id",
            _UUID,
            sa.ForeignKey("referral_partners.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "referred_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("base_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("percent", sa.Numeric(4, 1), nullable=False),
        sa.Column("amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _at("delivered_at"),
        _at("available_at"),
        _at("credited_at", nullable=True),
        sa.Column("cancelled_reason", sa.String(32), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("amount_uzs > 0", name="amount_positive"),
        sa.CheckConstraint("status IN ('held', 'credited', 'cancelled')", name="status"),
        sa.CheckConstraint(
            "cancelled_reason IS NULL OR cancelled_reason IN ('rolled_back')",
            name="cancelled_reason",
        ),
    )
    op.create_index(
        "ix_referral_rewards_due",
        "referral_rewards",
        ["available_at"],
        postgresql_where=sa.text("status = 'held'"),
    )
    op.create_index(
        "ix_referral_rewards_partner", "referral_rewards", ["partner_id", "delivered_at"]
    )
    op.create_table(
        "referral_visit_days",
        sa.Column(
            "partner_id",
            _UUID,
            sa.ForeignKey("referral_partners.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("visits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("visits >= 0", name="visits"),
    )


def upgrade() -> None:
    """Create the four tables and admit the ``house_referrals`` account kind."""
    _partners()
    _rewards()
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_KINDS_NEW})")


def downgrade() -> None:
    """Reverse; refused while a ``house_referrals`` account exists."""
    found = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM wallet_accounts WHERE kind = 'house_referrals'"))
        .scalar_one()
    )
    if found:
        raise RuntimeError("cannot downgrade: house_referrals wallet accounts exist")
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_KINDS_OLD})")
    op.drop_table("referral_visit_days")
    op.drop_index("ix_referral_rewards_partner", table_name="referral_rewards")
    op.drop_index("ix_referral_rewards_due", table_name="referral_rewards")
    op.drop_table("referral_rewards")
    op.drop_index("ix_referral_attributions_partner", table_name="referral_attributions")
    op.drop_table("referral_attributions")
    op.drop_table("referral_partners")
