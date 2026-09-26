import asyncio
import json
import sys
import time
import nodriver as uc


if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


BASE_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/tahun/2021.html"
)


# ============================================================
# STRATEGY 1
# EXACT BASELINE DARI test_nodriver.py
# ============================================================

JS_BASELINE = """
(() => {
    let mainWrapper =
        document.querySelector("#popular-post-list-sidebar") ||
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
            (
                !text.includes("putusan") &&
                !text.includes("nomor")
            )
        ) {
            return;
        }

        let href = a.getAttribute("href");

        if (!href) {
            return;
        }

        if (seenUrls.has(href)) {
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

            let blockText = (
                currentNode.innerText || ""
            ).toLowerCase();

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


# ============================================================
# STRATEGY 2
# HREF GLOBAL
#
# Ini sengaja diuji karena sebelumnya menghasilkan jumlah
# yang tidak sesuai dengan tampilan visual.
# ============================================================

JS_GLOBAL_HREF = """
(() => {
    let links = document.querySelectorAll(
        "a[href*='/direktori/putusan/']"
    );

    let results = [];
    let seenUrls = new Set();

    links.forEach(a => {
        let href = a.getAttribute("href");

        if (!href) {
            return;
        }

        let text = (a.innerText || "").trim();

        if (
            !text.toLowerCase().includes("putusan") &&
            !text.toLowerCase().includes("nomor")
        ) {
            return;
        }

        if (seenUrls.has(href)) {
            return;
        }

        seenUrls.add(href);

        results.push({
            judul: text,
            href: href
        });
    });

    return JSON.stringify(results);
})()
"""


# ============================================================
# STRATEGY 3
# HREF GLOBAL + CONTAINER TERDEKAT
#
# Tidak bergantung pada class item.
# Mencoba menemukan blok yang paling kecil yang memuat
# judul + status Unpublish.
# ============================================================

JS_NEAREST_CONTAINER = """
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

        let title = (a.innerText || "").trim();

        if (
            !title.toLowerCase().includes("putusan") &&
            !title.toLowerCase().includes("nomor")
        ) {
            return;
        }

        seenUrls.add(href);

        let is_unpublish = false;
        let node = a;

        /*
         * Naik perlahan.
         *
         * Kita tidak menggunakan class CSS.
         * Kita hanya melihat teks yang benar-benar
         * berada di sekitar link.
         */
        for (let depth = 0; depth < 6; depth++) {
            if (!node) {
                break;
            }

            let text = (
                node.innerText || ""
            ).toLowerCase();

            if (text.includes("unpublish")) {
                is_unpublish = true;
                break;
            }

            /*
             * Stop jika sudah terlalu besar.
             * Jangan sampai membaca seluruh halaman.
             */
            if (
                node === document.body ||
                node === document.documentElement
            ) {
                break;
            }

            node = node.parentElement;
        }

        results.push({
            judul: title,
            href: href,
            is_unpublish: is_unpublish
        });
    });

    return JSON.stringify(results);
})()
"""


# ============================================================
# HELPER
# ============================================================

def normalize_url(url: str) -> str:
    if url.startswith("/"):
        return (
            "https://putusan3.mahkamahagung.go.id"
            + url
        )

    return url


def analyze(name, results):
    urls = [
        normalize_url(item["href"])
        for item in results
        if item.get("href")
    ]

    unique_urls = set(urls)

    unpublish_items = [
        item
        for item in results
        if item.get("is_unpublish") is True
    ]

    return {
        "name": name,
        "total": len(results),
        "unique": len(unique_urls),
        "unpublish": len(unpublish_items),
        "urls": unique_urls,
        "unpublish_urls": {
            normalize_url(item["href"])
            for item in unpublish_items
        },
        "results": results,
    }


def print_report(report):
    print()
    print("=" * 70)
    print(report["name"])
    print("=" * 70)

    print(
        f"Total hasil      : {report['total']}"
    )

    print(
        f"URL unik         : {report['unique']}"
    )

    print(
        f"Unpublish        : {report['unpublish']}"
    )

    print()

    for index, item in enumerate(
        report["results"],
        start=1
    ):
        status = (
            "UNPUBLISH"
            if item.get("is_unpublish")
            else "VALID"
        )

        print(
            f"[{index:02d}] "
            f"{status:9} | "
            f"{item.get('judul', '')[:80]}"
        )

        print(
            f"      {normalize_url(item['href'])}"
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    print("=" * 70)
    print("DISCOVERY EXTRACTION BENCHMARK")
    print("=" * 70)

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

        page = browser.main_tab

        print()
        print("[1] Membuka halaman:")
        print(BASE_URL)

        start_navigation = time.perf_counter()

        await page.get(BASE_URL)

        navigation_time = (
            time.perf_counter()
            - start_navigation
        )

        print(
            f"[2] page.get selesai: "
            f"{navigation_time:.3f}s"
        )

        print(
            "[3] Menunggu Cloudflare/render "
            "selama 5 detik..."
        )

        await asyncio.sleep(5)

        strategies = [
            (
                "STRATEGY 1 - BASELINE test_nodriver",
                JS_BASELINE,
            ),
            (
                "STRATEGY 2 - GLOBAL HREF",
                JS_GLOBAL_HREF,
            ),
            (
                "STRATEGY 3 - GLOBAL HREF + NEAREST CONTAINER",
                JS_NEAREST_CONTAINER,
            ),
        ]

        reports = []

        for name, javascript in strategies:

            print()
            print(
                f"[TEST] {name}"
            )

            start = time.perf_counter()

            raw = await page.evaluate(
                javascript
            )

            elapsed = (
                time.perf_counter()
                - start
            )

            results = json.loads(raw)

            report = analyze(
                name,
                results,
            )

            report["elapsed"] = elapsed

            reports.append(report)

            print(
                f"JS extraction time: "
                f"{elapsed * 1000:.3f} ms"
            )

            print_report(report)

        # ====================================================
        # PERBANDINGAN
        # ====================================================

        baseline = reports[0]

        print()
        print("#" * 70)
        print("PERBANDINGAN DENGAN BASELINE")
        print("#" * 70)

        for report in reports:

            same_urls = (
                report["urls"]
                == baseline["urls"]
            )

            same_unpublish = (
                report["unpublish_urls"]
                == baseline["unpublish_urls"]
            )

            print()
            print(report["name"])

            print(
                f"  URL sama dengan baseline "
                f"      : {same_urls}"
            )

            print(
                f"  Unpublish sama baseline "
                f"  : {same_unpublish}"
            )

            print(
                f"  Total                  "
                f"  : {report['total']}"
            )

            print(
                f"  URL unik               "
                f"  : {report['unique']}"
            )

            print(
                f"  Unpublish              "
                f"  : {report['unpublish']}"
            )

            print(
                f"  Extraction time        "
                f"  : {report['elapsed'] * 1000:.3f} ms"
            )

        # ====================================================
        # BASELINE VALIDATION
        # ====================================================

        print()
        print("#" * 70)
        print("VALIDASI BASELINE")
        print("#" * 70)

        print(
            f"20 URL unik : "
            f"{baseline['unique'] == 20}"
        )

        print(
            f"2 Unpublish : "
            f"{baseline['unpublish'] == 2}"
        )

        if (
            baseline["unique"] == 20
            and baseline["unpublish"] == 2
        ):
            print()
            print(
                "BASELINE VALIDATION: PASS"
            )
        else:
            print()
            print(
                "BASELINE VALIDATION: FAIL"
            )

    except Exception as exc:

        print()
        print(
            "[ERROR]",
            repr(exc),
        )

    finally:

        print()
        print(
            "Menutup browser..."
        )

        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())