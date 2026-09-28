"""add scraping run retry lifecycle

Revision ID: phase13runretry
Revises: phase13runidx
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "phase13runretry"
down_revision: Union[str, Sequence[str], None] = "phase13runidx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scraping_runs",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scraping_runs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scraping_runs",
        sa.Column("retry_dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "ALTER TYPE scrapingrunstatus ADD VALUE IF NOT EXISTS 'FAILED_RETRY'"
    )

    op.create_index(
        "ix_scraping_runs_status_retry",
        "scraping_runs",
        ["status", "next_retry_at", "retry_dispatched_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scraping_runs_status_retry",
        table_name="scraping_runs",
    )
    op.drop_column("scraping_runs", "retry_dispatched_at")
    op.drop_column("scraping_runs", "next_retry_at")
    op.drop_column("scraping_runs", "retry_count")
