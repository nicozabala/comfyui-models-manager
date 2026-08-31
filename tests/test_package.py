import pytest

import comfy_network_tools
from comfy_network_tools.__main__ import main


def test_version_string():
    assert isinstance(comfy_network_tools.__version__, str)
    assert comfy_network_tools.__version__


def test_main_without_args_exits_zero_when_not_a_tty(capsys):
    # pytest runs with stdin detached, so run() takes the non-interactive path.
    assert main([]) == 0
    assert "interactive" in capsys.readouterr().out


def test_main_version_flag():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
