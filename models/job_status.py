# models/job_status.py
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from .base import Base

class CrawlJob(Base):
    __tablename__ = "crawl_jobs"
    id: Mapped[str] = mapped_column(primary_key=True) # UUID
    status: Mapped[str] = mapped_column(default="running") # running, completed, failed
    total_pages: Mapped[int] = mapped_column(default=0)
    processed_pages: Mapped[int] = mapped_column(default=0)
    start_time: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)