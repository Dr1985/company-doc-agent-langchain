import asyncio
import importlib
import sys


def test_sitecustomize_sets_selector_policy_on_windows(monkeypatch):
    selector_policy_calls = []

    class FakeWindowsSelectorEventLoopPolicy:
        pass

    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", FakeWindowsSelectorEventLoopPolicy, raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: selector_policy_calls.append(policy))

    sys.modules.pop("sitecustomize", None)
    importlib.import_module("sitecustomize")

    assert len(selector_policy_calls) == 1
    assert isinstance(selector_policy_calls[0], FakeWindowsSelectorEventLoopPolicy)


def test_sitecustomize_does_not_override_non_windows_event_loops(monkeypatch):
    selector_policy_calls = []

    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: selector_policy_calls.append(policy))

    sys.modules.pop("sitecustomize", None)
    importlib.import_module("sitecustomize")

    assert selector_policy_calls == []


