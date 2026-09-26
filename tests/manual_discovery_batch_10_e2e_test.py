from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import func, select

# ------------------------------------------------------------
# Environment: use exactly the same project env path.
# ------------------------------------------------------------
env_file = os.getenv("ENV_FILE", ".env")
load_dotenv(env_file)

from celery_app.tasks import dispatch_pending_discovery_page
from database.session import SessionLocal
from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)
from models.putusan import Putusan
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from scraper.pagination import PageDescriptor
from services.discovery_page_job_service import discovery_page_job_service
from services.discovery_run_service import discovery_run_service


YEAR = 2021
PAGE_COUNT = 10
BATCH_SIZE = 5
POLL_SECONDS = 5
TIMEOUT_SECONDS = 20 * 60

PAGE_1 = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/tahun/2021.html"
)
PAGE_TEMPLATE = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/tahun/2021/page/{page}.html"
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def count_putusan(session) -> int:
    return int(session.scalar(select(func.count()).select_from(Putusan)) or 0)


def create_clean_test_run() -> tuple[int, list[int]]:
    """
    Create one fresh run and exactly 10 fresh page jobs.
    Existing historical runs/jobs are never touched.
    """
    descriptors = [
        PageDescriptor(
            page_number=1,
            url_page=PAGE_1,
        )
    ] + [
        PageDescriptor(
            page_number=page,
            url_page=PAGE_TEMPLATE.format(page=page),
        )
        for page in range(2, PAGE_COUNT + 1)
    ]

    with SessionLocal.begin() as session:
        run = discovery_run_service.create_run(
            session,
            tahun=YEAR,
            url_halaman_pertama=PAGE_1,
        )
        run.status = ScrapingRunStatus.RUNNING
        run.started_at = utcnow()
        run.total_pages = PAGE_COUNT
        run.total_discovered = 0

        created = discovery_page_job_service.create_from_page_descriptors(
            session,
            run_id=run.id,
            tahun=YEAR,
            pages=descriptors,
        )

        job_ids = list(
            session.scalars(
                select(DiscoveryPageJob.id)
                .where(DiscoveryPageJob.run_id == run.id)
                .order_by(DiscoveryPageJob.page_number)
            ).all()
        )

        if created != PAGE_COUNT or len(job_ids) != PAGE_COUNT:
            raise AssertionError(
                f"Expected 10 new jobs, created={created}, total={len(job_ids)}"
            )

        return run.id, job_ids


def snapshot(run_id: int) -> dict:
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(DiscoveryPageJob)
                .where(DiscoveryPageJob.run_id == run_id)
                .order_by(DiscoveryPageJob.page_number)
            ).all()
        )
        putusan_count = count_putusan(session)

        by_status: dict[str, int] = {}
        for row in rows:
            key = row.status.value
            by_status[key] = by_status.get(key, 0) + 1

        return {
            "jobs": rows,
            "by_status": by_status,
            "putusan_count": putusan_count,
        }


def main() -> int:
    print("=" * 70)
    print("PHASE 5E - CLEAN 10-JOB DISCOVERY BATCH E2E")
    print("=" * 70)
    print(f"ENV_FILE       : {env_file}")
    print(f"YEAR           : {YEAR}")
    print(f"PAGE_COUNT     : {PAGE_COUNT}")
    print(f"BATCH_SIZE     : {BATCH_SIZE}")
    print()

    run_id, job_ids = create_clean_test_run()
    before = snapshot(run_id)
    putusan_before = before["putusan_count"]

    print(f"Created run_id : {run_id}")
    print(f"Created jobs   : {len(job_ids)}")
    print(f"Job IDs        : {job_ids}")
    print(f"Initial status : {before['by_status']}")
    print(f"Putusan before : {putusan_before}")
    print()

    # --------------------------------------------------------
    # Dispatch exactly ONE first batch. The Celery task itself
    # is responsible for scheduling the next batch automatically.
    # --------------------------------------------------------
    async_result = dispatch_pending_discovery_page.delay(BATCH_SIZE)
    print(f"First Celery task: {async_result.id}")
    print("Waiting for automatic batch chaining...")
    print()

    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_report = None

    while time.monotonic() < deadline:
        state = snapshot(run_id)
        status = state["by_status"]
        signature = (tuple(sorted(status.items())), state["putusan_count"])

        if signature != last_report:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"jobs={status} putusan={state['putusan_count']}"
            )
            last_report = signature

        success = status.get("SUCCESS", 0)
        processing = status.get("PROCESSING", 0)
        pending = status.get("PENDING", 0)
        failed_retry = status.get("FAILED_RETRY", 0)
        failed_permanent = status.get("FAILED_PERMANENT", 0)

        # PASS condition for this phase:
        # all 10 jobs completed successfully and none remains active.
        if (
            success == PAGE_COUNT
            and processing == 0
            and pending == 0
        ):
            putusan_after = state["putusan_count"]
            print()
            print("All 10 discovery page jobs are SUCCESS.")
            print(f"Putusan after : {putusan_after}")
            print(f"Putusan delta : {putusan_after - putusan_before}")
            print()

            if failed_retry or failed_permanent:
                print(
                    "FAIL: failure status exists despite all SUCCESS count."
                )
                return 1

            print("================================")
            print("PHASE 5E: PASS")
            print("================================")
            return 0

        if failed_permanent:
            print()
            print("FAIL: FAILED_PERMANENT detected.")
            return 1

        time.sleep(POLL_SECONDS)

    # ------------------------------------------------------------
    # Timeout diagnostics
    # ------------------------------------------------------------
    state = snapshot(run_id)
    print()
    print("================================")
    print("PHASE 5E: FAIL / TIMEOUT")
    print("================================")
    print(f"Final status: {state['by_status']}")
    print(f"Putusan count: {state['putusan_count']}")
    print()

    for row in state["jobs"]:
        print(
            f"page={row.page_number:>2} "
            f"id={row.id} "
            f"status={row.status.value} "
            f"retry={row.retry_count} "
            f"error={row.last_error!r}"
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
