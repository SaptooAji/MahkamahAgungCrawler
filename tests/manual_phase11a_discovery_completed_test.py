from database.session import SessionLocal
from models.scraping_run import ScrapingRun, ScrapingRunStatus
from services.discovery_run_service import DiscoveryRunService


TEST_YEAR = 2098


def main():
    print("=" * 70)
    print("PHASE 11A - DISCOVERY COMPLETED LIFECYCLE")
    print("=" * 70)
    print(f"ENV_FILE: {__import__('os').getenv('ENV_FILE')}")
    print(f"TEST_YEAR: {TEST_YEAR}")
    print("=" * 70)

    service = DiscoveryRunService()
    run_id = None

    try:
        # ------------------------------------------------------------
        # 11A.1 Create RUNNING run
        # ------------------------------------------------------------
        with SessionLocal.begin() as session:
            run = service.create_run(
                session,
                tahun=TEST_YEAR,
                url_halaman_pertama=(
                    "https://putusan3.mahkamahagung.go.id/"
                    "direktori/index/tahunjenis/putus/tahun/2098.html"
                ),
            )

            service.mark_run_running(session, run=run)

            run_id = run.id

            assert run.status == ScrapingRunStatus.RUNNING
            assert run.started_at is not None

            print("11A.1 RUNNING state: PASS")

        # ------------------------------------------------------------
        # 11A.2 RUNNING -> DISCOVERY_COMPLETED
        # ------------------------------------------------------------
        with SessionLocal.begin() as session:
            run = session.get(ScrapingRun, run_id)

            assert run is not None
            assert run.status == ScrapingRunStatus.RUNNING

            service.mark_discovery_phase_completed(
                session,
                run=run,
            )

            assert run.status == ScrapingRunStatus.DISCOVERY_COMPLETED
            assert run.finished_at is None

            print("11A.2 RUNNING -> DISCOVERY_COMPLETED: PASS")
            print("11A.3 Discovery completion does not set finished_at: PASS")

        # ------------------------------------------------------------
        # 11A.4 Persisted DB invariant
        # ------------------------------------------------------------
        with SessionLocal() as session:
            run = session.get(ScrapingRun, run_id)

            assert run is not None
            assert run.status == ScrapingRunStatus.DISCOVERY_COMPLETED
            assert run.finished_at is None

            print("11A.4 Final persisted DB invariant: PASS")

        print()
        print("=" * 70)
        print("PHASE 11A: PASS")
        print("=" * 70)

    finally:
        if run_id is not None:
            with SessionLocal.begin() as session:
                run = session.get(ScrapingRun, run_id)

                if run is not None:
                    session.delete(run)

            print(f"Cleanup test run: {run_id}")


if __name__ == "__main__":
    main()