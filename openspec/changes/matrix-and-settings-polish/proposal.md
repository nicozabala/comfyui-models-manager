## Why

Day-to-day use of the console surfaced three rough edges: on multi-host setups the
matrix has no way to ask "which models are everywhere I care about", the flat model
list makes it hard to scan a large repository by eye, and long sessions leave the
terminal scrollback cluttered with every prior screen, making it harder to see the
current state at a glance.

## What Changes

- Matrix screen: add a host-selection filter — the user picks a subset of registered
  hosts (checkbox) and the grid narrows to model rows present on every selected host.
  Composes with the existing category and name-fragment filters (all active filters
  narrow the same row set).
- Repository model list screen (`_models_screen` / `render.model_table`): render
  models grouped by category with a visible category heading instead of a flat table
  repeating the category value on every row.
- Settings: add a "clean terminal" toggle, persisted like the existing repo-root and
  category settings. When enabled, the main loop clears the terminal after each menu
  action returns, so only the most recently rendered screen is visible instead of
  accumulating scrollback. Off by default (current behavior unchanged).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `console-interface`: the "Model-to-host matrix screen" requirement gains an
  all-selected-hosts filter; a new requirement documents the repository model list
  screen's per-category grouping; the "Settings screen" requirement gains the
  clean-terminal toggle and its effect on the main loop.

## Impact

- `src/comfy_network_tools/ui/matrix.py` — host-filter UI and `filter_rows`.
- `src/comfy_network_tools/ui/render.py` — `model_table` grouped rendering.
- `src/comfy_network_tools/ui/settings.py` — new toggle in the settings menu.
- `src/comfy_network_tools/ui/app.py` — main loop reads the setting and clears the
  screen between actions when enabled.
- `src/comfy_network_tools/storage.py` — persisted boolean setting, following the
  existing `get_setting`/`set_setting` pattern used for `repo_root`/`categories`.
- No changes to `distribution.py`, `models_repo.py`, `hosts.py`, or the data model —
  this is UI-layer only.
