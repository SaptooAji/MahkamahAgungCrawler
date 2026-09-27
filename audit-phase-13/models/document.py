# models/document.py
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class DocumentMetadata(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    nomor_putusan: Mapped[str] = mapped_column(unique=True, index=True)
    klasifikasi: Mapped[str]
    tanggal_putusan: Mapped[str]
    pdf_url: Mapped[str]
    status_download: Mapped[str] = mapped_column(default="pending") # Untuk n8n nanti