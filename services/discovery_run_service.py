
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import select

from models.scraping_run import (
    PaginationMode,
    ScrapingRun,
    ScrapingRunStatus,
)

from scraper.pagination import (
    PaginationResult,
    PaginationScraper,
)

from services.discovery_page_job_service import (
    discovery_page_job_service,
)


class DiscoveryRunService:
    """
    Orchestrator untuk fase discovery.

    Alur:

        Browser
            ↓
        PaginationScraper
            ↓
        PaginationResult
            ↓
        DiscoveryPageJobService
            ↓
        PostgreSQL

    Service ini belum memproses detail putusan.
    Tugasnya hanya menemukan halaman direktori dan
    membuat DiscoveryPageJob.
    """

    def __init__(
        self,
        *,
        pagination_scraper: PaginationScraper | None = None,
    ):
        self.pagination_scraper = (
            pagination_scraper
            or PaginationScraper()
        )

    def create_run(
        self,
        session: Session,
        *,
        tahun: int,
        url_halaman_pertama: str,
    ) -> ScrapingRun:

        active_statuses = (
            ScrapingRunStatus.PENDING,
            ScrapingRunStatus.RUNNING,
            ScrapingRunStatus.DISCOVERY_COMPLETED,
        )

        existing_run = session.scalar(
            select(ScrapingRun)
            .where(
                ScrapingRun.tahun == tahun,
                ScrapingRun.status.in_(active_statuses),
            )
            .order_by(ScrapingRun.id.desc())
            .limit(1)
        )

        if existing_run is not None:
            raise ValueError(
                f"Masih ada ScrapingRun aktif untuk tahun {tahun}: "
                f"run_id={existing_run.id}, status={existing_run.status.value}"
            )

        run = ScrapingRun(
            tahun=tahun,
            status=ScrapingRunStatus.PENDING,
            url_halaman_pertama=url_halaman_pertama,
        )

        session.add(run)
        session.flush()

        return run
    
    def mark_run_running(
        self,
        session: Session,
        *,
        run: ScrapingRun,
    ) -> ScrapingRun:
        """
        Mengubah status run menjadi RUNNING.
        """

        run.status = ScrapingRunStatus.RUNNING
        run.started_at = datetime.now(
            timezone.utc
        )

        session.flush()

        return run

    def persist_pagination_result(
        self,
        session: Session,
        *,
        run: ScrapingRun,
        pagination_result: PaginationResult,
    ) -> int:
        """
        Menyimpan hasil pagination ke database.

        Informasi yang disimpan di ScrapingRun:
            - total_pages
            - pagination_mode
            - url_halaman_pertama

        Kemudian seluruh PageDescriptor dibuat menjadi
        DiscoveryPageJob secara idempotent.

        Return:
            jumlah DiscoveryPageJob baru yang dibuat.
        """

        run.total_pages = (
            pagination_result.total_pages
        )

        run.pagination_mode = (
            PaginationMode(
                pagination_result.mode.value
            )
        )

        run.url_halaman_pertama = (
            pagination_result.pages[0].url_page
            if pagination_result.pages
            else run.url_halaman_pertama
        )

        created_count = (
            discovery_page_job_service
            .create_from_page_descriptors(
                session,
                run_id=run.id,
                tahun=run.tahun,
                pages=pagination_result.pages,
            )
        )

        run.total_discovered = created_count

        session.flush()

        return created_count

    def mark_discovery_phase_completed(
        self,
        session: Session,
        *,
        run: ScrapingRun,
    ) -> ScrapingRun:
        run.status = ScrapingRunStatus.DISCOVERY_COMPLETED
        session.flush()
        return run
    
    async def discover_run(
        self,
        browser,
        session: Session,
        *,
        run: ScrapingRun,
    ) -> tuple[ScrapingRun, PaginationResult]:
        """
        Menjalankan discovery untuk satu ScrapingRun.

        Browser operation dilakukan di luar transaksi database.

        Setelah browser selesai, hasil pagination disimpan
        dalam satu transaksi pendek.

        Penting:
        - Tidak menahan transaksi PostgreSQL selama Chrome bekerja.
        - Jika browser gagal, status run dapat ditandai FAILED.
        """

        if not run.url_halaman_pertama:
            raise ValueError(
                "ScrapingRun tidak memiliki "
                "url_halaman_pertama."
            )

        try:
            run.status = (
                ScrapingRunStatus.RUNNING
            )
            run.started_at = datetime.now(
                timezone.utc
            )

            session.flush()

            pagination_result = (
                await self.pagination_scraper.discover_pages(
                    browser,
                    url_page_1=run.url_halaman_pertama,
                )
            )

            created_count = (
                self.persist_pagination_result(
                    session,
                    run=run,
                    pagination_result=pagination_result,
                )
            )

            run.total_discovered = (
                created_count
            )

            session.flush()

            return (
                run,
                pagination_result,
            )

        except Exception as exc:
            run.status = (
                ScrapingRunStatus.FAILED
            )

            run.last_error = str(exc)

            run.finished_at = datetime.now(
                timezone.utc
            )

            session.flush()

            raise

    def mark_discovery_completed(
        self,
        session: Session,
        *,
        run: ScrapingRun,
    ) -> ScrapingRun:
        """
        Menandai fase discovery selesai.

        COMPLETED di sini berarti discovery selesai,
        bukan berarti seluruh PDF sudah diproses.
        """

        run.status = (
            ScrapingRunStatus.COMPLETED
        )

        run.finished_at = datetime.now(
            timezone.utc
        )

        session.flush()

        return run


discovery_run_service = DiscoveryRunService()
