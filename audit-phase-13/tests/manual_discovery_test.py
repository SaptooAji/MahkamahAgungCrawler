from database.session import SessionLocal
from models.putusan import ScrapingStatus
from repositories.putusan_repository import (
    upsert_discovered_putusan,
)


TEST_URL = "https://example.com/discovery/1"


def main():
    with SessionLocal.begin() as session:

        putusan_1, created_1 = upsert_discovered_putusan(
            session,
            tahun=2025,
            halaman=1,
            url_detail=TEST_URL,
            judul="Putusan Discovery Test",
        )

        print(
            "First discovery:",
            putusan_1.id,
            created_1,
            putusan_1.status_scraping,
        )

        putusan_2, created_2 = upsert_discovered_putusan(
            session,
            tahun=2025,
            halaman=1,
            url_detail=TEST_URL,
            judul="Putusan Discovery Test",
        )

        print(
            "Second discovery:",
            putusan_2.id,
            created_2,
            putusan_2.status_scraping,
        )

        print(
            "Same ID:",
            putusan_1.id == putusan_2.id,
        )

        putus_an = putusan_2
        putus_an.status_scraping = ScrapingStatus.SUCCESS

        session.flush()

        putusan_3, created_3 = upsert_discovered_putusan(
            session,
            tahun=2025,
            halaman=99,
            url_detail=TEST_URL,
            judul="Judul Baru",
        )

        print(
            "After SUCCESS rediscovery:",
            putusan_3.id,
            created_3,
            putusan_3.status_scraping,
            putusan_3.halaman,
            putusan_3.judul,
        )


if __name__ == "__main__":
    main()