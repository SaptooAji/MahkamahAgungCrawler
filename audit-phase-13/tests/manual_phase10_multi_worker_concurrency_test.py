from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from sqlalchemy import delete, select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import claim_pending_putusan


TEST_PREFIX = "https://example.test/phase-10/"
TEST_YEAR = 2099
BATCH_SIZE = 5
TOTAL_ROWS = 10


@dataclass
class WorkerResult:
    worker_id: str
    ids: list[int]
    tokens: list[str]
    error: BaseException | None = None


def seed_rows() -> tuple[list[int], list[int]]:
    """
    Seed exactly 10 eligible rows and temporarily isolate the
    rest of the test database from the global claim selector.

    Production claim_pending_putusan() intentionally claims
    globally. Therefore the test must establish the invariant
    that these are the only eligible rows before testing
    concurrency.
    """
    with SessionLocal.begin() as session:
        urls = [
            f"{TEST_PREFIX}{i}"
            for i in range(1, TOTAL_ROWS + 1)
        ]

        session.execute(
            delete(Putusan).where(
                Putusan.url_detail.in_(urls)
            )
        )

        # Snapshot every pre-existing eligible row. The production
        # selector is global, so these rows would otherwise compete
        # with the Phase 10 rows.
        eligible_rows = list(
            session.scalars(
                select(Putusan).where(
                    Putusan.status_scraping.in_(
                        [
                            ScrapingStatus.PENDING,
                            ScrapingStatus.FAILED_RETRY,
                        ]
                    )
                )
            ).all()
        )

        isolated_ids = [row.id for row in eligible_rows]

        # Temporarily make all unrelated rows ineligible.
        for row in eligible_rows:
            row.status_scraping = ScrapingStatus.SUCCESS
            row.next_retry_at = None

        rows = [
            Putusan(
                tahun=TEST_YEAR,
                halaman=i,
                url_detail=url,
                judul=f"PHASE 10 TEST {i}",
                status_scraping=ScrapingStatus.PENDING,
                retry_count=0,
                url_pdf=None,
            )
            for i, url in enumerate(urls, start=1)
        ]

        session.add_all(rows)
        session.flush()

        return [row.id for row in rows], isolated_ids


def restore_isolated_rows(isolated_ids: list[int]) -> None:
    """Restore pre-existing eligible rows after the test."""
    if not isolated_ids:
        return

    with SessionLocal.begin() as session:
        rows = list(
            session.scalars(
                select(Putusan).where(
                    Putusan.id.in_(isolated_ids)
                )
            ).all()
        )

        for row in rows:
            # These rows were eligible before Phase 10. Restore them
            # to PENDING so the test is non-destructive to the test DB.
            row.status_scraping = ScrapingStatus.PENDING
            row.next_retry_at = None
            row.last_error = None


def concurrent_claim_worker(
    *,
    worker_id: str,
    barrier: threading.Barrier,
    result: WorkerResult,
) -> None:
    """
    Claim one batch in a real PostgreSQL transaction.

    The transaction intentionally stays open until both workers
    have completed their SELECT ... FOR UPDATE SKIP LOCKED.
    This makes the lock behavior observable rather than merely
    testing two sequential claims.
    """
    session = SessionLocal()

    try:
        session.begin()

        claimed = claim_pending_putusan(
            session,
            worker_id=worker_id,
            batch_size=BATCH_SIZE,
        )

        result.ids = [row.id for row in claimed]
        result.tokens = [
            row.processing_token
            for row in claimed
            if row.processing_token is not None
        ]

        # Both workers must reach this point before either commits.
        barrier.wait(timeout=10)

        session.commit()

    except BaseException as exc:
        result.error = exc
        session.rollback()

        # Release the barrier if the other worker is waiting.
        try:
            barrier.abort()
        except Exception:
            pass

    finally:
        session.close()


def assert_persisted_state(expected_ids: list[int]) -> None:
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan).where(
                    Putusan.id.in_(expected_ids)
                )
            ).all()
        )

        assert len(rows) == TOTAL_ROWS

        for row in rows:
            assert row.status_scraping == ScrapingStatus.PROCESSING
            assert row.processing_worker_id in {
                "phase-10-worker-A",
                "phase-10-worker-B",
            }
            assert row.processing_token
            assert row.processing_started_at is not None

        tokens = [
            row.processing_token
            for row in rows
            if row.processing_token is not None
        ]

        assert len(tokens) == TOTAL_ROWS
        assert len(set(tokens)) == TOTAL_ROWS


def assert_no_remaining_pending(expected_ids: list[int]) -> None:
    with SessionLocal() as session:
        pending = list(
            session.scalars(
                select(Putusan).where(
                    Putusan.id.in_(expected_ids),
                    Putusan.status_scraping.in_(
                        [
                            ScrapingStatus.PENDING,
                            ScrapingStatus.FAILED_RETRY,
                        ]
                    ),
                )
            ).all()
        )

        assert pending == [], (
            "Masih ada Putusan eligible yang belum di-claim: "
            f"{[row.id for row in pending]}"
        )


