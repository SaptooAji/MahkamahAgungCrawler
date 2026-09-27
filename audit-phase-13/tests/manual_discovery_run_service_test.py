
import asyncio
import sys

import nodriver as uc

from sqlalchemy import func, select

from database.session import SessionLocal

from models.discovery_page_job import (
    DiscoveryPageJob,
)

from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)

from services.discovery_run_service import (
    discovery_run_service,
)


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


YEAR = 2021

URL_PAGE_1 = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/tahun/2021.html"
)


async def main():
    browser = None
    run_id = None

    try:
        print("=" * 70)
        print("DISCOVERY SERVICE TEST")
        print("=" * 70)

        # ---------------------------------------------------------
        # START BROWSER
        # ---------------------------------------------------------

        browser = await uc.start(
            headless=False,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )

        # ---------------------------------------------------------
        # CREATE RUN
        # ---------------------------------------------------------

        with SessionLocal.begin() as session:
            run = discovery_run_service.create_run(
                session,
                tahun=YEAR,
                url_halaman_pertama=URL_PAGE_1,
            )

            run_id = run.id

            print()
            print(
                f"ScrapingRun ID : {run.id}"
            )

            assert (
                run.status
                == ScrapingRunStatus.PENDING
            )

            print(
                "RUN STATUS = PENDING: PASS"
            )

        # ---------------------------------------------------------
        # DISCOVERY
        # ---------------------------------------------------------

        with SessionLocal.begin() as session:
            run = session.get(
                ScrapingRun,
                run_id,
            )

            if run is None:
                raise RuntimeError(
                    "ScrapingRun tidak ditemukan."
                )

            # Browser bekerja di dalam method,
            # tetapi transaksi akan tetap kita commit
            # setelah hasil discovery tersedia.
            #
            # Untuk test ini kita menggunakan satu
            # session pendek untuk keseluruhan operasi.
            run, pagination_result = (
                await discovery_run_service.discover_run(
                    browser,
                    session,
                    run=run,
                )
            )

            print()
            print("DISCOVERY RESULT")
            print("-" * 70)

            print(
                f"Mode        : "
                f"{pagination_result.mode.value}"
            )

            print(
                f"Total pages : "
                f"{pagination_result.total_pages}"
            )

            print(
                f"Descriptors : "
                f"{len(pagination_result.pages)}"
            )

            # -----------------------------------------------------
            # ASSERT PAGINATION
            # -----------------------------------------------------

            assert (
                pagination_result.total_pages
                == 499
            )

            print(
                "TOTAL PAGES = 499: PASS"
            )

            assert len(
                pagination_result.pages
            ) == 499

            print(
                "PAGE DESCRIPTORS = 499: PASS"
            )

            # -----------------------------------------------------
            # ASSERT RUN
            # -----------------------------------------------------

            assert (
                run.pagination_mode.value
                == "PREDICTIVE"
            )

            print(
                "RUN PAGINATION MODE = PREDICTIVE: PASS"
            )

            assert (
                run.total_pages
                == 499
            )

            print(
                "RUN TOTAL PAGES = 499: PASS"
            )

        # ---------------------------------------------------------
        # VERIFY DATABASE
        # ---------------------------------------------------------

        with SessionLocal() as session:
            page_job_count = session.scalar(
                select(
                    func.count(
                        DiscoveryPageJob.id
                    )
                ).where(
                    DiscoveryPageJob.run_id
                    == run_id
                )
            )

            print()
            print("DATABASE")
            print("-" * 70)

            print(
                f"DiscoveryPageJob : "
                f"{page_job_count}"
            )

            assert page_job_count == 499

            print(
                "DISCOVERY PAGE JOBS = 499: PASS"
            )

            # -----------------------------------------------------
            # PAGE NUMBERS
            # -----------------------------------------------------

            page_jobs = session.scalars(
                select(DiscoveryPageJob)
                .where(
                    DiscoveryPageJob.run_id
                    == run_id
                )
                .order_by(
                    DiscoveryPageJob.page_number
                )
            ).all()

            page_numbers = [
                job.page_number
                for job in page_jobs
            ]

            assert page_numbers == list(
                range(1, 500)
            )

            print(
                "PAGE NUMBERS = 1..499: PASS"
            )

            # -----------------------------------------------------
            # PAGE 1
            # -----------------------------------------------------

            page_1 = page_jobs[0]

            assert (
                page_1.page_number == 1
            )

            print(
                "PAGE 1 NUMBER = 1: PASS"
            )

            assert (
                page_1.url_page
                == URL_PAGE_1
            )

            print(
                "PAGE 1 CANONICAL URL: PASS"
            )

            assert (
                "/page/1.html"
                not in page_1.url_page
            )

            print(
                "PAGE 1 IS NOT /page/1.html: PASS"
            )

            # -----------------------------------------------------
            # PAGE 2
            # -----------------------------------------------------

            page_2 = page_jobs[1]

            assert (
                page_2.page_number == 2
            )

            assert (
                page_2.url_page
                == (
                    "https://putusan3.mahkamahagung.go.id/"
                    "direktori/index/tahunjenis/putus/"
                    "tahun/2021/page/2.html"
                )
            )

            print(
                "PAGE 2 URL: PASS"
            )

            # -----------------------------------------------------
            # PAGE 499
            # -----------------------------------------------------

            page_499 = page_jobs[-1]

            assert (
                page_499.page_number == 499
            )

            assert (
                page_499.url_page
                == (
                    "https://putusan3.mahkamahagung.go.id/"
                    "direktori/index/tahunjenis/putus/"
                    "tahun/2021/page/499.html"
                )
            )

            print(
                "PAGE 499 URL: PASS"
            )

        print()
        print("=" * 70)
        print("DISCOVERY SERVICE TEST: PASS")
        print("=" * 70)

    finally:
        # ---------------------------------------------------------
        # CLEAN TEST DATA
        # ---------------------------------------------------------

        if run_id is not None:
            with SessionLocal.begin() as session:
                run = session.get(
                    ScrapingRun,
                    run_id,
                )

                if run is not None:
                    session.delete(run)

            print()
            print(
                f"TEST RUN {run_id} DELETED"
            )

        # ---------------------------------------------------------
        # STOP BROWSER
        # ---------------------------------------------------------

        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
