## Context

See `proposal.md` for motivation. All three changes live in `ui/` (plus one new
`storage.py` setting accessor pair) — no domain-layer (`distribution.py`,
`models_repo.py`, `hosts.py`) or schema changes beyond a new `settings` row. Existing
patterns to follow: `matrix.matrix_screen` already runs its own `while True` loop
with a `Filter` action that re-prompts `category` then `fragment`
([matrix.py](src/comfy_network_tools/ui/matrix.py)); `storage.py` already exposes
`get_repo_root`/`set_repo_root` and `get_categories`/`set_categories` as typed
wrappers over the generic `settings(key, value)` table; `app.loop()` is the single
top-level menu dispatcher that calls into each screen and regains control when a
screen returns.

## Goals / Non-Goals

**Goals:**

- Host-set filtering composes with the matrix's existing category/fragment filters
  rather than replacing them.
- The model list's category grouping is a rendering change only — `list_models()`
  already returns rows sorted by `(category, filename)`, so no query changes.
- The clean-terminal setting follows the existing `storage.py` accessor pattern
  (typed wrapper over `settings`) so it round-trips like `repo_root`/`categories`.

**Non-Goals:**

- Clearing inside each screen's own internal sub-loop (e.g. between two "Filter"
  actions inside the matrix screen, or between two edits inside the host screen).
  V1 clears only at the top-level `app.loop()` boundary — between a top-level menu
  action (matrix / models / hosts / download / settings) returning and the main menu
  being redisplayed. Sub-screens keep accumulating their own output internally, same
  as today. Extending clearing to every sub-loop is a separate follow-up if wanted,
  since it touches every screen module rather than just `app.py`.
- True scrollback erasure. Terminals differ on whether an ANSI clear also purges
  scroll-back; the spec only requires that the *next* screen renders as if starting
  fresh (matches `rich.Console.clear()` behavior), not that scrolling up is disabled.
- Any change to sort order, filtering semantics, or identity rules for models —
  the category grouping is purely how `render.model_table` lays out the same rows.

## Decisions

### D1: Host filter is AND-semantics over `present_host_ids`, folded into `filter_rows`

`matrix.filter_rows(matrix, category, fragment)` gains a fourth parameter,
`host_ids: set[int] | None`. When set and non-empty, a row survives only if
`host_ids <= row.present_host_ids` (every selected host is in the row's present
set). `None` / empty means "no host filter" (current behavior, unchanged default).
This keeps all three filters as independent predicates ANDed together in one place,
so `matrix_screen` doesn't need to special-case ordering.

The `Filter` action's existing two-step prompt (category, then name fragment) gains
a third step: a `checkbox` of registered hosts, defaulting to the currently-selected
set (so re-opening `Filter` doesn't silently drop it). An empty checkbox selection
clears the host filter, mirroring how leaving the name-fragment prompt blank already
clears that filter.

_Alternative considered:_ a separate "Filter by hosts" menu action next to `Filter`.
Rejected — three independent filter prompts under one `Filter` action matches the
existing UX (`category` then `fragment`) better than fragmenting filtering across
multiple menu entries the user has to remember to combine.

### D2: Category grouping is a `rich.Table` row-styling change, not a data change

`render.model_table` iterates `models` (already sorted by `category, filename`),
and for each new category value emits a full-width styled heading row (category
name, styled bold, via `Table.add_row(..., style=...)`) before that group's rows,
and drops the per-row `Category` column since the heading now carries it. A
`table.add_section()` between groups adds the existing rich visual rule used
elsewhere in the app for separation. No changes to `models_repo.list_models()` or
its ordering.

_Alternative considered:_ one `rich.Table` per category (multiple tables printed in
sequence). Rejected — loses the single coverage-style frame the rest of the app
uses (`matrix_table`, `host_table`) and complicates the "no models" empty case for
no real benefit over an in-table heading row.

### D3: `clean_terminal` is a boolean setting stored as `"1"`/`"0"`, read once per loop iteration

`storage.get_clean_terminal(conn) -> bool` / `storage.set_clean_terminal(conn, value: bool)`
wrap `get_setting`/`set_setting("clean_terminal", ...)`, following the exact shape of
`get_repo_root`/`set_repo_root`. Default (row absent) is `False` — off, matching
today's behavior, so existing users see no change until they opt in.

`settings_screen` gains a `Toggle clean terminal` action that shows the current
state and flips it via `prompter.confirm(..., default=current)`.

`ui.app.loop()` reads the setting once after each top-level action returns (not
before — the screen that just ran should render before the terminal is wiped for
the *next* one) and calls `console.clear()` when it is `True`, right before
re-displaying the `"Main menu"` prompt. `render.console` already centralizes the
single shared `Console` instance, so no new console object is created.

_Alternative considered:_ storing the flag in-memory only (no persistence). Rejected
— proposal explicitly asks for a persisted setting, and every other setting in this
screen already persists.

## Risks / Trade-offs

- **Host-filter checkbox adds a third prompt to `Filter`** → a no-op (empty
  selection) skips straight through with no extra confirmation needed, so users who
  don't want host filtering see one extra keypress (Enter) at most.
- **Category heading row uses `Table.add_row(..., style=...)` instead of true
  column spanning** → rich's `Table` has no native colspan; a styled row with the
  category name in the first cell and blank cells elsewhere reads clearly enough at
  the app's existing table widths and matches how the codebase already avoids
  fighting rich's grid model elsewhere.
- **Clean-terminal mode only clears at the top-level loop boundary** → a user deep
  in a multi-step sub-screen (e.g. running several matrix filters in a row) still
  sees accumulating output until they back out to the main menu. Documented as a
  Non-Goal above; the setting still delivers on the common case (menu-to-menu
  navigation) without a larger refactor of every screen's internal loop.
