from datetime import datetime, timedelta, timezone

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import putusan_lifecycle_service


TEST_PREFIX = "manual-processing-token-test"


def cleanup():
    with SessionLocal.begin() as session:
        session.query(Putusan).filter(
            Putusan.url_detail.like(f"{TEST_PREFIX}%")
        ).delete(synchronize_session=False)


def create_pending_putusan() -> int:
    with SessionLocal.begin() as session:
        putusan = Putusan(
            tahun=2026,
            halaman=1,
            url_detail=f"{TEST_PREFIX}/detail/1",
            judul="Manual Processing Token Test",
            status_scraping=ScrapingStatus.PENDING,
        )

        session.add(putusan)
        session.flush()

        return putusan.id


def test_token_rotation_and_stale_worker_protection():
    putusan_id = create_pending_putusan()

    # =========================================================
    # 1. Worker A claim
    # =========================================================
    worker_a = "manual-worker-A"

    with SessionLocal.begin() as session:
        putusan_a = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_a,
        )

        assert putusan_a is not None
        assert putusan_a.status_scraping == ScrapingStatus.PROCESSING
        assert putusan_a.processing_worker_id == worker_a
        assert putusan_a.processing_token is not None

        token_a = putusan_a.processing_token

    print("WORKER A CLAIM: PASS")
    print(f"  token A = {token_a}")

    # =========================================================
    # 2. Simulasikan worker A mati / lease expired
    # =========================================================
    with SessionLocal.begin() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None
        assert putusan.status_scraping == ScrapingStatus.PROCESSING

        putusan.processing_started_at = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        )

    # Recovery
    with SessionLocal.begin() as session:
        recovered = putusan_lifecycle_service.recover_stale(
            session,
            lease_timeout_seconds=1800,
        )

        assert recovered == 1

    print("STALE RECOVERY: PASS")

    # =========================================================
    # 3. Token lama harus sudah dihapus
    # =========================================================
    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None
        assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY
        assert putusan.processing_worker_id is None
        assert putusan.processing_token is None

    print("OLD TOKEN CLEARED: PASS")

    # =========================================================
    # 4. Worker B claim ulang
    # =========================================================
    worker_b = "manual-worker-B"

    with SessionLocal.begin() as session:
        putusan_b = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_b,
        )

        assert putusan_b is not None
        assert putusan_b.status_scraping == ScrapingStatus.PROCESSING
        assert putusan_b.processing_worker_id == worker_b
        assert putusan_b.processing_token is not None

        token_b = putusan_b.processing_token

    print("WORKER B CLAIM: PASS")
    print(f"  token B = {token_b}")

    # =========================================================
    # 5. Token harus berubah
    # =========================================================
    assert token_a != token_b

    print("TOKEN ROTATION: PASS")

    # =========================================================
    # 6. Worker A mencoba menyelesaikan job
    # =========================================================
    stale_worker_rejected = False

    try:
        with SessionLocal.begin() as session:
            putusan_lifecycle_service.mark_success(
                session,
                putusan_id=putusan_id,
                worker_id=worker_a,
                processing_token=token_a,
                url_pdf="https://example.com/stale-worker.pdf",
            )

    except RuntimeError:
        stale_worker_rejected = True

    assert stale_worker_rejected

    print("STALE WORKER REJECTED: PASS")

    # =========================================================
    # 7. Pastikan ownership Worker B tetap aman
    # =========================================================
    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None
        assert putusan.status_scraping == ScrapingStatus.PROCESSING
        assert putusan.processing_worker_id == worker_b
        assert putusan.processing_token == token_b
        assert putusan.url_pdf is None

    print("WORKER B OWNERSHIP PRESERVED: PASS")

    # =========================================================
    # 8. Worker B menyelesaikan job
    # =========================================================
    with SessionLocal.begin() as session:
        putusan_b = putusan_lifecycle_service.mark_success(
            session,
            putusan_id=putusan_id,
            worker_id=worker_b,
            processing_token=token_b,
            url_pdf="https://example.com/valid.pdf",
        )

        assert putusan_b.status_scraping == ScrapingStatus.SUCCESS
        assert putusan_b.url_pdf == "https://example.com/valid.pdf"

    print("NEW WORKER SUCCESS: PASS")

    # =========================================================
    # 9. Ownership harus dibersihkan
    # =========================================================
    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None
        assert putusan.status_scraping == ScrapingStatus.SUCCESS
        assert putusan.processing_worker_id is None
        assert putusan.processing_token is None
        assert putusan.processing_started_at is None

    print("OWNERSHIP CLEARED: PASS")


def main():
    print("Cleaning previous processing-token test data...")
    cleanup()

    try:
        test_token_rotation_and_stale_worker_protection()

        print()
        print("========================================")
        print("ALL PROCESSING TOKEN TESTS: PASS")
        print("========================================")

    finally:
        cleanup()


if __name__ == "__main__":
    main()