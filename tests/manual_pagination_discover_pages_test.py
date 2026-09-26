
import asyncio
import sys

import nodriver as uc

from scraper.pagination import (
    PaginationMode,
    PaginationScraper,
)


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


URL_PAGE_1 = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/tahun/2021.html"
)


async def main():
    browser = None

    try:
        print("=" * 70)
        print("DISCOVER PAGES TEST")
        print("=" * 70)

        browser = await uc.start(
            headless=False,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )

        scraper = PaginationScraper(
            render_wait_seconds=5.0
        )

        result = await scraper.discover_pages(
            browser,
            url_page_1=URL_PAGE_1,
        )

        print()
        print("RESULT")
        print("-" * 70)

        print(
            f"Mode        : {result.mode.value}"
        )

        print(
            f"Total pages : {result.total_pages}"
        )

        print(
            f"Descriptors : {len(result.pages)}"
        )

        print()
        print("FIRST 5")
        print("-" * 70)

        for descriptor in result.pages[:5]:
            print(
                f"page={descriptor.page_number} "
                f"url={descriptor.url_page}"
            )

        print()
        print("LAST 5")
        print("-" * 70)

        for descriptor in result.pages[-5:]:
            print(
                f"page={descriptor.page_number} "
                f"url={descriptor.url_page}"
            )

        print()
        print("ASSERTIONS")
        print("-" * 70)

        # ---------------------------------------------------------
        # Mode
        # ---------------------------------------------------------

        assert (
            result.mode
            == PaginationMode.PREDICTIVE
        )

        print(
            "MODE = PREDICTIVE: PASS"
        )

        # ---------------------------------------------------------
        # Total pages
        # ---------------------------------------------------------

        assert result.total_pages == 499

        print(
            "TOTAL PAGES = 499: PASS"
        )

        # ---------------------------------------------------------
        # Descriptor count
        # ---------------------------------------------------------

        assert len(result.pages) == 499

        print(
            "DESCRIPTORS = 499: PASS"
        )

        # ---------------------------------------------------------
        # Page numbers
        # ---------------------------------------------------------

        page_numbers = [
            descriptor.page_number
            for descriptor in result.pages
        ]

        assert page_numbers == list(
            range(1, 500)
        )

        print(
            "PAGE NUMBERS = 1..499: PASS"
        )

        # ---------------------------------------------------------
        # Page 1
        # ---------------------------------------------------------

        assert (
            result.pages[0].page_number
            == 1
        )

        print(
            "PAGE 1 NUMBER = 1: PASS"
        )

        assert (
            result.pages[0].url_page
            == URL_PAGE_1
        )

        print(
            "PAGE 1 USES CANONICAL URL: PASS"
        )

        # ---------------------------------------------------------
        # Tidak boleh ada /page/1.html
        # ---------------------------------------------------------

        assert not any(
            "/page/1.html"
            in descriptor.url_page
            for descriptor in result.pages
        )

        print(
            "NO /page/1.html: PASS"
        )

        # ---------------------------------------------------------
        # Page 2
        # ---------------------------------------------------------

        page_2 = result.pages[1]

        assert (
            page_2.page_number
            == 2
        )

        print(
            "PAGE 2 NUMBER = 2: PASS"
        )

        assert (
            page_2.url_page
            == (
                "https://putusan3.mahkamahagung.go.id/"
                "direktori/index/tahunjenis/putus/"
                "tahun/2021/page/2.html"
            )
        )

        print(
            "PAGE 2 URL: PASS"
        )

        # ---------------------------------------------------------
        # Page 3
        # ---------------------------------------------------------

        page_3 = result.pages[2]

        assert (
            page_3.page_number
            == 3
        )

        print(
            "PAGE 3 NUMBER = 3: PASS"
        )

        assert (
            page_3.url_page
            == (
                "https://putusan3.mahkamahagung.go.id/"
                "direktori/index/tahunjenis/putus/"
                "tahun/2021/page/3.html"
            )
        )

        print(
            "PAGE 3 URL: PASS"
        )

        # ---------------------------------------------------------
        # Page 499
        # ---------------------------------------------------------

        page_499 = result.pages[-1]

        assert (
            page_499.page_number
            == 499
        )

        print(
            "PAGE 499 NUMBER = 499: PASS"
        )

        assert (
            page_499.url_page
            == (
                "https://putusan3.mahkamahagung.go.id/"
                "direktori/index/tahunjenis/putus/"
                "tahun/2021/page/499.html"
            )
        )

        print(
            "PAGE 499 URL: PASS"
        )

        print()
        print("=" * 70)
        print("DISCOVER PAGES TEST: PASS")
        print("=" * 70)

    finally:
        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
