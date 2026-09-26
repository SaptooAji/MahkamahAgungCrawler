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
    is_unpublish: bool = False


def save_discovered_putusan(
    session: Session,
    data: DiscoveredPutusan,
) -> tuple[int, bool]:
    putusan, created = upsert_discovered_putusan(
        session,
        tahun=data.tahun,
        halaman=data.halaman,
        url_detail=data.url_detail,
        judul=data.judul,
        is_unpublish=data.is_unpublish,
    )

    return putusan.id, created