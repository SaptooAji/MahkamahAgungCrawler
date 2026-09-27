from __future__ import annotations
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import os

from sqlalchemy import delete, select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from services.putusan_lifecycle_service import (
    claim_putusan_by_id,
    putusan_lifecycle_service,
)
from services.putusan_dispatcher import (
    get_pending_putusan_ids,
)
from celery_app import tasks


TEST_PREFIX = "https://example.test/phase-6f/"


# ============================================================
# 6F.1 - SEED 5 PUTUSAN
# ============================================================

def seed_batch() -> list[int]:
    """
    Membuat tepat 5 Putusan test dalam keadaan PENDING.

    Test dapat dijalankan berulang kali karena URL test
    dibersihkan terlebih dahulu.
    """

    with SessionLocal.begin() as session:
        test_urls = [
            f"{TEST_PREFIX}{i}"
            for i in range(1, 6)
        ]

        session.execute(
            delete(Putusan).where(
                Putusan.url_detail.in_(test_urls)
            )
        )

        rows = []

        for i, test_url in enumerate(
            test_urls,
            start=1,
        ):
            row = Putusan(
                tahun=2099,
                halaman=i,
                url_detail=test_url,
                judul=f"PHASE 6F TEST {i}",
                status_scraping=ScrapingStatus.PENDING,
                url_pdf=None,
                retry_count=0,
            )

            session.add(row)
            rows.append(row)

        session.flush()

        ids = [row.id for row in rows]

        return ids


# ============================================================
# 6F.2 - DISPATCHER
# ============================================================

def test_dispatcher(expected_ids):
    calls = []
    fake_task_ids = [
        f"phase-6f-task-{putusan_id}"
        for putusan_id in expected_ids
    ]
    task_counter = iter(fake_task_ids)

    class FakeAsyncResult:
        def __init__(self, task_id):
            self.id = task_id

    def fake_delay(putusan_id):
        calls.append(putusan_id)
        return FakeAsyncResult(next(task_counter))

    with patch.object(
        tasks,
        "get_pending_putusan_ids",
        return_value=list(expected_ids),
    ) as mocked_selector, patch.object(
        tasks.process_putusan,
        "delay",
        side_effect=fake_delay,
    ) as mocked_delay:

        result = tasks.dispatch_pending_putusan.run(
            batch_size=5
        )

    # --------------------------------------------------------
    # 6F.2.1
    # Dispatcher meminta batch_size=5 ke selector.
    # --------------------------------------------------------
    mocked_selector.assert_called_once_with(
        batch_size=5
    )

    # --------------------------------------------------------
    # 6F.2.2
    # Semua seeded ID di-enqueue tepat satu kali.
    # --------------------------------------------------------
    assert calls == expected_ids, (
        "Urutan enqueue tidak sesuai.\n"
        f"Expected: {expected_ids}\n"
        f"Got:      {calls}"
    )

    assert mocked_delay.call_count == 5

    # --------------------------------------------------------
    # 6F.2.3
    # Metadata dispatcher konsisten.
    # --------------------------------------------------------
    assert result["dispatched"] == 5
    assert result["putusan_ids"] == expected_ids
    assert result["task_ids"] == fake_task_ids

    # --------------------------------------------------------
    # 6F.2.4
    # Dispatcher tidak melakukan claim.
    # --------------------------------------------------------
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan).where(
                    Putusan.id.in_(expected_ids)
                )
            ).all()
        )

        by_id = {
            row.id: row
            for row in rows
        }

        assert len(by_id) == 5

        for putusan_id in expected_ids:
            row = by_id[putusan_id]

            assert row.status_scraping == ScrapingStatus.PENDING, (
                f"Dispatcher melakukan mutation pada "
                f"Putusan {putusan_id}"
            )

            assert row.processing_worker_id is None
            assert row.processing_token is None
            assert row.processing_started_at is None

    print("6F.2 Dispatcher enqueue contract: PASS")

    return list(expected_ids)
# ============================================================
# 6F.3 - CLAIM BATCH
# ============================================================

