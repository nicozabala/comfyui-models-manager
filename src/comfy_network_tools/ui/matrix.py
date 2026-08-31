"""The model ↔ host matrix screen, with filters and a per-model copy action."""

from __future__ import annotations

from collections.abc import Callable

from .. import distribution, models_repo
from .. import hosts as hosts_svc
from ..distribution import Matrix, MatrixRow
from ..errors import CntError
from . import render
from .prompts import Prompter, host_key_prompt

ALL = "— all —"


def filter_rows(
    matrix: Matrix, category: str | None, fragment: str | None
) -> list[MatrixRow]:
    rows = matrix.rows
    if category:
        rows = [r for r in rows if r.model.category == category]
    if fragment:
        needle = fragment.lower()
        rows = [r for r in rows if needle in r.model.filename.lower()]
    return rows


def matrix_screen(
    prompter: Prompter,
    console,
    *,
    copy_model: Callable[[object], None] | None = None,
) -> None:
    copy_model = copy_model or (lambda model: _copy_model_flow(prompter, console, model))
    category: str | None = None
    fragment: str | None = None

    while True:
        matrix = distribution.matrix()
        if matrix.empty_reason:
            console.print(f"[yellow]Nothing to show: {matrix.empty_reason}.[/]")
            return

        visible = filter_rows(matrix, category, fragment)
        console.print(
            render.matrix_table(
                Matrix(hosts=matrix.hosts, rows=visible, empty_reason=None)
            )
        )
        if category or fragment:
            console.print(f"[dim]filter: category={category or '*'} name~{fragment or '*'}[/]")

        action = prompter.select(
            "Matrix",
            [("Filter", "filter"), ("Copy a model to hosts", "copy"), ("Back", "back")],
        )
        if action in (None, "back"):
            return
        if action == "filter":
            picked = prompter.select("Category", [ALL, *models_repo.categories()])
            category = None if picked in (None, ALL) else picked
            fragment = prompter.text("Name contains", default=fragment or "") or None
        elif action == "copy":
            if not visible:
                console.print("[dim]No rows to copy.[/]")
                continue
            model_id = prompter.select(
                "Which model?",
                [(f"{r.model.category}/{r.model.filename}", r.model.id) for r in visible],
            )
            if model_id is None:
                continue
            model = models_repo.get_model(model_id)
            try:
                copy_model(model)
            except CntError as exc:
                console.print(f"[red]{exc}[/]")


def _copy_model_flow(prompter: Prompter, console, model) -> None:
    hosts = hosts_svc.list_hosts()
    if not hosts:
        console.print("[dim]No hosts to copy to.[/]")
        return
    host_ids = prompter.checkbox(
        f"Copy {model.category}/{model.filename} to:", [(h.name, h.id) for h in hosts]
    )
    targets = [h for h in hosts if h.id in set(host_ids)]
    if not targets:
        console.print("[dim]No hosts selected.[/]")
        return

    with render.copy_progress() as progress:
        bars: dict[tuple[int, int], int] = {}

        def on_progress(plan, done: int, total: int) -> None:
            key = (plan.model.id, plan.host.id)
            if key not in bars:
                bars[key] = progress.add_task(
                    f"{plan.host.name}: {plan.model.filename}", total=total
                )
            progress.update(bars[key], completed=done, total=total)

        results = distribution.copy(
            [model],
            targets,
            on_conflict=lambda plan: prompter.confirm(
                f"{plan.host.name} already has a different {plan.model.filename}; overwrite?"
            ),
            progress=on_progress,
            host_key_prompt=host_key_prompt(prompter, console),
        )
    console.print(render.transfer_results_table(results))
    for result in results:
        if result.outcome == "failed" and result.detail == "host-key-changed":
            console.print(
                f"[bold red]HOST KEY CHANGED for {result.plan.host.name} "
                "— that copy was refused.[/]"
            )
