import threading
import time

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import claim_pending_putusan


def seed_data():
    with SessionLocal.begin() as session:
        session.add_all([
            Putusan(
                tahun=2025,
                halaman=1,
                url_detail="https://example.com/concurrency/1",
                judul="Concurrency Test 1",
                status_scraping=ScrapingStatus.PENDING,
            ),
            Putusan(
                tahun=2025,
                halaman=2,
                url_detail="https://example.com/concurrency/2",
                judul="Concurrency Test 2",
                status_scraping=ScrapingStatus.PENDING,
            ),
            Putusan(
                tahun=2025,
                halaman=3,
                url_detail="https://example.com/concurrency/3",
                judul="Concurrency Test 3",
                status_scraping=ScrapingStatus.PENDING,
            ),
            Putusan(
                tahun=2025,
                halaman=4,
                url_detail="https://example.com/concurrency/4",
                judul="Concurrency Test 4",
                status_scraping=ScrapingStatus.PENDING,
            ),
        ])


def worker(name: str, barrier: threading.Barrier):
    with SessionLocal() as session:
        barrier.wait()

        print(f"{name}: attempting to claim...")

        putusan_list = claim_pending_putusan(
            session,
            batch_size=2,
        )

        claimed_ids = [putusan.id for putusan in putusan_list]

        print(f"{name}: claimed IDs = {claimed_ids}")

        # Tahan transaction supaya worker lain punya kesempatan
        # mencoba claim pada saat row masih terkunci.
        time.sleep(3)

        session.commit()

        print(f"{name}: committed")


def main():
    seed_data()

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

    print("\nFinal database state:")

    with SessionLocal() as session:
        rows = (
            session.query(Putusan)
            .filter(
                Putusan.url_detail.like(
                    "https://example.com/concurrency/%"
                )
            )
            .order_by(Putusan.id)
            .all()
        )

        for row in rows:
            print(
                row.id,
                row.url_detail,
                row.status_scraping,
            )


if __name__ == "__main__":
    main()