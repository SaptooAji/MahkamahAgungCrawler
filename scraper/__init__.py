import asyncio
import json
import sys
import warnings

import nodriver as uc


warnings.simplefilter("ignore", DeprecationWarning)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


BASE_URL = "https://putusan3.mahkamahagung.go.id"


async def discover_page_async(
    url_page: str,
) -> list[dict]:
    """
    Membuka satu halaman direktori Mahkamah Agung
    dan mengembalikan daftar Putusan yang ditemukan.

    Return:
        [
            {
                "judul": "...",
                "url_detail": "...",
                "is_unpublish": False,
            },
            ...
        ]
    """

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

        print(f"[DISCOVERY] Membuka: {url_page}")

        await page.get(url_page)

        print("[DISCOVERY] Menunggu render...")
        await asyncio.sleep(4)

        js_ekstraksi_list = """
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

                    if (blockText.includes("unpublish")) {
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

        raw = await page.evaluate(
            js_ekstraksi_list
        )

        data = json.loads(raw)

        results = []

        for item in data:
            url_detail = item["href"]

            if url_detail.startswith("/"):
                url_detail = (
                    f"{BASE_URL}{url_detail}"
                )

            results.append(
                {
                    "judul": item["judul"],
                    "url_detail": url_detail,
                    "is_unpublish": item[
                        "is_unpublish"
                    ],
                }
            )

        print(
            f"[DISCOVERY] Ditemukan {len(results)} "
            f"Putusan."
        )

        return results

    finally:
        if browser is not None:
            print("[DISCOVERY] Menutup browser...")
            browser.stop()


def discover_page(
    url_page: str,
) -> list[dict]:
    """
    Synchronous wrapper untuk Celery task.
    """

    return asyncio.run(
        discover_page_async(url_page)
    )