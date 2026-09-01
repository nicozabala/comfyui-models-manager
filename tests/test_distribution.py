import posixpath

import pytest

from comfy_network_tools import distribution, hosts, models_repo
from comfy_network_tools.errors import ConnectivityError
from comfy_network_tools.ssh import InMemoryRemoteFS


@pytest.fixture
def repo(tmp_path, db):
    root = tmp_path / "repo"
    for category in ("checkpoints", "loras", "vae"):
        (root / category).mkdir(parents=True)
    models_repo.set_repo_root(root)
    return root


def add_model(repo, category, name, size):
    (repo / category / name).write_bytes(b"\0" * size)
    models_repo.reindex()
    return next(m for m in models_repo.list_models() if m.filename == name)


@pytest.fixture
def cloud():
    """host_id -> fake remote filesystem, each with an existing /models base dir."""
    store: dict[int, InMemoryRemoteFS] = {}

    def connect(host):
        fs = store.get(host.id)
        if fs is None:
            fs = InMemoryRemoteFS()
            fs.add_dir(host.remote_base_path)
            store[host.id] = fs
        return fs

    connect.store = store
    return connect


def make_host(name, base="/models"):
    return hosts.add_host(
        name=name, address=f"host-{name}", username="u", remote_base_path=base
    )


# --- 6.1 copy ---


def test_copy_expands_to_model_times_host_transfers(repo, cloud):
    m1 = add_model(repo, "loras", "a.safetensors", 10)
    m2 = add_model(repo, "vae", "b.safetensors", 20)
    h1, h2, h3 = make_host("h1"), make_host("h2"), make_host("h3")

    results = distribution.copy([m1, m2], [h1, h2, h3], connect=cloud)

    assert len(results) == 6
    assert all(r.outcome == distribution.COPIED for r in results)
    fs1 = cloud.store[h1.id]
    assert fs1.stat("/models/loras/a.safetensors").size == 10
    assert fs1.stat("/models/vae/b.safetensors").size == 20


def test_copy_creates_missing_category_dir(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 5)
    h = make_host("h1")
    distribution.copy([m], [h], connect=cloud)
    assert cloud.store[h.id].stat("/models/loras").is_dir


def test_copy_records_placement_on_success(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 5)
    h = make_host("h1")
    distribution.copy([m], [h], connect=cloud)
    assert [x.id for x in distribution.hosts_for_model(m.id)] == [h.id]
    assert [x.id for x in distribution.models_for_host(h.id)] == [m.id]


# --- 6.2 presence check ---


def test_identical_file_is_skipped_and_placement_recorded(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 8)
    h = make_host("h1")
    cloud(h).add_file("/models/loras/a.safetensors", 8)

    (result,) = distribution.copy([m], [h], connect=cloud)
    assert result.outcome == distribution.ALREADY_PRESENT
    assert distribution.hosts_for_model(m.id)


def test_size_mismatch_is_a_conflict_unless_overwrite_confirmed(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 8)
    h = make_host("h1")
    cloud(h).add_file("/models/loras/a.safetensors", 999)

    (result,) = distribution.copy([m], [h], connect=cloud)
    assert result.outcome == distribution.CONFLICT
    assert not distribution.hosts_for_model(m.id)

    (result,) = distribution.copy([m], [h], connect=cloud, on_conflict=lambda plan: True)
    assert result.outcome == distribution.COPIED
    assert cloud(h).stat("/models/loras/a.safetensors").size == 8


# --- 6.3 failure handling ---


def test_failed_transfer_records_no_placement_and_cleans_part(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 8)
    h = make_host("h1")
    fs = cloud(h)
    fs.fail_paths.add(posixpath.normpath("/models/loras/a.safetensors.cnt-part"))

    (result,) = distribution.copy([m], [h], connect=cloud)
    assert result.outcome == distribution.FAILED
    assert not distribution.hosts_for_model(m.id)
    assert fs.stat("/models/loras/a.safetensors") is None
    assert fs.stat("/models/loras/a.safetensors.cnt-part") is None


def test_unreachable_host_fails_all_its_transfers(repo):
    m = add_model(repo, "loras", "a.safetensors", 8)
    h = make_host("h1")

    def boom(host):
        raise ConnectivityError("unreachable")

    (result,) = distribution.copy([m], [h], connect=boom)
    assert result.outcome == distribution.FAILED and result.detail == "unreachable"


# --- 6.5 / 10.2 reconcile ---


def test_reconcile_adds_missing_placement(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 8)
    h = make_host("h1")
    cloud(h).add_file("/models/loras/a.safetensors", 8)

    changes = distribution.reconcile(h.id, connect=cloud)
    assert changes.added_placements == [("loras", "a.safetensors")]
    assert distribution.hosts_for_model(m.id)


def test_reconcile_removes_stale_placement(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 8)
    h = make_host("h1")
    distribution._record_placement(m.id, h.id)
    cloud(h)  # empty remote, file not there

    changes = distribution.reconcile(h.id, connect=cloud)
    assert changes.removed == [("loras", "a.safetensors")]
    assert not distribution.hosts_for_model(m.id)


