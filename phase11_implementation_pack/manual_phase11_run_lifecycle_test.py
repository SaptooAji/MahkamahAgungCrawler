from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import delete, select

from database.session import SessionLocal
from models.discovery_page_job import DiscoveryPageJob, DiscoveryPageJobStatus
from models.putusan import Putusan, ScrapingStatus
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from services.run_lifecycle_service import run_lifecycle_service


TEST_YEAR = 2099
TEST_PREFIX = "https://example.test/phase-11/"


def seed_run() -> tuple[int, list[int], list[int]]:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=TEST_YEAR,
            status=ScrapingRunStatus.RUNNING,
            url_halaman_pertama=f"{TEST_PREFIX}page-1.html",
            total_pages=2,
        )
        session.add(run)
        session.flush()

        page_jobs = []
        for page_number in (1, 2):
            page_job = DiscoveryPageJob(
                run_id=run.id,
                tahun=TEST_YEAR,
                page_number=page_number,
                url_page=f"{TEST_PREFIX}page-{page_number}.html",
                status=DiscoveryPageJobStatus.SUCCESS,
                discovered_count=2,
            )
            session.add(page_job)
            page_jobs.append(page_job)

        putusan_rows = []
        for i, status in enumerate(
            (
                ScrapingStatus.SUCCESS,
                ScrapingStatus.UNPUBLISHED,
                ScrapingStatus.SUCCESS,
            ),
            start=1,
        ):
            row = Putusan(
                run_id=run.id,
                tahun=TEST_YEAR,
                halaman=1,
                url_detail=f"{TEST_PREFIX}putusan-{i}",
                judul=f"PHASE 11 TEST {i}",
                status_scraping=status,
                retry_count=0,
            )
            session.add(row)
            putusan_rows.append(row)

        session.flush()

        return (
            run.id,
            [job.id for job in page_jobs],
            [row.id for row in putusan_rows],
        )


def test_discovery_phase_transition(run_id: int) -> None:
    with SessionLocal.begin() as session:
        run = session.get(ScrapingRun, run_id)
        assert run is not None

        result = run_lifecycle_service.mark_discovery_phase_completed(
            session,
            run=run,
        )

        assert result.status == ScrapingRunStatus.DISCOVERY_COMPLETED
        assert result.finished_at is None

    print("11.1 Discovery phase -> DISCOVERY_COMPLETED: PASS")


def test_final_completion(run_id: int) -> None:
    with SessionLocal.begin() as session:
        run = session.get(ScrapingRun, run_id)
        assert run is not None

        result = run_lifecycle_service.finalize(
            session,
            run=run,
        )

        assert result.status == ScrapingRunStatus.COMPLETED
        assert result.finished_at is not None
        assert result.total_discovered == 3
        assert result.total_success == 2
        assert result.total_unpublished == 1
        assert result.total_failed == 0

    print("11.2 All page jobs + Putusan terminal -> COMPLETED: PASS")


def test_finalize_idempotent(run_id: int) -> None:
    with SessionLocal.begin() as session:
        run = session.get(ScrapingRun, run_id)
        assert run is not None
        original_finished_at = run.finished_at

        result = run_lifecycle_service.finalize(
            session,
            run=run,
        )

        assert result.status == ScrapingRunStatus.COMPLETED
        assert result.finished_at == original_finished_at

    print("11.3 Finalizer is idempotent: PASS")


def seed_incomplete_run() -> int:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=TEST_YEAR,
            status=ScrapingRunStatus.DISCOVERY_COMPLETED,
            url_halaman_pertama=f"{TEST_PREFIX}incomplete-page-1.html",
            total_pages=1,
        )
        session.add(run)
        session.flush()

        session.add(
            DiscoveryPageJob(
                run_id=run.id,
                tahun=TEST_YEAR,
                page_number=1,
                url_page=f"{TEST_PREFIX}incomplete-page-1.html",
                status=DiscoveryPageJobStatus.SUCCESS,
                discovered_count=1,
            )
        )

        session.add(
            Putusan(
                run_id=run.id,
                tahun=TEST_YEAR,
                halaman=1,
                url_detail=f"{TEST_PREFIX}incomplete-putusan",
                judul="PHASE 11 INCOMPLETE",
                status_scraping=ScrapingStatus.FAILED_RETRY,
                retry_count=1,
                next_retry_at=datetime.now(timezone.utc),
            )
        )

        session.flush()
        return run.id


def test_pending_putusan_blocks_completion(run_id: int) -> None:
    with SessionLocal.begin() as session:
        run = session.get(ScrapingRun, run_id)
        assert run is not None

        result = run_lifecycle_service.finalize(
            session,
            run=run,
        )

        assert result.status == ScrapingRunStatus.DISCOVERY_COMPLETED
        assert result.finished_at is None

    print("11.4 FAILED_RETRY Putusan blocks completion: PASS")


def seed_failed_run() -> int:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=TEST_YEAR,
            status=ScrapingRunStatus.DISCOVERY_COMPLETED,
            url_halaman_pertama=f"{TEST_PREFIX}failed-page-1.html",
            total_pages=1,
        )
        session.add(run)
        session.flush()

        session.add(
            DiscoveryPageJob(
                run_id=run.id,
                tahun=TEST_YEAR,
                page_number=1,
                url_page=f"{TEST_PREFIX}failed-page-1.html",
                status=DiscoveryPageJobStatus.FAILED_PERMANENT,
                retry_count=3,
                last_error="permanent page failure",
            )
        )

        session.flush()
        return run.id


def test_failed_permanent_fails_run(run_id: int) -> None:
    with SessionLocal.begin() as session:
        run = session.get(ScrapingRun, run_id)
        assert run is not None

        result = run_lifecycle_service.finalize(
            session,
            run=run,
        )

        assert result.status == ScrapingRunStatus.FAILED
        assert result.finished_at is not None
        assert result.total_failed == 1
        assert result.last_error

    print("11.5 FAILED_PERMANENT -> FAILED: PASS")


def cleanup(run_ids: list[int]) -> None:
    if not run_ids:
        return

    with SessionLocal.begin() as session:
        session.execute(
            delete(Putusan).where(Putusan.run_id.in_(run_ids))
        )
        session.execute(
            delete(DiscoveryPageJob).where(
                DiscoveryPageJob.run_id.in_(run_ids)
            )
        )
        session.execute(
            delete(ScrapingRun).where(ScrapingRun.id.in_(run_ids))
        )


def main() -> None:
    print("=" * 70)
    print("PHASE 11 - AUTOMATIC RUN LIFECYCLE")
    print("=" * 70)
    print(f"ENV_FILE: {os.getenv('ENV_FILE')}")

    run_ids: list[int] = []

    try:
        run_id, _, _ = seed_run()
        run_ids.append(run_id)

        test_discovery_phase_transition(run_id)
        test_final_completion(run_id)
        test_finalize_idempotent(run_id)

        incomplete_id = seed_incomplete_run()
        run_ids.append(incomplete_id)
        test_pending_putusan_blocks_completion(incomplete_id)

        failed_id = seed_failed_run()
        run_ids.append(failed_id)
        test_failed_permanent_fails_run(failed_id)

        print()
        print("=" * 70)
        print("PHASE 11: PASS")
        print("=" * 70)

    finally:
        cleanup(run_ids)
        print(f"Cleanup Phase 11 ScrapingRun IDs: {run_ids}")


if __name__ == "__main__":
    main()
