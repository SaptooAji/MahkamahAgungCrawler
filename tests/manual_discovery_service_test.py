from database.session import SessionLocal

from models.scraping_run import ScrapingRun
from services.discovery_service import (
    DiscoveredPutusan,
    save_discovered_putusan,
)

def main():
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=2025,
        )
        session.add(run)
        session.flush()

        data = DiscoveredPutusan(
            run_id=run.id,
            tahun=2025,
            halaman=1,
            url_detail="https://example.com/service/1",
            judul="Service Test",
        )

        putusan_id, created = save_discovered_putusan(
            session,
            data,
        )

        print("Run ID:", run.id)
        print("Putusan ID:", putusan_id)
        print("Created:", created)

if __name__ == "__main__":
    main()