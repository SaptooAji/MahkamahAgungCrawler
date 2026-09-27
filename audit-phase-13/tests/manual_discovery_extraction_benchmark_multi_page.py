import asyncio
import json
import time
import warnings

import nodriver as uc


# ============================================================
# CONFIG
# ============================================================

TAHUN_TARGET = "2021"

# Tidak ada asumsi jumlah item per halaman.
# Kita hanya menguji beberapa halaman untuk membandingkan
# baseline dengan kandidat extraction.
HALAMAN_YANG_DIUJI = [1, 2, 3, 4, 5]

# Cloudflare / render wait.
# Ini sengaja tetap seperti benchmark sebelumnya.
WAIT_RENDER_SECONDS = 5

# Regression fixture KHUSUS page 1 tahun 2021.
# Jangan digunakan sebagai asumsi production.
PAGE1_EXPECTED_TOTAL = 20
PAGE1_EXPECTED_UNPUBLISH = 2


# ============================================================
# WINDOWS EVENT LOOP
# ============================================================

if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
    try:
        asyncio.set_event_loop_policy(
            asyncio.WindowsProactorEventLoopPolicy()
        )
    except (DeprecationWarning, RuntimeError):
        pass


# ============================================================
# URL
# ============================================================

def build_page_url(tahun: str, page_number: int) -> str:
    base = (
        "https://putusan3.mahkamahagung.go.id/"
        f"direktori/index/tahunjenis/putus/tahun/{tahun}"
    )

    if page_number == 1:
        return f"{base}.html"

    return f"{base}/page/{page_number}.html"


# ============================================================
# JAVASCRIPT STRATEGIES
# ============================================================