def test_claim_batch(expected_ids):
    worker_id = "phase-6f-worker"

    claimed_rows = []

    with SessionLocal() as session:
        for putusan_id in expected_ids:
            claimed = claim_putusan_by_id(
                session,
                putusan_id=putusan_id,
                worker_id=worker_id,
            )

            assert claimed is not None, (
                f"6F.3: Putusan {putusan_id} gagal di-claim"
            )

            claimed_rows.append(claimed)

        # --------------------------------------------------------
        # 6F.3.1
        # Semua 5 berhasil di-claim.
        # --------------------------------------------------------
        assert len(claimed_rows) == 5

        # --------------------------------------------------------
        # 6F.3.2
        # Semua menjadi PROCESSING.
        #
        # IMPORTANT:
        # Validasi ORM object dilakukan SEBELUM commit,
        # supaya tidak terkena expire_on_commit.
        # --------------------------------------------------------
        assert all(
            row.status_scraping == ScrapingStatus.PROCESSING
            for row in claimed_rows
        )

        # --------------------------------------------------------
        # 6F.3.3
        # Semua dimiliki worker yang sama.
        # --------------------------------------------------------
        assert all(
            row.processing_worker_id == worker_id
            for row in claimed_rows
        )

        # --------------------------------------------------------
        # 6F.3.4
        # Processing token harus ada dan unik.
        # --------------------------------------------------------
        tokens = [
            row.processing_token
            for row in claimed_rows
        ]

        assert all(tokens), (
            "6F.3: ada processing_token yang kosong"
        )

        assert len(set(tokens)) == 5, (
            "6F.3: processing_token tidak unik"
        )

        # Commit setelah seluruh state hasil claim
        # lolos validasi.
        session.commit()

    # ------------------------------------------------------------
    # 6F.3.5
    # Persisted state harus benar setelah commit.
    #
    # Gunakan Session BARU agar kita benar-benar membaca
    # state dari PostgreSQL.
    # ------------------------------------------------------------
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(expected_ids)
                )
                .order_by(Putusan.id)
            ).all()
        )

    assert len(rows) == 5

    for row in rows:
        assert row.status_scraping == ScrapingStatus.PROCESSING
        assert row.processing_worker_id == worker_id
        assert row.processing_token
        assert row.processing_started_at is not None
        assert row.url_pdf is None
        assert row.retry_count == 0

    print("6F.3 Batch claim / PROCESSING state: PASS")

    return rows

# ============================================================
# 6F.4 - SUCCESS BATCH
# ============================================================

def test_success_batch(expected_ids):
    worker_id = "phase-6f-worker"

    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(expected_ids)
                )
                .order_by(Putusan.id)
            ).all()
        )

        assert len(rows) == 5

        tokens = {
            row.id: row.processing_token
            for row in rows
        }

        # ----------------------------------------------------
        # Dua Putusan pertama diselesaikan SUCCESS.
        # ----------------------------------------------------
        for putusan_id in expected_ids[:2]:
            completed = putusan_lifecycle_service.mark_success(
                session,
                putusan_id=putusan_id,
                worker_id=worker_id,
                processing_token=tokens[putusan_id],
                url_pdf=(
                    f"https://example.test/phase-6f/pdf/"
                    f"{putusan_id}.pdf"
                ),
            )

            assert completed.status_scraping == ScrapingStatus.SUCCESS
            assert completed.url_pdf is not None
            assert completed.processing_worker_id is None
            assert completed.processing_token is None
            assert completed.processing_started_at is None
            assert completed.next_retry_at is None
            assert completed.last_error is None

        session.commit()

    # --------------------------------------------------------
    # Verifikasi persisted state SUCCESS.
    # --------------------------------------------------------
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(expected_ids[:2])
                )
                .order_by(Putusan.id)
            ).all()
        )

    assert len(rows) == 2

    for row in rows:
        assert row.status_scraping == ScrapingStatus.SUCCESS
        assert row.url_pdf == (
            f"https://example.test/phase-6f/pdf/"
            f"{row.id}.pdf"
        )
        assert row.processing_worker_id is None
        assert row.processing_token is None
        assert row.processing_started_at is None
        assert row.next_retry_at is None
        assert row.last_error is None

    print("6F.4 SUCCESS batch transition: PASS")


# ============================================================
# 6F.5 - UNPUBLISHED
# ============================================================

