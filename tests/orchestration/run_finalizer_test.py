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

from services.run_finalizer_service import (
    RunFinalizerService,
)


TEST_YEAR = 2095


def create_run(
    session,
    *,
    tahun: int,
) -> ScrapingRun:
    run = ScrapingRun(
        tahun=tahun,
        status=ScrapingRunStatus.RUNNING,
        url_halaman_pertama=(
            "https://example.test/phase-11b-finalizer/page/1.html"
        ),
    )

    session.add(run)
    session.flush()

    return run


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


def main():
    print("=" * 70)
    print("PHASE 11B - RUN FINALIZER")
    print("=" * 70)

    print(
        f"ENV_FILE: "
        f"{os.getenv('ENV_FILE', '.env')}"
    )

    cleanup()

    service = RunFinalizerService()

    try:
        # ====================================================
        # TEST 1
        # Discovery masih PROCESSING
        # ====================================================

        with SessionLocal.begin() as session:

            run = create_run(
                session,
                tahun=TEST_YEAR,
            )

            run_id = run.id

            session.add(
                DiscoveryPageJob(
                    run_id=run_id,
                    tahun=TEST_YEAR,
                    page_number=1,
                    url_page=(
                        "https://example.test/"
                        "phase-11b-finalizer/page/1.html"
                    ),
                    status=DiscoveryPageJobStatus.PROCESSING,
                )
            )

        with SessionLocal.begin() as session:

            run = session.get(
                ScrapingRun,
                run_id,
            )

            service.try_finalize(
                session,
                run=run,
            )

            session.flush()

            assert run.status == ScrapingRunStatus.RUNNING
            assert run.finished_at is None

        print(
            "11B.1 Discovery masih aktif -> RUNNING: PASS"
        )
        
        
        # ====================================================
        # Seed Putusan PROCESSING
        # ====================================================

        with SessionLocal.begin() as session:

            session.add(
                Putusan(
                    tahun=TEST_YEAR,
                    halaman=1,
                    run_id=run_id,
                    url_detail=(
                        "https://example.test/"
                        "phase-11b-finalizer/putusan/1"
                    ),
                    status_scraping=ScrapingStatus.PROCESSING,
                )
            )

        # ====================================================
        # TEST 2
        # Discovery selesai
        # ====================================================

        with SessionLocal.begin() as session:

            job = session.execute(
                __import__(
                    "sqlalchemy"
                ).select(
                    DiscoveryPageJob
                ).where(
                    DiscoveryPageJob.run_id == run_id
                )
            ).scalar_one()

            job.status = DiscoveryPageJobStatus.SUCCESS

        with SessionLocal.begin() as session:

            run = session.get(
                ScrapingRun,
                run_id,
            )

            service.try_finalize(
                session,
                run=run,
            )

            session.flush()

            assert (
                run.status
                == ScrapingRunStatus.DISCOVERY_COMPLETED
            )

            assert run.finished_at is None

        print(
            "11B.2 Discovery selesai -> "
            "DISCOVERY_COMPLETED: PASS"
        )

        # ====================================================
        # TEST 3
        # Putusan masih PROCESSING
        # ====================================================

        # with SessionLocal.begin() as session:

        #     session.add(
        #         Putusan(
        #             tahun=TEST_YEAR,
        #             halaman=1,
        #             url_detail=(
        #                 "https://example.test/"
        #                 "phase-11b-finalizer/putusan/1"
        #             ),
        #             status_scraping=ScrapingStatus.PROCESSING,
        #         )
        #     )

        with SessionLocal.begin() as session:

            run = session.get(
                ScrapingRun,
                run_id,
            )

            service.try_finalize(
                session,
                run=run,
            )

            session.flush()

            assert (
                run.status
                == ScrapingRunStatus.DISCOVERY_COMPLETED
            )

            assert run.finished_at is None

        print(
            "11B.3 Putusan masih aktif -> "
            "belum final: PASS"
        )

        # ====================================================
        # TEST 4
        # Putusan SUCCESS
        # ====================================================

        with SessionLocal.begin() as session:

            putusan = session.execute(
                __import__(
                    "sqlalchemy"
                ).select(
                    Putusan
                ).where(
                    Putusan.tahun == TEST_YEAR
                )
            ).scalar_one()

            putusan.status_scraping = (
                ScrapingStatus.SUCCESS
            )

        with SessionLocal.begin() as session:

            run = session.get(
                ScrapingRun,
                run_id,
            )

            service.try_finalize(
                session,
                run=run,
            )

            session.flush()

            assert (
                run.status
                == ScrapingRunStatus.COMPLETED
            )

            assert run.finished_at is not None

        print(
            "11B.4 Semua Putusan terminal -> "
            "COMPLETED: PASS"
        )

        # ====================================================
        # TEST 5
        # FAILED_PERMANENT
        # ====================================================

        with SessionLocal.begin() as session:

            failed_run = create_run(
                session,
                tahun=TEST_YEAR,
            )

            failed_run_id = failed_run.id

            session.add(
                DiscoveryPageJob(
                    run_id=failed_run_id,
                    tahun=TEST_YEAR,
                    page_number=1,
                    url_page=(
                        "https://example.test/"
                        "phase-11b-finalizer/"
                        "failed-page.html"
                    ),
                    status=(
                        DiscoveryPageJobStatus
                        .FAILED_PERMANENT
                    ),
                )
            )

        with SessionLocal.begin() as session:

            run = session.get(
                ScrapingRun,
                failed_run_id,
            )

            service.try_finalize(
                session,
                run=run,
            )

            session.flush()

            assert (
                run.status
                == ScrapingRunStatus.FAILED
            )

            assert run.finished_at is not None

        print(
            "11B.5 Discovery FAILED_PERMANENT -> "
            "FAILED: PASS"
        )

        # ====================================================
        # TEST 6
        # Idempotency
        # ====================================================

        with SessionLocal.begin() as session:

            run = session.get(
                ScrapingRun,
                run_id,
            )

            finished_at_before = run.finished_at

            service.try_finalize(
                session,
                run=run,
            )

            session.flush()

            assert (
                run.status
                == ScrapingRunStatus.COMPLETED
            )

            assert (
                run.finished_at
                == finished_at_before
            )

        print(
            "11B.6 Finalizer idempotent: PASS"
        )

        print()
        print("=" * 70)
        print("PHASE 11B RUN FINALIZER: PASS")
        print("=" * 70)

    finally:
        cleanup()

        print(
            f"Cleanup Phase 11B finalizer test year: "
            f"{TEST_YEAR}"
        )


if __name__ == "__main__":
    main()