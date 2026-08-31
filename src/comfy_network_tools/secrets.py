"""Symmetric encryption for secrets stored in the database (SSH passwords).

A single Fernet key lives at :func:`config.secret_key_path`, separate from
``state.db``. It is generated lazily the first time something is encrypted; if it
is missing or unreadable when decrypting, :class:`SecretError` is raised so the
caller can fall back to prompting.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from . import config
from .errors import SecretError


def key_exists() -> bool:
    return config.secret_key_path().is_file()


def _load_key(*, create: bool) -> bytes:
    path = config.secret_key_path()
    if path.is_file():
        return path.read_bytes().strip()
    if not create:
        raise SecretError(f"encryption key file is missing: {path}")
    key = Fernet.generate_key()
    path.write_bytes(key)
    config.restrict_permissions(path)
    return key


def _fernet(*, create: bool) -> Fernet:
    try:
        return Fernet(_load_key(create=create))
    except ValueError as exc:  # malformed key material
        raise SecretError("encryption key is invalid") from exc


def encrypt(plaintext: str) -> str:
    """Encrypt a string, creating the key file on first use. Returns ciphertext text."""
    return _fernet(create=True).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt ciphertext produced by :func:`encrypt`.

    Raises :class:`SecretError` if the key file is missing or the token is invalid.
    """
    try:
        return _fernet(create=False).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretError("stored secret could not be decrypted") from exc
