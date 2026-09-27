from database.session import SessionLocal
from services.putusan_lifecycle_service import putusan_lifecycle_service


TEST_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/putusan/zaf1b893e1c591d2b0aa313034373531.html"
    "?celery_test=1"
)


with SessionLocal.begin() as session:
    putusan, created = putusan_lifecycle_service.upsert_discovered(
        session,
        tahun=2021,
        halaman=1,
        url_detail=TEST_URL,
        judul="CELERY INTEGRATION TEST - Putusan PN RANGKAS BITUNG",
        is_unpublish=False,
    )

    print("Putusan ID :", putusan.id)
    print("Created    :", created)
    print("Status     :", putusan.status_scraping)
    print("URL Detail :", putusan.url_detail)