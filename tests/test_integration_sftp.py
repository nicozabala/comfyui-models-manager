"""Opt-in integration test: real SFTP transfer + reconcile against a mock SSH server.

Run with:  uv run pytest -m integration
Deselected by default (see ``addopts`` in pyproject.toml).
"""

from __future__ import annotations

import paramiko
import pytest

from comfy_network_tools import distribution, models_repo
from comfy_network_tools import hosts as hosts_svc

pytestmark = pytest.mark.integration


@pytest.fixture
def ssh_server(tmp_path):
    from mockssh import Server

    key_path = tmp_path / "id_rsa"
    paramiko.RSAKey.generate(2048).write_private_key_file(str(key_path))
    with Server({"u": str(key_path)}) as server:
        yield server, str(key_path)


def _posix(path) -> str:
    return str(path).replace("\\", "/")


def test_copy_and_reconcile_over_real_sftp(tmp_path, db, ssh_server):
    server, key_path = ssh_server

    remote_base = tmp_path / "remote"
    (remote_base / "loras").mkdir(parents=True)

    repo = tmp_path / "repo"
    (repo / "loras").mkdir(parents=True)
    payload = b"integration-payload" * 64
    (repo / "loras" / "m.safetensors").write_bytes(payload)
    models_repo.set_repo_root(repo)
    models_repo.reindex()
    model = models_repo.list_models()[0]

    host = hosts_svc.add_host(
        name="local",
        address=server.host,
        username="u",
        remote_base_path=_posix(remote_base),
        port=server.port,
        auth_method="key",
        private_key_path=key_path,
        trust_host_key=True,
    )

    (result,) = distribution.copy([model], [host])
    assert result.outcome == distribution.COPIED, result.detail
    assert (remote_base / "loras" / "m.safetensors").read_bytes() == payload

    # drop the placement, then let a scan rediscover it by name + size
    distribution._delete_placement(model.id, host.id)
    changes = distribution.reconcile(host.id)
    assert changes.added_placements == [("loras", "m.safetensors")]
    assert [h.id for h in distribution.hosts_for_model(model.id)] == [host.id]
