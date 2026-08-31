## Context

Greenfield project (`comfy-network-tools`) — see `proposal.md` for motivation. The
tool runs on one workstation, owns a local "central" model directory, and reaches a
set of LAN hosts over SSH to copy model files and observe what they hold. The five
capabilities in `specs/` split cleanly into a domain layer (repository, hosts,
distribution, huggingface) and a presentation layer (console-interface).

Constraints that shape the design:

- The operator machine may be Windows (see environment); target hosts are typically
  Linux ComfyUI boxes. Remote paths must be POSIX regardless of operator OS.
- Model files are large (GB-scale). Transfers must stream with progress and clean up
  after themselves.
- Two secrets exist: the Hugging Face token and, for `password`-auth hosts, SSH
  passwords. Neither is ever stored in cleartext; the SQLite database on its own
  must not be enough to recover either.
- Identity is name + byte size only (user decision); no content hashing in this
  change.

## Goals / Non-Goals

**Goals:**

- A testable domain layer with no `rich`/`questionary`/`paramiko` imports, so
  behavior from the specs can be unit-tested with fakes.
- One source of truth for hosts, models, and placements (relational queries like the
  model↔host matrix are first-class).
- Transfers and downloads that are safe to interrupt (Ctrl+C) without leaving
  corrupt state or partial remote files recorded as placements.
- Remote-path handling that is correct with a Windows operator and Linux hosts.

**Non-Goals:**

- Parallel transfers, transfer resume, and rsync-based delta copy (sequential SFTP
  only this change).
- A general SSH command runner, remote ComfyUI control, or model deletion on hosts.
- OS keyring integration and multi-user/shared deployment.
- Schema migration tooling beyond recording a schema version for later use.

## Decisions

### D1: Python 3.11+, packaged with `uv` and `pyproject.toml`, `src/` layout

Package `comfy_network_tools` under `src/`, console script
`comfy-network-tools = "comfy_network_tools.__main__:main"`. Runtime deps: `rich`,
`questionary`, `paramiko`, `huggingface_hub`, `platformdirs`, `cryptography` (Fernet
for SSH passwords at rest). Dev: `pytest`, `ruff`, `mock-ssh-server` (loopback SFTP
server for the opt-in integration test).

_Alternatives:_ Poetry / plain `pip` + `requirements.txt` — `uv` is faster and the
lockfile story is simple; no strong reason to differ.

### D2: SQLite as the single store for non-secret state

One database file at `platformdirs.user_data_dir("comfy-network-tools")/state.db`.
Tables:

- `hosts(id, name UNIQUE, address, port, username, auth_method, private_key_path,
  encrypted_password, remote_base_path, trust_host_key, host_key, last_check_at,
  last_check_ok, last_check_reason)` — `encrypted_password` holds a Fernet token
  (see D3), never cleartext; `host_key` is the pinned server key line
  `"<type> <base64>"` (see D4), NULL until trusted
- `models(id, category, filename, size_bytes, indexed_at, source)` with
  `UNIQUE(category, filename)` — `source` is `local`, `huggingface`, or `host`
  (discovered on a host during a scan, see D8)
- `placements(model_id, host_id, created_at, PRIMARY KEY(model_id, host_id))` with
  `ON DELETE CASCADE` from both parents
- `settings(key, value)` — holds `repo_root`, `categories` (JSON array),
  `schema_version`

The matrix, "which hosts have model X", and cascade-on-host-removal all fall out of
SQL. A `storage` module owns the connection and schema creation; domain services
depend on a thin repository-object interface over it, not on `sqlite3` directly.

_Alternatives:_ JSON/TOML files per entity — rejected: placements are a
many-to-many relation and we would be hand-rolling joins and referential integrity.

### D3: No secret is stored in cleartext

- **Hugging Face token:** file `user_config_dir/hf_token`, written with `0o600`
  where supported. Effective token resolution order:
  `HF_TOKEN` env → `HUGGING_FACE_HUB_TOKEN` env → token file. Only a masked form
  (`hf_...abcd`) is ever displayed or logged.
- **SSH passwords:** persisted, encrypted. When a host uses
  `auth_method = password`, the password entered on add/edit is encrypted with
  Fernet (`cryptography`) and stored in the `hosts.encrypted_password` column — the
  plaintext is never written to the DB, never logged, and never displayed (the UI
  shows only whether a password is stored). The Fernet key is generated on first
  use and kept in `user_data_dir/secret.key` with `0o600` perms, **separate from
  `state.db`**, so a copied or shared database is useless without the key file. At
  connect time the tool decrypts with the local key; if the key file is missing or
  decryption fails it reports this and prompts for the password for that session,
  offering to re-save. Key/agent auth stays the recommended default.

