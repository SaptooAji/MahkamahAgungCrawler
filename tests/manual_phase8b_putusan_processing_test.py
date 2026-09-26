from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from scraper.detail_page import DetailScrapeResult, DetailScrapeStatus
from services.putusan_worker import PutusanWorker


TEST_YEAR = 2098
TEST_PREFIX = "https://phase8b.test/putusan/"
WORKER_ID = "phase-8b-worker"


@dataclass
class FakeDetailScraper:
    result: DetailScrapeResult | None = None
    exception: Exception | None = None

    async def scrape(self, browser, *, url_detail: str):
        if self.exception is not None:
            raise self.exception

        if self.result is None:
            raise RuntimeError("FakeDetailScraper result belum dikonfigurasi.")

        return DetailScrapeResult(
            status=self.result.status,
            url_detail=url_detail,
            url_pdf=self.result.url_pdf,
            error_message=self.result.error_message,
        )


def seed_putusan(url_detail: str) -> int:
    with SessionLocal.begin() as session:
        row = Putusan(
            tahun=TEST_YEAR,
            halaman=1,
            url_detail=url_detail,
            judul="Phase 8B Test",
            status_scraping=ScrapingStatus.PENDING,
        )
        session.add(row)
        session.flush()
        return row.id


def load_putusan(putusan_id: int) -> Putusan:
    with SessionLocal() as session:
        row = session.get(Putusan, putusan_id)
        if row is None:
            raise AssertionError(f"Putusan {putusan_id} tidak ditemukan.")
        return row


def cleanup(ids: list[int]) -> None:
    if not ids:
        return

    with SessionLocal.begin() as session:
        rows = list(
            session.scalars(
                select(Putusan).where(Putusan.id.in_(ids))
            ).all()
        )
        for row in rows:
            session.delete(row)


def test_success() -> int:
    putusan_id = seed_putusan(TEST_PREFIX + "success")

    scraper = FakeDetailScraper(
        result=DetailScrapeResult(
            status=DetailScrapeStatus.SUCCESS,
            url_detail=TEST_PREFIX + "success",
            url_pdf="https://phase8b.test/pdf/success.pdf",
        )
    )
    worker = PutusanWorker(scraper)

    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=WORKER_ID,
    )
    assert claimed is not None

    processing = load_putusan(putusan_id)
    assert processing.status_scraping == ScrapingStatus.PROCESSING
    assert processing.processing_worker_id == WORKER_ID
    assert processing.processing_token == claimed.processing_token

    result = asyncio.run(
        worker.process_claimed(
            browser=object(),
            claimed=claimed,
            worker_id=WORKER_ID,
        )
    )

    assert result.status == DetailScrapeStatus.SUCCESS.value
    assert result.url_pdf == "https://phase8b.test/pdf/success.pdf"

    row = load_putusan(putusan_id)
    assert row.status_scraping == ScrapingStatus.SUCCESS
    assert row.url_pdf == "https://phase8b.test/pdf/success.pdf"
    assert row.last_error is None
    assert row.processing_worker_id is None
    assert row.processing_token is None
    assert row.processing_started_at is None
    assert row.next_retry_at is None

    print("8B.1 SUCCESS lifecycle: PASS")
    return putusan_id


def test_unpublished() -> int:
    putusan_id = seed_putusan(TEST_PREFIX + "unpublished")

    scraper = FakeDetailScraper(
        result=DetailScrapeResult(
            status=DetailScrapeStatus.UNPUBLISHED,
            url_detail=TEST_PREFIX + "unpublished",
            error_message="Belum dipublikasikan.",
        )
    )
    worker = PutusanWorker(scraper)

    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=WORKER_ID,
    )
    assert claimed is not None

    result = asyncio.run(
        worker.process_claimed(
            browser=object(),
            claimed=claimed,
            worker_id=WORKER_ID,
        )
    )

    assert result.status == DetailScrapeStatus.UNPUBLISHED.value
    assert result.error_message == "Belum dipublikasikan."

    row = load_putusan(putusan_id)
    assert row.status_scraping == ScrapingStatus.UNPUBLISHED
    assert row.url_pdf is None
    assert row.last_error == "Belum dipublikasikan."
    assert row.processing_worker_id is None
    assert row.processing_token is None
    assert row.next_retry_at is None

    print("8B.2 UNPUBLISHED lifecycle: PASS")
    return putusan_id


