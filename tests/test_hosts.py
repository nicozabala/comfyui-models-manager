import pytest

from comfy_network_tools import config, hosts, secrets, storage
from comfy_network_tools.errors import (
    ConnectivityError,
    DuplicateHost,
    HostValidationError,
    SecretError,
)
from comfy_network_tools.ssh import InMemoryRemoteFS

BASE = dict(name="gpu-1", address="10.0.0.5", username="ml", remote_base_path="/models")


def _raw_password(db, host_id):
    return db.execute(
        "SELECT encrypted_password FROM hosts WHERE id = ?", (host_id,)
    ).fetchone()["encrypted_password"]


# --- 4.1 add_host ---


def test_add_host_persists_and_lists(db):
    host = hosts.add_host(**BASE)
    assert host.id > 0
    assert [h.name for h in hosts.list_hosts()] == ["gpu-1"]
    assert host.port == 22 and host.auth_method == "agent" and not host.has_password


def test_add_host_rejects_duplicate_name(db):
    hosts.add_host(**BASE)
    with pytest.raises(DuplicateHost):
        hosts.add_host(**{**BASE, "address": "10.0.0.9"})
    assert len(hosts.list_hosts()) == 1


def test_add_host_rejects_duplicate_address_port_user(db):
    hosts.add_host(**BASE)
    with pytest.raises(DuplicateHost):
        hosts.add_host(**{**BASE, "name": "other"})


@pytest.mark.parametrize("field", ["name", "address", "username", "remote_base_path"])
def test_add_host_reports_each_missing_field(db, field):
    payload = {**BASE, field: "  "}
    with pytest.raises(HostValidationError) as excinfo:
        hosts.add_host(**payload)
    assert field in str(excinfo.value)


def test_add_password_host_stores_ciphertext_not_plaintext(db):
    host = hosts.add_host(**BASE, auth_method="password", password="s3cret-pw")
    assert host.has_password
    stored = _raw_password(db, host.id)
    assert stored is not None
    assert "s3cret-pw" not in stored
    assert secrets.decrypt(stored) == "s3cret-pw"


def test_key_auth_requires_a_key_path(db):
    with pytest.raises(HostValidationError):
        hosts.add_host(**BASE, auth_method="key")


# --- 4.2 edit_host / remove_host ---


def test_edit_preserves_other_fields(db):
    host = hosts.add_host(**BASE)
    edited = hosts.edit_host(host.id, remote_base_path="/data/models")
    assert edited.remote_base_path == "/data/models"
    assert edited.address == BASE["address"] and edited.username == BASE["username"]


def test_edit_password_host_blank_keeps_stored_password(db):
    host = hosts.add_host(**BASE, auth_method="password", password="orig-pw")
    before = _raw_password(db, host.id)
    hosts.edit_host(host.id, remote_base_path="/x")
    assert _raw_password(db, host.id) == before
    hosts.edit_host(host.id, password="")
    assert _raw_password(db, host.id) == before


def test_edit_new_password_reencrypts(db):
    host = hosts.add_host(**BASE, auth_method="password", password="orig-pw")
    hosts.edit_host(host.id, password="new-pw")
    assert secrets.decrypt(_raw_password(db, host.id)) == "new-pw"


def test_switching_away_from_password_clears_ciphertext(db):
    host = hosts.add_host(**BASE, auth_method="password", password="orig-pw")
    edited = hosts.edit_host(host.id, auth_method="agent")
    assert not edited.has_password
    assert _raw_password(db, host.id) is None


def test_remove_host_prunes_now_orphaned_host_model(db):
    from comfy_network_tools import models_repo

    host = hosts.add_host(**BASE)
    m = models_repo.register_host_model("loras", "only-here.safetensors", 4)
    db.execute(
        "INSERT INTO placements (model_id, host_id, created_at) VALUES (?, ?, ?)",
        (m.id, host.id, storage.utcnow_iso()),
    )
    db.commit()
    hosts.remove_host(host.id)
    assert models_repo.list_models() == []


def test_remove_host_deletes_placements_and_password(db):
    host = hosts.add_host(**BASE, auth_method="password", password="pw")
    db.execute(
        "INSERT INTO models (category, filename, size_bytes, indexed_at, source) "
        "VALUES ('loras', 'a', 1, ?, 'local')",
        (storage.utcnow_iso(),),
    )
    db.execute(
        "INSERT INTO placements (model_id, host_id, created_at) VALUES (1, ?, ?)",
        (host.id, storage.utcnow_iso()),
    )
    db.commit()
    hosts.remove_host(host.id)
    assert hosts.list_hosts() == []
    assert db.execute("SELECT COUNT(*) c FROM placements").fetchone()["c"] == 0


