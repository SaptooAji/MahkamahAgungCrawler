from __future__ import annotations

from dataclasses import dataclass
from services.run_finalizer_service import RunFinalizerService
from database.session import SessionLocal
from models.scraping_run import ScrapingRun

from scraper.discovery_page import (
    DiscoveredPutusan as DiscoveredPagePutusan,
)

from services.discovery_page_job_service import (
    discovery_page_job_service,
)

from services.discovery_service import (
    DiscoveredPutusan as DiscoveredPutusanData,
    save_discovered_putusan,
)


@dataclass(slots=True)
class DiscoveryPageProcessResult:
    page_job_id: int
    page_number: int
    discovered_count: int
    created_count: int
    existing_count: int
    unpublish_count: int

@dataclass(frozen=True, slots=True)
class ClaimedDiscoveryPage:
    page_job_id: int
    processing_token: str
    run_id: int
    page_number: int
    tahun: int
    url_page: str


class DiscoveryPageWorker:
    def __init__(self, scraper):
        self.scraper = scraper
        self.run_finalizer_service = RunFinalizerService()

    def claim(
        self,
        *,
        page_job_id: int,
        worker_id: str,
    ) -> ClaimedDiscoveryPage | None:
        with SessionLocal.begin() as session:
            page_job = discovery_page_job_service.claim_by_id(
                session,
                page_job_id=page_job_id,
                worker_id=worker_id,
            )

            if page_job is None:
                return None

            if not page_job.processing_token:
                raise RuntimeError(
                    f"DiscoveryPageJob {page_job_id} "
                    "berhasil di-claim tetapi processing_token kosong."
                )

            return ClaimedDiscoveryPage(
                page_job_id=page_job.id,
                processing_token=page_job.processing_token,
                run_id=page_job.run_id,
                page_number=page_job.page_number,
                tahun=page_job.tahun,
                url_page=page_job.url_page,
            )

    def adopt_claimed(
        self,
        *,
        page_job_id: int,
        dispatch_owner_id: str,
        worker_id: str,
    ) -> ClaimedDiscoveryPage | None:
        with SessionLocal.begin() as session:
            page_job = discovery_page_job_service.adopt_processing(
                session,
                page_job_id=page_job_id,
                dispatch_owner_id=dispatch_owner_id,
                worker_id=worker_id,
            )

            if page_job is None:
                return None

            if not page_job.processing_token:
                raise RuntimeError(
                    f"DiscoveryPageJob {page_job_id} adopted but processing_token kosong."
                )

            return ClaimedDiscoveryPage(
                page_job_id=page_job.id,
                processing_token=page_job.processing_token,
                run_id=page_job.run_id,
                page_number=page_job.page_number,
                tahun=page_job.tahun,
                url_page=page_job.url_page,
            )

    async def process_claimed(
        self,
        browser,
        *,
        claimed: ClaimedDiscoveryPage,
        worker_id: str,
    ) -> DiscoveryPageProcessResult:

        try:
            discovered = await self.scraper.scrape(
                browser,
                url_page=claimed.url_page,
            )

            if discovered is None:
                discovered = []

            if not isinstance(discovered, list):
                raise RuntimeError(
                    "Discovery scraper harus mengembalikan list."
                )

            for item in discovered:
                if not isinstance(item, DiscoveredPagePutusan):
                    raise RuntimeError(
                        "Item discovery memiliki tipe yang tidak valid."
                    )

            created_count = 0
            existing_count = 0
            unpublish_count = 0

            with SessionLocal.begin() as session:
                for item in discovered:
                    data = DiscoveredPutusanData(
                        run_id=claimed.run_id,
                        tahun=claimed.tahun,
                        halaman=claimed.page_number,
                        url_detail=item.url_detail,
                        judul=item.judul,
                        is_unpublish=item.is_unpublish,
                    )

                    _, created = save_discovered_putusan(
                        session,
                        data,
                    )

                    if created:
                        created_count += 1
                    else:
                        existing_count += 1

                    if item.is_unpublish:
                        unpublish_count += 1

                discovery_page_job_service.mark_success(
                    session,
                    page_job_id=claimed.page_job_id,
                    worker_id=worker_id,
                    processing_token=claimed.processing_token,
                    discovered_count=len(discovered),
                )

                run = session.get(
                    ScrapingRun,
                    claimed.run_id,
                )

                if run is not None:
                    self.run_finalizer_service.try_finalize(
                        session,
                        run=run,
                    )

            return DiscoveryPageProcessResult(
                page_job_id=claimed.page_job_id,
                page_number=claimed.page_number,
                discovered_count=len(discovered),
                created_count=created_count,
                existing_count=existing_count,
                unpublish_count=unpublish_count,
            )

        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"

            with SessionLocal.begin() as session:
                discovery_page_job_service.mark_failed_retry(
                    session,
                    page_job_id=claimed.page_job_id,
                    worker_id=worker_id,
                    processing_token=claimed.processing_token,
                    error_message=error_message,
                )

                run = session.get(
                    ScrapingRun,
                    claimed.run_id,
                )
                if run is not None:
                    self.run_finalizer_service.try_finalize(
                        session,
                        run=run,
                    )

            raise

    async def process(
        self,
        browser,
        *,
        page_job_id: int,
        worker_id: str,
    ) -> DiscoveryPageProcessResult:

        claimed = self.claim(
            page_job_id=page_job_id,
            worker_id=worker_id,
        )

        if claimed is None:
            raise RuntimeError(
                f"DiscoveryPageJob {page_job_id} tidak dapat di-claim."
            )

        return await self.process_claimed(
            browser,
            claimed=claimed,
            worker_id=worker_id,
        )
def build_discovery_page_worker(scraper):
    return DiscoveryPageWorker(scraper)