"""Add topic_title to chat_groups

Revision ID: a1b2c3d4e5f6
Revises: d6117a9653ff
Create Date: 2025-10-28 13:48:30

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "d6117a9653ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("chat_groups", sa.Column("topic_title", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chat_groups", "topic_title")


