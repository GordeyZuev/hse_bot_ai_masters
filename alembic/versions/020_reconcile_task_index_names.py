"""Reconcile task indexes left with deadline names by old online upgrades."""

from collections.abc import Sequence

from sqlalchemy import inspect

from alembic import context, op


revision: str = "020"
down_revision: str | Sequence[str] | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAMES = (
    ("idx_deadlines_subject_id", "idx_tasks_subject_id"),
    ("idx_deadlines_soft_ts", "idx_tasks_soft_ts"),
    ("idx_deadlines_hard_ts", "idx_tasks_hard_ts"),
)


def upgrade() -> None:
    if context.is_offline_mode():
        return
    existing = {index["name"] for index in inspect(op.get_bind()).get_indexes("tasks")}
    for old_name, new_name in INDEX_NAMES:
        if old_name in existing and new_name in existing:
            raise RuntimeError(f"Оба индекса существуют: {old_name}, {new_name}")
        if old_name in existing:
            op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")


def downgrade() -> None:
    # Renaming indexes back would reintroduce drift on existing databases.
    pass
