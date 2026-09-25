from sqlalchemy import select

from database.session import SessionLocal
from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)
from models.scraping_run import ScrapingRun, ScrapingRunStatus

from repositories.discovery_page_job_repository import (
    create_page_job,
    create_page_jobs,
)


TEST_YEAR = 2098


def create_test_run(session):
    run = ScrapingRun(
        tahun=TEST_YEAR,
        status=ScrapingRunStatus.PENDING,
    )
    session.add(run)
    session.flush()
    return run


def cleanup_test_data():
    session = SessionLocal()

    try:
        runs = session.scalars(
            select(ScrapingRun).where(
                ScrapingRun.tahun == TEST_YEAR
            )
        ).all()

        for run in runs:
            session.query(DiscoveryPageJob).filter(
                DiscoveryPageJob.run_id == run.id
            ).delete(synchronize_session=False)

        session.query(ScrapingRun).filter(
            ScrapingRun.tahun == TEST_YEAR
        ).delete(synchronize_session=False)

        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def test_duplicate_page_job():
    session = SessionLocal()

    try:
        run = create_test_run(session)

        first = create_page_job(
            session,
            run_id=run.id,
            tahun=TEST_YEAR,
            page_number=1,
            url_page="https://example.com/page/1",
        )

        session.commit()

        second = create_page_job(
            session,
            run_id=run.id,
            tahun=TEST_YEAR,
            page_number=1,
            url_page="https://example.com/page/1",
        )

        session.commit()

        jobs = session.scalars(
            select(DiscoveryPageJob).where(
                DiscoveryPageJob.run_id == run.id,
                DiscoveryPageJob.page_number == 1,
            )
        ).all()

        assert len(jobs) == 1, (
            f"Expected 1 page job, got {len(jobs)}"
        )

        assert jobs[0].id == first.id
        assert jobs[0].url_page == first.url_page
        assert jobs[0].status == DiscoveryPageJobStatus.PENDING

        print("CREATE DUPLICATE PAGE JOB: PASS")

    finally:
        session.close()


def test_bulk_duplicate_page_jobs():
    session = SessionLocal()

    try:
        run = create_test_run(session)

        pages = [
            {
                "page_number": 1,
                "url_page": "https://example.com/page/1",
            },
            {
                "page_number": 2,
                "url_page": "https://example.com/page/2",
            },
            {
                "page_number": 3,
                "url_page": "https://example.com/page/3",
            },
        ]

        first_count = create_page_jobs(
            session,
            run_id=run.id,
            tahun=TEST_YEAR,
            pages=pages,
        )

        session.commit()

        assert first_count == 3

        second_count = create_page_jobs(
            session,
            run_id=run.id,
            tahun=TEST_YEAR,
            pages=pages,
        )

        session.commit()

        jobs = session.scalars(
            select(DiscoveryPageJob)
            .where(
                DiscoveryPageJob.run_id == run.id
            )
            .order_by(DiscoveryPageJob.page_number)
        ).all()

        assert len(jobs) == 3, (
            f"Expected 3 unique page jobs, got {len(jobs)}"
        )

        assert [job.page_number for job in jobs] == [
            1,
            2,
            3,
        ]

        assert second_count == 0, (
            "Duplicate bulk insert should report 0 "
            "newly-created jobs."
        )

        print("BULK CREATE IDEMPOTENCY: PASS")

    finally:
        session.close()


def main():
    cleanup_test_data()

    try:
        test_duplicate_page_job()
        cleanup_test_data()

        test_bulk_duplicate_page_jobs()

    finally:
        cleanup_test_data()

    print()
    print("ALL DISCOVERY PAGE JOB IDEMPOTENCY TESTS: PASS")


if __name__ == "__main__":
    main()