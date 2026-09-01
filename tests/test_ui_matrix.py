import pytest

from comfy_network_tools import distribution, models_repo
from comfy_network_tools import hosts as hosts_svc
from comfy_network_tools.distribution import Matrix, MatrixRow
from comfy_network_tools.models_repo import Model
from comfy_network_tools.ssh import InMemoryRemoteFS
from comfy_network_tools.ui import matrix as matrix_ui
from comfy_network_tools.ui import render


@pytest.fixture
def seeded(tmp_path, db):
    root = tmp_path / "repo"
    (root / "loras").mkdir(parents=True)
    (root / "vae").mkdir(parents=True)
    models_repo.set_repo_root(root)
    (root / "loras" / "a.safetensors").write_bytes(b"\0" * 4)
    (root / "vae" / "b.safetensors").write_bytes(b"\0" * 4)
    models_repo.reindex()
    hosts_svc.add_host(name="h1", address="10.0.0.1", username="u", remote_base_path="/m")
    return root


def test_filter_rows_by_category_and_fragment():
    rows = [
        MatrixRow(model=_fake_model(1, "loras", "style-a.safetensors"), present_host_ids=set()),
        MatrixRow(model=_fake_model(2, "loras", "other.safetensors"), present_host_ids=set()),
        MatrixRow(model=_fake_model(3, "vae", "style-v.safetensors"), present_host_ids=set()),
    ]
    matrix = Matrix(hosts=[], rows=rows)
    assert [r.model.id for r in matrix_ui.filter_rows(matrix, "loras", None)] == [1, 2]
    assert [r.model.id for r in matrix_ui.filter_rows(matrix, None, "style")] == [1, 3]
    assert [r.model.id for r in matrix_ui.filter_rows(matrix, "loras", "style")] == [1]


def test_filter_rows_by_hosts_present_on_all_selected():
    row_both = MatrixRow(model=_fake_model(1, "loras", "a.safetensors"), present_host_ids={1, 2})
    row_one = MatrixRow(model=_fake_model(2, "loras", "b.safetensors"), present_host_ids={1})
    row_none = MatrixRow(model=_fake_model(3, "vae", "c.safetensors"), present_host_ids=set())
    matrix = Matrix(hosts=[], rows=[row_both, row_one, row_none])

    assert [r.model.id for r in matrix_ui.filter_rows(matrix, None, None, {1, 2})] == [1]
    assert [r.model.id for r in matrix_ui.filter_rows(matrix, None, None, {1})] == [1, 2]
    assert matrix_ui.filter_rows(matrix, None, None, {1, 2, 99}) == []
    assert [r.model.id for r in matrix_ui.filter_rows(matrix, None, None, None)] == [1, 2, 3]
    assert [r.model.id for r in matrix_ui.filter_rows(matrix, None, None, set())] == [1, 2, 3]
    assert [r.model.id for r in matrix_ui.filter_rows(matrix, "loras", None, {1})] == [1, 2]
    assert matrix_ui.filter_rows(matrix, "vae", None, {1}) == []


def test_filter_action_prompts_hosts_and_remembers_selection(make_prompter, console, seeded):
    h1 = next(h for h in hosts_svc.list_hosts() if h.name == "h1")
    # filter -> category ALL -> fragment blank -> hosts [h1] ; filter again (same) ; back
    prompter = make_prompter(
        ["filter", matrix_ui.ALL, "", [h1.id], "filter", matrix_ui.ALL, "", [h1.id], "back"]
    )
    matrix_ui.matrix_screen(prompter, console, copy_model=lambda m: None)

    # First Filter opens with no pre-checked hosts; the second remembers the prior pick.
    assert prompter.checked_seen == [None, {h1.id}]
    assert "hosts⊇{h1}" in console.export_text()


def test_copy_action_invokes_callback_with_selected_model(make_prompter, console, seeded):
    captured = []
    # select "Matrix" -> "copy" ; select model -> id 1 ; select "Matrix" -> "back"
    model_id = next(m.id for m in models_repo.list_models() if m.filename == "a.safetensors")
    prompter = make_prompter(["copy", model_id, "back"])
    matrix_ui.matrix_screen(prompter, console, copy_model=captured.append)
    assert len(captured) == 1
    assert captured[0].id == model_id


def test_empty_matrix_returns_immediately(make_prompter, console, db):
    prompter = make_prompter([])  # no prompts expected
    matrix_ui.matrix_screen(prompter, console, copy_model=lambda m: None)
    assert "Nothing to show" in console.export_text()


def test_copy_progress_helper_builds_and_advances():
    with render.copy_progress() as progress:
        task = progress.add_task("x", total=100)
        progress.update(task, completed=50)
        assert progress.tasks[0].completed == 50


def test_copy_flow_passes_a_progress_callback_that_advances(
    make_prompter, console, seeded, monkeypatch
):
    cloud = InMemoryRemoteFS()
    cloud.add_dir("/m")
    monkeypatch.setattr(distribution.hosts, "open_connection", lambda h, **kw: cloud)

    seen: list[tuple[int, int]] = []
    real_copy = distribution.copy

    def spy_copy(models, targets, *, progress=None, **kw):
        assert progress is not None

        def wrapped(plan, done, total):
            seen.append((done, total))
            progress(plan, done, total)

        return real_copy(models, targets, progress=wrapped, **kw)

    monkeypatch.setattr(matrix_ui.distribution, "copy", spy_copy)

    model = next(m for m in models_repo.list_models() if m.filename == "a.safetensors")
    matrix_ui._copy_model_flow(make_prompter([[hosts_svc.list_hosts()[0].id]]), console, model)

    assert seen and seen[-1][0] == seen[-1][1]  # last report is 100%
    assert [c for c, _ in seen] == sorted(c for c, _ in seen)  # monotonic byte counts


def test_import_action_invokes_callback_with_host_only_model(make_prompter, console, seeded):
    hosts_svc.add_host(name="h2", address="10.0.0.2", username="u", remote_base_path="/m")
    h1 = next(h for h in hosts_svc.list_hosts() if h.name == "h1")
    ghost = models_repo.register_host_model("vae", "stranger.safetensors", 3)
    distribution._record_placement(ghost.id, h1.id)

    captured = []
    prompter = make_prompter(["import", ghost.id, "back"])
    matrix_ui.matrix_screen(prompter, console, import_model=captured.append)
    assert len(captured) == 1
    assert captured[0].id == ghost.id


def test_import_action_has_nothing_to_offer_without_host_only_models(
    make_prompter, console, seeded
):
    prompter = make_prompter(["import", "back"])
    matrix_ui.matrix_screen(prompter, console, import_model=lambda m: None)
    assert "No host-only models" in console.export_text()


def test_import_flow_downloads_from_the_only_candidate_host(
    make_prompter, console, seeded, monkeypatch
):
    cloud = InMemoryRemoteFS()
    cloud.add_dir("/m")
    cloud.add_file("/m/vae/stranger.safetensors", 3)
    monkeypatch.setattr(distribution.hosts, "open_connection", lambda h, **kw: cloud)

    h1 = next(h for h in hosts_svc.list_hosts() if h.name == "h1")
    ghost = models_repo.register_host_model("vae", "stranger.safetensors", 3)
    distribution._record_placement(ghost.id, h1.id)

    matrix_ui._import_model_flow(make_prompter([]), console, ghost)

    imported = models_repo.get_model(ghost.id)
    assert imported.source == "local"


def _fake_model(id_, category, filename):
    return Model(
        id=id_, category=category, filename=filename, size_bytes=1,
        indexed_at="t", source="local",
    )
