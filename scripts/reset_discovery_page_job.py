from database.session import SessionLocal
from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)
from sqlalchemy import select


PAGE_JOB_ID = 1564


with SessionLocal.begin() as session:
    job = session.scalar(
        select(DiscoveryPageJob).where(
            DiscoveryPageJob.id == PAGE_JOB_ID
        )
    )

    if job is None:
        raise RuntimeError(
            f"DiscoveryPageJob {PAGE_JOB_ID} tidak ditemukan."
        )

    job.status = DiscoveryPageJobStatus.PENDING
    job.retry_count = 0
    job.last_error = None
    job.processing_started_at = None
    job.processing_worker_id = None
    job.processing_token = None
    job.next_retry_at = None

    print(
        "RESET:",
        job.id,
        "page=",
        job.page_number,
        "status=",
        job.status.value,
    )