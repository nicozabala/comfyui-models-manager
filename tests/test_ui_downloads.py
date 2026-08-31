from dataclasses import dataclass

import pytest

from comfy_network_tools import models_repo
from comfy_network_tools.errors import HuggingFaceAuthError
from comfy_network_tools.huggingface import DownloadOutcome, HFFile, HFReference, TokenStatus
from comfy_network_tools.ui import downloads


@pytest.fixture
def repo(tmp_path, db):
    root = tmp_path / "repo"
    (root / "checkpoints").mkdir(parents=True)
    models_repo.set_repo_root(root)
    return root


@dataclass
class FakeService:
    files: list
    outcomes: list
    list_error: Exception | None = None
    download_error: Exception | None = None
    download_calls: list = None

    def __post_init__(self):
        self.download_calls = []

    def token_status(self):
        return TokenStatus(configured=True, source="file", preview="hf_...abcd")

    def resolve_reference(self, ref):
        return HFReference(repo_id=ref)

    def list_files(self, ref):
        if self.list_error:
            raise self.list_error
        return self.files

    def download(self, ref, files, category, overwrite=False):
        self.download_calls.append((files, category))
        if self.download_error:
            raise self.download_error
        return self.outcomes


def test_download_flow_happy_path(make_prompter, console, repo):
    service = FakeService(
        files=[HFFile("model.safetensors", 10)],
        outcomes=[DownloadOutcome("model.safetensors", "checkpoints", "downloaded")],
    )
    prompter = make_prompter(
        ["owner/name", ["model.safetensors"], "checkpoints", True]
    )
    downloads.download_screen(prompter, console, service=service)
    assert service.download_calls == [(["model.safetensors"], "checkpoints")]
    assert "downloaded" in console.export_text()


def test_download_flow_stops_when_token_required(make_prompter, console, repo):
    service = FakeService(files=[], outcomes=[], list_error=HuggingFaceAuthError("gated repo"))
    prompter = make_prompter(["owner/gated"])
    downloads.download_screen(prompter, console, service=service)
    assert service.download_calls == []
    assert "valid token" in console.export_text()
