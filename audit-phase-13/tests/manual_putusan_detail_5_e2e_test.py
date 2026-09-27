from __future__ import annotations

import os
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import select, func

env_file = os.getenv("ENV_FILE", ".env")
load_dotenv(env_file)

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from celery_app.tasks import dispatch_pending_putusan


BATCH_SIZE = 5
TIMEOUT_SECONDS = 300


def utcnow():
    return datetime.now().astimezone()


def get_counts() -> dict[str, int]:
    with SessionLocal() as session:
        rows = session.execute(
            select(Putusan.status_scraping, func.count(Putusan.id))
            .group_by(Putusan.status_scraping)
        ).all()

        return {status.value: int(count) for status, count in rows}


def get_pending_ids(limit: int = 5) -> list[int]:
    with SessionLocal() as session:
        stmt = (
            select(Putusan.id)
            .where(Putusan.status_scraping == ScrapingStatus.PENDING)
            .order_by(Putusan.id)
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


def get_rows(ids: list[int]) -> list[Putusan]:
    with SessionLocal() as session:
        stmt = (
            select(Putusan)
            .where(Putusan.id.in_(ids))
            .order_by(Putusan.id)
        )
        return list(session.scalars(stmt).all())


def main() -> int:
    print("=" * 70)
    print("PHASE 6A - PUTUSAN DETAIL / PDF URL E2E")
    print("=" * 70)
    print(f"ENV_FILE       : {env_file}")
    print(f"BATCH_SIZE     : {BATCH_SIZE}")
    print()

    before = get_counts()
    pending_ids = get_pending_ids(BATCH_SIZE)

    print(f"Status before  : {before}")
    print(f"Selected IDs   : {pending_ids}")

    if len(pending_ids) != BATCH_SIZE:
        raise RuntimeError(
            f"Expected {BATCH_SIZE} PENDING Putusan, got {len(pending_ids)}"
        )

    rows_before = get_rows(pending_ids)

    for row in rows_before:
        if row.status_scraping != ScrapingStatus.PENDING:
            raise AssertionError(
                f"Putusan {row.id} expected PENDING, "
                f"got {row.status_scraping.value}"
            )
        print(
            f"  - id={row.id} "
            f"tahun={row.tahun} "
            f"halaman={row.halaman} "
            f"url={row.url_detail}"
        )

    print()
    print("Dispatching exactly one Putusan batch...")
    async_result = dispatch_pending_putusan.delay(BATCH_SIZE)
    print(f"Dispatcher task: {async_result.id}")
    print()

    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_signature = None

    while time.monotonic() < deadline:
        rows = get_rows(pending_ids)

        status_by_id = {
            row.id: row.status_scraping.value
            for row in rows
        }

        signature = tuple(
            (putusan_id, status_by_id.get(putusan_id, "MISSING"))
            for putusan_id in pending_ids
        )

        if signature != last_signature:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"{signature}"
            )
            last_signature = signature

        if all(
            status in {
                ScrapingStatus.SUCCESS.value,
                ScrapingStatus.UNPUBLISHED.value,
                ScrapingStatus.FAILED_RETRY.value,
                ScrapingStatus.FAILED_PERMANENT.value,
            }
            for status in status_by_id.values()
        ) and len(status_by_id) == len(pending_ids):
            break

        time.sleep(5)

    rows_after = get_rows(pending_ids)
    counts_after = get_counts()

    print()
    print("Final rows:")
    for row in rows_after:
        print(
            f"  - id={row.id} "
            f"status={row.status_scraping.value} "
            f"url_pdf={row.url_pdf} "
            f"retry={row.retry_count} "
            f"error={row.last_error!r}"
        )

    print()
    print(f"Status after   : {counts_after}")

    if len(rows_after) != BATCH_SIZE:
        raise AssertionError(
            f"Expected {BATCH_SIZE} rows after processing, "
            f"got {len(rows_after)}"
        )

    processing = [
        row.id
        for row in rows_after
        if row.status_scraping == ScrapingStatus.PROCESSING
    ]

    if processing:
        raise AssertionError(
            f"Putusan still PROCESSING: {processing}"
        )

    successful = [
        row
        for row in rows_after
        if row.status_scraping == ScrapingStatus.SUCCESS
    ]

    unpublished = [
        row
        for row in rows_after
        if row.status_scraping == ScrapingStatus.UNPUBLISHED
    ]

    retryable = [
        row
        for row in rows_after
        if row.status_scraping == ScrapingStatus.FAILED_RETRY
    ]

    permanent = [
        row
        for row in rows_after
        if row.status_scraping == ScrapingStatus.FAILED_PERMANENT
    ]

    print()
    print(f"SUCCESS         : {len(successful)}")
    print(f"UNPUBLISHED     : {len(unpublished)}")
    print(f"FAILED_RETRY    : {len(retryable)}")
    print(f"FAILED_PERMANENT: {len(permanent)}")

    # Phase 6A's primary E2E proof:
    # every SUCCESS must have a PDF URL.
    missing_pdf = [
        row.id
        for row in successful
        if not row.url_pdf
    ]

    if missing_pdf:
        raise AssertionError(
            f"SUCCESS Putusan tanpa url_pdf: {missing_pdf}"
        )

    if retryable:
        print()
        print(
            "NOTE: FAILED_RETRY ditemukan. "
            "Ini belum otomatis FAIL Phase 6A; "
            "retry behavior diuji khusus di Phase 9."
        )

    if permanent:
        print()
        print(
            "NOTE: FAILED_PERMANENT ditemukan. "
            "Investigasi error sebelum menganggap E2E sehat."
        )

    print()
    print("================================")
    print("PHASE 6A: PASS")
    print("================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
