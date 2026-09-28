from __future__ import annotations

from sqlalchemy.orm import Session

from repositories.discovery_page_job_repository import (
    claim_pending_page_jobs,
    adopt_processing_page_job,
    claim_page_job_by_id,
    create_page_jobs,
    mark_page_failed_retry,
    mark_page_success,
    recover_stale_page_jobs,
)

from scraper.pagination import PageDescriptor


class DiscoveryPageJobService:
    """
    Service untuk lifecycle DiscoveryPageJob.

    Repository tetap menangani detail persistence.
    Service menangani orchestration dan transformasi
    dari object scraper ke format database.
    """

    def create_from_page_descriptors(
        self,
        session: Session,
        *,
        run_id: int,
        tahun: int,
        pages: list[PageDescriptor],
    ) -> int:
        """
        Membuat discovery page jobs dari hasil pagination.

        Operasi bersifat idempotent karena repository menggunakan:

            ON CONFLICT DO NOTHING

        sehingga menjalankan method ini dua kali tidak akan
        membuat duplicate page jobs.

        Return:
            jumlah row baru yang benar-benar dibuat.
        """

        if not pages:
            return 0

        page_rows = [
            {
                "page_number": page.page_number,
                "url_page": page.url_page,
            }
            for page in pages
        ]

        return create_page_jobs(
            session,
            run_id=run_id,
            tahun=tahun,
            pages=page_rows,
        )

    def claim_pending(
        self,
        session: Session,
        *,
        worker_id: str,
        batch_size: int = 5,
        run_id: int | None = None,
    ):
        return claim_pending_page_jobs(
            session,
            worker_id=worker_id,
            batch_size=batch_size,
            run_id=run_id,
        )

    def adopt_processing(
        self,
        session: Session,
        *,
        page_job_id: int,
        dispatch_owner_id: str,
        worker_id: str,
    ):
        return adopt_processing_page_job(
            session,
            page_job_id=page_job_id,
            dispatch_owner_id=dispatch_owner_id,
            worker_id=worker_id,
        )

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
