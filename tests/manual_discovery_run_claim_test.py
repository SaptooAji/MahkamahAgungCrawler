from sqlalchemy import select

from database.session import SessionLocal

from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)

from services.discovery_run_service import (
    discovery_run_service,
)


YEAR = 2091

URL_PAGE_1 = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/tahunjenis/putus/tahun/2091.html"
)


def main():
    run_id = None

    try:
        print("=" * 70)
        print("DISCOVERY RUN CLAIM TEST")
        print("=" * 70)

        # ---------------------------------------------------------
        # CREATE
        # ---------------------------------------------------------

        with SessionLocal.begin() as session:
            run = discovery_run_service.create_run(
                session,
                tahun=YEAR,
                url_halaman_pertama=URL_PAGE_1,
            )

            run_id = run.id

            print()
            print(f"RUN ID : {run.id}")
            print(f"STATUS : {run.status.value}")

            assert (
                run.status
                == ScrapingRunStatus.PENDING
            )

            print("CREATE PENDING: PASS")

        # ---------------------------------------------------------
        # FIRST CLAIM
        # ---------------------------------------------------------

        with SessionLocal.begin() as session:
            claimed = discovery_run_service.claim_run(
                session,
                run_id=run_id,
            )

            assert claimed is not None

            assert (
                claimed.status
                == ScrapingRunStatus.RUNNING
            )

            assert claimed.started_at is not None

            print("FIRST CLAIM PENDING -> RUNNING: PASS")

        # ---------------------------------------------------------
        # SECOND CLAIM
        # ---------------------------------------------------------

        with SessionLocal.begin() as session:
            claimed_again = (
                discovery_run_service.claim_run(
                    session,
                    run_id=run_id,
                )
            )

            assert claimed_again is None

            print(
                "SECOND CLAIM -> SKIPPED: PASS"
            )

        # ---------------------------------------------------------
        # VERIFY DATABASE
        # ---------------------------------------------------------

        with SessionLocal() as session:
            run = session.scalar(
                select(ScrapingRun).where(
                    ScrapingRun.id == run_id
                )
            )

            assert run is not None

            assert (
                run.status
                == ScrapingRunStatus.RUNNING
            )

            print(
                "DATABASE STATUS = RUNNING: PASS"
            )

        print()
        print("=" * 70)
        print("DISCOVERY RUN CLAIM TEST: PASS")
        print("=" * 70)

    finally:
        if run_id is not None:
            with SessionLocal.begin() as session:
                run = session.get(
                    ScrapingRun,
                    run_id,
                )

                if run is not None:
                    session.delete(run)

            print(
                f"TEST RUN {run_id} DELETED"
            )


if __name__ == "__main__":
    main()