"""Pytest configuration and shared fixtures.

Provides:
- Environment isolation so tests don't connect to real databases.
- Shared mocks for heavy dependencies (DB, LLM, embedding).
"""

import os
import sys
from unittest.mock import MagicMock, patch

# ── MUST run at module level BEFORE any test file is imported ────
# Set test environment immediately
os.environ["APP_ENV"] = "test"

# Mock create_engine globally so DatabaseService.__init__ doesn't connect
mock_engine = MagicMock()
_sqlalchemy_patch = patch("sqlalchemy.create_engine", return_value=mock_engine)
_sqlalchemy_patch.start()
_sqlmodel_patch = patch("sqlmodel.create_engine", return_value=mock_engine)
_sqlmodel_patch.start()

# Clear cached settings so they reload with APP_ENV=test
for mod in list(sys.modules):
    if "config.settings" in mod or "system.logs" in mod:
        sys.modules.pop(mod, None)


def pytest_unconfigure(config):
    """Clean up after all tests."""
    _sqlalchemy_patch.stop()
    _sqlmodel_patch.stop()
