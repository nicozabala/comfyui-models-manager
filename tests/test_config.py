from pathlib import Path

from comfy_network_tools import config


def test_paths_live_under_the_overridden_dirs():
    assert config.state_db_path().parent == config.data_dir()
    assert config.secret_key_path().name == "secret.key"
    assert config.hf_token_path().parent == config.config_dir()
    assert config.state_db_path().name == "state.db"


def test_effective_token_none_when_nothing_set():
    token, source = config.effective_hf_token()
    assert token is None
    assert source == "none"


def test_effective_token_reads_the_file():
    config.hf_token_path().write_text("hf_fromfile\n", encoding="utf-8")
    token, source = config.effective_hf_token()
    assert token == "hf_fromfile"
    assert source == "file"


def test_hf_token_env_overrides_file(monkeypatch):
    config.hf_token_path().write_text("hf_fromfile", encoding="utf-8")
    monkeypatch.setenv("HF_TOKEN", "hf_fromenv")
    token, source = config.effective_hf_token()
    assert token == "hf_fromenv"
    assert source == "env:HF_TOKEN"


def test_primary_env_wins_over_secondary(monkeypatch):
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "secondary")
    monkeypatch.setenv("HF_TOKEN", "primary")
    token, source = config.effective_hf_token()
    assert token == "primary"
    assert source == "env:HF_TOKEN"


def test_secondary_env_used_when_primary_absent(monkeypatch):
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "secondary")
    token, source = config.effective_hf_token()
    assert token == "secondary"
    assert source == "env:HUGGING_FACE_HUB_TOKEN"


def test_blank_file_is_treated_as_unset():
    config.hf_token_path().write_text("   \n", encoding="utf-8")
    assert config.stored_hf_token() is None
    assert isinstance(config.data_dir(), Path)
