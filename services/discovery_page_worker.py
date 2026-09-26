from __future__ import annotations

from dataclasses import dataclass

from database.session import SessionLocal

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


class DiscoveryPageWorker:
    def __init__(self, scraper):
        self.scraper = scraper

    async def process(
        self,
        browser,
        *,
        page_job_id: int,
        worker_id: str,
    ) -> DiscoveryPageProcessResult:

        # ---------------------------------------------------------
        # 1. Claim page job
        # ---------------------------------------------------------
        with SessionLocal.begin() as session:
            page_job = discovery_page_job_service.claim_by_id(
                session,
                page_job_id=page_job_id,
                worker_id=worker_id,
            )

            if page_job is None:
                raise RuntimeError(
                    f"Discovery page job {page_job_id} "
                    "tidak dapat di-claim."
                )

            page_number = page_job.page_number
            tahun = page_job.tahun
            url_page = page_job.url_page
            processing_token = page_job.processing_token

            if not processing_token:
                raise RuntimeError(
                    "Discovery page job berhasil di-claim "
                    "tetapi processing_token kosong."
                )

        # ---------------------------------------------------------
        # 2. Scraping dilakukan DI LUAR transaction database
        # ---------------------------------------------------------
        try:
            discovered = await self.scraper.scrape(
                browser,
                url_page=url_page,
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
                        "Discovery scraper mengembalikan object "
                        "dengan tipe tidak sesuai."
                    )

            # -----------------------------------------------------
            # 3. Persist hasil discovery
            # -----------------------------------------------------
            created_count = 0
            existing_count = 0
            unpublish_count = 0

            with SessionLocal.begin() as session:
                for item in discovered:
                    data = DiscoveredPutusanData(
                        tahun=tahun,
                        halaman=page_number,
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

                # -------------------------------------------------
                # 4. Tandai page job SUCCESS
                # -------------------------------------------------
                discovery_page_job_service.mark_success(
                    session,
                    page_job_id=page_job_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    discovered_count=len(discovered),
                )

            return DiscoveryPageProcessResult(
                page_job_id=page_job_id,
                page_number=page_number,
                discovered_count=len(discovered),
                created_count=created_count,
                existing_count=existing_count,
                unpublish_count=unpublish_count,
            )

        except Exception as exc:
            error_message = (
                f"{type(exc).__name__}: {exc}"
            )

            with SessionLocal.begin() as session:
                discovery_page_job_service.mark_failed_retry(
                    session,
                    page_job_id=page_job_id,
                    worker_id=worker_id,
                    processing_token=processing_token,
                    error_message=error_message,
                )

            raise


def build_discovery_page_worker(scraper):
    return DiscoveryPageWorker(scraper)