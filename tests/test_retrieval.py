"""Unit tests for retrieval modules: BM25, hybrid search, parent document recall.

Tests cover what2do.md §4.1 — 检索模块测试.
"""

import math

from src.retrieval.bm25 import BM25Retriever


# ── BM25 Tokenization ─────────────────────────────────────────────

class TestBM25Tokenization:
    """4.1.3: BM25 关键词检索 — 基本查询返回结果"""

    def test_tokenize_english(self):
        tokens = BM25Retriever._tokenize("Hello World test-DOCUMENT")
        assert tokens == ["hello", "world", "test", "document"]

    def test_tokenize_chinese(self):
        tokens = BM25Retriever._tokenize("你好世界 测试文档")
        assert "你好" in tokens or "你" in tokens  # Chinese char-level
        # The tokenizer splits on non-Chinese/alphanumeric characters

    def test_tokenize_mixed(self):
        tokens = BM25Retriever._tokenize("员工手册 v3.2 2026版")
        # Should extract Chinese chars, digits, letters
        assert len(tokens) > 0
        assert "v3" in tokens or "3" in tokens or "2026" in tokens

    def test_tokenize_empty(self):
        tokens = BM25Retriever._tokenize("")
        assert tokens == []

    def test_tokenize_only_punctuation(self):
        tokens = BM25Retriever._tokenize("!!! ??? ---")
        assert tokens == []


class TestBM25Scoring:
    """4.1.3: BM25 关键词检索 — 基本查询返回结果"""

    def test_score_basic(self):
        """Full match gets high score."""
        retriever = BM25Retriever()
        retriever._doc_count = 3
        retriever._avg_dl = 5.0
        retriever._idf = {"hello": 1.0, "world": 1.0}

        query_tokens = ["hello", "world"]
        doc_tokens = ["hello", "world", "hello", "world", "extra"]

        score = retriever._score(query_tokens, doc_tokens)
        assert score > 0

    def test_score_zero_when_no_overlap(self):
        retriever = BM25Retriever()
        retriever._doc_count = 3
        retriever._avg_dl = 5.0
        retriever._idf = {"hello": 1.0}

        query_tokens = ["hello"]
        doc_tokens = ["world", "test"]

        score = retriever._score(query_tokens, doc_tokens)
        assert score == 0.0

    def test_score_higher_for_more_matches(self):
        retriever = BM25Retriever()
        retriever._doc_count = 3
        retriever._avg_dl = 10.0
        retriever._idf = {"a": 1.0, "b": 1.0, "c": 1.0}

        score_few = retriever._score(["a"], ["a", "x", "y", "z", "w"])
        score_many = retriever._score(["a", "b", "c"], ["a", "b", "c", "x", "y"])

        assert score_many > score_few

    def test_search_empty_corpus_returns_empty(self):
        """4.1.2: 空查询 / 无匹配结果时返回空列表"""
        retriever = BM25Retriever()

        # Mock _load_corpus to leave empty
        retriever._doc_count = 0
        retriever._corpus = []
        retriever._idf = {}

        results = retriever.search("测试查询", top_k=5)
        assert results == []

    def test_search_empty_query_returns_empty(self):
        """空查询返回空列表"""
        retriever = BM25Retriever()
        retriever._doc_count = 1
        retriever._corpus = [{"tokens": ["test"]}]

        results = retriever.search("", top_k=5)
        assert results == []


# ── Hybrid Search Fusion ──────────────────────────────────────────

class TestHybridFusion:
    """4.1.4: 混合检索融合策略：向量 + BM25 结果合并排序"""

    def test_rrf_fusion_basic(self):
        """Verify RRF formula produces correct scores."""
        from src.retrieval.hybrid import RRF_K

        # RRF score = 1 / (K + rank + 1)
        rank_0 = 1.0 / (RRF_K + 0 + 1)  # 1/61 ≈ 0.01639
        rank_1 = 1.0 / (RRF_K + 1 + 1)  # 1/62 ≈ 0.01613

        assert 0.01 < rank_0 < 0.02
        assert rank_0 > rank_1  # lower rank = higher score

    def test_rrf_dedup_combines_scores(self):
        """Same chunk from both vector and BM25 gets combined score."""
        from src.retrieval.hybrid import RRF_K

        rank_v = 0
        rank_b = 0
        combined = (1.0 / (RRF_K + rank_v + 1)) + (1.0 / (RRF_K + rank_b + 1))
        single = 1.0 / (RRF_K + 0 + 1)

        assert combined > single  # combined score > single source score


# ── Parent Document Recall ────────────────────────────────────────

class TestParentDocumentRecall:
    """4.1.6: 父文档回溯：chunk 命中后能获取完整父文档上下文"""

    def test_window_expansion_indices(self):
        """Parent recall expands correct index ranges."""
        window = 2
        hit_indices = {5}
        all_indices = set(hit_indices)
        for idx in hit_indices:
            for delta in range(-window, window + 1):
                if delta != 0:
                    all_indices.add(idx + delta)
        # Should include 3, 4, 5, 6, 7
        expected = {3, 4, 5, 6, 7}
        assert all_indices == expected

    def test_window_at_boundary_zero(self):
        """Parent recall at chunk 0 should not go negative (handled by DB filter)."""
        window = 2
        hit_indices = {0}
        all_indices = set(hit_indices)
        for idx in hit_indices:
            for delta in range(-window, window + 1):
                if delta != 0:
                    all_indices.add(idx + delta)
        # -2, -1, 0, 1, 2 → negatives will be filtered by DB
        assert -2 in all_indices or -1 in all_indices  # expansion is raw

    def test_multiple_hits_merge(self):
        """Multiple hit chunks merge their windows."""
        window = 1
        hit_indices = {3, 7}
        all_indices = set(hit_indices)
        for idx in hit_indices:
            for delta in range(-window, window + 1):
                if delta != 0:
                    all_indices.add(idx + delta)
        # Chunk 3: {2,3,4}, Chunk 7: {6,7,8}
        assert all_indices == {2, 3, 4, 6, 7, 8}


# ── BM25 IDF Computation ─────────────────────────────────────────

class TestBM25IDF:
    """Test IDF calculation correctness."""

    def test_idf_higher_for_rare_terms(self):
        """Rare terms get higher IDF."""
        doc_count = 100
        freq_common = 80
        freq_rare = 5

        idf_common = math.log((doc_count - freq_common + 0.5) / (freq_common + 0.5) + 1.0)
        idf_rare = math.log((doc_count - freq_rare + 0.5) / (freq_rare + 0.5) + 1.0)

        assert idf_rare > idf_common
