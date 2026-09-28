import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

# Jalankan dari root project, misalnya:
# ENV_FILE=.env.test python -m tests.persistence.putusan_claim_idempotency_test

from sqlalchemy import delete, select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import claim_putusan_by_id, mark_putusan_success


TEST_PREFIX = "__phase6c_claim_test__"


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def seed_pending(session, suffix=None):
    suffix = suffix or uuid4().hex
    putusan = Putusan(
        tahun=2099,
        halaman=1,
        url_detail=f"https://example.invalid/{TEST_PREFIX}/{suffix}",
        judul="Phase 6C test",
        status_scraping=ScrapingStatus.PENDING,
    )
    session.add(putusan)
    session.flush()
    return putusan.id


def fetch(session, putusan_id):
    return session.get(Putusan, putusan_id)


def cleanup_ids(ids):
    ids = [x for x in ids if x is not None]
    if not ids:
        return
    with SessionLocal() as session:
        session.execute(delete(Putusan).where(Putusan.id.in_(ids)))
        session.commit()


def test_6c1_single_claim(created):
    with SessionLocal() as session:
        putusan_id = seed_pending(session)
        session.commit()
        created.append(putusan_id)

    with SessionLocal() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="phase6c-worker-a",
        )
        assert_true(claimed is not None, "6C.1: claim pertama harus berhasil")
        assert_true(claimed.id == putusan_id, "6C.1: ID hasil claim salah")
        assert_true(
            claimed.status_scraping == ScrapingStatus.PROCESSING,
            "6C.1: status harus PROCESSING",
        )
        assert_true(
            claimed.processing_worker_id == "phase6c-worker-a",
            "6C.1: processing_worker_id salah",
        )
        assert_true(
            claimed.processing_token,
            "6C.1: processing_token tidak boleh kosong",
        )
        token = claimed.processing_token
        session.commit()

    with SessionLocal() as session:
        row = fetch(session, putusan_id)
        assert_true(row is not None, "6C.1: row hilang")
        assert_true(row.status_scraping == ScrapingStatus.PROCESSING, "6C.1: state tidak tersimpan")
        assert_true(row.processing_worker_id == "phase6c-worker-a", "6C.1: worker tidak tersimpan")
        assert_true(row.processing_token == token, "6C.1: token tidak konsisten")

    print("6C.1 Single claim: PASS")


def test_6c2_duplicate_claim(created):
    with SessionLocal() as session:
        putusan_id = seed_pending(session)
        session.commit()
        created.append(putusan_id)

    with SessionLocal() as session:
        first = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="phase6c-worker-a",
        )
        assert_true(first is not None, "6C.2: worker A harus berhasil claim")
        session.commit()

    with SessionLocal() as session:
        second = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="phase6c-worker-b",
        )
        assert_true(second is None, "6C.2: worker B tidak boleh claim row PROCESSING")
        session.rollback()

    print("6C.2 Duplicate claim blocked: PASS")


def test_6c3_token_uniqueness(created):
    with SessionLocal() as session:
        id_a = seed_pending(session, "token-a")
        id_b = seed_pending(session, "token-b")
        session.commit()
        created.extend([id_a, id_b])

    with SessionLocal() as session:
        a = claim_putusan_by_id(session, putusan_id=id_a, worker_id="phase6c-worker-a")
        b = claim_putusan_by_id(session, putusan_id=id_b, worker_id="phase6c-worker-a")
        assert_true(a is not None and b is not None, "6C.3: kedua claim harus berhasil")
        assert_true(a.processing_token, "6C.3: token A kosong")
        assert_true(b.processing_token, "6C.3: token B kosong")
        assert_true(
            a.processing_token != b.processing_token,
            "6C.3: processing_token harus unik antar claim",
        )
        session.commit()

    print("6C.3 Processing token uniqueness: PASS")


def test_6c4_ownership_protection(created):
    with SessionLocal() as session:
        putusan_id = seed_pending(session, "ownership")
        session.commit()
        created.append(putusan_id)

    with SessionLocal() as session:
        claimed = claim_putusan_by_id(
            session,
            putusan_id=putusan_id,
            worker_id="phase6c-owner",
        )
        assert_true(claimed is not None, "6C.4: owner claim harus berhasil")
        token = claimed.processing_token
        session.commit()

    # Worker salah dengan token yang benar.
    with SessionLocal() as session:
        try:
            mark_putusan_success(
                session,
                putusan_id=putusan_id,
                worker_id="phase6c-attacker",
                processing_token=token,
                url_pdf="https://example.invalid/fake.pdf",
            )
        except RuntimeError:
            session.rollback()
        else:
            raise AssertionError("6C.4: worker lain tidak boleh menyelesaikan Putusan")

    # Worker benar dengan token salah.
    with SessionLocal() as session:
        try:
            mark_putusan_success(
                session,
                putusan_id=putusan_id,
                worker_id="phase6c-owner",
                processing_token=str(uuid4()),
                url_pdf="https://example.invalid/fake.pdf",
            )
        except RuntimeError:
            session.rollback()
        else:
            raise AssertionError("6C.4: token lain tidak boleh menyelesaikan Putusan")

    # State harus tetap PROCESSING sebelum owner asli menyelesaikannya.
    with SessionLocal() as session:
        row = fetch(session, putusan_id)
        assert_true(row.status_scraping == ScrapingStatus.PROCESSING, "6C.4: state berubah setelah unauthorized update")
        assert_true(row.processing_worker_id == "phase6c-owner", "6C.4: ownership berubah")
        assert_true(row.processing_token == token, "6C.4: token berubah")

    # Owner asli boleh menyelesaikan row.
    with SessionLocal() as session:
        completed = mark_putusan_success(
            session,
            putusan_id=putusan_id,
            worker_id="phase6c-owner",
            processing_token=token,
            url_pdf="https://example.invalid/phase6c.pdf",
        )
        assert_true(completed.status_scraping == ScrapingStatus.SUCCESS, "6C.4: owner asli harus dapat menyelesaikan")
        session.commit()

    print("6C.4 Ownership protection: PASS")


