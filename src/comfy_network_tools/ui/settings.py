"""The settings screen: repository root, categories, Hugging Face token, re-index."""

from __future__ import annotations

from .. import config, huggingface, models_repo, storage
from ..errors import CntError
from .prompts import Prompter


def _print_state(console) -> None:
    conn = storage.get_db()
    root = storage.get_repo_root(conn) or "[red]not set[/]"
    console.print(f"Repository root : {root}")
    console.print(f"Categories      : {', '.join(storage.get_categories(conn))}")
    status = huggingface.token_status()
    console.print(
        "HF token        : "
        + (f"{status.preview} ({status.source})" if status.configured else "not configured")
    )
    console.print(f"Key file        : {config.secret_key_path()}")


def run_reindex(console):
    """Re-index the repository. Ctrl+C leaves the previous index untouched."""
    try:
        changes = models_repo.reindex()
    except KeyboardInterrupt:
        console.print("\n[yellow]Re-index cancelled — the previous index is unchanged.[/]")
        return None
    console.print(
        f"[green]Re-indexed[/] (+{len(changes.added)} / -{len(changes.removed)} "
        f"/ ~{len(changes.updated)})"
    )
    return changes


def settings_screen(prompter: Prompter, console) -> None:
    while True:
        _print_state(console)
        action = prompter.select(
            "Settings",
            [
                ("Set repository root", "repo"),
                ("Edit categories", "categories"),
                ("Set Hugging Face token", "token"),
                ("Re-index repository", "reindex"),
                ("Back", "back"),
            ],
        )
        if action in (None, "back"):
            return
        try:
            if action == "repo":
                _set_repo(prompter, console)
            elif action == "categories":
                _set_categories(prompter, console)
            elif action == "token":
                _set_token(prompter, console)
            elif action == "reindex":
                run_reindex(console)
        except CntError as exc:
            console.print(f"[red]{exc}[/]")


def _set_repo(prompter: Prompter, console) -> None:
    path = prompter.text("Repository root path")
    if not path:
        return
    resolved = models_repo.set_repo_root(path)
    console.print(f"[green]Repository root set to {resolved}.[/]")
    if prompter.confirm("Re-index now?", default=True):
        run_reindex(console)


def _set_categories(prompter: Prompter, console) -> None:
    current = ", ".join(storage.get_categories(storage.get_db()))
    answer = prompter.text("Categories (comma-separated)", default=current)
    if answer is None:
        return
    storage.set_categories(storage.get_db(), [c.strip() for c in answer.split(",")])
    console.print("[green]Categories updated.[/]")


def _set_token(prompter: Prompter, console) -> None:
    token = prompter.password("Hugging Face token")
    if not token:
        return
    huggingface.save_token(token)
    console.print("[green]Token saved.[/]")
    result = huggingface.validate_token()
    if result.valid:
        console.print(f"[green]Token is valid[/] (account: {result.account or 'unknown'}).")
    else:
        console.print(f"[yellow]Token saved but could not be validated: {result.detail}[/]")
