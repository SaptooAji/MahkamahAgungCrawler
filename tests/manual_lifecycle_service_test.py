from datetime import datetime, timezone

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import (
    putusan_lifecycle_service,
)


TEST_PREFIX = "https://example.com/lifecycle-service/"


def cleanup():
    with SessionLocal.begin() as session:
        session.query(Putusan).filter(
            Putusan.url_detail.like(f"{TEST_PREFIX}%")
        ).delete(synchronize_session=False)


def create_pending(suffix: str) -> int:
    with SessionLocal.begin() as session:
        putusan = Putusan(
            tahun=2025,
            halaman=1,
            url_detail=f"{TEST_PREFIX}{suffix}",
            judul=f"Lifecycle Service Test {suffix}",
            status_scraping=ScrapingStatus.PENDING,
        )

        session.add(putusan)
        session.flush()

        return putusan.id


def test_claim_and_success():
    putusan_id = create_pending("success")

    worker_id = "service-test-worker-success"

    with SessionLocal.begin() as session:
        claimed = putusan_lifecycle_service.claim(
            session,
            worker_id=worker_id,
            batch_size=1,
        )

        assert len(claimed) == 1
        assert claimed[0].id == putusan_id
        assert claimed[0].status_scraping == ScrapingStatus.PROCESSING

    with SessionLocal.begin() as session:
        putusan = putusan_lifecycle_service.mark_success(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            url_pdf="https://example.com/pdf/success.pdf",
        )

        assert putusan.status_scraping == ScrapingStatus.SUCCESS
        assert putusan.url_pdf == (
            "https://example.com/pdf/success.pdf"
        )
        assert putusan.processing_worker_id is None
        assert putusan.processing_started_at is None

    print("SERVICE SUCCESS: PASS")


def test_claim_and_retry():
    putusan_id = create_pending("retry")

    worker_id = "service-test-worker-retry"

    with SessionLocal.begin() as session:
        claimed = putusan_lifecycle_service.claim(
            session,
            worker_id=worker_id,
            batch_size=1,
        )

        assert len(claimed) == 1
        assert claimed[0].id == putusan_id

    with SessionLocal.begin() as session:
        putusan = putusan_lifecycle_service.mark_failed_retry(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            error_message="Simulated MA server error",
            retry_delay_seconds=300,
        )

        assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY
        assert putusan.retry_count == 1
        assert putusan.next_retry_at is not None
        assert putusan.last_error == "Simulated MA server error"

    print("SERVICE RETRY: PASS")


def test_unpublished():
    putusan_id = create_pending("unpublished")

    worker_id = "service-test-worker-unpublished"

    with SessionLocal.begin() as session:
        claimed = putusan_lifecycle_service.claim(
            session,
            worker_id=worker_id,
            batch_size=1,
        )

        assert len(claimed) == 1
        assert claimed[0].id == putusan_id

    with SessionLocal.begin() as session:
        putusan = putusan_lifecycle_service.mark_unpublished(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            error_message="Putusan tidak dipublikasikan",
        )

        assert putusan.status_scraping == ScrapingStatus.UNPUBLISHED
        assert putusan.last_error == "Putusan tidak dipublikasikan"
        assert putusan.processing_worker_id is None
        assert putusan.processing_started_at is None

    print("SERVICE UNPUBLISHED: PASS")


def test_stale_recovery():
    putusan_id = create_pending("stale")

    worker_id = "service-test-worker-stale"

    with SessionLocal.begin() as session:
        claimed = putusan_lifecycle_service.claim(
            session,
            worker_id=worker_id,
            batch_size=1,
        )

        assert len(claimed) == 1
        assert claimed[0].id == putusan_id

    with SessionLocal.begin() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None

        putusan.processing_started_at = (
            datetime.now(timezone.utc)
        )

    with SessionLocal.begin() as session:
        # Karena processing_started_at baru saja dibuat,
        # kita gunakan timeout 0 agar dianggap stale.
        recovered = putusan_lifecycle_service.recover_stale(
            session,
            lease_timeout_seconds=0,
        )

        assert recovered == 1

    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None
        assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY
        assert putusan.processing_worker_id is None
        assert putusan.processing_started_at is None
        assert putusan.next_retry_at is not None

    print("SERVICE STALE RECOVERY: PASS")


def main():
    print("Cleaning previous lifecycle service test data...")
    cleanup()

    try:
        test_claim_and_success()
        test_claim_and_retry()
        test_unpublished()
        test_stale_recovery()

        print()
        print("========================================")
        print("ALL LIFECYCLE SERVICE TESTS: PASS")
        print("========================================")

    finally:
        cleanup()


if __name__ == "__main__":
    main()