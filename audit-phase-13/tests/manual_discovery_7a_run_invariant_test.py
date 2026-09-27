from __future__ import annotations

"""
Manual validation for Phase 7A - ScrapingRun lifecycle invariants.

Yang diuji:

7A.1  create_run() -> PENDING
7A.2  Initial counters / timestamps invariant
7A.3  mark_run_running() -> RUNNING + started_at
7A.4  persist_pagination_result() -> pagination metadata
7A.5  DiscoveryPageJob dibuat sesuai PaginationResult
7A.6  persist_pagination_result() idempotent
7A.7  mark_discovery_completed() -> COMPLETED + finished_at
7A.8  COMPLETED tidak mengubah counter hasil Putusan
7A.9  Persisted DB invariant setelah commit/reload
7A.10 FAILED lifecycle melalui discover_run() ketika pagination gagal
7A.11 FAILED menyimpan last_error + finished_at
7A.12 Cleanup test rows

Run from project root:

    ENV_FILE=.env.test python -m tests.manual_discovery_7a_run_invariant_test

atau:

    $env:ENV_FILE=".env.test"
    python -m tests.manual_discovery_7a_run_invariant_test
"""

import asyncio
import os
from dataclasses import dataclass

from dotenv import load_dotenv
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


# ============================================================
# CONSTANTS
# ============================================================

TEST_PREFIX = (
    "https://example.test/phase-7a/"
)

TEST_YEAR = 2099

TEST_PAGE_1_URL = (
    f"{TEST_PREFIX}tahun/{TEST_YEAR}.html"
)

TEST_PAGE_2_URL = (
    f"{TEST_PREFIX}tahun/{TEST_YEAR}/page/2.html"
)

TEST_PAGE_3_URL = (
    f"{TEST_PREFIX}tahun/{TEST_YEAR}/page/3.html"
)


# ============================================================
# HELPERS
# ============================================================

def load_environment() -> str:
    """
    Memuat environment yang dipakai test.

    Default tetap .env apabila ENV_FILE tidak diberikan.
    """

    env_file = os.getenv(
        "ENV_FILE",
        ".env",
    )

    load_dotenv(env_file)

    return env_file


def assert_true(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(
    actual,
    expected,
    message: str,
) -> None:
    if actual != expected:
        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected!r}\n"
            f"Actual:   {actual!r}"
        )


def seed_pagination_result() -> PaginationResult:
    """
    PaginationResult sintetis untuk menguji persistence layer.

    Sengaja tidak memanggil website Mahkamah Agung.
    """

    pages = [
        PageDescriptor(
            page_number=1,
            url_page=TEST_PAGE_1_URL,
        ),
        PageDescriptor(
            page_number=2,
            url_page=TEST_PAGE_2_URL,
        ),
        PageDescriptor(
            page_number=3,
            url_page=TEST_PAGE_3_URL,
        ),
    ]

    return PaginationResult(
        mode=ScraperPaginationMode.PREDICTIVE,
        total_pages=3,
        pages=pages,
    )


def create_test_run(
    service: DiscoveryRunService,
) -> int:
    """
    Membuat satu ScrapingRun test dan commit.

    Return:
        run_id
    """

    with SessionLocal.begin() as session:
        run = service.create_run(
            session,
            tahun=TEST_YEAR,
            url_halaman_pertama=TEST_PAGE_1_URL,
        )

        run_id = run.id

    return run_id


def fetch_run(
    run_id: int,
) -> ScrapingRun | None:
    with SessionLocal() as session:
        return session.get(
            ScrapingRun,
            run_id,
        )


def fetch_jobs(
    run_id: int,
) -> list[DiscoveryPageJob]:
    with SessionLocal() as session:
        return session.scalars(
            select(DiscoveryPageJob)
            .where(
                DiscoveryPageJob.run_id == run_id
            )
            .order_by(
                DiscoveryPageJob.page_number
            )
        ).all()


