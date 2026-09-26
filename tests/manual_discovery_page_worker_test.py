
import asyncio
import sys

import nodriver as uc

from sqlalchemy import select

from database.session import SessionLocal

from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)

from models.putusan import Putusan, ScrapingStatus

from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)

from scraper.discovery_page import (
    DiscoveryPageScraper,
)

from scraper.pagination import (
    PageDescriptor,
)

from services.discovery_page_job_service import (
    discovery_page_job_service,
)

from services.discovery_page_worker import (
    DiscoveryPageWorker,
)


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


YEAR = 2021

URL_PAGE_1 = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/"
    "tahun/2021.html"
)


async def main():
    browser = None
    run_id = None
    page_job_id = None

    try:
        print("=" * 70)
        print("DISCOVERY PAGE WORKER TEST")
        print("=" * 70)

        # ==========================================================
        # 1. START BROWSER
        # ==========================================================

        browser = await uc.start(
            headless=False,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )

        # ==========================================================
        # 2. CREATE TEST RUN + PAGE JOB
        # ==========================================================

        with SessionLocal.begin() as session:
            run = ScrapingRun(
                tahun=YEAR,
                status=ScrapingRunStatus.RUNNING,
                url_halaman_pertama=URL_PAGE_1,
            )

            session.add(run)
            session.flush()

            run_id = run.id

            page_count = (
                discovery_page_job_service
                .create_from_page_descriptors(
                    session,
                    run_id=run_id,
                    tahun=YEAR,
                    pages=[
                        PageDescriptor(
                            page_number=1,
                            url_page=URL_PAGE_1,
                        )
                    ],
                )
            )

            assert page_count == 1

            page_job = session.scalar(
                select(DiscoveryPageJob)
                .where(
                    DiscoveryPageJob.run_id
                    == run_id
                )
            )

            if page_job is None:
                raise RuntimeError(
                    "Page job test tidak ditemukan."
                )

            page_job_id = page_job.id

            assert (
                page_job.status
                == DiscoveryPageJobStatus.PENDING
            )

        print()
        print(
            f"ScrapingRun ID      : {run_id}"
        )

        print(
            f"DiscoveryPageJob ID : {page_job_id}"
        )

        print(
            "PAGE JOB INITIAL = PENDING: PASS"
        )

        # ==========================================================
        # 3. CREATE SCRAPER + WORKER
        # ==========================================================

        scraper = DiscoveryPageScraper(
            render_wait_seconds=5.0,
        )

        worker = DiscoveryPageWorker(
            scraper,
        )

        worker_id = "manual-worker-001"

        # ==========================================================
        # 4. PROCESS PAGE
        # ==========================================================

        result = await worker.process(
            browser,
            page_job_id=page_job_id,
            worker_id=worker_id,
        )

        print()
        print("WORKER RESULT")
        print("-" * 70)

        print(
            f"Page job        : "
            f"{result.page_job_id}"
        )

        print(
            f"Page number     : "
            f"{result.page_number}"
        )

        print(
            f"Discovered      : "
            f"{result.discovered_count}"
        )

        print(
            f"Created         : "
            f"{result.created_count}"
        )

        print(
            f"Existing        : "
            f"{result.existing_count}"
        )

        print(
            f"Unpublish       : "
            f"{result.unpublish_count}"
        )

        # ==========================================================
        # 5. ASSERT RESULT
        # ==========================================================

        assert (
            result.page_job_id
            == page_job_id
        )

        print(
            "PAGE JOB ID: PASS"
        )

        assert (
            result.page_number == 1
        )

        print(
            "PAGE NUMBER = 1: PASS"
        )

        assert (
            result.discovered_count > 0
        )

        print(
            "DISCOVERED COUNT > 0: PASS"
        )

        # ==========================================================
        # 6. VERIFY PAGE JOB SUCCESS
        # ==========================================================

        with SessionLocal() as session:
            page_job = session.get(
                DiscoveryPageJob,
                page_job_id,
            )

            if page_job is None:
                raise RuntimeError(
                    "Page job hilang setelah processing."
                )

            assert (
                page_job.status
                == DiscoveryPageJobStatus.SUCCESS
            )

            print(
                "PAGE JOB STATUS = SUCCESS: PASS"
            )

            assert (
                page_job.discovered_count
                == result.discovered_count
            )

            print(
                "DISCOVERED COUNT PERSISTED: PASS"
            )

            assert (
                page_job.processing_token
                is None
            )

            print(
                "PROCESSING TOKEN CLEARED: PASS"
            )

            assert (
                page_job.processing_worker_id
                is None
            )

            print(
                "WORKER ID CLEARED: PASS"
            )

            assert (
                page_job.processing_started_at
                is None
            )

            print(
                "PROCESSING LEASE CLEARED: PASS"
            )

        # ==========================================================
        # 7. VERIFY PUTUSAN
        # ==========================================================

        with SessionLocal() as session:
            putusan_rows = session.scalars(
                select(Putusan)
                .where(
                    Putusan.tahun == YEAR,
                    Putusan.halaman == 1,
                )
            ).all()

            print()

            print(
                f"PUTUSAN ROWS FOR PAGE 1: "
                f"{len(putusan_rows)}"
            )

            assert len(putusan_rows) > 0

            if len(putusan_rows) == 20:
                print("PUTUSAN DISCOVERY PERSISTED: PASS")
            else:
                print("PUTUSAN DISCOVERY PERSISTED: FAIL")
                raise AssertionError(
                    f"Expected 20 Putusan rows, got {len(putusan_rows)}"
                )

            unpublished_rows = [
                row
                for row in putusan_rows
                if row.status_scraping == ScrapingStatus.UNPUBLISHED
            ]

            print(
                f"UNPUBLISHED ROWS : {len(unpublished_rows)}"
            )

            if len(unpublished_rows) == 2:
                print("UNPUBLISHED STATUS = 2: PASS")
            else:
                print("UNPUBLISHED STATUS = 2: FAIL")
                raise AssertionError(
                    "Expected exactly 2 Putusan rows with "
                    "status_scraping=UNPUBLISHED."
                )

            urls = [
                row.url_detail
                for row in putusan_rows
            ]

            if len(urls) == len(set(urls)):
                print("URL_DETAIL UNIQUE IN RESULT: PASS")
            else:
                print("URL_DETAIL UNIQUE IN RESULT: FAIL")
                raise AssertionError(
                    "Duplicate url_detail ditemukan."
                )
     
            print()
            print("=" * 70)
            print("DISCOVERY PAGE WORKER TEST: PASS")
            print("=" * 70)

    finally:
        # ==========================================================
        # 8. CLEAN TEST DATA
        # ==========================================================

        if run_id is not None:
            with SessionLocal.begin() as session:
                run = session.get(
                    ScrapingRun,
                    run_id,
                )

                if run is not None:
                    session.delete(run)

            print()
            print(
                f"TEST RUN {run_id} DELETED"
            )

        # ==========================================================
        # 9. STOP BROWSER
        # ==========================================================

        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
