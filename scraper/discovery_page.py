# scraper/discovery_page.py

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urljoin


@dataclass(frozen=True)
class DiscoveredPutusan:
    judul: str
    url_detail: str
    is_unpublish: bool


class DiscoveryPageScraper:
    DISCOVERY_JS = r"""
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

    def __init__(
        self,
        *,
        render_wait_seconds: float = 5.0,
    ):
        self.render_wait_seconds = render_wait_seconds

    async def extract_current_page(
        self,
        page,
        *,
        base_url: str | None = None,
    ) -> list[DiscoveredPutusan]:

        raw = await page.evaluate(
            self.DISCOVERY_JS
        )

        if not raw:
            return []

        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Hasil JavaScript discovery bukan JSON valid."
            ) from exc

        if not isinstance(rows, list):
            raise RuntimeError(
                "Hasil JavaScript discovery harus berupa list."
            )

        results: list[DiscoveredPutusan] = []

        for row in rows:
            if not isinstance(row, dict):
                continue

            href = row.get("href")

            if not href:
                continue

            judul = str(
                row.get("judul") or ""
            ).strip()

            is_unpublish = bool(
                row.get("is_unpublish", False)
            )

            absolute_url = (
                urljoin(base_url, href)
                if base_url
                else href
            )

            results.append(
                DiscoveredPutusan(
                    judul=judul,
                    url_detail=absolute_url,
                    is_unpublish=is_unpublish,
                )
            )

        return results

    async def scrape(
        self,
        browser,
        *,
        url_page: str,
    ) -> list[DiscoveredPutusan]:

        page = await browser.get(url_page)

        # Cloudflare/render wait yang sudah tervalidasi.
        await page.sleep(
            self.render_wait_seconds
        )

        return await self.extract_current_page(
            page,
            base_url=url_page,
        )