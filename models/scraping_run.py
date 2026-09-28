from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SQLEnum
from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

class PaginationMode(str, Enum):
    PREDICTIVE = "PREDICTIVE"
    SEQUENTIAL = "SEQUENTIAL"

class ScrapingRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DISCOVERY_COMPLETED = "DISCOVERY_COMPLETED"
    FAILED_RETRY = "FAILED_RETRY"



class ScrapingRun(Base):
    __tablename__ = "scraping_runs"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    tahun: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[ScrapingRunStatus] = mapped_column(
        SQLEnum(ScrapingRunStatus),
        nullable=False,
        default=ScrapingRunStatus.PENDING,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    total_discovered: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    total_success: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    total_failed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    total_unpublished: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retry_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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

    total_pages: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    pagination_mode: Mapped[PaginationMode | None] = mapped_column(
        SQLEnum(PaginationMode),
        nullable=True,
    )

    url_halaman_pertama: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )