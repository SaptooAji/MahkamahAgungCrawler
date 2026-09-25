from database.session import SessionLocal
from models.putusan import Putusan
from services.putusan_lifecycle_service import (
    putusan_lifecycle_service,
)

from .celery import celery_app


@celery_app.task(
    name="putusan.process",
)
def process_putusan(
    putusan_id: int,
    worker_id: str,
):
    with SessionLocal.begin() as session:
        putusan = session.get(Putusan, putusan_id)

        if putusan is None:
            raise ValueError(
                f"Putusan {putusan_id} tidak ditemukan"
            )

        claimed = putusan_lifecycle_service.claim(
            session,
            worker_id=worker_id,
            batch_size=1,
        )

        if not claimed:
            raise RuntimeError(
                f"Tidak ada Putusan yang dapat di-claim "
                f"oleh worker {worker_id}"
            )

        claimed_putusan = claimed[0]

        if claimed_putusan.id != putusan_id:
            raise RuntimeError(
                f"Task meminta Putusan {putusan_id}, "
                f"tetapi claim mendapatkan "
                f"Putusan {claimed_putusan.id}"
            )

    with SessionLocal.begin() as session:
        putusan = putusan_lifecycle_service.mark_success(
            session,
            putusan_id=putusan_id,
            worker_id=worker_id,
            url_pdf=None,
        )

        return {
            "putusan_id": putusan.id,
            "status": putusan.status_scraping.value,
        }