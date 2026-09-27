from __future__ import annotations

import os
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import upsert_discovered_putusan
from celery_app.tasks import process_putusan


UNPUBLISHED_URL = (
    "https://putusan3.mahkamahagung.go.id/direktori/putusan/"
    "zaf1b88a1e316718878d303933373537.html"
)

ERROR_505_URL = (
    "https://putusan3.mahkamahagung.go.id/direktori/putusan/"
    "zaf1a1ee4afbc5de9d42313530373035.html"
)


def load_environment() -> None:
    env_file = os.getenv("ENV_FILE", ".env")
    load_dotenv(env_file)


def find_by_url(url: str) -> Putusan | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Putusan).where(Putusan.url_detail == url)
        )


def snapshot(url: str) -> dict:
    with SessionLocal() as session:
        row = session.scalar(
            select(Putusan).where(Putusan.url_detail == url)
        )

        if row is None:
            return {"exists": False}

        return {
            "exists": True,
            "id": row.id,
            "tahun": row.tahun,
            "halaman": row.halaman,
            "status": row.status_scraping.value,
            "url_detail": row.url_detail,
            "url_pdf": row.url_pdf,
            "retry_count": row.retry_count,
            "last_error": row.last_error,
        }


def ensure_test_putusan(url: str, label: str) -> int:
    with SessionLocal() as session:
        row = session.scalar(
            select(Putusan).where(Putusan.url_detail == url)
        )

        if row is None:
            row = Putusan(
                tahun=2021,
                halaman=None,
                url_detail=url,
                url_pdf=None,
                judul=f"PHASE 6A TEST - {label}",
                status_scraping=ScrapingStatus.PENDING,
                retry_count=0,
                last_error=None,
                last_scraped_at=None,
                processing_started_at=None,
                processing_worker_id=None,
                processing_token=None,
                next_retry_at=None,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

        # Reset ONLY these two dedicated test rows so the E2E test is repeatable.
        row.status_scraping = ScrapingStatus.PENDING
        row.url_pdf = None
        row.retry_count = 0
        row.last_error = None
        row.last_scraped_at = None
        row.processing_started_at = None
        row.processing_worker_id = None
        row.processing_token = None
        row.next_retry_at = None
        session.commit()
        return row.id


def wait_for_terminal(ids: list[int], timeout: int = 120) -> dict[int, dict]:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        rows: dict[int, dict] = {}

        with SessionLocal() as session:
            db_rows = session.scalars(
                select(Putusan).where(Putusan.id.in_(ids))
            ).all()

            for row in db_rows:
                rows[row.id] = {
                    "status": row.status_scraping.value,
                    "url_pdf": row.url_pdf,
                    "retry_count": row.retry_count,
                    "last_error": row.last_error,
                }

        states = [
            (putusan_id, rows.get(putusan_id, {}).get("status"))
            for putusan_id in ids
        ]

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"{states}"
        )

        if rows and all(
            row["status"]
            in {
                ScrapingStatus.SUCCESS.value,
                ScrapingStatus.UNPUBLISHED.value,
                ScrapingStatus.FAILED_RETRY.value,
                ScrapingStatus.FAILED_PERMANENT.value,
            }
            for row in rows.values()
        ):
            return rows

        time.sleep(5)

    raise TimeoutError(
        f"Timeout menunggu Putusan IDs {ids}."
    )


def main() -> None:
    load_environment()

    print("=" * 72)
    print("PHASE 6A - MA 500 + UNPUBLISHED E2E")
    print("=" * 72)
    print(f"ENV_FILE: {os.getenv('ENV_FILE', '.env')}")
    print()

    unpublished_id = ensure_test_putusan(
        UNPUBLISHED_URL,
        "UNPUBLISHED",
    )

    error_505_id = ensure_test_putusan(
        ERROR_505_URL,
        "MA 500 / 505 UI",
    )

    ids = [unpublished_id, error_505_id]

    print(f"UNPUBLISHED test ID : {unpublished_id}")
    print(f"MA 500 test ID      : {error_505_id}")
    print()

    print("Dispatching exactly these two Putusan...")
    task_unpublished = process_putusan.delay(unpublished_id)
    task_error = process_putusan.delay(error_505_id)

    print(f"UNPUBLISHED task: {task_unpublished.id}")
    print(f"MA 500 task     : {task_error.id}")
    print()

    final = wait_for_terminal(ids)

    print()
    print("=" * 72)
    print("FINAL RESULT")
    print("=" * 72)

    for putusan_id in ids:
        row = final[putusan_id]

        print(f"id={putusan_id}")
        print(f"  status      : {row['status']}")
        print(f"  url_pdf     : {row['url_pdf']}")
        print(f"  retry_count : {row['retry_count']}")
        print(f"  last_error  : {row['last_error']}")
        print()

    # Core lifecycle assertions.
    unpublished = final[unpublished_id]
    error_505 = final[error_505_id]

    if unpublished["status"] != ScrapingStatus.UNPUBLISHED.value:
        raise AssertionError(
            "UNPUBLISHED E2E gagal: "
            f"expected UNPUBLISHED, got {unpublished['status']}"
        )

    if unpublished["url_pdf"] is not None:
        raise AssertionError(
            "UNPUBLISHED E2E gagal: url_pdf seharusnya NULL."
        )

    if error_505["status"] != ScrapingStatus.FAILED_RETRY.value:
        raise AssertionError(
            "MA 500 E2E gagal: "
            f"expected FAILED_RETRY, got {error_505['status']}"
        )

    if error_505["url_pdf"] is not None:
        raise AssertionError(
            "MA 500 E2E gagal: url_pdf seharusnya NULL."
        )

    if not error_505["last_error"]:
        raise AssertionError(
            "MA 500 E2E gagal: last_error kosong."
        )

    with SessionLocal() as session:
        stuck = session.scalars(
            select(Putusan).where(
                Putusan.id.in_(ids),
                Putusan.status_scraping == ScrapingStatus.PROCESSING,
            )
        ).all()

        if stuck:
            raise AssertionError(
                "Ada PROCESSING yang tertinggal: "
                f"{[row.id for row in stuck]}"
            )

    print("Assertions:")
    print("  UNPUBLISHED -> terminal UNPUBLISHED : PASS")
    print("  UNPUBLISHED -> url_pdf NULL         : PASS")
    print("  MA 500 -> FAILED_RETRY              : PASS")
    print("  MA 500 -> url_pdf NULL              : PASS")
    print("  MA 500 -> last_error terisi         : PASS")
    print("  Tidak ada PROCESSING tertinggal      : PASS")
    print()
    print("PHASE 6A MA 500 + UNPUBLISHED: PASS")


if __name__ == "__main__":
    main()
