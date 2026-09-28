import asyncio
from datetime import datetime, timezone

from models.putusan import Putusan, ScrapingStatus
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from scraper.detail_page import DetailScrapeResult, DetailScrapeStatus
from services.putusan_worker import ClaimedPutusan, PutusanWorker
from services.run_finalizer_service import RunFinalizerService
from database.session import SessionLocal


TEST_YEAR = 2091
PUTUSAN_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/putusan/2091/example-retry.html"
)


class FakeDetailScraper:
    def __init__(self, result: DetailScrapeResult):
        self.result = result

    async def scrape(self, browser, url_detail: str):
        return self.result


def seed_case() -> tuple[int, int, str]:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=TEST_YEAR,
            status=ScrapingRunStatus.DISCOVERY_COMPLETED,
            total_discovered=1,
        )
        session.add(run)
        session.flush()

        putusan = Putusan(
            tahun=TEST_YEAR,
            halaman=1,
            run_id=run.id,
            url_detail=PUTUSAN_URL,
            status_scraping=ScrapingStatus.PROCESSING,
            processing_worker_id="phase12-4-worker",
            processing_token="phase12-4-token",
            processing_started_at=datetime.now(timezone.utc),
            retry_count=0,
        )
        session.add(putusan)
        session.flush()

        return run.id, putusan.id, putusan.url_detail


async def run_test():
    run_id, putusan_id, url_detail = seed_case()

    retry_result = DetailScrapeResult(
        status=DetailScrapeStatus.RETRYABLE_ERROR,
        url_detail=url_detail,
        error_message="Simulated transient server error",
    )

    worker = PutusanWorker(
        FakeDetailScraper(retry_result)
    )

    claimed = ClaimedPutusan(
        putusan_id=putusan_id,
        url_detail=url_detail,
        processing_token="phase12-4-token",
    )

    result = await worker.process_claimed(
        browser=None,
        claimed=claimed,
        worker_id="phase12-4-worker",
    )

    assert result.status == DetailScrapeStatus.RETRYABLE_ERROR.value

    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)
        run = session.get(ScrapingRun, run_id)

        assert putusan is not None
        assert run is not None

        assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY
        assert putusan.last_error == "Simulated transient server error"

        assert run.status == ScrapingRunStatus.DISCOVERY_COMPLETED

        print("12.4A Putusan -> FAILED_RETRY: PASS")
        print("12.4B Run tetap DISCOVERY_COMPLETED: PASS")

    # Simulasikan retry berikutnya berhasil.

    with SessionLocal.begin() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None

        putusan.status_scraping = ScrapingStatus.PROCESSING
        putusan.processing_worker_id = "phase12-4-retry-worker"
        putusan.processing_token = "phase12-4-retry-token"
        putusan.processing_started_at = datetime.now(timezone.utc)
        putusan.next_retry_at = None

        session.flush()


    success_result = DetailScrapeResult(
        status=DetailScrapeStatus.SUCCESS,
        url_detail=url_detail,
        url_pdf=(
            "https://putusan3.mahkamahagung.go.id/"
            "pdf/example-retry.pdf"
        ),
    )

    retry_worker = PutusanWorker(
        FakeDetailScraper(success_result)
    )

    retry_claimed = ClaimedPutusan(
        putusan_id=putusan_id,
        url_detail=url_detail,
        processing_token="phase12-4-retry-token",
    )

    retry_process_result = await retry_worker.process_claimed(
        browser=None,
        claimed=retry_claimed,
        worker_id="phase12-4-retry-worker",
    )

    assert (
        retry_process_result.status
        == DetailScrapeStatus.SUCCESS.value
    )

    print("12.4C Retry SUCCESS -> Putusan SUCCESS: PASS")


    with SessionLocal() as session:
        run = session.get(ScrapingRun, run_id)

        assert run is not None
        assert run.status == ScrapingRunStatus.COMPLETED
        assert run.finished_at is not None

        print("12.4D Retry SUCCESS -> Run COMPLETED: PASS")


def cleanup():
    with SessionLocal.begin() as session:
        putusan = session.query(Putusan).filter(
            Putusan.tahun == TEST_YEAR
        ).delete()

        run = session.query(ScrapingRun).filter(
            ScrapingRun.tahun == TEST_YEAR
        ).delete()

        print(
            f"Cleanup Phase 12-4: "
            f"putusan={putusan}, runs={run}"
        )


if __name__ == "__main__":
    try:
        asyncio.run(run_test())

        print(
            "PHASE 12-4 PUTUSAN RETRY LIFECYCLE: PASS"
        )
    finally:
        cleanup()