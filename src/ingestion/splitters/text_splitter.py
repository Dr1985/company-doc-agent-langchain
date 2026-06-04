"""Recursive text splitter for document chunking.

Wraps LangChain's ``RecursiveCharacterTextSplitter`` with sensible
defaults tuned for Chinese + English mixed corporate documents.
"""

from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config.settings import settings
from src.system.logs import logger


class DocumentSplitter:
    """Split document text into overlapping chunks.

    The splitter uses recursive semantic boundaries —
    ``\n\n`` → ``\n`` → ``。\n`` → ``。`` → `` `` —
    which works well for mixed Chinese / English content such as
    employee handbooks, policy documents, and technical manuals.
    """

    # Default separator order, prioritising paragraph and sentence
    # boundaries common in Chinese / English corporate writing.
    _DEFAULT_SEPARATORS: List[str] = [
        "\n\n",
        "\n",
        "。\n",
        "。",
        "！",
        "？",
        ". ",
        " ",
        "",
    ]

    def __init__(
        self,
        chunk_size: int = 0,
        chunk_overlap: int = 0,
        separators: List[str] = None,
    ):
        self._chunk_size = chunk_size or settings.INGESTION_CHUNK_SIZE
        self._chunk_overlap = chunk_overlap or settings.INGESTION_CHUNK_OVERLAP
        self._separators = separators or self._DEFAULT_SEPARATORS

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
            separators=self._separators,
            length_function=len,
            is_separator_regex=False,
        )

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self._chunk_overlap

    def split(self, text: str) -> List[str]:
        """Split text into chunks.

        Args:
            text: Full document text.

        Returns:
            List of text chunks.
        """
        if not text or not text.strip():
            return []

        chunks = self._splitter.split_text(text)
        # Filter out empty chunks
        chunks = [c for c in chunks if c.strip()]
        logger.debug(
            "text_split",
            chunk_count=len(chunks),
            chunk_size=self._chunk_size,
            overlap=self._chunk_overlap,
            total_chars=len(text),
        )
        return chunks

    def split_with_indices(self, text: str) -> List[dict]:
        """Split text and return chunks with metadata.

        Returns:
            List of dicts with ``index`` and ``content`` keys.
        """
        chunks = self.split(text)
        return [
            {"index": i, "content": chunk}
            for i, chunk in enumerate(chunks)
        ]
