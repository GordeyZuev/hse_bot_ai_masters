"""Merge heads

Revision ID: 009
Revises: 008, 005
Create Date: 2025-10-31 21:44:10.060872

"""
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | Sequence[str] | None = ("008", "005")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
