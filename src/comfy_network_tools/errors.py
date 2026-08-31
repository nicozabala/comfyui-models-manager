"""Typed domain exceptions.

Every error the domain layer raises on purpose is a subclass of :class:`CntError`,
so the UI can catch one type at screen boundaries and render it inline.
"""

from __future__ import annotations


class CntError(Exception):
    """Base class for all comfy-network-tools domain errors."""


# --- model repository ---------------------------------------------------------


class RepositoryNotConfigured(CntError):
    """A repository operation was requested before a repository root was set."""


class InvalidRepositoryPath(CntError):
    """A path offered as the repository root does not exist or is not a directory."""


# --- host registry -----------------------------------------------------------


class DuplicateHost(CntError):
    """A host with the same display name or address+port+user already exists."""


class HostValidationError(CntError):
    """A host record is missing a required field or has an invalid value."""


class ConnectivityError(CntError):
    """Connecting to or probing a host failed.

    ``reason`` is one of ``authentication``, ``unreachable``, ``timeout``,
    ``missing/inaccessible base path``, ``host-key-unknown``, ``host-key-changed``,
    or ``sftp-unavailable``. The exception message keeps the underlying detail
    (transport error text, offending fingerprint, ...).
    """

    #: Recognised failure categories.
    REASONS = (
        "authentication",
        "unreachable",
        "timeout",
        "missing/inaccessible base path",
        "host-key-unknown",
        "host-key-changed",
        "sftp-unavailable",
    )

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


# --- distribution ----------------------------------------------------------


class TransferError(CntError):
    """A model file transfer failed or was interrupted."""


# --- secrets ---------------------------------------------------------------


class SecretError(CntError):
    """A stored secret could not be encrypted or decrypted (missing/invalid key)."""


# --- hugging face --------------------------------------------------------------


class HuggingFaceAuthError(CntError):
    """The effective Hugging Face token is missing or was rejected."""


class HuggingFaceNotFound(CntError):
    """A referenced Hugging Face repo, revision, or file does not exist or is not accessible."""


class DownloadError(CntError):
    """A Hugging Face download failed for a reason other than auth or not-found."""
