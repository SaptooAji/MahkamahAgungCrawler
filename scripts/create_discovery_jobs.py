import asyncio

from database.session import SessionLocal
from models.scraping_run import ScrapingRun
from scraper.pagination import PaginationScraper
from services.discovery_page_job_service import DiscoveryPageJobService


RUN_ID = 40
TAHUN = 2021


async def main():
    scraper = PaginationScraper()

    result = await scraper.discover(
        tahun=TAHUN,
    )

    print("PAGINATION MODE:", result.mode)
    print("TOTAL PAGES:", result.total_pages)
    print("FIRST URL:", result.url_halaman_pertama)

    pages = result.pages

    print("PAGE DESCRIPTORS:", len(pages))

    with SessionLocal.begin() as session:
        run = session.get(ScrapingRun, RUN_ID)

        if run is None:
            raise RuntimeError(f"ScrapingRun {RUN_ID} tidak ditemukan.")

        if run.tahun != TAHUN:
            raise RuntimeError(
                f"Run {RUN_ID} memiliki tahun {run.tahun}, "
                f"bukan {TAHUN}."
            )

        service = DiscoveryPageJobService()

        created = service.create_from_page_descriptors(
            session,
            run_id=RUN_ID,
            tahun=TAHUN,
            pages=pages,
        )

        print("CREATED PAGE JOBS:", created)


if __name__ == "__main__":
    asyncio.run(main())