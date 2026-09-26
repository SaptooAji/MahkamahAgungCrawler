from __future__ import annotations

from dataclasses import dataclass

from database.session import SessionLocal
from scraper.detail_page import (
    DetailPageScraper,
    DetailScrapeResult,
    DetailScrapeStatus,
)
from services.putusan_lifecycle_service import putusan_lifecycle_service


@dataclass(frozen=True, slots=True)
class PutusanProcessResult:
    putusan_id: int
    status: str
    url_detail: str
    url_pdf: str | None = None
    error_message: str | None = None


class PutusanWorker:
    """
    Orchestrator untuk memproses satu Putusan.

    Alur:

        claim DB
          ↓
        commit
          ↓
        scrape browser
          ↓
        update DB menggunakan processing_token
          ↓
        commit

    Browser TIDAK dijalankan di dalam transaksi PostgreSQL.
    """

    def __init__(
        self,
        scraper: DetailPageScraper,
    ) -> None:
        self.scraper = scraper

    async def process(
        self,
        browser,
        *,
        putusan_id: int,
        worker_id: str,
    ) -> PutusanProcessResult:
        # ============================================================
        # 1. CLAIM
        # ============================================================

        with SessionLocal.begin() as session:
            putusan = putusan_lifecycle_service.claim_by_id(
                session,
                putusan_id=putusan_id,
                worker_id=worker_id,
            )

            if putusan is None:
                raise RuntimeError(
                    f"Putusan ID {putusan_id} tidak dapat di-claim. "
                    "Kemungkinan sudah diproses worker lain, "
                    "belum waktunya retry, atau status tidak valid."
                )

            url_detail = putusan.url_detail
            processing_token = putusan.processing_token

            if not processing_token:
                raise RuntimeError(
                    f"Putusan ID {putusan_id} berhasil di-claim "
                    "tetapi processing_token kosong."
                )

        # ============================================================
        # 2. SCRAPE DETAIL
        #
        # Transaksi DB SUDAH selesai pada tahap ini.
        # ============================================================

        try:
            result = await self.scraper.scrape(
                browser,
                url_detail=url_detail,
            )

        except Exception as exc:
            error_message = (
                f"{type(exc).__name__}: {exc}"
            )

            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_failed_retry(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    error_message=error_message,
                )

            raise

        # ============================================================
        # 3. UPDATE DATABASE
        # ============================================================

        if result.status == DetailScrapeStatus.SUCCESS:
            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_success(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    url_pdf=result.url_pdf,
                )

            return PutusanProcessResult(
                putusan_id=putusan_id,
                status=result.status.value,
                url_detail=url_detail,
                url_pdf=result.url_pdf,
            )

        if result.status == DetailScrapeStatus.UNPUBLISHED:
            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_unpublished(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    error_message=result.error_message,
                )

            return PutusanProcessResult(
                putusan_id=putusan_id,
                status=result.status.value,
                url_detail=url_detail,
                error_message=result.error_message,
            )

        if result.status in (
            DetailScrapeStatus.RETRYABLE_ERROR,
            DetailScrapeStatus.PDF_NOT_FOUND,
        ):
            error_message = (
                result.error_message
                or f"Detail scraper menghasilkan status {result.status.value}."
            )

            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_failed_retry(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    error_message=error_message,
                )

            return PutusanProcessResult(
                putusan_id=putusan_id,
                status=result.status.value,
                url_detail=url_detail,
                error_message=error_message,
            )

        raise RuntimeError(
            f"Status hasil detail tidak ditangani: {result.status}"
        )


def build_putusan_worker(
    scraper: DetailPageScraper | None = None,
) -> PutusanWorker:
    if scraper is None:
        scraper = DetailPageScraper()

    return PutusanWorker(scraper)