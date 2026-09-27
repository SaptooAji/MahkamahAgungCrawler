from __future__ import annotations

from sqlalchemy.orm import Session

from models.discovery_page_job import DiscoveryPageJobStatus
from models.putusan import ScrapingStatus
from models.scraping_run import ScrapingRun, ScrapingRunStatus

from repositories.discovery_page_job_repository import (
    get_run_status_counts,
)
from repositories.putusan_repository import (
    get_status_counts_by_year,
)


class RunFinalizerService:
    def try_finalize(
        self,
        session: Session,
        *,
        run: ScrapingRun,
    ) -> ScrapingRun:
        # Terminal run tidak boleh diproses ulang.
        if run.status in (
            ScrapingRunStatus.COMPLETED,
            ScrapingRunStatus.FAILED,
            ScrapingRunStatus.CANCELLED,
        ):
            return run

        # ====================================================
        # 1. DiscoveryPageJob state
        # ====================================================


        discovery_counts = get_run_status_counts(
            session,
            run_id=run.id,
        )

        discovery_non_terminal = sum(
            discovery_counts.get(status, 0)
            for status in (
                DiscoveryPageJobStatus.PENDING,
                DiscoveryPageJobStatus.PROCESSING,
                DiscoveryPageJobStatus.FAILED_RETRY,
            )
        )

        discovery_permanent_failed = (
            discovery_counts.get(
                DiscoveryPageJobStatus.FAILED_PERMANENT,
                0,
            )
            > 0
        )

        # ====================================================
        # 2. Discovery belum selesai
        # ====================================================

        if discovery_non_terminal > 0:
            return run

        # ====================================================
        # 3. Discovery selesai
        # ====================================================

        if run.status == ScrapingRunStatus.RUNNING:
            if discovery_permanent_failed:
                run.status = ScrapingRunStatus.FAILED
                run.finished_at = _utc_now()
            else:
                run.status = ScrapingRunStatus.DISCOVERY_COMPLETED

            session.flush()

        # ====================================================
        # 4. Jika discovery gagal permanent,
        #    run langsung FAILED
        # ====================================================

        if discovery_permanent_failed:
            return run

        # ====================================================
        # 5. Putusan state
        # ====================================================

        putusan_counts = get_status_counts_by_year(
            session,
            tahun=run.tahun,
        )

        putusan_non_terminal = sum(
            putusan_counts.get(status, 0)
            for status in (
                ScrapingStatus.PENDING,
                ScrapingStatus.PROCESSING,
                ScrapingStatus.FAILED_RETRY,
            )
        )

        putusan_permanent_failed = (
            putusan_counts.get(
                ScrapingStatus.FAILED_PERMANENT,
                0,
            )
            > 0
        )

        # ====================================================
        # 6. Putusan masih berjalan
        # ====================================================

        if putusan_non_terminal > 0:
            return run

        # ====================================================
        # 7. Putusan selesai
        # ====================================================

        if putusan_permanent_failed:
            run.status = ScrapingRunStatus.FAILED
            run.finished_at = _utc_now()

        else:
            run.status = ScrapingRunStatus.COMPLETED
            run.finished_at = _utc_now()

        session.flush()

        return run


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)