def test_unpublished_batch(expected_ids):
    worker_id = "phase-6f-worker"

    putusan_id = expected_ids[2]

    with SessionLocal() as session:
        row = session.get(Putusan, putusan_id)

        assert row is not None
        assert row.status_scraping == ScrapingStatus.PROCESSING

        token = row.processing_token

        assert token is not None

        completed = putusan_lifecycle_service.mark_unpublished(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            processing_token=token,
            error_message=(
                "Putusan ini tidak dipublikasikan "
                "untuk melindungi privasi."
            ),
        )

        assert completed.status_scraping == ScrapingStatus.UNPUBLISHED
        assert completed.url_pdf is None
        assert completed.processing_worker_id is None
        assert completed.processing_token is None
        assert completed.processing_started_at is None
        assert completed.next_retry_at is None
        assert completed.last_error is not None

        session.commit()

    # --------------------------------------------------------
    # Verifikasi persisted state UNPUBLISHED.
    # --------------------------------------------------------
    with SessionLocal() as session:
        row = session.get(Putusan, putusan_id)

        assert row is not None
        assert row.status_scraping == ScrapingStatus.UNPUBLISHED
        assert row.url_pdf is None
        assert row.processing_worker_id is None
        assert row.processing_token is None
        assert row.processing_started_at is None
        assert row.next_retry_at is None
        assert row.last_error == (
            "Putusan ini tidak dipublikasikan "
            "untuk melindungi privasi."
        )

    print("6F.5 UNPUBLISHED transition: PASS")


# ============================================================
# 6F.6 - FAILED_RETRY
# ============================================================

def test_failed_retry_batch(expected_ids):
    worker_id = "phase-6f-worker"

    failed_ids = expected_ids[3:]
    retry_delay_seconds = 60

    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(failed_ids)
                )
                .order_by(Putusan.id)
            ).all()
        )

        assert len(rows) == 2

        tokens = {
            row.id: row.processing_token
            for row in rows
        }

        assert all(tokens.values())

        before_times = {}

        for putusan_id in failed_ids:
            before_times[putusan_id] = (
                datetime.now(timezone.utc)
            )

            failed = putusan_lifecycle_service.mark_failed_retry(
                session,
                putusan_id=putusan_id,
                worker_id=worker_id,
                processing_token=tokens[putusan_id],
                error_message=(
                    "500 - Exception Error / "
                    "terjadi kesalahan pada aplikasi"
                ),
                retry_delay_seconds=retry_delay_seconds,
            )

            assert failed.status_scraping == ScrapingStatus.FAILED_RETRY
            assert failed.retry_count == 1
            assert failed.last_error == (
                "500 - Exception Error / "
                "terjadi kesalahan pada aplikasi"
            )
            assert failed.processing_worker_id is None
            assert failed.processing_token is None
            assert failed.processing_started_at is None
            assert failed.next_retry_at is not None

            assert failed.next_retry_at > before_times[putusan_id]

        session.commit()

    # --------------------------------------------------------
    # Verifikasi persisted state FAILED_RETRY.
    # --------------------------------------------------------
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(failed_ids)
                )
                .order_by(Putusan.id)
            ).all()
        )

    assert len(rows) == 2

    for row in rows:
        assert row.status_scraping == ScrapingStatus.FAILED_RETRY
        assert row.retry_count == 1
        assert row.last_error == (
            "500 - Exception Error / "
            "terjadi kesalahan pada aplikasi"
        )
        assert row.processing_worker_id is None
        assert row.processing_token is None
        assert row.processing_started_at is None
        assert row.next_retry_at is not None

    print("6F.6 FAILED_RETRY transition: PASS")

# ============================================================
# 6F.7 - FAILED_RETRY RECLAIM / TERMINAL INVARIANT
# ============================================================

