"""Filesystem locations and Hugging Face token resolution.

Directory locations come from :mod:`platformdirs`, but both roots can be
redirected with an environment variable so tests (and power users) never touch
the real profile directories:

* ``CNT_DATA_DIR``   -> holds ``state.db`` and ``secret.key``
* ``CNT_CONFIG_DIR`` -> holds ``hf_token``
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

APP_NAME = "comfy-network-tools"

_DATA_DIR_ENV = "CNT_DATA_DIR"
_CONFIG_DIR_ENV = "CNT_CONFIG_DIR"

#: Hugging Face token environment variables, in precedence order.
HF_TOKEN_ENV_VARS: tuple[str, ...] = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")


def data_dir() -> Path:
    """Return the app data directory, creating it if needed."""
    override = os.environ.get(_DATA_DIR_ENV)
    base = Path(override) if override else Path(platformdirs.user_data_dir(APP_NAME))
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_dir() -> Path:
    """Return the app config directory, creating it if needed."""
    override = os.environ.get(_CONFIG_DIR_ENV)
    base = Path(override) if override else Path(platformdirs.user_config_dir(APP_NAME))
    base.mkdir(parents=True, exist_ok=True)
    return base


def state_db_path() -> Path:
    return data_dir() / "state.db"


def secret_key_path() -> Path:
    return data_dir() / "secret.key"


def hf_token_path() -> Path:
    return config_dir() / "hf_token"


def restrict_permissions(path: Path) -> None:
    """Best-effort ``chmod 600`` on a secret-bearing file (no-op where unsupported)."""
    try:
        path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass


def write_hf_token(token: str) -> Path:
    """Persist the Hugging Face token to its file with owner-only permissions."""
    path = hf_token_path()
    path.write_text(token.strip() + "\n", encoding="utf-8")
    restrict_permissions(path)
    return path


def mask_token(token: str) -> str:
    """Return a display-safe preview that never contains the whole token."""
    token = token.strip()
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:3]}...{token[-4:]}"


def stored_hf_token() -> str | None:
    """Return the token written to the token file, or ``None`` if unset/empty."""
    path = hf_token_path()
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def effective_hf_token() -> tuple[str | None, str]:
    """Resolve the token to use for Hugging Face requests.

    Returns ``(token, source)``. ``source`` is ``"env:HF_TOKEN"``,
    ``"env:HUGGING_FACE_HUB_TOKEN"``, ``"file"``, or ``"none"``.
    """
    for env in HF_TOKEN_ENV_VARS:
        value = os.environ.get(env)
        if value and value.strip():
            return value.strip(), f"env:{env}"
    token = stored_hf_token()
    if token:
        return token, "file"
    return None, "none"
