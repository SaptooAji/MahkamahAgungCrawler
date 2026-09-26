from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urljoin


class DetailScrapeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    UNPUBLISHED = "UNPUBLISHED"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    PDF_NOT_FOUND = "PDF_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class DetailScrapeResult:
    status: DetailScrapeStatus
    url_detail: str
    url_pdf: str | None = None
    error_message: str | None = None


class DetailPageScraper:
    """
    Scraper untuk halaman detail putusan Mahkamah Agung.

    Tanggung jawab class ini hanya:
    - membuka halaman detail
    - mendeteksi error halaman
    - mendeteksi Unpublish
    - mencari URL PDF

    Class ini TIDAK mengubah database.
    """

    DETAIL_JS = r"""
    (() => {
        const bodyText = (document.body?.innerText || "").trim();
        const bodyTextLower = bodyText.toLowerCase();

        /*
         * Deteksi error server MA.
         *
         * Kita menggunakan text karena halaman error dapat memiliki
         * struktur HTML yang berbeda dari halaman detail normal.
         */
        const isServerError =
            bodyTextLower.includes("500 - exception error") ||
            bodyTextLower.includes("terjadi kesalahan pada aplikasi");

        if (isServerError) {
            return JSON.stringify({
                status: "RETRYABLE_ERROR",
                error_message: "500 - Exception Error / terjadi kesalahan pada aplikasi"
            });
        }

        /*
         * Deteksi Unpublish.
         *
         * Untuk sementara menggunakan body text karena ini merupakan
         * fallback yang paling toleran terhadap variasi struktur HTML.
         */
        const isUnpublished =
            bodyTextLower.includes("unpublish") ||
            bodyTextLower.includes("belum dipublikasikan");

        /*
         * Cari link PDF.
         *
         * URL download MA yang kita temukan memiliki pola:
         *
         * /direktori/download_file/.../pdf/...
         *
         * Perhatikan bahwa URL tersebut TIDAK harus berakhiran .pdf.
         */
        const pdfLinks = Array.from(
            document.querySelectorAll(
                'a[href*="/direktori/download_file/"][href*="/pdf/"]'
            )
        );

        const pdfCandidates = pdfLinks.map((a) => ({
            href: a.href || a.getAttribute("href"),
            text: (a.innerText || a.textContent || "").trim()
        }));

        /*
         * Kalau Unpublish, kita tidak perlu menganggap tidak adanya
         * PDF sebagai error.
         */
        if (isUnpublished && pdfCandidates.length === 0) {
            return JSON.stringify({
                status: "UNPUBLISHED",
                pdf_candidates: []
            });
        }

        /*
         * Jika PDF tersedia, prioritaskan kandidat yang text-nya
         * mengandung ".pdf".
         *
         * URL-nya sendiri tidak harus berakhiran .pdf.
         */
        const pdfCandidate =
            pdfCandidates.find((item) =>
                item.text.toLowerCase().includes(".pdf")
            ) ||
            pdfCandidates[0] ||
            null;

        if (pdfCandidate && pdfCandidate.href) {
            return JSON.stringify({
                status: "SUCCESS",
                pdf_candidates: pdfCandidates,
                selected_pdf: pdfCandidate
            });
        }

        /*
         * Kalau tidak ada PDF tetapi halaman normal, kita pisahkan
         * kondisi ini dari SUCCESS supaya worker dapat memutuskan
         * apakah perlu retry.
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
        render_wait_seconds: float = 5.0,
    ) -> None:
        self.render_wait_seconds = render_wait_seconds

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

        status_raw = str(data.get("status") or "").strip()

        try:
            status = DetailScrapeStatus(status_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Status detail tidak dikenal: {status_raw!r}"
            ) from exc

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
                error_message="Link PDF tidak ditemukan pada halaman detail.",
            )

        selected_pdf = data.get("selected_pdf")

        if not isinstance(selected_pdf, dict):
            raise RuntimeError(
                "Status SUCCESS tetapi selected_pdf tidak tersedia."
            )

        href = selected_pdf.get("href")

        if not href:
            raise RuntimeError(
                "Status SUCCESS tetapi href PDF kosong."
            )

        url_pdf = urljoin(url_detail, str(href))

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
        page = await browser.get(url_detail)

        await page.sleep(self.render_wait_seconds)

        return await self.extract_detail(
            page,
            url_detail=url_detail,
        )