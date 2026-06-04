from pathlib import Path


DOCUMENTS_HTML_PATH = Path(__file__).resolve().parents[1] / "frontend" / "documents.html"


def test_documents_frontend_exposes_minio_sync_action():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "@click=\"syncMinioDocuments\"" in content
    assert "const syncing = ref(false);" in content
    assert "const infoMsg = ref('');" in content
    assert "await apiCall('/documents/sync-minio', { method: 'POST' });" in content
    assert "{{ syncing ? '同步中...' : '同步 MinIO' }}" in content
    assert "if (data.removed_documents) messageParts.push(`移除失效 ${data.removed_documents} 个`);" in content


def test_documents_frontend_shows_sync_feedback_and_returns_bindings():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "<div v-if=\"infoMsg\"" in content
    assert "infoMsg.value = data.message || (messageParts.join('，') + '。');" in content
    assert "loading, syncing, errorMsg, infoMsg," in content
    assert "fetchDocuments, syncMinioDocuments," in content


def test_documents_frontend_preview_requests_use_non_empty_query():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "const previewQuery = (doc?.name || '文档预览').trim() || '文档预览';" in content
    assert "body: JSON.stringify({ query: previewQuery, top_k: 3, document_ids: [doc.id] })," in content


