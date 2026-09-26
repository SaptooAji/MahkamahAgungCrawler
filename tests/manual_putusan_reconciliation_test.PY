from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import (
    upsert_discovered_putusan,
)


YEAR = 2021


def make_url(label: str) -> str:
    return (
        "https://putusan3.mahkamahagung.go.id/"
        f"direktori/putusan/test-reconciliation-{label}-{uuid4()}.html"
    )


def get_putusan(url_detail: str) -> Putusan | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Putusan).where(
                Putusan.url_detail == url_detail
            )
        )


def cleanup(urls: list[str]) -> None:
    with SessionLocal.begin() as session:
        rows = session.scalars(
            select(Putusan).where(
                Putusan.url_detail.in_(urls)
            )
        ).all()

        for row in rows:
            session.delete(row)


def main():
    print("=" * 70)
    print("PUTUSAN RECONCILIATION TEST")
    print("=" * 70)

    urls: list[str] = []

    try:
        # ==========================================================
        # 1. PENDING -> UNPUBLISHED
        # ==========================================================

        url_pending = make_url("pending")
        urls.append(url_pending)

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_pending,
                judul="Test Pending",
                is_unpublish=False,
            )

            assert created is True
            assert putusan.status_scraping == ScrapingStatus.PENDING

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_pending,
                judul="Test Pending",
                is_unpublish=True,
            )

            assert created is False
            assert putusan.status_scraping == ScrapingStatus.UNPUBLISHED

        print("PENDING -> UNPUBLISHED: PASS")

        # ==========================================================
        # 2. FAILED_RETRY -> UNPUBLISHED
        # ==========================================================

        url_failed_retry = make_url("failed-retry")
        urls.append(url_failed_retry)

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_failed_retry,
                judul="Test Failed Retry",
                is_unpublish=False,
            )

            assert created is True

            putusan.status_scraping = ScrapingStatus.FAILED_RETRY
            putusan.last_error = "Temporary error"
            putusan.retry_count = 3

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_failed_retry,
                judul="Test Failed Retry",
                is_unpublish=True,
            )

            assert created is False
            assert putusan.status_scraping == ScrapingStatus.UNPUBLISHED
            assert putusan.last_error is None
            assert putusan.next_retry_at is None

        print("FAILED_RETRY -> UNPUBLISHED: PASS")

        # ==========================================================
        # 3. UNPUBLISHED -> PENDING
        # ==========================================================

        url_republish = make_url("republish")
        urls.append(url_republish)

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_republish,
                judul="Test Republish",
                is_unpublish=True,
            )

            assert created is True
            assert putusan.status_scraping == ScrapingStatus.UNPUBLISHED

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_republish,
                judul="Test Republish",
                is_unpublish=False,
            )

            assert created is False
            assert putusan.status_scraping == ScrapingStatus.PENDING
            assert putusan.last_error is None
            assert putusan.next_retry_at is None

        print("UNPUBLISHED -> PENDING: PASS")

        # ==========================================================
        # 4. PROCESSING HARUS TETAP PROCESSING
        # ==========================================================

        url_processing = make_url("processing")
        urls.append(url_processing)

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_processing,
                judul="Test Processing",
                is_unpublish=False,
            )

            assert created is True

            putusan.status_scraping = ScrapingStatus.PROCESSING
            putusan.processing_started_at = datetime.now(timezone.utc)
            putusan.processing_worker_id = "test-worker"
            putusan.processing_token = str(uuid4())

            original_token = putusan.processing_token
            original_worker = putusan.processing_worker_id

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_processing,
                judul="Test Processing",
                is_unpublish=True,
            )

            assert created is False
            assert putusan.status_scraping == ScrapingStatus.PROCESSING
            assert putusan.processing_token == original_token
            assert putusan.processing_worker_id == original_worker

        print("PROCESSING + UNPUBLISH -> tetap PROCESSING: PASS")

        # ==========================================================
        # 5. SUCCESS HARUS TETAP SUCCESS
        #    DAN PDF TIDAK BOLEH HILANG
        # ==========================================================

        url_success = make_url("success")
        urls.append(url_success)

        pdf_url = (
            "https://putusan3.mahkamahagung.go.id/"
            "direktori/download_file/test.pdf"
        )

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_success,
                judul="Test Success",
                is_unpublish=False,
            )

            assert created is True

            putusan.status_scraping = ScrapingStatus.SUCCESS
            putusan.url_pdf = pdf_url
            putusan.last_scraped_at = datetime.now(timezone.utc)

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_success,
                judul="Test Success",
                is_unpublish=True,
            )

            assert created is False
            assert putusan.status_scraping == ScrapingStatus.SUCCESS
            assert putusan.url_pdf == pdf_url

        print("SUCCESS + UNPUBLISH -> tetap SUCCESS + PDF: PASS")

        # ==========================================================
        # 6. IDEMPOTENCY
        # ==========================================================

        url_idempotency = make_url("idempotency")
        urls.append(url_idempotency)

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_idempotency,
                judul="Test Idempotency",
                is_unpublish=False,
            )

            assert created is True

            first_id = putusan.id

        with SessionLocal.begin() as session:
            putusan, created = upsert_discovered_putusan(
                session,
                tahun=YEAR,
                halaman=1,
                url_detail=url_idempotency,
                judul="Test Idempotency",
                is_unpublish=False,
            )

            assert created is False
            assert putusan.id == first_id

        with SessionLocal() as session:
            rows = session.scalars(
                select(Putusan).where(
                    Putusan.url_detail == url_idempotency
                )
            ).all()

            assert len(rows) == 1

        print("DISCOVERY IDEMPOTENCY: PASS")

        print()
        print("=" * 70)
        print("PUTUSAN RECONCILIATION TEST: PASS")
        print("=" * 70)

    finally:
        cleanup(urls)
        print()
        print(f"TEST ROWS DELETED: {len(urls)}")


if __name__ == "__main__":
    main()