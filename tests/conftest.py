"""Shared pytest fixtures for comfy-network-tools tests."""

from __future__ import annotations

import pytest

from comfy_network_tools import storage
from comfy_network_tools.ui.prompts import Prompter

USE_DEFAULT = object()


class ScriptedPrompter(Prompter):
    """A Prompter that replays a fixed list of answers and records what it was asked."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.calls: list[tuple[str, str]] = []
        #: The `checked` kwarg seen on each `checkbox()` call, in order.
        self.checked_seen: list[set[object] | None] = []

    def _next(self, kind: str, message: str):
        self.calls.append((kind, message))
        if not self._answers:
            raise AssertionError(f"ScriptedPrompter ran out of answers at {kind}: {message!r}")
        return self._answers.pop(0)

    def select(self, message, options):
        return self._next("select", message)

    def checkbox(self, message, options, *, checked=None):
        self.checked_seen.append(checked)
        return self._next("checkbox", message)

    def text(self, message, *, default=""):
        value = self._next("text", message)
        return default if value is USE_DEFAULT else value

    def password(self, message):
        return self._next("password", message)

    def confirm(self, message, *, default=False):
        return self._next("confirm", message)


@pytest.fixture(autouse=True)
def isolated_app_dirs(tmp_path, monkeypatch):
    """Redirect the app data/config dirs to a temp location and clear HF env vars.

    Autouse so no test can read or write the real user profile directories.
    """
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("CNT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CNT_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    storage.reset_cache()
    yield tmp_path
    storage.reset_cache()


@pytest.fixture
def db(isolated_app_dirs):
    """A fresh state database connection for the test."""
    return storage.get_db()


@pytest.fixture
def make_prompter():
    return ScriptedPrompter


@pytest.fixture
def console():
    from rich.console import Console

    return Console(record=True, width=200)
