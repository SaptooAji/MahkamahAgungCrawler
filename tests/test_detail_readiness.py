from __future__ import annotations

import asyncio

import nodriver as uc

from database.session import SessionLocal
from scraper.detail_page import DetailPageScraper


PUTUSAN_ID = 127


def get_url_detail(putusan_id: int) -> str:
    with SessionLocal() as session:
        from models.putusan import Putusan

        putusan = session.get(Putusan, putusan_id)

        if putusan is None:
            raise RuntimeError(
                f"Putusan ID {putusan_id} tidak ditemukan."
            )

        return putusan.url_detail


async def main() -> None:
    url_detail = get_url_detail(PUTUSAN_ID)

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
        scraper = DetailPageScraper(
            render_wait_seconds=2.0,
            max_wait_seconds=20.0,
        )

        result = await scraper.scrape(
            browser,
            url_detail=url_detail,
        )

        print()
        print("=" * 80)
        print("HASIL SCRAPE")
        print("=" * 80)
        print(f"status       : {result.status.value}")
        print(f"url_detail   : {result.url_detail}")
        print(f"url_pdf      : {result.url_pdf}")
        print(f"error_message: {result.error_message}")
        print("=" * 80)

    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())