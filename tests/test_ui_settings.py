import pytest

from comfy_network_tools import models_repo
from comfy_network_tools.ui import settings as settings_ui


@pytest.fixture
def repo(tmp_path, db):
    root = tmp_path / "repo"
    (root / "loras").mkdir(parents=True)
    models_repo.set_repo_root(root)
    return root


def test_run_reindex_reports_changes(console, repo):
    (repo / "loras" / "a.safetensors").write_bytes(b"\0" * 3)
    changes = settings_ui.run_reindex(console)
    assert changes.added == [("loras", "a.safetensors")]
    assert [m.filename for m in models_repo.list_models()] == ["a.safetensors"]


def test_run_reindex_cancelled_leaves_index_unchanged(console, repo, monkeypatch):
    (repo / "loras" / "a.safetensors").write_bytes(b"\0" * 3)
    models_repo.reindex()
    before = models_repo.list_models()

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(models_repo, "scan_repo", interrupted)
    result = settings_ui.run_reindex(console)
    assert result is None
    assert models_repo.list_models() == before
    assert "cancelled" in console.export_text().lower()


def test_set_repo_flow_configures_and_offers_reindex(make_prompter, console, tmp_path, db):
    root = tmp_path / "models"
    (root / "loras").mkdir(parents=True)
    (root / "loras" / "x.safetensors").write_bytes(b"\0" * 2)
    prompter = make_prompter([str(root), True])  # path, then "Re-index now?" -> yes
    settings_ui._set_repo(prompter, console)
    assert models_repo.is_configured()
    assert models_repo.list_models()[0].filename == "x.safetensors"


def test_set_token_flow_saves_and_validates(make_prompter, console, db, monkeypatch):
    from comfy_network_tools import huggingface

    monkeypatch.setattr(
        huggingface, "validate_token",
        lambda **k: huggingface.ValidationResult(valid=True, account="bob", detail=None),
    )
    settings_ui._set_token(make_prompter(["hf_tokenvalue"]), console)
    assert huggingface.token_status().configured
    assert "valid" in console.export_text()
