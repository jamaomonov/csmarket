"""«Мои сделки»: the Skinslink bot that sent a deposit — its name, Steam id, and the Steam
profile's name and avatar (ADR-0027 amendment 2026-10-30).

Revision ID: 0045_desk_bot
Revises: 0044_desk
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_desk_bot"
down_revision: str | None = "0044_desk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("desk_deposits", sa.Column("bot_name", sa.String(64), nullable=True))
    op.add_column("desk_deposits", sa.Column("bot_steam_id", sa.String(20), nullable=True))
    op.add_column("desk_deposits", sa.Column("bot_persona", sa.String(64), nullable=True))
    op.add_column("desk_deposits", sa.Column("bot_avatar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in ("bot_avatar_url", "bot_persona", "bot_steam_id", "bot_name"):
        op.drop_column("desk_deposits", column)
