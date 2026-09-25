from database.session import SessionLocal

from services.discovery_service import (
    DiscoveredPutusan,
    save_discovered_putusan,
)


def main():
    data = DiscoveredPutusan(
        tahun=2025,
        halaman=1,
        url_detail="https://example.com/service/1",
        judul="Service Test",
    )

    with SessionLocal.begin() as session:
        putusan_id, created = save_discovered_putusan(
            session,
            data,
        )

        print(
            "Putusan ID:",
            putusan_id,
        )

        print(
            "Created:",
            created,
        )


if __name__ == "__main__":
    main()