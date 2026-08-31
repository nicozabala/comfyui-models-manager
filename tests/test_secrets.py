import os
import sys

import pytest

from comfy_network_tools import config, secrets
from comfy_network_tools.errors import SecretError


def test_encrypt_then_decrypt_round_trips():
    ciphertext = secrets.encrypt("hunter2")
    assert ciphertext != "hunter2"
    assert secrets.decrypt(ciphertext) == "hunter2"


def test_encrypt_creates_the_key_file_with_restricted_permissions():
    assert not secrets.key_exists()
    secrets.encrypt("x")
    key_path = config.secret_key_path()
    assert key_path.is_file()
    if sys.platform != "win32":
        assert oct(os.stat(key_path).st_mode & 0o777) == oct(0o600)


def test_decrypt_without_key_file_raises_secret_error():
    with pytest.raises(SecretError):
        secrets.decrypt("Z0FBQUFBQm1mYWtlZmFrZWZha2U=")


def test_decrypt_garbage_with_key_present_raises_secret_error():
    secrets.encrypt("prime the key")
    with pytest.raises(SecretError):
        secrets.decrypt("not-a-valid-token")


def test_ciphertext_is_not_stable_but_decrypts_the_same():
    a = secrets.encrypt("same")
    b = secrets.encrypt("same")
    assert a != b
    assert secrets.decrypt(a) == secrets.decrypt(b) == "same"
