from __future__ import annotations

import asyncio
import os

from sqlalchemy import delete, select

from database.session import SessionLocal

from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)

from models.putusan import (
    Putusan,
    ScrapingStatus,
)

from services.discovery_page_worker import (
    DiscoveryPageWorker,
)

from services.putusan_dispatcher import (
    get_pending_putusan_ids,
)

from scraper.discovery_page import (
    DiscoveredPutusan,
)


TEST_PREFIX = (
    "https://example.test/phase-8/"
)

TEST_YEAR = 2097

WORKER_ID = "phase-8-discovery-worker"


# ============================================================
# FAKE DISCOVERY SCRAPER
# ============================================================

class FakeDiscoveryScraper:
    """
    Tidak membuka browser.

    Mengembalikan hasil discovery yang menyerupai
    output DiscoveryPageScraper sebenarnya.
    """

    def __init__(self, items):
        self.items = items
        self.called_url = None

    async def scrape(
        self,
        browser,
        *,
        url_page: str,
    ):
        self.called_url = url_page

        return list(self.items)


# ============================================================
# SEED DISCOVERY PAGE JOB
# ============================================================

def seed_page_job() -> int:
    """
    Membuat satu DiscoveryPageJob PENDING.
    """

    test_url = (
        f"{TEST_PREFIX}"
        "direktori/page/1.html"
    )

    with SessionLocal.begin() as session:

        # Idempotent cleanup.
        session.execute(
            delete(DiscoveryPageJob).where(
                DiscoveryPageJob.url_page
                == test_url
            )
        )

        # Hapus Putusan test yang mungkin
        # berasal dari eksekusi sebelumnya.
        session.execute(
            delete(Putusan).where(
                Putusan.url_detail.like(
                    f"{TEST_PREFIX}putusan/%"
                )
            )
        )

        job = DiscoveryPageJob(
            run_id=None,
            tahun=TEST_YEAR,
            page_number=1,
            url_page=test_url,
            status=DiscoveryPageJobStatus.PENDING,
            retry_count=0,
            discovered_count=0,
        )

        session.add(job)
        session.flush()

        return job.id


# ============================================================
# NOTE
# ============================================================

def create_page_job_with_run() -> int:
    """
    DiscoveryPageJob memiliki FK run_id.

    Karena Phase 8 hanya menguji discovery -> Putusan,
    kita membuat run test terlebih dahulu.
    """

    from models.scraping_run import (
        ScrapingRun,
        ScrapingRunStatus,
    )

    page_url = (
        f"{TEST_PREFIX}"
        "direktori/page/1.html"
    )

    with SessionLocal.begin() as session:

        # Bersihkan Putusan.
        session.execute(
            delete(Putusan).where(
                Putusan.url_detail.like(
                    f"{TEST_PREFIX}putusan/%"
                )
            )
        )

        # Bersihkan job.
        session.execute(
            delete(DiscoveryPageJob).where(
                DiscoveryPageJob.url_page
                == page_url
            )
        )

        run = ScrapingRun(
            tahun=TEST_YEAR,
            status=ScrapingRunStatus.RUNNING,
            url_halaman_pertama=page_url,
        )

        session.add(run)
        session.flush()

        job = DiscoveryPageJob(
            run_id=run.id,
            tahun=TEST_YEAR,
            page_number=1,
            url_page=page_url,
            status=DiscoveryPageJobStatus.PENDING,
            retry_count=0,
            discovered_count=0,
        )

        session.add(job)
        session.flush()

        return job.id


# ============================================================
# DISCOVERY RESULT
# ============================================================

def build_discovery_result():
    return [
        DiscoveredPutusan(
            url_detail=(
                f"{TEST_PREFIX}"
                "putusan/normal-1"
            ),
            judul="Putusan Normal 1",
            is_unpublish=False,
        ),
        DiscoveredPutusan(
            url_detail=(
                f"{TEST_PREFIX}"
                "putusan/normal-2"
            ),
            judul="Putusan Normal 2",
            is_unpublish=False,
        ),
        DiscoveredPutusan(
            url_detail=(
                f"{TEST_PREFIX}"
                "putusan/unpublished-1"
            ),
            judul="Putusan Unpublished 1",
            is_unpublish=True,
        ),
    ]


# ============================================================
# 8A.1
# CLAIM PAGE JOB
# ============================================================

