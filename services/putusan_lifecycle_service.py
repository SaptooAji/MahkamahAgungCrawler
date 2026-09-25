from sqlalchemy.orm import Session

from models.putusan import Putusan
from repositories.putusan_repository import (
    claim_pending_putusan,
    mark_putusan_failed_retry,
    mark_putusan_success,
    mark_putusan_unpublished,
    recover_stale_processing_putusan,
)


class PutusanLifecycleService:
    """
    Application/service layer untuk mengatur lifecycle Putusan.

    Service ini tidak melakukan scraping.
    Service ini hanya mengorkestrasi perubahan state di database.
    """

    def claim(
        self,
        session: Session,
        *,
        worker_id: str,
        batch_size: int = 10,
    ) -> list[Putusan]:
        return claim_pending_putusan(
            session,
            worker_id=worker_id,
            batch_size=batch_size,
        )

    def mark_success(
        self,
        session: Session,
        *,
        putusan_id: int,
        worker_id: str,
        url_pdf: str | None = None,
    ) -> Putusan:
        return mark_putusan_success(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            url_pdf=url_pdf,
        )

    def mark_unpublished(
        self,
        session: Session,
        *,
        putusan_id: int,
        worker_id: str,
        error_message: str | None = None,
    ) -> Putusan:
        return mark_putusan_unpublished(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            error_message=error_message,
        )

    def mark_failed_retry(
        self,
        session: Session,
        *,
        putusan_id: int,
        worker_id: str,
        error_message: str,
        retry_delay_seconds: int = 300,
    ) -> Putusan:
        return mark_putusan_failed_retry(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            error_message=error_message,
            retry_delay_seconds=retry_delay_seconds,
        )

    def recover_stale(
        self,
        session: Session,
        *,
        lease_timeout_seconds: int = 1800,
    ) -> int:
        return recover_stale_processing_putusan(
            session,
            lease_timeout_seconds=lease_timeout_seconds,
        )

putusan_lifecycle_service = PutusanLifecycleService()