from __future__ import annotations

import os
from unittest.mock import patch
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import delete, select

from celery_app import tasks
from database.session import SessionLocal
from models.discovery_page_job import DiscoveryPageJob, DiscoveryPageJobStatus
from models.putusan import Putusan, ScrapingStatus
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from services.discovery_page_worker import build_discovery_page_worker
from services.putusan_worker import build_putusan_worker


TEST_PREFIX = f"phase13-dispatch-{uuid4().hex}"


class FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


def seed() -> tuple[int, list[int], list[int]]:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=2096,
            status=ScrapingRunStatus.RUNNING,
            url_halaman_pertama=f"https://example.test/{TEST_PREFIX}/page/1.html",
        )
        session.add(run)
        session.flush()

        pages = [
            DiscoveryPageJob(
                run_id=run.id,
                tahun=2096,
                page_number=i,
                url_page=f"https://example.test/{TEST_PREFIX}/page/{i}.html",
                status=DiscoveryPageJobStatus.PENDING,
            )
            for i in range(1, 3)
        ]
        putusans = [
            Putusan(
                run_id=run.id,
                tahun=2096,
                halaman=i,
                url_detail=f"https://example.test/{TEST_PREFIX}/putusan/{i}",
                judul=f"Phase 13 Putusan {i}",
                status_scraping=ScrapingStatus.PENDING,
                retry_count=0,
            )
            for i in range(1, 3)
        ]
        session.add_all(pages + putusans)
        session.flush()
        return run.id, [row.id for row in pages], [row.id for row in putusans]


def assert_discovery_dispatch_fenced(run_id: int, page_ids: list[int]) -> None:
    calls: list[tuple] = []

    def fake_delay(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeAsyncResult(f"discovery-{len(calls)}")

    with patch.object(tasks.process_discovery_page_batch, "delay", side_effect=fake_delay):
        first = tasks.dispatch_pending_discovery_page.apply(
            args=[2],
            kwargs={"run_id": run_id},
        ).get()
        second = tasks.dispatch_pending_discovery_page.apply(
            args=[2],
            kwargs={"run_id": run_id},
        ).get()

    assert first["dispatched"] == 2
    assert second["dispatched"] == 0
    assert second["reason"] == "batch_already_processing"
    assert len(calls) == 1

    with SessionLocal() as session:
        rows = list(session.scalars(
            select(DiscoveryPageJob)
            .where(DiscoveryPageJob.id.in_(page_ids))
            .order_by(DiscoveryPageJob.id)
        ))
        assert all(row.status == DiscoveryPageJobStatus.PROCESSING for row in rows)
        assert all(row.processing_worker_id and row.processing_worker_id.startswith("dispatch:") for row in rows)
        assert all(row.processing_token for row in rows)

    print("PASS discovery dispatch is DB-fenced and non-amplifying")


def assert_putusan_dispatch_fenced(run_id: int, putusan_ids: list[int]) -> None:
    calls: list[tuple] = []

    def fake_delay(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeAsyncResult(f"putusan-{len(calls)}")

    with patch.object(tasks.process_putusan, "delay", side_effect=fake_delay):
        first = tasks.dispatch_pending_putusan.apply(
            args=[2],
            kwargs={"run_id": run_id},
        ).get()
        second = tasks.dispatch_pending_putusan.apply(
            args=[2],
            kwargs={"run_id": run_id},
        ).get()

    assert first["dispatched"] == 2
    assert second["dispatched"] == 0
    assert second["reason"] == "batch_already_processing"
    assert len(calls) == 2

    with SessionLocal() as session:
        rows = list(session.scalars(
            select(Putusan)
            .where(Putusan.id.in_(putusan_ids))
            .order_by(Putusan.id)
        ))
        assert all(row.status_scraping == ScrapingStatus.PROCESSING for row in rows)
        assert all(row.processing_worker_id and row.processing_worker_id.startswith("dispatch:") for row in rows)
        assert all(row.processing_token for row in rows)

    print("PASS putusan dispatch is DB-fenced and non-amplifying")


def assert_child_fencing(run_id: int, page_ids: list[int], putusan_ids: list[int]) -> None:
    with SessionLocal.begin() as session:
        page_owner = session.get(DiscoveryPageJob, page_ids[0]).processing_worker_id
        putusan_owner = session.get(Putusan, putusan_ids[0]).processing_worker_id

    assert page_owner and putusan_owner

    page_worker = build_discovery_page_worker(object())
    adopted_page = page_worker.adopt_claimed(
        page_job_id=page_ids[0],
        dispatch_owner_id=page_owner,
        worker_id="phase13-real-worker-page",
    )
    assert adopted_page is not None
    duplicate_page = page_worker.adopt_claimed(
        page_job_id=page_ids[0],
        dispatch_owner_id=page_owner,
        worker_id="phase13-duplicate-page",
    )
    assert duplicate_page is None

    putusan_worker = build_putusan_worker(object())
    adopted_putusan = putusan_worker.adopt_claimed(
        putusan_id=putusan_ids[0],
        dispatch_owner_id=putusan_owner,
        worker_id="phase13-real-worker-putusan",
    )
    assert adopted_putusan is not None
    duplicate_putusan = putusan_worker.adopt_claimed(
        putusan_id=putusan_ids[0],
        dispatch_owner_id=putusan_owner,
        worker_id="phase13-duplicate-putusan",
    )
    assert duplicate_putusan is None

    print("PASS child task fencing prevents duplicate processing ownership")


def cleanup(run_id: int) -> None:
    with SessionLocal.begin() as session:
        session.execute(delete(Putusan).where(Putusan.run_id == run_id))
        session.execute(delete(DiscoveryPageJob).where(DiscoveryPageJob.run_id == run_id))
        session.execute(delete(ScrapingRun).where(ScrapingRun.id == run_id))


def main() -> None:
    env_file = os.getenv("ENV_FILE", ".env.test")
    load_dotenv(env_file, override=False)
    print("=" * 72)
    print("PHASE 13 - DISPATCH / QUEUE IDEMPOTENCY")
    print("=" * 72)
    print(f"ENV_FILE: {env_file}")

    run_id, page_ids, putusan_ids = seed()
    try:
        assert_discovery_dispatch_fenced(run_id, page_ids)
        assert_putusan_dispatch_fenced(run_id, putusan_ids)
        assert_child_fencing(run_id, page_ids, putusan_ids)
        print("=" * 72)
        print("PHASE 13 DISPATCH TEST: PASS")
        print("=" * 72)
    finally:
        cleanup(run_id)


if __name__ == "__main__":
    main()