def cleanup_run(
    run_id: int,
) -> None:
    """
    Cleanup hanya menggunakan run_id.

    discovery_page_jobs mempunyai FK CASCADE terhadap
    scraping_runs, sehingga penghapusan ScrapingRun
    seharusnya ikut membersihkan DiscoveryPageJob.
    """

    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        if run is not None:
            session.delete(run)


# ============================================================
# 7A.1 - CREATE RUN
# ============================================================

def test_7a1_create_run(
    service: DiscoveryRunService,
    run_id: int,
) -> None:
    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.1: ScrapingRun tidak ditemukan setelah create_run().",
    )

    assert_equal(
        run.tahun,
        TEST_YEAR,
        "7A.1: tahun ScrapingRun salah.",
    )

    assert_equal(
        run.status,
        ScrapingRunStatus.PENDING,
        "7A.1: run baru harus berstatus PENDING.",
    )

    assert_equal(
        run.url_halaman_pertama,
        TEST_PAGE_1_URL,
        "7A.1: url_halaman_pertama salah.",
    )

    print(
        "7A.1 create_run() -> PENDING: PASS"
    )


# ============================================================
# 7A.2 - INITIAL COUNTERS / TIMESTAMPS
# ============================================================

def test_7a2_initial_invariants(
    run_id: int,
) -> None:
    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.2: ScrapingRun tidak ditemukan.",
    )

    assert_equal(
        run.total_discovered,
        0,
        "7A.2: total_discovered awal harus 0.",
    )

    assert_equal(
        run.total_success,
        0,
        "7A.2: total_success awal harus 0.",
    )

    assert_equal(
        run.total_failed,
        0,
        "7A.2: total_failed awal harus 0.",
    )

    assert_equal(
        run.total_unpublished,
        0,
        "7A.2: total_unpublished awal harus 0.",
    )

    assert_true(
        run.started_at is None,
        "7A.2: started_at belum boleh terisi.",
    )

    assert_true(
        run.finished_at is None,
        "7A.2: finished_at belum boleh terisi.",
    )

    assert_true(
        run.last_error is None,
        "7A.2: last_error awal harus NULL.",
    )

    assert_true(
        run.total_pages is None,
        "7A.2: total_pages awal harus NULL.",
    )

    assert_true(
        run.pagination_mode is None,
        "7A.2: pagination_mode awal harus NULL.",
    )

    print(
        "7A.2 Initial counters / timestamps invariant: PASS"
    )


# ============================================================
# 7A.3 - MARK RUNNING
# ============================================================

def test_7a3_mark_running(
    service: DiscoveryRunService,
    run_id: int,
) -> None:
    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert_true(
            run is not None,
            "7A.3: ScrapingRun tidak ditemukan.",
        )

        result = service.mark_run_running(
            session,
            run=run,
        )

        assert_equal(
            result.status,
            ScrapingRunStatus.RUNNING,
            "7A.3: status harus RUNNING.",
        )

        assert_true(
            result.started_at is not None,
            "7A.3: started_at harus terisi.",
        )

    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.3: ScrapingRun hilang setelah commit.",
    )

    assert_equal(
        run.status,
        ScrapingRunStatus.RUNNING,
        "7A.3: status RUNNING tidak tersimpan.",
    )

    assert_true(
        run.started_at is not None,
        "7A.3: started_at tidak tersimpan.",
    )

    assert_true(
        run.finished_at is None,
        "7A.3: finished_at belum boleh terisi.",
    )

    print(
        "7A.3 mark_run_running() -> RUNNING + started_at: PASS"
    )


# ============================================================
# 7A.4 - PERSIST PAGINATION RESULT
# ============================================================

