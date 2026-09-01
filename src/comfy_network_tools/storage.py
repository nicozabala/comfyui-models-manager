"""SQLite persistence: connection handling, schema, and settings accessors.

The database file lives at :func:`config.state_db_path`. Domain modules call
:func:`get_db` for the shared connection; tests point ``CNT_DATA_DIR`` at a temp
directory (see the autouse fixture) and call :func:`reset_cache` between cases.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from . import config

SCHEMA_VERSION = 1

#: Default ComfyUI-style model categories, seeded into ``settings`` on first run.
DEFAULT_CATEGORIES: list[str] = [
    "checkpoints",
    "loras",
    "vae",
    "controlnet",
    "clip",
    "clip_vision",
    "unet",
    "diffusion_models",
    "upscale_models",
    "embeddings",
    "hypernetworks",
    "style_models",
    "detection",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hosts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT    NOT NULL UNIQUE,
    address            TEXT    NOT NULL,
    port               INTEGER NOT NULL DEFAULT 22,
    username           TEXT    NOT NULL,
    auth_method        TEXT    NOT NULL DEFAULT 'agent',
    private_key_path   TEXT,
    encrypted_password TEXT,
    remote_base_path   TEXT    NOT NULL,
    trust_host_key     INTEGER NOT NULL DEFAULT 0,
    host_key           TEXT,
    last_check_at      TEXT,
    last_check_ok      INTEGER,
    last_check_reason  TEXT,
    UNIQUE (address, port, username)
);

CREATE TABLE IF NOT EXISTS models (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT    NOT NULL,
    filename   TEXT    NOT NULL,
    size_bytes INTEGER NOT NULL,
    indexed_at TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT 'local',
    UNIQUE (category, filename)
);

CREATE TABLE IF NOT EXISTS placements (
    model_id   INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    host_id    INTEGER NOT NULL REFERENCES hosts(id)  ON DELETE CASCADE,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (model_id, host_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_REPO_ROOT_KEY = "repo_root"
_CATEGORIES_KEY = "categories"
_SCHEMA_VERSION_KEY = "schema_version"
_CLEAN_TERMINAL_KEY = "clean_terminal"

_connections: dict[str, sqlite3.Connection] = {}


def utcnow_iso() -> str:
    """A timezone-aware UTC timestamp, second precision, for stored ``*_at`` columns."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign keys enabled and the schema applied."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_schema(conn)
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _add_missing_columns(conn, "hosts", {"host_key": "TEXT"})
    if _raw_setting(conn, _SCHEMA_VERSION_KEY) is None:
        _write_setting(conn, _SCHEMA_VERSION_KEY, str(SCHEMA_VERSION))
    if _raw_setting(conn, _CATEGORIES_KEY) is None:
        _write_setting(conn, _CATEGORIES_KEY, json.dumps(DEFAULT_CATEGORIES))
    conn.commit()


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Backfill columns added to ``table`` after a database was first created.

    ``CREATE TABLE IF NOT EXISTS`` leaves pre-existing tables untouched, so a
    state.db from an earlier version of the schema won't pick up new columns
    on its own.
    """
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def get_db() -> sqlite3.Connection:
    """Return the shared connection for the configured state database."""
    key = str(config.state_db_path())
    conn = _connections.get(key)
    if conn is None:
        conn = connect(key)
        _connections[key] = conn
    return conn


def reset_cache() -> None:
    """Close and forget every cached connection (used between tests)."""
    for conn in _connections.values():
        conn.close()
    _connections.clear()


# --- settings ----------------------------------------------------------------


def _raw_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _write_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    return _raw_setting(conn, key)


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    _write_setting(conn, key, value)
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    raw = _raw_setting(conn, _SCHEMA_VERSION_KEY)
    return int(raw) if raw is not None else 0


def get_repo_root(conn: sqlite3.Connection) -> str | None:
    return _raw_setting(conn, _REPO_ROOT_KEY)


def set_repo_root(conn: sqlite3.Connection, path: str) -> None:
    set_setting(conn, _REPO_ROOT_KEY, path)


def get_categories(conn: sqlite3.Connection) -> list[str]:
    raw = _raw_setting(conn, _CATEGORIES_KEY)
    if raw is None:
        return list(DEFAULT_CATEGORIES)
    return list(json.loads(raw))


def set_categories(conn: sqlite3.Connection, categories: list[str]) -> None:
    cleaned = [c.strip() for c in categories if c.strip()]
    set_setting(conn, _CATEGORIES_KEY, json.dumps(cleaned))


def get_clean_terminal(conn: sqlite3.Connection) -> bool:
    return _raw_setting(conn, _CLEAN_TERMINAL_KEY) == "1"


def set_clean_terminal(conn: sqlite3.Connection, value: bool) -> None:
    set_setting(conn, _CLEAN_TERMINAL_KEY, "1" if value else "0")
