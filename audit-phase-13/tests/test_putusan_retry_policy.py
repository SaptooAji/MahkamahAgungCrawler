from datetime import datetime, timezone

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import (
    MAX_PUTUSAN_ATTEMPTS,
    mark_putusan_failed_retry,
)


def main():
    with SessionLocal() as session:
        transaction = session.begin()

        try:
            putusan = Putusan(
                tahun=9999,
                halaman=1,
                url_detail=(
                    "https://example.invalid/"
                    "test-retry-policy"
                ),
                status_scraping=ScrapingStatus.PROCESSING,
                retry_count=0,
                processing_started_at=datetime.now(timezone.utc),
                processing_worker_id="retry-policy-test",
                processing_token="test-token",
            )

            session.add(putusan)
            session.flush()

            putusan_id = putusan.id

            print(f"MAX_ATTEMPTS: {MAX_PUTUSAN_ATTEMPTS}")
            print(
                f"INITIAL: "
                f"status={putusan.status_scraping} "
                f"retry_count={putusan.retry_count}"
            )

            for attempt in range(1, 4):
                # Set kembali menjadi PROCESSING untuk simulasi
                # attempt berikutnya.
                if attempt > 1:
                    putusan.status_scraping = (
                        ScrapingStatus.PROCESSING
                    )
                    putusan.processing_started_at = (
                        datetime.now(timezone.utc)
                    )
                    putusan.processing_worker_id = (
                        "retry-policy-test"
                    )
                    putusan.processing_token = (
                        f"test-token-{attempt}"
                    )
                    session.flush()

                mark_putusan_failed_retry(
                    session,
                    putusan_id=putusan_id,
                    worker_id="retry-policy-test",
                    processing_token=(
                        "test-token"
                        if attempt == 1
                        else f"test-token-{attempt}"
                    ),
                    error_message=f"TEST_FAILURE_{attempt}",
                    retry_delay_seconds=300,
                )

                session.refresh(putusan)

                print(
                    f"ATTEMPT {attempt}: "
                    f"status={putusan.status_scraping} "
                    f"retry_count={putusan.retry_count} "
                    f"next_retry_at="
                    f"{putusan.next_retry_at}"
                )

            transaction.rollback()
            print("ROLLBACK: PASS")

        except Exception:
            transaction.rollback()
            raise


if __name__ == "__main__":
    main()