def test_7a4_persist_pagination_result(
    service: DiscoveryRunService,
    run_id: int,
    pagination_result: PaginationResult,
) -> int:
    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert_true(
            run is not None,
            "7A.4: ScrapingRun tidak ditemukan.",
        )

        created_count = (
            service.persist_pagination_result(
                session,
                run=run,
                pagination_result=pagination_result,
            )
        )

        assert_equal(
            created_count,
            3,
            "7A.4: jumlah DiscoveryPageJob baru harus 3.",
        )

    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.4: ScrapingRun hilang.",
    )

    assert_equal(
        run.total_pages,
        3,
        "7A.4: total_pages salah.",
    )

    assert_equal(
        run.pagination_mode,
        PaginationMode.PREDICTIVE,
        "7A.4: pagination_mode salah.",
    )

    assert_equal(
        run.url_halaman_pertama,
        TEST_PAGE_1_URL,
        "7A.4: url_halaman_pertama salah.",
    )

    assert_equal(
        run.total_discovered,
        3,
        "7A.4: total_discovered harus 3.",
    )

    jobs = fetch_jobs(run_id)

    assert_equal(
        len(jobs),
        3,
        "7A.4: jumlah DiscoveryPageJob harus 3.",
    )

    print(
        "7A.4 persist_pagination_result(): PASS"
    )

    return created_count


# ============================================================
# 7A.5 - DISCOVERY PAGE JOB INVARIANT
# ============================================================

def test_7a5_page_job_invariants(
    run_id: int,
) -> None:
    jobs = fetch_jobs(run_id)

    assert_equal(
        len(jobs),
        3,
        "7A.5: harus ada 3 DiscoveryPageJob.",
    )

    expected = [
        (
            1,
            TEST_PAGE_1_URL,
        ),
        (
            2,
            TEST_PAGE_2_URL,
        ),
        (
            3,
            TEST_PAGE_3_URL,
        ),
    ]

    for job, (expected_page, expected_url) in zip(
        jobs,
        expected,
    ):
        assert_equal(
            job.run_id,
            run_id,
            f"7A.5: run_id job page {expected_page} salah.",
        )

        assert_equal(
            job.tahun,
            TEST_YEAR,
            f"7A.5: tahun job page {expected_page} salah.",
        )

        assert_equal(
            job.page_number,
            expected_page,
            f"7A.5: page_number salah untuk page {expected_page}.",
        )

        assert_equal(
            job.url_page,
            expected_url,
            f"7A.5: url_page salah untuk page {expected_page}.",
        )

        assert_equal(
            job.status,
            DiscoveryPageJobStatus.PENDING,
            f"7A.5: job page {expected_page} harus PENDING.",
        )

        assert_equal(
            job.retry_count,
            0,
            f"7A.5: retry_count job page {expected_page} harus 0.",
        )

        assert_true(
            job.processing_started_at is None,
            f"7A.5: processing_started_at page {expected_page} harus NULL.",
        )

        assert_true(
            job.processing_worker_id is None,
            f"7A.5: processing_worker_id page {expected_page} harus NULL.",
        )

        assert_true(
            job.processing_token is None,
            f"7A.5: processing_token page {expected_page} harus NULL.",
        )

        assert_true(
            job.next_retry_at is None,
            f"7A.5: next_retry_at page {expected_page} harus NULL.",
        )

        assert_equal(
            job.discovered_count,
            0,
            f"7A.5: discovered_count page {expected_page} harus 0.",
        )

    print(
        "7A.5 DiscoveryPageJob invariants: PASS"
    )


# ============================================================
# 7A.6 - IDEMPOTENT PERSISTENCE
# ============================================================

def test_7a6_idempotent_persistence(
    service: DiscoveryRunService,
    run_id: int,
    pagination_result: PaginationResult,
) -> None:
    """
    Memanggil persist_pagination_result() kedua kali dengan
    PageDescriptor yang sama.

    Karena DiscoveryPageJob menggunakan UNIQUE(run_id, page_number),
    jumlah job tidak boleh bertambah.
    """

    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert_true(
            run is not None,
            "7A.6: ScrapingRun tidak ditemukan.",
        )

        created_count = (
            service.persist_pagination_result(
                session,
                run=run,
                pagination_result=pagination_result,
            )
        )

        assert_equal(
            created_count,
            0,
            "7A.6: persist kedua harus menghasilkan 0 job baru.",
        )

    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.6: ScrapingRun hilang setelah persist kedua.",
    )

    assert_equal(
        run.total_discovered,
        0,
        (
            "7A.6: total_discovered setelah persist kedua "
            "harus mengikuti created_count aktual."
        ),
    )

    jobs = fetch_jobs(run_id)

    assert_equal(
        len(jobs),
        3,
        (
            "7A.6: persist kedua tidak boleh menggandakan "
            "DiscoveryPageJob."
        ),
    )

    print(
        "7A.6 Idempotent persist_pagination_result(): PASS"
    )


