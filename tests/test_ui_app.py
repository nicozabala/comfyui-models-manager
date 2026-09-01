import sys

from comfy_network_tools import models_repo, storage
from comfy_network_tools.ui import app


def test_menu_items_hidden_until_repo_configured():
    keys_unconfigured = {key for _, key in app.available_menu_items(False)}
    assert keys_unconfigured == {"hosts", "settings", "exit"}

    keys_configured = {key for _, key in app.available_menu_items(True)}
    assert keys_configured == {"matrix", "models", "hosts", "download", "settings", "exit"}


def test_loop_exits_on_exit_choice(make_prompter, console, tmp_path, db):
    root = tmp_path / "repo"
    root.mkdir()
    models_repo.set_repo_root(root)
    prompter = make_prompter(["exit"])
    app.loop(prompter, console)
    assert prompter.calls == [("select", "Main menu")]


def test_first_run_prompts_to_configure_then_menu_unlocks(make_prompter, console, db, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    # first_run text -> path ; "Re-index now?" confirm -> False ; main menu -> exit
    prompter = make_prompter([str(root), False, "exit"])
    app.loop(prompter, console)
    assert models_repo.is_configured()


def test_first_run_skip_keeps_repo_unconfigured(make_prompter, console, db):
    prompter = make_prompter(["", "exit"])  # blank path skips, then exit
    app.loop(prompter, console)
    assert not models_repo.is_configured()


def test_loop_clears_terminal_between_actions_when_enabled(make_prompter, console, tmp_path, db):
    root = tmp_path / "repo"
    root.mkdir()
    models_repo.set_repo_root(root)
    storage.set_clean_terminal(db, True)
    calls = []
    console.clear = lambda *a, **k: calls.append(True)

    prompter = make_prompter(["hosts", "back", "exit"])
    app.loop(prompter, console)
    assert calls


def test_loop_does_not_clear_terminal_by_default(make_prompter, console, tmp_path, db):
    root = tmp_path / "repo"
    root.mkdir()
    models_repo.set_repo_root(root)
    calls = []
    console.clear = lambda *a, **k: calls.append(True)

    prompter = make_prompter(["hosts", "back", "exit"])
    app.loop(prompter, console)
    assert not calls


def test_run_swallows_keyboard_interrupt(monkeypatch, console):
    monkeypatch.setattr(app.sys.stdin, "isatty", lambda: True, raising=False)

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "loop", boom)
    monkeypatch.setattr(app, "QuestionaryPrompter", lambda: object())
    assert app.run() == 0


def test_run_non_tty_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert app.run() == 0
