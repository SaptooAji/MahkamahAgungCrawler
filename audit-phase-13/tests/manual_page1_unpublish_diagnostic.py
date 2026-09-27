from __future__ import annotations

import asyncio
import json
import sys

import nodriver as uc


if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


YEAR = 2021

URL = (
    "https://putusan3.mahkamahagung.go.id"
    "/direktori/index/tahunjenis/putus/"
    f"tahun/{YEAR}.html"
)


DIAGNOSTIC_JS = r"""
(() => {
    const mainWrapper =
        document.querySelector("#popular-post-list-sidebar") ||
        document.querySelector("#kolom-kiri");

    if (!mainWrapper) {
        return JSON.stringify({
            wrapper_found: false,
            wrapper_id: null,
            all_text_unpublish: [],
            putusan_links: [],
            putusan_links_with_unpublish_ancestor: []
        });
    }

    const PUTUSAN_SELECTOR =
        "a[href*='/direktori/putusan/']";

    const links =
        mainWrapper.querySelectorAll(
            PUTUSAN_SELECTOR
        );

    const results = [];

    links.forEach((a, index) => {
        const href =
            a.getAttribute("href");

        const title =
            (a.innerText || "").trim();

        let currentNode =
            a.parentElement;

        const ancestors = [];

        let strategy4Detected =
            false;

        let firstUnpublishAncestor = null;

        while (
            currentNode &&
            currentNode !== mainWrapper
        ) {
            const itemLinks =
                currentNode.querySelectorAll(
                    PUTUSAN_SELECTOR
                );

            const linkCount =
                itemLinks.length;

            const blockText =
                (currentNode.innerText || "")
                .trim();

            const blockTextLower =
                blockText.toLowerCase();

            ancestors.push({
                tag: currentNode.tagName,
                id: currentNode.id || null,
                className:
                    currentNode.className || null,
                linkCount: linkCount,
                text: blockText
            });

            if (linkCount > 1) {
                break;
            }

            if (
                linkCount === 1 &&
                blockTextLower.includes("unpublish")
            ) {
                strategy4Detected = true;

                firstUnpublishAncestor = {
                    tag: currentNode.tagName,
                    id: currentNode.id || null,
                    className:
                        currentNode.className || null,
                    text: blockText
                };

                break;
            }

            currentNode =
                currentNode.parentElement;
        }

        results.push({
            index: index,
            href: href,
            title: title,
            strategy4_detected_unpublish:
                strategy4Detected,
            first_unpublish_ancestor:
                firstUnpublishAncestor,
            ancestors: ancestors
        });
    });

    /*
     * Cari SEMUA element di wrapper yang mengandung
     * kata "unpublish", bukan hanya ancestor dari link.
     */
    const allElements =
        mainWrapper.querySelectorAll("*");

    const allTextUnpublish = [];

    allElements.forEach((element, index) => {
        const text =
            (element.innerText || "").trim();

        if (
            text &&
            text.toLowerCase().includes("unpublish")
        ) {
            allTextUnpublish.push({
                index: index,
                tag: element.tagName,
                id: element.id || null,
                className:
                    element.className || null,
                text: text
            });
        }
    });

    return JSON.stringify({
        wrapper_found: true,
        wrapper_id:
            mainWrapper.id || null,
        putusan_link_count:
            links.length,
        all_text_unpublish:
            allTextUnpublish,
        putusan_links:
            results
    });
})()
"""


async def main():
    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    try:
        print("=" * 78)
        print("PAGE 1 / 2021 - UNPUBLISH DIAGNOSTIC")
        print("=" * 78)
        print()
        print(URL)
        print()

        page = await browser.get(URL)

        print(
            "Menunggu Cloudflare/render selama 5 detik..."
        )

        await page.sleep(5)

        raw = await page.evaluate(
            DIAGNOSTIC_JS
        )

        data = json.loads(raw)

        print()
        print("=" * 78)
        print("WRAPPER")
        print("=" * 78)

        print(
            "Wrapper found:",
            data["wrapper_found"]
        )

        print(
            "Wrapper ID:",
            data["wrapper_id"]
        )

        print(
            "Putusan links:",
            data["putusan_link_count"]
        )

        print()
        print("=" * 78)
        print("SEMUA ELEMENT YANG MENGANDUNG 'UNPUBLISH'")
        print("=" * 78)

        all_unpublish = data[
            "all_text_unpublish"
        ]

        print(
            "Jumlah element:",
            len(all_unpublish)
        )

        for item in all_unpublish:
            print()
            print(
                f"Element index : {item['index']}"
            )
            print(
                f"Tag           : {item['tag']}"
            )
            print(
                f"ID            : {item['id']}"
            )
            print(
                f"Class         : {item['className']}"
            )
            print(
                "Text:"
            )
            print(item["text"][:2000])

        print()
        print("=" * 78)
        print(
            "PUTUSAN LINK DENGAN DETEKSI STRATEGY 4"
        )
        print("=" * 78)

        detected = [
            item
            for item in data["putusan_links"]
            if item[
                "strategy4_detected_unpublish"
            ]
        ]

        print(
            "Strategy 4 Unpublish:",
            len(detected)
        )

        for item in detected:
            print()
            print(
                f"Index : {item['index']}"
            )
            print(
                f"Title : {item['title']}"
            )
            print(
                f"Href  : {item['href']}"
            )

            print(
                "Ancestor:"
            )

            print(
                json.dumps(
                    item[
                        "first_unpublish_ancestor"
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )

        print()
        print("=" * 78)
        print(
            "SEMUA PUTUSAN LINK"
        )
        print("=" * 78)

        for item in data["putusan_links"]:
            print()
            print(
                f"[{item['index']}] "
                f"{item['title']}"
            )
            print(
                f"URL: {item['href']}"
            )

            if item[
                "strategy4_detected_unpublish"
            ]:
                print(
                    "STATUS: UNPUBLISH"
                )
            else:
                print(
                    "STATUS: normal"
                )

        print()
        print("=" * 78)
        print("DIAGNOSTIC SELESAI")
        print("=" * 78)

    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())