from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_dispatcher import get_pending_putusan_ids


env_file = os.getenv("ENV_FILE", ".env.test")
load_dotenv(env_file)


BATCH_SIZE = 5


def create_putusan(
    session,
    *,
    url_detail: str,
    status: ScrapingStatus,
    next_retry_at=None,
) -> Putusan:

    putusan = Putusan(
        tahun=2099,
        halaman=None,
        url_detail=url_detail,
        url_pdf=None,
        status_scraping=status,
        retry_count=0,
        last_error=None,
        last_scraped_at=None,
        processing_started_at=None,
        processing_worker_id=None,
        processing_token=None,
        next_retry_at=next_retry_at,
    )

    session.add(putusan)
    session.flush()

    return putusan


def main() -> int:

    print("=" * 70)
    print("PHASE 6B - PUTUSAN DISPATCHER")
    print("=" * 70)

    print(f"ENV_FILE: {env_file}")
    print()

    now = datetime.now(timezone.utc)

    with SessionLocal() as session:

        # ----------------------------------------------------
        # Clean test rows from previous run
        # ----------------------------------------------------

        test_prefix = (
            "https://test.local/"
            "phase6b/"
        )

        existing = session.scalars(
            select(Putusan).where(
                Putusan.url_detail.like(
                    f"{test_prefix}%"
                )
            )
        ).all()

        for putusan in existing:
            session.delete(putusan)

        session.commit()

        # ----------------------------------------------------
        # Seed deterministic dataset
        # ----------------------------------------------------

        p1 = create_putusan(
            session,
            url_detail=test_prefix + "01",
            status=ScrapingStatus.PENDING,
        )

        p2 = create_putusan(
            session,
            url_detail=test_prefix + "02",
            status=ScrapingStatus.PENDING,
        )

        p3 = create_putusan(
            session,
            url_detail=test_prefix + "03",
            status=ScrapingStatus.SUCCESS,
        )

        p4 = create_putusan(
            session,
            url_detail=test_prefix + "04",
            status=ScrapingStatus.UNPUBLISHED,
        )

        p5 = create_putusan(
            session,
            url_detail=test_prefix + "05",
            status=ScrapingStatus.PROCESSING,
        )

        p6 = create_putusan(
            session,
            url_detail=test_prefix + "06",
            status=ScrapingStatus.FAILED_RETRY,
        )

        p7 = create_putusan(
            session,
            url_detail=test_prefix + "07",
            status=ScrapingStatus.FAILED_RETRY,
            next_retry_at=now - timedelta(minutes=5),
        )

        p8 = create_putusan(
            session,
            url_detail=test_prefix + "08",
            status=ScrapingStatus.FAILED_RETRY,
            next_retry_at=now + timedelta(hours=1),
        )

        p9 = create_putusan(
            session,
            url_detail=test_prefix + "09",
            status=ScrapingStatus.PENDING,
        )

        p10 = create_putusan(
            session,
            url_detail=test_prefix + "10",
            status=ScrapingStatus.PENDING,
        )

        p11 = create_putusan(
            session,
            url_detail=test_prefix + "11",
            status=ScrapingStatus.PENDING,
        )

        p12 = create_putusan(
            session,
            url_detail=test_prefix + "12",
            status=ScrapingStatus.PENDING,
        )

        session.commit()

        expected_ids = [
            p1.id,
            p2.id,
            p6.id,
            p7.id,
            p9.id,
        ]

        all_ids = [
            p1.id,
            p2.id,
            p3.id,
            p4.id,
            p5.id,
            p6.id,
            p7.id,
            p8.id,
            p9.id,
            p10.id,
            p11.id,
            p12.id,
        ]

        print("Seeded IDs:")
        print(all_ids)
        print()

        # ----------------------------------------------------
        # Snapshot before dispatcher
        # ----------------------------------------------------

        before = {
            row.id: (
                row.status_scraping,
                row.processing_worker_id,
                row.processing_token,
                row.processing_started_at,
                row.next_retry_at,
            )
            for row in session.scalars(
                select(Putusan).where(
                    Putusan.id.in_(all_ids)
                )
            ).all()
        }

    # --------------------------------------------------------
    # Execute dispatcher
    # --------------------------------------------------------

    actual_ids = get_pending_putusan_ids(
        batch_size=BATCH_SIZE
    )

    print("Dispatcher returned:")
    print(actual_ids)
    print()

    print("Expected:")
    print(expected_ids)
    print()

    # --------------------------------------------------------
    # Assertion: exact candidate set
    # --------------------------------------------------------

    assert actual_ids == expected_ids, (
        "Dispatcher candidate selection salah.\n"
        f"expected={expected_ids}\n"
        f"actual={actual_ids}"
    )

    print(
        "PASS: hanya candidate yang eligible "
        "yang dipilih."
    )

    # --------------------------------------------------------
    # Assertion: batch size
    # --------------------------------------------------------

    assert len(actual_ids) <= BATCH_SIZE

    print(
        "PASS: batch size <= 5."
    )

    # --------------------------------------------------------
    # Verify dispatcher did NOT claim anything
    # --------------------------------------------------------

    with SessionLocal() as session:

        after_rows = session.scalars(
            select(Putusan).where(
                Putusan.id.in_(all_ids)
            )
        ).all()

        after = {
            row.id: (
                row.status_scraping,
                row.processing_worker_id,
                row.processing_token,
                row.processing_started_at,
                row.next_retry_at,
            )
            for row in after_rows
        }

    assert before == after, (
        "Dispatcher mengubah state database. "
        "Dispatcher seharusnya hanya membaca "
        "candidate IDs."
    )

    print(
        "PASS: dispatcher tidak melakukan claim "
        "atau mengubah state."
    )

    # --------------------------------------------------------
    # Explicit protected-state assertions
    # --------------------------------------------------------

    assert p3.id not in actual_ids
    assert p4.id not in actual_ids
    assert p5.id not in actual_ids
    assert p8.id not in actual_ids

    print(
        "PASS: SUCCESS tidak di-dispatch."
    )

    print(
        "PASS: UNPUBLISHED tidak di-dispatch."
    )

    print(
        "PASS: PROCESSING tidak di-dispatch."
    )

    print(
        "PASS: FAILED_RETRY future tidak di-dispatch."
    )

    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    with SessionLocal() as session:

        rows = session.scalars(
            select(Putusan).where(
                Putusan.url_detail.like(
                    f"{test_prefix}%"
                )
            )
        ).all()

        for row in rows:
            session.delete(row)

        session.commit()

    print()
    print("=" * 70)
    print("PHASE 6B.1: PASS")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())