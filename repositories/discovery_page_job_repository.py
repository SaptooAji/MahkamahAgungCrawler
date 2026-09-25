from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)


def create_page_job(
    session: Session,
    *,
    run_id: int,
    tahun: int,
    page_number: int,
    url_page: str,
) -> DiscoveryPageJob:
    stmt = (
        insert(DiscoveryPageJob)
        .values(
            run_id=run_id,
            tahun=tahun,
            page_number=page_number,
            url_page=url_page,
            status=DiscoveryPageJobStatus.PENDING,
        )
        .on_conflict_do_nothing(
            constraint="uq_discovery_page_job_run_page"
        )
        .returning(DiscoveryPageJob.id)
    )

    result = session.execute(stmt)
    page_job_id = result.scalar_one_or_none()

    if page_job_id is None:
        existing = session.scalar(
            select(DiscoveryPageJob).where(
                DiscoveryPageJob.run_id == run_id,
                DiscoveryPageJob.page_number == page_number,
            )
        )

        if existing is None:
            raise RuntimeError(
                "Page job tidak ditemukan setelah INSERT "
                "mengalami conflict."
            )

        return existing

    page_job = session.get(DiscoveryPageJob, page_job_id)

    if page_job is None:
        raise RuntimeError(
            "Page job berhasil dibuat tetapi tidak dapat "
            "dimuat kembali."
        )

    return page_job

def create_page_jobs(
    session: Session,
    *,
    run_id: int,
    tahun: int,
    pages: list[dict],
) -> int:
    """
    Create discovery page jobs idempotently.

    pages:
        [
            {
                "page_number": 1,
                "url_page": "...",
            },
            ...
        ]

    Returns:
        Number of newly-created page jobs.
    """

    if not pages:
        return 0

    values = [
        {
            "run_id": run_id,
            "tahun": tahun,
            "page_number": item["page_number"],
            "url_page": item["url_page"],
            "status": DiscoveryPageJobStatus.PENDING,
        }
        for item in pages
    ]

    stmt = (
        insert(DiscoveryPageJob)
        .values(values)
        .on_conflict_do_nothing(
            constraint="uq_discovery_page_job_run_page"
        )
        .returning(DiscoveryPageJob.id)
    )

    result = session.execute(stmt)

    created_ids = result.scalars().all()

    return len(created_ids)

def claim_page_job_by_id(
    session: Session,
    *,
    page_job_id: int,
    worker_id: str,
) -> DiscoveryPageJob | None:
    now = datetime.now(timezone.utc)

    stmt = (
        select(DiscoveryPageJob)
        .where(
            DiscoveryPageJob.id == page_job_id,
            DiscoveryPageJob.status.in_([
                DiscoveryPageJobStatus.PENDING,
                DiscoveryPageJobStatus.FAILED_RETRY,
            ]),
            (
                DiscoveryPageJob.next_retry_at.is_(None)
                | (DiscoveryPageJob.next_retry_at <= now)
            ),
        )
        .with_for_update(skip_locked=True)
    )

    page_job = session.scalar(stmt)

    if page_job is None:
        return None

    page_job.status = DiscoveryPageJobStatus.PROCESSING
    page_job.processing_started_at = now
    page_job.processing_worker_id = worker_id
    page_job.processing_token = str(uuid4())
    page_job.next_retry_at = None

    session.flush()

    return page_job

def mark_page_success(
    session: Session,
    *,
    page_job_id: int,
    worker_id: str,
    processing_token: str,
    discovered_count: int,
):
    stmt = (
        select(DiscoveryPageJob)
        .where(
            DiscoveryPageJob.id == page_job_id,
            DiscoveryPageJob.status == DiscoveryPageJobStatus.PROCESSING,
            DiscoveryPageJob.processing_worker_id == worker_id,
            DiscoveryPageJob.processing_token == processing_token,
        )
    )

    page_job = session.scalar(stmt)

    if page_job is None:
        raise RuntimeError(
            "Page job tidak dapat diubah SUCCESS: "
            "worker/token tidak cocok atau job bukan PROCESSING."
        )

    page_job.status = DiscoveryPageJobStatus.SUCCESS
    page_job.discovered_count = discovered_count
    page_job.processing_started_at = None
    page_job.processing_worker_id = None
    page_job.processing_token = None
    page_job.next_retry_at = None
    page_job.last_error = None

    session.flush()

    return page_job

def mark_page_failed_retry(
    session: Session,
    *,
    page_job_id: int,
    worker_id: str,
    processing_token: str,
    error_message: str,
    retry_delay_seconds: int = 300,
):
    from datetime import timedelta

    stmt = (
        select(DiscoveryPageJob)
        .where(
            DiscoveryPageJob.id == page_job_id,
            DiscoveryPageJob.status == DiscoveryPageJobStatus.PROCESSING,
            DiscoveryPageJob.processing_worker_id == worker_id,
            DiscoveryPageJob.processing_token == processing_token,
        )
    )

    page_job = session.scalar(stmt)

    if page_job is None:
        raise RuntimeError(
            "Page job tidak dapat diubah FAILED_RETRY: "
            "worker/token tidak cocok."
        )

    page_job.status = DiscoveryPageJobStatus.FAILED_RETRY
    page_job.retry_count += 1
    page_job.last_error = error_message
    page_job.processing_started_at = None
    page_job.processing_worker_id = None
    page_job.processing_token = None
    page_job.next_retry_at = (
        datetime.now(timezone.utc)
        + timedelta(seconds=retry_delay_seconds)
    )

    session.flush()

    return page_job

def recover_stale_page_jobs(
    session: Session,
    *,
    stale_after_seconds: int = 900,
) -> int:
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=stale_after_seconds)

    stmt = (
        select(DiscoveryPageJob)
        .where(
            DiscoveryPageJob.status == DiscoveryPageJobStatus.PROCESSING,
            DiscoveryPageJob.processing_started_at.is_not(None),
            DiscoveryPageJob.processing_started_at < stale_before,
        )
        .with_for_update(skip_locked=True)
    )

    page_jobs = session.scalars(stmt).all()

    for page_job in page_jobs:
        page_job.status = DiscoveryPageJobStatus.FAILED_RETRY
        page_job.retry_count += 1
        page_job.last_error = (
            "Processing lease expired; job recovered automatically."
        )
        page_job.processing_started_at = None
        page_job.processing_worker_id = None
        page_job.processing_token = None
        page_job.next_retry_at = now

    session.flush()

    return len(page_jobs)