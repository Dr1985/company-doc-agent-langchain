"""DOCX document loader using python-docx."""

from src.ingestion.loaders.base import BaseLoader
from src.system.logs import logger


class DocxLoader(BaseLoader):
    """Load text from Word ``.docx`` files."""

    async def load(self, file_path: str) -> str:
        """Extract text from a DOCX file.

        Args:
            file_path: Local path to the DOCX file.

        Returns:
            Concatenated text from all paragraphs.
        """
        from docx import Document as DocxDocument

        logger.info("docx_loading", path=file_path)
        try:
            doc = DocxDocument(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            full_text = "\n\n".join(paragraphs)
            logger.info("docx_loaded", path=file_path, paragraphs=len(paragraphs), chars=len(full_text))
            return full_text
        except Exception as exc:
            logger.error("docx_load_failed", path=file_path, error=str(exc))
            raise
