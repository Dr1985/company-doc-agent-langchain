import re
from pathlib import Path


CHAT_HTML_PATH = Path(__file__).resolve().parents[1] / "frontend" / "chat.html"


def test_chat_frontend_caches_per_session_tokens_and_active_session_token():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert re.search(r"_token:\s*\(s\.token && s\.token\.access_token\)\s*\|\|\s*''", content)
    assert "const preferred = activeSessionId.value || getSessionId();" in content
    assert "const next = sessions.value.find(s => s.id === preferred) || sessions.value[0];" in content
    assert re.search(
        r"if \(next\._token\)\s+localStorage\.setItem\('session_token', next\._token\);",
        content,
    )
    assert re.search(
        r"if \(s && s\._token\)\s+localStorage\.setItem\('session_token', s\._token\);",
        content,
    )


def test_chat_frontend_uses_timestamp_based_default_session_names():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert "function formatSessionTimestamp(date = new Date())" in content
    assert "name: formatSessionTimestamp()" in content
    assert "name: resolveSessionName(data.name)" in content


def test_chat_frontend_has_model_selector():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert "selectedModel" in content
    assert "availableModels" in content
    assert "model-select" in content
    assert "localStorage.getItem('selected_model')" in content


def test_chat_frontend_has_message_actions():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert "copyMessage" in content
    assert "feedbackMessage" in content
    assert "navigator.clipboard.writeText" in content


def test_chat_frontend_has_session_rename():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert "startRename" in content
    assert "commitRename" in content
    assert "editingSessionId" in content


def test_chat_frontend_has_dashboard_link():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert 'href="dashboard.html"' in content
