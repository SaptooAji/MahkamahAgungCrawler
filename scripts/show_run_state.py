from __future__ import annotations

import argparse

from sqlalchemy import func, select

from database.session import SessionLocal
from models.discovery_page_job import DiscoveryPageJob
from models.putusan import Putusan
from models.scraping_run import ScrapingRun


def main() -> None:
    parser = argparse.ArgumentParser(description="Show one ScrapingRun state for Phase 13 E2E monitoring.")
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    with SessionLocal() as session:
        run = session.get(ScrapingRun, args.run_id)
        if run is None:
            raise SystemExit(f"run_id={args.run_id} tidak ditemukan")

        page_rows = session.execute(
            select(DiscoveryPageJob.status, func.count(DiscoveryPageJob.id))
            .where(DiscoveryPageJob.run_id == args.run_id)
            .group_by(DiscoveryPageJob.status)
        ).all()

        putusan_rows = session.execute(
            select(Putusan.status_scraping, func.count(Putusan.id))
            .where(Putusan.run_id == args.run_id)
            .group_by(Putusan.status_scraping)
        ).all()

        print(f"run_id={run.id}")
        print(f"tahun={run.tahun}")
        print(f"status={run.status.value}")
        print(f"total_pages={run.total_pages}")
        print(f"pagination_mode={run.pagination_mode.value if run.pagination_mode else None}")
        print(f"total_discovered={run.total_discovered}")
        print(f"total_success={run.total_success}")
        print(f"total_failed={run.total_failed}")
        print(f"total_unpublished={run.total_unpublished}")
        print("discovery_page_jobs:")
        for status, count in page_rows:
            print(f"  {status.value}: {count}")
        print("putusan:")
        for status, count in putusan_rows:
            print(f"  {status.value}: {count}")


if __name__ == "__main__":
    main()