_Alternatives:_ Not persisting passwords at all (prompt every session) — the
behavior we are replacing; rejected as too much friction for a single-operator
tool. OS keyring — better at-rest protection but an extra dependency and awkward on
headless/remote-desktop operator machines; still a Non-Goal. Encrypting a secrets
blob in the DB with the key also in the DB — no real protection.

### D4: SSH/SFTP via `paramiko` directly, behind a `RemoteHost` interface

A `HostConnection` wraps a `paramiko.SSHClient` + `SFTPClient`. The distribution
service depends on an abstract `RemoteFS` (list dir, stat, mkdirs, put-with-callback,
remove, rename) so it can be faked in tests.

- **Auth:** built from the host record — SSH agent, an explicit private key path, or
  the decrypted stored password (`secrets.decrypt` of `encrypted_password`); on
  `SecretError` the caller prompts for the password for the session.
- **Remote paths:** always composed with `posixpath` from `remote_base_path`,
  `category`, `filename` — never `os.path`.
- **Directory creation:** emulate `mkdir -p` by walking path segments and
  `sftp.mkdir` on the ones that `stat` says are missing.
- **Atomic-ish transfer:** upload to `…/<filename>.cnt-part`, then `sftp.posix_rename`
  to the final name on success. On any exception, `sftp.remove` the `.cnt-part` file
  and record no placement.
- **Host key verification — trust on first use.** `connect()` loads the operator's
  system `known_hosts` and, if `host.host_key` is set, pins it into the client's
  host keys so paramiko verifies against it (a mismatch raises `BadHostKeyException`
  → `ConnectivityError("host-key-changed", <presented vs expected fingerprint>)`).
  If `host.host_key` is NULL, a custom `MissingHostKeyPolicy` calls a
  `host_key_prompt(host, key)` callback with the `SHA256` fingerprint: return true
  to accept, false → `ConnectivityError("host-key-unknown", …)`; with no callback
  (non-interactive) the key is rejected. `trust_host_key = true` replaces the prompt
  with an auto-accept but still pins. After any successful connect where
  `host.host_key` was NULL, `open_connection` persists the presented key
  (`"<type> <base64>"`) so the next connect is silent and key changes are detected.
- **`open_sftp()` is inside the error handling.** A host that authenticates but has
  no SFTP subsystem fails as `ConnectivityError("sftp-unavailable", <detail>)`
  rather than escaping as a raw `SSHException`.
- **Every `ConnectivityError` keeps the paramiko detail.** `reason` is one of
  `authentication`, `unreachable`, `timeout`, `missing/inaccessible base path`,
  `host-key-unknown`, `host-key-changed`, `sftp-unavailable`; the message carries
  the underlying text, and `hosts.test_connectivity` stores `"<reason>: <detail>"`
  in `last_check_reason` so a failure is diagnosable from the host list.

_Alternatives:_ `fabric` — pulls in `invoke` and a task model we do not need.
`rsync` over SSH — needs `rsync` on every host and is awkward from a Windows
operator; noted as a future speed optimization, not now.

### D5: `huggingface_hub` writes straight into the repository category

Use `hf_hub_download(repo_id, filename, revision=…, local_dir=<repo_root>/<category>,
token=<effective token>)`. This lands the real file in place (no symlink into the HF
cache). Repo/URL parsing accepts `owner/name`, `owner/name` + revision + file, and
`https://huggingface.co/owner/name/(blob|resolve)/<rev>/<path>` forms. File listing
uses `HfApi().list_repo_files` / `model_info` for sizes. After download the file is
handed to the repository indexer, which upserts the `models` row.

_Alternatives:_ shelling out to the `hf` CLI — user chose the library; also avoids
depending on a CLI being on `PATH`. Downloading to a temp dir then moving — extra
copy of a multi-GB file for no benefit.

### D6: Layered module structure

```
comfy_network_tools/
  __main__.py            # entry point → ui.app.run()
  config.py              # paths, effective HF token, settings accessors
  secrets.py             # Fernet key file (secret.key) + encrypt/decrypt helpers
  storage.py             # sqlite connection, schema, repository objects
  models_repo.py         # repository indexing & queries        (model-repository)
  hosts.py               # host registry CRUD + connectivity     (host-registry)
  ssh.py                 # paramiko RemoteFS implementation
  distribution.py        # copy, placements, reconcile, matrix   (model-distribution)
  huggingface.py         # token, resolve, list, download        (huggingface-integration)
  errors.py              # typed domain exceptions
  ui/
    app.py               # main menu loop
    matrix.py, hosts.py, downloads.py, settings.py   # screens
    prompts.py, render.py                             # questionary/rich helpers
```

