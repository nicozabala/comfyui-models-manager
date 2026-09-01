## 1. Matrix: filter by hosts that must all have the model

- [x] 1.1 Extend `matrix.filter_rows(matrix, category, fragment, host_ids=None)` with AND-semantics host filtering (`host_ids <= row.present_host_ids`); verify with unit tests in `tests/test_ui_matrix.py` covering: host filter alone, combined with category/fragment, empty result set, and empty/`None` `host_ids` behaving as no filter (existing tests keep passing)
- [x] 1.2 Add the host checkbox step to the `Filter` action in `matrix_screen` (after category and name-fragment), pre-selecting the currently active host filter, and store the selection in the screen's loop state alongside `category`/`fragment`; verify via a scripted-prompter test in `tests/test_ui_matrix.py` that selecting hosts narrows the rendered table and re-opening `Filter` shows the prior selection
- [x] 1.3 Update the filter status line (`console.print(f"[dim]filter: ...")`) to also show the active host filter when set; verify by asserting on `console.export_text()` in a test

## 2. Model list: group by category

- [x] 2.1 Rewrite `render.model_table` to emit a styled heading row per category (in the order categories first appear in the already-sorted input) followed by that category's rows without a per-row `Category` column, and a section break between groups; verify with a unit test in `tests/test_ui_matrix.py` or a new `tests/test_render.py` asserting the rendered table's row count/headings for a multi-category input and that a category absent from the input has no heading
- [x] 2.2 Confirm `_models_screen` in `ui/app.py` needs no changes beyond the `render.model_table` call already in place (it passes `models_repo.list_models()` unchanged); run `uv run pytest tests/test_ui_app.py` to confirm no regression

## 3. Settings: clean terminal toggle

- [x] 3.1 Add `get_clean_terminal(conn) -> bool` and `set_clean_terminal(conn, value: bool) -> None` to `storage.py`, wrapping `get_setting`/`set_setting("clean_terminal", ...)` with `"1"`/`"0"` values and a default of `False`; verify with a round-trip test in `tests/test_storage.py`
- [x] 3.2 Add a `Toggle clean terminal` action to `settings_screen` showing current state and flipping it via `prompter.confirm(..., default=current)`; verify with a scripted-prompter test in `tests/test_ui_settings.py` that toggling on then re-opening settings shows the new state
- [x] 3.3 In `ui/app.py::loop()`, after a top-level action returns, call `console.clear()` when `storage.get_clean_terminal(storage.get_db())` is `True`, before re-displaying the main menu; verify with a test in `tests/test_ui_app.py` that stubs/spies `console.clear` (or `render.console`) and asserts it is called only when the setting is enabled

## 4. Docs / spec bookkeeping

- [x] 4.1 Run `openspec validate --specs --strict` and fix any reported issues in the delta spec
- [x] 4.2 Run `uv run pytest -q` and `uv run ruff check src tests` and confirm both are clean
