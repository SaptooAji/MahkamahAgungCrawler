from __future__ import annotations

from datetime import datetime, timezone

from database.session import SessionLocal
from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)
from models.putusan import Putusan, ScrapingStatus
from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)
from services.run_finalizer_service import RunFinalizerService


TEST_YEAR = 2088


def utc_now():
    return datetime.now(timezone.utc)


def create_run(session: SessionLocal) -> ScrapingRun:
    run = ScrapingRun(
        tahun=TEST_YEAR,
        status=ScrapingRunStatus.RUNNING,
        started_at=utc_now(),
    )
    session.add(run)
    session.flush()
    return run


def create_page_job(
    session,
    *,
    run_id: int,
    page_number: int,
    status: DiscoveryPageJobStatus,
):
    job = DiscoveryPageJob(
        run_id=run_id,
        tahun=TEST_YEAR,
        page_number=page_number,
        url_page=(
            "https://putusan3.mahkamahagung.go.id/"
            f"direktori/index/tahunjenis/putus/tahun/{TEST_YEAR}"
            f"/page/{page_number}.html"
        ),
        status=status,
    )
    session.add(job)
    session.flush()
    return job


def create_putusan(
    session,
    *,
    url_suffix: str,
    status: ScrapingStatus,
):
    putusan = Putusan(
        tahun=TEST_YEAR,
        halaman=1,
        url_detail=(
            "https://putusan3.mahkamahagung.go.id/"
            f"direktori/putusan/{TEST_YEAR}/{url_suffix}.html"
        ),
        status_scraping=status,
    )
    session.add(putusan)
    session.flush()
    return putusan


