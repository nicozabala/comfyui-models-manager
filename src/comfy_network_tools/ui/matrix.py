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
    matrix: Matrix,
    category: str | None,
    fragment: str | None,
    host_ids: set[int] | None = None,
) -> list[MatrixRow]:
    rows = matrix.rows
    if category:
        rows = [r for r in rows if r.model.category == category]
    if fragment:
        needle = fragment.lower()
        rows = [r for r in rows if needle in r.model.filename.lower()]
    if host_ids:
        rows = [r for r in rows if host_ids <= r.present_host_ids]
    return rows


def matrix_screen(
    prompter: Prompter,
    console,
    *,
    copy_model: Callable[[object], None] | None = None,
    import_model: Callable[[object], None] | None = None,
) -> None:
    copy_model = copy_model or (lambda model: _copy_model_flow(prompter, console, model))
    import_model = import_model or (lambda model: _import_model_flow(prompter, console, model))
    category: str | None = None
    fragment: str | None = None
    host_ids: set[int] | None = None

    while True:
        matrix = distribution.matrix()
        if matrix.empty_reason:
            console.print(f"[yellow]Nothing to show: {matrix.empty_reason}.[/]")
            return

        visible = filter_rows(matrix, category, fragment, host_ids)
        console.print(
            render.matrix_table(
                Matrix(hosts=matrix.hosts, rows=visible, empty_reason=None)
            )
        )
        if category or fragment or host_ids:
            bits = [f"category={category or '*'}", f"name~{fragment or '*'}"]
            if host_ids:
                names = ",".join(sorted(h.name for h in matrix.hosts if h.id in host_ids))
                bits.append(f"hosts⊇{{{names}}}")
            console.print(f"[dim]filter: {' '.join(bits)}[/]")

        action = prompter.select(
            "Matrix",
            [
                ("Filter", "filter"),
                ("Copy a model to hosts", "copy"),
                ("Copy a model from a host to the repository", "import"),
                ("Back", "back"),
            ],
        )
        if action in (None, "back"):
            return
        if action == "filter":
            picked = prompter.select("Category", [ALL, *models_repo.categories()])
            category = None if picked in (None, ALL) else picked
            fragment = prompter.text("Name contains", default=fragment or "") or None
            host_choice = prompter.checkbox(
                "Hosts (model must be present on all selected)",
                [(h.name, h.id) for h in matrix.hosts],
                checked=host_ids,
            )
            host_ids = set(host_choice) or None
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
        elif action == "import":
            host_only = [r for r in visible if r.model.source == "host"]
            if not host_only:
                console.print("[dim]No host-only models to import.[/]")
                continue
            model_id = prompter.select(
                "Which model?",
                [(f"{r.model.category}/{r.model.filename}", r.model.id) for r in host_only],
            )
            if model_id is None:
                continue
            model = models_repo.get_model(model_id)
            try:
                import_model(model)
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


def _import_model_flow(prompter: Prompter, console, model) -> None:
    candidates = distribution.hosts_for_model(model.id)
    if not candidates:
        console.print("[dim]No host currently has this model.[/]")
        return
    if len(candidates) == 1:
        source = candidates[0]
    else:
        host_id = prompter.select(
            f"Copy {model.category}/{model.filename} from:",
            [(h.name, h.id) for h in candidates],
        )
        if host_id is None:
            return
        source = next(h for h in candidates if h.id == host_id)

    with render.copy_progress() as progress:
        bars: dict[tuple[int, int], int] = {}

        def on_progress(plan, done: int, total: int) -> None:
            key = (plan.model.id, plan.host.id)
            if key not in bars:
                bars[key] = progress.add_task(
                    f"{plan.host.name} → repository: {plan.model.filename}", total=total
                )
            progress.update(bars[key], completed=done, total=total)

        results = distribution.import_from_host(
            [model],
            source,
            on_conflict=lambda plan: prompter.confirm(
                f"The repository already has a different {plan.model.filename}; overwrite?"
            ),
            progress=on_progress,
            host_key_prompt=host_key_prompt(prompter, console),
        )
    console.print(render.transfer_results_table(results))
    for result in results:
        if result.outcome == "failed" and result.detail == "host-key-changed":
            console.print(
                f"[bold red]HOST KEY CHANGED for {result.plan.host.name} "
                "— that import was refused.[/]"
            )
