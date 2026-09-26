from __future__ import annotations

import asyncio

import nodriver as uc

from database.session import SessionLocal
from models.putusan import Putusan
from scraper.detail_page import DetailPageScraper


PUTUSAN_IDS = [
    126,
    127,
    128,
]


def get_putusan_urls(
    putusan_ids: list[int],
) -> dict[int, str]:
    with SessionLocal() as session:
        rows = (
            session.query(Putusan)
            .filter(Putusan.id.in_(putusan_ids))
            .order_by(Putusan.id)
            .all()
        )

        result = {
            row.id: row.url_detail
            for row in rows
        }

        missing_ids = [
            putusan_id
            for putusan_id in putusan_ids
            if putusan_id not in result
        ]

        if missing_ids:
            raise RuntimeError(
                "Putusan ID tidak ditemukan: "
                f"{missing_ids}"
            )

        return result


async def main() -> None:
    urls = get_putusan_urls(
        PUTUSAN_IDS
    )

    print("=" * 80)
    print("DETAIL BATCH TEST")
    print("=" * 80)

    for putusan_id in PUTUSAN_IDS:
        print(
            f"ID {putusan_id}: "
            f"{urls[putusan_id]}"
        )

    print("=" * 80)

    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    scraper = DetailPageScraper(
        initial_wait_seconds=5.0,
        retry_wait_seconds=5.0,
        max_wait_seconds=20.0,
    )

    try:
        results = []

        for putusan_id in PUTUSAN_IDS:
            url_detail = urls[putusan_id]

            print()
            print("=" * 80)
            print(
                f"MEMPROSES PUTUSAN ID {putusan_id}"
            )
            print("=" * 80)

            result = await scraper.scrape(
                browser,
                url_detail=url_detail,
            )

            results.append(
                (
                    putusan_id,
                    result,
                )
            )

            print(
                f"ID           : {putusan_id}"
            )
            print(
                f"status       : "
                f"{result.status.value}"
            )
            print(
                f"url_pdf      : "
                f"{result.url_pdf}"
            )
            print(
                f"error_message: "
                f"{result.error_message}"
            )

        print()
        print("=" * 80)
        print("RINGKASAN BATCH TEST")
        print("=" * 80)

        for putusan_id, result in results:
            print(
                f"{putusan_id}: "
                f"{result.status.value} | "
                f"{result.url_pdf}"
            )

        print("=" * 80)

    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())