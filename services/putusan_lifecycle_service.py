from sqlalchemy.orm import Session

from models.putusan import Putusan

from repositories.putusan_repository import (
    claim_pending_putusan,
    claim_putusan_by_id,
    mark_putusan_failed_retry,
    mark_putusan_success,
    mark_putusan_unpublished,
    recover_stale_processing_putusan,
    upsert_discovered_putusan,
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
        run_id: int | None = None,
    ) -> list[Putusan]:
        return claim_pending_putusan(
            session,
            worker_id=worker_id,
            batch_size=batch_size,
            run_id=run_id,
        )

    def mark_success(
        self,
        session: Session,
        *,
        putusan_id: int,
        worker_id: str,
        processing_token: str,
        url_pdf: str | None = None,
    ) -> Putusan:
        return mark_putusan_success(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            processing_token=processing_token,
            url_pdf=url_pdf,
        )

    def mark_unpublished(
        self,
        session: Session,
        *,
        putusan_id: int,
        worker_id: str,
        processing_token: str,
        error_message: str | None = None,
    ) -> Putusan:
        return mark_putusan_unpublished(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            processing_token=processing_token,
            error_message=error_message,
        )

    def mark_failed_retry(
        self,
        session: Session,
        *,
        putusan_id: int,
        worker_id: str,
        processing_token: str,
        error_message: str,
        retry_delay_seconds: int = 300,
    ) -> Putusan:
        return mark_putusan_failed_retry(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            processing_token=processing_token,
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

    def claim_by_id(
        self,
        session: Session,
        *,
        putusan_id: int,
        worker_id: str,
        run_id: int | None = None,
    ) -> Putusan | None:
        return claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            run_id=run_id,
        )

    def upsert_discovered(
        self,
        session: Session,
        *,
        run_id: int | None = None,
        tahun: int,
        halaman: int | None,
        url_detail: str,
        judul: str | None = None,
        is_unpublish: bool = False,
    ) -> tuple[Putusan, bool]:
        return upsert_discovered_putusan(
            session,
            run_id=run_id,
            tahun=tahun,
            halaman=halaman,
            url_detail=url_detail,
            judul=judul,
            is_unpublish=is_unpublish,
        )


putusan_lifecycle_service = PutusanLifecycleService()