from database.session import SessionLocal
from models.scraping_run import (
    PaginationMode,
    ScrapingRun,
    ScrapingRunStatus,
)
from repositories.discovery_page_job_repository import create_page_job


YEAR = 2021

URL_PAGE_1 = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/tahun/2021.html"
)


with SessionLocal.begin() as session:
    # --------------------------------------------------------
    # 1. Buat scraping run
    # --------------------------------------------------------
    run = ScrapingRun(
        tahun=YEAR,
        status=ScrapingRunStatus.RUNNING,
        total_pages=499,
        pagination_mode=PaginationMode.PREDICTIVE,
        url_halaman_pertama=URL_PAGE_1,
    )

    session.add(run)
    session.flush()

    print(f"Created scraping run:")
    print(f"  run_id      = {run.id}")
    print(f"  tahun       = {run.tahun}")
    print(f"  total_pages = {run.total_pages}")

    # --------------------------------------------------------
    # 2. Buat discovery page job untuk halaman 1
    # --------------------------------------------------------
    page_job = create_page_job(
        session,
        run_id=run.id,
        tahun=YEAR,
        page_number=1,
        url_page=URL_PAGE_1,
    )

    print()
    print("Created discovery page job:")
    print(f"  page_job_id = {page_job.id}")
    print(f"  run_id      = {page_job.run_id}")
    print(f"  page_number = {page_job.page_number}")
    print(f"  status      = {page_job.status}")
    print(f"  url_page    = {page_job.url_page}")