import asyncio
import sys

import nodriver as uc

from scraper.pagination import (
    PaginationMode,
    PaginationScraper,
)


TAHUN = 2021

ENTRY_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/"
    "tahunjenis/putus/"
    f"tahun/{TAHUN}.html"
)


async def main():
    browser = None

    try:
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

        result = await scraper.scrape(
            browser,
            url_page=ENTRY_URL,
        )

        print()
        print("=" * 70)
        print("PAGINATION TEST")
        print("=" * 70)

        print(
            f"Mode        : {result.mode.value}"
        )

        print(
            f"Total pages : {result.total_pages}"
        )

        print(
            f"DOM pages   : {len(result.pages)}"
        )

        print()
        print("PAGE DESCRIPTORS:")

        for item in result.pages:
            print(
                f"  page={item.page_number} "
                f"url={item.url_page}"
            )

        print()
        print("ASSERTIONS:")

        assert (
            result.mode
            == PaginationMode.PREDICTIVE
        )

        print(
            "MODE PREDICTIVE: PASS"
        )

        assert result.total_pages == 499

        print(
            "TOTAL PAGES = 499: PASS"
        )

        assert (
            result.pages[0].page_number == 1
        )

        print(
            "PAGE 1 NUMBER: PASS"
        )

        assert (
            result.pages[0].url_page
            == ENTRY_URL
        )

        print(
            "PAGE 1 URL IS CANONICAL ENTRY URL: PASS"
        )

        assert "/page/1.html" not in (
            result.pages[0].url_page
        )

        print(
            "PAGE 1 IS NOT /page/1.html: PASS"
        )

        page_2 = next(
            (
                item
                for item in result.pages
                if item.page_number == 2
            ),
            None,
        )

        assert page_2 is not None

        print(
            "PAGE 2 FOUND: PASS"
        )

        assert page_2.url_page.endswith(
            "/page/2.html"
        )

        print(
            "PAGE 2 URL: PASS"
        )

        page_3 = next(
            (
                item
                for item in result.pages
                if item.page_number == 3
            ),
            None,
        )

        assert page_3 is not None

        print(
            "PAGE 3 FOUND: PASS"
        )

        assert page_3.url_page.endswith(
            "/page/3.html"
        )

        print(
            "PAGE 3 URL: PASS"
        )

        page_4 = next(
            (
                item
                for item in result.pages
                if item.page_number == 4
            ),
            None,
        )

        assert page_4 is not None

        print(
            "PAGE 4 FOUND: PASS"
        )

        assert page_4.url_page.endswith(
            "/page/4.html"
        )

        print(
            "PAGE 4 URL: PASS"
        )

        last_page = next(
            (
                item
                for item in result.pages
                if item.page_number == 499
            ),
            None,
        )

        assert last_page is not None

        print(
            "PAGE 499 FOUND FROM LAST LINK: PASS"
        )

        assert last_page.url_page.endswith(
            "/page/499.html"
        )

        print(
            "PAGE 499 URL: PASS"
        )

        print()
        print(
            "PAGINATION PAGE 1 TEST: PASS"
        )

        print()
        print(
            "PAGINATION PAGE 1 TEST: PASS"
        )

    finally:
        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(
            asyncio.WindowsProactorEventLoopPolicy()
        )

    asyncio.run(main())