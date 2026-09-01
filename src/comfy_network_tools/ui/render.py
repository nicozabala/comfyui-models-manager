"""rich rendering helpers: the shared console and the app's tables."""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from ..distribution import Matrix, TransferResult
from ..hosts import Host
from ..models_repo import Model

console = Console()


def copy_progress() -> Progress:
    """A `rich.Progress` with one bar per file: label, bar, %, bytes, speed."""
    return Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    )


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def model_table(models: list[Model]) -> Table:
    """One heading row per category (in first-seen order) over that category's models.

    Assumes ``models`` is already sorted by ``(category, filename)`` — the order
    ``models_repo.list_models()`` returns — so each category's rows are contiguous.
    """
    table = Table(title="Repository models")
    table.add_column("File")
    table.add_column("Size", justify="right")
    table.add_column("Source")

    current_category: str | None = None
    for model in models:
        if model.category != current_category:
            if current_category is not None:
                table.add_section()
            table.add_row(f"[bold cyan]{model.category}[/]", "", "")
            current_category = model.category
        table.add_row(model.filename, _human_size(model.size_bytes), model.source)
    return table


def host_table(hosts: list[Host]) -> Table:
    table = Table(title="Hosts")
    table.add_column("Name")
    table.add_column("Address")
    table.add_column("User")
    table.add_column("Auth")
    table.add_column("Password", justify="center")
    table.add_column("Host key")
    table.add_column("Base path")
    table.add_column("Last check")
    for host in hosts:
        if host.last_check_ok is None:
            last = "-"
        else:
            last = "[green]ok[/]" if host.last_check_ok else f"[red]{host.last_check_reason}[/]"
        fingerprint = host.host_key_fingerprint
        table.add_row(
            host.name,
            f"{host.address}:{host.port}",
            host.username,
            host.auth_method,
            "yes" if host.has_password else "-",
            fingerprint or "[dim]untrusted[/]",
            host.remote_base_path,
            last,
        )
    return table


def matrix_table(matrix: Matrix) -> Table:
    table = Table(title="Model ↔ host coverage")
    table.add_column("Category")
    table.add_column("File")
    for host in matrix.hosts:
        table.add_column(host.name, justify="center")
    table.add_column("Cov.", justify="right")
    host_ids = {h.id for h in matrix.hosts}
    for row in matrix.rows:
        cells = [
            "[green]✓[/]" if host.id in row.present_host_ids else "[dim]·[/]"
            for host in matrix.hosts
        ]
        table.add_row(
            row.model.category,
            row.model.filename,
            *cells,
            f"{row.coverage(host_ids)}/{len(matrix.hosts)}",
        )
    return table


def transfer_results_table(results: list[TransferResult]) -> Table:
    table = Table(title="Transfer results")
    table.add_column("Host")
    table.add_column("Model")
    table.add_column("Outcome")
    table.add_column("Detail")
    styles = {
        "copied": "green",
        "already-present": "cyan",
        "conflict": "yellow",
        "failed": "red",
    }
    for result in results:
        style = styles.get(result.outcome, "")
        table.add_row(
            result.plan.host.name,
            f"{result.plan.model.category}/{result.plan.model.filename}",
            f"[{style}]{result.outcome}[/]" if style else result.outcome,
            result.detail or "",
        )
    return table
