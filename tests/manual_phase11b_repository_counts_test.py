from __future__ import annotations

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

from repositories.discovery_page_job_repository import (
    get_run_status_counts,
)

from repositories.putusan_repository import (
    get_status_counts_by_year,
)


TEST_YEAR = 2096


def main():
    print("=" * 70)
    print("PHASE 11B - REPOSITORY STATUS COUNTS")
    print("=" * 70)

    print(
        f"ENV_FILE: "
        f"{os.getenv('ENV_FILE', '.env')}"
    )

    run_id = None

    try:
        # ====================================================
        # SEED
        # ====================================================

        with SessionLocal.begin() as session:

            # Cleanup jika test pernah dijalankan sebelumnya.
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

            run = ScrapingRun(
                tahun=TEST_YEAR,
                status=ScrapingRunStatus.RUNNING,
                url_halaman_pertama=(
                    "https://example.test/phase-11b/page/1.html"
                ),
            )

            session.add(run)
            session.flush()

            run_id = run.id

            # ------------------------------------------------
            # DiscoveryPageJob
            # ------------------------------------------------

            session.add_all(
                [
                    DiscoveryPageJob(
                        run_id=run_id,
                        tahun=TEST_YEAR,
                        page_number=1,
                        url_page=(
                            "https://example.test/phase-11b/page/1.html"
                        ),
                        status=DiscoveryPageJobStatus.SUCCESS,
                    ),
                    DiscoveryPageJob(
                        run_id=run_id,
                        tahun=TEST_YEAR,
                        page_number=2,
                        url_page=(
                            "https://example.test/phase-11b/page/2.html"
                        ),
                        status=DiscoveryPageJobStatus.SUCCESS,
                    ),
                    DiscoveryPageJob(
                        run_id=run_id,
                        tahun=TEST_YEAR,
                        page_number=3,
                        url_page=(
                            "https://example.test/phase-11b/page/3.html"
                        ),
                        status=DiscoveryPageJobStatus.FAILED_RETRY,
                    ),
                    DiscoveryPageJob(
                        run_id=run_id,
                        tahun=TEST_YEAR,
                        page_number=4,
                        url_page=(
                            "https://example.test/phase-11b/page/4.html"
                        ),
                        status=DiscoveryPageJobStatus.PROCESSING,
                    ),
                ]
            )

            # ------------------------------------------------
            # Putusan
            # ------------------------------------------------

            session.add_all(
                [
                    Putusan(
                        tahun=TEST_YEAR,
                        halaman=1,
                        url_detail=(
                            "https://example.test/phase-11b/putusan/1"
                        ),
                        status_scraping=ScrapingStatus.SUCCESS,
                    ),
                    Putusan(
                        tahun=TEST_YEAR,
                        halaman=1,
                        url_detail=(
                            "https://example.test/phase-11b/putusan/2"
                        ),
                        status_scraping=ScrapingStatus.SUCCESS,
                    ),
                    Putusan(
                        tahun=TEST_YEAR,
                        halaman=1,
                        url_detail=(
                            "https://example.test/phase-11b/putusan/3"
                        ),
                        status_scraping=ScrapingStatus.UNPUBLISHED,
                    ),
                    Putusan(
                        tahun=TEST_YEAR,
                        halaman=1,
                        url_detail=(
                            "https://example.test/phase-11b/putusan/4"
                        ),
                        status_scraping=ScrapingStatus.FAILED_RETRY,
                    ),
                    Putusan(
                        tahun=TEST_YEAR,
                        halaman=1,
                        url_detail=(
                            "https://example.test/phase-11b/putusan/5"
                        ),
                        status_scraping=ScrapingStatus.PROCESSING,
                    ),
                ]
            )

        print(
            f"11B.1 Seed data: PASS "
            f"(run_id={run_id})"
        )

        # ====================================================
        # TEST DISCOVERY COUNTS
        # ====================================================

        with SessionLocal() as session:

            counts = get_run_status_counts(
                session,
                run_id=run_id,
            )

        assert counts[
            DiscoveryPageJobStatus.SUCCESS
        ] == 2

        assert counts[
            DiscoveryPageJobStatus.FAILED_RETRY
        ] == 1

        assert counts[
            DiscoveryPageJobStatus.PROCESSING
        ] == 1

        print(
            "11B.2 DiscoveryPageJob status counts: PASS"
        )

        # ====================================================
        # TEST PUTUSAN COUNTS
        # ====================================================

        with SessionLocal() as session:

            counts = get_status_counts_by_year(
                session,
                tahun=TEST_YEAR,
            )

        assert counts[
            ScrapingStatus.SUCCESS
        ] == 2

        assert counts[
            ScrapingStatus.UNPUBLISHED
        ] == 1

        assert counts[
            ScrapingStatus.FAILED_RETRY
        ] == 1

        assert counts[
            ScrapingStatus.PROCESSING
        ] == 1

        print(
            "11B.3 Putusan status counts: PASS"
        )

        print()
        print("=" * 70)
        print("PHASE 11B REPOSITORY COUNTS: PASS")
        print("=" * 70)

    finally:
        # ====================================================
        # CLEANUP
        # ====================================================

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

        print(
            f"Cleanup Phase 11B test year: "
            f"{TEST_YEAR}"
        )


if __name__ == "__main__":
    main()