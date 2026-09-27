from __future__ import annotations

import asyncio
from uuid import uuid4

import nodriver as uc

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from scraper.detail_page import DetailPageScraper
from services.putusan_worker import build_putusan_worker
from sqlalchemy import select


URL_DETAIL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/putusan/zaf1b893e1c591d2b0aa313034373531.html"
)

WORKER_ID = f"manual-detail-test-{uuid4()}"


async def main() -> None:
    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    try:
        # ------------------------------------------------------------
        # Cari / buat Putusan berdasarkan URL detail.
        # ------------------------------------------------------------

        with SessionLocal.begin() as session:
            putusan = session.scalar(
                select(Putusan).where(
                    Putusan.url_detail == URL_DETAIL
                )
            )

            if putusan is None:
                raise RuntimeError(
                    "Putusan dengan URL detail tersebut belum ada di DB. "
                    "Jalankan discovery terlebih dahulu."
                )

            putusan_id = putusan.id

            print("=" * 70)
            print("BEFORE")
            print("=" * 70)
            print("Putusan ID :", putusan.id)
            print("URL detail :", putusan.url_detail)
            print("Status     :", putusan.status_scraping)
            print("URL PDF    :", putusan.url_pdf)

        # ------------------------------------------------------------
        # Process
        # ------------------------------------------------------------

        scraper = DetailPageScraper(
            render_wait_seconds=5.0,
        )

        worker = build_putusan_worker(scraper)

        result = await worker.process(
            browser,
            putusan_id=putusan_id,
            worker_id=WORKER_ID,
        )

        print()
        print("=" * 70)
        print("WORKER RESULT")
        print("=" * 70)
        print("Putusan ID :", result.putusan_id)
        print("Status     :", result.status)
        print("URL detail :", result.url_detail)
        print("URL PDF    :", result.url_pdf)
        print("Error      :", result.error_message)

        # ------------------------------------------------------------
        # Verify DB
        # ------------------------------------------------------------

        with SessionLocal() as session:
            putusan = session.get(Putusan, putusan_id)

            if putusan is None:
                raise RuntimeError(
                    "Putusan hilang setelah processing."
                )

            print()
            print("=" * 70)
            print("AFTER")
            print("=" * 70)
            print("Putusan ID :", putusan.id)
            print("Status     :", putusan.status_scraping)
            print("URL PDF    :", putusan.url_pdf)
            print("Error      :", putusan.last_error)
            print("Token      :", putusan.processing_token)
            print("Worker     :", putusan.processing_worker_id)

            if result.status == "SUCCESS":
                assert putusan.status_scraping == ScrapingStatus.SUCCESS
                assert putusan.url_pdf is not None

                print()
                print("STATUS = SUCCESS: PASS")
                print("URL_PDF tersimpan: PASS")

            elif result.status == "UNPUBLISHED":
                assert putusan.status_scraping == ScrapingStatus.UNPUBLISHED

                print()
                print("STATUS = UNPUBLISHED: PASS")

            else:
                assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY

                print()
                print("STATUS = FAILED_RETRY: PASS")

            assert putusan.processing_token is None
            assert putusan.processing_worker_id is None

            print("PROCESSING TOKEN CLEARED: PASS")
            print("WORKER ID CLEARED: PASS")

    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())