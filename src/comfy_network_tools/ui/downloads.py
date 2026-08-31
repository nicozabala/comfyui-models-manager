"""The Hugging Face download screen."""

from __future__ import annotations

from .. import huggingface, models_repo
from ..errors import CntError, HuggingFaceAuthError
from .prompts import Prompter


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{num} B"


def download_screen(prompter: Prompter, console, *, service=huggingface) -> None:
    status = service.token_status()
    if status.configured:
        token_line = f"{status.preview} ({status.source})"
    else:
        token_line = "not configured"
    console.print(f"[dim]Hugging Face token: {token_line}[/]")

    ref_text = prompter.text("Reference (owner/name, or a huggingface.co URL)")
    if not ref_text:
        return

    try:
        reference = service.resolve_reference(ref_text)
        files = service.list_files(reference)
    except HuggingFaceAuthError as exc:
        console.print(f"[red]A valid token with access is required: {exc}[/]")
        return
    except CntError as exc:
        console.print(f"[red]{exc}[/]")
        return

    if not files:
        console.print("[yellow]No downloadable files found for that reference.[/]")
        return

    chosen = prompter.checkbox(
        "Files to download",
        [(f"{f.path}  ({_human_size(f.size)})", f.path) for f in files],
    )
    if not chosen:
        console.print("[dim]Nothing selected.[/]")
        return

    category = prompter.select("Target category", models_repo.categories())
    if category is None:
        return

    if not prompter.confirm(f"Download {len(chosen)} file(s) into {category}?", default=True):
        return

    try:
        outcomes = service.download(reference, list(chosen), category)
    except HuggingFaceAuthError as exc:
        console.print(f"[red]A valid token with access is required: {exc}[/]")
        return
    except CntError as exc:
        console.print(f"[red]Download failed: {exc}[/]")
        return

    for outcome in outcomes:
        tag = {"downloaded": "green", "skipped": "cyan"}.get(outcome.status, "red")
        console.print(
            f"[{tag}]{outcome.status}[/] {outcome.filename}"
            + (f" — {outcome.detail}" if outcome.detail else "")
        )
