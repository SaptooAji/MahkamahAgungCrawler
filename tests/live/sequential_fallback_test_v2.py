import asyncio
import sys

import nodriver as uc

from scraper.pagination import PaginationMode, PaginationScraper


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


YEAR = 1997
ENTRY_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/"
    f"tahun/{YEAR}.html"
)

MAX_EXPECTED_PAGES = 10
CLOUDFLARE_WAIT_SECONDS = 300
HEALTH_POLL_SECONDS = 3


async def wait_until_page_healthy(scraper, page):
    """Allow a human to complete a visible Cloudflare challenge normally."""
    deadline = asyncio.get_running_loop().time() + CLOUDFLARE_WAIT_SECONDS
    printed_waiting = False

    while True:
        health = await scraper._check_page_health(page)
        status = health.get("status")

        if status == "OK":
            return health

        if status == "CLOUDFLARE_CHALLENGE":
            if not printed_waiting:
                print()
                print("CLOUDFLARE CHECKPOINT")
                print("-" * 70)
                print("Browser sedang berada pada Cloudflare challenge.")
                print("Selesaikan challenge secara normal pada browser yang terbuka.")
                print(
                    f"Test akan menunggu maksimal {CLOUDFLARE_WAIT_SECONDS} detik."
                )
                print()
                printed_waiting = True

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    "Cloudflare challenge tidak selesai dalam "
                    f"{CLOUDFLARE_WAIT_SECONDS} detik."
                )

            await page.sleep(HEALTH_POLL_SECONDS)
            continue

        raise RuntimeError(
            "Page health bukan OK/CLOUDFLARE_CHALLENGE: "
            f"status={status!r}; title={health.get('title')!r}; "
            f"errors={health.get('matched_errors')}"
        )


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
        print("cloudflare       : manual checkpoint allowed")
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
        # Open the real MA page once.  Do not use _resolve_page_1_url
        # here because it intentionally raises immediately on an active
        # Cloudflare challenge.
        # ---------------------------------------------------------
        page = await browser.get(ENTRY_URL)
        await page.sleep(scraper.render_wait_seconds)

        health = await wait_until_page_healthy(scraper, page)
        print(
            f"page health      : {health.get('status')}"
            f"; title={health.get('title')!r}"
        )

        resolved_url = ENTRY_URL

        # ---------------------------------------------------------
        # Preflight: inspect the real MA pagination without starting the
        # sequential crawl.  This is only a safety guard against a live
        # dataset becoming unexpectedly large.
        # ---------------------------------------------------------
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
                "test membutuhkan minimal 3 halaman untuk membuktikan "
                "traversal sequential."
            )

        # ---------------------------------------------------------
        # Keep the exact already-healthy page.  This prevents a second
        # navigation and therefore avoids re-triggering Cloudflare.
        # ---------------------------------------------------------
        async def use_existing_page(_browser, *, url_page_1: str):
            return resolved_url, page

        scraper._resolve_page_1_url = use_existing_page

        # ---------------------------------------------------------
        # Force the existing production code down the SEQUENTIAL branch.
        # Production source is untouched.  The actual MA DOM, Next links,
        # browser navigation, health checks, loop guard, and monotonic page
        # guard are still production logic.
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

        assert page_numbers == list(range(1, observed_total + 1))
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
