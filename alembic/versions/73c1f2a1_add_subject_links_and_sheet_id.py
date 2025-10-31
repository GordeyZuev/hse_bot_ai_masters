"""Add subject links and sheet_subject_id

Revision ID: 73c1f2a1
Revises: 4f17dc3b1c48
Create Date: 2025-10-31 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision = "73c1f2a1"
down_revision = "4f17dc3b1c48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subjects") as batch_op:
        batch_op.add_column(sa.Column("sheet_subject_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("wiki_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("vk_playlist_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("yt_playlist_url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subjects") as batch_op:
        batch_op.drop_column("yt_playlist_url")
        batch_op.drop_column("vk_playlist_url")
        batch_op.drop_column("wiki_url")
        batch_op.drop_column("sheet_subject_id")


