"""create discovery page jobs

Revision ID: 88a15dc3ed28
Revises: 29c108a7fbd4
Create Date: 2026-09-25 21:32:15.097415

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "88a15dc3ed28"
down_revision: Union[str, Sequence[str], None] = "29c108a7fbd4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


discovery_page_job_status_enum = postgresql.ENUM(
    "PENDING",
    "PROCESSING",
    "SUCCESS",
    "FAILED_RETRY",
    "FAILED_PERMANENT",
    name="discoverypagejobstatus",
    create_type=False,
)

pagination_mode_enum = postgresql.ENUM(
    "PREDICTIVE",
    "SEQUENTIAL",
    name="paginationmode",
    create_type=False,
)


def upgrade() -> None:
    # ---------------------------------------------------------
    # 1. Create PostgreSQL enum types first
    # ---------------------------------------------------------

    discovery_page_job_status_enum.create(
        op.get_bind(),
        checkfirst=True,
    )

    pagination_mode_enum.create(
        op.get_bind(),
        checkfirst=True,
    )

    # ---------------------------------------------------------
    # 2. Create discovery_page_jobs table
    # ---------------------------------------------------------

    op.create_table(
        "discovery_page_jobs",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "tahun",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "page_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "url_page",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "status",
            discovery_page_job_status_enum,
            nullable=False,
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "processing_worker_id",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "processing_token",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "discovered_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["scraping_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "page_number",
            name="uq_discovery_page_job_run_page",
        ),
    )

    # ---------------------------------------------------------
    # 3. Create indexes
    # ---------------------------------------------------------

    op.create_index(
        "ix_discovery_page_jobs_run_status",
        "discovery_page_jobs",
        ["run_id", "status"],
        unique=False,
    )

    op.create_index(
        "ix_discovery_page_jobs_status",
        "discovery_page_jobs",
        ["status"],
        unique=False,
    )

    # ---------------------------------------------------------
    # 4. Add new columns to scraping_runs
    # ---------------------------------------------------------

    op.add_column(
        "scraping_runs",
        sa.Column(
            "total_pages",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "scraping_runs",
        sa.Column(
            "pagination_mode",
            pagination_mode_enum,
            nullable=True,
        ),
    )

    op.add_column(
        "scraping_runs",
        sa.Column(
            "url_halaman_pertama",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # ---------------------------------------------------------
    # 1. Remove scraping_runs columns
    # ---------------------------------------------------------

    op.drop_column(
        "scraping_runs",
        "url_halaman_pertama",
    )

    op.drop_column(
        "scraping_runs",
        "pagination_mode",
    )

    op.drop_column(
        "scraping_runs",
        "total_pages",
    )

    # ---------------------------------------------------------
    # 2. Remove indexes
    # ---------------------------------------------------------

    op.drop_index(
        "ix_discovery_page_jobs_status",
        table_name="discovery_page_jobs",
    )

    op.drop_index(
        "ix_discovery_page_jobs_run_status",
        table_name="discovery_page_jobs",
    )

    # ---------------------------------------------------------
    # 3. Remove table
    # ---------------------------------------------------------

    op.drop_table("discovery_page_jobs")

    # ---------------------------------------------------------
    # 4. Remove PostgreSQL enum types
    # ---------------------------------------------------------

    pagination_mode_enum.drop(
        op.get_bind(),
        checkfirst=True,
    )

    discovery_page_job_status_enum.drop(
        op.get_bind(),
        checkfirst=True,
    )