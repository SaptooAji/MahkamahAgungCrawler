from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ScrapingStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    UNPUBLISHED = "UNPUBLISHED"
    FAILED_RETRY = "FAILED_RETRY"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class Putusan(Base):
    __tablename__ = "putusan"

    __table_args__ = (
            Index(
                "ix_putusan_status_scraping",
                "status_scraping",
            ),
            Index(
                "ix_putusan_run_status_retry",
                "run_id",
                "status_scraping",
                "next_retry_at",
                "id",
            ),
        )
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scraping_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    tahun: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    halaman: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    url_detail: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )

    url_pdf: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    judul: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status_scraping: Mapped[ScrapingStatus] = mapped_column(
        SQLEnum(ScrapingStatus),
        nullable=False,
        default=ScrapingStatus.PENDING,
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

    last_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processing_worker_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    processing_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )