"""Repair installations stamped 015 by an older, unrelated migration.

The existing production database may report revision 015 while still having
the 014 schema plus a legacy deadline_display_mode column. PostgreSQL DDL is
transactional, so the missing 015 columns indicate that our 015 did not run.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from alembic import context, op


revision: str = "016"
down_revision: str | Sequence[str] | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        return
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("subjects")
    }
    if "modules" not in columns:
        previous = ScriptDirectory.from_config(context.config).get_revision("015")
        previous.module.upgrade()


def downgrade() -> None:
    # The repair is additive. Reversing it could remove data from databases
    # whose 015 revision originally meant a different schema.
    pass
