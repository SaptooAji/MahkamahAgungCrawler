from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus
from repositories.putusan_repository import claim_pending_putusan


def seed_data():
    with SessionLocal.begin() as session:
        session.add_all(
            [
                Putusan(
                    tahun=2025,
                    halaman=1,
                    url_detail="https://example.com/putusan/1",
                    judul="Test Putusan 1",
                    status_scraping=ScrapingStatus.PENDING,
                ),
                Putusan(
                    tahun=2025,
                    halaman=2,
                    url_detail="https://example.com/putusan/2",
                    judul="Test Putusan 2",
                    status_scraping=ScrapingStatus.PENDING,
                ),
                Putusan(
                    tahun=2025,
                    halaman=3,
                    url_detail="https://example.com/putusan/3",
                    judul="Test Putusan 3",
                    status_scraping=ScrapingStatus.PENDING,
                ),
                Putusan(
                    tahun=2025,
                    halaman=4,
                    url_detail="https://example.com/putusan/4",
                    judul="Test Putusan 4",
                    status_scraping=ScrapingStatus.FAILED_RETRY,
                ),
                Putusan(
                    tahun=2025,
                    halaman=5,
                    url_detail="https://example.com/putusan/5",
                    judul="Test Putusan 5",
                    status_scraping=ScrapingStatus.SUCCESS,
                ),
            ]
        )


def claim_data():
    with SessionLocal.begin() as session:
        putusan_list = claim_pending_putusan(
            session,
            batch_size=2,
        )

        print("Claimed:")

        for putusan in putusan_list:
            print(
                putusan.id,
                putusan.url_detail,
                putusan.status_scraping,
            )


if __name__ == "__main__":
    seed_data()
    claim_data()