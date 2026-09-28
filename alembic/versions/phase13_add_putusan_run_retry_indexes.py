"""add run-scoped putusan retry indexes

Revision ID: phase13runidx
Revises: cae44439e42e
Create Date: 2026-09-27
"""

from alembic import op


revision = "phase13runidx"
down_revision = "cae44439e42e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_putusan_run_status_retry",
        "putusan",
        ["run_id", "status_scraping", "next_retry_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_putusan_run_status_retry",
        table_name="putusan",
    )
