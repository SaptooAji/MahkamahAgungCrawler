from __future__ import annotations

import os

from sqlalchemy import delete, select

from database.session import SessionLocal

from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)

from models.scraping_run import (
    PaginationMode,
    ScrapingRun,
    ScrapingRunStatus,
)

from scraper.pagination import (
    PageDescriptor,
    PaginationMode as ScraperPaginationMode,
    PaginationResult,
)

from services.discovery_run_service import (
    DiscoveryRunService,
)


TEST_YEAR = 2098

TEST_PREFIX = (
    "https://example.test/phase-7b/"
)


# ============================================================
# HELPERS
# ============================================================

def build_predictive_result() -> PaginationResult:
    """
    PaginationResult simulasi PREDICTIVE.

    Tidak membuka browser.
    """

    pages = [
        PageDescriptor(
            page_number=1,
            url_page=(
                f"{TEST_PREFIX}"
                "tahun/2098.html"
            ),
        ),
        PageDescriptor(
            page_number=2,
            url_page=(
                f"{TEST_PREFIX}"
                "tahun/2098/page/2.html"
            ),
        ),
        PageDescriptor(
            page_number=3,
            url_page=(
                f"{TEST_PREFIX}"
                "tahun/2098/page/3.html"
            ),
        ),
        PageDescriptor(
            page_number=4,
            url_page=(
                f"{TEST_PREFIX}"
                "tahun/2098/page/4.html"
            ),
        ),
        PageDescriptor(
            page_number=5,
            url_page=(
                f"{TEST_PREFIX}"
                "tahun/2098/page/5.html"
            ),
        ),
    ]

    return PaginationResult(
        mode=ScraperPaginationMode.PREDICTIVE,
        total_pages=5,
        pages=pages,
    )


def build_sequential_result() -> PaginationResult:
    """
    PaginationResult simulasi SEQUENTIAL.

    Untuk test fallback.
    """

    pages = [
        PageDescriptor(
            page_number=1,
            url_page=(
                f"{TEST_PREFIX}"
                "sequential/tahun/2098.html"
            ),
        ),
        PageDescriptor(
            page_number=2,
            url_page=(
                f"{TEST_PREFIX}"
                "sequential/tahun/2098/page/2.html"
            ),
        ),
    ]

    return PaginationResult(
        mode=ScraperPaginationMode.SEQUENTIAL,
        total_pages=None,
        pages=pages,
    )


def create_run(
    session,
    *,
    tahun: int,
    url_page_1: str,
) -> ScrapingRun:
    """
    Membuat ScrapingRun melalui service yang sama
    dengan aplikasi.
    """

    service = DiscoveryRunService()

    run = service.create_run(
        session,
        tahun=tahun,
        url_halaman_pertama=url_page_1,
    )

    return run


# ============================================================
# CLEANUP
# ============================================================

def cleanup_runs(run_ids: list[int]) -> None:
    if not run_ids:
        return

    with SessionLocal.begin() as session:
        session.execute(
            delete(ScrapingRun).where(
                ScrapingRun.id.in_(run_ids)
            )
        )

    print(
        f"Cleanup residual test runs: {run_ids}"
    )


# ============================================================
# 7B.1
# CREATE RUN
# ============================================================

def test_create_run() -> int:
    """
    Verifikasi run baru:
        PENDING
        counters = 0
        belum selesai
    """

    service = DiscoveryRunService()

    with SessionLocal.begin() as session:
        run = service.create_run(
            session,
            tahun=TEST_YEAR,
            url_halaman_pertama=(
                f"{TEST_PREFIX}"
                "tahun/2098.html"
            ),
        )

        run_id = run.id

        assert run.status == (
            ScrapingRunStatus.PENDING
        )

        assert run.tahun == TEST_YEAR

        assert run.total_discovered == 0

        assert run.total_success == 0

        assert run.total_failed == 0

        assert run.total_unpublished == 0

        assert run.started_at is None

        assert run.finished_at is None

        assert run.url_halaman_pertama == (
            f"{TEST_PREFIX}"
            "tahun/2098.html"
        )

    print(
        "7B.1 create ScrapingRun: PASS"
    )

    return run_id


# ============================================================
# 7B.2
# PREDICTIVE PAGINATION
# ============================================================