def test_retryable_result() -> int:
    putusan_id = seed_putusan(TEST_PREFIX + "retryable")

    scraper = FakeDetailScraper(
        result=DetailScrapeResult(
            status=DetailScrapeStatus.RETRYABLE_ERROR,
            url_detail=TEST_PREFIX + "retryable",
            error_message="500 - Exception Error",
        )
    )
    worker = PutusanWorker(scraper)

    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=WORKER_ID,
    )
    assert claimed is not None

    before = datetime.now(timezone.utc)

    result = asyncio.run(
        worker.process_claimed(
            browser=object(),
            claimed=claimed,
            worker_id=WORKER_ID,
        )
    )

    assert result.status == DetailScrapeStatus.RETRYABLE_ERROR.value
    assert result.error_message == "500 - Exception Error"

    row = load_putusan(putusan_id)
    assert row.status_scraping == ScrapingStatus.FAILED_RETRY
    assert row.retry_count == 1
    assert row.last_error == "500 - Exception Error"
    assert row.processing_worker_id is None
    assert row.processing_token is None
    assert row.processing_started_at is None
    assert row.next_retry_at is not None
    assert row.next_retry_at >= before + timedelta(seconds=299)

    print("8B.3 RETRYABLE_ERROR lifecycle: PASS")
    return putusan_id


def test_scraper_exception() -> int:
    putusan_id = seed_putusan(TEST_PREFIX + "exception")

    scraper = FakeDetailScraper(
        exception=RuntimeError("browser crashed")
    )
    worker = PutusanWorker(scraper)

    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=WORKER_ID,
    )
    assert claimed is not None

    try:
        asyncio.run(
            worker.process_claimed(
                browser=object(),
                claimed=claimed,
                worker_id=WORKER_ID,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "browser crashed"
    else:
        raise AssertionError(
            "process_claimed() seharusnya meneruskan exception scraper."
        )

    row = load_putusan(putusan_id)
    assert row.status_scraping == ScrapingStatus.FAILED_RETRY
    assert row.retry_count == 1
    assert row.last_error == "RuntimeError: browser crashed"
    assert row.processing_worker_id is None
    assert row.processing_token is None
    assert row.processing_started_at is None
    assert row.next_retry_at is not None

    print("8B.4 Scraper exception -> FAILED_RETRY: PASS")
    return putusan_id


def test_pdf_not_found() -> int:
    putusan_id = seed_putusan(TEST_PREFIX + "pdf-not-found")

    scraper = FakeDetailScraper(
        result=DetailScrapeResult(
            status=DetailScrapeStatus.PDF_NOT_FOUND,
            url_detail=TEST_PREFIX + "pdf-not-found",
            error_message="Link PDF tidak ditemukan.",
        )
    )
    worker = PutusanWorker(scraper)

    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=WORKER_ID,
    )
    assert claimed is not None

    result = asyncio.run(
        worker.process_claimed(
            browser=object(),
            claimed=claimed,
            worker_id=WORKER_ID,
        )
    )

    assert result.status == DetailScrapeStatus.PDF_NOT_FOUND.value

    row = load_putusan(putusan_id)
    assert row.status_scraping == ScrapingStatus.FAILED_RETRY
    assert row.retry_count == 1
    assert row.last_error == "Link PDF tidak ditemukan."
    assert row.processing_worker_id is None
    assert row.processing_token is None
    assert row.next_retry_at is not None

    print("8B.5 PDF_NOT_FOUND -> FAILED_RETRY: PASS")
    return putusan_id


def test_claim_blocked_after_success() -> int:
    putusan_id = seed_putusan(TEST_PREFIX + "terminal")

    scraper = FakeDetailScraper(
        result=DetailScrapeResult(
            status=DetailScrapeStatus.SUCCESS,
            url_detail=TEST_PREFIX + "terminal",
            url_pdf="https://phase8b.test/pdf/terminal.pdf",
        )
    )
    worker = PutusanWorker(scraper)

    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=WORKER_ID,
    )
    assert claimed is not None

    asyncio.run(
        worker.process_claimed(
            browser=object(),
            claimed=claimed,
            worker_id=WORKER_ID,
        )
    )

    second_claim = worker.claim(
        putusan_id=putusan_id,
        worker_id="phase-8b-other-worker",
    )
    assert second_claim is None

    row = load_putusan(putusan_id)
    assert row.status_scraping == ScrapingStatus.SUCCESS
    assert row.url_pdf == "https://phase8b.test/pdf/terminal.pdf"

    print("8B.6 SUCCESS remains terminal / second claim blocked: PASS")
    return putusan_id


def main() -> None:
    print("=" * 70)
    print("PHASE 8B - PUTUSAN PROCESSING INTEGRATION")
    print("=" * 70)
    print("ENV_FILE:", os.getenv("ENV_FILE"))

    ids: list[int] = []

    try:
        ids.append(test_success())
        ids.append(test_unpublished())
        ids.append(test_retryable_result())
        ids.append(test_scraper_exception())
        ids.append(test_pdf_not_found())
        ids.append(test_claim_blocked_after_success())

        print()
        print("=" * 70)
        print("PHASE 8B: PASS")
        print("=" * 70)

    finally:
        cleanup(ids)
        print("Cleanup Phase 8B Putusan IDs:", ids)


if __name__ == "__main__":
    main()
