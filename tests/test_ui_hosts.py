from comfy_network_tools import distribution, models_repo
from comfy_network_tools import hosts as hosts_svc
from comfy_network_tools.ssh import InMemoryRemoteFS
from comfy_network_tools.ui import hosts as hosts_ui
from comfy_network_tools.ui import render


def test_add_host_flow_success(make_prompter, console, db):
    prompter = make_prompter(
        ["gpu-1", "10.0.0.5", "22", "ml", "/models", "agent"]
    )
    hosts_ui.add_host_flow(prompter, console)
    assert [h.name for h in hosts_svc.list_hosts()] == ["gpu-1"]


def test_add_host_flow_reprompts_after_validation_error(make_prompter, console, db):
    hosts_svc.add_host(name="taken", address="10.0.0.1", username="u", remote_base_path="/m")
    prompter = make_prompter(
        [
            "taken", "10.0.0.9", "22", "u", "/m", "agent",   # round 1: duplicate name -> error
            "fresh", "10.0.0.9", "22", "u", "/m", "agent",   # round 2: succeeds
        ]
    )
    hosts_ui.add_host_flow(prompter, console)
    names = {h.name for h in hosts_svc.list_hosts()}
    assert names == {"taken", "fresh"}
    assert "already exists" in console.export_text()


def test_edit_flow_blank_password_keeps_stored(make_prompter, console, db):
    host = hosts_svc.add_host(
        name="h1", address="10.0.0.1", username="u", remote_base_path="/m",
        auth_method="password", password="orig-pw",
    )
    before = db.execute(
        "SELECT encrypted_password FROM hosts WHERE id = ?", (host.id,)
    ).fetchone()["encrypted_password"]

    prompter = make_prompter(
        [host.id, "h1", "10.0.0.1", "22", "u", "/m", "password", ""]
    )
    hosts_ui.edit_host_flow(prompter, console)

    after = db.execute(
        "SELECT encrypted_password FROM hosts WHERE id = ?", (host.id,)
    ).fetchone()["encrypted_password"]
    assert after == before


def test_host_table_never_shows_the_password(db):
    hosts_svc.add_host(
        name="h1", address="10.0.0.1", username="u", remote_base_path="/m",
        auth_method="password", password="super-secret-pw",
    )
    from rich.console import Console

    rec = Console(record=True, width=200)
    rec.print(render.host_table(hosts_svc.list_hosts()))
    text = rec.export_text()
    assert "super-secret-pw" not in text
    assert "yes" in text  # password-stored indicator


def test_host_table_shows_host_key_state(db):
    import paramiko
    from rich.console import Console

    from comfy_network_tools import ssh

    hosts_svc.add_host(name="new", address="10.0.0.1", username="u", remote_base_path="/m")
    key = ssh.key_line(paramiko.ECDSAKey.generate())
    trusted = hosts_svc.add_host(
        name="old", address="10.0.0.2", username="u", remote_base_path="/m"
    )
    hosts_svc._pin_host_key(trusted.id, key)

    rec = Console(record=True, width=240)
    rec.print(render.host_table(hosts_svc.list_hosts()))
    text = rec.export_text()
    assert "untrusted" in text
    assert "SHA256:" in text


def _fake_connect_with_prompt(server_key_line, base_is_dir=True, changed=False):
    """A fake ssh.connect that exercises the host_key_prompt / changed-key paths."""
    from comfy_network_tools.errors import ConnectivityError

    def _connect(host, *, host_key_prompt=None, **kwargs):
        if changed:
            raise ConnectivityError("host-key-changed", "SHA256:new vs SHA256:old")
        if not host.host_key:
            if host_key_prompt is None or not host_key_prompt(host, "SHA256:testfp"):
                raise ConnectivityError("host-key-unknown", "SHA256:testfp was not trusted")
        fs = InMemoryRemoteFS()
        if base_is_dir:
            fs.add_dir(host.remote_base_path)
        fs.server_key_line = server_key_line
        return fs

    return _connect


def test_test_flow_prompts_for_fingerprint_and_pins_on_accept(
    make_prompter, console, db, monkeypatch
):
    from comfy_network_tools import ssh

    host = hosts_svc.add_host(name="h1", address="10.0.0.1", username="u", remote_base_path="/m")
    monkeypatch.setattr(ssh, "connect", _fake_connect_with_prompt("ssh-ed25519 AAAAPIN"))

    # _pick_host select -> host.id ; "Trust this host key and pin it?" confirm -> True
    hosts_ui.test_host_flow(make_prompter([host.id, True]), console)

    assert "SHA256:testfp" in console.export_text()
    assert hosts_svc.get_host(host.id).host_key == "ssh-ed25519 AAAAPIN"


def test_test_flow_fails_when_fingerprint_declined(make_prompter, console, db, monkeypatch):
    from comfy_network_tools import ssh

    host = hosts_svc.add_host(name="h1", address="10.0.0.1", username="u", remote_base_path="/m")
    monkeypatch.setattr(ssh, "connect", _fake_connect_with_prompt("x"))

    hosts_ui.test_host_flow(make_prompter([host.id, False]), console)

    assert "host-key-unknown" in console.export_text()
    assert hosts_svc.get_host(host.id).host_key is None


def test_test_flow_warns_on_changed_key(make_prompter, console, db, monkeypatch):
    from comfy_network_tools import ssh

    host = hosts_svc.add_host(name="h1", address="10.0.0.1", username="u", remote_base_path="/m")
    monkeypatch.setattr(ssh, "connect", _fake_connect_with_prompt("x", changed=True))

    hosts_ui.test_host_flow(make_prompter([host.id]), console)
    assert "HOST KEY CHANGED" in console.export_text()


def test_remove_flow_requires_confirmation(make_prompter, console, db):
    host = hosts_svc.add_host(name="h1", address="10.0.0.1", username="u", remote_base_path="/m")
    hosts_ui.remove_host_flow(make_prompter([host.id, False]), console)
    assert len(hosts_svc.list_hosts()) == 1
    hosts_ui.remove_host_flow(make_prompter([host.id, True]), console)
    assert hosts_svc.list_hosts() == []


def test_scan_flow_registers_a_host_only_model(make_prompter, console, tmp_path, db, monkeypatch):
    (tmp_path / "repo" / "loras").mkdir(parents=True)
    models_repo.set_repo_root(tmp_path / "repo")
    host = hosts_svc.add_host(name="h1", address="10.0.0.1", username="u", remote_base_path="/m")

    cloud = InMemoryRemoteFS()
    cloud.add_file("/m/loras/found.safetensors", 7)
    monkeypatch.setattr(distribution.hosts, "open_connection", lambda h, **kw: cloud)

    hosts_ui.scan_host_flow(make_prompter([host.id]), console)

    text = console.export_text()
    assert "registered" in text and "found.safetensors" in text
    model = next(m for m in models_repo.list_models() if m.filename == "found.safetensors")
    assert model.source == "host"
    assert [h.id for h in distribution.hosts_for_model(model.id)] == [host.id]
