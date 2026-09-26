
from __future__ import annotations

import asyncio
import json
import sys
from urllib.parse import urljoin

import nodriver as uc

from scraper.discovery_page import DiscoveryPageScraper


if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


TAHUN = 2021

PAGES = [1, 2, 3, 4, 5]

BASE_URL = (
    "https://putusan3.mahkamahagung.go.id"
    "/direktori/index/"
    "tahunjenis/putus/"
    f"tahun/{TAHUN}/page/{{page}}.html"
)


BASELINE_JS = r"""
(() => {
    let mainWrapper =
        document.querySelector("#popular-post-list-sidebar") ||
        document.querySelector("#kolom-kiri") ||
        document;

    let links =
        mainWrapper.querySelectorAll(
            "a[href*='/direktori/putusan/']"
        );

    let results = [];
    let seenUrls = new Set();

    links.forEach(a => {
        let text = (a.innerText || "").toLowerCase();

        if (
            text.length < 10 ||
            (
                !text.includes("putusan") &&
                !text.includes("nomor")
            )
        ) {
            return;
        }

        let href = a.getAttribute("href");

        if (!href || seenUrls.has(href)) {
            return;
        }

        seenUrls.add(href);

        let judul = a.innerText
            ? a.innerText.trim()
            : "";

        let is_unpublish = false;
        let currentNode = a;

        for (let i = 0; i < 4; i++) {
            if (!currentNode) {
                break;
            }

            if (
                currentNode.id ===
                "popular-post-list-sidebar"
            ) {
                break;
            }

            let blockText =
                (currentNode.innerText || "")
                .toLowerCase();

            if (
                blockText.includes("unpublish")
            ) {
                is_unpublish = true;
                break;
            }

            currentNode =
                currentNode.parentElement;
        }

        results.push({
            judul: judul,
            href: href,
            is_unpublish: is_unpublish
        });
    });

    return JSON.stringify(results);
})()
"""


def normalize_url(
    href: str,
    *,
    base_url: str,
) -> str:
    return urljoin(
        base_url,
        href,
    )


async def main():
    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    scraper = DiscoveryPageScraper(
        render_wait_seconds=5,
    )

    total_baseline = 0
    total_production = 0

    total_baseline_unpublish = 0
    total_production_unpublish = 0

    try:
        for page_number in PAGES:
            url = BASE_URL.format(
                page=page_number
            )

            print()
            print("=" * 70)
            print(f"PAGE {page_number}")
            print("=" * 70)

            # =========================================================
            # SATU navigation saja.
            #
            # Baseline dan production extraction membaca DOM yang sama.
            # =========================================================

            page = await browser.get(url)

            await page.sleep(5)

            # =========================================================
            # Baseline
            # =========================================================

            baseline_raw = await page.evaluate(
                BASELINE_JS
            )

            baseline = json.loads(
                baseline_raw or "[]"
            )

            baseline_urls = {
                normalize_url(
                    item["href"],
                    base_url=url,
                )
                for item in baseline
                if item.get("href")
            }

            baseline_unpublish = {
                normalize_url(
                    item["href"],
                    base_url=url,
                )
                for item in baseline
                if (
                    item.get("href")
                    and item.get("is_unpublish")
                )
            }

            # =========================================================
            # Production
            #
            # Tidak melakukan navigation ulang.
            # Menggunakan DOM page yang sama.
            # =========================================================

            production = (
                await scraper.extract_current_page(
                    page,
                    base_url=url,
                )
            )

            production_urls = {
                item.url_detail
                for item in production
            }

            production_unpublish = {
                item.url_detail
                for item in production
                if item.is_unpublish
            }

            # =========================================================
            # Output
            # =========================================================

            print(
                "Baseline total:",
                len(baseline),
            )

            print(
                "Production total:",
                len(production),
            )

            print(
                "Baseline Unpublish:",
                len(baseline_unpublish),
            )

            print(
                "Production Unpublish:",
                len(production_unpublish),
            )

            # =========================================================
            # Assertions
            # =========================================================

            assert (
                production_urls ==
                baseline_urls
            ), (
                f"URL SET MISMATCH pada page "
                f"{page_number}"
            )

            print(
                "URL SET: PASS"
            )

            assert (
                production_unpublish ==
                baseline_unpublish
            ), (
                "UNPUBLISH SET MISMATCH pada page "
                f"{page_number}"
            )

            print(
                "UNPUBLISH SET: PASS"
            )

            # =========================================================
            # Historical observation only.
            #
            # Page 1 pernah menghasilkan 20/2 pada benchmark sebelumnya.
            # Nilai ini TIDAK dijadikan invariant live.
            # =========================================================

            if page_number == 1:
                print(
                    "PAGE 1 CURRENT OBSERVATION:",
                    f"{len(production)} items / "
                    f"{len(production_unpublish)} Unpublish",
                )

                print(
                    "PAGE 1 HISTORICAL FIXTURE 20/2: "
                    "informational only"
                )

            total_baseline += len(baseline)
            total_production += len(production)

            total_baseline_unpublish += (
                len(baseline_unpublish)
            )

            total_production_unpublish += (
                len(production_unpublish)
            )

        # =============================================================
        # Final assertions
        # =============================================================

        assert (
            total_production ==
            total_baseline
        ), (
            "TOTAL ITEM COUNT MISMATCH"
        )

        assert (
            total_production_unpublish ==
            total_baseline_unpublish
        ), (
            "TOTAL UNPUBLISH COUNT MISMATCH"
        )

        print()
        print("=" * 70)
        print(
            "TOTAL BASELINE ITEMS:",
            total_baseline,
        )
        print(
            "TOTAL PRODUCTION ITEMS:",
            total_production,
        )
        print(
            "TOTAL BASELINE UNPUBLISH:",
            total_baseline_unpublish,
        )
        print(
            "TOTAL PRODUCTION UNPUBLISH:",
            total_production_unpublish,
        )
        print("=" * 70)

        print()
        print(
            "PRODUCTION DISCOVERY REGRESSION: PASS"
        )

    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())

