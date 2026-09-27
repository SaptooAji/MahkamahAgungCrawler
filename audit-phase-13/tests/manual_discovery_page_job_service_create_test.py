from sqlalchemy import func, select

from database.session import SessionLocal
from models.discovery_page_job import DiscoveryPageJob
from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)
from scraper.pagination import (
    PageDescriptor,
    PaginationScraper,
)
from services.discovery_page_job_service import (
    discovery_page_job_service,
)


YEAR = 2021

RUN_ID = None


def build_test_pages() -> list[PageDescriptor]:
    """
    Membuat descriptor 1..499 menggunakan URL yang
    sudah kita validasi dari pagination live.
    """

    current_url = (
        "https://putusan3.mahkamahagung.go.id/"
        "direktori/index/tahunjenis/putus/tahun/2021.html"
    )

    page_url_template = (
        "https://putusan3.mahkamahagung.go.id/"
        "direktori/index/tahunjenis/putus/"
        "tahun/2021/page/{page}.html"
    )

    return PaginationScraper.build_page_descriptors(
        current_url=current_url,
        total_pages=499,
        page_url_template=page_url_template,
    )


def create_test_run() -> int:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=YEAR,
            status=ScrapingRunStatus.PENDING,
        )

        session.add(run)
        session.flush()

        return run.id


def count_page_jobs(
    *,
    run_id: int,
) -> int:
    with SessionLocal() as session:
        count = session.scalar(
            select(
                func.count(
                    DiscoveryPageJob.id
                )
            ).where(
                DiscoveryPageJob.run_id
                == run_id
            )
        )

        return int(count or 0)


def delete_test_data(
    *,
    run_id: int,
):
    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            run_id,
        )

        if run is not None:
            session.delete(run)


def main():
    global RUN_ID

    print("=" * 70)
    print("DISCOVERY PAGE JOB SERVICE CREATE TEST")
    print("=" * 70)

    pages = build_test_pages()

    print()
    print(
        f"Page descriptors : {len(pages)}"
    )

    assert len(pages) == 499

    print(
        "BUILD 499 PAGE DESCRIPTORS: PASS"
    )

    RUN_ID = create_test_run()

    print()
    print(
        f"Test run ID      : {RUN_ID}"
    )

    try:
        # ---------------------------------------------------------
        # INSERT PERTAMA
        # ---------------------------------------------------------

        with SessionLocal.begin() as session:
            created_first = (
                discovery_page_job_service
                .create_from_page_descriptors(
                    session,
                    run_id=RUN_ID,
                    tahun=YEAR,
                    pages=pages,
                )
            )

        print()
        print(
            f"First insert      : {created_first}"
        )

        assert created_first == 499

        print(
            "FIRST INSERT = 499: PASS"
        )

        count_after_first = count_page_jobs(
            run_id=RUN_ID
        )

        print(
            f"Rows after first  : {count_after_first}"
        )

        assert count_after_first == 499

        print(
            "DB ROWS = 499 AFTER FIRST INSERT: PASS"
        )

        # ---------------------------------------------------------
        # INSERT KEDUA
        # ---------------------------------------------------------

        with SessionLocal.begin() as session:
            created_second = (
                discovery_page_job_service
                .create_from_page_descriptors(
                    session,
                    run_id=RUN_ID,
                    tahun=YEAR,
                    pages=pages,
                )
            )

        print()
        print(
            f"Second insert     : {created_second}"
        )

        assert created_second == 0

        print(
            "SECOND INSERT = 0 NEW ROWS: PASS"
        )

        count_after_second = count_page_jobs(
            run_id=RUN_ID
        )

        print(
            f"Rows after second : {count_after_second}"
        )

        assert count_after_second == 499

        print(
            "DB ROWS STAY = 499: PASS"
        )

        # ---------------------------------------------------------
        # VERIFY PAGE NUMBERS
        # ---------------------------------------------------------

        with SessionLocal() as session:
            rows = session.scalars(
                select(DiscoveryPageJob)
                .where(
                    DiscoveryPageJob.run_id
                    == RUN_ID
                )
                .order_by(
                    DiscoveryPageJob.page_number
                )
            ).all()

        page_numbers = [
            row.page_number
            for row in rows
        ]

        assert page_numbers == list(
            range(1, 500)
        )

        print(
            "PAGE NUMBERS = 1..499: PASS"
        )

        # ---------------------------------------------------------
        # VERIFY PAGE 1
        # ---------------------------------------------------------

        assert (
            rows[0].page_number
            == 1
        )

        assert (
            rows[0].url_page
            == pages[0].url_page
        )

        assert (
            "/page/1.html"
            not in rows[0].url_page
        )

        print(
            "PAGE 1 CANONICAL URL: PASS"
        )

        # ---------------------------------------------------------
        # VERIFY LAST PAGE
        # ---------------------------------------------------------

        assert (
            rows[-1].page_number
            == 499
        )

        assert (
            rows[-1].url_page
            == pages[-1].url_page
        )

        print(
            "PAGE 499 URL: PASS"
        )

        print()
        print("=" * 70)
        print(
            "DISCOVERY PAGE JOB SERVICE CREATE TEST: PASS"
        )
        print("=" * 70)

    finally:
        if RUN_ID is not None:
            delete_test_data(
                run_id=RUN_ID
            )

            print()
            print(
                f"TEST DATA RUN {RUN_ID} DELETED"
            )


if __name__ == "__main__":
    main()
