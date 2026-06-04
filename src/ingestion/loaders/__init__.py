"""Document loaders for various file types."""

from src.ingestion.loaders.base import BaseLoader
from src.ingestion.loaders.pdf_loader import PdfLoader
from src.ingestion.loaders.txt_loader import TxtLoader
from src.ingestion.loaders.docx_loader import DocxLoader

__all__ = [
    "BaseLoader",
    "PdfLoader",
    "TxtLoader",
    "DocxLoader",
]
