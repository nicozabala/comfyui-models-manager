"""The central model repository: locate it, scan it, and keep the index in sync.

A model's identity is ``(category, filename, size_bytes)`` — no content hashing.
``filename`` is the direct name of a file inside a category directory; nested
subdirectories inside a category are not scanned.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import storage
from .errors import InvalidRepositoryPath, RepositoryNotConfigured


@dataclass(frozen=True)
class Model:
    id: int
    category: str
    filename: str
    size_bytes: int
    indexed_at: str
    source: str


@dataclass(frozen=True)
class ScannedFile:
    category: str
    filename: str
    size_bytes: int


@dataclass(frozen=True)
class IndexChanges:
    added: list[tuple[str, str]]
    removed: list[tuple[str, str]]
    updated: list[tuple[str, str]]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.updated)


# --- configuration ---------------------------------------------------------


def is_configured() -> bool:
    return bool(storage.get_repo_root(storage.get_db()))


def set_repo_root(path: str | Path) -> Path:
    """Validate and persist the repository root. Raises :class:`InvalidRepositoryPath`."""
    candidate = Path(path).expanduser()
    if not candidate.exists() or not candidate.is_dir():
        raise InvalidRepositoryPath(f"not an existing directory: {candidate}")
    resolved = candidate.resolve()
    storage.set_repo_root(storage.get_db(), str(resolved))
    return resolved


def repo_root() -> Path:
    raw = storage.get_repo_root(storage.get_db())
    if not raw:
        raise RepositoryNotConfigured("the model repository must be configured first")
    return Path(raw)


def categories() -> list[str]:
    return storage.get_categories(storage.get_db())


# --- scanning & indexing --------------------------------------------------


def scan_repo() -> list[ScannedFile]:
    """List model files directly inside each known category directory."""
    root = repo_root()
    found: list[ScannedFile] = []
    for category in categories():
        category_dir = root / category
        if not category_dir.is_dir():
            continue
        for entry in sorted(category_dir.iterdir()):
            if entry.is_file():
                found.append(ScannedFile(category, entry.name, entry.stat().st_size))
    return found


def index_file(category: str, filename: str, size_bytes: int, source: str = "local") -> None:
    """Upsert one model by ``(category, filename)``; ``source`` applies to new rows only."""
    conn = storage.get_db()
    conn.execute(
        "INSERT INTO models (category, filename, size_bytes, indexed_at, source) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(category, filename) DO UPDATE SET "
        "  size_bytes = excluded.size_bytes, indexed_at = excluded.indexed_at",
        (category, filename, size_bytes, storage.utcnow_iso(), source),
    )
    conn.commit()


def register_host_model(category: str, filename: str, size_bytes: int) -> Model:
    """Insert a model discovered on a host (``source = 'host'``).

    A no-op if ``(category, filename)`` is already indexed. Returns the row either way.
    """
    conn = storage.get_db()
    conn.execute(
        "INSERT INTO models (category, filename, size_bytes, indexed_at, source) "
        "VALUES (?, ?, ?, ?, 'host') ON CONFLICT(category, filename) DO NOTHING",
        (category, filename, size_bytes, storage.utcnow_iso()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, category, filename, size_bytes, indexed_at, source FROM models "
        "WHERE category = ? AND filename = ?",
        (category, filename),
    ).fetchone()
    return Model(
        id=row["id"],
        category=row["category"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        indexed_at=row["indexed_at"],
        source=row["source"],
    )


def mark_local(model_id: int) -> None:
    """Flip a ``source = 'host'`` model to ``'local'`` once its file has been downloaded."""
    conn = storage.get_db()
    conn.execute("UPDATE models SET source = 'local' WHERE id = ?", (model_id,))
    conn.commit()


def prune_orphan_host_models() -> list[tuple[str, str]]:
    """Delete ``source = 'host'`` models that no host holds any more."""
    conn = storage.get_db()
    rows = conn.execute(
        "SELECT id, category, filename FROM models WHERE source = 'host' "
        "AND id NOT IN (SELECT model_id FROM placements)"
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM models WHERE id = ?", (row["id"],))
    conn.commit()
    return sorted((row["category"], row["filename"]) for row in rows)


def reindex() -> IndexChanges:
    """Reconcile the index with the central repository on disk.

    Adds new files, resizes changed ones, and removes entries backed by the central
    repository whose files are gone. A ``source = 'host'`` model is never removed
    here; if its file turns up in the central scan it is promoted to ``'local'``.
    """
    conn = storage.get_db()
    scanned = {(f.category, f.filename): f for f in scan_repo()}
    existing = {
        (row["category"], row["filename"]): row
        for row in conn.execute(
            "SELECT id, category, filename, size_bytes, source FROM models"
        )
    }

    added: list[tuple[str, str]] = []
    removed: list[tuple[str, str]] = []
    updated: list[tuple[str, str]] = []
    now = storage.utcnow_iso()

    for key, scanned_file in scanned.items():
        row = existing.get(key)
        if row is None:
            conn.execute(
                "INSERT INTO models (category, filename, size_bytes, indexed_at, source) "
                "VALUES (?, ?, ?, ?, 'local')",
                (scanned_file.category, scanned_file.filename, scanned_file.size_bytes, now),
            )
            added.append(key)
            continue
        changed = False
        if row["size_bytes"] != scanned_file.size_bytes:
            conn.execute(
                "UPDATE models SET size_bytes = ?, indexed_at = ? WHERE id = ?",
                (scanned_file.size_bytes, now, row["id"]),
            )
            changed = True
        if row["source"] == "host":
            conn.execute(
                "UPDATE models SET source = 'local' WHERE id = ?", (row["id"],)
            )
            changed = True
        if changed:
            updated.append(key)

    for key, row in existing.items():
        if key not in scanned and row["source"] != "host":
            conn.execute("DELETE FROM models WHERE id = ?", (row["id"],))
            removed.append(key)

    conn.commit()
    return IndexChanges(sorted(added), sorted(removed), sorted(updated))


# --- queries -------------------------------------------------------------


def list_models(
    category: str | None = None, name_fragment: str | None = None
) -> list[Model]:
    """Indexed models, optionally filtered, sorted by category then filename."""
    conn = storage.get_db()
    sql = "SELECT id, category, filename, size_bytes, indexed_at, source FROM models"
    clauses: list[str] = []
    params: list[object] = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if name_fragment:
        clauses.append("filename LIKE ? ESCAPE '\\'")
        params.append("%" + _like_escape(name_fragment) + "%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY category, filename"
    return [
        Model(
            id=row["id"],
            category=row["category"],
            filename=row["filename"],
            size_bytes=row["size_bytes"],
            indexed_at=row["indexed_at"],
            source=row["source"],
        )
        for row in conn.execute(sql, params)
    ]


def get_model(model_id: int) -> Model | None:
    for model in list_models():
        if model.id == model_id:
            return model
    return None


def _like_escape(fragment: str) -> str:
    return fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