# ============================================================
# 7A.7 - COMPLETED
# ============================================================

def test_7a7_mark_completed(
    service: DiscoveryRunService,
    run_id: int,
) -> None:
    """
    Sebelum completion, kita set counter hasil Putusan
    secara manual untuk memastikan mark_discovery_completed()
    tidak mereset counter tersebut.
    """

    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert_true(
            run is not None,
            "7A.7: ScrapingRun tidak ditemukan.",
        )

        # Simulasikan counter hasil downstream.
        run.total_success = 2
        run.total_failed = 1
        run.total_unpublished = 1

        session.flush()

        result = (
            service.mark_discovery_completed(
                session,
                run=run,
            )
        )

        assert_equal(
            result.status,
            ScrapingRunStatus.COMPLETED,
            "7A.7: status harus COMPLETED.",
        )

        assert_true(
            result.finished_at is not None,
            "7A.7: finished_at harus terisi.",
        )

    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.7: ScrapingRun hilang setelah completion.",
    )

    assert_equal(
        run.status,
        ScrapingRunStatus.COMPLETED,
        "7A.7: status COMPLETED tidak tersimpan.",
    )

    assert_true(
        run.finished_at is not None,
        "7A.7: finished_at tidak tersimpan.",
    )

    print(
        "7A.7 mark_discovery_completed() -> COMPLETED: PASS"
    )


# ============================================================
# 7A.8 - COUNTER INVARIANT
# ============================================================

def test_7a8_counter_invariant(
    run_id: int,
) -> None:
    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.8: ScrapingRun tidak ditemukan.",
    )

    assert_equal(
        run.total_discovered,
        0,
        (
            "7A.8: total_discovered harus merepresentasikan "
            "jumlah job BARU dari persist terakhir."
        ),
    )

    assert_equal(
        run.total_success,
        2,
        "7A.8: total_success berubah secara tidak semestinya.",
    )

    assert_equal(
        run.total_failed,
        1,
        "7A.8: total_failed berubah secara tidak semestinya.",
    )

    assert_equal(
        run.total_unpublished,
        1,
        "7A.8: total_unpublished berubah secara tidak semestinya.",
    )

    print(
        "7A.8 Completion tidak merusak counters: PASS"
    )


# ============================================================
# 7A.9 - FINAL PERSISTED INVARIANT
# ============================================================

def test_7a9_final_db_invariant(
    run_id: int,
) -> None:
    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.9: ScrapingRun tidak ditemukan.",
    )

    assert_equal(
        run.status,
        ScrapingRunStatus.COMPLETED,
        "7A.9: final status harus COMPLETED.",
    )

    assert_equal(
        run.tahun,
        TEST_YEAR,
        "7A.9: tahun berubah.",
    )

    assert_equal(
        run.total_pages,
        3,
        "7A.9: total_pages berubah.",
    )

    assert_equal(
        run.pagination_mode,
        PaginationMode.PREDICTIVE,
        "7A.9: pagination_mode berubah.",
    )

    assert_equal(
        run.url_halaman_pertama,
        TEST_PAGE_1_URL,
        "7A.9: canonical page 1 berubah.",
    )

    assert_true(
        run.started_at is not None,
        "7A.9: started_at harus tetap tersedia.",
    )

    assert_true(
        run.finished_at is not None,
        "7A.9: finished_at harus tersedia.",
    )

    assert_true(
        run.last_error is None,
        "7A.9: completed run tidak boleh memiliki last_error.",
    )

    jobs = fetch_jobs(run_id)

    assert_equal(
        len(jobs),
        3,
        "7A.9: jumlah DiscoveryPageJob final harus 3.",
    )

    page_numbers = [
        job.page_number
        for job in jobs
    ]

    assert_equal(
        page_numbers,
        [1, 2, 3],
        "7A.9: page numbers final tidak sesuai.",
    )

    print(
        "7A.9 Final persisted DB invariant: PASS"
    )


