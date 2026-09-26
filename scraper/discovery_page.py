
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urljoin


class DiscoveryPageStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"


@dataclass(frozen=True)
class DiscoveredPutusan:
    judul: str
    url_detail: str
    is_unpublish: bool


@dataclass(frozen=True)
class DiscoveryPageSnapshot:
    status: DiscoveryPageStatus
    items: list[DiscoveredPutusan]
    reason: str | None = None


class DiscoveryPageScraper:
    DISCOVERY_JS = r"""
    (() => {
        const bodyText = (
            document.body?.innerText || ""
        ).toLowerCase();

        if (
            bodyText.includes("500 - exception error") ||
            bodyText.includes("terjadi kesalahan pada aplikasi")
        ) {
            return JSON.stringify({
                status: "RETRYABLE_ERROR",
                reason: "Server menampilkan error aplikasi."
            });
        }

        const mainWrapper =
            document.querySelector("#popular-post-list-sidebar") ||
            document.querySelector("#kolom-kiri");

        if (!mainWrapper) {
            return JSON.stringify({
                status: "RETRYABLE_ERROR",
                reason: "Wrapper discovery belum ditemukan."
            });
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

        return JSON.stringify({
            status: results.length > 0
                ? "SUCCESS"
                : "EMPTY",
            reason: results.length > 0
                ? null
                : "Wrapper ditemukan tetapi tidak ada link putusan.",
            results: results
        });
    })()
    """

    def __init__(
        self,
        *,
        render_wait_seconds: float = 5.0,
        retry_wait_seconds: float = 3.0,
        max_attempts: int = 3,
    ):
        self.render_wait_seconds = render_wait_seconds
        self.retry_wait_seconds = retry_wait_seconds
        self.max_attempts = max_attempts

    async def extract_current_page(
        self,
        page,
        *,
        base_url: str | None = None,
    ) -> DiscoveryPageSnapshot:

        raw = await page.evaluate(self.DISCOVERY_JS)

        if not raw:
            raise RuntimeError(
                "JavaScript discovery tidak mengembalikan hasil."
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Hasil JavaScript discovery bukan JSON valid."
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Hasil JavaScript discovery harus berupa object."
            )

        status = payload.get("status")

        if status == "RETRYABLE_ERROR":
            return DiscoveryPageSnapshot(
                status=DiscoveryPageStatus.RETRYABLE_ERROR,
                items=[],
                reason=str(
                    payload.get("reason")
                    or "Alasan retry tidak diketahui."
                ),
            )

        if status == "EMPTY":
            return DiscoveryPageSnapshot(
                status=DiscoveryPageStatus.EMPTY,
                items=[],
                reason=str(
                    payload.get("reason")
                    or "Tidak ada putusan ditemukan."
                ),
            )

        if status != "SUCCESS":
            raise RuntimeError(
                f"Status discovery tidak dikenal: {status!r}"
            )

        rows = payload.get("results")

        if not isinstance(rows, list):
            raise RuntimeError(
                "Field 'results' dari discovery harus berupa list."
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

        return DiscoveryPageSnapshot(
            status=DiscoveryPageStatus.SUCCESS,
            items=results,
        )

    async def scrape(
        self,
        browser,
        *,
        url_page: str,
    ) -> list[DiscoveredPutusan]:

        page = await browser.get(url_page)

        for attempt in range(1, self.max_attempts + 1):
            await page.sleep(
                self.render_wait_seconds
            )

            snapshot = await self.extract_current_page(
                page,
                base_url=url_page,
            )

            if (
                snapshot.status
                == DiscoveryPageStatus.SUCCESS
            ):
                return snapshot.items

            if (
                snapshot.status
                == DiscoveryPageStatus.EMPTY
            ):
                # Wrapper ada dan halaman valid, tetapi
                # memang tidak ditemukan putusan.
                return []

            # RETRYABLE_ERROR
            if attempt < self.max_attempts:
                await page.sleep(
                    self.retry_wait_seconds
                )
                continue

            raise RuntimeError(
                "Discovery page tidak siap setelah "
                f"{self.max_attempts} percobaan: "
                f"{snapshot.reason}"
            )

        raise RuntimeError(
            "Discovery page gagal diproses."
        )
