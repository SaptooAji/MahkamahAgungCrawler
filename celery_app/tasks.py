from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import asdict
from datetime import datetime, timezone

import nodriver as uc

from celery_app.celery import celery_app
from celery import chord
from database.session import SessionLocal
from scraper.detail_page import (
    DetailPageScraper,
    build_detail_page_scraper,
)
from scraper.discovery_page import DiscoveryPageScraper
from services.discovery_page_worker import build_discovery_page_worker
from services.discovery_page_job_service import discovery_page_job_service
from services.putusan_worker import build_putusan_worker
from services.putusan_dispatcher import get_pending_putusan_ids
from services.discovery_page_dispatcher import (
    get_pending_discovery_page_ids,
)
from services.run_finalizer_service import RunFinalizerService
from repositories.discovery_page_job_repository import get_run_status_counts
from repositories.putusan_repository import get_status_counts_by_run_id
from models.discovery_page_job import DiscoveryPageJobStatus
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import putusan_lifecycle_service
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from services.discovery_run_service import discovery_run_service


logger = logging.getLogger(f"celery.{__name__}")


def get_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


# ============================================================
# PUTUSAN PROCESS
# ============================================================

async def _process_putusan(
    putusan_id: int,
    worker_id: str,
    run_id: int | None = None,
) -> dict:
    logger.info(
        "PUTUSAN_TASK_START putusan_id=%s worker_id=%s",
        putusan_id,
        worker_id,
    )

    worker = build_putusan_worker()

    # ============================================================
    # 1. CLAIM DULU
    # ============================================================

    claimed = worker.claim(
        putusan_id=putusan_id,
        worker_id=worker_id,
        run_id=run_id,
    )

    if claimed is None:
        logger.info(
            "PUTUSAN_TASK_SKIPPED "
            "putusan_id=%s worker_id=%s reason=claim_failed",
            putusan_id,
            worker_id,
        )

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

    logger.info(
        "PUTUSAN_CLAIMED putusan_id=%s worker_id=%s",
        putusan_id,
        worker_id,
    )

    # ============================================================
    # 2. BARU START BROWSER
    # ============================================================

    try:
        browser = await uc.start(
            headless=False,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )
    except Exception as exc:
        with SessionLocal.begin() as session:
            putusan = session.get(Putusan, putusan_id)
            if putusan is not None and (
                run_id is None or putusan.run_id == run_id
            ):
                putusan_lifecycle_service.mark_failed_retry(
                    session,
                    putusan_id=putusan_id,
                    worker_id=worker_id,
                    processing_token=claimed.processing_token,
                    error_message=f"{type(exc).__name__}: {exc}",
                )
                run = session.get(ScrapingRun, putusan.run_id)
                if run is not None:
                    RunFinalizerService().try_finalize(
                        session,
                        run=run,
                    )
        raise

    logger.info(
        "PUTUSAN_BROWSER_STARTED putusan_id=%s worker_id=%s",
        putusan_id,
        worker_id,
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

        logger.info(
            "PUTUSAN_TASK_FINISHED "
            "putusan_id=%s worker_id=%s status=%s",
            result.putusan_id,
            worker_id,
            result.status,
        )

        return {
            "putusan_id": result.putusan_id,
            "status": result.status,
            "url_detail": result.url_detail,
            "url_pdf": result.url_pdf,
            "error_message": result.error_message,
        }

    except Exception as exc:
        logger.exception(
            "PUTUSAN_TASK_ERROR "
            "putusan_id=%s worker_id=%s",
            putusan_id,
            worker_id,
        )

        return {
            "putusan_id": putusan_id,
            "status": "FAILED_RETRY",
            "url_detail": "",
            "url_pdf": None,
            "error_message": f"{type(exc).__name__}: {exc}",
        }

    finally:
        logger.info(
            "PUTUSAN_BROWSER_STOP "
            "putusan_id=%s worker_id=%s",
            putusan_id,
            worker_id,
        )
        browser.stop()

@celery_app.task(
    bind=True,
    name="putusan.dispatch_pending",
)
def dispatch_pending_putusan(
    self,
    batch_size: int = 5,
    run_id: int | None = None,
) -> dict:
    """
    Mengirim maksimal batch_size Putusan yang siap diproses.

    Dispatcher tidak melakukan claim.
    Claim dilakukan oleh putusan.process.

    Batch berikutnya hanya dijadwalkan setelah seluruh task
    pada batch saat ini selesai.
    """

    logger.info(
        "PUTUSAN_DISPATCH_START batch_size=%s",
        batch_size,
    )

    if batch_size < 1:
        raise ValueError("batch_size harus >= 1")

    if batch_size > 5:
        raise ValueError(
            "batch_size maksimal 5 untuk konfigurasi worker saat ini."
        )

    if run_id is None:
        raise ValueError("run_id wajib diisi untuk dispatcher Putusan.")

    putusan_ids = get_pending_putusan_ids(
        batch_size=batch_size,
        run_id=run_id,
    )

    logger.info(
        "PUTUSAN_DISPATCH_SELECTED "
        "putusan_ids=%s count=%s",
        putusan_ids,
        len(putusan_ids),
    )

    if not putusan_ids:
        logger.info(
            "PUTUSAN_DISPATCH_EMPTY"
        )

        return {
            "dispatched": 0,
            "putusan_ids": [],
            "task_ids": [],
            "next_batch_scheduled": False,
        }

    tasks = [
        process_putusan.s(putusan_id, run_id=run_id)
        for putusan_id in putusan_ids
    ]

    callback = dispatch_pending_putusan.si(
        batch_size=batch_size,
        run_id=run_id,
    )

    result = chord(tasks)(callback)

    logger.info(
        "PUTUSAN_BATCH_SCHEDULED "
        "putusan_ids=%s chord_id=%s",
        putusan_ids,
        result.id,
    )

    return {
        "dispatched": len(putusan_ids),
        "putusan_ids": putusan_ids,
        "chord_id": result.id,
        "next_batch_scheduled": True,
    }

@celery_app.task(
    bind=True,
    name="putusan.process",
)
def process_putusan(
    self,
    putusan_id: int,
    run_id: int | None = None,
) -> dict:
    worker_id = get_worker_id()

    return asyncio.run(
        _process_putusan(
            putusan_id,
            worker_id,
            run_id,
        )
    )


# ============================================================
# DISCOVERY PAGE BATCH PROCESS
# ============================================================

DISCOVERY_BATCH_SIZE_MAX = 5


async def _process_discovery_page_batch(
    page_job_ids: list[int],
    worker_id: str,
) -> dict:
    """
    Memproses satu batch DiscoveryPageJob secara sequential.

    Invariant:

    - maksimal 5 job per batch;
    - claim dilakukan sebelum browser dimulai;
    - satu batch menggunakan satu browser;
    - kegagalan satu job tidak menghentikan job berikutnya.

    Lifecycle status job tetap menjadi tanggung jawab
    DiscoveryPageWorker melalui process_claimed().
    """

    logger.info(
        "DISCOVERY_BATCH_START "
        "page_job_ids=%s worker_id=%s",
        page_job_ids,
        worker_id,
    )

    if not page_job_ids:
        return {
            "requested": 0,
            "claimed": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "next_batch_scheduled": False,
            "next_task_id": None,
        }

    if len(page_job_ids) > DISCOVERY_BATCH_SIZE_MAX:
        raise ValueError(
            "Jumlah page_job_ids dalam satu batch tidak boleh lebih dari 5."
        )

    scraper = DiscoveryPageScraper(
        render_wait_seconds=5.0,
    )

    worker = build_discovery_page_worker(scraper)

    # ------------------------------------------------------------
    # 1. CLAIM SEMUA JOB DULU
    # ------------------------------------------------------------

    claimed_jobs = []
    skipped_ids = []

    for page_job_id in page_job_ids:
        claimed = worker.claim(
            page_job_id=page_job_id,
            worker_id=worker_id,
        )

        if claimed is None:
            logger.info(
                "DISCOVERY_PAGE_SKIPPED "
                "page_job_id=%s worker_id=%s reason=claim_failed",
                page_job_id,
                worker_id,
            )

            skipped_ids.append(page_job_id)
            continue

        logger.info(
            "DISCOVERY_PAGE_CLAIMED "
            "page_job_id=%s page_number=%s worker_id=%s",
            claimed.page_job_id,
            claimed.page_number,
            worker_id,
        )

        claimed_jobs.append(claimed)

    # Tidak ada job yang berhasil di-claim.

    if not claimed_jobs:
        return {
            "requested": len(page_job_ids),
            "claimed": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": len(skipped_ids),
            "results": [
                {
                    "page_job_id": page_job_id,
                    "status": "SKIPPED",
                }
                for page_job_id in skipped_ids
            ],
            "next_batch_scheduled": False,
            "next_task_id": None,
        }

    # ------------------------------------------------------------
    # 2. BARU START SATU BROWSER
    # ------------------------------------------------------------

    try:
        browser = await uc.start(
            headless=False,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        with SessionLocal.begin() as session:
            for claimed in claimed_jobs:
                try:
                    discovery_page_job_service.mark_failed_retry(
                        session,
                        page_job_id=claimed.page_job_id,
                        worker_id=worker_id,
                        processing_token=claimed.processing_token,
                        error_message=error_message,
                    )
                except Exception:
                    logger.exception(
                        "DISCOVERY_BROWSER_START_RECOVERY_FAILED "
                        "page_job_id=%s worker_id=%s",
                        claimed.page_job_id,
                        worker_id,
                    )
        raise

    logger.info(
        "DISCOVERY_BROWSER_STARTED "
        "worker_id=%s claimed_count=%s",
        worker_id,
        len(claimed_jobs),
    )

    results = [
        {
            "page_job_id": page_job_id,
            "status": "SKIPPED",
        }
        for page_job_id in skipped_ids
    ]

    success_count = 0
    failed_count = 0

    try:
        # --------------------------------------------------------
        # 3. PROCESS SEQUENTIAL DALAM SATU BROWSER
        # --------------------------------------------------------

        for claimed in claimed_jobs:
            try:
                result = await worker.process_claimed(
                    browser,
                    claimed=claimed,
                    worker_id=worker_id,
                )

                results.append({
                    **asdict(result),
                    "status": "SUCCESS",
                })

                logger.info(
                    "DISCOVERY_PAGE_FINISHED "
                    "page_job_id=%s page_number=%s status=SUCCESS "
                    "discovered_count=%s created_count=%s "
                    "existing_count=%s worker_id=%s",
                    claimed.page_job_id,
                    claimed.page_number,
                    result.discovered_count,
                    result.created_count,
                    result.existing_count,
                    worker_id,
                )

                success_count += 1

            except Exception as exc:
                logger.exception(
                    "DISCOVERY_PAGE_ERROR "
                    "page_job_id=%s page_number=%s worker_id=%s",
                    claimed.page_job_id,
                    claimed.page_number,
                    worker_id,
                )

                # process_claimed() sudah bertanggung jawab menandai
                # job FAILED_RETRY sebelum exception dilempar kembali.

                results.append({
                    "page_job_id": claimed.page_job_id,
                    "page_number": claimed.page_number,
                    "status": "FAILED_RETRY",
                    "error_message": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                })

                failed_count += 1

        return {
            "requested": len(page_job_ids),
            "claimed": len(claimed_jobs),
            "processed": len(claimed_jobs),
            "success": success_count,
            "failed": failed_count,
            "skipped": len(skipped_ids),
            "results": results,
        }

    finally:
        logger.info(
            "DISCOVERY_BROWSER_STOP "
            "worker_id=%s claimed_count=%s",
            worker_id,
            len(claimed_jobs),
        )

        browser.stop()


@celery_app.task(
    bind=True,
    name="discovery_page.dispatch_pending",
)
def dispatch_pending_discovery_page(
    self,
    batch_size: int = DISCOVERY_BATCH_SIZE_MAX,
    run_id: int | None = None,
) -> dict:
    """
    Memulai satu batch DiscoveryPageJob.

    Dispatcher hanya memilih ID yang siap diproses.
    Claim tetap dilakukan oleh batch worker setelah task dimulai.
    """

    logger.info(
        "DISCOVERY_DISPATCH_START "
        "batch_size=%s run_id=%s",
        batch_size,
        run_id,
    )

    if batch_size < 1:
        raise ValueError("batch_size harus >= 1")

    if batch_size > DISCOVERY_BATCH_SIZE_MAX:
        raise ValueError(
            "batch_size maksimal 5 untuk konfigurasi worker saat ini."
        )

    page_job_ids = get_pending_discovery_page_ids(
        batch_size=batch_size,
        run_id=run_id,
    )

    logger.info(
        "DISCOVERY_DISPATCH_SELECTED "
        "run_id=%s page_job_ids=%s count=%s",
        run_id,
        page_job_ids,
        len(page_job_ids),
    )

    if not page_job_ids:
        logger.info(
            "DISCOVERY_DISPATCH_EMPTY run_id=%s",
            run_id,
        )

        return {
            "dispatched": 0,
            "page_job_ids": [],
            "task_id": None,
        }

    result = process_discovery_page_batch.delay(
        page_job_ids,
        run_id=run_id,
    )

    logger.info(
        "DISCOVERY_BATCH_SCHEDULED "
        "run_id=%s page_job_ids=%s task_id=%s",
        run_id,
        page_job_ids,
        result.id,
    )

    return {
        "dispatched": len(page_job_ids),
        "page_job_ids": page_job_ids,
        "task_id": result.id,
    }


@celery_app.task(
    bind=True,
    name="discovery_page.process_batch",
)
def process_discovery_page_batch(
    self,
    page_job_ids: list[int],
    run_id: int | None = None,
) -> dict:
    """
    Celery entry point untuk satu batch.

    Setelah batch selesai, satu batch berikutnya dijadwalkan
    otomatis jika masih ada DiscoveryPageJob yang pending.
    """

    if not page_job_ids:
        return {
            "requested": 0,
            "claimed": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "next_batch_scheduled": False,
            "next_task_id": None,
        }

    if len(page_job_ids) > DISCOVERY_BATCH_SIZE_MAX:
        raise ValueError(
            "Satu batch maksimal berisi 5 DiscoveryPageJob."
        )

    worker_id = get_worker_id()

    logger.info(
        "DISCOVERY_BATCH_TASK_START "
        "run_id=%s page_job_ids=%s worker_id=%s",
        run_id,
        page_job_ids,
        worker_id,
    )

    result = asyncio.run(
        _process_discovery_page_batch(
            page_job_ids,
            worker_id,
        )
    )

    # ------------------------------------------------------------
    # AUTOMATIC NEXT BATCH
    # ------------------------------------------------------------

    next_page_job_ids = get_pending_discovery_page_ids(
        batch_size=DISCOVERY_BATCH_SIZE_MAX,
        run_id=run_id,
    )

    if next_page_job_ids:
        next_task = process_discovery_page_batch.delay(
            next_page_job_ids,
            run_id=run_id,
        )

        logger.info(
            "DISCOVERY_NEXT_BATCH_SCHEDULED "
            "run_id=%s page_job_ids=%s task_id=%s worker_id=%s",
            run_id,
            next_page_job_ids,
            next_task.id,
            worker_id,
        )

        result["next_batch_scheduled"] = True
        result["next_task_id"] = next_task.id

    else:
        logger.info(
            "DISCOVERY_BATCH_CHAIN_COMPLETE "
            "run_id=%s worker_id=%s",
            run_id,
            worker_id,
        )

        result["next_batch_scheduled"] = False
        result["next_task_id"] = None

    return result


@celery_app.task(
    bind=True,
    name="discovery_page.process",
)
def process_discovery_page(
    self,
    page_job_id: int,
) -> dict:
    """
    Manual/recovery path untuk satu DiscoveryPageJob.

    Path ini sengaja dipertahankan untuk debugging dan recovery.

    Jalur normal Phase 5 menggunakan process_discovery_page_batch.
    """

    worker_id = get_worker_id()

    return asyncio.run(
        _process_discovery_page(
            page_job_id,
            worker_id,
        )
    )


async def _process_discovery_page(
    page_job_id: int,
    worker_id: str,
) -> dict:
    """Single-job compatibility/recovery path."""

    scraper = DiscoveryPageScraper(
        render_wait_seconds=5.0,
    )

    worker = build_discovery_page_worker(scraper)

    claimed = worker.claim(
        page_job_id=page_job_id,
        worker_id=worker_id,
    )

    if claimed is None:
        logger.info(
            "DISCOVERY_PAGE_MANUAL_SKIPPED "
            "page_job_id=%s worker_id=%s reason=claim_failed",
            page_job_id,
            worker_id,
        )

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

    logger.info(
        "DISCOVERY_PAGE_MANUAL_CLAIMED "
        "page_job_id=%s page_number=%s worker_id=%s",
        claimed.page_job_id,
        claimed.page_number,
        worker_id,
    )

    browser = await uc.start(
        headless=False,
        browser_args=[
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--mute-audio",
        ],
    )

    logger.info(
        "DISCOVERY_MANUAL_BROWSER_STARTED "
        "page_job_id=%s worker_id=%s",
        claimed.page_job_id,
        worker_id,
    )

    try:
        result = await worker.process_claimed(
            browser,
            claimed=claimed,
            worker_id=worker_id,
        )

        logger.info(
            "DISCOVERY_PAGE_FINISHED "
            "page_job_id=%s page_number=%s status=SUCCESS "
            "discovered_count=%s created_count=%s "
            "existing_count=%s worker_id=%s",
            claimed.page_job_id,
            claimed.page_number,
            result.discovered_count,
            result.created_count,
            result.existing_count,
            worker_id,
        )

        return asdict(result)

    except Exception:
        logger.exception(
            "DISCOVERY_PAGE_MANUAL_ERROR "
            "page_job_id=%s page_number=%s worker_id=%s",
            claimed.page_job_id,
            claimed.page_number,
            worker_id,
        )
        raise

    finally:
        logger.info(
            "DISCOVERY_MANUAL_BROWSER_STOP "
            "page_job_id=%s worker_id=%s",
            claimed.page_job_id,
            worker_id,
        )

        browser.stop()


@celery_app.task(
    name="scraping_run.process",
)
def process_scraping_run(run_id: int) -> dict:
    logger.info(
        "SCRAPING_RUN_TASK_START run_id=%s",
        run_id,
    )

    return asyncio.run(
        _process_scraping_run(
            run_id=run_id,
            worker_id=get_worker_id(),
        )
    )


async def _process_scraping_run(
    run_id: int,
    worker_id: str,
) -> dict:
    # ---------------------------------------------------------
    # STEP 1 — Claim run dalam transaction pendek
    # ---------------------------------------------------------

    logger.info(
        "SCRAPING_RUN_CLAIM_START "
        "run_id=%s worker_id=%s",
        run_id,
        worker_id,
    )

    with SessionLocal.begin() as session:
        run = discovery_run_service.claim_run(
            session,
            run_id=run_id,
        )

        if run is None:
            logger.info(
                "SCRAPING_RUN_SKIPPED "
                "run_id=%s worker_id=%s reason=run_not_claimable",
                run_id,
                worker_id,
            )

            return {
                "run_id": run_id,
                "status": "SKIPPED",
                "reason": "run_not_claimable",
            }

        claimed_run_id = run.id
        tahun = run.tahun
        url_halaman_pertama = run.url_halaman_pertama

    logger.info(
        "SCRAPING_RUN_CLAIMED "
        "run_id=%s tahun=%s worker_id=%s",
        claimed_run_id,
        tahun,
        worker_id,
    )

    # ---------------------------------------------------------
    # STEP 2 — Browser discovery
    #
    # Tidak ada transaction DB yang terbuka di sini.
    # ---------------------------------------------------------

    browser = None

    try:
        logger.info(
            "SCRAPING_RUN_BROWSER_START "
            "run_id=%s worker_id=%s",
            claimed_run_id,
            worker_id,
        )

        browser = await uc.start(
            headless=False,
        )

        logger.info(
            "SCRAPING_RUN_BROWSER_STARTED "
            "run_id=%s worker_id=%s",
            claimed_run_id,
            worker_id,
        )

        pagination_result = (
            await discovery_run_service.discover_pagination(
                browser,
                url_halaman_pertama=url_halaman_pertama,
            )
        )

        logger.info(
            "SCRAPING_RUN_PAGINATION_FINISHED "
            "run_id=%s tahun=%s total_pages=%s "
            "pagination_mode=%s worker_id=%s",
            claimed_run_id,
            tahun,
            pagination_result.total_pages,
            pagination_result.mode.value,
            worker_id,
        )

    except Exception as exc:
        logger.exception(
            "SCRAPING_RUN_ERROR "
            "run_id=%s worker_id=%s",
            claimed_run_id,
            worker_id,
        )

        # Mark FAILED dalam transaction terpisah.

        with SessionLocal.begin() as session:
            run = session.get(
                ScrapingRun,
                claimed_run_id,
            )

            if run is not None:
                run.status = ScrapingRunStatus.FAILED
                run.last_error = str(exc)
                run.finished_at = datetime.now(timezone.utc)

        raise

    finally:
        if browser is not None:
            logger.info(
                "SCRAPING_RUN_BROWSER_STOP "
                "run_id=%s worker_id=%s",
                claimed_run_id,
                worker_id,
            )

            browser.stop()

    # ---------------------------------------------------------
    # STEP 3 — Persist hasil discovery
    #
    # Transaction baru setelah browser selesai.
    # ---------------------------------------------------------

    with SessionLocal.begin() as session:
        run = session.get(
            ScrapingRun,
            claimed_run_id,
        )

        if run is None:
            raise RuntimeError(
                f"ScrapingRun {claimed_run_id} tidak ditemukan."
            )

        discovery_run_service.persist_pagination_result(
            session,
            run=run,
            pagination_result=pagination_result,
        )

        discovery_run_service.mark_discovery_phase_completed(
            session,
            run=run,
        )

        logger.info(
            "SCRAPING_RUN_DISCOVERY_COMPLETED "
            "run_id=%s tahun=%s status=%s "
            "total_pages=%s pagination_mode=%s "
            "total_discovered=%s worker_id=%s",
            run.id,
            tahun,
            run.status.value,
            pagination_result.total_pages,
            pagination_result.mode.value,
            run.total_discovered,
            worker_id,
        )

        return {
            "run_id": run.id,
            "tahun": tahun,
            "status": run.status.value,
            "total_pages": pagination_result.total_pages,
            "pagination_mode": pagination_result.mode.value,
            "total_discovered": run.total_discovered,
        }
# ============================================================
# PERIODIC RECOVERY / RETRY MAINTENANCE
# ============================================================

@celery_app.task(name="maintenance.tick")
def maintenance_tick() -> dict:
    """
    Periodic safety net untuk dua hal yang tidak boleh bergantung
    pada callback Celery sebelumnya:

    1. recover PROCESSING yang lease-nya sudah stale;
    2. membangunkan kembali retry yang sudah melewati next_retry_at.

    Dispatcher tetap melakukan claim di task worker sehingga tick ini
    aman terhadap duplicate scheduling. run_id selalu dibawa sampai
    dispatcher agar run tidak saling mengambil pekerjaan.
    """
    recovered_putusan = 0
    recovered_pages = 0

    with SessionLocal.begin() as session:
        recovered_putusan = putusan_lifecycle_service.recover_stale(
            session,
            lease_timeout_seconds=1800,
        )

        from services.discovery_page_job_service import (
            discovery_page_job_service,
        )

        recovered_pages = discovery_page_job_service.recover_stale(
            session,
            stale_after_seconds=900,
        )

        active_runs = list(
            session.scalars(
                select(ScrapingRun).where(
                    ScrapingRun.status.in_(
                        [
                            ScrapingRunStatus.RUNNING,
                            ScrapingRunStatus.DISCOVERY_COMPLETED,
                        ]
                    )
                )
            ).all()
        )

        run_ids = [run.id for run in active_runs]

        # Finalizer setelah recovery dapat langsung menutup run yang
        # ternyata sudah terminal.
        finalizer = RunFinalizerService()
        for run in active_runs:
            finalizer.try_finalize(session, run=run)

    scheduled_discovery = []
    scheduled_putusan = []

    for run_id in run_ids:
        page_counts = get_run_status_counts_for_maintenance(run_id)
        page_processing = page_counts.get(
            DiscoveryPageJobStatus.PROCESSING,
            0,
        )
        page_non_terminal = sum(
            page_counts.get(status, 0)
            for status in (
                DiscoveryPageJobStatus.PENDING,
                DiscoveryPageJobStatus.PROCESSING,
                DiscoveryPageJobStatus.FAILED_RETRY,
            )
        )
        if page_processing == 0:
            page_ids = get_pending_discovery_page_ids(
                batch_size=5,
                run_id=run_id,
            )
            if page_ids:
                task = process_discovery_page_batch.delay(
                    page_ids,
                    run_id=run_id,
                )
                scheduled_discovery.append({
                    "run_id": run_id,
                    "task_id": task.id,
                    "page_job_ids": page_ids,
                })

        putusan_counts = get_putusan_status_counts_for_maintenance(run_id)
        putusan_processing = putusan_counts.get(
            ScrapingStatus.PROCESSING,
            0,
        )
        if (
            run_status_is_discovery_completed(run_id)
            and page_non_terminal == 0
            and putusan_processing == 0
        ):
            putusan_ids = get_pending_putusan_ids(
                batch_size=5,
                run_id=run_id,
            )
            if putusan_ids:
                task = dispatch_pending_putusan.delay(
                    batch_size=5,
                    run_id=run_id,
                )
                scheduled_putusan.append({
                    "run_id": run_id,
                    "task_id": task.id,
                    "candidate_ids": putusan_ids,
                })

    logger.info(
        "MAINTENANCE_TICK recovered_putusan=%s recovered_pages=%s "
        "scheduled_discovery=%s scheduled_putusan=%s",
        recovered_putusan,
        recovered_pages,
        len(scheduled_discovery),
        len(scheduled_putusan),
    )

    return {
        "recovered_putusan": recovered_putusan,
        "recovered_pages": recovered_pages,
        "scheduled_discovery": scheduled_discovery,
        "scheduled_putusan": scheduled_putusan,
    }


def get_run_status_counts_for_maintenance(run_id: int) -> dict:
    with SessionLocal() as session:
        return get_run_status_counts(
            session,
            run_id=run_id,
        )


def get_putusan_status_counts_for_maintenance(run_id: int) -> dict:
    with SessionLocal() as session:
        return get_status_counts_by_run_id(
            session,
            run_id=run_id,
        )


def run_status_is_discovery_completed(run_id: int) -> bool:
    with SessionLocal() as session:
        run = session.get(ScrapingRun, run_id)
        return (
            run is not None
            and run.status == ScrapingRunStatus.DISCOVERY_COMPLETED
        )