# ============================================================
# 7A.10 - FAILED DISCOVERY
# ============================================================

class FailingPaginationScraper:
    """
    Fake pagination scraper.

    Tidak menyentuh website.
    Digunakan untuk memvalidasi error handling
    DiscoveryRunService.discover_run().
    """

    async def discover_pages(
        self,
        browser,
        *,
        url_page_1: str,
    ):
        raise RuntimeError(
            "PHASE 7A TEST - simulated pagination failure"
        )


async def run_failed_discovery(
    run_id: int,
) -> None:
    service = DiscoveryRunService(
        pagination_scraper=FailingPaginationScraper()
    )

    with SessionLocal() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        assert_true(
            run is not None,
            "7A.10: failed-test ScrapingRun tidak ditemukan.",
        )

        try:
            await service.discover_run(
                browser=None,
                session=session,
                run=run,
            )
        except RuntimeError as exc:
            assert_equal(
                str(exc),
                "PHASE 7A TEST - simulated pagination failure",
                "7A.10: exception message berubah.",
            )

            session.commit()
        else:
            raise AssertionError(
                "7A.10: discover_run() seharusnya melempar "
                "RuntimeError."
            )


def test_7a10_failed_discovery(
    service: DiscoveryRunService,
) -> int:
    with SessionLocal.begin() as session:
        run = service.create_run(
            session,
            tahun=TEST_YEAR,
            url_halaman_pertama=(
                f"{TEST_PREFIX}failed/{TEST_YEAR}.html"
            ),
        )

        run_id = run.id

    asyncio.run(
        run_failed_discovery(
            run_id
        )
    )

    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.10: failed ScrapingRun tidak ditemukan.",
    )

    assert_equal(
        run.status,
        ScrapingRunStatus.FAILED,
        "7A.10: status harus FAILED.",
    )

    print(
        "7A.10 discover_run() failure transition: PASS"
    )

    return run_id


# ============================================================
# 7A.11 - FAILED ERROR INVARIANT
# ============================================================

def test_7a11_failed_error_invariant(
    run_id: int,
) -> None:
    run = fetch_run(run_id)

    assert_true(
        run is not None,
        "7A.11: failed ScrapingRun tidak ditemukan.",
    )

    assert_equal(
        run.status,
        ScrapingRunStatus.FAILED,
        "7A.11: status harus FAILED.",
    )

    assert_equal(
        run.last_error,
        "PHASE 7A TEST - simulated pagination failure",
        "7A.11: last_error tidak tersimpan dengan benar.",
    )

    assert_true(
        run.started_at is not None,
        "7A.11: failed run harus memiliki started_at.",
    )

    assert_true(
        run.finished_at is not None,
        "7A.11: failed run harus memiliki finished_at.",
    )

    assert_true(
        run.finished_at >= run.started_at,
        "7A.11: finished_at tidak boleh sebelum started_at.",
    )

    assert_true(
        run.total_pages is None,
        "7A.11: failed discovery tidak boleh memiliki total_pages.",
    )

    assert_true(
        run.pagination_mode is None,
        "7A.11: failed discovery tidak boleh memiliki pagination_mode.",
    )

    jobs = fetch_jobs(run_id)

    assert_equal(
        len(jobs),
        0,
        "7A.11: failed discovery tidak boleh membuat page jobs.",
    )

    print(
        "7A.11 FAILED error / timestamp invariant: PASS"
    )


# ============================================================
# 7A.12 - CLEANUP INVARIANT
# ============================================================

