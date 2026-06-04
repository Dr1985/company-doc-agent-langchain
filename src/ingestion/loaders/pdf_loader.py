"""PDF document loader using PyMuPDF (fitz)."""

from src.ingestion.loaders.base import BaseLoader
from src.system.logs import logger


class PdfLoader(BaseLoader):
    """Load text from PDF files via PyMuPDF."""

    async def load(self, file_path: str) -> str:
        """Extract text from a PDF file.

        Args:
            file_path: Local path to the PDF.

        Returns:
            Concatenated text from all pages.
        """
        import fitz  # PyMuPDF

        logger.info("pdf_loading", path=file_path)
        try:
            doc = fitz.open(file_path)
            try:
                pages = []
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    text = page.get_text()
                    if text.strip():
                        pages.append(text)
            finally:
                doc.close()
            full_text = "\n\n".join(pages)
            logger.info("pdf_loaded", path=file_path, pages=len(pages), chars=len(full_text))
            return full_text
        except Exception as exc:
            logger.error("pdf_load_failed", path=file_path, error=str(exc))
            raise
