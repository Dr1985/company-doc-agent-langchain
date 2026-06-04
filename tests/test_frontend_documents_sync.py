from pathlib import Path


DOCUMENTS_HTML_PATH = Path(__file__).resolve().parents[1] / "frontend" / "documents.html"


def test_documents_frontend_exposes_minio_sync_action():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "@click=\"syncMinioDocuments\"" in content
    assert "const syncing = ref(false);" in content
    assert "const infoMsg = ref('');" in content
    assert "await apiCall('/documents/sync-minio', { method: 'POST' });" in content
    assert "同步 MinIO" in content


def test_documents_frontend_shows_sync_feedback_and_returns_bindings():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "<div v-if=\"infoMsg\"" in content
    assert "infoMsg.value" in content
    assert "loading, syncing, errorMsg, infoMsg," in content
    assert "fetchDocuments, syncMinioDocuments," in content


def test_documents_frontend_preview_requests_use_non_empty_query():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "文档预览" in content
    assert "body: JSON.stringify({ query:" in content
    assert "document_ids: [doc.id]" in content


def test_documents_frontend_has_upload_zone():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "upload-zone" in content
    assert "dragOver" in content
    assert "triggerUpload" in content
    assert "@drop.prevent=\"onDrop\"" in content
    assert "uploadQueue" in content
    assert "FormData" in content


def test_documents_frontend_has_file_validation():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert "ALLOWED_EXT" in content or ".pdf,.docx,.txt,.md" in content
    assert "MAX_SIZE" in content or "50 * 1024 * 1024" in content


def test_documents_frontend_has_dashboard_link():
    content = DOCUMENTS_HTML_PATH.read_text(encoding="utf-8")

    assert 'href="dashboard.html"' in content
