"""End-to-end walk of the full workflow at the service layer (no interactive UI).

Mirrors the manual walkthrough in tasks.md 9.4: configure -> index -> add host ->
copy -> matrix -> reconcile -> Hugging Face download -> matrix again.
"""

from __future__ import annotations

from dataclasses import dataclass

from comfy_network_tools import distribution, huggingface, models_repo
from comfy_network_tools import hosts as hosts_svc
from comfy_network_tools.ssh import InMemoryRemoteFS


@dataclass
class _Sibling:
    rfilename: str
    size: int


class _FakeApi:
    def __init__(self, siblings):
        self._siblings = siblings

    def model_info(self, repo_id, revision=None, files_metadata=False):
        return type("Info", (), {"siblings": self._siblings})()


def test_full_workflow(tmp_path, db):
    # 1. configure the repository and index a sample tree
    repo = tmp_path / "repo"
    for category in ("checkpoints", "loras"):
        (repo / category).mkdir(parents=True)
    (repo / "loras" / "style.safetensors").write_bytes(b"\0" * 512)
    models_repo.set_repo_root(repo)
    models_repo.reindex()
    style = models_repo.list_models()[0]

    # 2. add a host
    host = hosts_svc.add_host(
        name="gpu", address="10.0.0.2", username="ml", remote_base_path="/models"
    )

    # 3. copy the model to the host (fake transport) and check the placement
    cloud = InMemoryRemoteFS()
    cloud.add_dir("/models")
    (result,) = distribution.copy([style], [host], connect=lambda h: cloud)
    assert result.outcome == distribution.COPIED
    assert cloud.stat("/models/loras/style.safetensors").size == 512

    # 4. the matrix shows it present
    row = next(r for r in distribution.matrix().rows if r.model.id == style.id)
    assert row.present_host_ids == {host.id}

    # 5. reconcile is a no-op now that the file and placement agree
    assert distribution.reconcile(host.id, connect=lambda h: cloud).is_empty

    # 5b. a model already sitting on the host (not put there by the tool) is registered
    cloud.add_file("/models/loras/preexisting.safetensors", 999)
    scan = distribution.reconcile(host.id, connect=lambda h: cloud)
    assert scan.registered == [("loras", "preexisting.safetensors")]
    pre = next(m for m in models_repo.list_models() if m.filename == "preexisting.safetensors")
    assert pre.source == "host"
    pre_row = next(r for r in distribution.matrix().rows if r.model.id == pre.id)
    assert pre_row.present_host_ids == {host.id}
    # it survives a central re-index
    models_repo.reindex()
    assert any(m.id == pre.id for m in models_repo.list_models())

    # 6. download a model from Hugging Face into a category
    def fake_download(*, repo_id, filename, revision, local_dir, token):
        path = repo / "checkpoints" / filename
        path.write_bytes(b"\0" * 2048)
        return str(path)

    outcomes = huggingface.download(
        "owner/base", ["base.safetensors"], "checkpoints",
        api=_FakeApi([_Sibling("base.safetensors", 2048)]), hf_download=fake_download,
    )
    assert outcomes[0].status == huggingface.DOWNLOADED

    # 7. the downloaded model is in the index and the matrix (missing on the host)
    base = next(m for m in models_repo.list_models() if m.filename == "base.safetensors")
    assert base.source == "huggingface"
    base_row = next(r for r in distribution.matrix().rows if r.model.id == base.id)
    assert base_row.present_host_ids == set()
