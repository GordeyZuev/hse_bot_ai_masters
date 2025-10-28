"""merge heads

Revision ID: 4d64b6231a53
Revises: 73b82a745d6e, a1b2c3d4e5f6
Create Date: 2025-10-28 13:48:56.480112

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d64b6231a53'
down_revision: Union[str, Sequence[str], None] = ('73b82a745d6e', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
