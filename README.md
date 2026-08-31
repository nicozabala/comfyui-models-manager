# comfy-network-tools

Interactive admin for a central AI-model repository that is distributed to several
ComfyUI / AI hosts on a LAN over SSH. From one console you can see which host holds
which model, push missing models to hosts, and pull new models from Hugging Face.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Run

```bash
uv run comfy-network-tools
```

The app is an interactive menu (built on `rich` + `questionary`) and must be run
from a real terminal.

### First run

On first launch there is no model repository configured. You are prompted for the
**repository root** — a local directory whose subdirectories are ComfyUI-style
model categories (`checkpoints/`, `loras/`, `vae/`, `controlnet/`, ...). You can
skip and set it later from **Settings**. After setting it, choose **Re-index** to
scan the tree into the model index.

### Adding a host

**Manage hosts → Add host**. Provide a display name, address, SSH port, username,
the remote models base path, and an authentication method:

- **SSH agent** – uses your running agent / `~/.ssh` keys (recommended).
- **Private key file** – an explicit key path.
- **Password (stored encrypted)** – you type the password once; it is encrypted
  with Fernet and only the ciphertext is stored (see *State on disk* below). It is
  never shown again — the host list only indicates whether a password is stored.

Use **Test connectivity** to confirm the host is reachable and its base path is a
directory. On failure the reason is recorded on the host list with the underlying
detail — one of `authentication`, `unreachable`, `timeout`,
`missing/inaccessible base path`, `host-key-unknown`, `host-key-changed`, or
`sftp-unavailable`.

### Host keys

The tool verifies each host's SSH key **trust-on-first-use**, like `ssh` itself:

- The first time it connects to a host, it shows the key's `SHA256` fingerprint and
  asks whether to trust it. On yes, the key is **pinned** to that host (stored in
  `state.db`) and you are not asked again.
- If a host later presents a *different* key, the connection is refused with
  `host-key-changed` — investigate before doing anything else.
- Editing a host's address or port clears its pinned key (it's a different endpoint).
- A host can be marked to trust its key without prompting; the first key is still
  pinned and a later change is still refused.

The tool does **not** read `~/.ssh/config` — `ProxyJump`, per-host `IdentityFile`,
`HostName` aliases, and legacy-algorithm options there are not applied.

### Copying models

Open **View model ↔ host matrix** to see every indexed model against every host
(`✓` present / `·` missing, plus a coverage count). Choose **Copy a model to
hosts**, pick the targets, and each file is transferred over SFTP with a live
per-file progress bar. A file already present with the same size is skipped; a
same-name/different-size file asks before overwriting.

### Scanning a host

**Manage hosts → Scan host (reconcile models)** lists the model files on a host and
reconciles the index with them:

- files that match an indexed model (name + size) get a placement;
- **files that are on the host but not in the index are registered as models**
  (marked as discovered on a host), so a host's existing library shows up in the
  matrix even if the tool never put it there;
- a file whose name matches an indexed model but whose size differs is reported as
  a discrepancy and left alone.

Host-discovered models survive a central re-index and are dropped automatically once
no host holds them.

### Hugging Face downloads

**Settings → Set Hugging Face token** to store a token (or set `HF_TOKEN` /
`HUGGING_FACE_HUB_TOKEN` in the environment, which take precedence). Then
**Download from Hugging Face**: paste a reference (`owner/name` or a
`huggingface.co` URL), pick files and a target category, and they download
straight into the repository and are indexed.

## State on disk

| Path | Contents |
| --- | --- |
| `<user data dir>/comfy-network-tools/state.db` | SQLite: hosts, model index, placements, settings |
| `<user data dir>/comfy-network-tools/secret.key` | Fernet key for stored SSH passwords (`0600`) |
| `<user config dir>/comfy-network-tools/hf_token` | Hugging Face token (`0600`) |

`<user data dir>` / `<user config dir>` follow the platform (`platformdirs`); both
can be redirected with `CNT_DATA_DIR` / `CNT_CONFIG_DIR`.

**If you lose `secret.key`, every stored SSH password must be re-entered** — the
tool detects the failure and falls back to prompting for that session.

## Development

```bash
uv run pytest          # unit tests
uv run pytest -m integration   # also run the opt-in SFTP integration test
uv run ruff check .
```
