import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.session import SessionLocal
from models.scraping_run import ScrapingRun
from scraper.pagination import PaginationScraper
from services.discovery_page_job_service import DiscoveryPageJobService

RUN_ID = 40


async def main():
    # ---------------------------------------------------------
    # 1. Ambil metadata run dari PostgreSQL
    # ---------------------------------------------------------
    with SessionLocal() as session:
        run = session.get(ScrapingRun, RUN_ID)

        if run is None:
            raise RuntimeError(
                f"ScrapingRun {RUN_ID} tidak ditemukan."
            )

        if run.total_pages is None:
            raise RuntimeError(
                "scraping_run.total_pages belum tersedia"
            )
        
        total_pages = run.total_pages

        tahun = run.tahun
        url_page_1 = run.url_halaman_pertama

        print("RUN_ID:", run.id)
        print("TAHUN:", tahun)
        print("DB TOTAL_PAGES:", total_pages)
        print("DB PAGINATION_MODE:", run.pagination_mode.value if run.pagination_mode else None)
        print("PAGE 1:", url_page_1)

    # ---------------------------------------------------------
    # 2. Detect pagination
    # ---------------------------------------------------------
    scraper = PaginationScraper(
        render_wait_seconds=5.0,
    )

    browser = None

    try:
        # Nodriver import dibuat di sini supaya script tetap ringan
        # sampai browser memang diperlukan.
        import nodriver as uc

        browser = await uc.start()

        result = await scraper.discover_pages(
            browser,
            url_page_1=url_page_1,
        )

        print("DETECTED MODE:", result.mode.value)
        print("DETECTED TOTAL_PAGES:", result.total_pages)
        print("PAGE DESCRIPTORS:", len(result.pages))

        if result.mode.value != "PREDICTIVE":
            raise RuntimeError(
                f"Pagination bukan PREDICTIVE: {result.mode.value}"
            )

        if result.total_pages != 499:
            raise RuntimeError(
                f"Expected 499 pages, got {result.total_pages}"
            )

        if len(result.pages) != 499:
            raise RuntimeError(
                f"Expected 499 page descriptors, got {len(result.pages)}"
            )

        if result.pages[0].page_number != 1:
            raise RuntimeError(
                "Descriptor pertama bukan page 1."
            )

        if result.pages[0].url_page != url_page_1:
            raise RuntimeError(
                "URL page 1 berubah dari canonical URL."
            )

        print("FIRST:", result.pages[0])
        print("SECOND:", result.pages[1])
        print("LAST:", result.pages[-1])

        # -----------------------------------------------------
        # 3. Insert page jobs secara idempotent
        # -----------------------------------------------------
        with SessionLocal.begin() as session:
            service = DiscoveryPageJobService()

            created = service.create_from_page_descriptors(
                session,
                run_id=RUN_ID,
                tahun=tahun,
                pages=result.pages,
            )

            print("CREATED PAGE JOBS:", created)

    finally:
        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())