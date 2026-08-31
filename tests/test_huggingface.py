from dataclasses import dataclass

import pytest

from comfy_network_tools import huggingface, models_repo
from comfy_network_tools.errors import (
    DownloadError,
    HuggingFaceAuthError,
    HuggingFaceNotFound,
)
from comfy_network_tools.huggingface import HFReference


@pytest.fixture
def repo(tmp_path, db):
    root = tmp_path / "repo"
    for category in ("checkpoints", "loras"):
        (root / category).mkdir(parents=True)
    models_repo.set_repo_root(root)
    return root


# --- fakes ---


@dataclass
class Sibling:
    rfilename: str
    size: int


class FakeApi:
    def __init__(self, siblings, error=None):
        self._siblings = siblings
        self._error = error

    def model_info(self, repo_id, revision=None, files_metadata=False):
        if self._error is not None:
            raise self._error
        return type("Info", (), {"siblings": self._siblings})()


# --- 7.1 token storage ---


def test_save_token_and_status(db):
    huggingface.save_token("hf_abcdefghijklmnop")
    status = huggingface.token_status()
    assert status.configured and status.source == "file"
    assert status.preview and "abcdefghijklmnop" not in status.preview


def test_env_var_overrides_stored_token(db, monkeypatch):
    huggingface.save_token("hf_fromfile1234")
    monkeypatch.setenv("HF_TOKEN", "hf_fromenv5678")
    status = huggingface.token_status()
    assert status.source == "env:HF_TOKEN"


def test_empty_token_rejected(db):
    with pytest.raises(HuggingFaceAuthError):
        huggingface.save_token("   ")


# --- 7.2 validation ---


def test_validate_token_accepted(db):
    huggingface.save_token("hf_x")
    result = huggingface.validate_token(whoami=lambda token: {"name": "alice"})
    assert result.valid and result.account == "alice"


def test_validate_token_rejected(db):
    huggingface.save_token("hf_x")

    def boom(token):
        raise RuntimeError("401 unauthorized")

    result = huggingface.validate_token(whoami=boom)
    assert not result.valid and "401" in result.detail


def test_validate_token_missing(db):
    result = huggingface.validate_token(whoami=lambda token: {"name": "x"})
    assert not result.valid and result.detail == "no token configured"


# --- 7.3 reference parsing ---


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("owner/name", HFReference("owner/name", None, None)),
        ("owner/name@v2", HFReference("owner/name", "v2", None)),
        (
            "https://huggingface.co/owner/name/blob/main/model.safetensors",
            HFReference("owner/name", "main", "model.safetensors"),
        ),
        (
            "huggingface.co/owner/name/resolve/abc123/sub/dir/m.bin",
            HFReference("owner/name", "abc123", "sub/dir/m.bin"),
        ),
    ],
)
def test_resolve_reference_forms(ref, expected):
    assert huggingface.resolve_reference(ref) == expected


def test_resolve_reference_malformed():
    with pytest.raises(HuggingFaceNotFound):
        huggingface.resolve_reference("not a reference")


# --- 7.4 list_files ---


def test_list_files_returns_name_and_size(repo):
    api = FakeApi([Sibling("a.safetensors", 100), Sibling("b.safetensors", 200)])
    files = huggingface.list_files("owner/name", api=api)
    assert [(f.path, f.size) for f in files] == [
        ("a.safetensors", 100),
        ("b.safetensors", 200),
    ]


def test_list_files_unknown_repo(repo):
    api = FakeApi([], error=RuntimeError("boom"))
    with pytest.raises(HuggingFaceNotFound):
        # generic errors on an explicit-file reference surface as not-found
        huggingface.list_files("owner/name/blob/main/missing.bin", api=api)


# --- 7.5 download ---


def test_download_places_file_and_indexes_it(repo):
    api = FakeApi([Sibling("model.safetensors", 42)])

    def fake_download(*, repo_id, filename, revision, local_dir, token):
        path = repo / "checkpoints" / filename
        path.write_bytes(b"\0" * 42)
        return str(path)

    outcomes = huggingface.download(
        "owner/name", ["model.safetensors"], "checkpoints", api=api, hf_download=fake_download
    )
    assert outcomes[0].status == huggingface.DOWNLOADED
    indexed = models_repo.list_models()
    assert [(m.filename, m.size_bytes, m.source) for m in indexed] == [
        ("model.safetensors", 42, "huggingface")
    ]


def test_download_skips_when_same_name_and_size_present(repo):
    api = FakeApi([Sibling("model.safetensors", 42)])
    (repo / "checkpoints" / "model.safetensors").write_bytes(b"\0" * 42)

    calls = []

    def fake_download(**kwargs):
        calls.append(kwargs)
        raise AssertionError("should not download")

    outcomes = huggingface.download(
        "owner/name", ["model.safetensors"], "checkpoints", api=api, hf_download=fake_download
    )
    assert outcomes[0].status == huggingface.SKIPPED
    assert calls == []


def test_download_failure_cleans_partial_and_indexes_nothing(repo):
    api = FakeApi([Sibling("model.safetensors", 42)])

    def fake_download(*, repo_id, filename, revision, local_dir, token):
        (repo / "checkpoints" / filename).write_bytes(b"\0" * 10)  # partial
        raise ConnectionError("network down")

    with pytest.raises(DownloadError):
        huggingface.download(
            "owner/name",
            ["model.safetensors"],
            "checkpoints",
            api=api,
            hf_download=fake_download,
        )
    assert not (repo / "checkpoints" / "model.safetensors").exists()
    assert models_repo.list_models() == []


def test_download_unknown_category(repo):
    api = FakeApi([Sibling("m", 1)])
    with pytest.raises(DownloadError):
        huggingface.download(
            "owner/name", ["m"], "not_a_category", api=api, hf_download=lambda **k: ""
        )
