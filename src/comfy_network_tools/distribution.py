"""Copy repository models to hosts, track placements, and build the coverage matrix."""

from __future__ import annotations

import posixpath
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from . import hosts, models_repo, storage
from .errors import ConnectivityError, SecretError, TransferError
from .hosts import Host
from .models_repo import Model
from .ssh import PART_SUFFIX, RemoteFS, download_atomic, upload_atomic

ConnectFn = Callable[[Host], RemoteFS]
ConflictFn = Callable[["TransferPlan"], bool]
ProgressFn = Callable[["TransferPlan", int, int], None]

# transfer outcomes
COPIED = "copied"
ALREADY_PRESENT = "already-present"
CONFLICT = "conflict"
FAILED = "failed"


@dataclass(frozen=True)
class TransferPlan:
    model: Model
    host: Host
    remote_path: str


@dataclass(frozen=True)
class TransferResult:
    plan: TransferPlan
    outcome: str
    detail: str | None = None


@dataclass(frozen=True)
class ReconcileResult:
    added_placements: list[tuple[str, str]]
    registered: list[tuple[str, str]]
    removed: list[tuple[str, str]]
    discrepancies: list[str]

    @property
    def is_empty(self) -> bool:
        return not (
            self.added_placements or self.registered or self.removed or self.discrepancies
        )


@dataclass(frozen=True)
class MatrixRow:
    model: Model
    present_host_ids: set[int]

    def coverage(self, host_ids: set[int]) -> int:
        return len(self.present_host_ids & host_ids)


@dataclass(frozen=True)
class Matrix:
    hosts: list[Host]
    rows: list[MatrixRow] = field(default_factory=list)
    empty_reason: str | None = None


def _dest(host: Host, model: Model) -> str:
    return posixpath.join(host.remote_base_path, model.category, model.filename)


def plan_transfers(models: list[Model], targets: list[Host]) -> list[TransferPlan]:
    return [
        TransferPlan(model=model, host=host, remote_path=_dest(host, model))
        for host in targets
        for model in models
    ]


# --- copy -------------------------------------------------------------------


def copy(
    models: list[Model],
    targets: list[Host],
    *,
    connect: ConnectFn | None = None,
    on_conflict: ConflictFn | None = None,
    progress: ProgressFn | None = None,
    host_key_prompt: object = None,
) -> list[TransferResult]:
    """Copy every model to every target host, one transfer at a time, host by host."""
    if connect is None:
        def connect(host: Host) -> RemoteFS:
            return hosts.open_connection(host, host_key_prompt=host_key_prompt)
    results: list[TransferResult] = []

    for host in targets:
        try:
            remote = connect(host)
        except (ConnectivityError, SecretError) as exc:
            reason = getattr(exc, "reason", str(exc))
            for model in models:
                results.append(
                    TransferResult(TransferPlan(model, host, _dest(host, model)), FAILED, reason)
                )
            continue
        try:
            for model in models:
                results.append(_transfer_one(remote, TransferPlan(model, host, _dest(host, model)),
                                             on_conflict, progress))
        finally:
            remote.close()
    return results


def _transfer_one(
    remote: RemoteFS,
    plan: TransferPlan,
    on_conflict: ConflictFn | None,
    progress: ProgressFn | None,
) -> TransferResult:
    local_path = models_repo.repo_root() / plan.model.category / plan.model.filename
    if not local_path.is_file():
        return TransferResult(plan, FAILED, "source file missing from repository")

    existing = remote.stat(plan.remote_path)
    if existing is not None and not existing.is_dir:
        if existing.size == plan.model.size_bytes:
            _record_placement(plan.model.id, plan.host.id)
            return TransferResult(plan, ALREADY_PRESENT)
        if not (on_conflict(plan) if on_conflict else False):
            return TransferResult(
                plan, CONFLICT, f"remote size {existing.size} != {plan.model.size_bytes}"
            )

    callback = (lambda done, total: progress(plan, done, total)) if progress else None
    try:
        remote.makedirs(posixpath.dirname(plan.remote_path))
        upload_atomic(remote, local_path, plan.remote_path, progress=callback)
    except TransferError as exc:
        return TransferResult(plan, FAILED, str(exc))

    _record_placement(plan.model.id, plan.host.id)
    return TransferResult(plan, COPIED)


def import_from_host(
    models: list[Model],
    source: Host,
    *,
    connect: ConnectFn | None = None,
    on_conflict: ConflictFn | None = None,
    progress: ProgressFn | None = None,
    host_key_prompt: object = None,
) -> list[TransferResult]:
    """Download models found on ``source`` but not in the repository, one at a time."""
    if connect is None:
        def connect(host: Host) -> RemoteFS:
            return hosts.open_connection(host, host_key_prompt=host_key_prompt)

    try:
        remote = connect(source)
    except (ConnectivityError, SecretError) as exc:
        reason = getattr(exc, "reason", str(exc))
        return [
            TransferResult(TransferPlan(model, source, _dest(source, model)), FAILED, reason)
            for model in models
        ]
    try:
        return [
            _download_one(remote, TransferPlan(model, source, _dest(source, model)),
                           on_conflict, progress)
            for model in models
        ]
    finally:
        remote.close()


