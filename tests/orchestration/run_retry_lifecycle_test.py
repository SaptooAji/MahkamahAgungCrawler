from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from dotenv import load_dotenv
from sqlalchemy import delete, select

load_dotenv(os.getenv("ENV_FILE", ".env"))

from database.session import SessionLocal
from celery_app.tasks import maintenance_tick
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from services.discovery_run_service import discovery_run_service
from services.run_finalizer_service import RunFinalizerService

TEST_YEAR = 2197
TEST_URL = "https://example.invalid/phase13/run-retry"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_run() -> int:
    with SessionLocal.begin() as session:
        session.execute(
            delete(ScrapingRun).where(ScrapingRun.tahun == TEST_YEAR)
        )
        run = discovery_run_service.create_run(
            session,
            tahun=TEST_YEAR,
            url_halaman_pertama=TEST_URL,
        )
        return run.id


def snapshot(run_id: int) -> dict:
    with SessionLocal() as session:
        run = session.get(ScrapingRun, run_id)
        assert run is not None
        return {
            "status": run.status.value,
            "retry_count": run.retry_count,
            "next_retry_at": run.next_retry_at,
            "retry_dispatched_at": run.retry_dispatched_at,
            "last_error": run.last_error,
        }


def cleanup(run_id: int) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            delete(ScrapingRun).where(ScrapingRun.id == run_id)
        )


def main() -> int:
    run_id = create_run()

    try:
        # 13R.1 Initial claim must work.
        with SessionLocal.begin() as session:
            claimed = discovery_run_service.claim_run(
                session,
                run_id=run_id,
            )
            assert claimed is not None
            assert claimed.status == ScrapingRunStatus.RUNNING
        print("13R.1 ScrapingRun initial claim: PASS")

        # 13R.2 First retryable failure is persisted.
        with SessionLocal.begin() as session:
            run = discovery_run_service.mark_retryable_failure(
                session,
                run_id=run_id,
                error_message="Cloudflare challenge masih aktif",
                retry_delay_seconds=300,
            )
            assert run.status == ScrapingRunStatus.FAILED_RETRY
            assert run.retry_count == 1
            assert run.next_retry_at is not None
            assert run.next_retry_at > utcnow()
            assert run.retry_dispatched_at is None
        print("13R.2 First discovery retry state: PASS")

        # 13R.3 Finalizer must not turn FAILED_RETRY into COMPLETED.
        with SessionLocal.begin() as session:
            run = session.get(ScrapingRun, run_id)
            assert run is not None
            before = run.status
            RunFinalizerService().try_finalize(session, run=run)
            session.flush()
            assert run.status == before == ScrapingRunStatus.FAILED_RETRY
        print("13R.3 FAILED_RETRY protected from finalization: PASS")

        # Make retry due and verify claim is blocked before due, then allowed after due.
        with SessionLocal.begin() as session:
            run = session.get(ScrapingRun, run_id)
            assert run is not None
            run.next_retry_at = utcnow() + timedelta(seconds=60)

        with SessionLocal.begin() as session:
            early = discovery_run_service.claim_run(session, run_id=run_id)
            assert early is None
        print("13R.4 Early retry claim blocked by next_retry_at: PASS")

        with SessionLocal.begin() as session:
            run = session.get(ScrapingRun, run_id)
            assert run is not None
            run.next_retry_at = utcnow() - timedelta(seconds=1)

        with SessionLocal.begin() as session:
            claimed = discovery_run_service.claim_run(
                session,
                run_id=run_id,
            )
            assert claimed is not None
            assert claimed.status == ScrapingRunStatus.RUNNING
            assert claimed.next_retry_at is None
            assert claimed.retry_dispatched_at is None
        print("13R.5 Due retry can be reclaimed: PASS")

        # 13R.6 Attempts 2 and 3, where attempt 3 becomes terminal.
        with SessionLocal.begin() as session:
            run = discovery_run_service.mark_retryable_failure(
                session,
                run_id=run_id,
                error_message="retryable-2",
            )
            assert run.status == ScrapingRunStatus.FAILED_RETRY
            assert run.retry_count == 2

        with SessionLocal.begin() as session:
            run = session.get(ScrapingRun, run_id)
            assert run is not None
            run.next_retry_at = utcnow() - timedelta(seconds=1)

        with SessionLocal.begin() as session:
            claimed = discovery_run_service.claim_run(session, run_id=run_id)
            assert claimed is not None

        with SessionLocal.begin() as session:
            run = discovery_run_service.mark_retryable_failure(
                session,
                run_id=run_id,
                error_message="retryable-3",
            )
            assert run.status == ScrapingRunStatus.FAILED
            assert run.retry_count == 3
            assert run.next_retry_at is None
            assert run.finished_at is not None
        print("13R.6 Third retry becomes terminal FAILED: PASS")

        # 13R.7 Maintenance DB fence: one due run is scheduled once.
        with SessionLocal.begin() as session:
            run = session.get(ScrapingRun, run_id)
            assert run is not None
            run.status = ScrapingRunStatus.FAILED_RETRY
            run.retry_count = 1
            run.next_retry_at = utcnow() - timedelta(seconds=1)
            run.retry_dispatched_at = None
            run.finished_at = None

        class FakeAsyncResult:
            id = "phase13-run-retry-task"

        with patch(
            "celery_app.tasks.process_scraping_run.delay",
            return_value=FakeAsyncResult(),
        ) as mocked_delay:
            result = maintenance_tick.run()
            assert len(result["scheduled_run_retries"]) == 1
            assert result["scheduled_run_retries"][0]["run_id"] == run_id
            mocked_delay.assert_called_once_with(run_id)

        with SessionLocal() as session:
            run = session.get(ScrapingRun, run_id)
            assert run is not None
            assert run.retry_dispatched_at is not None

        print("13R.7 Maintenance run-retry DB dispatch fence: PASS")

        with patch(
            "celery_app.tasks.process_scraping_run.delay",
            return_value=FakeAsyncResult(),
        ) as mocked_delay:
            result = maintenance_tick.run()
            assert result["scheduled_run_retries"] == []
            mocked_delay.assert_not_called()
        print("13R.8 Duplicate maintenance tick does not re-dispatch: PASS")

        print()
        print("=" * 70)
        print("PHASE 13 RUN RETRY LIFECYCLE: PASS")
        print("=" * 70)
        return 0
    finally:
        cleanup(run_id)


if __name__ == "__main__":
    raise SystemExit(main())
