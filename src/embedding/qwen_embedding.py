"""Qwen embedding service via DashScope OpenAI-compatible API.

Uses raw HTTP calls (``httpx``) instead of ``langchain_openai``
because the OpenAI SDK's internal Pydantic model serialises ``input``
in a way that DashScope rejects (``input.contents`` vs ``input``).

DashScope also appears to reject oversized embedding batches in this
project's environment, so document embedding is sent in small batches.
"""

from typing import List

import httpx

from src.config.settings import settings
from src.system.logs import logger


class QwenEmbeddingService:
    """Wrapper around Qwen text-embedding-v4 via direct HTTP calls.

    Provides batch embedding generation and single-query embedding
    using the OpenAI-compatible endpoint on DashScope.
    """

    def __init__(self):
        self._api_key = settings.QWEN_EMBEDDING_API_KEY
        self._base_url = settings.QWEN_EMBEDDING_BASE_URL.rstrip("/")
        self._model = settings.QWEN_EMBEDDING_MODEL
        self._batch_size = 10

        if not self._api_key:
            logger.warning("qwen_embedding_not_configured")
            return

        logger.info(
            "qwen_embedding_initialized",
            model=self._model,
            dims=settings.QWEN_EMBEDDING_DIMS,
        )

    @property
    def available(self) -> bool:
        """Whether the embedding service is configured."""
        return bool(self._api_key)

    @property
    def dims(self) -> int:
        """Embedding dimensionality (default 1024 for text-embedding-v4)."""
        return settings.QWEN_EMBEDDING_DIMS

    @staticmethod
    def _normalize_texts(texts: List[str]) -> List[str]:
        """Drop empty inputs while preserving the original text content."""
        normalized: List[str] = []
        for text in texts:
            if text is None:
                continue

            text_str = text if isinstance(text, str) else str(text)
            if text_str.strip():
                normalized.append(text_str)
        return normalized

    def _build_payload(self, texts: List[str]) -> dict:
        """Build the request payload for a single embedding batch."""
        return {
            "model": self._model,
            "input": texts[0] if len(texts) == 1 else texts,
        }

    async def _post_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Call DashScope for one embedding batch and return ordered vectors."""
        if not self.available:
            raise RuntimeError(
                "Qwen embedding service is not configured (missing QWEN_EMBEDDING_API_KEY)"
            )

        if not texts:
            return []

        payload = self._build_payload(texts)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            items = data.get("data", [])
            if any("index" in item for item in items):
                items = sorted(items, key=lambda item: item.get("index", 0))

            embeddings = [item["embedding"] for item in items]
            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"Embedding API returned {len(embeddings)} embeddings for {len(texts)} texts"
                )

            logger.debug("documents_embedded_batch", count=len(texts), got=len(embeddings))
            return embeddings

        except Exception as exc:
            logger.error("embed_documents_failed", error=str(exc), count=len(texts))
            raise

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of text strings via DashScope API.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each is a list of floats).

        Raises:
            RuntimeError: If the embedding service is not configured.
        """
        if not texts:
            return []

        normalized_texts = self._normalize_texts(texts)
        if not normalized_texts:
            return []

        batch_size = max(1, getattr(self, "_batch_size", 10))
        embeddings: List[List[float]] = []

        for start in range(0, len(normalized_texts), batch_size):
            batch = normalized_texts[start : start + batch_size]
            embeddings.extend(await self._post_embeddings(batch))

        logger.debug("documents_embedded", count=len(normalized_texts), got=len(embeddings))
        return embeddings

    async def embed_query(self, text: str) -> List[float]:
        """Embed a single query string.

        Args:
            text: Query text to embed.

        Returns:
            Single embedding vector.

        Raises:
            RuntimeError: If the embedding service is not configured.
        """
        if not self.available:
            raise RuntimeError(
                "Qwen embedding service is not configured (missing QWEN_EMBEDDING_API_KEY)"
            )

        embedding = (await self._post_embeddings([text]))[0]
        logger.debug("query_embedded", text_length=len(text))
        return embedding



# Singleton
qwen_embedding = QwenEmbeddingService()
