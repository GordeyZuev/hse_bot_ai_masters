"""Merge heads

Revision ID: 008
Revises: 006, 007
Create Date: 2025-10-28 13:48:56.480112

"""
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | Sequence[str] | None = ("006", "007")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
