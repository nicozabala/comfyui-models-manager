## MODIFIED Requirements

### Requirement: Model-to-host matrix screen

The system SHALL render the model-to-host matrix as a table with models as rows and
hosts as columns, present/missing cells visually distinguished, and per-model
coverage shown. The screen SHALL allow filtering by category, name fragment, and a
set of hosts the user selects; when a host set is selected, the screen SHALL show
only model rows present on every selected host. All active filters SHALL narrow the
same row set together. The screen SHALL let the user trigger a copy for a selected
model directly from the view, and SHALL let the user trigger an import into the
repository for a selected model that has no central repository copy. While a copy
or import runs, the screen SHALL show a per-file progress bar advancing toward each
file's total size.

#### Scenario: Viewing the matrix

- **WHEN** the user opens the matrix screen with hosts and models present
- **THEN** the system shows the model rows against host columns with present/missing cells and coverage counts

#### Scenario: Filtering the matrix

- **WHEN** the user applies a category filter on the matrix screen
- **THEN** the system shows only rows for models in that category

#### Scenario: Filtering by hosts that must all have the model

- **WHEN** the user selects a set of hosts as a filter on the matrix screen
- **THEN** the system shows only model rows present on every host in that set

#### Scenario: Host filter combines with category and name filters

- **WHEN** the user has a host-set filter active together with a category or name-fragment filter
- **THEN** the system shows only rows that satisfy all active filters at once

#### Scenario: No models present on every selected host

- **WHEN** the user selects a set of hosts and no model is present on all of them
- **THEN** the system shows an empty row set rather than an error

#### Scenario: Clearing the host filter

- **WHEN** the user clears the host-set filter
- **THEN** the system returns to showing rows per the remaining active filters (or all rows if none)

#### Scenario: Acting from the matrix

- **WHEN** the user selects a model row and chooses to copy it
- **THEN** the system starts the host-selection copy flow for that model

#### Scenario: Copy shows per-file progress

- **WHEN** a copy started from the matrix is transferring a file to a host
- **THEN** the screen shows a progress bar advancing toward that file's total size

#### Scenario: Importing a host-only model from the matrix

- **WHEN** the user selects a model row with no central repository copy and chooses to import it
- **THEN** the system starts the import flow for that model, asking which host to download from when more than one holds it

#### Scenario: No host-only models to import

- **WHEN** the user chooses to import a model but the currently visible rows have no host-only model
- **THEN** the system reports that there is nothing to import and does not start the flow

### Requirement: Settings screen

The system SHALL provide a settings screen to view and change the repository root,
the category list, and the Hugging Face token, to run repository re-indexing, and
to toggle "clean terminal" mode. Long-running operations SHALL show progress and
SHALL be cancellable with Ctrl+C without corrupting persisted state. The
clean-terminal setting SHALL persist across restarts. While enabled, the main menu
loop SHALL clear the terminal after each menu action returns, before rendering the
next screen, so only the most recently rendered screen is visible; while disabled,
output SHALL accumulate in the scrollback as before.

#### Scenario: Changing the repository root

- **WHEN** the user sets a new valid repository root in settings
- **THEN** the system persists it and offers to re-index

#### Scenario: Cancelling a long operation

- **WHEN** the user presses Ctrl+C during repository re-indexing
- **THEN** the system stops the operation, keeps the last consistent index, and returns to the menu

#### Scenario: Enabling clean terminal mode

- **WHEN** the user enables "clean terminal" mode in settings
- **THEN** the system persists the setting, and after each subsequent menu action returns, the terminal is cleared before the next screen is shown

#### Scenario: Clean terminal mode stays off by default

- **WHEN** the user has never changed the clean-terminal setting
- **THEN** the terminal is not cleared between screens and prior output remains in the scrollback

#### Scenario: Disabling clean terminal mode

- **WHEN** the user disables "clean terminal" mode after having enabled it
- **THEN** the system persists the change and subsequent screens accumulate in the scrollback again

## ADDED Requirements

### Requirement: Repository model list screen

The system SHALL render the repository model list grouped by category, with each
category visually distinguished by a heading, rather than as a single flat table
repeating the category on every row. Within each category, models SHALL be listed
sorted by file name.

#### Scenario: Viewing the model list with multiple categories

- **WHEN** the user opens the repository model list and indexed models span more than one category
- **THEN** the system shows each category under its own heading, with that category's models listed beneath it in file-name order

#### Scenario: Category with no models is omitted

- **WHEN** a known category has no indexed models
- **THEN** the model list does not show a heading for that empty category
