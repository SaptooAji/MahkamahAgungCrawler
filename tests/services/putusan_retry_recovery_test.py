from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import (
    putusan_lifecycle_service,
    claim_putusan_by_id,
    recover_stale_processing_putusan,
)


TEST_PREFIX = "https://example.test/phase-9/"


def seed_rows() -> list[int]:
    with SessionLocal.begin() as session:
        urls = [f"{TEST_PREFIX}{i}" for i in range(1, 6)]

        session.execute(
            delete(Putusan).where(Putusan.url_detail.in_(urls))
        )

        rows = [
            Putusan(
                tahun=2099,
                halaman=i,
                url_detail=url,
                judul=f"PHASE 9 TEST {i}",
                status_scraping=ScrapingStatus.PENDING,
                url_pdf=None,
                retry_count=0,
            )
            for i, url in enumerate(urls, start=1)
        ]

        session.add_all(rows)
        session.flush()
        return [row.id for row in rows]


def test_failed_retry_becomes_claimable(ids: list[int]) -> None:
    putusan_id = ids[0]
    worker_id = "phase-9-worker"

    # Claim first.
    with SessionLocal.begin() as session:
        row = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
        )
        assert row is not None
        token = row.processing_token
        assert token

        putusan_lifecycle_service.mark_failed_retry(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            processing_token=token,
            error_message="phase-9 retry test",
            retry_delay_seconds=0,
        )

    # Retry is immediately eligible.
    with SessionLocal.begin() as session:
        row = session.get(Putusan, putusan_id)
        assert row is not None
        assert row.status_scraping == ScrapingStatus.FAILED_RETRY
        assert row.retry_count == 1
        assert row.next_retry_at is not None

        reclaimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="phase-9-worker-retry",
        )
        assert reclaimed is not None
        assert reclaimed.status_scraping == ScrapingStatus.PROCESSING
        assert reclaimed.processing_worker_id == "phase-9-worker-retry"
        assert reclaimed.processing_token

    print("9.1 FAILED_RETRY -> reclaimable: PASS")


def test_future_retry_is_blocked(ids: list[int]) -> None:
    putusan_id = ids[1]

    with SessionLocal.begin() as session:
        row = session.get(Putusan, putusan_id)
        assert row is not None
        row.status_scraping = ScrapingStatus.FAILED_RETRY
        row.retry_count = 2
        row.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    with SessionLocal.begin() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="phase-9-too-early",
        )
        assert claimed is None

    print("9.2 Future next_retry_at blocks claim: PASS")


def test_stale_processing_recovery(ids: list[int]) -> None:
    putusan_id = ids[2]

    stale_time = datetime.now(timezone.utc) - timedelta(hours=2)

    with SessionLocal.begin() as session:
        row = session.get(Putusan, putusan_id)
        assert row is not None

        row.status_scraping = ScrapingStatus.PROCESSING
        row.processing_started_at = stale_time
        row.processing_worker_id = "dead-worker"
        row.processing_token = "stale-token"
        row.retry_count = 0
        row.next_retry_at = None

    with SessionLocal.begin() as session:
        recovered = recover_stale_processing_putusan(
            session,
            lease_timeout_seconds=1800,
        )
        assert recovered == 1

    with SessionLocal() as session:
        row = session.get(Putusan, putusan_id)
        assert row is not None

        assert row.status_scraping == ScrapingStatus.FAILED_RETRY
        assert row.retry_count == 1
        assert row.last_error == (
            "Processing lease expired; job recovered automatically."
        )
        assert row.processing_started_at is None
        assert row.processing_worker_id is None
        assert row.processing_token is None
        assert row.next_retry_at is not None

    print("9.3 Stale PROCESSING recovery: PASS")


def test_fresh_processing_is_not_recovered(ids: list[int]) -> None:
    putusan_id = ids[3]

    fresh_time = datetime.now(timezone.utc) - timedelta(seconds=10)

    with SessionLocal.begin() as session:
        row = session.get(Putusan, putusan_id)
        assert row is not None

        row.status_scraping = ScrapingStatus.PROCESSING
        row.processing_started_at = fresh_time
        row.processing_worker_id = "healthy-worker"
        row.processing_token = "fresh-token"
        row.retry_count = 0
        row.next_retry_at = None

    with SessionLocal.begin() as session:
        recovered = recover_stale_processing_putusan(
            session,
            lease_timeout_seconds=1800,
        )
        assert recovered == 0

    with SessionLocal() as session:
        row = session.get(Putusan, putusan_id)
        assert row is not None
        assert row.status_scraping == ScrapingStatus.PROCESSING
        assert row.processing_worker_id == "healthy-worker"
        assert row.processing_token == "fresh-token"
        assert row.retry_count == 0

    print("9.4 Fresh PROCESSING is not recovered: PASS")


def test_terminal_states_are_not_recovered(ids: list[int]) -> None:
    success_id = ids[4]

    with SessionLocal.begin() as session:
        row = session.get(Putusan, success_id)
        assert row is not None

        row.status_scraping = ScrapingStatus.SUCCESS
        row.url_pdf = "https://example.test/phase-9/success.pdf"
        row.retry_count = 7
        row.last_error = None
        row.processing_started_at = None
        row.processing_worker_id = None
        row.processing_token = None
        row.next_retry_at = None

    # Gunakan timeout normal agar row PROCESSING fresh milik
    # test 9.4 tidak ikut dianggap stale. Recovery service
    # memang bekerja secara global terhadap semua PROCESSING
    # yang melewati lease timeout.
    with SessionLocal.begin() as session:
        recovered = recover_stale_processing_putusan(
            session,
            lease_timeout_seconds=1800,
        )
        assert recovered == 0

    with SessionLocal() as session:
        row = session.get(Putusan, success_id)
        assert row is not None
        assert row.status_scraping == ScrapingStatus.SUCCESS
        assert row.url_pdf == "https://example.test/phase-9/success.pdf"
        assert row.retry_count == 7

    print("9.5 SUCCESS remains terminal during recovery: PASS")


def test_recovered_row_can_be_reclaimed(ids: list[int]) -> None:
    putusan_id = ids[2]

    with SessionLocal.begin() as session:
        row = session.get(Putusan, putusan_id)
        assert row is not None
        assert row.status_scraping == ScrapingStatus.FAILED_RETRY
        assert row.next_retry_at is not None

        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="phase-9-recovery-worker",
        )
        assert claimed is not None
        assert claimed.status_scraping == ScrapingStatus.PROCESSING
        assert claimed.processing_worker_id == "phase-9-recovery-worker"
        assert claimed.processing_token

    print("9.6 Recovered row can be reclaimed: PASS")


def cleanup(ids: list[int]) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            delete(Putusan).where(Putusan.id.in_(ids))
        )

    print(f"Cleanup Phase 9 Putusan IDs: {ids}")


def main() -> None:
    print("=" * 70)
    print("PHASE 9 - PUTUSAN RETRY & RECOVERY")
    print("=" * 70)
    print(f"ENV_FILE: {os.getenv('ENV_FILE', '.env')}")

    ids: list[int] = []

    try:
        ids = seed_rows()

        test_failed_retry_becomes_claimable(ids)
        test_future_retry_is_blocked(ids)
        test_stale_processing_recovery(ids)
        test_fresh_processing_is_not_recovered(ids)
        test_terminal_states_are_not_recovered(ids)
        test_recovered_row_can_be_reclaimed(ids)

        print()
        print("=" * 70)
        print("PHASE 9: PASS")
        print("=" * 70)

    finally:
        if ids:
            cleanup(ids)


if __name__ == "__main__":
    main()
