from __future__ import annotations

import argparse
import asyncio

from database.session import SessionLocal
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from services.discovery_run_service import discovery_run_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover pagination untuk satu ScrapingRun dan "
            "membuat DiscoveryPageJob secara idempotent."
        )
    )
    parser.add_argument(
        "--run-id",
        type=int,
        required=True,
        help="ID ScrapingRun yang akan diproses.",
    )
    return parser.parse_args()


async def main(run_id: int) -> None:
    # Ambil metadata run tanpa menahan transaksi saat browser bekerja.
    with SessionLocal() as session:
        run = session.get(ScrapingRun, run_id)

        if run is None:
            raise RuntimeError(
                f"ScrapingRun {run_id} tidak ditemukan."
            )

        if run.status not in (
            ScrapingRunStatus.PENDING,
            ScrapingRunStatus.RUNNING,
        ):
            raise RuntimeError(
                f"ScrapingRun {run_id} berstatus "
                f"{run.status.value}; hanya PENDING/RUNNING "
                "yang boleh dipakai oleh script ini."
            )

        if not run.url_halaman_pertama:
            raise RuntimeError(
                f"ScrapingRun {run_id} tidak memiliki "
                "url_halaman_pertama."
            )

        selected_run_id = run.id
        url_page_1 = run.url_halaman_pertama

        print("RUN_ID:", run.id)
        print("TAHUN:", run.tahun)
        print("STATUS:", run.status.value)
        print("PAGE 1:", url_page_1)

    browser = None

    try:
        import nodriver as uc

        browser = await uc.start()

        # Gunakan API service yang sama dengan jalur Celery production.
        pagination_result = (
            await discovery_run_service.discover_pagination(
                browser,
                url_halaman_pertama=url_page_1,
            )
        )

        print("PAGINATION MODE:", pagination_result.mode.value)
        print("TOTAL PAGES:", pagination_result.total_pages)
        print("PAGE DESCRIPTORS:", len(pagination_result.pages))

        if not pagination_result.pages:
            raise RuntimeError(
                "Pagination discovery tidak menghasilkan page descriptor."
            )

        with SessionLocal.begin() as session:
            run = session.get(ScrapingRun, selected_run_id)

            if run is None:
                raise RuntimeError(
                    f"ScrapingRun {run_id} hilang saat persistence."
                )

            created = discovery_run_service.persist_pagination_result(
                session,
                run=run,
                pagination_result=pagination_result,
            )

            print("CREATED PAGE JOBS:", created)
            print("DB TOTAL PAGES:", run.total_pages)
            print("DB PAGINATION MODE:", run.pagination_mode.value)

    finally:
        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.run_id))
