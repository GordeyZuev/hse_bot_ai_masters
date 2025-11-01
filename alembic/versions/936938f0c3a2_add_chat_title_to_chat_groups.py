"""add_chat_title_to_chat_groups

Revision ID: 936938f0c3a2
Revises: add_notification_updates
Create Date: 2025-11-01 19:09:43.718695

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "936938f0c3a2"
down_revision: str | Sequence[str] | None = "add_notification_updates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("chat_groups", sa.Column("chat_title", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chat_groups", "chat_title")
