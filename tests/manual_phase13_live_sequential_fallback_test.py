import asyncio
import sys

import nodriver as uc

from scraper.pagination import PaginationMode, PaginationScraper


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


YEAR = 1997
ENTRY_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/"
    f"tahun/{YEAR}.html"
)

# Guard: this is deliberately a small live test.  Do not let an unexpected
# change in the selected year turn this into a large crawl.
MAX_EXPECTED_PAGES = 10


async def main() -> None:
    browser = None

    try:
        print("=" * 70)
        print("PHASE 13 - LIVE SEQUENTIAL PAGINATION FALLBACK")
        print("=" * 70)
        print(f"year             : {YEAR}")
        print(f"entry_url        : {ENTRY_URL}")
        print("database         : NOT USED")
        print("mode injection   : predictive template deliberately disabled")
        print()

        browser = await uc.start(
            headless=False,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )

        scraper = PaginationScraper(render_wait_seconds=5.0)

        # ---------------------------------------------------------
        # Preflight on the real MA page.
        # This checks that the chosen year is still small enough for a
        # controlled live test before we perform the full traversal.
        # ---------------------------------------------------------
        resolved_url, page = await scraper._resolve_page_1_url(
            browser,
            url_page_1=ENTRY_URL,
        )

        pagination = await scraper._extract_pagination(
            page,
            current_url=resolved_url,
        )
        last_info = scraper._find_last_page(
            links=pagination["links"]
        )

        observed_total = (
            last_info[0]
            if last_info is not None
            else None
        )

        print(f"resolved_url      : {resolved_url}")
        print(f"live Last pages   : {observed_total}")

        if observed_total is None:
            raise AssertionError(
                "Preflight tidak menemukan Last/page count; "
                "test kecil ini tidak aman untuk dijalankan tanpa guard."
            )

        if observed_total > MAX_EXPECTED_PAGES:
            raise AssertionError(
                f"Preflight menemukan {observed_total} halaman, "
                f"melebihi guard {MAX_EXPECTED_PAGES}. "
                "Test dihentikan agar tidak menjadi crawl besar."
            )

        if observed_total < 3:
            raise AssertionError(
                f"Preflight hanya menemukan {observed_total} halaman; "
                "test ini membutuhkan minimal 3 halaman untuk membuktikan "
                "traversal sequential."
            )

        # ---------------------------------------------------------
        # Force the existing production code down the SEQUENTIAL branch.
        # No production source is modified. This simulates the condition
        # "predictive pagination is not safe" while still using the real
        # MA DOM, real Next links, real browser navigation, and real page
        # health checks.
        # ---------------------------------------------------------
        scraper._derive_page_url_template = lambda **_kwargs: None

        result = await scraper.discover_pages(
            browser,
            url_page_1=ENTRY_URL,
        )

        page_numbers = [
            descriptor.page_number
            for descriptor in result.pages
        ]
        urls = [
            descriptor.url_page
            for descriptor in result.pages
        ]

        print()
        print("RESULT")
        print("-" * 70)
        print(f"mode              : {result.mode.value}")
        print(f"total_pages       : {result.total_pages}")
        print(f"descriptor_count  : {len(result.pages)}")
        print(f"page_numbers      : {page_numbers}")

        print()
        print("PAGE DESCRIPTORS")
        print("-" * 70)
        for descriptor in result.pages:
            print(
                f"page={descriptor.page_number} "
                f"url={descriptor.url_page}"
            )

        print()
        print("ASSERTIONS")
        print("-" * 70)

        assert result.mode == PaginationMode.SEQUENTIAL
        print("13.1 LIVE mode = SEQUENTIAL: PASS")

        assert result.total_pages == observed_total
        print(
            "13.2 LIVE traversal reached the observed terminal page "
            f"({observed_total}): PASS"
        )

        assert page_numbers == list(
            range(1, observed_total + 1)
        )
        print(
            "13.3 LIVE page sequence is strictly consecutive "
            f"1..{observed_total}: PASS"
        )

        assert len(urls) == len(set(urls))
        print("13.4 LIVE URLs contain no duplicate: PASS")

        assert "/page/1.html" not in urls
        print("13.5 LIVE result has no /page/1.html: PASS")

        print()
        print("=" * 70)
        print("PHASE 13 LIVE SEQUENTIAL FALLBACK: PASS")
        print("=" * 70)
        print(
            "Scope: live MA pages + real browser navigation + production "
            "sequential traversal; PostgreSQL/Celery are not involved."
        )

    finally:
        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
