from dataclasses import dataclass

from sqlalchemy.orm import Session
from utils.url import canonicalize_detail_url

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
    canonical_url = canonicalize_detail_url(data.url_detail)

    putusan, created = upsert_discovered_putusan(
        session,
        tahun=data.tahun,
        halaman=data.halaman,
        url_detail=canonical_url,
        judul=data.judul,
        is_unpublish=data.is_unpublish,
    )

    return putusan.id, created