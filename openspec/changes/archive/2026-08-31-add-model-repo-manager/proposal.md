## Why

Teams running several ComfyUI (and other AI) hosts on a LAN keep copies of the same
large model files (checkpoints, LoRAs, VAEs, ...) spread across machines, with no
single place to see which host already has which model or to push a missing one.
This change introduces a Python admin tool that owns a central model repository,
knows the hosts, distributes models to them over SSH, and can pull new models from
Hugging Face — all from one interactive console.

## What Changes

- New `comfy-network-tools` Python package with a console entry point that opens an
  interactive menu built on **rich** (tables, the model↔host matrix, progress) and
  **questionary** (prompts, selection lists).
- **Central model repository**: a configured local directory indexed by the tool.
  Models are tracked by category (ComfyUI-style: `checkpoints`, `loras`, `vae`,
  `controlnet`, ...), file name, and byte size.
- **Host registry**: hosts are added to a persisted list with their SSH connection
  details (host, port, user, auth method — SSH agent, private key, or password —
  and remote models base path). A password is entered once and stored encrypted.
  Connectivity can be checked; the host key is verified trust-on-first-use (the
  fingerprint is shown and confirmed once, then pinned), and connection failures
  report a specific reason with the underlying detail.
- **Model distribution**: copy a repository model to one or more hosts over SFTP,
  with a live per-file progress bar; every successful copy is recorded as a placement
  (`model` present on `host`). An on-demand host scan reconciles placements with
  what is actually on the host and **registers models it finds there that the tool
  did not put there**, so a host's existing library becomes visible.
- **Model↔host view**: a matrix showing, for each indexed model (central repository,
  Hugging Face download, or host-discovered), the hosts it is present on and where
  it is missing.
- **Hugging Face integration**: store a Hugging Face API key; given a HF repo (and
  optional file/revision), download the selected files into the correct category of
  the central repository using the `huggingface_hub` library, then index them.
- **Persistence**: hosts, settings, and the model/placement registry are stored in
  a local SQLite database under the user data directory. The HF token is stored
  outside the tracked repo and can be overridden by an env var. SSH passwords are
  stored encrypted (Fernet) in the database, with the encryption key in a separate
  `0o600` key file next to the database.

No existing behavior changes — this is the first feature in the project.

## Capabilities

### New Capabilities

- `model-repository`: define, locate, and index the central model repository;
  represent a model by category + file name + byte size; expose the model list and
  per-model metadata. The index may also hold models that exist only on a host
  (registered by a scan) and are retained across central re-indexes.
- `host-registry`: add, edit, remove, and list hosts with SSH connection details
  (agent, private key, or an encrypted-at-rest password) and a remote models base
  path; verify the host key trust-on-first-use (pin on confirm, refuse on change);
  test connectivity to a host with a specific, detailed failure reason.
- `model-distribution`: copy repository models to hosts over SFTP with per-file
  progress; record and query placements (which model is on which host); scan a host
  to reconcile placements and register models found only on that host; render the
  model↔host matrix.
- `huggingface-integration`: store/validate a Hugging Face API token; resolve a HF
  repo/file/revision; download selected files into the central repository via
  `huggingface_hub` and hand them to the repository index.
- `console-interface`: the rich + questionary interactive application that exposes
  all of the above as menus and views, including the model↔host matrix screen.

### Modified Capabilities

_None — greenfield project._

## Impact

- **New dependencies**: `rich`, `questionary`, `paramiko` (SSH/SFTP),
  `huggingface_hub`, `cryptography` (Fernet for SSH passwords); packaging via
  `pyproject.toml` (managed with `uv`).
- **New code**: `src/comfy_network_tools/` package (repository, hosts, distribution,
  huggingface, secrets, console UI, persistence) plus a `comfy-network-tools`
  console script.
- **New state on disk**: SQLite DB and a `secret.key` file in the user data
  directory; HF token file in the user config directory. All secret-bearing files
  use restricted permissions.
- **Network**: outbound SSH/SFTP to hosts on the LAN; outbound HTTPS to
  `huggingface.co`.
- **Out of scope**: web UI, scheduled/automatic sync, model deletion on hosts,
  non-SSH transports, and content-hash-based deduplication (name + size only for
  now; sha256 may be added later).