Domain modules raise typed exceptions from `errors.py`; `ui/` is the only place that
imports `rich`/`questionary` and the only place that catches `KeyboardInterrupt` at
screen boundaries.

### D7: Sequential transfers with a single `rich.progress` display

The copy flow expands (models × hosts) into an ordered task list and runs it one
transfer at a time, appending a per-transfer result row (ok / skipped / conflict /
failed+reason). Predictable, easy to reason about under Ctrl+C. Parallelism is a
later optimization behind the same service API.

`distribution.copy(progress=…)` takes a `(plan, bytes_done, bytes_total)` callback;
the matrix copy screen (`ui/matrix.py`) drives a single `rich.Progress` with one
per-file bar from that callback, and `ui/render.py` owns the helper that builds it.
The domain layer never imports `rich`.

### D8: Host-discovered models

A host scan (`distribution.reconcile`) is the only path that puts a model in the
index without a central-repository file. Such a row is `source = 'host'`. Matching
stays strict on `(category, filename, size_bytes)`:

- name+size match to an indexed model → ensure the placement (unchanged).
- `(category, filename)` not indexed → insert a `source = 'host'` model + placement.
- `(category, filename)` indexed but size differs → a **discrepancy**: no placement,
  no insert (the `UNIQUE(category, filename)` constraint also forbids a second row).

`models_repo.reindex` skips `source = 'host'` rows when deleting missing files, and
promotes a `'host'` row to `'local'` if its file later appears in the central scan.
After a scan, and after a host is removed, `source = 'host'` models with zero
placements are pruned. `*.cnt-part` transfer temporaries are ignored by the scan.

## Risks / Trade-offs

- **HF token on disk in plaintext** → `0o600` perms, env-var override, masked
  display, never stored in the shared DB; document the file location.
- **SSH password at rest** → encrypted with Fernet; the key lives in a separate
  `0o600` file, so `state.db` alone never yields a password. Trade-off: the key
  sits on the same disk as the DB, so this protects against a casual disk copy,
  accidental DB sharing, or a VCS commit — not a determined local attacker with
  filesystem access. Losing `secret.key` means every stored password must be
  re-entered (the tool detects the failure and falls back to prompting).
- **`trust_host_key` skips the fingerprint prompt** → weakens first-connection MITM
  protection for that host; it is opt-in per host, off by default, shown in the host
  list, and a later key change is still refused because the first key is pinned.
- **name+size identity collisions** (two genuinely different files, same name and
  size) → treated as the same model; low probability for model artifacts, and the
  design keeps a `source` column and leaves room to add a `sha256` column +
  on-demand verification later without a spec change to identity semantics… (this
  would be a spec change if it altered matching — see Open Questions).
- **Interrupted transfer leaves `.cnt-part` file** → cleaned in the exception path;
  a hard kill (SIGKILL / power loss) can still orphan one. The host scan skips
  `*.cnt-part` files by name so an orphan is never registered as a model; the user
  deletes it out of band.
- **Windows operator, POSIX hosts** → all remote path building goes through
  `posixpath`; a lint rule / review check forbids `os.path` in `ssh.py` and
  `distribution.py`.
- **`huggingface_hub` API drift** (function signatures, progress bar behavior) →
  pin a minimum version in `pyproject.toml`; wrap all calls in `huggingface.py` so
  there is one place to adjust.
- **Large `models` scans on network/remote filesystems** → repository indexing is
  local-only by design; host enumeration is explicit (user-triggered scan), not
  automatic.

## Migration Plan

Greenfield — no data migration. The `hosts` schema includes `encrypted_password`
and `host_key` from `schema_version = 1`. First run creates the app data directory,
the SQLite schema, and writes `schema_version = 1` into `settings`; `secret.key` is
created lazily the first time a password is stored. Rollback is deleting
`user_data_dir/comfy-network-tools/` (state DB and `secret.key`) and
`user_config_dir/comfy-network-tools/` (HF token); no host-side changes are made by
install or uninstall. Future schema changes key off `schema_version`.

## Open Questions

- Should a later change add an optional `sha256` to model identity/matching? That
  would be a `model-repository` / `model-distribution` spec change, so it is
  deliberately out of scope here, not a silent TODO.
- Parallel transfer count and whether to expose it as a setting — safe to decide
  after real-world use; the sequential API does not need to change.
