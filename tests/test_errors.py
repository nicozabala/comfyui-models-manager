import pytest

from comfy_network_tools import errors

ALL_ERRORS = [
    errors.RepositoryNotConfigured,
    errors.InvalidRepositoryPath,
    errors.DuplicateHost,
    errors.HostValidationError,
    errors.ConnectivityError,
    errors.TransferError,
    errors.SecretError,
    errors.HuggingFaceAuthError,
    errors.HuggingFaceNotFound,
    errors.DownloadError,
]


@pytest.mark.parametrize("exc", ALL_ERRORS)
def test_every_domain_error_subclasses_cnterror(exc):
    assert issubclass(exc, errors.CntError)
    assert issubclass(exc, Exception)


def test_cnterror_can_be_raised_and_caught():
    with pytest.raises(errors.CntError):
        raise errors.SecretError("no key")


def test_connectivity_error_keeps_reason_and_detail():
    exc = errors.ConnectivityError("host-key-unknown", "SHA256:abc not trusted")
    assert exc.reason == "host-key-unknown"
    assert str(exc) == "SHA256:abc not trusted"
    assert "host-key-changed" in errors.ConnectivityError.REASONS
    assert "sftp-unavailable" in errors.ConnectivityError.REASONS


def test_connectivity_error_defaults_message_to_reason():
    exc = errors.ConnectivityError("unreachable")
    assert str(exc) == "unreachable"
