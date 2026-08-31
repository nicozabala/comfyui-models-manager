"""The host registry: CRUD over remote machines plus connectivity checks.

A :class:`Host` never carries the stored password — only ``has_password``. The
ciphertext lives in the ``encrypted_password`` column and is reachable only
through :func:`resolve_password`, which the SSH layer calls at connect time.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from . import models_repo, secrets, storage
from .errors import ConnectivityError, DuplicateHost, HostValidationError, SecretError

AUTH_METHODS = ("agent", "key", "password")

_UNSET = object()

_ROW_COLUMNS = (
    "id",
    "name",
    "address",
    "port",
    "username",
    "auth_method",
    "private_key_path",
    "encrypted_password",
    "remote_base_path",
    "trust_host_key",
    "host_key",
    "last_check_at",
    "last_check_ok",
    "last_check_reason",
)


@dataclass(frozen=True)
class Host:
    id: int
    name: str
    address: str
    port: int
    username: str
    auth_method: str
    private_key_path: str | None
    has_password: bool
    remote_base_path: str
    trust_host_key: bool
    host_key: str | None
    last_check_at: str | None
    last_check_ok: bool | None
    last_check_reason: str | None

    @property
    def host_key_fingerprint(self) -> str | None:
        """SHA256 fingerprint of the pinned host key, or ``None`` if none is trusted."""
        from . import ssh  # noqa: PLC0415 - keep paramiko out of module import

        return ssh.fingerprint_of_line(self.host_key)


@dataclass(frozen=True)
class ConnectivityResult:
    ok: bool
    reason: str | None
    detail: str | None
    checked_at: str


ConnectFn = Callable[[Host], object]  # returns a ssh.RemoteFS


# --- helpers -------------------------------------------------------------


def _to_host(row: sqlite3.Row) -> Host:
    return Host(
        id=row["id"],
        name=row["name"],
        address=row["address"],
        port=row["port"],
        username=row["username"],
        auth_method=row["auth_method"],
        private_key_path=row["private_key_path"],
        has_password=row["encrypted_password"] is not None,
        remote_base_path=row["remote_base_path"],
        trust_host_key=bool(row["trust_host_key"]),
        host_key=row["host_key"],
        last_check_at=row["last_check_at"],
        last_check_ok=None if row["last_check_ok"] is None else bool(row["last_check_ok"]),
        last_check_reason=row["last_check_reason"],
    )


def _row(conn: sqlite3.Connection, host_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {', '.join(_ROW_COLUMNS)} FROM hosts WHERE id = ?", (host_id,)
    ).fetchone()


def _require_row(conn: sqlite3.Connection, host_id: int) -> sqlite3.Row:
    row = _row(conn, host_id)
    if row is None:
        raise HostValidationError(f"no host with id {host_id}")
    return row


def _clean_required(value: str | None, field: str) -> str:
    if value is None or not str(value).strip():
        raise HostValidationError(f"missing required field: {field}")
    return str(value).strip()


def _validate_auth(auth_method: str, private_key_path: str | None) -> None:
    if auth_method not in AUTH_METHODS:
        raise HostValidationError(f"unknown auth method: {auth_method}")
    if auth_method == "key" and not (private_key_path and private_key_path.strip()):
        raise HostValidationError("key authentication requires a private key path")


def _reject_duplicates(
    conn: sqlite3.Connection,
    *,
    name: str,
    address: str,
    port: int,
    username: str,
    exclude_id: int | None = None,
) -> None:
    clause = "id != ?" if exclude_id is not None else "1 = 1"
    args: list[object] = [exclude_id] if exclude_id is not None else []
    if conn.execute(
        f"SELECT 1 FROM hosts WHERE {clause} AND name = ?", (*args, name)
    ).fetchone():
        raise DuplicateHost(f"a host named {name!r} already exists")
    if conn.execute(
        f"SELECT 1 FROM hosts WHERE {clause} AND address = ? AND port = ? AND username = ?",
        (*args, address, port, username),
    ).fetchone():
        raise DuplicateHost(f"a host for {username}@{address}:{port} already exists")


# --- CRUD --------------------------------------------------------------


def add_host(
    *,
    name: str,
    address: str,
    username: str,
    remote_base_path: str,
    port: int = 22,
    auth_method: str = "agent",
    private_key_path: str | None = None,
    password: str | None = None,
    trust_host_key: bool = False,
) -> Host:
    name = _clean_required(name, "name")
    address = _clean_required(address, "address")
    username = _clean_required(username, "username")
    remote_base_path = _clean_required(remote_base_path, "remote_base_path")
    _validate_auth(auth_method, private_key_path)

    conn = storage.get_db()
    _reject_duplicates(conn, name=name, address=address, port=port, username=username)

    encrypted = (
        secrets.encrypt(password) if auth_method == "password" and password else None
    )
    cursor = conn.execute(
        "INSERT INTO hosts (name, address, port, username, auth_method, private_key_path, "
        "encrypted_password, remote_base_path, trust_host_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            address,
            port,
            username,
            auth_method,
            (private_key_path or None),
            encrypted,
            remote_base_path,
            int(bool(trust_host_key)),
        ),
    )
    conn.commit()
    return _to_host(_require_row(conn, cursor.lastrowid))


def edit_host(host_id: int, *, password: object = _UNSET, **fields: object) -> Host:
    """Update any host field. ``password`` is separate: a non-empty string re-encrypts,
    a blank string or the default keeps the stored one, and switching ``auth_method``
    away from ``password`` clears it."""
    conn = storage.get_db()
    row = _require_row(conn, host_id)

    merged = {col: row[col] for col in _ROW_COLUMNS}
    unknown = set(fields) - set(_ROW_COLUMNS) - {"trust_host_key"}
    if unknown:
        raise HostValidationError(f"unknown field(s): {sorted(unknown)}")
    merged.update(fields)

    name = _clean_required(merged["name"], "name")
    address = _clean_required(merged["address"], "address")
    username = _clean_required(merged["username"], "username")
    remote_base_path = _clean_required(merged["remote_base_path"], "remote_base_path")
    auth_method = str(merged["auth_method"])
    private_key_path = merged["private_key_path"] or None
    _validate_auth(auth_method, private_key_path)
    port = int(merged["port"])
    _reject_duplicates(
        conn, name=name, address=address, port=port, username=username, exclude_id=host_id
    )

    encrypted = row["encrypted_password"]
    if auth_method != "password":
        encrypted = None
    elif password is not _UNSET and str(password):
        encrypted = secrets.encrypt(str(password))

    # a pinned host key belongs to a specific address:port — drop it if either changed
    host_key = row["host_key"]
    if address != row["address"] or port != row["port"]:
        host_key = None

    conn.execute(
        "UPDATE hosts SET name = ?, address = ?, port = ?, username = ?, auth_method = ?, "
        "private_key_path = ?, encrypted_password = ?, remote_base_path = ?, trust_host_key = ?, "
        "host_key = ? WHERE id = ?",
        (
            name,
            address,
            port,
            username,
            auth_method,
            private_key_path,
            encrypted,
            remote_base_path,
            int(bool(merged["trust_host_key"])),
            host_key,
            host_id,
        ),
    )
    conn.commit()
    return _to_host(_require_row(conn, host_id))


def remove_host(host_id: int) -> None:
    conn = storage.get_db()
    conn.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
    conn.commit()
    # placements cascade; a host-only model may now be orphaned.
    models_repo.prune_orphan_host_models()


def list_hosts() -> list[Host]:
    conn = storage.get_db()
    return [
        _to_host(row)
        for row in conn.execute(
            f"SELECT {', '.join(_ROW_COLUMNS)} FROM hosts ORDER BY name"
        )
    ]


def get_host(host_id: int) -> Host | None:
    row = _row(storage.get_db(), host_id)
    return None if row is None else _to_host(row)


# --- secrets & connectivity -----------------------------------------------


def resolve_password(host_id: int) -> str:
    """Decrypt the stored SSH password, or raise :class:`SecretError` if unavailable."""
    row = _require_row(storage.get_db(), host_id)
    if not row["encrypted_password"]:
        raise SecretError("no password is stored for this host")
    return secrets.decrypt(row["encrypted_password"])


def _pin_host_key(host_id: int, key_line: str) -> None:
    conn = storage.get_db()
    conn.execute(
        "UPDATE hosts SET host_key = ? WHERE id = ? AND host_key IS NULL",
        (key_line, host_id),
    )
    conn.commit()


def open_connection(
    host: Host,
    *,
    prompt_password: object = None,
    host_key_prompt: object = None,
) -> object:
    """Open an SSH/SFTP session to ``host``; pin its host key on first successful use."""
    from . import ssh  # noqa: PLC0415 - imported lazily to keep the module graph flat

    remote = ssh.connect(
        host,
        password_resolver=resolve_password,
        prompt_password=prompt_password,
        host_key_prompt=host_key_prompt,
    )
    if not host.host_key and getattr(remote, "server_key_line", None):
        _pin_host_key(host.id, remote.server_key_line)
    return remote


def test_connectivity(
    host_id: int,
    *,
    connect: ConnectFn | None = None,
    host_key_prompt: object = None,
) -> ConnectivityResult:
    """Open a session, confirm the remote base path is a directory, and record the result."""
    if connect is None:
        def connect(h: Host) -> object:
            return open_connection(h, host_key_prompt=host_key_prompt)

    conn = storage.get_db()
    host = get_host(host_id)
    if host is None:
        raise HostValidationError(f"no host with id {host_id}")

    ok = False
    reason: str | None = None
    detail: str | None = None
    try:
        remote = connect(host)
        try:
            info = remote.stat(host.remote_base_path)
            if info is None or not info.is_dir:
                reason = "missing/inaccessible base path"
            else:
                ok = True
        finally:
            remote.close()
    except ConnectivityError as exc:
        reason = exc.reason
        text = str(exc)
        detail = text if text != exc.reason else None
    except SecretError as exc:
        reason = "authentication"
        detail = str(exc)

    stored_reason = f"{reason}: {detail}" if reason and detail else reason
    checked_at = storage.utcnow_iso()
    conn.execute(
        "UPDATE hosts SET last_check_at = ?, last_check_ok = ?, last_check_reason = ? WHERE id = ?",
        (checked_at, int(ok), stored_reason, host_id),
    )
    conn.commit()
    return ConnectivityResult(ok=ok, reason=reason, detail=detail, checked_at=checked_at)
