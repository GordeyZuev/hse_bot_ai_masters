"""Add subject links and sheet_subject_id

Revision ID: 005
Revises: 003
Create Date: 2025-10-31 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("subjects") as batch_op:
        batch_op.add_column(sa.Column("sheet_subject_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("wiki_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("vk_playlist_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("yt_playlist_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("subjects") as batch_op:
        batch_op.drop_column("yt_playlist_url")
        batch_op.drop_column("vk_playlist_url")
        batch_op.drop_column("wiki_url")
        batch_op.drop_column("sheet_subject_id")


