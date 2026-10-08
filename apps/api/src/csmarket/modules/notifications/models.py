"""SQLAlchemy ORM for the ``notifications`` module (M4b ruling R5).

:class:`EmailOutbox` — one letter to send: written in the transaction of the event it
reports, claimed by the worker's ``emails`` queue, sent with the row id as the provider's
idempotency key. Order letters carry no address: the recipient is resolved at send time
from the user's verified email. Only a ``verify`` letter snapshots the address it verifies.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id
from csmarket.modules.sales import models as _sales_models  # noqa: F401  # FK target sales.id

#: Letter kinds: three order letters, the email confirmation, three sale letters (2026-10-08).
KINDS = (
    "receipt",
    "trade_sent",
    "refunded",
    "verify",
    "sale_hold",
    "sale_paid",
    "sale_canceled",
)
#: ``pending`` until sent; ``skipped`` = no verified address to send to (never retried);
#: ``failed`` = rejected by the provider or out of attempts.
STATUSES = ("pending", "sent", "skipped", "failed")


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class EmailOutbox(Base):
    """One letter in the outbox."""

    __tablename__ = "email_outbox"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
    )
    #: The sale a sale letter reports; ``NULL`` otherwise.
    sale_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=True
    )
    #: The address a ``verify`` letter confirms (PII: never logged); ``NULL`` otherwise.
    address: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    #: Strings the template needs (a token, an amount, a deadline).
    payload: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = _ts()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: ``http_422``, ``timeout``, ``network``… — never the provider's message text.
    last_error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(f"kind IN {_in(KINDS)}", name="kind"),
        CheckConstraint(f"status IN {_in(STATUSES)}", name="status"),
        # A replayed event never enqueues the same order letter twice.
        Index(
            "uq_email_outbox_order_kind",
            "order_id",
            "kind",
            unique=True,
            postgresql_where=text("order_id IS NOT NULL"),
        ),
        # A replayed sale event never enqueues the same sale letter twice.
        Index(
            "uq_email_outbox_sale_kind",
            "sale_id",
            "kind",
            unique=True,
            postgresql_where=text("sale_id IS NOT NULL"),
        ),
        Index(
            "ix_email_outbox_claimable",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_email_outbox_user_kind", "user_id", "kind", text("created_at DESC")),
    )
