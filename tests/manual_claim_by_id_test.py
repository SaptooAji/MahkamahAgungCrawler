from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import (
    putusan_lifecycle_service,
)


TEST_PREFIX = "https://example.com/claim-by-id/"


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
            judul=f"Claim by ID test {suffix}",
            status_scraping=ScrapingStatus.PENDING,
        )

        session.add(putusan)
        session.flush()

        return putusan.id


def test_claim_exact_id():
    target_id = create_pending("target")

    # Buat pending row lain dengan ID yang berbeda.
    other_id = create_pending("other")

    worker_id = "claim-by-id-worker"

    with SessionLocal.begin() as session:
        claimed = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=target_id,
            worker_id=worker_id,
        )

        assert claimed is not None
        assert claimed.id == target_id
        assert claimed.status_scraping == ScrapingStatus.PROCESSING

    # Row lain seharusnya tetap PENDING.
    with SessionLocal() as session:
        other = session.get(Putusan, other_id)

        assert other is not None
        assert other.status_scraping == ScrapingStatus.PENDING

    print("CLAIM EXACT ID: PASS")


def test_cannot_claim_twice():
    target_id = create_pending("single-claim")

    with SessionLocal.begin() as session:
        claimed = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=target_id,
            worker_id="worker-first",
        )

        assert claimed is not None
        assert claimed.id == target_id

    # Status sudah PROCESSING, jadi claim kedua harus gagal.
    with SessionLocal.begin() as session:
        claimed_again = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=target_id,
            worker_id="worker-second",
        )

        assert claimed_again is None

    print("CANNOT CLAIM TWICE: PASS")


def test_unknown_id():
    with SessionLocal.begin() as session:
        claimed = putusan_lifecycle_service.claim_by_id(
            session,
            putusan_id=-999999,
            worker_id="worker-unknown",
        )

        assert claimed is None

    print("UNKNOWN ID: PASS")


def main():
    print("Cleaning previous claim-by-ID test data...")
    cleanup()

    try:
        test_claim_exact_id()
        test_cannot_claim_twice()
        test_unknown_id()

        print()
        print("================================")
        print("ALL CLAIM BY ID TESTS: PASS")
        print("================================")

    finally:
        cleanup()


if __name__ == "__main__":
    main()