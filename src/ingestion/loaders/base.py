"""Base document loader interface.

All file-type-specific loaders inherit from this class and
implement ``load()`` which returns the full text content.
"""

from abc import ABC, abstractmethod
from typing import List


class BaseLoader(ABC):
    """Abstract base loader for document files."""

    @abstractmethod
    async def load(self, file_path: str) -> str:
        """Load a document and return its full text content.

        Args:
            file_path: Local path to the file.

        Returns:
            Extracted plain-text content.
        """
