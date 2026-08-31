"""Remote filesystem access over SSH/SFTP.

`RemoteFS` is the small interface the rest of the app depends on; `ParamikoRemoteFS`
is the real implementation and `InMemoryRemoteFS` is the test double. All remote
paths are POSIX and must be built with :mod:`posixpath`, never :mod:`os.path`.
"""

from __future__ import annotations

import base64
import hashlib
import posixpath
import stat as stat_module
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import paramiko

from .errors import ConnectivityError, SecretError, TransferError

if TYPE_CHECKING:
    from .hosts import Host

#: Resolves a host's stored password by id; raises SecretError when unavailable.
PasswordResolver = Callable[[int], str]
#: Interactively prompts for a host's password (used when no stored one is usable).
PasswordPrompt = Callable[["Host"], str]
#: Asked ``(host, sha256_fingerprint)`` to trust an unknown host key; returns a bool.
HostKeyPrompt = Callable[["Host", str], bool]

#: Called with ``(bytes_transferred, total_bytes)`` during a transfer.
ProgressCallback = Callable[[int, int], None]

#: Suffix for the in-progress upload before it is renamed into place.
PART_SUFFIX = ".cnt-part"


@dataclass(frozen=True)
class RemoteStat:
    is_dir: bool
    size: int


class RemoteFS(ABC):
    """Minimal remote filesystem operations used by hosts/distribution."""

    @abstractmethod
    def listdir(self, path: str) -> list[str]:
        """Names of the entries directly under ``path`` (empty list if it is missing)."""

    @abstractmethod
    def stat(self, path: str) -> RemoteStat | None:
        """Stat ``path``, or ``None`` if it does not exist."""

    @abstractmethod
    def makedirs(self, path: str) -> None:
        """Create ``path`` and any missing parents (``mkdir -p``)."""

    @abstractmethod
    def put(
        self, local_path: str | Path, remote_path: str, *, progress: ProgressCallback | None = None
    ) -> None:
        """Upload a local file to ``remote_path`` (no atomicity — see :func:`upload_atomic`)."""

    @abstractmethod
    def remove(self, path: str) -> None:
        """Delete a remote file (no error if already gone)."""

    @abstractmethod
    def rename(self, src: str, dst: str) -> None:
        """Rename ``src`` to ``dst``, replacing ``dst`` if it exists."""

    #: Set by :func:`connect` to the key line the server presented (``"<type> <b64>"``).
    server_key_line: str | None = None

    def close(self) -> None:  # noqa: B027 - optional hook, no-op by default
        pass


def upload_atomic(
    fs: RemoteFS,
    local_path: str | Path,
    remote_path: str,
    *,
    progress: ProgressCallback | None = None,
) -> None:
    """Upload to ``<remote_path>.cnt-part`` then rename into place.

    On any failure the partial file is removed and the exception propagates as a
    :class:`TransferError`; no file appears at ``remote_path``.
    """
    part_path = remote_path + PART_SUFFIX
    try:
        fs.put(local_path, part_path, progress=progress)
        fs.rename(part_path, remote_path)
    except TransferError:
        _safe_remove(fs, part_path)
        raise
    except Exception as exc:  # noqa: BLE001 - normalise any transport error
        _safe_remove(fs, part_path)
        raise TransferError(f"transfer of {remote_path} failed: {exc}") from exc


def _safe_remove(fs: RemoteFS, path: str) -> None:
    try:
        fs.remove(path)
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass


class InMemoryRemoteFS(RemoteFS):
    """A fake remote filesystem for tests. Seed it via :meth:`add_dir` / :meth:`add_file`."""

    def __init__(self) -> None:
        self._dirs: set[str] = {"/"}
        self._files: dict[str, int] = {}
        #: If set, the next matching :meth:`put` reports partial progress then raises it.
        self.put_failure: Exception | None = None
        self.fail_paths: set[str] = set()

    # -- seeding helpers --

    def add_dir(self, path: str) -> None:
        self.makedirs(path)

    def add_file(self, path: str, size: int) -> None:
        self.makedirs(posixpath.dirname(path))
        self._files[posixpath.normpath(path)] = size

    # -- RemoteFS --

    def listdir(self, path: str) -> list[str]:
        path = posixpath.normpath(path)
        if path not in self._dirs:
            return []
        names: set[str] = set()
        prefix = path.rstrip("/") + "/"
        for known in (*self._dirs, *self._files):
            if known != path and known.startswith(prefix):
                rest = known[len(prefix) :]
                if "/" not in rest:
                    names.add(rest)
        return sorted(names)

    def stat(self, path: str) -> RemoteStat | None:
        path = posixpath.normpath(path)
        if path in self._dirs:
            return RemoteStat(is_dir=True, size=0)
        if path in self._files:
            return RemoteStat(is_dir=False, size=self._files[path])
        return None

    def makedirs(self, path: str) -> None:
        path = posixpath.normpath(path)
        parts = path.strip("/").split("/")
        current = ""
        for part in parts:
            current = current + "/" + part
            self._dirs.add(posixpath.normpath(current))

    def put(
        self, local_path: str | Path, remote_path: str, *, progress: ProgressCallback | None = None
    ) -> None:
        total = Path(local_path).stat().st_size
        remote_path = posixpath.normpath(remote_path)
        if posixpath.dirname(remote_path) not in self._dirs:
            raise TransferError(f"remote directory missing for {remote_path}")
        if self.put_failure is not None or remote_path in self.fail_paths:
            if progress is not None:
                progress(total // 2, total)
            failure = self.put_failure or TransferError("simulated transfer failure")
            self.put_failure = None
            raise failure
        if progress is not None:
            for done in (0, total // 2, total):
                progress(done, total)
        self._files[remote_path] = total

    def remove(self, path: str) -> None:
        self._files.pop(posixpath.normpath(path), None)

    def rename(self, src: str, dst: str) -> None:
        src, dst = posixpath.normpath(src), posixpath.normpath(dst)
        if src not in self._files:
            raise TransferError(f"cannot rename missing file {src}")
        self._files[dst] = self._files.pop(src)


# --- real implementation -------------------------------------------------


def fingerprint(key: paramiko.PKey) -> str:
    """OpenSSH-style ``SHA256:...`` fingerprint of a host key."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def key_line(key: paramiko.PKey) -> str:
    """The ``known_hosts``-style ``"<type> <base64>"`` line for a key."""
    return f"{key.get_name()} {key.get_base64()}"


def fingerprint_of_line(line: str | None) -> str | None:
    """Fingerprint of a stored key line, or ``None`` if the line is empty/unparseable."""
    if not line:
        return None
    try:
        return fingerprint(paramiko.hostkeys.HostKeyEntry.from_line(f"* {line.strip()}").key)
    except Exception:  # noqa: BLE001 - a corrupt pin should not crash the host list
        return None


def _parse_key_line(line: str) -> paramiko.PKey:
    return paramiko.hostkeys.HostKeyEntry.from_line(f"* {line.strip()}").key


class _HostKeyDeclined(paramiko.SSHException):
    """Raised inside the missing-host-key policy when the user declines the fingerprint."""


class _TofuPolicy(paramiko.MissingHostKeyPolicy):
    """Trust-on-first-use: ask (or auto-accept) an unknown host key, else decline."""

    def __init__(self, host: Host, prompt: HostKeyPrompt | None) -> None:
        self._host = host
        self._prompt = prompt
        self.accepted_key: paramiko.PKey | None = None

    def missing_host_key(self, client, hostname, key) -> None:
        trusted = self._host.trust_host_key or (
            self._prompt is not None and self._prompt(self._host, fingerprint(key))
        )
        if not trusted:
            raise _HostKeyDeclined(fingerprint(key))
        self.accepted_key = key
        client.get_host_keys().add(hostname, key.get_name(), key)


def build_auth_kwargs(
    host: Host,
    *,
    password_resolver: PasswordResolver | None = None,
    prompt_password: PasswordPrompt | None = None,
) -> dict[str, object]:
    """Translate a host's ``auth_method`` into ``SSHClient.connect`` keyword args.

    For password auth: try the stored password, then fall back to ``prompt_password``
    if the stored one is missing/undecryptable.
    """
    if host.auth_method == "agent":
        return {"allow_agent": True, "look_for_keys": True}
    if host.auth_method == "key":
        return {
            "key_filename": host.private_key_path,
            "allow_agent": False,
            "look_for_keys": False,
        }
    if host.auth_method == "password":
        password: str | None = None
        if password_resolver is not None:
            try:
                password = password_resolver(host.id)
            except SecretError:
                password = None
        if not password and prompt_password is not None:
            password = prompt_password(host)
        if not password:
            raise ConnectivityError("authentication", "no password available for host")
        return {"password": password, "allow_agent": False, "look_for_keys": False}
    raise ConnectivityError("authentication", f"unknown auth method {host.auth_method!r}")


def connect(
    host: Host,
    *,
    password_resolver: PasswordResolver | None = None,
    prompt_password: PasswordPrompt | None = None,
    host_key_prompt: HostKeyPrompt | None = None,
    timeout: float = 15.0,
) -> ParamikoRemoteFS:
    """Open an SSH+SFTP session to ``host``. Raises :class:`ConnectivityError` on failure.

    Host key handling (trust on first use): if ``host.host_key`` is pinned it is the
    only key accepted (a change → ``host-key-changed``); otherwise ``host_key_prompt``
    is asked to trust the presented key (decline / no prompt → ``host-key-unknown``).
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()

    if host.host_key:
        pinned = _parse_key_line(host.host_key)
        for name in (host.address, f"[{host.address}]:{host.port}"):
            client.get_host_keys().add(name, pinned.get_name(), pinned)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(_TofuPolicy(host, host_key_prompt))

    try:
        client.connect(
            hostname=host.address,
            port=host.port,
            username=host.username,
            timeout=timeout,
            **build_auth_kwargs(
                host, password_resolver=password_resolver, prompt_password=prompt_password
            ),
        )
    except paramiko.BadHostKeyException as exc:
        raise ConnectivityError(
            "host-key-changed",
            f"{fingerprint(exc.key)} presented, expected {fingerprint(exc.expected_key)}",
        ) from exc
    except _HostKeyDeclined as exc:
        raise ConnectivityError("host-key-unknown", f"host key {exc} was not trusted") from exc
    except paramiko.AuthenticationException as exc:
        raise ConnectivityError("authentication", str(exc)) from exc
    except TimeoutError as exc:
        raise ConnectivityError("timeout", str(exc)) from exc
    except (paramiko.SSHException, OSError) as exc:
        raise ConnectivityError("unreachable", str(exc)) from exc

    try:
        sftp = client.open_sftp()
    except (paramiko.SSHException, OSError) as exc:
        client.close()
        raise ConnectivityError("sftp-unavailable", str(exc)) from exc

    remote = ParamikoRemoteFS(client, sftp)
    server_key = client.get_transport().get_remote_server_key()
    remote.server_key_line = key_line(server_key)
    return remote


class ParamikoRemoteFS(RemoteFS):
    def __init__(self, client: paramiko.SSHClient, sftp: paramiko.SFTPClient) -> None:
        self._client = client
        self._sftp = sftp
        self.server_key_line: str | None = None

    def listdir(self, path: str) -> list[str]:
        try:
            return sorted(self._sftp.listdir(path))
        except FileNotFoundError:
            return []

    def stat(self, path: str) -> RemoteStat | None:
        try:
            info = self._sftp.stat(path)
        except FileNotFoundError:
            return None
        mode = info.st_mode or 0
        return RemoteStat(is_dir=stat_module.S_ISDIR(mode), size=info.st_size or 0)

    def makedirs(self, path: str) -> None:
        segments = [seg for seg in path.split("/") if seg]
        current = "/" if path.startswith("/") else ""
        for segment in segments:
            current = posixpath.join(current, segment) if current else segment
            info = self.stat(current)
            if info is None:
                self._sftp.mkdir(current)
            elif not info.is_dir:
                raise TransferError(f"{current} exists and is not a directory")

    def put(
        self, local_path: str | Path, remote_path: str, *, progress: ProgressCallback | None = None
    ) -> None:
        callback = (lambda done, total: progress(done, total)) if progress else None
        try:
            self._sftp.put(str(local_path), remote_path, callback=callback)
        except OSError as exc:
            raise TransferError(f"upload to {remote_path} failed: {exc}") from exc

    def remove(self, path: str) -> None:
        try:
            self._sftp.remove(path)
        except FileNotFoundError:
            pass

    def rename(self, src: str, dst: str) -> None:
        # posix_rename (atomic replace) where the server supports it; plain rename otherwise.
        try:
            self._sftp.posix_rename(src, dst)
        except OSError:
            self._sftp.rename(src, dst)

    def close(self) -> None:
        try:
            self._sftp.close()
        finally:
            self._client.close()
