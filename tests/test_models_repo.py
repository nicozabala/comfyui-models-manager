import pytest

from comfy_network_tools import models_repo, storage
from comfy_network_tools.errors import InvalidRepositoryPath, RepositoryNotConfigured


@pytest.fixture
def repo(tmp_path, db):
    root = tmp_path / "repo"
    root.mkdir()
    for category in ("checkpoints", "loras", "vae", "unet"):
        (root / category).mkdir()
    models_repo.set_repo_root(root)
    return root


def _write(path, size):
    path.write_bytes(b"\0" * size)


# --- Repository location is configured ---


def test_set_repo_root_accepts_a_directory(tmp_path, db):
    root = tmp_path / "models"
    root.mkdir()
    resolved = models_repo.set_repo_root(root)
    assert resolved == root.resolve()
    assert models_repo.is_configured()
    assert storage.get_repo_root(db) == str(root.resolve())


def test_set_repo_root_rejects_missing_path(tmp_path, db):
    with pytest.raises(InvalidRepositoryPath):
        models_repo.set_repo_root(tmp_path / "nope")
    assert not models_repo.is_configured()


def test_set_repo_root_rejects_a_file(tmp_path, db):
    f = tmp_path / "a-file"
    f.write_text("x")
    with pytest.raises(InvalidRepositoryPath):
        models_repo.set_repo_root(f)


def test_rejected_path_leaves_previous_value(tmp_path, db):
    good = tmp_path / "good"
    good.mkdir()
    models_repo.set_repo_root(good)
    with pytest.raises(InvalidRepositoryPath):
        models_repo.set_repo_root(tmp_path / "bad")
    assert storage.get_repo_root(db) == str(good.resolve())


def test_operations_without_a_repo_raise(db):
    with pytest.raises(RepositoryNotConfigured):
        models_repo.scan_repo()


# --- Models are organized by category ---


def test_scan_records_files_in_known_categories(repo):
    _write(repo / "loras" / "style.safetensors", 5)
    scanned = models_repo.scan_repo()
    assert (("loras", "style.safetensors", 5),) == tuple(
        (s.category, s.filename, s.size_bytes) for s in scanned
    )


def test_scan_ignores_root_level_and_unknown_dirs(repo):
    _write(repo / "loose.safetensors", 3)
    (repo / "totally_unknown").mkdir()
    _write(repo / "totally_unknown" / "x.safetensors", 3)
    assert models_repo.scan_repo() == []


# --- identity ---


def test_same_name_different_category_are_two_models(repo):
    _write(repo / "checkpoints" / "model.safetensors", 10)
    _write(repo / "unet" / "model.safetensors", 20)
    models_repo.reindex()
    models = models_repo.list_models(name_fragment="model")
    assert {(m.category, m.size_bytes) for m in models} == {
        ("checkpoints", 10),
        ("unet", 20),
    }
    assert all(m.indexed_at for m in models)


# --- reindex diffing ---


def test_reindex_adds_new_files(repo):
    _write(repo / "vae" / "v.safetensors", 7)
    changes = models_repo.reindex()
    assert changes.added == [("vae", "v.safetensors")]
    assert [m.filename for m in models_repo.list_models()] == ["v.safetensors"]


def test_reindex_removes_vanished_files(repo):
    target = repo / "vae" / "v.safetensors"
    _write(target, 7)
    models_repo.reindex()
    target.unlink()
    changes = models_repo.reindex()
    assert changes.removed == [("vae", "v.safetensors")]
    assert models_repo.list_models() == []


def test_reindex_updates_changed_size(repo):
    target = repo / "loras" / "l.safetensors"
    _write(target, 4)
    models_repo.reindex()
    _write(target, 9)
    changes = models_repo.reindex()
    assert changes.updated == [("loras", "l.safetensors")]
    assert models_repo.list_models()[0].size_bytes == 9


def test_reindex_preserves_huggingface_source_on_conflict(repo):
    _write(repo / "checkpoints" / "hf.safetensors", 12)
    models_repo.index_file("checkpoints", "hf.safetensors", 12, source="huggingface")
    models_repo.reindex()
    assert models_repo.list_models()[0].source == "huggingface"


# --- host-discovered models (10.1) ---


def test_register_host_model_inserts_and_is_idempotent(repo):
    first = models_repo.register_host_model("loras", "h.safetensors", 42)
    assert first.source == "host" and first.size_bytes == 42
    again = models_repo.register_host_model("loras", "h.safetensors", 999)
    assert again.id == first.id and again.size_bytes == 42  # no-op on conflict


def test_host_model_survives_central_reindex(repo):
    models_repo.register_host_model("loras", "only-on-host.safetensors", 5)
    models_repo.reindex()  # nothing on the central disk
    assert [m.filename for m in models_repo.list_models()] == ["only-on-host.safetensors"]


def test_host_model_promoted_to_local_when_file_appears_centrally(repo):
    models_repo.register_host_model("loras", "shared.safetensors", 8)
    _write(repo / "loras" / "shared.safetensors", 8)
    models_repo.reindex()
    assert models_repo.list_models()[0].source == "local"


def test_prune_orphan_host_models(repo, db):
    models_repo.register_host_model("vae", "orphan.safetensors", 3)
    assert models_repo.prune_orphan_host_models() == [("vae", "orphan.safetensors")]
    assert models_repo.list_models() == []

    # a host model with a placement is kept
    keep = models_repo.register_host_model("vae", "kept.safetensors", 3)
    db.execute(
        "INSERT INTO hosts (name, address, username, remote_base_path) "
        "VALUES ('h', '10.0.0.1', 'u', '/m')"
    )
    db.execute(
        "INSERT INTO placements (model_id, host_id, created_at) VALUES (?, 1, ?)",
        (keep.id, storage.utcnow_iso()),
    )
    db.commit()
    assert models_repo.prune_orphan_host_models() == []


# --- list_models query ---


def test_list_models_no_filter_is_sorted_by_category_then_name(repo):
    _write(repo / "loras" / "b.safetensors", 1)
    _write(repo / "loras" / "a.safetensors", 1)
    _write(repo / "checkpoints" / "z.safetensors", 1)
    models_repo.reindex()
    assert [(m.category, m.filename) for m in models_repo.list_models()] == [
        ("checkpoints", "z.safetensors"),
        ("loras", "a.safetensors"),
        ("loras", "b.safetensors"),
    ]


def test_list_models_combined_filter(repo):
    _write(repo / "vae" / "sdxl-vae.safetensors", 1)
    _write(repo / "vae" / "sd15-vae.safetensors", 1)
    _write(repo / "checkpoints" / "sdxl-base.safetensors", 1)
    models_repo.reindex()
    result = models_repo.list_models(category="vae", name_fragment="sdxl")
    assert [m.filename for m in result] == ["sdxl-vae.safetensors"]