# --- 4.3 list_hosts ---


def test_list_hosts_empty(db):
    assert hosts.list_hosts() == []


def test_list_hosts_includes_last_check(db):
    host = hosts.add_host(**BASE)
    assert host.last_check_at is None and host.last_check_ok is None


# --- 4.4 test_connectivity ---


def _fs_with_base(is_dir=True):
    fs = InMemoryRemoteFS()
    if is_dir:
        fs.add_dir("/models")
    return fs


def test_connectivity_success(db):
    host = hosts.add_host(**BASE)
    result = hosts.test_connectivity(host.id, connect=lambda h: _fs_with_base())
    assert result.ok and result.reason is None
    assert hosts.get_host(host.id).last_check_ok is True


def test_connectivity_unreachable(db):
    host = hosts.add_host(**BASE)

    def boom(h):
        raise ConnectivityError("unreachable")

    result = hosts.test_connectivity(host.id, connect=boom)
    assert not result.ok and result.reason == "unreachable"
    assert hosts.get_host(host.id).last_check_reason == "unreachable"


def test_connectivity_missing_base_path(db):
    host = hosts.add_host(**BASE)
    result = hosts.test_connectivity(host.id, connect=lambda h: _fs_with_base(is_dir=False))
    assert not result.ok and result.reason == "missing/inaccessible base path"


def test_connectivity_records_detail_with_reason(db):
    host = hosts.add_host(**BASE)

    def boom(h):
        raise ConnectivityError("host-key-unknown", "SHA256:deadbeef was not trusted")

    result = hosts.test_connectivity(host.id, connect=boom)
    assert result.reason == "host-key-unknown"
    assert result.detail == "SHA256:deadbeef was not trusted"
    assert hosts.get_host(host.id).last_check_reason == (
        "host-key-unknown: SHA256:deadbeef was not trusted"
    )


# --- 11.4 host-key pinning ---


def _fake_ssh_connect(server_key_line, *, base_is_dir=True):
    def _connect(host, **kwargs):
        fs = _fs_with_base(is_dir=base_is_dir)
        fs.server_key_line = server_key_line
        return fs

    return _connect


def test_first_connect_pins_the_host_key(db, monkeypatch):
    from comfy_network_tools import ssh

    host = hosts.add_host(**BASE)
    assert hosts.get_host(host.id).host_key is None

    monkeypatch.setattr(ssh, "connect", _fake_ssh_connect("ssh-ed25519 AAAAKEY1"))
    hosts.test_connectivity(host.id)

    assert hosts.get_host(host.id).host_key == "ssh-ed25519 AAAAKEY1"


def test_second_connect_does_not_repin_a_changed_key(db, monkeypatch):
    from comfy_network_tools import ssh

    host = hosts.add_host(**BASE)
    monkeypatch.setattr(ssh, "connect", _fake_ssh_connect("ssh-ed25519 AAAAKEY1"))
    hosts.test_connectivity(host.id)

    monkeypatch.setattr(ssh, "connect", _fake_ssh_connect("ssh-ed25519 DIFFERENT"))
    hosts.test_connectivity(host.id)
    assert hosts.get_host(host.id).host_key == "ssh-ed25519 AAAAKEY1"


def test_editing_address_drops_the_pinned_key(db):
    host = hosts.add_host(**BASE)
    hosts._pin_host_key(host.id, "ssh-ed25519 AAAAKEY1")
    assert hosts.get_host(host.id).host_key == "ssh-ed25519 AAAAKEY1"

    hosts.edit_host(host.id, address="10.9.9.9")
    assert hosts.get_host(host.id).host_key is None


# --- 4.5 resolve_password ---


def test_resolve_password_returns_plaintext(db):
    host = hosts.add_host(**BASE, auth_method="password", password="pw-123")
    assert hosts.resolve_password(host.id) == "pw-123"


def test_resolve_password_without_stored_password_raises(db):
    host = hosts.add_host(**BASE)
    with pytest.raises(SecretError):
        hosts.resolve_password(host.id)


def test_resolve_password_with_missing_key_file_raises(db):
    host = hosts.add_host(**BASE, auth_method="password", password="pw-123")
    config.secret_key_path().unlink()
    with pytest.raises(SecretError):
        hosts.resolve_password(host.id)