def test_claim(
    page_job_id: int,
):
    scraper = FakeDiscoveryScraper(
        build_discovery_result()
    )

    worker = DiscoveryPageWorker(
        scraper
    )

    claimed = worker.claim(
        page_job_id=page_job_id,
        worker_id=WORKER_ID,
    )

    assert claimed is not None

    assert claimed.page_job_id == (
        page_job_id
    )

    assert claimed.tahun == TEST_YEAR

    assert claimed.page_number == 1

    assert claimed.processing_token

    assert claimed.url_page == (
        f"{TEST_PREFIX}"
        "direktori/page/1.html"
    )

    print(
        "8A.1 DiscoveryPageJob claim: PASS"
    )

    return claimed, scraper


# ============================================================
# 8A.2
# PROCESS DISCOVERY RESULT
# ============================================================

def test_process_claimed(
    claimed,
    scraper,
):
    worker = DiscoveryPageWorker(
        scraper
    )

    result = asyncio.run(
        worker.process_claimed(
            browser=None,
            claimed=claimed,
            worker_id=WORKER_ID,
        )
    )

    assert result.page_job_id == (
        claimed.page_job_id
    )

    assert result.page_number == 1

    assert result.discovered_count == 3

    assert result.created_count == 3

    assert result.existing_count == 0

    assert result.unpublish_count == 1

    assert scraper.called_url == (
        claimed.url_page
    )

    print(
        "8A.2 DiscoveryPageWorker processing: PASS"
    )

    return result


# ============================================================
# 8A.3
# PAGE JOB SUCCESS
# ============================================================

def test_page_job_success(
    page_job_id: int,
):
    with SessionLocal() as session:

        job = session.get(
            DiscoveryPageJob,
            page_job_id,
        )

        assert job is not None

        assert job.status == (
            DiscoveryPageJobStatus.SUCCESS
        )

        assert job.discovered_count == 3

        assert job.processing_worker_id is None

        assert job.processing_token is None

        assert job.processing_started_at is None

        assert job.last_error is None

        assert job.retry_count == 0

    print(
        "8A.3 DiscoveryPageJob SUCCESS invariant: PASS"
    )


# ============================================================
# 8A.4
# PUTUSAN CREATED
# ============================================================

def test_putusan_created():
    expected_urls = [
        (
            f"{TEST_PREFIX}"
            "putusan/normal-1"
        ),
        (
            f"{TEST_PREFIX}"
            "putusan/normal-2"
        ),
        (
            f"{TEST_PREFIX}"
            "putusan/unpublished-1"
        ),
    ]

    with SessionLocal() as session:

        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.url_detail.in_(
                        expected_urls
                    )
                )
                .order_by(
                    Putusan.url_detail
                )
            ).all()
        )

    assert len(rows) == 3

    by_url = {
        row.url_detail: row
        for row in rows
    }

    normal_1 = by_url[
        expected_urls[0]
    ]

    normal_2 = by_url[
        expected_urls[1]
    ]

    unpublished = by_url[
        expected_urls[2]
    ]

    # --------------------------------------------------------
    # Normal Putusan
    # --------------------------------------------------------

    assert normal_1.tahun == TEST_YEAR

    assert normal_1.halaman == 1

    assert normal_1.judul == (
        "Putusan Normal 1"
    )

    assert normal_1.status_scraping == (
        ScrapingStatus.PENDING
    )

    assert normal_1.url_pdf is None

    assert normal_1.retry_count == 0

    # --------------------------------------------------------

    assert normal_2.tahun == TEST_YEAR

    assert normal_2.halaman == 1

    assert normal_2.judul == (
        "Putusan Normal 2"
    )

    assert normal_2.status_scraping == (
        ScrapingStatus.PENDING
    )

    assert normal_2.url_pdf is None

    # --------------------------------------------------------
    # Unpublished
    # --------------------------------------------------------

    assert unpublished.tahun == TEST_YEAR

    assert unpublished.halaman == 1

    assert unpublished.judul == (
        "Putusan Unpublished 1"
    )

    assert unpublished.status_scraping == (
        ScrapingStatus.UNPUBLISHED
    )

    assert unpublished.url_pdf is None

    assert unpublished.retry_count == 0

    print(
        "8A.4 Putusan creation/state mapping: PASS"
    )


# ============================================================
# 8A.5
# DISPATCHER ELIGIBILITY
# ============================================================

