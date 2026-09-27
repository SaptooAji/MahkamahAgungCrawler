import threading

from database.session import SessionLocal
from models.putusan import Putusan
from repositories.putusan_repository import (
    upsert_discovered_putusan,
)


TEST_URL = "https://example.com/discovery-concurrent/1"


def worker(name: str, barrier: threading.Barrier):
    with SessionLocal() as session:
        barrier.wait()

        putusan, created = upsert_discovered_putusan(
            session,
            tahun=2025,
            halaman=1,
            url_detail=TEST_URL,
            judul="Concurrent Discovery Test",
        )

        session.commit()

        print(
            f"{name}: "
            f"id={putusan.id}, "
            f"created={created}"
        )


def main():
    # Pastikan test dimulai dari kondisi bersih.
    with SessionLocal.begin() as session:
        session.query(Putusan).filter(
            Putusan.url_detail == TEST_URL
        ).delete(
            synchronize_session=False
        )

    barrier = threading.Barrier(2)

    worker_a = threading.Thread(
        target=worker,
        args=("Worker A", barrier),
    )

    worker_b = threading.Thread(
        target=worker,
        args=("Worker B", barrier),
    )

    worker_a.start()
    worker_b.start()

    worker_a.join()
    worker_b.join()

    with SessionLocal() as session:
        rows = (
            session.query(Putusan)
            .filter(
                Putusan.url_detail == TEST_URL
            )
            .all()
        )

        print("\nFinal rows:")

        for row in rows:
            print(
                row.id,
                row.url_detail,
                row.status_scraping,
            )

        print("\nTotal rows:", len(rows))


if __name__ == "__main__":
    main()