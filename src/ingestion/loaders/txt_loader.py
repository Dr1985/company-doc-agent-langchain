"""Plain-text / Markdown document loader."""

from src.ingestion.loaders.base import BaseLoader
from src.system.logs import logger


class TxtLoader(BaseLoader):
    """Load text from plain-text and Markdown files."""

    async def load(self, file_path: str) -> str:
        """Read a text file as UTF-8.

        Args:
            file_path: Local path to the file.

        Returns:
            File content as string.
        """
        logger.info("txt_loading", path=file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                text = fh.read()
            logger.info("txt_loaded", path=file_path, chars=len(text))
            return text
        except UnicodeDecodeError:
            # Fallback for non-UTF-8 encoded text files
            with open(file_path, "r", encoding="gbk") as fh:
                text = fh.read()
            logger.info("txt_loaded_fallback_gbk", path=file_path, chars=len(text))
            return text
        except Exception as exc:
            logger.error("txt_load_failed", path=file_path, error=str(exc))
            raise
