from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import mark_putusan_success
from scraper.detail_page import (
    DetailScrapeResult,
    DetailScrapeStatus,
)
from services.putusan_worker import PutusanWorker


YEAR = 2021


def make_url(label: str) -> str:
    return (
        "https://putusan3.mahkamahagung.go.id/"
        f"direktori/putusan/test-detail-worker-{label}-{uuid4()}.html"
    )


def create_putusan(url_detail: str, *, judul: str) -> int:
    with SessionLocal.begin() as session:
        putusan = Putusan(
            tahun=YEAR,
            halaman=None,
            url_detail=url_detail,
            judul=judul,
            status_scraping=ScrapingStatus.PENDING,
        )

        session.add(putusan)
        session.flush()

        return putusan.id


def get_putusan(putusan_id: int) -> Putusan | None:
    with SessionLocal() as session:
        return session.get(Putusan, putusan_id)


def cleanup(put_ids: list[int]) -> None:
    if not put_ids:
        return

    with SessionLocal.begin() as session:
        rows = session.scalars(
            select(Putusan).where(
                Putusan.id.in_(put_ids)
            )
        ).all()

        for row in rows:
            session.delete(row)


class FakeBrowser:
    """
    Browser dummy.

    PutusanWorker tetap menerima object browser,
    tetapi FakeDetailScraper tidak menggunakannya.
    """

    pass


class FakeDetailScraper:
    """
    Scraper dummy untuk menguji lifecycle worker.

    Tidak membuka website.
    """

    def __init__(self, result: DetailScrapeResult):
        self.result = result

    async def scrape(
        self,
        browser,
        *,
        url_detail: str,
    ) -> DetailScrapeResult:
        return self.result


async def test_unpublished(
    browser,
    created_ids: list[int],
) -> None:
    url_detail = make_url("unpublished")

    putusan_id = create_putusan(
        url_detail,
        judul="TEST UNPUBLISHED",
    )
    created_ids.append(putusan_id)

    scraper = FakeDetailScraper(
        DetailScrapeResult(
            status=DetailScrapeStatus.UNPUBLISHED,
            url_detail=url_detail,
        )
    )

    worker = PutusanWorker(scraper)

    result = await worker.process(
        browser,
        putusan_id=putusan_id,
        worker_id=f"test-unpublished-{uuid4()}",
    )

    assert result.status == DetailScrapeStatus.UNPUBLISHED.value

    putusan = get_putusan(putusan_id)

    assert putusan is not None
    assert putusan.status_scraping == ScrapingStatus.UNPUBLISHED
    assert putusan.url_pdf is None
    assert putusan.processing_token is None
    assert putusan.processing_worker_id is None
    assert putusan.processing_started_at is None

    print("UNPUBLISHED RESULT: PASS")
    print("STATUS = UNPUBLISHED: PASS")
    print("URL_PDF = NULL: PASS")
    print("PROCESSING TOKEN CLEARED: PASS")
    print("WORKER ID CLEARED: PASS")
    print("PROCESSING LEASE CLEARED: PASS")


async def test_retryable_error(
    browser,
    created_ids: list[int],
) -> None:
    url_detail = make_url("retryable")

    putusan_id = create_putusan(
        url_detail,
        judul="TEST RETRYABLE ERROR",
    )
    created_ids.append(putusan_id)

    scraper = FakeDetailScraper(
        DetailScrapeResult(
            status=DetailScrapeStatus.RETRYABLE_ERROR,
            url_detail=url_detail,
            error_message="500 - Exception Error",
        )
    )

    worker = PutusanWorker(scraper)

    result = await worker.process(
        browser,
        putusan_id=putusan_id,
        worker_id=f"test-retryable-{uuid4()}",
    )

    assert result.status == DetailScrapeStatus.RETRYABLE_ERROR.value

    putusan = get_putusan(putusan_id)

    assert putusan is not None
    assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY
    assert putusan.retry_count == 1
    assert putusan.last_error == "500 - Exception Error"
    assert putusan.next_retry_at is not None
    assert putusan.processing_token is None
    assert putusan.processing_worker_id is None
    assert putusan.processing_started_at is None

    print("RETRYABLE ERROR RESULT: PASS")
    print("STATUS = FAILED_RETRY: PASS")
    print("RETRY COUNT = 1: PASS")
    print("LAST ERROR PERSISTED: PASS")
    print("NEXT RETRY AT SET: PASS")
    print("PROCESSING TOKEN CLEARED: PASS")
    print("WORKER ID CLEARED: PASS")
    print("PROCESSING LEASE CLEARED: PASS")


