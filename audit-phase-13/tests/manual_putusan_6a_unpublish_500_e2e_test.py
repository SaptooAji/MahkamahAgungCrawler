from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from celery_app.tasks import process_putusan


# ============================================================
# ENVIRONMENT
# ============================================================

env_file = os.getenv("ENV_FILE", ".env.test")
load_dotenv(env_file)


# ============================================================
# TEST DATA
# ============================================================

UNPUBLISHED_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/putusan/"
    "zaf1b88a1e316718878d303933373537.html"
)

MA_500_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/putusan/"
    "zaf1a1ee4afbc5de9d42313530373035.html"
)

POLL_INTERVAL_SECONDS = 5
TIMEOUT_SECONDS = 180


# ============================================================
# HELPERS
# ============================================================

def get_or_create_putusan(
    session,
    *,
    url_detail: str,
    tahun: int = 2021,
) -> Putusan:

    stmt = select(Putusan).where(
        Putusan.url_detail == url_detail
    )

    putusan = session.scalar(stmt)

    if putusan is None:
        putusan = Putusan(
            tahun=tahun,
            halaman=None,
            url_detail=url_detail,
            status_scraping=ScrapingStatus.PENDING,
            retry_count=0,
            last_error=None,
            last_scraped_at=None,
            processing_started_at=None,
            processing_worker_id=None,
            processing_token=None,
            next_retry_at=None,
        )

        session.add(putusan)
        session.commit()
        session.refresh(putusan)

    return putusan


def reset_putusan(session, putusan: Putusan) -> None:
    """
    Reset state supaya test repeatable.
    """

    putusan.status_scraping = ScrapingStatus.PENDING
    putusan.url_pdf = None
    putusan.retry_count = 0
    putusan.last_error = None
    putusan.last_scraped_at = None

    putusan.processing_started_at = None
    putusan.processing_worker_id = None
    putusan.processing_token = None
    putusan.next_retry_at = None

    session.commit()


def get_statuses(ids: list[int]) -> list[tuple[int, str, str | None, int, str | None]]:
    with SessionLocal() as session:
        stmt = (
            select(
                Putusan.id,
                Putusan.status_scraping,
                Putusan.url_pdf,
                Putusan.retry_count,
                Putusan.last_error,
            )
            .where(Putusan.id.in_(ids))
            .order_by(Putusan.id)
        )

        rows = session.execute(stmt).all()

        result = []

        for row in rows:
            status = row.status_scraping

            if hasattr(status, "value"):
                status = status.value

            result.append(
                (
                    row.id,
                    status,
                    row.url_pdf,
                    row.retry_count,
                    row.last_error,
                )
            )

        return result


def is_terminal(status: str) -> bool:
    return status in {
        "SUCCESS",
        "UNPUBLISHED",
        "FAILED_RETRY",
        "FAILED_PERMANENT",
    }


