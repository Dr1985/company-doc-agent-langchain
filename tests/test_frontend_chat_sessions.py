import re
from pathlib import Path


CHAT_HTML_PATH = Path(__file__).resolve().parents[1] / "frontend" / "chat.html"


def test_chat_frontend_caches_per_session_tokens_and_active_session_token():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert re.search(r"_token:\s*\(s\.token && s\.token\.access_token\)\s*\|\|\s*''", content)
    assert "const preferredSessionId = activeSessionId.value || getSessionId();" in content
    assert "const nextActiveSession = sessions.value.find(s => s.id === preferredSessionId) || sessions.value[0];" in content
    assert re.search(
        r"if \(nextActiveSession\._token\) \{\s*localStorage\.setItem\('session_token', nextActiveSession\._token\);",
        content,
        re.S,
    )
    assert re.search(
        r"if \(s && s\._token\) \{\s*localStorage\.setItem\('session_token', s\._token\);",
        content,
        re.S,
    )


def test_chat_frontend_uses_timestamp_based_default_session_names():
    content = CHAT_HTML_PATH.read_text(encoding="utf-8")

    assert "function formatSessionTimestamp(date = new Date())" in content
    assert "name: formatSessionTimestamp()" in content
    assert "name: resolveSessionName(data.name)" in content

