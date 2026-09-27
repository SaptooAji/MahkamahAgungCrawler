from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from database.session import SessionLocal
from models.putusan import Putusan, ScrapingStatus


@dataclass(frozen=True, slots=True)
class PendingPutusan:
    id: int


def get_pending_putusan_ids(
    *,
    batch_size: int = 5,
    run_id: int | None = None,
) -> list[int]:
    """
    Mengambil ID Putusan yang siap diproses.

    Fungsi ini TIDAK melakukan claim.
    Claim dilakukan secara atomik oleh putusan.process
    ketika task mulai berjalan.
    """

    with SessionLocal() as session:
        stmt = (
            select(Putusan.id)
            .where(
                Putusan.status_scraping.in_(
                    [
                        ScrapingStatus.PENDING,
                        ScrapingStatus.FAILED_RETRY,
                    ]
                ),
                (
                    Putusan.next_retry_at.is_(None)
                    | (
                        Putusan.next_retry_at
                        <= __import__("datetime").datetime.now(
                            __import__("datetime").timezone.utc
                        )
                    )
                ),
            )
        )

        if run_id is not None:
            stmt = stmt.where(Putusan.run_id == run_id)

        stmt = stmt.order_by(Putusan.id).limit(batch_size)

        return list(session.scalars(stmt).all())