from __future__ import annotations

from dataclasses import dataclass
from services.run_finalizer_service import RunFinalizerService
from models.putusan import Putusan
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.session import SessionLocal
from scraper.detail_page import (
    DetailPageScraper,
    DetailScrapeStatus,
)
from services.putusan_lifecycle_service import putusan_lifecycle_service


@dataclass(frozen=True, slots=True)
class ClaimedPutusan:
    putusan_id: int
    url_detail: str
    processing_token: str


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

    Lifecycle:

        claim DB
          ↓
        commit
          ↓
        start/use browser
          ↓
        scrape
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
        self.run_finalizer_service = RunFinalizerService()

    def claim(
        self,
        *,
        putusan_id: int,
        worker_id: str,
        run_id: int | None = None,
    ) -> ClaimedPutusan | None:
        """
        Claim satu Putusan secara atomik.

        Tidak membuka browser.

        Return:
            ClaimedPutusan jika berhasil di-claim.
            None jika row tidak dapat di-claim.
        """
        with SessionLocal.begin() as session:
            putusan = putusan_lifecycle_service.claim_by_id(
                session,
                putusan_id=putusan_id,
                worker_id=worker_id,
                run_id=run_id,
            )

            if putusan is None:
                return None

            processing_token = putusan.processing_token

            if not processing_token:
                raise RuntimeError(
                    f"Putusan ID {putusan_id} berhasil di-claim "
                    "tetapi processing_token kosong."
                )

            return ClaimedPutusan(
                putusan_id=putusan.id,
                url_detail=putusan.url_detail,
                processing_token=processing_token,
            )

    def adopt_claimed(
        self,
        *,
        putusan_id: int,
        dispatch_owner_id: str,
        worker_id: str,
    ) -> ClaimedPutusan | None:
        with SessionLocal.begin() as session:
            putusan = putusan_lifecycle_service.adopt_processing(
                session,
                putusan_id=putusan_id,
                dispatch_owner_id=dispatch_owner_id,
                worker_id=worker_id,
            )

            if putusan is None:
                return None

            if not putusan.processing_token:
                raise RuntimeError(
                    f"Putusan {putusan_id} adopted but processing_token kosong."
                )

            return ClaimedPutusan(
                putusan_id=putusan.id,
                url_detail=putusan.url_detail,
                processing_token=putusan.processing_token,
            )

    async def process_claimed(
        self,
        browser,
        *,
        claimed: ClaimedPutusan,
        worker_id: str,
    ) -> PutusanProcessResult:
        """
        Memproses Putusan yang SUDAH di-claim.

        Browser sudah tersedia ketika method ini dipanggil.
        """

        putusan_id = claimed.putusan_id
        url_detail = claimed.url_detail
        processing_token = claimed.processing_token

        # SCRAPE
        try:
            result = await self.scraper.scrape(
                browser,
                url_detail=url_detail,
            )
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"

            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_failed_retry(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    error_message=error_message,
                )

            raise

        # SUCCESS
        if result.status == DetailScrapeStatus.SUCCESS:
            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_success(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    url_pdf=result.url_pdf,
                )

                putusan = session.get(Putusan, putusan_id)

                if putusan is None:
                    raise RuntimeError(
                        f"Putusan ID {putusan_id} tidak ditemukan "
                        "setelah mark_success()."
                    )

                run = self._get_run_for_putusan(
                    session,
                    putusan=putusan,
                )

                if run is not None:
                    self.run_finalizer_service.try_finalize(
                        session,
                        run=run,
                    )

            return PutusanProcessResult(
                        putusan_id=putusan_id,
                        status=result.status.value,
                        url_detail=url_detail,
                        url_pdf=result.url_pdf,
                    )

        # UNPUBLISHED
        if result.status == DetailScrapeStatus.UNPUBLISHED:
            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_unpublished(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    error_message=result.error_message,
                )

                putusan = session.get(Putusan, putusan_id)

                if putusan is None:
                    raise RuntimeError(
                        f"Putusan ID {putusan_id} tidak ditemukan "
                        "setelah mark_unpublished()."
                    )

                run = self._get_run_for_putusan(
                    session,
                    putusan=putusan,
                )

                if run is not None:
                    self.run_finalizer_service.try_finalize(
                        session,
                        run=run,
                    )

            return PutusanProcessResult(
                        putusan_id=putusan_id,
                        status=result.status.value,
                        url_detail=url_detail,
                        error_message=result.error_message,
                    )

        # RETRYABLE / PDF_NOT_FOUND
        if result.status in (
            DetailScrapeStatus.RETRYABLE_ERROR,
            DetailScrapeStatus.PDF_NOT_FOUND,
        ):
            error_message = (
                result.error_message
                or f"Detail scraper menghasilkan status "
                f"{result.status.value}."
            )

            with SessionLocal.begin() as session:
                putusan_lifecycle_service.mark_failed_retry(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    error_message=error_message,
                )

                putusan = session.get(Putusan, putusan_id)
                if putusan is not None:
                    run = self._get_run_for_putusan(
                        session,
                        putusan=putusan,
                    )
                    if run is not None:
                        self.run_finalizer_service.try_finalize(
                            session,
                            run=run,
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

    async def process(
        self,
        browser,
        *,
        putusan_id: int,
        worker_id: str,
        run_id: int | None = None,
    ) -> PutusanProcessResult:
        """
        Backward-compatible convenience method.

        Method ini tetap melakukan claim lalu scrape menggunakan browser
        yang diberikan caller.

        Untuk Celery production flow, gunakan:
            claim()
            lalu start browser
            lalu process_claimed()
        """

        claimed = self.claim(
            putusan_id=putusan_id,
            worker_id=worker_id,
            run_id=run_id,
        )

        if claimed is None:
            return PutusanProcessResult(
                putusan_id=putusan_id,
                status="SKIPPED",
                url_detail="",
                error_message=(
                    "Putusan tidak dapat di-claim. "
                    "Kemungkinan sudah diproses worker lain, "
                    "belum waktunya retry, atau status tidak valid."
                ),
            )

        return await self.process_claimed(
            browser,
            claimed=claimed,
            worker_id=worker_id,
        )

    def _get_run_for_putusan(
        self,
        session: Session,
        *,
        putusan: Putusan,
    ) -> ScrapingRun | None:
        if putusan.run_id is None:
            return None
        return session.get(ScrapingRun, putusan.run_id)


def build_putusan_worker(
    scraper: DetailPageScraper | None = None,
) -> PutusanWorker:
    if scraper is None:
        scraper = DetailPageScraper()

    return PutusanWorker(scraper)