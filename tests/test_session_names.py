from datetime import UTC, datetime

from src.utils.session_names import format_session_timestamp, resolve_session_name


def test_resolve_session_name_preserves_explicit_name():
    assert resolve_session_name("  研发答疑  ") == "研发答疑"


def test_resolve_session_name_falls_back_to_created_at_timestamp():
    created_at = datetime(2026, 6, 4, 12, 34, 56, tzinfo=UTC)

    assert resolve_session_name("", created_at) == "2026-06-04 12:34:56"


def test_format_session_timestamp_uses_expected_default_format():
    created_at = datetime(2026, 6, 4, 1, 2, 3)

    assert format_session_timestamp(created_at) == "2026-06-04 01:02:03"

