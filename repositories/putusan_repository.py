from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models.putusan import Putusan, ScrapingStatus


def claim_pending_putusan(
    session: Session,
    *,
    worker_id: str,
    batch_size: int = 10,
) -> list[Putusan]:
    now = datetime.now(timezone.utc)

    stmt = (
        select(Putusan)
        .where(
            Putusan.status_scraping.in_(
                [
                    ScrapingStatus.PENDING,
                    ScrapingStatus.FAILED_RETRY,
                ]
            ),
            (
                Putusan.next_retry_at.is_(None)
                | (Putusan.next_retry_at <= now)
            ),
        )
        .order_by(Putusan.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )

    putusan_list = session.scalars(stmt).all()

    for putusan in putusan_list:
        putusan.status_scraping = ScrapingStatus.PROCESSING
        putusan.processing_started_at = now
        putusan.processing_worker_id = worker_id
        putusan.processing_token = str(uuid4())
        putusan.next_retry_at = None

    session.flush()

    return putusan_list


def upsert_discovered_putusan(
    session: Session,
    *,
    run_id: int | None = None,
    tahun: int,
    halaman: int | None,
    url_detail: str,
    judul: str | None = None,
    is_unpublish: bool = False,
) -> tuple[Putusan, bool]:
    initial_status = (
        ScrapingStatus.UNPUBLISHED
        if is_unpublish
        else ScrapingStatus.PENDING
    )

    stmt = (
        insert(Putusan)
        .values(
            run_id=run_id,
            tahun=tahun,
            halaman=halaman,
            url_detail=url_detail,
            judul=judul,
            status_scraping=initial_status,
        )
        .on_conflict_do_nothing(
            index_elements=[Putusan.url_detail]
        )
        .returning(Putusan.id)
    )

    result = session.execute(stmt)
    inserted_id = result.scalar_one_or_none()

    if inserted_id is not None:
        putusan = session.get(Putusan, inserted_id)

        if putusan is None:
            raise RuntimeError(
                "Putusan berhasil dibuat tetapi tidak dapat dimuat kembali."
            )

        return putusan, True

    putusan = session.scalar(
        select(Putusan).where(
            Putusan.url_detail == url_detail
        )
    )

    if putusan is None:
        raise RuntimeError(
            "Putusan tidak ditemukan setelah ON CONFLICT DO NOTHING."
        )

    # Jangan mengambil alih Putusan yang sudah dimiliki run lain.
    # Run baru hanya boleh mengisi run_id jika sebelumnya belum ada.
    if putusan.run_id is None and run_id is not None:
        putusan.run_id = run_id

    # Discovery adalah sumber informasi terbaru mengenai
    # apakah sebuah putusan sedang berstatus Unpublish.
    #
    # Kita hanya melakukan rekonsiliasi terhadap state yang
    # aman diubah oleh discovery.
    if is_unpublish:
        if putusan.status_scraping in (
            ScrapingStatus.PENDING,
            ScrapingStatus.FAILED_RETRY,
        ):
            putusan.status_scraping = ScrapingStatus.UNPUBLISHED
            putusan.next_retry_at = None
            putusan.last_error = None

    else:
        # Jika sebelumnya UNPUBLISHED tetapi sekarang muncul
        # sebagai putusan normal, izinkan diproses kembali.
        if putusan.status_scraping == ScrapingStatus.UNPUBLISHED:
            putusan.status_scraping = ScrapingStatus.PENDING
            putusan.next_retry_at = None
            putusan.last_error = None

    # Judul/metadata discovery terbaru boleh diperbarui,
    # tetapi jangan mengubah ownership processing.
    if judul:
        putusan.judul = judul

    if halaman is not None:
        putusan.halaman = halaman

    session.flush()

    return putusan, False


def mark_putusan_success(
    session: Session,
    *,
    putusan_id: int,
    worker_id: str,
    processing_token: str,
    url_pdf: str | None = None,
) -> Putusan:
    stmt = (
        select(Putusan)
        .where(
            Putusan.id == putusan_id,
            Putusan.status_scraping == ScrapingStatus.PROCESSING,
            Putusan.processing_worker_id == worker_id,
            Putusan.processing_token == processing_token,
        )
    )

    putusan = session.scalar(stmt)

    if putusan is None:
        raise RuntimeError(
            f"Putusan {putusan_id} tidak sedang dimiliki "
            f"oleh worker {worker_id}"
        )

    putusan.status_scraping = ScrapingStatus.SUCCESS
    putusan.url_pdf = url_pdf
    putusan.last_error = None
    putusan.last_scraped_at = datetime.now(timezone.utc)
    putusan.processing_started_at = None
    putusan.processing_worker_id = None
    putusan.processing_token = None
    putusan.next_retry_at = None

    session.flush()

    return putusan


def mark_putusan_unpublished(
    session: Session,
    *,
    putusan_id: int,
    worker_id: str,
    processing_token: str,
    error_message: str | None = None,
) -> Putusan:
    putusan = session.scalar(
        select(Putusan).where(
            Putusan.id == putusan_id,
            Putusan.status_scraping == ScrapingStatus.PROCESSING,
            Putusan.processing_worker_id == worker_id,
            Putusan.processing_token == processing_token,
        )
    )

    if putusan is None:
        raise RuntimeError(
            f"Putusan {putusan_id} tidak dimiliki "
            f"worker {worker_id}"
        )

    putusan.status_scraping = ScrapingStatus.UNPUBLISHED
    putusan.last_error = error_message
    putusan.processing_started_at = None
    putusan.processing_worker_id = None
    putusan.processing_token = None
    putusan.next_retry_at = None

    session.flush()

    return putusan


def mark_putusan_failed_retry(
    session: Session,
    *,
    putusan_id: int,
    worker_id: str,
    processing_token: str,
    error_message: str,
    retry_delay_seconds: int = 300,
) -> Putusan:
    putusan = session.scalar(
        select(Putusan).where(
            Putusan.id == putusan_id,
            Putusan.status_scraping == ScrapingStatus.PROCESSING,
            Putusan.processing_worker_id == worker_id,
            Putusan.processing_token == processing_token,
        )
    )

    if putusan is None:
        raise RuntimeError(
            f"Putusan {putusan_id} tidak dimiliki "
            f"worker {worker_id}"
        )

    now = datetime.now(timezone.utc)

    putusan.status_scraping = ScrapingStatus.FAILED_RETRY
    putusan.retry_count += 1
    putusan.last_error = error_message
    putusan.processing_started_at = None
    putusan.processing_worker_id = None
    putusan.processing_token = None
    putusan.next_retry_at = (
        now + timedelta(seconds=retry_delay_seconds)
    )

    session.flush()

    return putusan


def recover_stale_processing_putusan(
    session: Session,
    *,
    lease_timeout_seconds: int = 1800,
) -> int:
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=lease_timeout_seconds)
    )

    stmt = (
        select(Putusan)
        .where(
            Putusan.status_scraping == ScrapingStatus.PROCESSING,
            Putusan.processing_started_at.is_not(None),
            Putusan.processing_started_at < cutoff,
        )
        .with_for_update(skip_locked=True)
    )

    putusan_list = session.scalars(stmt).all()

    for putusan in putusan_list:
        putusan.status_scraping = ScrapingStatus.FAILED_RETRY
        putusan.retry_count += 1
        putusan.last_error = (
            "Processing lease expired; job recovered automatically."
        )
        putusan.processing_started_at = None
        putusan.processing_worker_id = None
        putusan.processing_token = None
        putusan.next_retry_at = datetime.now(timezone.utc)

    session.flush()

    return len(putusan_list)


def claim_putusan_by_id(
    session: Session,
    *,
    putusan_id: int,
    worker_id: str,
) -> Putusan | None:
    now = datetime.now(timezone.utc)

    stmt = (
        select(Putusan)
        .where(
            Putusan.id == putusan_id,
            Putusan.status_scraping.in_(
                [
                    ScrapingStatus.PENDING,
                    ScrapingStatus.FAILED_RETRY,
                ]
            ),
            (
                Putusan.next_retry_at.is_(None)
                | (Putusan.next_retry_at <= now)
            ),
        )
        .with_for_update(skip_locked=True)
    )

    putusan = session.scalar(stmt)

    if putusan is None:
        return None

    putusan.status_scraping = ScrapingStatus.PROCESSING
    putusan.processing_started_at = now
    putusan.processing_worker_id = worker_id
    putusan.processing_token = str(uuid4())
    putusan.next_retry_at = None

    session.flush()

    return putusan