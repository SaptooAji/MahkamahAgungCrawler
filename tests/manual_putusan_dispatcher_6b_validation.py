from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_dispatcher import get_pending_putusan_ids


def seed_rows() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    rows = [
        ("eligible_pending", ScrapingStatus.PENDING, None),
        ("eligible_failed_null", ScrapingStatus.FAILED_RETRY, None),
        ("eligible_failed_past", ScrapingStatus.FAILED_RETRY, now - timedelta(minutes=5)),
        ("blocked_success", ScrapingStatus.SUCCESS, None),
        ("blocked_unpublished", ScrapingStatus.UNPUBLISHED, None),
        ("blocked_processing", ScrapingStatus.PROCESSING, None),
        ("blocked_failed_future", ScrapingStatus.FAILED_RETRY, now + timedelta(hours=1)),
    ]

    ids: dict[str, int] = {}
    with SessionLocal.begin() as session:
        for key, status, next_retry_at in rows:
            row = Putusan(
                tahun=2099,
                halaman=6,
                url_detail=f"https://test.local/phase6b-validation/{key}",
                judul=f"Phase 6B {key}",
                status_scraping=status,
                retry_count=0,
                next_retry_at=next_retry_at,
            )
            session.add(row)
            session.flush()
            ids[key] = row.id
    return ids


def cleanup(ids: dict[str, int]) -> None:
    with SessionLocal.begin() as session:
        for row_id in ids.values():
            row = session.get(Putusan, row_id)
            if row is not None:
                session.delete(row)


def main() -> None:
    print("=" * 70)
    print("PHASE 6B - PUTUSAN DISPATCHER VALIDATION")
    print("=" * 70)
    print("ENV_FILE:", os.getenv("ENV_FILE", ".env"))

    ids = seed_rows()
    print("Seeded IDs:", ids)

    try:
        # 6B.3: hard batch limit
        candidates = get_pending_putusan_ids(batch_size=5)
        print("\nDispatcher returned:", candidates)
        assert len(candidates) <= 5, "Dispatcher melebihi batch_size=5."
        print("PASS: batch size <= 5")

        # 6B.1 + 6B.2: every returned row must be eligible now.
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            rows = session.scalars(
                select(Putusan).where(Putusan.id.in_(candidates))
            ).all()

            assert len(rows) == len(candidates), "Ada candidate yang tidak ditemukan."
            for row in rows:
                assert row.status_scraping in {
                    ScrapingStatus.PENDING,
                    ScrapingStatus.FAILED_RETRY,
                }, f"Status tidak eligible: {row.id}={row.status_scraping}"
                assert (
                    row.next_retry_at is None
                    or row.next_retry_at <= now
                ), f"next_retry_at belum jatuh tempo: {row.id}"
        print("PASS: semua candidate memenuhi PENDING/FAILED_RETRY + retry schedule")

        # 6B.5: protected states must not be dispatched.
        protected = {
            ids["blocked_success"],
            ids["blocked_unpublished"],
            ids["blocked_processing"],
            ids["blocked_failed_future"],
        }
        assert not protected.intersection(candidates), (
            "Protected state masuk candidate: "
            f"{protected.intersection(candidates)}"
        )
        print("PASS: SUCCESS/UNPUBLISHED/PROCESSING/future-retry tidak masuk")

        # Seeded eligible rows must remain eligible and unclaimed.
        eligible = {
            ids["eligible_pending"],
            ids["eligible_failed_null"],
            ids["eligible_failed_past"],
        }
        with SessionLocal() as session:
            seeded = session.scalars(
                select(Putusan).where(Putusan.id.in_(list(ids.values())))
            ).all()
            by_id = {row.id: row for row in seeded}

            for key in ("eligible_pending", "eligible_failed_null", "eligible_failed_past"):
                row = by_id[ids[key]]
                assert row.processing_token is None, f"Dispatcher melakukan claim pada {row.id}"
                assert row.processing_worker_id is None, f"Dispatcher mengisi worker pada {row.id}"
                assert row.processing_started_at is None, f"Dispatcher mengubah processing_started_at pada {row.id}"

            assert by_id[ids["blocked_success"]].status_scraping == ScrapingStatus.SUCCESS
            assert by_id[ids["blocked_unpublished"]].status_scraping == ScrapingStatus.UNPUBLISHED
            assert by_id[ids["blocked_processing"]].status_scraping == ScrapingStatus.PROCESSING

        print("PASS: dispatcher tidak melakukan claim / state mutation")

        # Dispatcher may return older global rows first; that is intentional.
        print("\nNOTE: candidate IDs berasal dari seluruh tabel Putusan.")
        print("      Test tidak mengharapkan seed IDs tertentu berada di posisi pertama.")

        print("\n" + "=" * 70)
        print("PHASE 6B.1-6B.5: PASS")
        print("=" * 70)

    finally:
        cleanup(ids)
        print("Cleanup test rows: DONE")


if __name__ == "__main__":
    main()
