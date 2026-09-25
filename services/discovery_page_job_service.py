from sqlalchemy.orm import Session

from repositories.discovery_page_job_repository import (
    claim_page_job_by_id,
    mark_page_success,
    mark_page_failed_retry,
    recover_stale_page_jobs,
)


class DiscoveryPageJobService:
    def claim_by_id(
        self,
        session: Session,
        *,
        page_job_id: int,
        worker_id: str,
    ):
        return claim_page_job_by_id(
            session,
            page_job_id=page_job_id,
            worker_id=worker_id,
        )

    def mark_success(
        self,
        session: Session,
        *,
        page_job_id: int,
        worker_id: str,
        processing_token: str,
        discovered_count: int,
    ):
        return mark_page_success(
            session,
            page_job_id=page_job_id,
            worker_id=worker_id,
            processing_token=processing_token,
            discovered_count=discovered_count,
        )

    def mark_failed_retry(
        self,
        session: Session,
        *,
        page_job_id: int,
        worker_id: str,
        processing_token: str,
        error_message: str,
        retry_delay_seconds: int = 300,
    ):
        return mark_page_failed_retry(
            session,
            page_job_id=page_job_id,
            worker_id=worker_id,
            processing_token=processing_token,
            error_message=error_message,
            retry_delay_seconds=retry_delay_seconds,
        )

    def recover_stale(
        self,
        session: Session,
        *,
        stale_after_seconds: int = 900,
    ):
        return recover_stale_page_jobs(
            session,
            stale_after_seconds=stale_after_seconds,
        )


discovery_page_job_service = DiscoveryPageJobService()