def test_7a12_cleanup(
    run_id: int,
) -> None:
    jobs_before = fetch_jobs(run_id)

    assert_equal(
        len(jobs_before),
        3,
        "7A.12: expected 3 jobs before cleanup.",
    )

    cleanup_run(run_id)

    run_after = fetch_run(run_id)

    assert_true(
        run_after is None,
        "7A.12: ScrapingRun masih ada setelah cleanup.",
    )

    jobs_after = fetch_jobs(run_id)

    assert_equal(
        len(jobs_after),
        0,
        (
            "7A.12: DiscoveryPageJob masih ada setelah "
            "ScrapingRun dihapus. Pastikan FK CASCADE aktif."
        ),
    )

    print(
        "7A.12 Cleanup + FK CASCADE invariant: PASS"
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    env_file = load_environment()

    print("=" * 70)
    print("PHASE 7A - SCRAPING RUN INVARIANT")
    print("=" * 70)
    print(
        f"ENV_FILE: {env_file}"
    )
    print(
        f"TEST_YEAR: {TEST_YEAR}"
    )
    print("=" * 70)

    service = DiscoveryRunService()

    main_run_id: int | None = None
    failed_run_id: int | None = None

    pagination_result = seed_pagination_result()

    try:
        # --------------------------------------------------------
        # 7A.1 + 7A.2
        # --------------------------------------------------------

        main_run_id = create_test_run(
            service
        )

        print(
            f"Created test ScrapingRun ID: {main_run_id}"
        )

        test_7a1_create_run(
            service,
            main_run_id,
        )

        test_7a2_initial_invariants(
            main_run_id
        )

        # --------------------------------------------------------
        # 7A.3
        # --------------------------------------------------------

        test_7a3_mark_running(
            service,
            main_run_id,
        )

        # --------------------------------------------------------
        # 7A.4
        # --------------------------------------------------------

        test_7a4_persist_pagination_result(
            service,
            main_run_id,
            pagination_result,
        )

        # --------------------------------------------------------
        # 7A.5
        # --------------------------------------------------------

        test_7a5_page_job_invariants(
            main_run_id
        )

        # --------------------------------------------------------
        # 7A.6
        # --------------------------------------------------------

        test_7a6_idempotent_persistence(
            service,
            main_run_id,
            pagination_result,
        )

        # --------------------------------------------------------
        # 7A.7
        # --------------------------------------------------------

        test_7a7_mark_completed(
            service,
            main_run_id,
        )

        # --------------------------------------------------------
        # 7A.8
        # --------------------------------------------------------

        test_7a8_counter_invariant(
            main_run_id
        )

        # --------------------------------------------------------
        # 7A.9
        # --------------------------------------------------------

        test_7a9_final_db_invariant(
            main_run_id
        )

        print()
        print("=" * 70)
        print("PHASE 7A SUCCESS PATH: PASS")
        print("=" * 70)

        # --------------------------------------------------------
        # 7A.10 + 7A.11
        # --------------------------------------------------------

        failed_run_id = test_7a10_failed_discovery(
            service
        )

        test_7a11_failed_error_invariant(
            failed_run_id
        )

        print()
        print("=" * 70)
        print("PHASE 7A FAILURE PATH: PASS")
        print("=" * 70)

        # --------------------------------------------------------
        # Cleanup success-path run
        # --------------------------------------------------------

        test_7a12_cleanup(
            main_run_id
        )

        main_run_id = None

        # --------------------------------------------------------
        # Cleanup failed-path run
        # --------------------------------------------------------

        cleanup_run(
            failed_run_id
        )

        failed_run_id = None

        print()
        print("=" * 70)
        print("PHASE 7A: PASS")
        print("=" * 70)

    finally:
        # Defensive cleanup.
        if main_run_id is not None:
            cleanup_run(main_run_id)

        if failed_run_id is not None:
            cleanup_run(failed_run_id)

        print(
            "Cleanup residual test runs: DONE"
        )


if __name__ == "__main__":
    main()