def _download_one(
    remote: RemoteFS,
    plan: TransferPlan,
    on_conflict: ConflictFn | None,
    progress: ProgressFn | None,
) -> TransferResult:
    local_path = models_repo.repo_root() / plan.model.category / plan.model.filename
    if local_path.is_file():
        if local_path.stat().st_size == plan.model.size_bytes:
            models_repo.mark_local(plan.model.id)
            return TransferResult(plan, ALREADY_PRESENT)
        if not (on_conflict(plan) if on_conflict else False):
            return TransferResult(
                plan, CONFLICT,
                f"local size {local_path.stat().st_size} != {plan.model.size_bytes}",
            )

    remote_info = remote.stat(plan.remote_path)
    if remote_info is None or remote_info.is_dir:
        return TransferResult(plan, FAILED, "source file missing from host")

    callback = (lambda done, total: progress(plan, done, total)) if progress else None
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        download_atomic(remote, plan.remote_path, local_path, progress=callback)
    except TransferError as exc:
        return TransferResult(plan, FAILED, str(exc))

    models_repo.mark_local(plan.model.id)
    return TransferResult(plan, COPIED)


# --- placements ------------------------------------------------------------


def _record_placement(model_id: int, host_id: int) -> None:
    conn = storage.get_db()
    conn.execute(
        "INSERT INTO placements (model_id, host_id, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(model_id, host_id) DO UPDATE SET created_at = excluded.created_at",
        (model_id, host_id, storage.utcnow_iso()),
    )
    conn.commit()


def _delete_placement(model_id: int, host_id: int) -> None:
    conn = storage.get_db()
    conn.execute(
        "DELETE FROM placements WHERE model_id = ? AND host_id = ?", (model_id, host_id)
    )
    conn.commit()


def _placement_pairs() -> set[tuple[int, int]]:
    conn = storage.get_db()
    return {
        (r["model_id"], r["host_id"])
        for r in conn.execute("SELECT model_id, host_id FROM placements")
    }


def hosts_for_model(model_id: int) -> list[Host]:
    host_ids = {h for m, h in _placement_pairs() if m == model_id}
    return [h for h in hosts.list_hosts() if h.id in host_ids]


def models_for_host(host_id: int) -> list[Model]:
    model_ids = {m for m, h in _placement_pairs() if h == host_id}
    return [m for m in models_repo.list_models() if m.id in model_ids]


# --- reconcile ------------------------------------------------------------


def reconcile(
    host_id: int, *, connect: ConnectFn | None = None, host_key_prompt: object = None
) -> ReconcileResult:
    """Scan a host: align placements, register models found only there, flag mismatches."""
    if connect is None:
        def connect(host: Host) -> RemoteFS:
            return hosts.open_connection(host, host_key_prompt=host_key_prompt)
    host = hosts.get_host(host_id)
    if host is None:
        raise ConnectivityError("unreachable", f"no host with id {host_id}")

    by_key = {(m.category, m.filename): m for m in models_repo.list_models()}
    added_placements: list[tuple[str, str]] = []
    registered: list[tuple[str, str]] = []
    discrepancies: list[str] = []
    seen_model_ids: set[int] = set()
    existing_here = {m for m, h in _placement_pairs() if h == host_id}

    remote = connect(host)
    try:
        for category in models_repo.categories():
            category_dir = posixpath.join(host.remote_base_path, category)
            for name in remote.listdir(category_dir):
                if name.endswith(PART_SUFFIX):
                    continue
                info = remote.stat(posixpath.join(category_dir, name))
                if info is None or info.is_dir:
                    continue
                model = by_key.get((category, name))
                if model is not None and model.size_bytes == info.size:
                    seen_model_ids.add(model.id)
                    if model.id not in existing_here:
                        _record_placement(model.id, host_id)
                        added_placements.append((category, name))
                elif model is not None:
                    discrepancies.append(
                        f"{category}/{name} (host {info.size} != index {model.size_bytes})"
                    )
                else:
                    new_model = models_repo.register_host_model(category, name, info.size)
                    seen_model_ids.add(new_model.id)
                    _record_placement(new_model.id, host_id)
                    registered.append((category, name))
    finally:
        remote.close()

    removed: list[tuple[str, str]] = []
    models_by_id = {m.id: m for m in models_repo.list_models()}
    for model_id in existing_here - seen_model_ids:
        gone = models_by_id.get(model_id)
        _delete_placement(model_id, host_id)
        if gone is not None:
            removed.append((gone.category, gone.filename))

    models_repo.prune_orphan_host_models()

    return ReconcileResult(
        sorted(added_placements), sorted(registered), sorted(removed), sorted(discrepancies)
    )


# --- matrix ---------------------------------------------------------------


def matrix() -> Matrix:
    host_list = hosts.list_hosts()
    model_list = models_repo.list_models()
    if not host_list:
        return Matrix(hosts=host_list, empty_reason="no registered hosts")
    if not model_list:
        return Matrix(hosts=host_list, empty_reason="no indexed models")

    present: dict[int, set[int]] = defaultdict(set)
    for model_id, host_id in _placement_pairs():
        present[model_id].add(host_id)

    rows = [MatrixRow(model=m, present_host_ids=present[m.id]) for m in model_list]
    return Matrix(hosts=host_list, rows=rows)
