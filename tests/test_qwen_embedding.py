import asyncio

from src.embedding.qwen_embedding import QwenEmbeddingService


def _make_service(batch_size: int = 10) -> QwenEmbeddingService:
    service = object.__new__(QwenEmbeddingService)
    service._api_key = "test-key"
    service._base_url = "https://example.com/compatible-mode/v1"
    service._model = "text-embedding-v4"
    service._batch_size = batch_size
    return service


def test_embed_documents_batches_requests_and_preserves_order():
    service = _make_service(batch_size=10)
    seen_batches = []
    counter = 0

    async def fake_post_embeddings(texts):
        nonlocal counter
        seen_batches.append(list(texts))
        embeddings = []
        for _ in texts:
            embeddings.append([float(counter)])
            counter += 1
        return embeddings

    service._post_embeddings = fake_post_embeddings

    texts = [f"chunk-{i}" for i in range(11)]
    result = asyncio.run(service.embed_documents(texts))

    assert seen_batches == [texts[:10], texts[10:]]
    assert [vector[0] for vector in result] == [float(i) for i in range(11)]


def test_embed_query_uses_single_item_batch():
    service = _make_service()
    seen_batches = []

    async def fake_post_embeddings(texts):
        seen_batches.append(list(texts))
        return [[0.12, 0.34]]

    service._post_embeddings = fake_post_embeddings

    result = asyncio.run(service.embed_query("公司员工手册"))

    assert seen_batches == [["公司员工手册"]]
    assert result == [0.12, 0.34]

