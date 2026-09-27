from __future__ import annotations

from sqlalchemy import func, select

from database.session import SessionLocal
from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)
from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)
from services.discovery_page_worker import DiscoveryPageWorker


class DummyScraper:
    """Tidak pernah dipakai; test hanya memvalidasi claim idempotency."""


def seed_jobs() -> tuple[int, list[int]]:
    with SessionLocal.begin() as session:
        run = ScrapingRun(
            tahun=2099,
            status=ScrapingRunStatus.RUNNING,
        )
        session.add(run)
        session.flush()

        jobs = []
        for page_number in range(1, 6):
            job = DiscoveryPageJob(
                run_id=run.id,
                tahun=2099,
                page_number=page_number,
                url_page=(
                    "https://example.test/"
                    f"page/{page_number}.html"
                ),
                status=DiscoveryPageJobStatus.PENDING,
            )
            session.add(job)
            jobs.append(job)

        session.flush()

        return run.id, [job.id for job in jobs]


def cleanup(run_id: int) -> None:
    with SessionLocal.begin() as session:
        jobs = list(
            session.scalars(
                select(DiscoveryPageJob).where(
                    DiscoveryPageJob.run_id == run_id
                )
            )
        )

        for job in jobs:
            session.delete(job)

        run = session.get(ScrapingRun, run_id)
        if run is not None:
            session.delete(run)


def main() -> None:
    run_id, page_job_ids = seed_jobs()

    try:
        worker_a = DiscoveryPageWorker(DummyScraper())
        worker_b = DiscoveryPageWorker(DummyScraper())

        first_claims = [
            worker_a.claim(
                page_job_id=page_job_id,
                worker_id="phase5d-worker-a",
            )
            for page_job_id in page_job_ids
        ]

        second_claims = [
            worker_b.claim(
                page_job_id=page_job_id,
                worker_id="phase5d-worker-b",
            )
            for page_job_id in page_job_ids
        ]

        first_ok = all(claim is not None for claim in first_claims)
        second_blocked = all(claim is None for claim in second_claims)

        with SessionLocal() as session:
            processing_count = session.scalar(
                select(func.count())
                .select_from(DiscoveryPageJob)
                .where(
                    DiscoveryPageJob.run_id == run_id,
                    DiscoveryPageJob.status
                    == DiscoveryPageJobStatus.PROCESSING,
                )
            )

        print("=" * 70)
        print("PHASE 5D - DISCOVERY BATCH IDEMPOTENCY")
        print("=" * 70)
        print(f"Seeded jobs       : {len(page_job_ids)}")
        print(f"First claim       : {'PASS' if first_ok else 'FAIL'}")
        print(f"Duplicate blocked : {'PASS' if second_blocked else 'FAIL'}")
        print(f"Processing rows   : {processing_count}")
        print()

        if not first_ok:
            raise AssertionError(
                "Worker A gagal claim semua seeded DiscoveryPageJob."
            )

        if not second_blocked:
            raise AssertionError(
                "Worker B berhasil duplicate-claim DiscoveryPageJob."
            )

        if processing_count != len(page_job_ids):
            raise AssertionError(
                "Jumlah PROCESSING row tidak sesuai hasil first claim."
            )

        print("================================")
        print("PHASE 5D: PASS")
        print("================================")

    finally:
        cleanup(run_id)


if __name__ == "__main__":
    main()
