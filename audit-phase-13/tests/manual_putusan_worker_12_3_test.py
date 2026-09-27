from __future__ import annotations

import asyncio

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from scraper.detail_page import DetailScrapeResult, DetailScrapeStatus
from services.putusan_worker import (
    ClaimedPutusan,
    PutusanWorker,
)


class FakeDetailScraper:
    def __init__(self, result: DetailScrapeResult):
        self.result = result

    async def scrape(
        self,
        browser,
        *,
        url_detail: str,
    ) -> DetailScrapeResult:
        return self.result


def seed_success_case() -> tuple[int, int]:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=2093,
            status=ScrapingRunStatus.RUNNING,
        )
        session.add(run)
        session.flush()

        putusan = Putusan(
            tahun=2093,
            halaman=1,
            url_detail=(
                "https://putusan3.mahkamahagung.go.id/"
                "direktori/putusan/2093-test-success.html"
            ),
            status_scraping=ScrapingStatus.PROCESSING,
            processing_worker_id="phase12-3-worker",
            processing_token="phase12-3-token-success",
        )
        session.add(putusan)
        session.flush()

        return run.id, putusan.id


def seed_unpublished_case() -> tuple[int, int]:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=2092,
            status=ScrapingRunStatus.RUNNING,
        )
        session.add(run)
        session.flush()

        putusan = Putusan(
            tahun=2092,
            halaman=1,
            url_detail=(
                "https://putusan3.mahkamahagung.go.id/"
                "direktori/putusan/2092-test-unpublished.html"
            ),
            status_scraping=ScrapingStatus.PROCESSING,
            processing_worker_id="phase12-3-worker",
            processing_token="phase12-3-token-unpublished",
        )
        session.add(putusan)
        session.flush()

        return run.id, putusan.id


async def run_success_case() -> None:
    run_id, putusan_id = seed_success_case()

    url_detail = (
        "https://putusan3.mahkamahagung.go.id/"
        "direktori/putusan/2093-test-success.html"
    )

    result = DetailScrapeResult(
        status=DetailScrapeStatus.SUCCESS,
        url_detail=url_detail,
        url_pdf=(
            "https://putusan3.mahkamahagung.go.id/"
            "direktori/download_file/test/pdf/2093-test.pdf"
        ),
    )

    worker = PutusanWorker(
        FakeDetailScraper(result)
    )

    claimed = ClaimedPutusan(
        putusan_id=putusan_id,
        url_detail=url_detail,
        processing_token="phase12-3-token-success",
    )

    process_result = await worker.process_claimed(
        browser=None,
        claimed=claimed,
        worker_id="phase12-3-worker",
    )

    assert process_result.status == "SUCCESS"
    assert process_result.url_pdf is not None

    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)
        run = session.get(ScrapingRun, run_id)

        assert putusan is not None
        assert run is not None

        assert putusan.status_scraping == ScrapingStatus.SUCCESS
        assert putusan.url_pdf == result.url_pdf
        assert run.status == ScrapingRunStatus.COMPLETED
        assert run.finished_at is not None

    print("12.3A SUCCESS -> Putusan SUCCESS: PASS")
    print("12.3A SUCCESS -> Run COMPLETED: PASS")


async def run_unpublished_case() -> None:
    run_id, putusan_id = seed_unpublished_case()

    url_detail = (
        "https://putusan3.mahkamahagung.go.id/"
        "direktori/putusan/2092-test-unpublished.html"
    )

    result = DetailScrapeResult(
        status=DetailScrapeStatus.UNPUBLISHED,
        url_detail=url_detail,
        error_message=None,
    )

    worker = PutusanWorker(
        FakeDetailScraper(result)
    )

    claimed = ClaimedPutusan(
        putusan_id=putusan_id,
        url_detail=url_detail,
        processing_token="phase12-3-token-unpublished",
    )

    process_result = await worker.process_claimed(
        browser=None,
        claimed=claimed,
        worker_id="phase12-3-worker",
    )

    assert process_result.status == "UNPUBLISHED"

    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)
        run = session.get(ScrapingRun, run_id)

        assert putusan is not None
        assert run is not None

        assert putusan.status_scraping == ScrapingStatus.UNPUBLISHED
        assert run.status == ScrapingRunStatus.COMPLETED
        assert run.finished_at is not None

    print("12.3B UNPUBLISHED -> Putusan UNPUBLISHED: PASS")
    print("12.3B UNPUBLISHED -> Run COMPLETED: PASS")


def cleanup() -> None:
    with SessionLocal.begin() as session:
        session.query(Putusan).filter(
            Putusan.tahun.in_([2092, 2093])
        ).delete(synchronize_session=False)

        session.query(ScrapingRun).filter(
            ScrapingRun.tahun.in_([2092, 2093])
        ).delete(synchronize_session=False)


async def main() -> None:
    try:
        await run_success_case()
        await run_unpublished_case()

        print("PHASE 12-3 PUTUSAN WORKER INTEGRATION: PASS")
    finally:
        cleanup()
        print("Cleanup Phase 12-3 test years: 2092, 2093")


if __name__ == "__main__":
    asyncio.run(main())