def main():
    finalizer = RunFinalizerService()

    with SessionLocal.begin() as session:
        run = create_run(session)

        # ---------------------------------------------------------
        # Discovery: beberapa page job, sebagian masih aktif.
        # ---------------------------------------------------------
        create_page_job(
            session,
            run_id=run.id,
            page_number=1,
            status=DiscoveryPageJobStatus.SUCCESS,
        )

        create_page_job(
            session,
            run_id=run.id,
            page_number=2,
            status=DiscoveryPageJobStatus.SUCCESS,
        )

        create_page_job(
            session,
            run_id=run.id,
            page_number=3,
            status=DiscoveryPageJobStatus.PROCESSING,
        )

        # Putusan sudah ada, tetapi sebagian masih aktif.
        create_putusan(
            session,
            url_suffix="finalizer-success-1",
            status=ScrapingStatus.SUCCESS,
        )

        create_putusan(
            session,
            url_suffix="finalizer-unpublished-1",
            status=ScrapingStatus.UNPUBLISHED,
        )

        create_putusan(
            session,
            url_suffix="finalizer-processing-1",
            status=ScrapingStatus.PROCESSING,
        )

        # Discovery masih aktif.
        finalizer.try_finalize(
            session,
            run=run,
        )

        assert run.status == ScrapingRunStatus.RUNNING

        print("12F.1 Discovery masih aktif -> RUNNING: PASS")

        # ---------------------------------------------------------
        # Semua discovery terminal.
        # ---------------------------------------------------------
        page3 = session.scalar(
            __import__("sqlalchemy").select(DiscoveryPageJob)
            .where(
                DiscoveryPageJob.run_id == run.id,
                DiscoveryPageJob.page_number == 3,
            )
        )

        assert page3 is not None

        page3.status = DiscoveryPageJobStatus.SUCCESS
        session.flush()

        finalizer.try_finalize(
            session,
            run=run,
        )

        assert run.status == ScrapingRunStatus.DISCOVERY_COMPLETED

        print(
            "12F.2 Semua DiscoveryPageJob terminal "
            "-> DISCOVERY_COMPLETED: PASS"
        )

        # ---------------------------------------------------------
        # Putusan masih aktif.
        # ---------------------------------------------------------
        assert run.status == ScrapingRunStatus.DISCOVERY_COMPLETED

        finalizer.try_finalize(
            session,
            run=run,
        )

        assert run.status == ScrapingRunStatus.DISCOVERY_COMPLETED

        print(
            "12F.3 Putusan masih aktif "
            "-> tetap DISCOVERY_COMPLETED: PASS"
        )

        # ---------------------------------------------------------
        # Semua Putusan terminal.
        # ---------------------------------------------------------
        putusan_processing = session.scalar(
            __import__("sqlalchemy").select(Putusan)
            .where(
                Putusan.tahun == TEST_YEAR,
                Putusan.url_detail.like("%finalizer-processing-1%"),
            )
        )

        assert putusan_processing is not None

        putusan_processing.status_scraping = ScrapingStatus.SUCCESS
        session.flush()

        finalizer.try_finalize(
            session,
            run=run,
        )

        assert run.status == ScrapingRunStatus.COMPLETED
        assert run.finished_at is not None

        print(
            "12F.4 Semua Putusan terminal "
            "-> COMPLETED + finished_at: PASS"
        )

        # ---------------------------------------------------------
        # Idempotency.
        # ---------------------------------------------------------
        finished_at = run.finished_at

        finalizer.try_finalize(
            session,
            run=run,
        )

        assert run.status == ScrapingRunStatus.COMPLETED
        assert run.finished_at == finished_at

        print("12F.5 Finalizer idempotent: PASS")

        run_id = run.id

    # -------------------------------------------------------------
    # Skenario FAILED_PERMANENT pada Putusan.
    # -------------------------------------------------------------
    with SessionLocal.begin() as session:
        failed_run = create_run(session)

        create_page_job(
            session,
            run_id=failed_run.id,
            page_number=1,
            status=DiscoveryPageJobStatus.SUCCESS,
        )

        create_putusan(
            session,
            url_suffix="finalizer-permanent-failed-1",
            status=ScrapingStatus.FAILED_PERMANENT,
        )

        finalizer.try_finalize(
            session,
            run=failed_run,
        )

        assert failed_run.status == ScrapingRunStatus.FAILED
        assert failed_run.finished_at is not None

        print(
            "12F.6 Putusan FAILED_PERMANENT "
            "-> FAILED: PASS"
        )

        failed_run_id = failed_run.id

    # -------------------------------------------------------------
    # Skenario FAILED_PERMANENT pada DiscoveryPageJob.
    # -------------------------------------------------------------
    with SessionLocal.begin() as session:
        discovery_failed_run = create_run(session)

        create_page_job(
            session,
            run_id=discovery_failed_run.id,
            page_number=1,
            status=DiscoveryPageJobStatus.FAILED_PERMANENT,
        )

        finalizer.try_finalize(
            session,
            run=discovery_failed_run,
        )

        assert discovery_failed_run.status == ScrapingRunStatus.FAILED
        assert discovery_failed_run.finished_at is not None

        print(
            "12F.7 DiscoveryPageJob FAILED_PERMANENT "
            "-> FAILED: PASS"
        )

        discovery_failed_run_id = discovery_failed_run.id

    # -------------------------------------------------------------
    # Cleanup.
    # -------------------------------------------------------------
    with SessionLocal.begin() as session:
        session.query(Putusan).filter(
            Putusan.tahun == TEST_YEAR,
        ).delete(
            synchronize_session=False,
        )

        session.query(DiscoveryPageJob).filter(
            DiscoveryPageJob.run_id.in_(
                [
                    run_id,
                    failed_run_id,
                    discovery_failed_run_id,
                ]
            ),
        ).delete(
            synchronize_session=False,
        )

        session.query(ScrapingRun).filter(
            ScrapingRun.id.in_(
                [
                    run_id,
                    failed_run_id,
                    discovery_failed_run_id,
                ]
            ),
        ).delete(
            synchronize_session=False,
        )

        print(
            f"Cleanup Phase 12 Finalizer: "
            f"year={TEST_YEAR}"
        )

    print(
        "PHASE 12 RUN FINALIZER INTEGRATION: PASS"
    )


if __name__ == "__main__":
    main()