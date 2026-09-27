from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from database.session import SessionLocal
from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)


@dataclass(frozen=True, slots=True)
class PendingDiscoveryPage:
    id: int


def get_pending_discovery_page_ids(
    *,
    batch_size: int = 5,
    run_id: int | None = None,
) -> list[int]:

    if batch_size < 1:
        raise ValueError("batch_size harus >= 1")

    if batch_size > 5:
        raise ValueError(
            "batch_size maksimal 5 untuk menjaga batas concurrency."
        )

    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        stmt = (
            select(DiscoveryPageJob.id)
            .where(
                DiscoveryPageJob.status.in_(
                    [
                        DiscoveryPageJobStatus.PENDING,
                        DiscoveryPageJobStatus.FAILED_RETRY,
                    ]
                ),
                (
                    DiscoveryPageJob.next_retry_at.is_(None)
                    | (DiscoveryPageJob.next_retry_at <= now)
                ),
            )
        )

        if run_id is not None:
            stmt = stmt.where(
                DiscoveryPageJob.run_id == run_id
            )

        stmt = (
            stmt
            .order_by(DiscoveryPageJob.id)
            .limit(batch_size)
        )

        return list(session.scalars(stmt).all())