def test_predictive_persistence(
    run_id: int,
) -> None:

    pagination_result = (
        build_predictive_result()
    )

    service = DiscoveryRunService()

    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert run is not None

        created_count = (
            service.persist_pagination_result(
                session,
                run=run,
                pagination_result=pagination_result,
            )
        )

        assert created_count == 5

        assert run.total_pages == 5

        assert run.pagination_mode == (
            PaginationMode.PREDICTIVE
        )

        assert run.url_halaman_pertama == (
            f"{TEST_PREFIX}"
            "tahun/2098.html"
        )

        assert run.total_discovered == 5

    print(
        "7B.2 PREDICTIVE persistence: PASS"
    )


# ============================================================
# 7B.3
# DISCOVERY PAGE JOB INVARIANT
# ============================================================

def test_predictive_page_jobs(
    run_id: int,
) -> None:

    with SessionLocal() as session:
        jobs = list(
            session.scalars(
                select(
                    DiscoveryPageJob
                )
                .where(
                    DiscoveryPageJob.run_id
                    == run_id
                )
                .order_by(
                    DiscoveryPageJob.page_number
                )
            ).all()
        )

    assert len(jobs) == 5

    expected_urls = [
        (
            f"{TEST_PREFIX}"
            "tahun/2098.html"
        ),
        (
            f"{TEST_PREFIX}"
            "tahun/2098/page/2.html"
        ),
        (
            f"{TEST_PREFIX}"
            "tahun/2098/page/3.html"
        ),
        (
            f"{TEST_PREFIX}"
            "tahun/2098/page/4.html"
        ),
        (
            f"{TEST_PREFIX}"
            "tahun/2098/page/5.html"
        ),
    ]

    for index, job in enumerate(jobs):
        expected_page = index + 1

        assert job.run_id == run_id

        assert job.tahun == TEST_YEAR

        assert job.page_number == expected_page

        assert job.url_page == (
            expected_urls[index]
        )

        assert job.status == (
            DiscoveryPageJobStatus.PENDING
        )

        assert job.retry_count == 0

        assert job.last_error is None

        assert job.processing_started_at is None

        assert job.processing_worker_id is None

        assert job.processing_token is None

        assert job.next_retry_at is None

        assert job.discovered_count == 0

    print(
        "7B.3 DiscoveryPageJob invariant: PASS"
    )


# ============================================================
# 7B.4
# IDEMPOTENT SECOND PERSISTENCE
# ============================================================

def test_predictive_idempotency(
    run_id: int,
) -> None:

    pagination_result = (
        build_predictive_result()
    )

    service = DiscoveryRunService()

    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert run is not None

        created_count = (
            service.persist_pagination_result(
                session,
                run=run,
                pagination_result=pagination_result,
            )
        )

        # Kontrak service saat ini:
        # persistence kedua tidak membuat job baru.
        assert created_count == 0

        assert run.total_pages == 5

        assert run.pagination_mode == (
            PaginationMode.PREDICTIVE
        )

        assert run.total_discovered == 0

    with SessionLocal() as session:
        jobs = list(
            session.scalars(
                select(
                    DiscoveryPageJob
                )
                .where(
                    DiscoveryPageJob.run_id
                    == run_id
                )
                .order_by(
                    DiscoveryPageJob.page_number
                )
            ).all()
        )

    assert len(jobs) == 5

    page_numbers = [
        job.page_number
        for job in jobs
    ]

    assert page_numbers == [
        1,
        2,
        3,
        4,
        5,
    ]

    print(
        "7B.4 Idempotent second persistence: PASS"
    )


# ============================================================
# 7B.5
# RUN METADATA AFTER IDEMPOTENT PERSISTENCE
# ============================================================

def test_predictive_run_metadata(
    run_id: int,
) -> None:

    with SessionLocal() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert run is not None

        assert run.status == (
            ScrapingRunStatus.PENDING
        )

        assert run.tahun == TEST_YEAR

        assert run.total_pages == 5

        assert run.pagination_mode == (
            PaginationMode.PREDICTIVE
        )

        assert run.url_halaman_pertama == (
            f"{TEST_PREFIX}"
            "tahun/2098.html"
        )

        # Persistence tidak boleh mengubah
        # status run menjadi COMPLETED.
        assert run.finished_at is None

    print(
        "7B.5 ScrapingRun metadata invariant: PASS"
    )


# ============================================================
# 7B.6
# SEQUENTIAL PAGINATION
# ============================================================

