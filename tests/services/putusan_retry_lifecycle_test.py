"""
Manual validation for Phase 6E - Putusan retry lifecycle.

Run from project root:
    ENV_FILE=.env.test python -m tests.services.putusan_retry_lifecycle_test
"""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import delete, update

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import putusan_lifecycle_service


def load_environment():
    env_file = os.getenv("ENV_FILE", ".env")
    load_dotenv(env_file)
    return env_file


def seed_putusan(session, *, suffix: str) -> Putusan:
    
    from sqlalchemy import delete
    test_url = f"https://example.test/phase-6e/{suffix}"

    session.execute(
        delete(Putusan).where(Putusan.url_detail == test_url)
    )

    row = Putusan(
        tahun=2099,
        halaman=1,
        url_detail=test_url,
        judul=f"PHASE 6E TEST {suffix}",
        status_scraping=ScrapingStatus.PENDING,
        url_pdf=None,
        retry_count=0,
    )


    session.add(row)
    session.flush()
    return row


def claim_one(session, putusan_id: int, worker_id: str) -> Putusan:
    claimed = putusan_lifecycle_service.claim_by_id(
        session,
        putusan_id=putusan_id,
        worker_id=worker_id,
    )
    if claimed is None:
        raise AssertionError(f"Failed to claim Putusan {putusan_id}")
    if claimed.status_scraping != ScrapingStatus.PROCESSING:
        raise AssertionError("Claim did not produce PROCESSING state")
    if not claimed.processing_token:
        raise AssertionError("Claim did not generate processing_token")
    return claimed


def main():
    env_file = load_environment()

    print("=" * 50)
    print("PHASE 6E - PUTUSAN RETRY LIFECYCLE")
    print("=" * 50)
    print(f"ENV_FILE: {env_file}")

    test_ids = []

    # ------------------------------------------------------------
    # 6E.1 - 6E.5 FAILED_RETRY transition
    # ------------------------------------------------------------
    with SessionLocal() as session:
        row = seed_putusan(session, suffix="FAILED-RETRY")
        session.commit()
        test_ids.append(row.id)

        claimed = claim_one(session, row.id, "phase-6e-worker")
        token = claimed.processing_token
        session.commit()

        with SessionLocal() as retry_session:
            before = datetime.now(timezone.utc)

            result = putusan_lifecycle_service.mark_failed_retry(
                retry_session,
                putusan_id=row.id,
                worker_id="phase-6e-worker",
                processing_token=token,
                error_message="PHASE 6E simulated MA 500 error",
                retry_delay_seconds=300,
            )
            retry_session.commit()

            if result.status_scraping != ScrapingStatus.FAILED_RETRY:
                raise AssertionError("Status did not become FAILED_RETRY")

            if result.retry_count != 1:
                raise AssertionError(
                    f"Expected retry_count=1, got {result.retry_count}"
                )

            if result.last_error != "PHASE 6E simulated MA 500 error":
                raise AssertionError("last_error was not persisted")

            if result.next_retry_at is None:
                raise AssertionError("next_retry_at was not populated")

            delta = (
                    result.next_retry_at - before
                ).total_seconds()

            print(f"before: {before.isoformat()}")
            print(f"next_retry_at: {result.next_retry_at.isoformat()}")
            print(f"delta: {delta:.3f}s")

            if not 295 <= delta <= 305:
                raise AssertionError(
                    f"Expected retry delay around 300s, got {delta:.3f}s"
                )

            if result.processing_started_at is not None:
                raise AssertionError(
                    "FAILED_RETRY left processing_started_at populated"
                )

            if result.processing_worker_id is not None:
                raise AssertionError(
                    "FAILED_RETRY left processing_worker_id populated"
                )

            if result.processing_token is not None:
                raise AssertionError(
                    "FAILED_RETRY left processing_token populated"
                )

        print("6E.1 FAILED_RETRY transition: PASS")
        print("6E.2 retry_count increment: PASS")
        print("6E.3 last_error persistence: PASS")
        print("6E.4 next_retry_at scheduling: PASS")
        print("6E.5 processing ownership cleanup: PASS")

    # ------------------------------------------------------------
    # 6E.6 - 6E.7 retry schedule enforcement
    #
    # First verify a future retry is blocked.
    # Then move next_retry_at into the past and verify it becomes
    # claimable again.
    # ------------------------------------------------------------
    with SessionLocal() as session:
        future_claim = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=test_ids[0],
            worker_id="phase-6e-second-worker",
        )

        if future_claim is not None:
            raise AssertionError(
                "FAILED_RETRY with future next_retry_at was claimable"
            )

        print("6E.7 future next_retry_at blocks claim: PASS")

        session.execute(
            update(Putusan)
            .where(Putusan.id == test_ids[0])
            .values(
                next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
        session.commit()

    with SessionLocal() as session:
        retry_claim = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=test_ids[0],
            worker_id="phase-6e-retry-worker",
        )

        if retry_claim is None:
            raise AssertionError(
                "FAILED_RETRY did not become claimable after next_retry_at"
            )

        if retry_claim.status_scraping != ScrapingStatus.PROCESSING:
            raise AssertionError(
                "Retry claim did not produce PROCESSING state"
            )

        if retry_claim.processing_worker_id != "phase-6e-retry-worker":
            raise AssertionError("Retry claim assigned wrong worker")

        if not retry_claim.processing_token:
            raise AssertionError("Retry claim did not generate new token")

        session.commit()

    print("6E.6 retry becomes claimable after schedule: PASS")

    # ------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------
    with SessionLocal() as cleanup_session:
        if test_ids:
            cleanup_session.execute(
                delete(Putusan).where(Putusan.id.in_(test_ids))
            )
            cleanup_session.commit()

    print("=" * 50)
    print("PHASE 6E: PASS")
    print("=" * 50)
    print(f"Cleanup test rows: {test_ids}")


if __name__ == "__main__":
    main()
