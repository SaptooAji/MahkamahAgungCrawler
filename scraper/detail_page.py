from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urljoin


class DetailScrapeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    UNPUBLISHED = "UNPUBLISHED"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    CLOUDFLARE_CHALLENGE = "CLOUDFLARE_CHALLENGE"
    PDF_NOT_FOUND = "PDF_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class DetailScrapeResult:
    status: DetailScrapeStatus
    url_detail: str
    url_pdf: str | None = None
    error_message: str | None = None


class DetailPageScraper:
    """
    Scraper halaman detail putusan Mahkamah Agung.

    Strategi waiting:
        browser.get()
            ↓
        tunggu 5 detik
            ↓
        extract
            ↓
        belum ada PDF?
            ↓
        tunggu 5 detik
            ↓
        extract lagi
            ↓
        maksimal 20 detik

    Tidak melakukan polling JavaScript selama Cloudflare challenge.
    """

    DETAIL_JS = r"""
        (() => {
            const bodyText = (document.body?.innerText || "").trim();
            const bodyTextLower = bodyText.toLowerCase();
            const title = (document.title || "").trim();
            const titleLower = title.toLowerCase();

            /*
            * 1. Cloudflare challenge
            *
            * Cloudflare challenge bukan Python exception.
            * Browser tetap berhasil membuka halaman, tetapi DOM yang
            * tersedia bukan halaman detail putusan.
            */
            const cloudflareSelectors = [
                "#challenge-running",
                "#challenge-stage",
                ".cf-chl-widget",
                "[name='cf-turnstile-response']",
                "iframe[src*='challenges.cloudflare.com']"
            ];

            const cloudflareMatchedSelectors =
                cloudflareSelectors.filter(
                    (selector) =>
                        document.querySelector(selector) !== null
                );

            const cloudflareTexts = [
                "just a moment",
                "performing security verification",
                "verify you are human",
                "checking your browser",
                "checking if the site connection is secure",
                "enable javascript and cookies to continue"
            ];

            const cloudflareMatchedTexts =
                cloudflareTexts.filter(
                    (text) =>
                        titleLower.includes(text) ||
                        bodyTextLower.includes(text)
                );

            const isCloudflare =
                cloudflareMatchedSelectors.length > 0 ||
                cloudflareMatchedTexts.length > 0;

            if (isCloudflare) {
                return JSON.stringify({
                    status: "CLOUDFLARE_CHALLENGE",
                    cloudflare: {
                        title: title,
                        matched_selectors:
                            cloudflareMatchedSelectors,
                        matched_texts:
                            cloudflareMatchedTexts
                    }
                });
            }

            /*
            * 2. Server error Mahkamah Agung
            */
            const isServerError =
                bodyTextLower.includes("500 - exception error") ||
                bodyTextLower.includes(
                    "terjadi kesalahan pada aplikasi"
                );

            if (isServerError) {
                return JSON.stringify({
                    status: "RETRYABLE_ERROR",
                    error_message:
                        "500 - Exception Error / " +
                        "terjadi kesalahan pada aplikasi"
                });
            }

            /*
            * 3. Cari link PDF.
            *
            * URL PDF Mahkamah Agung tidak selalu berakhiran .pdf.
            * Struktur yang digunakan:
            *
            * /direktori/download_file/.../pdf/...
            */
            const pdfLinks = Array.from(
                document.querySelectorAll(
                    'a[href*="/direktori/download_file/"][href*="/pdf/"]'
                )
            );

            const pdfCandidates = pdfLinks.map((a) => ({
                href: a.href || a.getAttribute("href"),
                text: (
                    a.innerText ||
                    a.textContent ||
                    ""
                ).trim()
            }));

            /*
            * 4. Unpublish
            *
            * Berdasarkan struktur HTML aktual halaman Mahkamah Agung:
            *
            * <section id="content">
            *     ...
            *     <p>
            *         Putusan ini tidak dipublikasikan ...
            *     </p>
            * </section>
            *
            * Kita tidak menggunakan keyword generik seperti:
            *   - "unpublish"
            *   - "belum dipublikasikan"
            *   - "tidak tersedia"
            *
            * Detector menggunakan struktur DOM #content dan frasa
            * inti yang spesifik terhadap halaman Unpublish.
            *
            * PDF juga harus tidak ditemukan agar halaman tidak salah
            * diklasifikasikan sebagai UNPUBLISHED jika suatu saat
            * halaman mengandung teks tersebut tetapi tetap menyediakan PDF.
            */
            const content = document.querySelector("#content");

            const unpublishedParagraphs = Array.from(
                content?.querySelectorAll("p") || []
            ).map(
                (p) =>
                    (p.innerText || "")
                        .trim()
                        .toLowerCase()
            );

            const unpublishedMatchedParagraphs =
                unpublishedParagraphs.filter(
                    (text) =>
                        text.includes(
                            "putusan ini tidak dipublikasikan"
                        )
                );

            const isUnpublished =
                unpublishedMatchedParagraphs.length > 0;

            /*
            * 5. Unpublish tanpa PDF
            */
            if (
                isUnpublished &&
                pdfCandidates.length === 0
            ) {
                return JSON.stringify({
                    status: "UNPUBLISHED",
                    reason:
                        "putusan_tidak_dipublikasikan",
                    diagnostics: {
                        matched_paragraphs:
                            unpublishedMatchedParagraphs,
                        pdf_count:
                            pdfCandidates.length
                    },
                    pdf_candidates: []
                });
            }

            /*
            * 6. PDF ditemukan
            */
            const pdfCandidate =
                pdfCandidates.find((item) =>
                    item.text
                        .toLowerCase()
                        .includes(".pdf")
                ) ||
                pdfCandidates[0] ||
                null;

            if (
                pdfCandidate &&
                pdfCandidate.href
            ) {
                return JSON.stringify({
                    status: "SUCCESS",
                    pdf_candidates: pdfCandidates,
                    selected_pdf: pdfCandidate
                });
            }

            /*
            * 7. Belum ada PDF.
            *
            * Jangan langsung menganggap halaman gagal.
            * Python akan melakukan waiting berikutnya.
            */
            return JSON.stringify({
                status: "PDF_NOT_FOUND",
                pdf_candidates: []
            });
        })()
    """
    def __init__(
        self,
        *,
        initial_wait_seconds: float = 5.0,
        retry_wait_seconds: float = 5.0,
        max_wait_seconds: float = 20.0,
    ) -> None:
        if initial_wait_seconds <= 0:
            raise ValueError(
                "initial_wait_seconds harus > 0."
            )

        if retry_wait_seconds <= 0:
            raise ValueError(
                "retry_wait_seconds harus > 0."
            )

        if max_wait_seconds <= 0:
            raise ValueError(
                "max_wait_seconds harus > 0."
            )

        if initial_wait_seconds > max_wait_seconds:
            raise ValueError(
                "initial_wait_seconds tidak boleh "
                "lebih besar dari max_wait_seconds."
            )

        if retry_wait_seconds > max_wait_seconds:
            raise ValueError(
                "retry_wait_seconds tidak boleh "
                "lebih besar dari max_wait_seconds."
            )

        self.initial_wait_seconds = initial_wait_seconds
        self.retry_wait_seconds = retry_wait_seconds
        self.max_wait_seconds = max_wait_seconds

    async def extract_detail(
        self,
        page,
        *,
        url_detail: str,
    ) -> DetailScrapeResult:
        raw = await page.evaluate(self.DETAIL_JS)

        if not raw:
            raise RuntimeError(
                "JavaScript detail tidak menghasilkan response."
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Hasil JavaScript detail bukan JSON valid."
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                "Hasil JavaScript detail harus berupa object."
            )

        status_raw = str(
            data.get("status") or ""
        ).strip()

        try:
            status = DetailScrapeStatus(status_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Status detail tidak dikenal: {status_raw!r}"
            ) from exc

        if status == DetailScrapeStatus.CLOUDFLARE_CHALLENGE:
            cloudflare = data.get("cloudflare") or {}

            title = str(cloudflare.get("title") or "").strip()
            matched_selectors = cloudflare.get("matched_selectors") or []
            matched_texts = cloudflare.get("matched_texts") or []

            return DetailScrapeResult(
                status=status,
                url_detail=url_detail,
                error_message=(
                    "Cloudflare challenge detected. "
                    f"title={title!r}; "
                    f"selectors={matched_selectors}; "
                    f"texts={matched_texts}"
                ),
            )

        if status == DetailScrapeStatus.RETRYABLE_ERROR:
            return DetailScrapeResult(
                status=status,
                url_detail=url_detail,
                error_message=(
                    data.get("error_message")
                    or "Server error Mahkamah Agung."
                ),
            )

        if status == DetailScrapeStatus.UNPUBLISHED:
            return DetailScrapeResult(
                status=status,
                url_detail=url_detail,
            )

        if status == DetailScrapeStatus.PDF_NOT_FOUND:
            return DetailScrapeResult(
                status=status,
                url_detail=url_detail,
                error_message=(
                    "Link PDF belum ditemukan."
                ),
            )

        selected_pdf = data.get(
            "selected_pdf"
        )

        if not isinstance(
            selected_pdf,
            dict,
        ):
            raise RuntimeError(
                "Status SUCCESS tetapi "
                "selected_pdf tidak tersedia."
            )

        href = selected_pdf.get("href")

        if not href:
            raise RuntimeError(
                "Status SUCCESS tetapi href PDF kosong."
            )

        url_pdf = urljoin(
            url_detail,
            str(href),
        )

        return DetailScrapeResult(
            status=DetailScrapeStatus.SUCCESS,
            url_detail=url_detail,
            url_pdf=url_pdf,
        )

    async def scrape(
        self,
        browser,
        *,
        url_detail: str,
    ) -> DetailScrapeResult:
        print(
            f"[DETAIL] Membuka: {url_detail}"
        )

        page = await browser.get(
            url_detail
        )

        elapsed = 0.0

        '''/*
         * JavaScript hanya dieksekusi setelah
         * waiting period, bukan setiap 2 detik.
         */'''
        await page.sleep(
            self.initial_wait_seconds
        )

        elapsed += self.initial_wait_seconds

        while True:
            print(
                "[DETAIL] "
                f"Checking setelah {elapsed:.1f}s..."
            )

            result = await self.extract_detail(
                page,
                url_detail=url_detail,
            )

            print(
                "[DETAIL] "
                f"status={result.status.value}"
            )

            '''/*
             * Kondisi terminal.
             */'''
            if result.status in (
                DetailScrapeStatus.SUCCESS,
                DetailScrapeStatus.UNPUBLISHED,
                DetailScrapeStatus.RETRYABLE_ERROR,
            ):
                return result

            if result.status == DetailScrapeStatus.CLOUDFLARE_CHALLENGE:
                print(
                    "[DETAIL] Cloudflare challenge detected. "
                    f"{result.error_message}"
                )

                if elapsed >= self.max_wait_seconds:
                    return DetailScrapeResult(
                        status=DetailScrapeStatus.RETRYABLE_ERROR,
                        url_detail=url_detail,
                        error_message=(
                            "Cloudflare challenge tidak terlewati "
                            f"setelah {elapsed:.1f} detik. "
                            f"{result.error_message}"
                        ),
                    )

            '''/*
             * PDF_NOT_FOUND:
             * halaman mungkin belum selesai render.
             *
             * Beri kesempatan lagi sampai max_wait_seconds.
             */'''
            if (
                elapsed >=
                self.max_wait_seconds
            ):
                return DetailScrapeResult(
                    status=(
                        DetailScrapeStatus
                        .PDF_NOT_FOUND
                    ),
                    url_detail=url_detail,
                    error_message=(
                        "Link PDF tidak ditemukan "
                        f"setelah {elapsed:.1f} detik."
                    ),
                )

            remaining = (
                self.max_wait_seconds
                - elapsed
            )

            wait_seconds = min(
                self.retry_wait_seconds,
                remaining,
            )

            if result.status == DetailScrapeStatus.CLOUDFLARE_CHALLENGE:
                print(
                    "[DETAIL] "
                    "Cloudflare masih aktif. "
                    f"Menunggu {wait_seconds:.1f}s lagi..."
                )
            else:
                print(
                    "[DETAIL] "
                    f"PDF belum ditemukan. "
                    f"Menunggu {wait_seconds:.1f}s lagi..."
                )

            await page.sleep(
                wait_seconds
            )

            elapsed += wait_seconds


def build_detail_page_scraper() -> DetailPageScraper:
    return DetailPageScraper(
        initial_wait_seconds=5.0,
        retry_wait_seconds=5.0,
        max_wait_seconds=20.0,
    )