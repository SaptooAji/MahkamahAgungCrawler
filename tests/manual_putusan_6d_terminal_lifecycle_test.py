"""
Manual validation for Phase 6D - Putusan SUCCESS / UNPUBLISHED lifecycle.

Run from project root:
    ENV_FILE=.env.test python -m tests.manual_putusan_6d_terminal_lifecycle_test
"""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import delete

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import putusan_lifecycle_service


def load_environment():
    env_file = os.getenv("ENV_FILE", ".env")
    load_dotenv(env_file)
    return env_file


def seed_putusan(session, *, suffix: str) -> Putusan:
    putusan = Putusan(
        tahun=2099,
        halaman=1,
        url_detail=f"https://example.test/phase-6d/{suffix}",
        url_pdf=None,
        judul=f"PHASE 6D TEST {suffix}",
        status_scraping=ScrapingStatus.PENDING,
        retry_count=0,
    )
    session.add(putusan)
    session.flush()
    return putusan


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
    print("PHASE 6D - PUTUSAN TERMINAL LIFECYCLE")
    print("=" * 50)
    print(f"ENV_FILE: {env_file}")

    test_ids = []

    with SessionLocal() as session:
        # ------------------------------------------------------------
        # 6D.1 SUCCESS terminal transition
        # ------------------------------------------------------------
        success_row = seed_putusan(session, suffix="SUCCESS")
        session.commit()
        test_ids.append(success_row.id)

        claimed = claim_one(session, success_row.id, "phase-6d-success-worker")
        success_token = claimed.processing_token
        session.commit()

        with SessionLocal() as success_session:
            result = putusan_lifecycle_service.mark_success(
                success_session,
                putusan_id=success_row.id,
                worker_id="phase-6d-success-worker",
                processing_token=success_token,
                url_pdf="https://example.test/pdf/phase-6d-success.pdf",
            )
            success_session.commit()

            if result.status_scraping != ScrapingStatus.SUCCESS:
                raise AssertionError("SUCCESS transition failed")
            if result.url_pdf != "https://example.test/pdf/phase-6d-success.pdf":
                raise AssertionError("SUCCESS did not persist url_pdf")
            if result.last_scraped_at is None:
                raise AssertionError("SUCCESS did not set last_scraped_at")
            if result.processing_started_at is not None:
                raise AssertionError("SUCCESS left processing_started_at populated")
            if result.processing_worker_id is not None:
                raise AssertionError("SUCCESS left processing_worker_id populated")
            if result.processing_token is not None:
                raise AssertionError("SUCCESS left processing_token populated")
            if result.next_retry_at is not None:
                raise AssertionError("SUCCESS left next_retry_at populated")
            if result.last_error is not None:
                raise AssertionError("SUCCESS left last_error populated")

        print("6D.1 SUCCESS terminal transition: PASS")

        # ------------------------------------------------------------
        # 6D.2 UNPUBLISHED terminal transition
        # ------------------------------------------------------------
        unpublished_row = seed_putusan(session, suffix="UNPUBLISHED")
        session.commit()
        test_ids.append(unpublished_row.id)

        claimed = claim_one(session, unpublished_row.id, "phase-6d-unpublished-worker")
        unpublished_token = claimed.processing_token
        session.commit()

        with SessionLocal() as unpublished_session:
            result = putusan_lifecycle_service.mark_unpublished(
                unpublished_session,
                putusan_id=unpublished_row.id,
                worker_id="phase-6d-unpublished-worker",
                processing_token=unpublished_token,
                error_message=None,
            )
            unpublished_session.commit()

            if result.status_scraping != ScrapingStatus.UNPUBLISHED:
                raise AssertionError("UNPUBLISHED transition failed")
            if result.url_pdf is not None:
                raise AssertionError("UNPUBLISHED must not contain url_pdf")
            if result.processing_started_at is not None:
                raise AssertionError(
                    "UNPUBLISHED left processing_started_at populated"
                )
            if result.processing_worker_id is not None:
                raise AssertionError(
                    "UNPUBLISHED left processing_worker_id populated"
                )
            if result.processing_token is not None:
                raise AssertionError(
                    "UNPUBLISHED left processing_token populated"
                )
            if result.next_retry_at is not None:
                raise AssertionError("UNPUBLISHED left next_retry_at populated")

        print("6D.2 UNPUBLISHED terminal transition: PASS")

        # ------------------------------------------------------------
        # 6D.3 Terminal states are not claimable again
        # ------------------------------------------------------------
        with SessionLocal() as terminal_session:
            success_claim = putusan_lifecycle_service.claim_by_id(
                terminal_session,
                putusan_id=success_row.id,
                worker_id="phase-6d-second-worker",
            )
            unpublished_claim = putusan_lifecycle_service.claim_by_id(
                terminal_session,
                putusan_id=unpublished_row.id,
                worker_id="phase-6d-second-worker",
            )

            if success_claim is not None:
                raise AssertionError("SUCCESS row became claimable again")
            if unpublished_claim is not None:
                raise AssertionError("UNPUBLISHED row became claimable again")

        print("6D.3 Terminal states remain terminal: PASS")

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
    print("PHASE 6D: PASS")
    print("=" * 50)
    print(f"Cleanup test rows: {test_ids}")


if __name__ == "__main__":
    main()
