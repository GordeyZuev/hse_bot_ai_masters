"""merge 4d64b6231a53 and 73c1f2a1

Revision ID: cbea2120eaa8
Revises: 4d64b6231a53, 73c1f2a1
Create Date: 2025-10-31 21:44:10.060872

"""
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "cbea2120eaa8"
down_revision: str | Sequence[str] | None = ("4d64b6231a53", "73c1f2a1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