def test_6c5_actual_postgres_concurrency(created):
    """
    PostgreSQL concurrency test yang sengaja mempertahankan transaction worker A
    tetap terbuka setelah claim. Worker B kemudian mencoba claim row yang sama.
    Dengan FOR UPDATE SKIP LOCKED, B harus langsung mendapatkan None, bukan menunggu
    lock A selesai dan bukan mendapatkan row yang sama.
    """
    with SessionLocal() as session:
        putusan_id = seed_pending(session, "concurrency")
        session.commit()
        created.append(putusan_id)

    a_claimed = threading.Event()
    allow_a_commit = threading.Event()
    result = {}

    def worker_a():
        with SessionLocal() as session:
            try:
                claimed = claim_putusan_by_id(
                    session,
                    putusan_id=putusan_id,
                    worker_id="phase6c-concurrency-a",
                )
                result["a_claimed"] = claimed is not None
                result["a_token"] = claimed.processing_token if claimed else None
                a_claimed.set()

                # Pertahankan row lock sampai worker B selesai mencoba.
                if not allow_a_commit.wait(timeout=10):
                    raise TimeoutError("6C.5: timeout menunggu worker B")

                session.commit()
            except BaseException as exc:
                result["a_error"] = repr(exc)
                session.rollback()
                a_claimed.set()
                allow_a_commit.set()

    def worker_b():
        if not a_claimed.wait(timeout=10):
            result["b_error"] = "6C.5: worker A tidak pernah mencapai claim"
            allow_a_commit.set()
            return

        started = time.monotonic()
        with SessionLocal() as session:
            try:
                claimed = claim_putusan_by_id(
                    session,
                    putusan_id=putusan_id,
                    worker_id="phase6c-concurrency-b",
                )
                result["b_claimed"] = claimed is not None
                result["b_elapsed"] = time.monotonic() - started
                session.rollback()
            except BaseException as exc:
                result["b_error"] = repr(exc)
                session.rollback()
            finally:
                allow_a_commit.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(worker_a)
        future_b = executor.submit(worker_b)
        future_a.result(timeout=15)
        future_b.result(timeout=15)

    assert_true("a_error" not in result, f"6C.5: worker A error: {result.get('a_error')}")
    assert_true("b_error" not in result, f"6C.5: worker B error: {result.get('b_error')}")
    assert_true(result.get("a_claimed") is True, "6C.5: worker A harus mendapatkan claim")
    assert_true(result.get("b_claimed") is False, "6C.5: worker B tidak boleh mendapatkan row yang sama")
    assert_true(
        result.get("b_elapsed", 999) < 5,
        f"6C.5: worker B terlalu lama menunggu lock: {result.get('b_elapsed'):.3f}s",
    )

    with SessionLocal() as session:
        row = fetch(session, putusan_id)
        assert_true(row.status_scraping == ScrapingStatus.PROCESSING, "6C.5: row harus tetap PROCESSING")
        assert_true(
            row.processing_worker_id == "phase6c-concurrency-a",
            "6C.5: owner harus worker A",
        )
        assert_true(
            row.processing_token == result.get("a_token"),
            "6C.5: token owner berubah",
        )

        # Cleanup test row melalui DB session yang sama.
        session.delete(row)
        session.commit()
        created.remove(putusan_id)

    print("6C.5 PostgreSQL concurrent claim / SKIP LOCKED: PASS")


def main():
    env_file = os.getenv("ENV_FILE", ".env")
    print("==================================================")
    print("PHASE 6C - PUTUSAN CLAIM / IDEMPOTENCY")
    print("==================================================")
    print(f"ENV_FILE: {env_file}")

    created = []
    try:
        test_6c1_single_claim(created)
        test_6c2_duplicate_claim(created)
        test_6c3_token_uniqueness(created)
        test_6c4_ownership_protection(created)
        test_6c5_actual_postgres_concurrency(created)

        print("==================================================")
        print("PHASE 6C: PASS")
        print("==================================================")
    finally:
        cleanup_ids(created)
        if created:
            print(f"Cleanup residual test rows: {created}")
        else:
            print("Cleanup residual test rows: DONE")


if __name__ == "__main__":
    main()
