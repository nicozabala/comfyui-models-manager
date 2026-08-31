import paramiko
import pytest

from comfy_network_tools import ssh
from comfy_network_tools.errors import ConnectivityError, SecretError
from comfy_network_tools.hosts import Host
from comfy_network_tools.ssh import (
    InMemoryRemoteFS,
    _HostKeyDeclined,
    _TofuPolicy,
    build_auth_kwargs,
    fingerprint,
    fingerprint_of_line,
    key_line,
)


def make_host(**overrides) -> Host:
    base = dict(
        id=1,
        name="h",
        address="10.0.0.1",
        port=22,
        username="u",
        auth_method="agent",
        private_key_path=None,
        has_password=False,
        remote_base_path="/models",
        trust_host_key=False,
        host_key=None,
        last_check_at=None,
        last_check_ok=None,
        last_check_reason=None,
    )
    base.update(overrides)
    return Host(**base)


@pytest.fixture
def server_key():
    return paramiko.ECDSAKey.generate()


class _FakeClient:
    def __init__(self):
        self._hk = paramiko.hostkeys.HostKeys()

    def get_host_keys(self):
        return self._hk


# --- host key: fingerprint / key line helpers ---


def test_fingerprint_and_line_round_trip(server_key):
    line = key_line(server_key)
    assert line.startswith(server_key.get_name())
    assert fingerprint(server_key).startswith("SHA256:")
    assert fingerprint_of_line(line) == fingerprint(server_key)
    assert fingerprint_of_line(None) is None
    assert fingerprint_of_line("garbage") is None


# --- _TofuPolicy ---


def test_tofu_declines_without_a_prompt(server_key):
    policy = _TofuPolicy(make_host(), prompt=None)
    with pytest.raises(_HostKeyDeclined):
        policy.missing_host_key(_FakeClient(), "10.0.0.1", server_key)


def test_tofu_accepts_when_prompt_confirms(server_key):
    client = _FakeClient()
    policy = _TofuPolicy(make_host(), prompt=lambda host, fp: True)
    policy.missing_host_key(client, "10.0.0.1", server_key)
    assert policy.accepted_key is server_key
    assert client.get_host_keys().lookup("10.0.0.1")


def test_tofu_auto_accepts_when_trust_flag_set(server_key):
    policy = _TofuPolicy(make_host(trust_host_key=True), prompt=None)
    policy.missing_host_key(_FakeClient(), "10.0.0.1", server_key)
    assert policy.accepted_key is server_key


def test_tofu_declines_when_prompt_refuses(server_key):
    policy = _TofuPolicy(make_host(), prompt=lambda host, fp: False)
    with pytest.raises(_HostKeyDeclined):
        policy.missing_host_key(_FakeClient(), "10.0.0.1", server_key)


# --- connect() error mapping ---


@pytest.mark.parametrize(
    "raised, expected_reason",
    [
        (paramiko.AuthenticationException("bad creds"), "authentication"),
        (TimeoutError("slow"), "timeout"),
        (paramiko.SSHException("no kex"), "unreachable"),
        (OSError("refused"), "unreachable"),
        (_HostKeyDeclined("SHA256:zzz"), "host-key-unknown"),
    ],
)
def test_connect_maps_exceptions_to_reasons(monkeypatch, raised, expected_reason):
    class Boom:
        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, policy):
            pass

        def get_host_keys(self):
            return paramiko.hostkeys.HostKeys()

        def connect(self, **kw):
            raise raised

    monkeypatch.setattr(ssh.paramiko, "SSHClient", Boom)
    with pytest.raises(ConnectivityError) as excinfo:
        ssh.connect(make_host())
    assert excinfo.value.reason == expected_reason


def test_connect_maps_changed_host_key(monkeypatch, server_key):
    other = paramiko.ECDSAKey.generate()

    class Changed:
        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, policy):
            pass

        def get_host_keys(self):
            return paramiko.hostkeys.HostKeys()

        def connect(self, **kw):
            raise paramiko.BadHostKeyException("10.0.0.1", server_key, other)

    monkeypatch.setattr(ssh.paramiko, "SSHClient", Changed)
    host = make_host(host_key=key_line(other))
    with pytest.raises(ConnectivityError) as excinfo:
        ssh.connect(host)
    assert excinfo.value.reason == "host-key-changed"
    assert fingerprint(server_key) in str(excinfo.value)


def test_connect_maps_sftp_failure(monkeypatch):
    class NoSftp:
        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, policy):
            pass

        def get_host_keys(self):
            return paramiko.hostkeys.HostKeys()

        def connect(self, **kw):
            pass

        def open_sftp(self):
            raise paramiko.SSHException("subsystem request failed")

        def close(self):
            pass

    monkeypatch.setattr(ssh.paramiko, "SSHClient", NoSftp)
    with pytest.raises(ConnectivityError) as excinfo:
        ssh.connect(make_host())
    assert excinfo.value.reason == "sftp-unavailable"


# --- auth kwargs (unchanged behaviour) ---


def test_agent_auth_kwargs():
    kw = build_auth_kwargs(make_host(auth_method="agent"))
    assert kw == {"allow_agent": True, "look_for_keys": True}


def test_key_auth_kwargs():
    kw = build_auth_kwargs(make_host(auth_method="key", private_key_path="/home/u/id_ed25519"))
    assert kw["key_filename"] == "/home/u/id_ed25519"
    assert kw["look_for_keys"] is False


def test_password_auth_uses_stored_password():
    kw = build_auth_kwargs(
        make_host(auth_method="password", has_password=True),
        password_resolver=lambda host_id: "stored-pw",
    )
    assert kw["password"] == "stored-pw"


def test_password_auth_falls_back_to_prompt_when_key_missing():
    def resolver(host_id):
        raise SecretError("no key file")

    kw = build_auth_kwargs(
        make_host(auth_method="password"),
        password_resolver=resolver,
        prompt_password=lambda host: "typed-pw",
    )
    assert kw["password"] == "typed-pw"


def test_password_auth_with_no_password_available_raises():
    with pytest.raises(ConnectivityError) as excinfo:
        build_auth_kwargs(
            make_host(auth_method="password"),
            password_resolver=lambda host_id: (_ for _ in ()).throw(SecretError("x")),
        )
    assert excinfo.value.reason == "authentication"


# --- makedirs semantics (fake-backed) ---


def test_makedirs_creates_only_missing_segments():
    fs = InMemoryRemoteFS()
    fs.add_dir("/models/loras")
    fs.makedirs("/models/loras/flux/v1")
    assert fs.stat("/models/loras/flux").is_dir
    assert fs.stat("/models/loras/flux/v1").is_dir
