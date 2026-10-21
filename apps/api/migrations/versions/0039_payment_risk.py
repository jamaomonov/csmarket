"""Payment risk limits: kassa limits, user policies, holds; held / rejected statuses.

Revision ID: 0039_payment_risk
Revises: 0038_p2p
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_payment_risk"
down_revision: str | None = "0038_p2p"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")
_WINDOW = "window_hours BETWEEN 1 AND 720"

_TOPUP_OLD = "status IN ('pending', 'succeeded', 'expired', 'reversed')"
_TOPUP_NEW = "status IN ('pending', 'succeeded', 'expired', 'reversed', 'held', 'rejected')"
_ORDER_OLD = (
    "status IN ('pending', 'paid', 'buying', 'trade_sent', 'delivered', 'cancelled', "
    "'failed', 'returned')"
)
_ORDER_NEW = (
    "status IN ('pending', 'held', 'paid', 'buying', 'trade_sent', 'delivered', 'cancelled', "
    "'failed', 'returned')"
)
#: Owner ruling 2 (spec 2026-10-21): every kassa on, 2 000 000 soʻm per 24 h.
_SEED = ("payme", "click", "uzum", "p2p")


def upgrade() -> None:
    op.create_table(
        "kassa_review_limits",
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("updated_by", _UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint("max_amount_uzs >= 1", name="max_positive"),
        sa.CheckConstraint(_WINDOW, name="window"),
    )
    op.create_table(
        "user_risk_policies",
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("trusted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("kassa_blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("max_amount_uzs", sa.Numeric(14, 0), nullable=True),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", _UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint("max_amount_uzs IS NULL OR max_amount_uzs >= 1", name="max_positive"),
        sa.CheckConstraint(_WINDOW, name="window"),
    )
    op.create_table(
        "payment_holds",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("payment_id", _UUID, sa.ForeignKey("payments.id"), nullable=False, unique=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("window_sum_uzs", sa.Numeric(14, 0), nullable=True),
        sa.Column("limit_uzs", sa.Numeric(14, 0), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("decided_by", _UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", _TS, nullable=True),
        sa.CheckConstraint("kind IN ('topup', 'order')", name="kind"),
        sa.CheckConstraint(
            "reason IN ('kassa_limit', 'user_limit', 'check_failed')", name="reason"
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('released', 'returned', 'reversed_by_kassa')",
            name="decision",
        ),
        sa.CheckConstraint("(decision IS NULL) = (decided_at IS NULL)", name="decided_pair"),
    )
    op.create_index(
        "ix_payment_holds_open",
        "payment_holds",
        [sa.text("created_at DESC")],
        postgresql_where=sa.text("decision IS NULL"),
    )
    op.create_index(
        "ix_payment_holds_decided",
        "payment_holds",
        [sa.text("decided_at DESC")],
        postgresql_where=sa.text("decision IS NOT NULL"),
    )
    op.create_index("ix_payment_holds_user", "payment_holds", ["user_id"])
    # The window sum: a user's succeeded payments, per kassa, newest first.
    op.create_index(
        "ix_payments_user_provider_succeeded",
        "payments",
        ["user_id", "provider", sa.text("succeeded_at DESC")],
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.drop_constraint("status", "wallet_topups", type_="check")
    op.create_check_constraint("status", "wallet_topups", _TOPUP_NEW)
    op.drop_constraint("status", "orders", type_="check")
    op.create_check_constraint("status", "orders", _ORDER_NEW)
    for provider in _SEED:
        op.execute(
            "INSERT INTO kassa_review_limits (provider, enabled, max_amount_uzs, window_hours) "
            f"VALUES ('{provider}', true, 2000000, 24)"
        )


def downgrade() -> None:
    op.drop_constraint("status", "orders", type_="check")
    op.create_check_constraint("status", "orders", _ORDER_OLD)
    op.drop_constraint("status", "wallet_topups", type_="check")
    op.create_check_constraint("status", "wallet_topups", _TOPUP_OLD)
    op.drop_index("ix_payments_user_provider_succeeded", table_name="payments")
    op.drop_table("payment_holds")
    op.drop_table("user_risk_policies")
    op.drop_table("kassa_review_limits")
