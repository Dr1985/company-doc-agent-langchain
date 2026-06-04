"""Helpers for generating stable default chat session names."""

from datetime import datetime


SESSION_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_session_timestamp(created_at: datetime | None = None) -> str:
    """Format a datetime for use as a default session name."""
    moment = created_at or datetime.now().astimezone()
    return moment.strftime(SESSION_TIMESTAMP_FORMAT)


def resolve_session_name(name: str | None, created_at: datetime | None = None) -> str:
    """Return the explicit session name when present, otherwise a timestamp name."""
    if name is not None:
        stripped_name = name.strip()
        if stripped_name:
            return stripped_name
    return format_session_timestamp(created_at)

