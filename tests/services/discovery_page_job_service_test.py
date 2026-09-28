from datetime import datetime, timezone, timedelta

from database.session import SessionLocal

from models.discovery_page_job import DiscoveryPageJobStatus
from models.scraping_run import ScrapingRun, ScrapingRunStatus

from repositories.discovery_page_job_repository import (
    create_page_job,
)

from services.discovery_page_job_service import (
    discovery_page_job_service,
)


TEST_YEAR = 2098


def create_test_run(session: SessionLocal) -> ScrapingRun:
    run = ScrapingRun(
        tahun=TEST_YEAR,
        status=ScrapingRunStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )

    session.add(run)
    session.flush()

    return run


def cleanup(session, run_id: int):
    session.rollback()

    from models.discovery_page_job import DiscoveryPageJob

    session.query(DiscoveryPageJob).filter(
        DiscoveryPageJob.run_id == run_id
    ).delete()

    session.query(ScrapingRun).filter(
        ScrapingRun.id == run_id
    ).delete()

    session.commit()


def test_claim_and_success():
    session = SessionLocal()

    run = None

    try:
        run = create_test_run(session)

        page_job = create_page_job(
            session,
            run_id=run.id,
            tahun=TEST_YEAR,
            page_number=1,
            url_page="https://example.com/page/1",
        )

        session.commit()

        claimed = discovery_page_job_service.claim_by_id(
            session,
            page_job_id=page_job.id,
            worker_id="service-test-worker",
        )

        assert claimed is not None
        assert claimed.status == DiscoveryPageJobStatus.PROCESSING
        assert claimed.processing_worker_id == "service-test-worker"
        assert claimed.processing_token is not None

        processing_token = claimed.processing_token

        succeeded = discovery_page_job_service.mark_success(
            session,
            page_job_id=claimed.id,
            worker_id="service-test-worker",
            processing_token=processing_token,
            discovered_count=25,
        )

        session.commit()

        assert succeeded.status == DiscoveryPageJobStatus.SUCCESS
        assert succeeded.discovered_count == 25
        assert succeeded.processing_worker_id is None
        assert succeeded.processing_token is None

        print("SERVICE CLAIM + SUCCESS: PASS")

    finally:
        if run is not None:
            cleanup(session, run.id)

        session.close()


def test_claim_failed_retry():
    session = SessionLocal()

    run = None

    try:
        run = create_test_run(session)

        page_job = create_page_job(
            session,
            run_id=run.id,
            tahun=TEST_YEAR,
            page_number=2,
            url_page="https://example.com/page/2",
        )

        session.commit()

        claimed = discovery_page_job_service.claim_by_id(
            session,
            page_job_id=page_job.id,
            worker_id="service-test-worker",
        )

        assert claimed is not None
        assert claimed.status == DiscoveryPageJobStatus.PROCESSING
        assert claimed.processing_token is not None

        processing_token = claimed.processing_token

        failed = discovery_page_job_service.mark_failed_retry(
            session,
            page_job_id=claimed.id,
            worker_id="service-test-worker",
            processing_token=processing_token,
            error_message="Test server error",
            retry_delay_seconds=300,
        )

        session.commit()

        assert failed.status == DiscoveryPageJobStatus.FAILED_RETRY
        assert failed.retry_count == 1
        assert failed.last_error == "Test server error"
        assert failed.processing_worker_id is None
        assert failed.processing_token is None
        assert failed.next_retry_at is not None

        print("SERVICE CLAIM + FAILED_RETRY: PASS")

    finally:
        if run is not None:
            cleanup(session, run.id)

        session.close()


def test_stale_recovery():
    session = SessionLocal()

    run = None

    try:
        run = create_test_run(session)

        page_job = create_page_job(
            session,
            run_id=run.id,
            tahun=TEST_YEAR,
            page_number=3,
            url_page="https://example.com/page/3",
        )

        session.commit()

        claimed = discovery_page_job_service.claim_by_id(
            session,
            page_job_id=page_job.id,
            worker_id="service-test-worker",
        )

        assert claimed is not None
        assert claimed.status == DiscoveryPageJobStatus.PROCESSING

        claimed.processing_started_at = (
            datetime.now(timezone.utc) - timedelta(minutes=30)
        )

        session.commit()

        recovered_count = (
            discovery_page_job_service.recover_stale(
                session,
                stale_after_seconds=900,
            )
        )

        session.commit()

        assert recovered_count == 1

        refreshed = session.get(
            type(page_job),
            page_job.id,
        )

        assert refreshed is not None
        assert refreshed.status == DiscoveryPageJobStatus.FAILED_RETRY
        assert refreshed.processing_worker_id is None
        assert refreshed.processing_token is None
        assert refreshed.next_retry_at is not None

        print("SERVICE STALE RECOVERY: PASS")

    finally:
        if run is not None:
            cleanup(session, run.id)

        session.close()


def main():
    test_claim_and_success()
    test_claim_failed_retry()
    test_stale_recovery()

    print()
    print("ALL DISCOVERY PAGE JOB SERVICE TESTS: PASS")


if __name__ == "__main__":
    main()