def test_multi_worker_claim(expected_ids: list[int]) -> None:
    barrier = threading.Barrier(2)

    result_a = WorkerResult(
        worker_id="phase-10-worker-A",
        ids=[],
        tokens=[],
    )
    result_b = WorkerResult(
        worker_id="phase-10-worker-B",
        ids=[],
        tokens=[],
    )

    thread_a = threading.Thread(
        target=concurrent_claim_worker,
        kwargs={
            "worker_id": result_a.worker_id,
            "barrier": barrier,
            "result": result_a,
        },
        name="phase10-worker-A",
    )
    thread_b = threading.Thread(
        target=concurrent_claim_worker,
        kwargs={
            "worker_id": result_b.worker_id,
            "barrier": barrier,
            "result": result_b,
        },
        name="phase10-worker-B",
    )

    thread_a.start()
    thread_b.start()

    thread_a.join(timeout=20)
    thread_b.join(timeout=20)

    assert not thread_a.is_alive(), "Worker A timeout."
    assert not thread_b.is_alive(), "Worker B timeout."

    if result_a.error is not None:
        raise result_a.error

    if result_b.error is not None:
        raise result_b.error

    # --------------------------------------------------------
    # 10.1 Each concurrent worker receives exactly one batch.
    # --------------------------------------------------------
    assert len(result_a.ids) == BATCH_SIZE, (
        f"Worker A expected {BATCH_SIZE}, got {result_a.ids}"
    )
    assert len(result_b.ids) == BATCH_SIZE, (
        f"Worker B expected {BATCH_SIZE}, got {result_b.ids}"
    )
    print("10.1 Concurrent workers each receive 5 rows: PASS")

    # --------------------------------------------------------
    # 10.2 No row is claimed by both workers.
    # --------------------------------------------------------
    intersection = set(result_a.ids) & set(result_b.ids)
    assert intersection == set(), (
        f"Duplicate claim detected: {sorted(intersection)}"
    )
    print("10.2 Worker claim sets are disjoint: PASS")

    # --------------------------------------------------------
    # 10.3 Union contains every seeded row.
    # --------------------------------------------------------
    claimed_union = set(result_a.ids) | set(result_b.ids)
    assert claimed_union == set(expected_ids), (
        "Claim union does not equal seeded IDs.\n"
        f"Expected: {sorted(expected_ids)}\n"
        f"Got:      {sorted(claimed_union)}"
    )
    print("10.3 Claim union covers all eligible rows: PASS")

    # --------------------------------------------------------
    # 10.4 Processing tokens are unique across workers.
    # --------------------------------------------------------
    all_tokens = result_a.tokens + result_b.tokens
    assert len(all_tokens) == TOTAL_ROWS
    assert len(set(all_tokens)) == TOTAL_ROWS
    print("10.4 Processing tokens are globally unique: PASS")

    # --------------------------------------------------------
    # 10.5 Persisted ownership matches the two workers.
    # --------------------------------------------------------
    assert_persisted_state(expected_ids)
    print("10.5 Persisted PROCESSING ownership invariant: PASS")

    # --------------------------------------------------------
    # 10.6 No seeded row remains eligible after both claims.
    # --------------------------------------------------------
    assert_no_remaining_pending(expected_ids)
    print("10.6 No duplicate/remaining eligible row: PASS")


def cleanup(ids: list[int]) -> None:
    if not ids:
        return

    with SessionLocal.begin() as session:
        session.execute(
            delete(Putusan).where(
                Putusan.id.in_(ids)
            )
        )


def main() -> None:
    print("=" * 70)
    print("PHASE 10 - MULTI-WORKER CONCURRENCY")
    print("=" * 70)
    print(f"ENV_FILE: {os.getenv('ENV_FILE')}")
    print()

    ids: list[int] = []
    isolated_ids: list[int] = []

    try:
        ids, isolated_ids = seed_rows()
        print(
            f"Seeded {len(ids)} Putusan PENDING rows: "
            f"{ids}"
        )
        print(
            f"Temporarily isolated unrelated eligible rows: "
            f"{len(isolated_ids)}"
        )

        test_multi_worker_claim(ids)

        print()
        print("=" * 70)
        print("PHASE 10: PASS")
        print("=" * 70)

    finally:
        cleanup(ids)
        restore_isolated_rows(isolated_ids)
        print(
            f"Cleanup Phase 10 Putusan IDs: {ids}"
        )
        print(
            f"Restored unrelated eligible rows: "
            f"{len(isolated_ids)}"
        )


if __name__ == "__main__":
    main()