def test_dispatcher_eligibility():
    expected_urls = [
        (
            f"{TEST_PREFIX}"
            "putusan/normal-1"
        ),
        (
            f"{TEST_PREFIX}"
            "putusan/normal-2"
        ),
        (
            f"{TEST_PREFIX}"
            "putusan/unpublished-1"
        ),
    ]

    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.url_detail.in_(
                        expected_urls
                    )
                )
                .order_by(
                    Putusan.id
                )
            ).all()
        )

    assert len(rows) == 3

    # --------------------------------------------------------
    # Normal Putusan harus eligible untuk dispatcher.
    #
    # Jangan menggunakan get_pending_putusan_ids() di sini
    # karena selector production bersifat GLOBAL dan memakai
    # LIMIT. Isi database test lain tidak boleh mempengaruhi
    # hasil test ini.
    # --------------------------------------------------------

    normal_rows = [
        row
        for row in rows
        if row.status_scraping
        == ScrapingStatus.PENDING
    ]

    assert len(normal_rows) == 2

    normal_ids = {
        row.id
        for row in normal_rows
    }

    # --------------------------------------------------------
    # Pastikan kedua normal Putusan benar-benar memenuhi
    # invariant eligibility.
    # --------------------------------------------------------

    for row in normal_rows:
        assert row.next_retry_at is None
        assert row.processing_worker_id is None
        assert row.processing_token is None

    # --------------------------------------------------------
    # Unpublished tidak boleh eligible.
    # --------------------------------------------------------

    unpublished_rows = [
        row
        for row in rows
        if row.status_scraping
        == ScrapingStatus.UNPUBLISHED
    ]

    assert len(unpublished_rows) == 1

    unpublished_id = unpublished_rows[0].id

    assert unpublished_id not in normal_ids

    print(
        "8A.5 Dispatcher eligibility invariant: PASS"
    )
# ============================================================
# 8A.6
# IDEMPOTENT DISCOVERY
# ============================================================

def test_idempotent_second_processing(
    page_job_id: int,
):
    """
    DiscoveryPageJob sudah SUCCESS.

    Worker tidak boleh memproses ulang job
    hanya karena task duplicate.

    Claim kedua harus gagal.
    """

    scraper = FakeDiscoveryScraper(
        build_discovery_result()
    )

    worker = DiscoveryPageWorker(
        scraper
    )

    claimed = worker.claim(
        page_job_id=page_job_id,
        worker_id=(
            "phase-8-duplicate-worker"
        ),
    )

    assert claimed is None

    with SessionLocal() as session:

        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.url_detail.like(
                        f"{TEST_PREFIX}putusan/%"
                    )
                )
                .order_by(
                    Putusan.id
                )
            ).all()
        )

    assert len(rows) == 3

    print(
        "8A.6 Duplicate DiscoveryPageJob blocked: PASS"
    )


# ============================================================
# CLEANUP
# ============================================================

def cleanup(
    page_job_id: int,
):
    from models.scraping_run import (
        ScrapingRun,
    )

    with SessionLocal.begin() as session:

        session.execute(
            delete(Putusan).where(
                Putusan.url_detail.like(
                    f"{TEST_PREFIX}putusan/%"
                )
            )
        )

        job = session.get(
            DiscoveryPageJob,
            page_job_id,
        )

        run_id = (
            job.run_id
            if job is not None
            else None
        )

        if job is not None:
            session.delete(job)

        if run_id is not None:
            run = session.get(
                ScrapingRun,
                run_id,
            )

            if run is not None:
                session.delete(run)

    print(
        f"Cleanup Phase 8 test job: "
        f"{page_job_id}"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print(
        "PHASE 8A - DISCOVERY -> PUTUSAN INTEGRATION"
    )
    print("=" * 70)

    print(
        f"ENV_FILE: "
        f"{os.getenv('ENV_FILE', '.env')}"
    )

    page_job_id = None

    try:

        # ----------------------------------------------------
        # 8A.1
        # ----------------------------------------------------

        page_job_id = (
            create_page_job_with_run()
        )

        claimed, scraper = test_claim(
            page_job_id
        )

        # ----------------------------------------------------
        # 8A.2
        # ----------------------------------------------------

        test_process_claimed(
            claimed,
            scraper,
        )

        # ----------------------------------------------------
        # 8A.3
        # ----------------------------------------------------

        test_page_job_success(
            page_job_id
        )

        # ----------------------------------------------------
        # 8A.4
        # ----------------------------------------------------

        test_putusan_created()

        # ----------------------------------------------------
        # 8A.5
        # ----------------------------------------------------

        test_dispatcher_eligibility()

        # ----------------------------------------------------
        # 8A.6
        # ----------------------------------------------------

        test_idempotent_second_processing(
            page_job_id
        )

        print()
        print("=" * 70)
        print("PHASE 8A: PASS")
        print("=" * 70)

    finally:

        if page_job_id is not None:
            cleanup(
                page_job_id
            )


if __name__ == "__main__":
    main()