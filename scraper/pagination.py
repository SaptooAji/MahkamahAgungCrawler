
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urljoin, urlparse


class PaginationRetryableError(RuntimeError):
    """Transient discovery failure that can be retried by the run orchestrator."""


class PaginationMode(str, Enum):
    PREDICTIVE = "PREDICTIVE"
    SEQUENTIAL = "SEQUENTIAL"


@dataclass(frozen=True)
class PageDescriptor:
    page_number: int
    url_page: str


@dataclass(frozen=True)
class PaginationResult:
    mode: PaginationMode
    total_pages: int | None
    pages: list[PageDescriptor]


class PaginationScraper:
    """
    Membaca pagination dari halaman direktori
    Mahkamah Agung.

    Prinsip:
    - Page 1 selalu menggunakan canonical URL.
    - Tidak pernah membuat /page/1.html.
    - Jika Last + page 2 + page 3 tersedia dan
      struktur URL konsisten -> PREDICTIVE.
    - Jika tidak -> SEQUENTIAL.
    """

    PAGE_HEALTH_JS = r"""
    (() => {
        const title = (
            document.title || ""
        ).trim();

        const titleLower = title.toLowerCase();

        const bodyText = (
            document.body?.innerText || ""
        ).trim();

        const bodyTextLower = bodyText.toLowerCase();

        const isCloudflare =
            titleLower.includes("just a moment") ||
            bodyTextLower.includes(
                "performing security verification"
            ) ||
            bodyTextLower.includes(
                "verify you are human"
            ) ||
            bodyTextLower.includes(
                "checking your browser"
            ) ||
            bodyTextLower.includes(
                "checking if the site connection is secure"
            ) ||
            document.querySelector(
                "#challenge-running"
            ) !== null ||
            document.querySelector(
                "#challenge-stage"
            ) !== null ||
            document.querySelector(
                ".cf-chl-widget"
            ) !== null ||
            document.querySelector(
                "iframe[src*='challenges.cloudflare.com']"
            ) !== null;

        if (isCloudflare) {
            return JSON.stringify({
                status: "CLOUDFLARE_CHALLENGE",
                title: title
            });
        }

        const serverErrorPatterns = [
            "500 - exception error",
            "terjadi kesalahan pada aplikasi",
            "http error 500",
            "http error 502",
            "http error 503",
            "http error 504",
            "http error 505",
            "error 500",
            "error 502",
            "error 503",
            "error 504",
            "error 505",
            "http version not supported"
        ];

        const matchedErrors =
            serverErrorPatterns.filter(
                (pattern) =>
                    titleLower.includes(pattern) ||
                    bodyTextLower.includes(pattern)
            );

        if (matchedErrors.length > 0) {
            return JSON.stringify({
                status: "RETRYABLE_ERROR",
                title: title,
                matched_errors: matchedErrors
            });
        }

        return JSON.stringify({
            status: "OK",
            title: title
        });
    })()
    """


    PAGINATION_JS = r"""
    (() => {
        const paginationRoot =
            document.querySelector("div.pagging.text-center") ||
            document.querySelector("ul.pagination");

        if (!paginationRoot) {
            return JSON.stringify({
                found: false,
                links: []
            });
        }

        const anchors = paginationRoot.querySelectorAll("a");

        const links = [];

        anchors.forEach(a => {
            links.push({
                href: a.getAttribute("href"),
                text: (a.innerText || "").trim(),
                page: a.getAttribute("data-ci-pagination-page"),
                rel: (a.getAttribute("rel") || "").toLowerCase()
            });
        });

        return JSON.stringify({
            found: true,
            links: links
        });
    })()
    """

    def __init__(
        self,
        *,
        render_wait_seconds: float = 5.0,
    ):
        self.render_wait_seconds = render_wait_seconds

    @staticmethod
    def _normalize_url(
        *,
        current_url: str,
        href: str,
    ) -> str:
        return urljoin(current_url, href)

    @staticmethod
    def _parse_page_number_from_url(
        url: str,
    ) -> int | None:
        """
        Contoh:
            /page/2.html   -> 2
            /page/499.html -> 499
        """

        path = urlparse(url).path.rstrip("/")

        marker = "/page/"

        if marker not in path:
            return None

        suffix = path.split(marker, 1)[1]

        if suffix.endswith(".html"):
            suffix = suffix[:-5]

        try:
            return int(suffix)
        except ValueError:
            return None

    @staticmethod
    def _replace_page_number(
        *,
        url: str,
        page_number: int,
    ) -> str:
        """
        Mengganti nomor halaman pada URL yang sudah
        diketahui valid.

        Contoh:

            page/2.html
            ->
            page/3.html
        """

        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        marker = "/page/"

        if marker not in path:
            raise ValueError(
                "URL tidak mempunyai pola "
                "/page/<number>.html: "
                f"{url}"
            )

        prefix, suffix = path.split(
            marker,
            1,
        )

        if suffix.endswith(".html"):
            suffix = suffix[:-5]

        try:
            int(suffix)
        except ValueError as exc:
            raise ValueError(
                "Nomor halaman pada URL tidak valid: "
                f"{url}"
            ) from exc

        new_path = (
            f"{prefix}"
            f"{marker}"
            f"{page_number}.html"
        )

        return parsed._replace(
            path=new_path
        ).geturl()

    @classmethod
    def _derive_page_url_template(
        cls,
        *,
        page_2_url: str,
        page_3_url: str,
    ) -> str | None:
        """
        Memastikan URL page 2 dan page 3 mempunyai
        struktur yang konsisten.

        Contoh:

            page 2:
            .../tahun/2021/page/2.html

            page 3:
            .../tahun/2021/page/3.html

        Hasil:

            .../tahun/2021/page/{page}.html
        """

        page_2_number = cls._parse_page_number_from_url(
            page_2_url
        )

        page_3_number = cls._parse_page_number_from_url(
            page_3_url
        )

        if page_2_number != 2:
            return None

        if page_3_number != 3:
            return None

        expected_page_3_url = cls._replace_page_number(
            url=page_2_url,
            page_number=3,
        )

        if expected_page_3_url != page_3_url:
            return None

        parsed = urlparse(page_2_url)
        path = parsed.path.rstrip("/")

        marker = "/page/"

        if marker not in path:
            return None

        prefix, suffix = path.split(
            marker,
            1,
        )

        if suffix.endswith(".html"):
            suffix = suffix[:-5]

        try:
            int(suffix)
        except ValueError:
            return None

        template_path = (
            f"{prefix}"
            f"{marker}"
            f"{{page}}.html"
        )

        return parsed._replace(
            path=template_path
        ).geturl()

    @staticmethod
    def build_page_descriptors(
        *,
        current_url: str,
        total_pages: int,
        page_url_template: str,
    ) -> list[PageDescriptor]:
        """
        Membuat descriptor halaman 1..N.

        Page 1 selalu menggunakan current_url.

        Page 2..N menggunakan template yang sudah
        divalidasi dari URL pagination aktual.
        """

        if total_pages < 1:
            raise ValueError(
                "total_pages harus >= 1."
            )

        if "{page}" not in page_url_template:
            raise ValueError(
                "page_url_template harus mengandung "
                "placeholder {page}."
            )

        pages: list[PageDescriptor] = [
            PageDescriptor(
                page_number=1,
                url_page=current_url,
            )
        ]

        for page_number in range(
            2,
            total_pages + 1,
        ):
            pages.append(
                PageDescriptor(
                    page_number=page_number,
                    url_page=page_url_template.format(
                        page=page_number
                    ),
                )
            )

        return pages

    async def _extract_pagination(
        self,
        page,
        *,
        current_url: str,
    ) -> dict:
        raw = await page.evaluate(
            self.PAGINATION_JS
        )

        if not raw:
            raise RuntimeError(
                "JavaScript pagination tidak "
                "menghasilkan data."
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Hasil JavaScript pagination "
                "bukan JSON valid."
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                "Hasil pagination harus berupa object."
            )

        if not data.get("found"):
            return {
                "found": False,
                "links": [],
            }

        raw_links = data.get("links", [])

        if not isinstance(raw_links, list):
            raise RuntimeError(
                "Field links pada pagination "
                "harus berupa list."
            )

        links: list[dict] = []

        for item in raw_links:
            if not isinstance(item, dict):
                continue

            href = item.get("href")

            if not href:
                continue

            links.append(
                {
                    "href": self._normalize_url(
                        current_url=current_url,
                        href=href,
                    ),
                    "text": str(
                        item.get("text") or ""
                    ).strip(),
                    "page": item.get("page"),
                    "rel": str(
                        item.get("rel") or ""
                    ).lower(),
                }
            )

        return {
            "found": True,
            "links": links,
        }

    @staticmethod
    def _find_page_link(
        *,
        links: list[dict],
        page_number: int,
    ) -> str | None:
        for link in links:
            raw_page = link.get("page")

            if raw_page is None:
                continue

            try:
                parsed_page = int(raw_page)
            except (TypeError, ValueError):
                continue

            if parsed_page == page_number:
                href = link.get("href")

                if href:
                    return href

        return None

    @staticmethod
    def _find_last_page(
        *,
        links: list[dict],
    ) -> tuple[int, str] | None:
        for link in links:
            text = (
                str(link.get("text") or "")
                .strip()
                .lower()
            )

            if text != "last":
                continue

            raw_page = link.get("page")

            try:
                page_number = int(raw_page)
            except (TypeError, ValueError):
                continue

            href = link.get("href")

            if href:
                return page_number, href

        return None

    @staticmethod
    def _find_next_page(
        *,
        links: list[dict],
    ) -> str | None:
        """
        Digunakan untuk sequential fallback.

        Prioritas:
        1. rel="next"
        2. text "Next"
        3. text "Selanjutnya"
        """

        for link in links:
            rel = str(
                link.get("rel") or ""
            ).lower()

            if rel == "next":
                href = link.get("href")

                if href:
                    return href

        for link in links:
            text = (
                str(link.get("text") or "")
                .strip()
                .lower()
            )

            if text in {
                "next",
                "selanjutnya",
                ">",
                "›",
            }:
                href = link.get("href")

                if href:
                    return href

        return None

    async def _check_page_health(
        self,
        page,
    ) -> dict:
        raw = await page.evaluate(
            self.PAGE_HEALTH_JS
        )

        if not raw:
            raise RuntimeError(
                "JavaScript page health "
                "tidak menghasilkan data."
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Hasil JavaScript page health "
                "bukan JSON valid."
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                "Hasil JavaScript page health "
                "harus berupa object."
            )

        return data

    @staticmethod
    def _build_page_1_candidates(
        url_page_1: str,
    ) -> list[str]:
        """
        Membuat kandidat URL page 1.

        Prioritas:
        1. URL yang diberikan
        2. Bentuk alternatif tanpa / dengan .html

        Contoh:

            /tahun/2000.html
            ->
            [
                /tahun/2000.html,
                /tahun/2000,
            ]

            /tahun/2021
            ->
            [
                /tahun/2021,
                /tahun/2021.html,
            ]
        """

        parsed = urlparse(url_page_1)

        path = parsed.path

        if path.endswith(".html"):
            alternative_path = path[:-5]
        else:
            alternative_path = f"{path}.html"

        alternative_url = parsed._replace(
            path=alternative_path
        ).geturl()

        candidates = [
            url_page_1,
            alternative_url,
        ]

        # Hilangkan duplicate tanpa mengubah urutan.
        return list(dict.fromkeys(candidates))

    async def _resolve_page_1_url(
        self,
        browser,
        *,
        url_page_1: str,
    ) -> tuple[str, object]:
        """
        Mencari URL page 1 yang benar-benar sehat.

        Candidate dicoba berdasarkan urutan.

        Jika candidate menampilkan:
        - OK -> digunakan
        - RETRYABLE_ERROR -> coba candidate berikutnya
        - CLOUDFLARE_CHALLENGE -> langsung error

        Jika seluruh candidate gagal -> error.
        """

        candidates = self._build_page_1_candidates(
            url_page_1
        )

        errors: list[str] = []

        for candidate_url in candidates:
            page = await browser.get(
                candidate_url
            )

            await page.sleep(
                self.render_wait_seconds
            )

            health = await self._check_page_health(
                page
            )

            status = health.get("status")

            if status == "OK":
                return candidate_url, page

            if status == "CLOUDFLARE_CHALLENGE":
                raise PaginationRetryableError(
                    "Cloudflare challenge masih aktif "
                    f"pada URL {candidate_url!r}. "
                    f"title={health.get('title')!r}"
                )

            if status == "RETRYABLE_ERROR":
                errors.append(
                    f"{candidate_url}: "
                    f"title={health.get('title')!r}; "
                    f"errors={health.get('matched_errors')}"
                )
                continue

            raise RuntimeError(
                "Status page health tidak dikenal: "
                f"{status!r}; "
                f"url={candidate_url!r}"
            )

        raise RuntimeError(
            "Semua candidate URL page 1 gagal.\n"
            + "\n".join(errors)
        )
    
    async def discover_pages(
        self,
        browser,
        *,
        url_page_1: str,
    ) -> PaginationResult:
        """
        Membuka canonical page 1 dan menentukan
        strategi pagination.

        URL page 1 dapat memiliki dua bentuk:

            /tahun/2000.html
            /tahun/2000

        Candidate pertama digunakan terlebih dahulu.
        Jika candidate pertama menghasilkan retryable
        server/application error, candidate alternatif
        dicoba.

        PREDICTIVE:
            Last ditemukan.
            Page 2 ditemukan.
            Page 3 ditemukan.
            Struktur URL page 2 -> page 3 konsisten.

        SEQUENTIAL:
            Digunakan jika predictive tidak aman.

        Page 1 selalu menggunakan URL yang berhasil
        melewati page-health check.
        """

        # ---------------------------------------------------------
        # Resolve URL page 1
        # ---------------------------------------------------------
        resolved_url_page_1, page = (
            await self._resolve_page_1_url(
                browser,
                url_page_1=url_page_1,
            )
        )

        # ---------------------------------------------------------
        # Extract pagination
        # ---------------------------------------------------------
        pagination = await self._extract_pagination(
            page,
            current_url=resolved_url_page_1,
        )

        links = pagination["links"]

        # ---------------------------------------------------------
        # Tidak ada pagination
        # ---------------------------------------------------------
        if not pagination["found"]:
            return PaginationResult(
                mode=PaginationMode.SEQUENTIAL,
                total_pages=None,
                pages=[
                    PageDescriptor(
                        page_number=1,
                        url_page=resolved_url_page_1,
                    )
                ],
            )

        # ---------------------------------------------------------
        # Cari Last
        # ---------------------------------------------------------
        last_info = self._find_last_page(
            links=links
        )

        total_pages: int | None = None

        if last_info is not None:
            total_pages = last_info[0]

            if total_pages < 1:
                total_pages = None

        # ---------------------------------------------------------
        # Cari page 2 dan page 3
        # ---------------------------------------------------------
        page_2_url = self._find_page_link(
            links=links,
            page_number=2,
        )

        page_3_url = self._find_page_link(
            links=links,
            page_number=3,
        )

        # ---------------------------------------------------------
        # PREDICTIVE MODE
        # ---------------------------------------------------------
        if (
            total_pages is not None
            and total_pages >= 2
            and page_2_url is not None
            and page_3_url is not None
        ):
            page_url_template = (
                self._derive_page_url_template(
                    page_2_url=page_2_url,
                    page_3_url=page_3_url,
                )
            )

            if page_url_template is not None:
                pages = self.build_page_descriptors(
                    current_url=resolved_url_page_1,
                    total_pages=total_pages,
                    page_url_template=page_url_template,
                )

                # -------------------------------------------------
                # Safety checks
                # -------------------------------------------------
                if (
                    pages[0].url_page
                    != resolved_url_page_1
                ):
                    raise RuntimeError(
                        "Invariant pagination rusak: "
                        "page 1 bukan resolved URL."
                    )

                if any(
                    "/page/1.html"
                    in descriptor.url_page
                    for descriptor in pages
                ):
                    raise RuntimeError(
                        "Invariant pagination rusak: "
                        "/page/1.html ditemukan."
                    )

                return PaginationResult(
                    mode=PaginationMode.PREDICTIVE,
                    total_pages=total_pages,
                    pages=pages,
                )

        # ---------------------------------------------------------
        # SEQUENTIAL FALLBACK
        # ---------------------------------------------------------
        # Jangan menebak total halaman dari Last. Traversal mengikuti
        # link Next aktual sampai Next tidak tersedia. Ini memastikan
        # fallback benar-benar sequential dan tidak kehilangan halaman
        # ketika struktur URL predictive tidak aman.
        pages = [
            PageDescriptor(
                page_number=1,
                url_page=resolved_url_page_1,
            )
        ]

        visited_urls = {resolved_url_page_1}
        current_page_number = 1
        current_page_url = resolved_url_page_1
        current_page = page

        while True:
            current_pagination = (
                pagination
                if current_page_url == resolved_url_page_1
                else await self._extract_pagination(
                    current_page,
                    current_url=current_page_url,
                )
            )

            next_url = self._find_next_page(
                links=current_pagination["links"]
            )

            # Be tolerant of pagination markup that exposes page 2 but
            # omits rel="next"/"Next" on the first page.
            if (
                next_url is None
                and current_page_number == 1
                and page_2_url is not None
            ):
                next_url = page_2_url

            if not next_url:
                break

            if next_url in visited_urls:
                raise RuntimeError(
                    "Pagination sequential mendeteksi loop URL: "
                    f"{next_url}"
                )

            visited_urls.add(next_url)

            parsed_next_number = (
                self._parse_page_number_from_url(next_url)
            )

            next_page_number = (
                parsed_next_number
                if parsed_next_number is not None
                else current_page_number + 1
            )

            if next_page_number <= current_page_number:
                raise RuntimeError(
                    "Nomor halaman sequential tidak meningkat: "
                    f"current={current_page_number}, "
                    f"next={next_page_number}, url={next_url}"
                )

            next_page = await browser.get(next_url)
            await next_page.sleep(self.render_wait_seconds)

            health = await self._check_page_health(next_page)
            status = health.get("status")

            if status == "CLOUDFLARE_CHALLENGE":
                raise PaginationRetryableError(
                    "Cloudflare challenge pada sequential page "
                    f"{next_page_number}: {next_url!r}; "
                    f"title={health.get('title')!r}"
                )

            if status == "RETRYABLE_ERROR":
                raise PaginationRetryableError(
                    "Retryable server/application error pada "
                    f"sequential page {next_page_number}: "
                    f"{next_url!r}; "
                    f"errors={health.get('matched_errors')}"
                )

            if status != "OK":
                raise RuntimeError(
                    "Status page health tidak dikenal pada "
                    f"sequential page {next_page_number}: {status!r}"
                )

            pages.append(
                PageDescriptor(
                    page_number=next_page_number,
                    url_page=next_url,
                )
            )

            current_page_number = next_page_number
            current_page_url = next_url
            current_page = next_page

        return PaginationResult(
            mode=PaginationMode.SEQUENTIAL,
            # Last yang ditemukan tetapi tidak tervalidasi predictive
            # hanya menjadi observasi; jumlah aktual ditentukan traversal.
            total_pages=len(pages),
            pages=pages,
        )
    
    
    async def scrape(
        self,
        browser,
        *,
        url_page_1: str,
    ) -> PaginationResult:
        return await self.discover_pages(
            browser,
            url_page_1=url_page_1,
        )
