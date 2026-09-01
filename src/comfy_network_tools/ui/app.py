"""Main menu loop and the console entry point."""

from __future__ import annotations

import sys

from .. import models_repo, storage
from . import downloads, matrix, render, settings
from . import hosts as hosts_ui
from .prompts import Prompter, QuestionaryPrompter

#: (label, key, requires a configured repository)
MENU: list[tuple[str, str, bool]] = [
    ("View model ↔ host matrix", "matrix", True),
    ("Manage models / repository", "models", True),
    ("Manage hosts", "hosts", False),
    ("Download from Hugging Face", "download", True),
    ("Settings", "settings", False),
    ("Exit", "exit", False),
]


def available_menu_items(repo_configured: bool) -> list[tuple[str, str]]:
    return [
        (label, key)
        for label, key, needs_repo in MENU
        if repo_configured or not needs_repo
    ]


def first_run_configure(prompter: Prompter, console) -> None:
    console.print(
        "[bold]Welcome to comfy-network-tools.[/]\n"
        "No model repository is configured yet. Set one now, or choose "
        "'Skip' to configure it later from Settings."
    )
    path = prompter.text("Repository root path (blank to skip)")
    if not path:
        return
    try:
        resolved = models_repo.set_repo_root(path)
    except Exception as exc:  # noqa: BLE001 - show any failure, stay unconfigured
        console.print(f"[red]{exc}[/]")
        return
    console.print(f"[green]Repository root set to {resolved}.[/]")
    if prompter.confirm("Re-index now?", default=True):
        settings.run_reindex(console)


def loop(prompter: Prompter, console) -> None:
    if not models_repo.is_configured():
        first_run_configure(prompter, console)

    while True:
        items = available_menu_items(models_repo.is_configured())
        choice = prompter.select("Main menu", items)
        if choice in (None, "exit"):
            return
        if choice == "matrix":
            matrix.matrix_screen(prompter, console)
        elif choice == "models":
            _models_screen(prompter, console)
        elif choice == "hosts":
            hosts_ui.host_screen(prompter, console)
        elif choice == "download":
            downloads.download_screen(prompter, console)
        elif choice == "settings":
            settings.settings_screen(prompter, console)
        if storage.get_clean_terminal(storage.get_db()):
            console.clear()


def _models_screen(prompter: Prompter, console) -> None:
    console.print(render.model_table(models_repo.list_models()))
    action = prompter.select(
        "Repository", [("Re-index", "reindex"), ("Back", "back")]
    )
    if action == "reindex":
        settings.run_reindex(console)


def run() -> int:
    if not sys.stdin.isatty():
        render.console.print(
            "comfy-network-tools is interactive — run it from a terminal."
        )
        return 0
    prompter = QuestionaryPrompter()
    try:
        loop(prompter, render.console)
    except (KeyboardInterrupt, EOFError):
        render.console.print()
    return 0
