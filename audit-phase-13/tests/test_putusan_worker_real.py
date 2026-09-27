from __future__ import annotations

import asyncio

import nodriver as uc

from database.session import SessionLocal
from services.putusan_worker import build_putusan_worker
from models.putusan import (
    Putusan,
    ScrapingStatus,
)


PUTUSAN_ID = 127
WORKER_ID = "manual-test-worker"


def reset_putusan_for_test(putusan_id: int) -> str:
    """
    Hanya untuk test manual.

    Mengembalikan Putusan ke PENDING supaya worker
    dapat melakukan claim.
    """
    with SessionLocal.begin() as session:
        putusan = session.get(
            Putusan,
            putusan_id,
        )

        if putusan is None:
            raise RuntimeError(
                f"Putusan ID {putusan_id} tidak ditemukan."
            )

        print(
            f"[DB BEFORE] "
            f"id={putusan.id} "
            f"status={putusan.status_scraping.value} "
            f"url_pdf={putusan.url_pdf}"
        )

        putusan.status_scraping = ScrapingStatus.PENDING
        putusan.processing_started_at = None
        putusan.processing_worker_id = None
        putusan.processing_token = None
        putusan.next_retry_at = None
        putusan.last_error = None

        return putusan.url_detail


def read_putusan(putusan_id: int) -> None:
    with SessionLocal() as session:
        putusan = session.get(
            Putusan,
            putusan_id,
        )

        if putusan is None:
            print(
                f"[DB AFTER] "
                f"Putusan ID {putusan_id} tidak ditemukan."
            )
            return

        print()
        print("=" * 80)
        print("DATABASE AFTER")
        print("=" * 80)
        print(
            f"id                  : "
            f"{putusan.id}"
        )
        print(
            f"status_scraping      : "
            f"{putusan.status_scraping.value}"
        )
        print(
            f"url_detail           : "
            f"{putusan.url_detail}"
        )
        print(
            f"url_pdf              : "
            f"{putusan.url_pdf}"
        )
        print(
            f"retry_count          : "
            f"{putusan.retry_count}"
        )
        print(
            f"last_error           : "
            f"{putusan.last_error}"
        )
        print(
            f"processing_worker_id  : "
            f"{putusan.processing_worker_id}"
        )
        print(
            f"processing_token     : "
            f"{putusan.processing_token}"
        )
        print("=" * 80)


async def main() -> None:
    url_detail = reset_putusan_for_test(
        PUTUSAN_ID
    )

    print()
    print("=" * 80)
    print("PUTUSAN WORKER REAL TEST")
    print("=" * 80)
    print(f"PUTUSAN ID : {PUTUSAN_ID}")
    print(f"URL DETAIL : {url_detail}")
    print("=" * 80)

    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    try:
        worker = build_putusan_worker()

        result = await worker.process(
            browser,
            putusan_id=PUTUSAN_ID,
            worker_id=WORKER_ID,
        )

        print()
        print("=" * 80)
        print("WORKER RESULT")
        print("=" * 80)
        print(
            f"putusan_id   : "
            f"{result.putusan_id}"
        )
        print(
            f"status       : "
            f"{result.status}"
        )
        print(
            f"url_detail   : "
            f"{result.url_detail}"
        )
        print(
            f"url_pdf      : "
            f"{result.url_pdf}"
        )
        print(
            f"error_message: "
            f"{result.error_message}"
        )
        print("=" * 80)

    finally:
        browser.stop()

    read_putusan(PUTUSAN_ID)


if __name__ == "__main__":
    asyncio.run(main())