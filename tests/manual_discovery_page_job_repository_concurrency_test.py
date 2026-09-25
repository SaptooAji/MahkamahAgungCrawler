import threading
from queue import Queue

from sqlalchemy import delete, select

from database.session import SessionLocal
from models.discovery_page_job import DiscoveryPageJob
from models.scraping_run import ScrapingRun, ScrapingRunStatus

from repositories.discovery_page_job_repository import (
    create_page_job,
)


TEST_YEAR = 2097


def create_test_run():
    session = SessionLocal()

    try:
        run = ScrapingRun(
            tahun=TEST_YEAR,
            status=ScrapingRunStatus.PENDING,
        )

        session.add(run)
        session.commit()
        session.refresh(run)

        return run.id

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def cleanup_test_data():
    session = SessionLocal()

    try:
        run_ids = session.scalars(
            select(ScrapingRun.id).where(
                ScrapingRun.tahun == TEST_YEAR
            )
        ).all()

        if run_ids:
            session.execute(
                delete(DiscoveryPageJob).where(
                    DiscoveryPageJob.run_id.in_(run_ids)
                )
            )

            session.execute(
                delete(ScrapingRun).where(
                    ScrapingRun.id.in_(run_ids)
                )
            )

        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def worker_create_page_job(
    *,
    worker_name: str,
    run_id: int,
    barrier: threading.Barrier,
    results: Queue,
):
    session = SessionLocal()

    try:
        barrier.wait()

        job = create_page_job(
            session,
            run_id=run_id,
            tahun=TEST_YEAR,
            page_number=1,
            url_page="https://example.com/page/1",
        )

        session.commit()

        results.put(
            {
                "worker": worker_name,
                "status": "SUCCESS",
                "job_id": job.id,
            }
        )

    except Exception as exc:
        session.rollback()

        results.put(
            {
                "worker": worker_name,
                "status": "ERROR",
                "error": repr(exc),
            }
        )

    finally:
        session.close()


def test_concurrent_duplicate_insert():
    run_id = create_test_run()

    barrier = threading.Barrier(2)
    results = Queue()

    worker_a = threading.Thread(
        target=worker_create_page_job,
        kwargs={
            "worker_name": "worker-A",
            "run_id": run_id,
            "barrier": barrier,
            "results": results,
        },
    )

    worker_b = threading.Thread(
        target=worker_create_page_job,
        kwargs={
            "worker_name": "worker-B",
            "run_id": run_id,
            "barrier": barrier,
            "results": results,
        },
    )

    worker_a.start()
    worker_b.start()

    worker_a.join()
    worker_b.join()

    results_list = [
        results.get(),
        results.get(),
    ]

    errors = [
        result
        for result in results_list
        if result["status"] == "ERROR"
    ]

    assert not errors, (
        "Concurrent insert menghasilkan error:\n"
        f"{errors}"
    )

    success_results = [
        result
        for result in results_list
        if result["status"] == "SUCCESS"
    ]

    assert len(success_results) == 2, (
        "Kedua worker seharusnya mendapatkan hasil "
        f"SUCCESS. Hasil: {results_list}"
    )

    job_ids = {
        result["job_id"]
        for result in success_results
    }

    assert len(job_ids) == 1, (
        "Kedua worker seharusnya mendapatkan DiscoveryPageJob "
        f"yang sama. Job IDs: {job_ids}"
    )

    session = SessionLocal()

    try:
        jobs = session.scalars(
            select(DiscoveryPageJob).where(
                DiscoveryPageJob.run_id == run_id,
                DiscoveryPageJob.page_number == 1,
            )
        ).all()

        assert len(jobs) == 1, (
            f"Expected exactly 1 DiscoveryPageJob, "
            f"got {len(jobs)}"
        )

        assert jobs[0].id in job_ids

    finally:
        session.close()

    print("CONCURRENT DUPLICATE INSERT: PASS")
    print(f"SHARED PAGE JOB ID: {jobs[0].id}")


def main():
    cleanup_test_data()

    try:
        test_concurrent_duplicate_insert()

    finally:
        cleanup_test_data()

    print()
    print("ALL DISCOVERY PAGE JOB CONCURRENCY TESTS: PASS")

if __name__ == "__main__":
    main()