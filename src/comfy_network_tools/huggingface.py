"""Hugging Face integration: token handling, reference parsing, listing, downloading.

Every call into ``huggingface_hub`` is wrapped here so there is one place to adapt
to API changes and one place that turns its errors into our typed exceptions.
Downloads land directly in ``<repo root>/<category>/`` and are handed to the model
index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import config, models_repo
from .errors import DownloadError, HuggingFaceAuthError, HuggingFaceNotFound


@dataclass(frozen=True)
class HFReference:
    repo_id: str
    revision: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class HFFile:
    path: str
    size: int


@dataclass(frozen=True)
class TokenStatus:
    configured: bool
    source: str
    preview: str | None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    account: str | None
    detail: str | None


@dataclass(frozen=True)
class DownloadOutcome:
    filename: str
    category: str
    status: str  # "downloaded" | "skipped" | "failed"
    detail: str | None = None


DOWNLOADED = "downloaded"
SKIPPED = "skipped"
FAILED = "failed"

_REFERENCE_RE = re.compile(
    r"^(?:https?://)?(?:huggingface\.co/)?"
    r"(?P<repo>[^/\s@]+/[^/\s@]+?)"
    r"(?:@(?P<rev_at>[^/\s@]+))?"
    r"(?:/(?:blob|resolve)/(?P<rev_path>[^/\s]+)/(?P<path>[^\s]+))?$"
)


# --- token ---------------------------------------------------------------


def save_token(token: str) -> None:
    if not token or not token.strip():
        raise HuggingFaceAuthError("the token must not be empty")
    config.write_hf_token(token)


def token_status() -> TokenStatus:
    token, source = config.effective_hf_token()
    if token is None:
        return TokenStatus(configured=False, source=source, preview=None)
    return TokenStatus(configured=True, source=source, preview=config.mask_token(token))


def validate_token(*, whoami=None) -> ValidationResult:
    token, _ = config.effective_hf_token()
    if token is None:
        return ValidationResult(valid=False, account=None, detail="no token configured")
    whoami = whoami or _default_whoami
    try:
        info = whoami(token)
    except Exception as exc:  # noqa: BLE001 - any failure means "not valid"
        return ValidationResult(valid=False, account=None, detail=str(exc))
    account = None
    if isinstance(info, dict):
        account = info.get("name") or info.get("fullname")
    return ValidationResult(valid=True, account=account, detail=None)


def _default_whoami(token: str):
    from huggingface_hub import HfApi

    return HfApi().whoami(token=token)


# --- references & listing ------------------------------------------------


def resolve_reference(ref: str) -> HFReference:
    match = _REFERENCE_RE.match(ref.strip())
    if not match:
        raise HuggingFaceNotFound(f"not a valid Hugging Face reference: {ref!r}")
    return HFReference(
        repo_id=match.group("repo"),
        revision=match.group("rev_path") or match.group("rev_at"),
        filename=match.group("path"),
    )


def list_files(ref: str | HFReference, *, api=None) -> list[HFFile]:
    reference = ref if isinstance(ref, HFReference) else resolve_reference(ref)
    api = api or _default_api()
    try:
        info = api.model_info(
            reference.repo_id, revision=reference.revision, files_metadata=True
        )
    except Exception as exc:  # noqa: BLE001 - normalised below
        translated = _translate_hf_error(exc, reference)
        if isinstance(translated, DownloadError):
            raise HuggingFaceNotFound(
                f"could not read {reference.repo_id}: {exc}"
            ) from exc
        raise translated from exc

    files = sorted(
        (
            HFFile(path=sibling.rfilename, size=int(getattr(sibling, "size", 0) or 0))
            for sibling in (info.siblings or [])
        ),
        key=lambda f: f.path,
    )
    if reference.filename:
        files = [f for f in files if f.path == reference.filename]
        if not files:
            raise HuggingFaceNotFound(
                f"{reference.filename!r} is not in {reference.repo_id}"
            )
    return files


def _default_api():
    from huggingface_hub import HfApi

    return HfApi(token=config.effective_hf_token()[0])


# --- download ----------------------------------------------------------------


def download(
    ref: str | HFReference,
    files: list[str],
    category: str,
    *,
    overwrite: bool = False,
    api=None,
    hf_download=None,
) -> list[DownloadOutcome]:
    reference = ref if isinstance(ref, HFReference) else resolve_reference(ref)
    if category not in models_repo.categories():
        raise DownloadError(f"unknown category: {category!r}")

    target_dir = models_repo.repo_root() / category
    target_dir.mkdir(parents=True, exist_ok=True)
    hf_download = hf_download or _default_hf_download
    known = {f.path: f for f in list_files(reference, api=api)}

    outcomes: list[DownloadOutcome] = []
    for filename in files:
        dest = target_dir / Path(filename).name
        expected = known.get(filename)
        if (
            not overwrite
            and dest.is_file()
            and expected is not None
            and dest.stat().st_size == expected.size
        ):
            models_repo.index_file(
                category, dest.name, dest.stat().st_size, source="huggingface"
            )
            outcomes.append(
                DownloadOutcome(filename, category, SKIPPED, "already downloaded")
            )
            continue

        try:
            result_path = hf_download(
                repo_id=reference.repo_id,
                filename=filename,
                revision=reference.revision,
                local_dir=str(target_dir),
                token=config.effective_hf_token()[0],
            )
        except Exception as exc:  # noqa: BLE001 - normalised below
            _cleanup_partial(dest)
            raise _translate_hf_error(exc, reference) from exc

        landed = Path(result_path)
        size = landed.stat().st_size
        models_repo.index_file(category, landed.name, size, source="huggingface")
        outcomes.append(DownloadOutcome(filename, category, DOWNLOADED))
    return outcomes


def _default_hf_download(**kwargs):
    from huggingface_hub import hf_hub_download

    return hf_hub_download(**kwargs)


def _cleanup_partial(dest: Path) -> None:
    for candidate in (dest, dest.with_name(dest.name + ".incomplete")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def _translate_hf_error(exc: Exception, reference: HFReference) -> Exception:
    try:
        from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
    except Exception:  # noqa: BLE001 - older/newer layout
        GatedRepoError = RepositoryNotFoundError = ()  # type: ignore[assignment]

    if RepositoryNotFoundError and isinstance(exc, RepositoryNotFoundError):
        return HuggingFaceNotFound(
            f"repo not found or not accessible: {reference.repo_id}"
        )
    if GatedRepoError and isinstance(exc, GatedRepoError):
        return HuggingFaceAuthError(
            f"repo {reference.repo_id} is gated; a token with access is required"
        )
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return HuggingFaceAuthError("Hugging Face rejected the token")
    if isinstance(exc, HuggingFaceNotFound | HuggingFaceAuthError | DownloadError):
        return exc
    return DownloadError(str(exc) or exc.__class__.__name__)
