from datetime import datetime, timezone

from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)

from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DiscoveryPageJobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED_RETRY = "FAILED_RETRY"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class DiscoveryPageJob(Base):
    __tablename__ = "discovery_page_jobs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("scraping_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    tahun: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    page_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    url_page: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[DiscoveryPageJobStatus] = mapped_column(
        SQLEnum(DiscoveryPageJobStatus),
        nullable=False,
        default=DiscoveryPageJobStatus.PENDING,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processing_worker_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    processing_token: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    discovered_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "page_number",
            name="uq_discovery_page_job_run_page",
        ),
        Index(
            "ix_discovery_page_jobs_status",
            "status",
        ),
        Index(
            "ix_discovery_page_jobs_run_status",
            "run_id",
            "status",
        ),
    )