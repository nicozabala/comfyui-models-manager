import os
import sys

from comfy_network_tools import config


def test_write_hf_token_persists_and_is_readable_back():
    config.write_hf_token("  hf_secretvalue123  ")
    assert config.stored_hf_token() == "hf_secretvalue123"


def test_write_hf_token_restricts_permissions_on_posix():
    path = config.write_hf_token("hf_secretvalue123")
    if sys.platform != "win32":
        assert oct(os.stat(path).st_mode & 0o777) == oct(0o600)


def test_mask_token_hides_the_secret():
    masked = config.mask_token("hf_abcdefghijklmnop")
    assert "abcdefghijklmnop" not in masked
    assert masked.startswith("hf_")
    assert masked.endswith("mnop")
    assert "..." in masked


def test_mask_token_short_value_is_all_stars():
    assert config.mask_token("short") == "*****"
