from __future__ import annotations

import argparse

from database.session import SessionLocal
from services.discovery_run_service import discovery_run_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a clean ScrapingRun for MVP E2E testing.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    with SessionLocal.begin() as session:
        run = discovery_run_service.create_run(
            session,
            tahun=args.year,
            url_halaman_pertama=args.url,
        )
        print(f"Created run_id={run.id}")
        print(f"status={run.status.value}")
        print(f"tahun={run.tahun}")
        print(f"url={run.url_halaman_pertama}")


if __name__ == "__main__":
    main()
