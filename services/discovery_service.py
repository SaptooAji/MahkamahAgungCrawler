from dataclasses import dataclass

from sqlalchemy.orm import Session

from repositories.putusan_repository import (
    upsert_discovered_putusan,
)


@dataclass(slots=True)
class DiscoveredPutusan:
    tahun: int
    halaman: int | None
    url_detail: str
    judul: str | None = None


def save_discovered_putusan(
    session: Session,
    data: DiscoveredPutusan,
) -> tuple[int, bool]:
    """
    Simpan hasil discovery ke database.

    Returns:
        (putusan_id, created)
    """

    putusan, created = upsert_discovered_putusan(
        session,
        tahun=data.tahun,
        halaman=data.halaman,
        url_detail=data.url_detail,
        judul=data.judul,
    )

    return putusan.id, created