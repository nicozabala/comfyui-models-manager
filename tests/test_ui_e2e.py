"""Drives the real UI screens end to end with a scripted prompter (no TTY needed).

Covers the tasks.md 9.4 walkthrough through ``app.loop`` and the screen functions:
first-run configure -> add host -> matrix copy -> reconcile-free -> settings re-index.
"""

from __future__ import annotations

from comfy_network_tools import distribution, models_repo
from comfy_network_tools import hosts as hosts_svc
from comfy_network_tools.ssh import InMemoryRemoteFS
from comfy_network_tools.ui import app
from comfy_network_tools.ui import matrix as matrix_ui


def test_ui_walkthrough(tmp_path, db, console, make_prompter, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "loras").mkdir(parents=True)
    (repo / "loras" / "style.safetensors").write_bytes(b"\0" * 256)

    # --- first run: configure the repository from the menu, then re-index ---
    prompter = make_prompter([str(repo), True, "exit"])  # path, "re-index now?" yes, menu exit
    app.loop(prompter, console)
    assert models_repo.is_configured()
    assert [m.filename for m in models_repo.list_models()] == ["style.safetensors"]

    # --- add a host through the host screen ---
    from comfy_network_tools.ui import hosts as hosts_ui

    hosts_ui.add_host_flow(
        make_prompter(["gpu", "10.0.0.9", "22", "ml", "/models", "agent"]), console
    )
    host = hosts_svc.list_hosts()[0]

    # --- copy the model to the host from the matrix screen (fake transport) ---
    cloud = InMemoryRemoteFS()
    cloud.add_dir("/models")
    monkeypatch.setattr(distribution.hosts, "open_connection", lambda h, **kw: cloud)

    model = models_repo.list_models()[0]
    matrix_ui._copy_model_flow(
        make_prompter([[host.id]]), console, model  # checkbox of target hosts
    )
    assert cloud.stat("/models/loras/style.safetensors").size == 256

    # --- the matrix now shows it present ---
    row = next(r for r in distribution.matrix().rows if r.model.id == model.id)
    assert row.present_host_ids == {host.id}

    # --- scan the host: a pre-existing file (not put there by the tool) is registered ---
    cloud.add_file("/models/vae/preexisting.safetensors", 4096)
    hosts_ui.scan_host_flow(make_prompter([host.id]), console)

    registered = next(
        m for m in models_repo.list_models() if m.filename == "preexisting.safetensors"
    )
    assert registered.source == "host"
    reg_row = next(r for r in distribution.matrix().rows if r.model.id == registered.id)
    assert reg_row.present_host_ids == {host.id}
