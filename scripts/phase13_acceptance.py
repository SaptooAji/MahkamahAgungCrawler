"""Phase 13 acceptance checks.

Run without --run-id for static/runtime checks only.
Run with --run-id after a local E2E run to verify DB invariants for that run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import inspect

from scraper.pagination import PaginationMode, PaginationScraper
from celery_app.celery import celery_app


class FakePage:
    def __init__(self, links: list[dict]):
        self.links = links

    async def sleep(self, seconds: float):
        return None

    async def evaluate(self, script: str):
        if "challenge-running" in script:
            return json.dumps({"status": "OK", "title": "OK"})
        if "paginationRoot" in script:
            return json.dumps({"found": True, "links": self.links})
        raise AssertionError("Unknown JS payload")


class FakeBrowser:
    def __init__(self, pages: dict[str, FakePage]):
        self.pages = pages

    async def get(self, url: str):
        try:
            return self.pages[url]
        except KeyError as exc:
            raise AssertionError(f"Unexpected browser.get URL: {url}") from exc


def check_sequential_pagination() -> None:
    base = "https://example.test/tahun/2021.html"
    page2 = "https://example.test/tahun/2021/page/2.html"
    page3 = "https://example.test/tahun/2021/page/3.html"

    pages = {
        base: FakePage([
            {"href": page2, "text": "Next", "page": None, "rel": "next"},
        ]),
        page2: FakePage([
            {"href": page3, "text": "Next", "page": None, "rel": "next"},
        ]),
        page3: FakePage([]),
    }

    result = asyncio.run(
        PaginationScraper(render_wait_seconds=0).discover_pages(
            FakeBrowser(pages),
            url_page_1=base,
        )
    )

    assert result.mode == PaginationMode.SEQUENTIAL
    assert result.total_pages == 3
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert [p.url_page for p in result.pages] == [base, page2, page3]

    print("PASS sequential pagination: 1 -> 2 -> 3 -> stop")


def check_celery_schedule() -> None:
    schedule = celery_app.conf.beat_schedule
    entry = schedule.get("maintenance-tick-every-30-seconds")
    assert entry is not None
    assert entry["task"] == "maintenance.tick"
    assert float(entry["schedule"]) == 30.0
    print("PASS Celery Beat maintenance schedule: 30s")


def check_orchestration_contract() -> None:
    from celery_app import tasks as task_module

    registered = set(task_module.celery_app.tasks.keys())

    assert "discovery_page.dispatch_pending" not in registered
    assert "discovery_page.dispatch_batch" in registered
    assert "discovery_page.process_batch" in registered
    assert "putusan.dispatch_pending" in registered

    source = inspect.getsource(task_module)
    assert "from celery import chord" not in source

    discovery_batch_source = inspect.getsource(
        task_module.process_discovery_page_batch.run
        if hasattr(task_module.process_discovery_page_batch, "run")
        else task_module.process_discovery_page_batch
    )
    assert "process_discovery_page_batch.delay(" not in discovery_batch_source

    assert "pg_advisory_xact_lock" in source

    print("PASS orchestration contract: single scheduler + DB dispatch fence")


def check_database(run_id: int) -> None:
    from sqlalchemy import func, select
    from database.session import SessionLocal
    from models.discovery_page_job import (
        DiscoveryPageJob,
        DiscoveryPageJobStatus,
    )
    from models.putusan import Putusan, ScrapingStatus
    from models.scraping_run import ScrapingRun

    with SessionLocal() as session:
        run = session.get(ScrapingRun, run_id)
        assert run is not None, f"run_id={run_id} tidak ditemukan"

        processing_putusan = session.scalar(
            select(func.count(Putusan.id)).where(
                Putusan.run_id == run_id,
                Putusan.status_scraping == ScrapingStatus.PROCESSING,
            )
        )
        assert processing_putusan == 0, processing_putusan

        processing_pages = session.scalar(
            select(func.count(DiscoveryPageJob.id)).where(
                DiscoveryPageJob.run_id == run_id,
                DiscoveryPageJob.status == DiscoveryPageJobStatus.PROCESSING,
            )
        )
        assert processing_pages == 0, processing_pages

        invalid_retry = session.scalar(
            select(func.count(Putusan.id)).where(
                Putusan.run_id == run_id,
                Putusan.retry_count > 3,
            )
        )
        assert invalid_retry == 0, invalid_retry

        bad_success = session.scalar(
            select(func.count(Putusan.id)).where(
                Putusan.run_id == run_id,
                Putusan.status_scraping == ScrapingStatus.SUCCESS,
                Putusan.url_pdf.is_(None),
            )
        )
        assert bad_success == 0, bad_success

        bad_pdf = session.scalar(
            select(func.count(Putusan.id)).where(
                Putusan.run_id == run_id,
                Putusan.status_scraping != ScrapingStatus.SUCCESS,
                Putusan.url_pdf.is_not(None),
            )
        )
        assert bad_pdf == 0, bad_pdf

        bad_permanent = session.scalar(
            select(func.count(Putusan.id)).where(
                Putusan.run_id == run_id,
                Putusan.status_scraping == ScrapingStatus.FAILED_PERMANENT,
                (Putusan.retry_count != 3) | Putusan.next_retry_at.is_not(None),
            )
        )
        assert bad_permanent == 0, bad_permanent

        print(
            "PASS DB invariants: "
            f"run={run_id} status={run.status.value} "
            f"discovered={run.total_discovered} "
            f"success={run.total_success} "
            f"failed={run.total_failed} "
            f"unpublished={run.total_unpublished}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int)
    args = parser.parse_args()

    check_sequential_pagination()
    check_celery_schedule()
    check_orchestration_contract()

    if args.run_id is not None:
        check_database(args.run_id)

    print("PHASE 13 ACCEPTANCE: PASS")


if __name__ == "__main__":
    main()
