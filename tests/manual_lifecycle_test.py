from datetime import datetime, timedelta, timezone

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import (
    claim_putusan_by_id,
    mark_putusan_success,
    mark_putusan_failed_retry,
    recover_stale_processing_putusan,
)


TEST_PREFIX = "https://example.com/lifecycle/"


def cleanup():
    with SessionLocal.begin() as session:
        session.query(Putusan).filter(
            Putusan.url_detail.like(f"{TEST_PREFIX}%")
        ).delete(
            synchronize_session=False
        )

def cleanup_test_row(suffix: str):
    with SessionLocal.begin() as session:
        session.query(Putusan).filter(
            Putusan.url_detail == f"{TEST_PREFIX}{suffix}"
        ).delete(synchronize_session=False)


def create_pending(suffix: str):
    with SessionLocal.begin() as session:
        putusan = Putusan(
            tahun=2025,
            halaman=1,
            url_detail=f"{TEST_PREFIX}{suffix}",
            judul=f"Lifecycle Test {suffix}",
            status_scraping=ScrapingStatus.PENDING,
        )
        session.add(putusan)
        session.flush()
        return putusan.id


def test_success():
    cleanup_test_row("success")

    putusan_id = create_pending("success")
    worker_id = "lifecycle-worker-01"

    with SessionLocal.begin() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
        )

        assert claimed is not None
        assert claimed.id == putusan_id
        assert claimed.status_scraping == ScrapingStatus.PROCESSING

        processing_token = claimed.processing_token

    with SessionLocal.begin() as session:
        putusan = mark_putusan_success(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            processing_token=processing_token,
            url_pdf="https://example.com/pdf/1.pdf",
        )

        assert putusan.status_scraping == ScrapingStatus.SUCCESS
        assert putusan.processing_worker_id is None
        assert putusan.processing_started_at is None
        assert putusan.processing_token is None

    print("SUCCESS lifecycle: PASS")

def test_failed_retry():
    cleanup_test_row("retry")

    putusan_id = create_pending("retry")
    worker_id = "lifecycle-worker-02"

    # ============================================================
    # 1. Claim pertama
    # ============================================================
    with SessionLocal.begin() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
        )

        assert claimed is not None
        assert claimed.id == putusan_id
        assert claimed.status_scraping == ScrapingStatus.PROCESSING

        processing_token = claimed.processing_token
        assert processing_token is not None

    # ============================================================
    # 2. Worker gagal -> FAILED_RETRY
    # ============================================================
    with SessionLocal.begin() as session:
        putusan = mark_putusan_failed_retry(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            processing_token=processing_token,
            error_message="Simulated server error",
            retry_delay_seconds=300,
        )

        assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY
        assert putusan.retry_count == 1
        assert putusan.next_retry_at is not None

        # Ownership harus sudah dilepas
        assert putusan.processing_worker_id is None
        assert putusan.processing_started_at is None
        assert putusan.processing_token is None

    # ============================================================
    # 3. Belum waktunya retry -> TIDAK BOLEH di-claim
    # ============================================================
    with SessionLocal.begin() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="lifecycle-worker-03",
        )

        assert claimed is None

    # ============================================================
    # 4. Simulasikan waktu retry sudah tiba
    # ============================================================
    with SessionLocal.begin() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None
        assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY

        putusan.next_retry_at = (
            datetime.now(timezone.utc)
            - timedelta(seconds=1)
        )

    # ============================================================
    # 5. Sekarang harus bisa di-claim kembali
    # ============================================================
    with SessionLocal.begin() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="lifecycle-worker-03",
        )

        assert claimed is not None
        assert claimed.id == putusan_id
        assert claimed.status_scraping == ScrapingStatus.PROCESSING

        # Token harus berubah / dibuat untuk worker baru
        new_processing_token = claimed.processing_token
        assert new_processing_token is not None
        assert new_processing_token != processing_token

    print("FAILED_RETRY lifecycle: PASS")

def test_stale_processing_recovery():
    cleanup_test_row("stale")

    putusan_id = create_pending("stale")
    worker_id = "crashed-worker"

    # ============================================================
    # 1. Claim putusan
    # ============================================================
    with SessionLocal.begin() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
        )

        assert claimed is not None
        assert claimed.id == putusan_id
        assert claimed.status_scraping == ScrapingStatus.PROCESSING

    # ============================================================
    # 2. Simulasikan worker crash selama > 30 menit
    # ============================================================
    with SessionLocal.begin() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None

        putusan.processing_started_at = (
            datetime.now(timezone.utc)
            - timedelta(minutes=31)
        )

    # ============================================================
    # 3. Recovery
    # ============================================================
    with SessionLocal.begin() as session:
        recovered = recover_stale_processing_putusan(
            session,
            lease_timeout_seconds=1800,
        )

        assert recovered == 1

    # ============================================================
    # 4. Pastikan menjadi FAILED_RETRY
    # ============================================================
    with SessionLocal() as session:
        putusan = session.get(Putusan, putusan_id)

        assert putusan is not None
        assert putusan.status_scraping == ScrapingStatus.FAILED_RETRY
        assert putusan.processing_worker_id is None
        assert putusan.processing_started_at is None
        assert putusan.processing_token is None
        assert putusan.next_retry_at is not None

    print("STALE PROCESSING recovery: PASS")
    
def main():
    print("Cleaning previous lifecycle test data...")
    cleanup()

    try:
        test_success()
        test_failed_retry()
        test_stale_processing_recovery()

        print()
        print("====================================")
        print("ALL LIFECYCLE TESTS: PASS")
        print("====================================")

    finally:
        cleanup()


if __name__ == "__main__":
    main()