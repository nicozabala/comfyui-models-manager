"""Guard: remote-path modules must not use os.path (POSIX-only paths -> posixpath)."""

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "src" / "comfy_network_tools"
GUARDED = ("ssh.py", "distribution.py")


def uses_os_path(source: str) -> bool:
    """True if the code actually *uses* os.path (prose mentions in docstrings are fine)."""
    return bool(re.search(r"\bos\.path\.", source)) or any(
        marker in source
        for marker in ("import os.path", "from os.path import", "from os import path")
    )


@pytest.mark.parametrize("name", GUARDED)
def test_guarded_module_does_not_use_os_path(name):
    assert not uses_os_path((PKG / name).read_text(encoding="utf-8"))


def test_guard_would_catch_a_violation():
    assert uses_os_path("import os\nx = os.path.join('a', 'b')\n")
    assert uses_os_path("from os.path import join\n")
    assert not uses_os_path("import posixpath\nx = posixpath.join('a', 'b')\n")
    assert not uses_os_path('"""build with posixpath, never :mod:`os.path`."""\n')