def test_reconcile_registers_host_only_file(repo, cloud):
    h = make_host("h1")
    cloud(h).add_file("/models/vae/stranger.safetensors", 3)

    changes = distribution.reconcile(h.id, connect=cloud)
    assert changes.registered == [("vae", "stranger.safetensors")]

    (model,) = [m for m in models_repo.list_models() if m.filename == "stranger.safetensors"]
    assert model.source == "host"
    assert [x.id for x in distribution.hosts_for_model(model.id)] == [h.id]


def test_reconcile_size_mismatch_is_a_discrepancy(repo, cloud):
    m = add_model(repo, "loras", "known.safetensors", 8)
    h = make_host("h1")
    cloud(h).add_file("/models/loras/known.safetensors", 999)

    changes = distribution.reconcile(h.id, connect=cloud)
    assert changes.discrepancies and "known.safetensors" in changes.discrepancies[0]
    assert changes.added_placements == [] and changes.registered == []
    assert not distribution.hosts_for_model(m.id)


def test_reconcile_ignores_cnt_part_files(repo, cloud):
    h = make_host("h1")
    cloud(h).add_file("/models/loras/half.safetensors.cnt-part", 5)

    changes = distribution.reconcile(h.id, connect=cloud)
    assert changes.is_empty
    assert models_repo.list_models() == []


def test_reconcile_drops_orphaned_host_model(repo, cloud):
    h = make_host("h1")
    fs = cloud(h)
    fs.add_file("/models/vae/x.safetensors", 4)
    distribution.reconcile(h.id, connect=cloud)
    assert any(m.filename == "x.safetensors" for m in models_repo.list_models())

    fs.remove("/models/vae/x.safetensors")
    changes = distribution.reconcile(h.id, connect=cloud)
    assert changes.removed == [("vae", "x.safetensors")]
    assert models_repo.list_models() == []


# --- import (host -> repository) ---


def test_import_downloads_host_only_model_into_repo(repo, cloud):
    h = make_host("h1")
    cloud(h).add_file("/models/vae/stranger.safetensors", 3)
    distribution.reconcile(h.id, connect=cloud)
    (model,) = [m for m in models_repo.list_models() if m.filename == "stranger.safetensors"]
    assert model.source == "host"

    (result,) = distribution.import_from_host([model], h, connect=cloud)
    assert result.outcome == distribution.COPIED
    assert (repo / "vae" / "stranger.safetensors").stat().st_size == 3
    imported = models_repo.get_model(model.id)
    assert imported.source == "local"


def test_import_skips_when_already_present_locally(repo, cloud):
    m = add_model(repo, "loras", "a.safetensors", 8)
    h = make_host("h1")
    cloud(h).add_file("/models/loras/a.safetensors", 8)

    (result,) = distribution.import_from_host([m], h, connect=cloud)
    assert result.outcome == distribution.ALREADY_PRESENT


def test_import_size_mismatch_is_a_conflict_unless_overwrite_confirmed(repo, cloud):
    # A stray local file sits where the host-only model would land, sized differently
    # from what the host reports (e.g. left over from before a reindex).
    (repo / "loras" / "a.safetensors").write_bytes(b"\0" * 999)
    m = models_repo.register_host_model("loras", "a.safetensors", 8)
    h = make_host("h1")
    cloud(h).add_file("/models/loras/a.safetensors", 8)
    distribution._record_placement(m.id, h.id)

    (result,) = distribution.import_from_host([m], h, connect=cloud)
    assert result.outcome == distribution.CONFLICT

    (result,) = distribution.import_from_host(
        [m], h, connect=cloud, on_conflict=lambda plan: True
    )
    assert result.outcome == distribution.COPIED
    assert (repo / "loras" / "a.safetensors").stat().st_size == 8


def test_import_missing_source_file_fails(repo, cloud):
    h = make_host("h1")
    cloud(h)  # nothing on the host
    from comfy_network_tools.models_repo import Model

    ghost = Model(
        id=999, category="loras", filename="ghost.safetensors", size_bytes=1,
        indexed_at="t", source="host",
    )
    (result,) = distribution.import_from_host([ghost], h, connect=cloud)
    assert result.outcome == distribution.FAILED


def test_import_unreachable_host_fails(repo):
    h = make_host("h1")
    m = add_model(repo, "loras", "a.safetensors", 8)  # placeholder; not host-only, but ok here

    def boom(host):
        raise ConnectivityError("unreachable")

    (result,) = distribution.import_from_host([m], h, connect=boom)
    assert result.outcome == distribution.FAILED and result.detail == "unreachable"


# --- 6.6 matrix ---


def test_matrix_marks_present_and_missing(repo, cloud):
    m1 = add_model(repo, "loras", "a.safetensors", 8)
    add_model(repo, "vae", "b.safetensors", 8)
    h1, h2 = make_host("h1"), make_host("h2")
    distribution.copy([m1], [h1], connect=cloud)

    mtx = distribution.matrix()
    assert mtx.empty_reason is None
    assert [h.id for h in mtx.hosts] == [h1.id, h2.id]
    row_a = next(r for r in mtx.rows if r.model.filename == "a.safetensors")
    row_b = next(r for r in mtx.rows if r.model.filename == "b.safetensors")
    assert row_a.present_host_ids == {h1.id}
    assert row_a.coverage({h1.id, h2.id}) == 1
    assert row_b.present_host_ids == set()


def test_matrix_empty_states(repo):
    assert distribution.matrix().empty_reason == "no registered hosts"
    make_host("h1")
    assert distribution.matrix().empty_reason == "no indexed models"
