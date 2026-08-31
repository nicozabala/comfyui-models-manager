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


def _fake_model(id_, category, filename):
    return Model(
        id=id_, category=category, filename=filename, size_bytes=1,
        indexed_at="t", source="local",
    )
