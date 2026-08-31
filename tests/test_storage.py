import json

from comfy_network_tools import storage


def _table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def _column_names(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_db_has_all_tables_and_version(db):
    assert {"hosts", "models", "placements", "settings"} <= _table_names(db)
    assert storage.schema_version(db) == 1


def test_hosts_table_has_secret_and_host_key_columns(db):
    columns = _column_names(db, "hosts")
    assert "encrypted_password" in columns
    assert "host_key" in columns


def test_foreign_keys_are_enforced(db):
    (fk,) = db.execute("PRAGMA foreign_keys").fetchone()
    assert fk == 1


def test_placement_cascades_when_host_removed(db):
    db.execute(
        "INSERT INTO models (category, filename, size_bytes, indexed_at, source) "
        "VALUES ('loras', 'a.safetensors', 10, '2026-01-01T00:00:00+00:00', 'local')"
    )
    db.execute(
        "INSERT INTO hosts (name, address, username, remote_base_path) "
        "VALUES ('h1', '10.0.0.1', 'user', '/models')"
    )
    db.execute(
        "INSERT INTO placements (model_id, host_id, created_at) VALUES (1, 1, ?)",
        ("2026-01-01T00:00:00+00:00",),
    )
    db.commit()
    db.execute("DELETE FROM hosts WHERE id = 1")
    db.commit()
    assert db.execute("SELECT COUNT(*) c FROM placements").fetchone()["c"] == 0


def test_categories_seeded_and_settings_round_trip(db):
    assert storage.get_categories(db) == storage.DEFAULT_CATEGORIES

    assert storage.get_repo_root(db) is None
    storage.set_repo_root(db, "/srv/models")
    assert storage.get_repo_root(db) == "/srv/models"

    storage.set_categories(db, ["checkpoints", " loras ", ""])
    assert storage.get_categories(db) == ["checkpoints", "loras"]
    assert json.loads(storage.get_setting(db, "categories")) == ["checkpoints", "loras"]


def test_get_db_returns_same_cached_connection(db):
    assert storage.get_db() is db
