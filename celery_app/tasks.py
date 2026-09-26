from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import asdict

import nodriver as uc

from celery_app.celery import celery_app
from scraper.detail_page import (DetailPageScraper, build_detail_page_scraper)
from scraper.discovery_page import DiscoveryPageScraper
from services.discovery_page_worker import build_discovery_page_worker
from services.putusan_worker import build_putusan_worker
from services.putusan_dispatcher import get_pending_putusan_ids
from services.discovery_page_dispatcher import (
    get_pending_discovery_page_ids,
)


def get_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


# ============================================================
# PUTUSAN PROCESS
# ============================================================

async def _process_putusan(
    putusan_id: int,
    worker_id: str,
) -> dict:
    worker = build_putusan_worker()

    # ============================================================
    # 1. CLAIM DULU
    # ============================================================
    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=worker_id,
    )

    if claimed is None:
        return {
            "putusan_id": putusan_id,
            "status": "SKIPPED",
            "url_detail": "",
            "url_pdf": None,
            "error_message": (
                "Putusan tidak dapat di-claim. "
                "Kemungkinan sudah diproses worker lain, "
                "belum waktunya retry, atau status tidak valid."
            ),
        }

    # ============================================================
    # 2. BARU START BROWSER
    # ============================================================
    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    try:
        # ========================================================
        # 3. SCRAPE PUTUSAN YANG SUDAH DI-CLAIM
        # ========================================================
        result = await worker.process_claimed(
            browser,
            claimed=claimed,
            worker_id=worker_id,
        )

        return {
            "putusan_id": result.putusan_id,
            "status": result.status,
            "url_detail": result.url_detail,
            "url_pdf": result.url_pdf,
            "error_message": result.error_message,
        }

    finally:
        browser.stop()

@celery_app.task(
    bind=True,
    name="putusan.dispatch_pending",
)
def dispatch_pending_putusan(
    self,
    batch_size: int = 5,
) -> dict:
    """
    Mengirim maksimal batch_size Putusan yang siap diproses
    ke Celery.

    Dispatcher tidak melakukan claim.
    Claim dilakukan oleh putusan.process.
    """

    if batch_size < 1:
        raise ValueError("batch_size harus >= 1")

    if batch_size > 5:
        raise ValueError(
            "batch_size maksimal 5 untuk konfigurasi worker saat ini."
        )

    putusan_ids = get_pending_putusan_ids(
        batch_size=batch_size,
    )

    task_ids = []

    for putusan_id in putusan_ids:
        result = process_putusan.delay(putusan_id)
        task_ids.append(result.id)

    return {
        "dispatched": len(putusan_ids),
        "putusan_ids": putusan_ids,
        "task_ids": task_ids,
    }

@celery_app.task(
    bind=True,
    name="putusan.process",
)
def process_putusan(
    self,
    putusan_id: int,
) -> dict:
    worker_id = get_worker_id()

    return asyncio.run(
        _process_putusan(
            putusan_id,
            worker_id,
        )
    )


# ============================================================
# DISCOVERY PAGE PROCESS
# ============================================================

async def _process_discovery_page(
    page_job_id: int,
    worker_id: str,
) -> dict:
    scraper = DiscoveryPageScraper(
        render_wait_seconds=5.0,
    )

    worker = build_discovery_page_worker(scraper)

    claimed = worker.claim(
        page_job_id=page_job_id,
        worker_id=worker_id,
    )

    if claimed is None:
        return {
            "page_job_id": page_job_id,
            "page_number": None,
            "discovered_count": 0,
            "created_count": 0,
            "existing_count": 0,
            "unpublish_count": 0,
            "status": "SKIPPED",
            "error_message": (
                "DiscoveryPageJob tidak dapat di-claim. "
                "Kemungkinan sudah diproses worker lain, "
                "belum waktunya retry, atau status tidak valid."
            ),
        }

    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    try:
        result = await worker.process_claimed(
            browser,
            claimed=claimed,
            worker_id=worker_id,
        )

        return asdict(result)

    finally:
        browser.stop()

@celery_app.task(
    bind=True,
    name="discovery_page.dispatch_pending",
)
def dispatch_pending_discovery_page(
    self,
    batch_size: int = 5,
) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size harus >= 1")

    if batch_size > 5:
        raise ValueError(
            "batch_size maksimal 5 untuk menjaga batas concurrency."
        )

    page_job_ids = get_pending_discovery_page_ids(
        batch_size=batch_size,
    )

    task_ids = []

    for page_job_id in page_job_ids:
        result = process_discovery_page.delay(page_job_id)
        task_ids.append(result.id)

    return {
        "dispatched": len(page_job_ids),
        "page_job_ids": page_job_ids,
        "task_ids": task_ids,
    }

@celery_app.task(
    bind=True,
    name="discovery_page.process",
)
def process_discovery_page(
    self,
    page_job_id: int,
) -> dict:
    worker_id = get_worker_id()

    return asyncio.run(
        _process_discovery_page(
            page_job_id,
            worker_id,
        )
    )