def test_retry_reclaim_batch(expected_ids):
    worker_id = "phase-6f-retry-worker"

    success_ids = expected_ids[:2]
    unpublished_id = expected_ids[2]
    retry_ids = expected_ids[3:]

    assert len(retry_ids) == 2

    # --------------------------------------------------------
    # 6F.7.1
    # Buat FAILED_RETRY menjadi eligible untuk retry sekarang.
    #
    # 6F.6 sengaja memberikan next_retry_at ke masa depan.
    # Untuk test reclaim kita majukan waktunya.
    # --------------------------------------------------------
    with SessionLocal.begin() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(retry_ids)
                )
                .order_by(Putusan.id)
            ).all()
        )

        assert len(rows) == 2

        eligible_at = (
            datetime.now(timezone.utc)
            - timedelta(seconds=1)
        )

        for row in rows:
            assert row.status_scraping == ScrapingStatus.FAILED_RETRY
            assert row.retry_count == 1

            row.next_retry_at = eligible_at

    print(
        "6F.7.1 FAILED_RETRY dibuat eligible untuk retry: PASS"
    )

    # --------------------------------------------------------
    # 6F.7.2
    # SUCCESS tidak boleh di-claim kembali.
    # --------------------------------------------------------
    with SessionLocal() as session:
        for putusan_id in success_ids:
            claimed = claim_putusan_by_id(
                session,
                putusan_id=putusan_id,
                worker_id=worker_id,
            )

            assert claimed is None, (
                f"6F.7.2: SUCCESS Putusan {putusan_id} "
                "tidak boleh di-claim kembali"
            )

        session.rollback()

    print(
        "6F.7.2 SUCCESS tetap terminal: PASS"
    )

    # --------------------------------------------------------
    # 6F.7.3
    # UNPUBLISHED tidak boleh di-claim kembali.
    # --------------------------------------------------------
    with SessionLocal() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=unpublished_id,
            worker_id=worker_id,
        )

        assert claimed is None, (
            f"6F.7.3: UNPUBLISHED Putusan {unpublished_id} "
            "tidak boleh di-claim kembali"
        )

        session.rollback()

    print(
        "6F.7.3 UNPUBLISHED tetap terminal: PASS"
    )

    # --------------------------------------------------------
    # 6F.7.4
    # FAILED_RETRY yang sudah eligible harus bisa di-claim.
    # --------------------------------------------------------
    reclaimed = []

    with SessionLocal() as session:
        for putusan_id in retry_ids:
            claimed = claim_putusan_by_id(
                session,
                putusan_id=putusan_id,
                worker_id=worker_id,
            )

            assert claimed is not None, (
                f"6F.7.4: FAILED_RETRY Putusan "
                f"{putusan_id} harus dapat di-claim kembali"
            )

            assert (
                claimed.status_scraping
                == ScrapingStatus.PROCESSING
            )

            assert (
                claimed.processing_worker_id
                == worker_id
            )

            assert claimed.processing_token

            reclaimed.append(
                (
                    claimed.id,
                    claimed.processing_token,
                )
            )

        session.commit()

    assert len(reclaimed) == 2

    tokens = [
        token
        for _, token in reclaimed
    ]

    assert len(set(tokens)) == 2, (
        "6F.7.4: processing_token hasil reclaim "
        "harus unik"
    )

    print(
        "6F.7.4 FAILED_RETRY berhasil di-reclaim: PASS"
    )

    # --------------------------------------------------------
    # 6F.7.5
    # Verifikasi state persisted setelah reclaim.
    # --------------------------------------------------------
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(retry_ids)
                )
                .order_by(Putusan.id)
            ).all()
        )

        assert len(rows) == 2

        for row in rows:
            assert (
                row.status_scraping
                == ScrapingStatus.PROCESSING
            )

            assert (
                row.processing_worker_id
                == worker_id
            )

            assert row.processing_token

            assert row.processing_started_at is not None

            # retry_count tidak di-reset ketika reclaim.
            assert row.retry_count == 1

            # Claim kembali harus menghapus scheduling lama.
            assert row.next_retry_at is None

    print(
        "6F.7.5 Persisted reclaim state: PASS"
    )

    # --------------------------------------------------------
    # 6F.7.6
    # Final invariant batch.
    #
    # SUCCESS       = terminal
    # UNPUBLISHED   = terminal
    # FAILED_RETRY  = PROCESSING kembali
    # --------------------------------------------------------
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Putusan)
                .where(
                    Putusan.id.in_(expected_ids)
                )
                .order_by(Putusan.id)
            ).all()
        )

    assert len(rows) == 5

    by_id = {
        row.id: row
        for row in rows
    }

    for putusan_id in success_ids:
        row = by_id[putusan_id]

        assert (
            row.status_scraping
            == ScrapingStatus.SUCCESS
        )

        assert row.processing_worker_id is None
        assert row.processing_token is None
        assert row.processing_started_at is None
        assert row.next_retry_at is None

    row = by_id[unpublished_id]

    assert (
        row.status_scraping
        == ScrapingStatus.UNPUBLISHED
    )

    assert row.processing_worker_id is None
    assert row.processing_token is None
    assert row.processing_started_at is None
    assert row.next_retry_at is None

    for putusan_id in retry_ids:
        row = by_id[putusan_id]

        assert (
            row.status_scraping
            == ScrapingStatus.PROCESSING
        )

        assert (
            row.processing_worker_id
            == worker_id
        )

        assert row.processing_token
        assert row.processing_started_at is not None
        assert row.retry_count == 1
        assert row.next_retry_at is None

    print(
        "6F.7.6 Final batch retry invariant: PASS"
    )

    print("6F.7 Retry/Reclaim batch: PASS")


