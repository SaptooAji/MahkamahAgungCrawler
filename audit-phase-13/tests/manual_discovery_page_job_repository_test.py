from datetime import datetime, timedelta, timezone
from models.scraping_run import ScrapingRun, ScrapingRunStatus

from database.session import SessionLocal
from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)
from models.scraping_run import ScrapingRun

from repositories.discovery_page_job_repository import (
    create_page_job,
    create_page_jobs,
    claim_page_job_by_id,
    mark_page_success,
    mark_page_failed_retry,
    recover_stale_page_jobs,
)


def create_test_run(session: SessionLocal) -> ScrapingRun:
    run = ScrapingRun(
        tahun=2099,
        status=ScrapingRunStatus.PENDING,
    )
    session.add(run)
    session.flush()
    return run


def test_create_page_job(session):
    run = create_test_run(session)

    job = create_page_job(
        session,
        run_id=run.id,
        tahun=2099,
        page_number=1,
        url_page="https://example.com/page/1",
    )

    assert job.id is not None
    assert job.run_id == run.id
    assert job.tahun == 2099
    assert job.page_number == 1
    assert job.url_page == "https://example.com/page/1"
    assert job.status == DiscoveryPageJobStatus.PENDING

    print("CREATE PAGE JOB: PASS")

    return run.id, job.id


def test_create_page_jobs(session):
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

    count = create_page_jobs(
        session,
        run_id=run.id,
        tahun=2099,
        pages=pages,
    )

    assert count == 3

    jobs = (
        session.query(DiscoveryPageJob)
        .filter(DiscoveryPageJob.run_id == run.id)
        .order_by(DiscoveryPageJob.page_number)
        .all()
    )

    assert len(jobs) == 3
    assert [job.page_number for job in jobs] == [1, 2, 3]
    assert all(
        job.status == DiscoveryPageJobStatus.PENDING
        for job in jobs
    )

    print("CREATE PAGE JOBS: PASS")


def test_claim_and_success(session):
    run = create_test_run(session)

    job = create_page_job(
        session,
        run_id=run.id,
        tahun=2099,
        page_number=1,
        url_page="https://example.com/page/1",
    )

    worker_id = "test-worker-A"

    claimed = claim_page_job_by_id(
        session,
        page_job_id=job.id,
        worker_id=worker_id,
    )

    assert claimed is not None
    assert claimed.status == DiscoveryPageJobStatus.PROCESSING
    assert claimed.processing_worker_id == worker_id
    assert claimed.processing_token is not None

    token = claimed.processing_token

    succeeded = mark_page_success(
        session,
        page_job_id=job.id,
        worker_id=worker_id,
        processing_token=token,
        discovered_count=25,
    )

    assert succeeded.status == DiscoveryPageJobStatus.SUCCESS
    assert succeeded.discovered_count == 25
    assert succeeded.processing_started_at is None
    assert succeeded.processing_worker_id is None
    assert succeeded.processing_token is None
    assert succeeded.next_retry_at is None
    assert succeeded.last_error is None

    print("CLAIM + SUCCESS: PASS")


def test_claim_and_failed_retry(session):
    run = create_test_run(session)

    job = create_page_job(
        session,
        run_id=run.id,
        tahun=2099,
        page_number=1,
        url_page="https://example.com/page/1",
    )

    worker_id = "test-worker-A"

    claimed = claim_page_job_by_id(
        session,
        page_job_id=job.id,
        worker_id=worker_id,
    )

    assert claimed is not None

    token = claimed.processing_token

    failed = mark_page_failed_retry(
        session,
        page_job_id=job.id,
        worker_id=worker_id,
        processing_token=token,
        error_message="500 - Exception Error",
        retry_delay_seconds=300,
    )

    assert failed.status == DiscoveryPageJobStatus.FAILED_RETRY
    assert failed.retry_count == 1
    assert failed.last_error == "500 - Exception Error"
    assert failed.next_retry_at is not None
    assert failed.processing_started_at is None
    assert failed.processing_worker_id is None
    assert failed.processing_token is None

    print("CLAIM + FAILED_RETRY: PASS")


def test_stale_recovery(session):
    run = create_test_run(session)

    job = create_page_job(
        session,
        run_id=run.id,
        tahun=2099,
        page_number=1,
        url_page="https://example.com/page/1",
    )

    worker_id = "test-worker-A"

    claimed = claim_page_job_by_id(
        session,
        page_job_id=job.id,
        worker_id=worker_id,
    )

    assert claimed is not None
    assert claimed.processing_token is not None

    old_token = claimed.processing_token

    # Simulasikan worker mati / lease kedaluwarsa.
    claimed.processing_started_at = (
        datetime.now(timezone.utc) - timedelta(seconds=3600)
    )

    session.flush()

    recovered_count = recover_stale_page_jobs(
        session,
        stale_after_seconds=900,
    )

    assert recovered_count == 1

    assert claimed.status == DiscoveryPageJobStatus.FAILED_RETRY
    assert claimed.retry_count == 1
    assert claimed.processing_started_at is None
    assert claimed.processing_worker_id is None
    assert claimed.processing_token is None
    assert claimed.next_retry_at is not None
    assert claimed.last_error == (
        "Processing lease expired; job recovered automatically."
    )

    assert old_token != claimed.processing_token

    print("STALE RECOVERY: PASS")


def test_old_worker_cannot_finish_after_recovery(session):
    run = create_test_run(session)

    job = create_page_job(
        session,
        run_id=run.id,
        tahun=2099,
        page_number=1,
        url_page="https://example.com/page/1",
    )

    worker_a = "test-worker-A"

    claimed_a = claim_page_job_by_id(
        session,
        page_job_id=job.id,
        worker_id=worker_a,
    )

    assert claimed_a is not None
    old_token = claimed_a.processing_token

    # Paksa lease menjadi stale.
    claimed_a.processing_started_at = (
        datetime.now(timezone.utc) - timedelta(seconds=3600)
    )

    session.flush()

    recovered_count = recover_stale_page_jobs(
        session,
        stale_after_seconds=900,
    )

    assert recovered_count == 1

    # Worker A mencoba menyelesaikan job menggunakan token lama.
    try:
        mark_page_success(
            session,
            page_job_id=job.id,
            worker_id=worker_a,
            processing_token=old_token,
            discovered_count=10,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Worker lama berhasil menyelesaikan job setelah lease recovery."
        )

    print("OLD WORKER REJECTED AFTER RECOVERY: PASS")


def cleanup_test_data():
    """
    Hapus data test tahun 2099.

    Jalankan dalam transaction terpisah supaya test tidak
    meninggalkan data dummy di database.
    """
    session = SessionLocal()

    try:
        session.query(DiscoveryPageJob).filter(
            DiscoveryPageJob.tahun == 2099
        ).delete(synchronize_session=False)

        session.query(ScrapingRun).filter(
            ScrapingRun.tahun == 2099
        ).delete(synchronize_session=False)

        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def main():
    cleanup_test_data()

    tests = [
        test_create_page_job,
        test_create_page_jobs,
        test_claim_and_success,
        test_claim_and_failed_retry,
        test_stale_recovery,
        test_old_worker_cannot_finish_after_recovery,
    ]

    try:
        for test in tests:
            session = SessionLocal()

            try:
                test(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    finally:
        cleanup_test_data()

    print()
    print("ALL DISCOVERY PAGE JOB REPOSITORY TESTS: PASS")


if __name__ == "__main__":
    main()