def test_sequential_persistence(
    run_id: int,
) -> None:

    pagination_result = (
        build_sequential_result()
    )

    service = DiscoveryRunService()

    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert run is not None

        created_count = (
            service.persist_pagination_result(
                session,
                run=run,
                pagination_result=pagination_result,
            )
        )

        assert created_count == 2

        assert run.total_pages is None

        assert run.pagination_mode == (
            PaginationMode.SEQUENTIAL
        )

        assert run.url_halaman_pertama == (
            f"{TEST_PREFIX}"
            "sequential/tahun/2098.html"
        )

        assert run.total_discovered == 2

    print(
        "7B.6 SEQUENTIAL persistence: PASS"
    )


# ============================================================
# 7B.7
# SEQUENTIAL PAGE JOB INVARIANT
# ============================================================

def test_sequential_page_jobs(
    run_id: int,
) -> None:

    with SessionLocal() as session:
        jobs = list(
            session.scalars(
                select(
                    DiscoveryPageJob
                )
                .where(
                    DiscoveryPageJob.run_id
                    == run_id
                )
                .order_by(
                    DiscoveryPageJob.page_number
                )
            ).all()
        )

    assert len(jobs) == 2

    expected_urls = [
        (
            f"{TEST_PREFIX}"
            "sequential/tahun/2098.html"
        ),
        (
            f"{TEST_PREFIX}"
            "sequential/tahun/2098/page/2.html"
        ),
    ]

    for index, job in enumerate(jobs):
        assert job.page_number == (
            index + 1
        )

        assert job.url_page == (
            expected_urls[index]
        )

        assert job.status == (
            DiscoveryPageJobStatus.PENDING
        )

        assert job.run_id == run_id

        assert job.tahun == TEST_YEAR

    print(
        "7B.7 SEQUENTIAL DiscoveryPageJob invariant: PASS"
    )


# ============================================================
# 7B.8
# UNIQUE(run_id, page_number)
# ============================================================

def test_unique_page_numbers(
    run_id: int,
) -> None:

    with SessionLocal() as session:
        jobs = list(
            session.scalars(
                select(
                    DiscoveryPageJob
                )
                .where(
                    DiscoveryPageJob.run_id
                    == run_id
                )
            ).all()
        )

    page_numbers = [
        job.page_number
        for job in jobs
    ]

    assert len(page_numbers) == (
        len(set(page_numbers))
    )

    print(
        "7B.8 Unique(run_id, page_number): PASS"
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    print("=" * 70)
    print("PHASE 7B - DISCOVERY RUN + PAGE JOB INTEGRATION")
    print("=" * 70)

    print(
        f"ENV_FILE: "
        f"{os.getenv('ENV_FILE', '.env')}"
    )

    run_ids: list[int] = []

    try:
        # ----------------------------------------------------
        # PREDICTIVE RUN
        # ----------------------------------------------------

        predictive_run_id = (
            test_create_run()
        )

        run_ids.append(
            predictive_run_id
        )

        test_predictive_persistence(
            predictive_run_id
        )

        test_predictive_page_jobs(
            predictive_run_id
        )

        test_predictive_idempotency(
            predictive_run_id
        )

        test_predictive_run_metadata(
            predictive_run_id
        )

        print()
        print(
            "PHASE 7B PREDICTIVE PATH: PASS"
        )

        # ----------------------------------------------------
        # SEQUENTIAL RUN
        # ----------------------------------------------------

        sequential_run_id = None

        with SessionLocal.begin() as session:
            sequential_run = create_run(
                session,
                tahun=TEST_YEAR,
                url_page_1=(
                    f"{TEST_PREFIX}"
                    "sequential/tahun/2098.html"
                ),
            )

            sequential_run_id = (
                sequential_run.id
            )

        run_ids.append(
            sequential_run_id
        )

        test_sequential_persistence(
            sequential_run_id
        )

        test_sequential_page_jobs(
            sequential_run_id
        )

        test_unique_page_numbers(
            sequential_run_id
        )

        print()
        print(
            "PHASE 7B SEQUENTIAL PATH: PASS"
        )

        # ----------------------------------------------------
        # FINAL
        # ----------------------------------------------------

        print()
        print("=" * 70)
        print("PHASE 7B: PASS")
        print("=" * 70)

    finally:
        cleanup_runs(run_ids)


if __name__ == "__main__":
    main()