def test_processing_token_ownership(
    created_ids: list[int],
) -> None:
    url_detail = make_url("token-ownership")

    putusan_id = create_putusan(
        url_detail,
        judul="TEST TOKEN OWNERSHIP",
    )
    created_ids.append(putusan_id)

    worker_a = f"worker-a-{uuid4()}"
    worker_b = f"worker-b-{uuid4()}"

    # ------------------------------------------------------------
    # Worker A claim
    # ------------------------------------------------------------

    with SessionLocal.begin() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None

        from repositories.putusan_repository import claim_putusan_by_id

        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_a,
        )

        assert claimed is not None
        assert claimed.status_scraping == ScrapingStatus.PROCESSING

        token_a = claimed.processing_token

        assert token_a is not None

    # ------------------------------------------------------------
    # Worker B tidak boleh claim row yang masih PROCESSING
    # ------------------------------------------------------------

    with SessionLocal.begin() as session:
        from repositories.putusan_repository import claim_putusan_by_id

        claimed_by_b = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_b,
        )

        assert claimed_by_b is None

    print("WORKER B CANNOT CLAIM ACTIVE ROW: PASS")

    # ------------------------------------------------------------
    # Worker A masih owner
    # ------------------------------------------------------------

    with SessionLocal.begin() as session:
        mark_putusan_success(
            session,
            putusan_id=putusan_id,
            worker_id=worker_a,
            processing_token=token_a,
            url_pdf="https://example.test/file.pdf",
        )

    putusan = get_putusan(putusan_id)

    assert putusan is not None
    assert putusan.status_scraping == ScrapingStatus.SUCCESS
    assert putusan.url_pdf == "https://example.test/file.pdf"
    assert putusan.processing_token is None
    assert putusan.processing_worker_id is None

    print("OWNER CAN MARK SUCCESS: PASS")
    print("URL_PDF PERSISTED: PASS")

    # ------------------------------------------------------------
    # Worker A mencoba menggunakan token lama lagi.
    # Harus ditolak.
    # ------------------------------------------------------------

    old_token_rejected = False

    try:
        with SessionLocal.begin() as session:
            mark_putusan_success(
                session,
                putusan_id=putusan_id,
                worker_id=worker_a,
                processing_token=token_a,
                url_pdf="https://example.test/another-file.pdf",
            )
    except RuntimeError:
        old_token_rejected = True

    assert old_token_rejected

    putusan = get_putusan(putusan_id)

    assert putusan is not None
    assert putusan.status_scraping == ScrapingStatus.SUCCESS
    assert putusan.url_pdf == "https://example.test/file.pdf"

    print("OLD PROCESSING TOKEN REJECTED: PASS")
    print("ORIGINAL SUCCESS RESULT PRESERVED: PASS")


async def main() -> None:
    created_ids: list[int] = []

    print("=" * 70)
    print("DETAIL WORKER LIFECYCLE TEST")
    print("=" * 70)

    browser = FakeBrowser()

    try:
        print()
        print("-" * 70)
        print("TEST 1: UNPUBLISHED")
        print("-" * 70)

        await test_unpublished(
            browser,
            created_ids,
        )

        print()
        print("-" * 70)
        print("TEST 2: RETRYABLE ERROR")
        print("-" * 70)

        await test_retryable_error(
            browser,
            created_ids,
        )

        print()
        print("-" * 70)
        print("TEST 3: PROCESSING TOKEN OWNERSHIP")
        print("-" * 70)

        test_processing_token_ownership(
            created_ids,
        )

        print()
        print("=" * 70)
        print("DETAIL WORKER LIFECYCLE TEST: PASS")
        print("=" * 70)

    finally:
        cleanup(created_ids)

        print()
        print("TEST ROWS DELETED:", len(created_ids))


if __name__ == "__main__":
    asyncio.run(main())