# ============================================================
# FINAL CHECKPOINT 6F.1 - 6F.3
# ============================================================

def verify_batch_state(expected_ids: list[int]) -> None:
    """
    Verifikasi database setelah 6F.1-6F.3.
    """

    with SessionLocal() as session:
        rows = session.scalars(
            select(Putusan)
            .where(
                Putusan.id.in_(expected_ids)
            )
            .order_by(Putusan.id)
        ).all()

        if len(rows) != 5:
            raise AssertionError(
                f"Expected 5 rows, got {len(rows)}"
            )

        for row in rows:
            if row.status_scraping != (
                ScrapingStatus.PROCESSING
            ):
                raise AssertionError(
                    f"Putusan {row.id} expected "
                    "PROCESSING."
                )

            if row.processing_worker_id != (
                "phase-6f-worker"
            ):
                raise AssertionError(
                    f"Putusan {row.id} memiliki "
                    "worker ID yang salah."
                )

            if not row.processing_token:
                raise AssertionError(
                    f"Putusan {row.id} tidak memiliki "
                    "processing_token."
                )

            if row.url_pdf is not None:
                raise AssertionError(
                    f"Putusan {row.id} seharusnya belum "
                    "memiliki url_pdf."
                )

            if row.retry_count != 0:
                raise AssertionError(
                    f"Putusan {row.id} seharusnya "
                    "retry_count=0."
                )

    print(
        "6F.3 Database invariant setelah claim: PASS"
    )


# ============================================================
# CLEANUP
# ============================================================

def cleanup(ids: list[int]) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            delete(Putusan).where(
                Putusan.id.in_(ids)
            )
        )

    print(
        f"Cleanup test rows: {ids}"
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print("=" * 50)
    print("PHASE 6F.1-6F.3 - PUTUSAN BATCH")
    print("=" * 50)
    print(
        f"ENV_FILE: {os.getenv('ENV_FILE', '.env')}"
    )

    test_ids: list[int] = []

    try:
        # ----------------------------------------------------
        # 6F.1
        # ----------------------------------------------------

        test_ids = seed_batch()

        if len(test_ids) != 5:
            raise AssertionError(
                f"Expected 5 seeded Putusan, got {len(test_ids)}"
            )

        print(
            "6F.1 Seed 5 Putusan PENDING: PASS"
        )

        # ----------------------------------------------------
        # 6F.2
        # ----------------------------------------------------

        dispatched_ids = test_dispatcher(
            test_ids
        )

        # ----------------------------------------------------
        # 6F.3
        # ----------------------------------------------------

        test_claim_batch(
            dispatched_ids
        )

        verify_batch_state(
            dispatched_ids
        )

        # ----------------------------------------------------
        # 6F.4
        # ----------------------------------------------------

        test_success_batch(
            dispatched_ids
        )

        # ----------------------------------------------------
        # 6F.5
        # ----------------------------------------------------

        test_unpublished_batch(
            dispatched_ids
        )

        # ----------------------------------------------------
        # 6F.6
        # ----------------------------------------------------

        test_failed_retry_batch(
            dispatched_ids
        )

        # ----------------------------------------------------
        # 6F.7
        # ----------------------------------------------------

        test_retry_reclaim_batch(
            dispatched_ids
        )

        print("=" * 50)
        print("PHASE 6F.7: PASS")
        print("=" * 50)

    finally:
        if test_ids:
            cleanup(test_ids)


if __name__ == "__main__":
    main()