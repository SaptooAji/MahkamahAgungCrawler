from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.discovery_page_job import (
    DiscoveryPageJob,
    DiscoveryPageJobStatus,
)
from models.putusan import Putusan, ScrapingStatus
from models.scraping_run import (
    ScrapingRun,
    ScrapingRunStatus,
)


class RunLifecycleService:
    """
    Menentukan apakah satu ScrapingRun benar-benar selesai.

    Discovery selesai != seluruh run selesai.

    Putusan yang diproses oleh run diidentifikasi melalui
    Putusan.run_id. run_id bukan identity Putusan; url_detail
    tetap UNIQUE.
    """

    def mark_discovery_phase_completed(
        self,
        session: Session,
        *,
        run: ScrapingRun,
    ) -> ScrapingRun:
        """
        RUNNING -> DISCOVERY_COMPLETED.

        Method ini hanya menandai bahwa seluruh pagination result
        sudah dibuat menjadi DiscoveryPageJob. Ia tidak mengisi
        finished_at karena PDF processing masih berjalan.
        """
        if run.status == ScrapingRunStatus.DISCOVERY_COMPLETED:
            return run

        if run.status != ScrapingRunStatus.RUNNING:
            raise RuntimeError(
                f"Run {run.id} tidak dapat masuk "
                f"DISCOVERY_COMPLETED dari status {run.status.value}."
            )

        run.status = ScrapingRunStatus.DISCOVERY_COMPLETED
        session.flush()
        return run

    def finalize(
        self,
        session: Session,
        *,
        run: ScrapingRun,
    ) -> ScrapingRun:
        """
        Evaluasi dan finalisasi run secara idempotent.

        COMPLETED hanya jika:
        - semua DiscoveryPageJob SUCCESS;
        - semua Putusan milik run terminal SUCCESS/UNPUBLISHED;
        - tidak ada FAILED_PERMANENT.

        Jika ada FAILED_PERMANENT, run menjadi FAILED.
        """
        if run.status in (
            ScrapingRunStatus.COMPLETED,
            ScrapingRunStatus.FAILED,
            ScrapingRunStatus.CANCELLED,
        ):
            return run

        page_counts = dict(
            session.execute(
                select(
                    DiscoveryPageJob.status,
                    func.count(DiscoveryPageJob.id),
                )
                .where(DiscoveryPageJob.run_id == run.id)
                .group_by(DiscoveryPageJob.status)
            ).all()
        )

        total_page_jobs = sum(page_counts.values())
        failed_page_jobs = page_counts.get(
            DiscoveryPageJobStatus.FAILED_PERMANENT,
            0,
        )
        pending_page_jobs = (
            page_counts.get(DiscoveryPageJobStatus.PENDING, 0)
            + page_counts.get(DiscoveryPageJobStatus.PROCESSING, 0)
            + page_counts.get(DiscoveryPageJobStatus.FAILED_RETRY, 0)
        )

        putusan_counts = dict(
            session.execute(
                select(
                    Putusan.status_scraping,
                    func.count(Putusan.id),
                )
                .where(Putusan.run_id == run.id)
                .group_by(Putusan.status_scraping)
            ).all()
        )

        total_putusan = sum(putusan_counts.values())
        putusan_failed = putusan_counts.get(
            ScrapingStatus.FAILED_PERMANENT,
            0,
        )
        putusan_pending = (
            putusan_counts.get(ScrapingStatus.PENDING, 0)
            + putusan_counts.get(ScrapingStatus.PROCESSING, 0)
            + putusan_counts.get(ScrapingStatus.FAILED_RETRY, 0)
        )

        run.total_discovered = total_putusan
        run.total_success = putusan_counts.get(
            ScrapingStatus.SUCCESS,
            0,
        )
        run.total_unpublished = putusan_counts.get(
            ScrapingStatus.UNPUBLISHED,
            0,
        )
        run.total_failed = putusan_failed + failed_page_jobs

        if failed_page_jobs or putusan_failed:
            run.status = ScrapingRunStatus.FAILED
            run.last_error = (
                "Run memiliki pekerjaan FAILED_PERMANENT."
            )
            run.finished_at = datetime.now(timezone.utc)
            session.flush()
            return run

        # Tidak boleh selesai sebelum discovery page jobs selesai.
        if (
            total_page_jobs == 0
            or pending_page_jobs > 0
        ):
            session.flush()
            return run

        # Semua page job harus SUCCESS.
        successful_page_jobs = page_counts.get(
            DiscoveryPageJobStatus.SUCCESS,
            0,
        )
        if successful_page_jobs != total_page_jobs:
            session.flush()
            return run

        # Semua Putusan yang ditemukan harus terminal.
        if putusan_pending > 0:
            session.flush()
            return run

        # Tidak ada Putusan ditemukan juga sah, misalnya direktori kosong,
        # selama seluruh page job sukses.
        run.status = ScrapingRunStatus.COMPLETED
        run.finished_at = datetime.now(timezone.utc)
        run.last_error = None
        session.flush()
        return run


run_lifecycle_service = RunLifecycleService()