def print_status(rows) -> None:
    for (
        putusan_id,
        status,
        url_pdf,
        retry_count,
        last_error,
    ) in rows:

        print(
            f"  id={putusan_id} "
            f"status={status} "
            f"retry={retry_count} "
            f"url_pdf={url_pdf!r} "
            f"error={last_error!r}"
        )


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    print("=" * 70)
    print("PHASE 6A - UNPUBLISHED + MA 500 FULL E2E")
    print("=" * 70)

    print(f"ENV_FILE: {env_file}")
    print()

    # --------------------------------------------------------
    # 1. Prepare DB rows
    # --------------------------------------------------------

    with SessionLocal() as session:

        unpublished = get_or_create_putusan(
            session,
            url_detail=UNPUBLISHED_URL,
        )

        ma_500 = get_or_create_putusan(
            session,
            url_detail=MA_500_URL,
        )

        reset_putusan(session, unpublished)
        reset_putusan(session, ma_500)

        unpublished_id = unpublished.id
        ma_500_id = ma_500.id

    print(f"UNPUBLISHED test ID : {unpublished_id}")
    print(f"MA 500 test ID      : {ma_500_id}")
    print()

    # --------------------------------------------------------
    # 2. Initial state
    # --------------------------------------------------------

    initial = get_statuses(
        [
            unpublished_id,
            ma_500_id,
        ]
    )

    print("Initial state:")
    print_status(initial)
    print()

    # --------------------------------------------------------
    # 3. Dispatch exactly two Celery tasks
    # --------------------------------------------------------

    print("Dispatching exactly these two Putusan...")

    unpublished_task = process_putusan.delay(
        unpublished_id
    )

    ma_500_task = process_putusan.delay(
        ma_500_id
    )

    print(
        f"UNPUBLISHED task: "
        f"{unpublished_task.id}"
    )

    print(
        f"MA 500 task     : "
        f"{ma_500_task.id}"
    )

    print()

    # --------------------------------------------------------
    # 4. Poll DB
    # --------------------------------------------------------

    started = time.monotonic()

    final_rows = None

    while True:

        rows = get_statuses(
            [
                unpublished_id,
                ma_500_id,
            ]
        )

        now = datetime.now().strftime("%H:%M:%S")

        compact = [
            (
                row[0],
                row[1],
            )
            for row in rows
        ]

        print(
            f"[{now}] {compact}"
        )

        if all(
            is_terminal(row[1])
            for row in rows
        ):
            final_rows = rows
            break

        if (
            time.monotonic() - started
            > TIMEOUT_SECONDS
        ):
            print()
            print(
                "TIMEOUT: Putusan masih belum "
                "mencapai terminal state."
            )

            print_status(rows)

            return 1

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    # --------------------------------------------------------
    # 5. Print final result
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    print_status(final_rows)

    print()

    by_id = {
        row[0]: row
        for row in final_rows
    }

    unpublished_row = by_id[
        unpublished_id
    ]

    ma_500_row = by_id[
        ma_500_id
    ]

    (
        _,
        unpublished_status,
        unpublished_pdf,
        unpublished_retry,
        unpublished_error,
    ) = unpublished_row

    (
        _,
        ma_500_status,
        ma_500_pdf,
        ma_500_retry,
        ma_500_error,
    ) = ma_500_row

    # --------------------------------------------------------
    # 6. Assertions: UNPUBLISHED
    # --------------------------------------------------------

    print("Checking UNPUBLISHED...")

    assert (
        unpublished_status
        == "UNPUBLISHED"
    ), (
        "UNPUBLISHED E2E gagal: "
        f"expected UNPUBLISHED, "
        f"got {unpublished_status}"
    )

    assert (
        unpublished_pdf is None
    ), (
        "UNPUBLISHED E2E gagal: "
        f"url_pdf seharusnya NULL, "
        f"got {unpublished_pdf!r}"
    )

    assert (
        unpublished_error is None
        or unpublished_error == ""
    ), (
        "UNPUBLISHED E2E gagal: "
        "terminal UNPUBLISHED tidak seharusnya "
        "meninggalkan last_error."
    )

    print("  PASS: status = UNPUBLISHED")
    print("  PASS: url_pdf = NULL")

    # --------------------------------------------------------
    # 7. Assertions: MA 500
    # --------------------------------------------------------

    print()
    print("Checking MA 500...")

    assert (
        ma_500_status
        == "FAILED_RETRY"
    ), (
        "MA 500 E2E gagal: "
        f"expected FAILED_RETRY, "
        f"got {ma_500_status}"
    )

    assert (
        ma_500_pdf is None
    ), (
        "MA 500 E2E gagal: "
        f"url_pdf seharusnya NULL, "
        f"got {ma_500_pdf!r}"
    )

    assert (
        ma_500_retry >= 1
    ), (
        "MA 500 E2E gagal: "
        f"retry_count seharusnya >= 1, "
        f"got {ma_500_retry}"
    )

    assert (
        ma_500_error
    ), (
        "MA 500 E2E gagal: "
        "last_error seharusnya terisi."
    )

    print("  PASS: status = FAILED_RETRY")
    print("  PASS: url_pdf = NULL")
    print(
        f"  PASS: retry_count = {ma_500_retry}"
    )
    print(
        f"  PASS: last_error = {ma_500_error!r}"
    )

    # --------------------------------------------------------
    # 8. No PROCESSING rows
    # --------------------------------------------------------

    print()
    print("Checking PROCESSING cleanup...")

    final_statuses = {
        row[1]
        for row in final_rows
    }

    assert (
        "PROCESSING"
        not in final_statuses
    ), (
        "E2E gagal: masih ada "
        "Putusan PROCESSING."
    )

    print(
        "  PASS: tidak ada PROCESSING "
        "yang tertinggal."
    )

    # --------------------------------------------------------
    # 9. Summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("PHASE 6A E2E: PASS")
    print("=" * 70)

    print()
    print(
        "Expected lifecycle:"
    )

    print(
        "  Unpublished:"
    )
    print(
        "    PENDING -> PROCESSING -> UNPUBLISHED"
    )

    print(
        "  MA 500:"
    )
    print(
        "    PENDING -> PROCESSING "
        "-> FAILED_RETRY"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())