BASELINE_JS = r"""
(() => {
    let mainWrapper = document.querySelector("#popular-post-list-sidebar") ||
                      document.querySelector("#kolom-kiri") ||
                      document;

    let links = mainWrapper.querySelectorAll(
        "a[href*='/direktori/putusan/']"
    );

    let results = [];
    let seenUrls = new Set();

    links.forEach(a => {
        let text = (a.innerText || "").toLowerCase();

        if (
            text.length < 10 ||
            (!text.includes("putusan") && !text.includes("nomor"))
        ) {
            return;
        }

        let href = a.getAttribute("href");

        if (!href || seenUrls.has(href)) {
            return;
        }

        seenUrls.add(href);

        let judul = a.innerText ? a.innerText.trim() : "";

        let is_unpublish = false;
        let currentNode = a;

        for (let i = 0; i < 4; i++) {
            if (!currentNode) break;

            if (currentNode.id === "popular-post-list-sidebar") {
                break;
            }

            let blockText = (
                currentNode.innerText || ""
            ).toLowerCase();

            if (blockText.includes("unpublish")) {
                is_unpublish = true;
                break;
            }

            currentNode = currentNode.parentElement;
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


GLOBAL_HREF_JS = r"""
(() => {
    let links = document.querySelectorAll(
        "a[href*='/direktori/putusan/']"
    );

    let results = [];
    let seenUrls = new Set();

    links.forEach(a => {
        let href = a.getAttribute("href");

        if (!href || seenUrls.has(href)) {
            return;
        }

        seenUrls.add(href);

        let judul = a.innerText ? a.innerText.trim() : "";

        results.push({
            judul: judul,
            href: href,
            is_unpublish: false
        });
    });

    return JSON.stringify(results);
})()
"""


GLOBAL_HREF_NEAREST_CONTAINER_JS = r"""
(() => {
    let links = document.querySelectorAll(
        "a[href*='/direktori/putusan/']"
    );

    let results = [];
    let seenUrls = new Set();

    links.forEach(a => {
        let href = a.getAttribute("href");

        if (!href || seenUrls.has(href)) {
            return;
        }

        seenUrls.add(href);

        let judul = a.innerText ? a.innerText.trim() : "";

        let is_unpublish = false;
        let currentNode = a;

        // Kandidat yang sengaja diuji, bukan production algorithm.
        for (let i = 0; i < 6 && currentNode; i++) {
            let blockText = (
                currentNode.innerText || ""
            ).toLowerCase();

            if (blockText.includes("unpublish")) {
                is_unpublish = true;
                break;
            }

            currentNode = currentNode.parentElement;
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

STRATEGY4_SCOPED_SINGLE_ITEM_JS = r"""
(() => {
    const mainWrapper =
        document.querySelector("#popular-post-list-sidebar") ||
        document.querySelector("#kolom-kiri");

    if (!mainWrapper) {
        return JSON.stringify([]);
    }

    const PUTUSAN_SELECTOR =
        "a[href*='/direktori/putusan/']";

    const links = mainWrapper.querySelectorAll(
        PUTUSAN_SELECTOR
    );

    const results = [];
    const seenUrls = new Set();

    links.forEach(a => {
        const text = (a.innerText || "").toLowerCase();

        // Pertahankan semantic filter baseline.
        if (
            text.length < 10 ||
            (
                !text.includes("putusan") &&
                !text.includes("nomor")
            )
        ) {
            return;
        }

        const href = a.getAttribute("href");

        if (!href || seenUrls.has(href)) {
            return;
        }

        seenUrls.add(href);

        const judul = (a.innerText || "").trim();

        let is_unpublish = false;

        let currentNode = a.parentElement;

        while (
            currentNode &&
            currentNode !== mainWrapper
        ) {
            const itemLinks =
                currentNode.querySelectorAll(
                    PUTUSAN_SELECTOR
                );

            const linkCount = itemLinks.length;

            // Jika ancestor sudah mencakup lebih dari satu
            // putusan, jangan naik lagi agar tidak bocor
            // ke item tetangga.
            if (linkCount > 1) {
                break;
            }

            if (linkCount === 1) {
                const blockText = (
                    currentNode.innerText || ""
                ).toLowerCase();

                if (blockText.includes("unpublish")) {
                    is_unpublish = true;
                    break;
                }
            }

            currentNode = currentNode.parentElement;
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


# ============================================================
# HELPERS
# ============================================================

async def run_strategy(page, strategy_name, js_code):
    started = time.perf_counter()

    raw = await page.evaluate(js_code)

    elapsed_ms = (time.perf_counter() - started) * 1000

    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw

    if not isinstance(data, list):
        raise RuntimeError(
            f"{strategy_name}: hasil JS bukan list: {type(data)!r}"
        )

    return data, elapsed_ms


def normalize_url(url: str, page_url: str) -> str:
    """
    Normalisasi URL hanya untuk comparison benchmark.
    Tidak mengubah source DOM.
    """
    from urllib.parse import urljoin, urldefrag

    absolute = urljoin(page_url, url)
    absolute, _ = urldefrag(absolute)

    return absolute.rstrip("/")


def normalize_results(results, page_url):
    normalized = []

    for item in results:
        href = normalize_url(item["href"], page_url)

        normalized.append(
            {
                "judul": item.get("judul", "").strip(),
                "href": href,
                "is_unpublish": bool(item.get("is_unpublish", False)),
            }
        )

    return normalized


def url_set(results):
    return {item["href"] for item in results}


def unpublish_url_set(results):
    return {
        item["href"]
        for item in results
        if item["is_unpublish"]
    }


def print_strategy_summary(name, results, elapsed_ms):
    urls = url_set(results)
    unpublish = unpublish_url_set(results)

    print()
    print("-" * 70)
    print(name)
    print("-" * 70)
    print(f"Total hasil      : {len(results)}")
    print(f"URL unik         : {len(urls)}")
    print(f"Unpublish        : {len(unpublish)}")
    print(f"Extraction time  : {elapsed_ms:.3f} ms")


def compare_strategy(
    baseline,
    candidate,
):
    baseline_urls = url_set(baseline)
    candidate_urls = url_set(candidate)

    baseline_unpublish = unpublish_url_set(baseline)
    candidate_unpublish = unpublish_url_set(candidate)

    missing_urls = baseline_urls - candidate_urls
    extra_urls = candidate_urls - baseline_urls

    missing_unpublish = (
        baseline_unpublish - candidate_unpublish
    )
    extra_unpublish = (
        candidate_unpublish - baseline_unpublish
    )

    return {
        "urls_same": baseline_urls == candidate_urls,
        "unpublish_same": (
            baseline_unpublish == candidate_unpublish
        ),
        "missing_urls": missing_urls,
        "extra_urls": extra_urls,
        "missing_unpublish": missing_unpublish,
        "extra_unpublish": extra_unpublish,
    }


def print_url_diff(label, values, limit=10):
    if not values:
        return

    print(f"  {label}: {len(values)}")

    for url in sorted(values)[:limit]:
        print(f"    - {url}")

    if len(values) > limit:
        print(f"    ... +{len(values) - limit} lainnya")


# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 78)
    print("MULTI-PAGE DISCOVERY EXTRACTION BENCHMARK")
    print("=" * 78)
    print()
    print(f"Tahun             : {TAHUN_TARGET}")
    print(f"Halaman diuji     : {HALAMAN_YANG_DIUJI}")
    print(
        "Catatan            : tidak ada asumsi jumlah item/page."
    )
    print(
        "Fixture page 1     : "
        f"{PAGE1_EXPECTED_TOTAL} item / "
        f"{PAGE1_EXPECTED_UNPUBLISH} Unpublish"
    )
    print()

    browser = None

    all_page_results = {}

    try:
        browser = await uc.start(
            headless=False,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )

        for page_number in HALAMAN_YANG_DIUJI:
            page_url = build_page_url(
                TAHUN_TARGET,
                page_number,
            )

            print()
            print("=" * 78)
            print(
                f"PAGE {page_number}/{len(HALAMAN_YANG_DIUJI)}"
            )
            print("=" * 78)
            print(page_url)

            page = await browser.get(page_url)

            print(
                f"[PAGE {page_number}] "
                "Menunggu Cloudflare/render selama "
                f"{WAIT_RENDER_SECONDS} detik..."
            )

            await asyncio.sleep(WAIT_RENDER_SECONDS)

            page_results = {}

            # ------------------------------------------------
            # STRATEGY 1 - BASELINE
            # ------------------------------------------------

            print()
            print(
                "[TEST] STRATEGY 1 - "
                "BASELINE test_nodriver"
            )

            baseline, baseline_ms = await run_strategy(
                page,
                "BASELINE",
                BASELINE_JS,
            )

            baseline = normalize_results(
                baseline,
                page_url,
            )

            page_results["baseline"] = baseline

            print_strategy_summary(
                "STRATEGY 1 - BASELINE",
                baseline,
                baseline_ms,
            )

            # ------------------------------------------------
            # STRATEGY 2 - GLOBAL HREF
            # ------------------------------------------------

            print()
            print(
                "[TEST] STRATEGY 2 - GLOBAL HREF"
            )

            strategy2, strategy2_ms = await run_strategy(
                page,
                "GLOBAL HREF",
                GLOBAL_HREF_JS,
            )

            strategy2 = normalize_results(
                strategy2,
                page_url,
            )

            page_results["strategy2"] = strategy2

            print_strategy_summary(
                "STRATEGY 2 - GLOBAL HREF",
                strategy2,
                strategy2_ms,
            )

            # ------------------------------------------------
            # STRATEGY 3 - GLOBAL HREF + NEAREST CONTAINER
            # ------------------------------------------------

            print()
            print(
                "[TEST] STRATEGY 3 - "
                "GLOBAL HREF + NEAREST CONTAINER"
            )

            strategy3, strategy3_ms = await run_strategy(
                page,
                "GLOBAL HREF + NEAREST CONTAINER",
                GLOBAL_HREF_NEAREST_CONTAINER_JS,
            )

            strategy3 = normalize_results(
                strategy3,
                page_url,
            )

            page_results["strategy3"] = strategy3

            print_strategy_summary(
                "STRATEGY 3 - GLOBAL HREF + NEAREST CONTAINER",
                strategy3,
                strategy3_ms,
            )

            # ------------------------------------------------
            # STRATEGY 4 - SCOPED SINGLE-ITEM CONTAINER
            # ------------------------------------------------

            print()
            print(
                "[TEST] STRATEGY 4 - "
                "SCOPED SINGLE-ITEM CONTAINER"
            )

            strategy4, strategy4_ms = await run_strategy(
                page,
                "SCOPED SINGLE-ITEM CONTAINER",
                STRATEGY4_SCOPED_SINGLE_ITEM_JS,
            )

            strategy4 = normalize_results(
                strategy4,
                page_url,
            )

            page_results["strategy4"] = strategy4

            print_strategy_summary(
                "STRATEGY 4 - SCOPED SINGLE-ITEM CONTAINER",
                strategy4,
                strategy4_ms,
            )

            # ------------------------------------------------
            # STORE METRICS
            # ------------------------------------------------

            all_page_results[page_number] = {
                "page_url": page_url,
                "baseline": baseline,
                "baseline_ms": baseline_ms,
                "strategy2": strategy2,
                "strategy2_ms": strategy2_ms,
                "strategy3": strategy3,
                "strategy3_ms": strategy3_ms,
                "strategy4": strategy4,
                "strategy4_ms": strategy4_ms,
            }

            # ------------------------------------------------
            # PAGE COMPARISON
            # ------------------------------------------------

            print()
            print(
                "=" * 70
            )
            print(
                f"PERBANDINGAN PAGE {page_number}"
            )
            print(
                "=" * 70
            )

            comparison2 = compare_strategy(
                baseline,
                strategy2,
            )

            comparison3 = compare_strategy(
                baseline,
                strategy3,
            )

            comparison4 = compare_strategy(
                baseline,
                strategy4,
            )

            print()
            print("STRATEGY 2 - GLOBAL HREF")
            print(
                "  URL sama baseline       : "
                f"{comparison2['urls_same']}"
            )
            print(
                "  Unpublish sama baseline : "
                f"{comparison2['unpublish_same']}"
            )

            print_url_diff(
                "URL hilang",
                comparison2["missing_urls"],
            )
            print_url_diff(
                "URL ekstra",
                comparison2["extra_urls"],
            )
            print_url_diff(
                "Unpublish hilang",
                comparison2["missing_unpublish"],
            )
            print_url_diff(
                "Unpublish ekstra",
                comparison2["extra_unpublish"],
            )

            print()
            print(
                "STRATEGY 3 - GLOBAL HREF + "
                "NEAREST CONTAINER"
            )
            print(
                "  URL sama baseline       : "
                f"{comparison3['urls_same']}"
            )
            print(
                "  Unpublish sama baseline : "
                f"{comparison3['unpublish_same']}"
            )

            print_url_diff(
                "URL hilang",
                comparison3["missing_urls"],
            )
            print_url_diff(
                "URL ekstra",
                comparison3["extra_urls"],
            )
            print_url_diff(
                "Unpublish hilang",
                comparison3["missing_unpublish"],
            )
            print_url_diff(
                "Unpublish ekstra",
                comparison3["extra_unpublish"],
            )

            print()
            print(
                "STRATEGY 4 - SCOPED SINGLE-ITEM CONTAINER"
            )

            print(
                "  URL sama baseline       : "
                f"{comparison4['urls_same']}"
            )

            print(
                "  Unpublish sama baseline : "
                f"{comparison4['unpublish_same']}"
            )

            print_url_diff(
                "URL hilang",
                comparison4["missing_urls"],
            )

            print_url_diff(
                "URL ekstra",
                comparison4["extra_urls"],
            )

            print_url_diff(
                "Unpublish hilang",
                comparison4["missing_unpublish"],
            )

            print_url_diff(
                "Unpublish ekstra",
                comparison4["extra_unpublish"],
            )

            # ------------------------------------------------
            # PAGE 1 FIXTURE ONLY
            # ------------------------------------------------

            if page_number == 1:
                baseline_total = len(
                    url_set(baseline)
                )
                baseline_unpublish = len(
                    unpublish_url_set(baseline)
                )

                print()
                print(
                    "FIXTURE REGRESSION - PAGE 1 / 2021"
                )
                print(
                    "  Expected total     : "
                    f"{PAGE1_EXPECTED_TOTAL}"
                )
                print(
                    "  Actual total       : "
                    f"{baseline_total}"
                )
                print(
                    "  Expected Unpublish : "
                    f"{PAGE1_EXPECTED_UNPUBLISH}"
                )
                print(
                    "  Actual Unpublish   : "
                    f"{baseline_unpublish}"
                )

                fixture_pass = (
                    baseline_total
                    == PAGE1_EXPECTED_TOTAL
                    and baseline_unpublish
                    == PAGE1_EXPECTED_UNPUBLISH
                )

                print(
                    "  PAGE 1 FIXTURE     : "
                    f"{'PASS' if fixture_pass else 'FAIL'}"
                )

        # ====================================================
        # FINAL SUMMARY
        # ====================================================

        print()
        print("#" * 78)
        print("FINAL MULTI-PAGE SUMMARY")
        print("#" * 78)

        strategy2_all_match = True
        strategy3_all_match = True
        strategy4_all_match = True

        total_baseline_urls = 0
        total_baseline_unpublish = 0

        for page_number in HALAMAN_YANG_DIUJI:
            data = all_page_results[page_number]

            baseline = data["baseline"]
            strategy2 = data["strategy2"]
            strategy3 = data["strategy3"]
            strategy4 = data["strategy4"]
            comparison2 = compare_strategy(
                baseline,
                strategy2,
            )
            comparison3 = compare_strategy(
                baseline,
                strategy3,
            )
            comparison4 = compare_strategy(
                baseline,
                strategy4,
            )

            strategy2_match = (
                comparison2["urls_same"]
                and comparison2["unpublish_same"]
            )

            strategy3_match = (
                comparison3["urls_same"]
                and comparison3["unpublish_same"]
            )

            strategy4_match = (
                comparison4["urls_same"]
                and comparison4["unpublish_same"]
            )

            if not strategy2_match:
                strategy2_all_match = False

            if not strategy3_match:
                strategy3_all_match = False

            if not strategy4_match:
                strategy4_all_match = False

            baseline_urls = len(
                url_set(baseline)
            )
            baseline_unpublish = len(
                unpublish_url_set(baseline)
            )

            total_baseline_urls += baseline_urls
            total_baseline_unpublish += baseline_unpublish

            print()
            print(
                f"PAGE {page_number}:"
            )
            print(
                f"  Baseline URLs       : "
                f"{baseline_urls}"
            )
            print(
                f"  Baseline Unpublish  : "
                f"{baseline_unpublish}"
            )
            print(
                f"  Strategy 2 match    : "
                f"{'PASS' if strategy2_match else 'FAIL'}"
            )
            print(
                f"  Strategy 3 match    : "
                f"{'PASS' if strategy3_match else 'FAIL'}"
            )
            print(
                f"  Strategy 4 match    : "
                f"{'PASS' if strategy4_match else 'FAIL'}"
            )
            print(
                f"  Baseline JS time    : "
                f"{data['baseline_ms']:.3f} ms"
            )
            print(
                f"  Strategy 2 JS time  : "
                f"{data['strategy2_ms']:.3f} ms"
            )
            print(
                f"  Strategy 3 JS time  : "
                f"{data['strategy3_ms']:.3f} ms"
            )
            print(
                f"  Strategy 4 JS time  : "
                f"{data['strategy4_ms']:.3f} ms"
            )

        print()
        print("-" * 78)
        print(
            "TOTAL BASELINE URL (jumlah lintas halaman, "
            "bukan unique global): "
            f"{total_baseline_urls}"
        )
        print(
            "TOTAL BASELINE UNPUBLISH (jumlah lintas halaman): "
            f"{total_baseline_unpublish}"
        )

        print()
        print(
            "STRATEGY 2 MULTI-PAGE RESULT: "
            f"{'PASS' if strategy2_all_match else 'FAIL'}"
        )

        print(
            "STRATEGY 3 MULTI-PAGE RESULT: "
            f"{'PASS' if strategy3_all_match else 'FAIL'}"
        )

        print(
            "STRATEGY 4 MULTI-PAGE RESULT: "
            f"{'PASS' if strategy4_all_match else 'FAIL'}"
        )

        print()
        print("INTERPRETASI:")
        print(
            "- PASS berarti URL set dan Unpublish URL set "
            "sama dengan baseline pada SEMUA halaman."
        )
        print(
            "- Jumlah item per halaman tidak dianggap fixed."
        )
        print(
            "- Jumlah Unpublish per halaman tidak dianggap fixed."
        )
        print(
            "- Fixture 20/2 hanya berlaku untuk page 1 "
            "tahun 2021."
        )

        print()
        print("Benchmark selesai.")

    finally:
        if browser is not None:
            print()
            print("Menutup browser...")
            try:
                browser.stop()
            except Exception as exc:
                print(
                    f"[WARNING] browser.stop() error: {exc}"
                )


if __name__ == "__main__":
    asyncio.run(main())
