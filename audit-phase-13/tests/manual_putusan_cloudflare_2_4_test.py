from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from celery_app.tasks import process_putusan


def load_environment() -> None:
    env_file = os.getenv("ENV_FILE", ".env")
    load_dotenv(env_file)


def read_rows(ids: list[int]) -> dict[int, dict]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(Putusan).where(Putusan.id.in_(ids))
        ).all()

        return {
            row.id: {
                "status": row.status_scraping.value,
                "url_detail": row.url_detail,
                "url_pdf": row.url_pdf,
                "retry_count": row.retry_count,
                "last_error": row.last_error,
            }
            for row in rows
        }


def main() -> None:
    load_environment()

    ids = [2, 4]

    print("=" * 70)
    print("PHASE 6A - CLOUDFLARE DIAGNOSTIC TEST")
    print("=" * 70)
    print(f"ENV_FILE : {os.getenv('ENV_FILE', '.env')}")
    print(f"Putusan IDs: {ids}")
    print()

    before = read_rows(ids)

    for putusan_id in ids:
        row = before.get(putusan_id)

        if row is None:
            raise RuntimeError(
                f"Putusan ID {putusan_id} tidak ditemukan."
            )

        print(
            f"id={putusan_id} "
            f"status={row['status']} "
            f"retry={row['retry_count']} "
            f"url={row['url_detail']}"
        )

    print()
    print("Dispatching ID 2 dan 4 secara eksplisit...")
    print()

    task_ids = {}

    for putusan_id in ids:
        result = process_putusan.delay(putusan_id)
        task_ids[putusan_id] = result.id
        print(
            f"id={putusan_id} task_id={result.id}"
        )

    print()
    print("Polling database...")
    print()

    deadline = time.monotonic() + 180

    while time.monotonic() < deadline:
        rows = read_rows(ids)

        states = [
            (
                putusan_id,
                rows.get(putusan_id, {}).get("status"),
                rows.get(putusan_id, {}).get("retry_count"),
            )
            for putusan_id in ids
        ]

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"{states}"
        )

        active = {
            ScrapingStatus.PENDING.value,
            ScrapingStatus.PROCESSING.value,
        }

        if not any(
            rows.get(putusan_id, {}).get("status") in active
            for putusan_id in ids
        ):
            break

        time.sleep(5)

    print()
    print("=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    final = read_rows(ids)

    for putusan_id in ids:
        row = final[putusan_id]

        print(f"id={putusan_id}")
        print(f"  status      : {row['status']}")
        print(f"  retry_count : {row['retry_count']}")
        print(f"  url_pdf     : {row['url_pdf']}")
        print(f"  last_error  : {row['last_error']}")
        print()

    stuck = [
        putusan_id
        for putusan_id in ids
        if final[putusan_id]["status"]
        == ScrapingStatus.PROCESSING.value
    ]

    if stuck:
        raise AssertionError(
            f"PROCESSING masih tertinggal: {stuck}"
        )

    print("Tidak ada PROCESSING yang tertinggal.")

    print()
    print("Interpretasi:")
    print(
        "- Jika Celery log menunjukkan "
        "'Cloudflare challenge detected', detector bekerja."
    )
    print(
        "- Jika timeout Cloudflare terjadi, DB seharusnya "
        "tetap menggunakan FAILED_RETRY melalui lifecycle lama."
    )
    print(
        "- Jika PDF ditemukan, status SUCCESS dan url_pdf terisi."
    )
    print()
    print("CLOUDFLARE DIAGNOSTIC TEST: PASS")


if __name__ == "__main__":
    main()
