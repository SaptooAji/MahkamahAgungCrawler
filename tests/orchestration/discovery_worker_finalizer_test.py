from __future__ import annotations

import asyncio
import os

from sqlalchemy import delete

from database.session import SessionLocal

from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)

from models.putusan import (
    Putusan,
    ScrapingStatus,
)

from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)

from scraper.discovery_page import (
    DiscoveredPutusan,
)

from services.discovery_page_worker import (
    DiscoveryPageWorker,
)


TEST_YEAR = 2094


class FakeDiscoveryScraper:
    async def scrape(
        self,
        browser,
        *,
        url_page: str,
    ):
        return [
            DiscoveredPutusan(
                url_detail=(
                    "https://example.test/"
                    "phase-12/putusan/1"
                ),
                judul="Test Putusan 1",
                is_unpublish=False,
            )
        ]


def cleanup():
    with SessionLocal.begin() as session:
        session.execute(
            delete(Putusan).where(
                Putusan.tahun == TEST_YEAR
            )
        )

        session.execute(
            delete(DiscoveryPageJob).where(
                DiscoveryPageJob.tahun == TEST_YEAR
            )
        )

        session.execute(
            delete(ScrapingRun).where(
                ScrapingRun.tahun == TEST_YEAR
            )
        )


async def run_test():
    print("=" * 70)
    print("PHASE 12-2 - DISCOVERY WORKER -> RUN FINALIZER")
    print("=" * 70)

    print(
        f"ENV_FILE: "
        f"{os.getenv('ENV_FILE', '.env')}"
    )

    cleanup()

    try:
        # ====================================================
        # SEED RUN
        # ====================================================

        with SessionLocal.begin() as session:

            run = ScrapingRun(
                tahun=TEST_YEAR,
                status=ScrapingRunStatus.RUNNING,
                url_halaman_pertama=(
                    "https://example.test/"
                    "phase-12/page/1.html"
                ),
            )

            session.add(run)
            session.flush()

            run_id = run.id

            page_job = DiscoveryPageJob(
                run_id=run_id,
                tahun=TEST_YEAR,
                page_number=1,
                url_page=(
                    "https://example.test/"
                    "phase-12/page/1.html"
                ),
                status=DiscoveryPageJobStatus.PENDING,
            )

            session.add(page_job)
            session.flush()

            page_job_id = page_job.id

        print(
            f"12.1 Seed run/page job: PASS "
            f"(run_id={run_id}, page_job_id={page_job_id})"
        )

        # ====================================================
        # PROCESS
        # ====================================================

        worker = DiscoveryPageWorker(
            FakeDiscoveryScraper()
        )

        result = await worker.process(
            browser=None,
            page_job_id=page_job_id,
            worker_id="phase12-test-worker",
        )

        assert result.page_job_id == page_job_id
        assert result.discovered_count == 1
        assert result.created_count == 1

        print(
            "12.2 DiscoveryPageWorker processing: PASS"
        )

        # ====================================================
        # VERIFY DISCOVERY PAGE JOB
        # ====================================================

        with SessionLocal() as session:

            page_job = session.get(
                DiscoveryPageJob,
                page_job_id,
            )

            assert page_job is not None

            assert (
                page_job.status
                == DiscoveryPageJobStatus.SUCCESS
            )

            assert page_job.discovered_count == 1

        print(
            "12.3 DiscoveryPageJob SUCCESS: PASS"
        )

        # ====================================================
        # VERIFY PUTUSAN
        # ====================================================

        with SessionLocal() as session:

            putusan = session.execute(
                __import__("sqlalchemy").select(
                    Putusan
                ).where(
                    Putusan.tahun == TEST_YEAR
                )
            ).scalar_one()

            assert putusan.url_detail == (
                "https://example.test/"
                "phase-12/putusan/1"
            )

            assert (
                putusan.status_scraping
                == ScrapingStatus.PENDING
            )

            assert putusan.run_id == run_id

        print(
            "12.4 Putusan created: PASS"
        )

        # ====================================================
        # VERIFY RUN
        # ====================================================

        with SessionLocal() as session:

            run = session.get(
                ScrapingRun,
                run_id,
            )

            assert run is not None

            # Putusan masih PENDING, jadi run belum boleh
            # menjadi COMPLETED.
            assert (
                run.status
                == ScrapingRunStatus.DISCOVERY_COMPLETED
            )

            assert run.finished_at is None

        print(
            "12.5 Run -> DISCOVERY_COMPLETED: PASS"
        )

        # ====================================================
        # FINISH PUTUSAN
        # ====================================================

        with SessionLocal.begin() as session:

            putusan = session.execute(
                __import__("sqlalchemy").select(
                    Putusan
                ).where(
                    Putusan.tahun == TEST_YEAR
                )
            ).scalar_one()

            putusan.status_scraping = (
                ScrapingStatus.SUCCESS
            )

        # ====================================================
        # FINALIZER
        # ====================================================

        with SessionLocal.begin() as session:

            run = session.get(
                ScrapingRun,
                run_id,
            )

            worker.run_finalizer_service.try_finalize(
                session,
                run=run,
            )

            assert (
                run.status
                == ScrapingRunStatus.COMPLETED
            )

            assert run.finished_at is not None

        print(
            "12.6 Putusan terminal -> COMPLETED: PASS"
        )

        print()
        print("=" * 70)
        print("PHASE 12-2 DISCOVERY WORKER INTEGRATION: PASS")
        print("=" * 70)

    finally:
        cleanup()

        print(
            f"Cleanup Phase 12 test year: "
            f"{TEST_YEAR}"
        )


def main():
    asyncio.run(run_test())


if __name__ == "__main__":
    main()