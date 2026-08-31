# Console Interface Specification

## Purpose

The console interface is the interactive application, built on rich and questionary,
that a user runs to manage the repository, hosts, distribution, and Hugging Face
downloads, with the model-to-host matrix as its central view.

## Requirements

### Requirement: Interactive application launches with a main menu

The system SHALL provide a console entry point that opens an interactive main menu
offering: view model-to-host matrix, manage models / repository, manage hosts,
download from Hugging Face, settings, and exit. Selecting exit SHALL terminate the
application cleanly.

#### Scenario: Launching the application

- **WHEN** the user runs the console entry point
- **THEN** the system displays the main menu with all listed options

#### Scenario: Exiting

- **WHEN** the user selects exit, or interrupts with Ctrl+C at the main menu
- **THEN** the application terminates without a traceback and with a zero exit status

### Requirement: First-run configuration is guided

When the repository root is not configured, the system SHALL prompt the user to set
it before offering repository-dependent actions, and SHALL keep host management and
settings reachable.

#### Scenario: First run without a repository

- **WHEN** the user launches the application and no repository root is configured
- **THEN** the system prompts to configure the repository root and does not offer matrix or download actions until it is set

#### Scenario: Repository configured later

- **WHEN** the user sets a valid repository root from settings
- **THEN** the repository-dependent menu options become available without restarting

### Requirement: Model-to-host matrix screen

The system SHALL render the model-to-host matrix as a table with models as rows and
hosts as columns, present/missing cells visually distinguished, and per-model
coverage shown. The screen SHALL allow filtering by category and name fragment and
SHALL let the user trigger a copy for a selected model directly from the view. While
a copy runs, the screen SHALL show a per-file progress bar advancing toward each
file's total size.

#### Scenario: Viewing the matrix

- **WHEN** the user opens the matrix screen with hosts and models present
- **THEN** the system shows the model rows against host columns with present/missing cells and coverage counts

#### Scenario: Filtering the matrix

- **WHEN** the user applies a category filter on the matrix screen
- **THEN** the system shows only rows for models in that category

#### Scenario: Acting from the matrix

- **WHEN** the user selects a model row and chooses to copy it
- **THEN** the system starts the host-selection copy flow for that model

#### Scenario: Copy shows per-file progress

- **WHEN** a copy started from the matrix is transferring a file to a host
- **THEN** the screen shows a progress bar advancing toward that file's total size

### Requirement: Host management screens

The system SHALL provide interactive flows to list hosts, add a host, edit a host,
remove a host (with confirmation), test a host's connectivity, and scan a host to
reconcile its models, surfacing validation errors inline without crashing. When the
user selects password authentication, the flow SHALL prompt for the password with
hidden input; the host list SHALL show the authentication method and whether a
password is stored, never the password itself. When a flow that opens a connection
meets a host whose key is not yet trusted, it SHALL show the key's `SHA256`
fingerprint and ask the user whether to trust it; when a host presents a changed
key, the flow SHALL show a warning and abort without connecting.

#### Scenario: Adding a host through the UI

- **WHEN** the user completes the add-host prompts with valid values
- **THEN** the system adds the host and returns to the host list showing it

#### Scenario: Entering a password with hidden input

- **WHEN** the user selects password authentication in the add-host flow and types a password
- **THEN** the input is masked on screen and the host is stored with the password encrypted

#### Scenario: Keeping the stored password when editing

- **WHEN** the user edits a password host and submits the password prompt empty
- **THEN** the system keeps the existing stored password and does not prompt again

#### Scenario: Rejecting invalid host input

- **WHEN** the user submits add-host prompts with a duplicate name or missing field
- **THEN** the system shows the error and lets the user correct the input without losing the other entered values

#### Scenario: Confirming host removal

- **WHEN** the user chooses to remove a host
- **THEN** the system asks for confirmation and only deletes the host if confirmed

#### Scenario: Scanning a host

- **WHEN** the user runs a scan on a host
- **THEN** the system reports the placements added, the models newly registered from the host, the placements removed, and any discrepancies

#### Scenario: Scan registers a model from the host

- **WHEN** a scan finds a model file on the host that is not in the index
- **THEN** after the scan that model appears in the model-to-host matrix, present on that host

#### Scenario: Prompted to trust an unknown host key

- **WHEN** the user tests connectivity to a host whose key is not yet trusted
- **THEN** the flow shows the key's SHA256 fingerprint and asks whether to trust it, pinning it only if the user confirms

#### Scenario: Aborting on a changed host key

- **WHEN** a host presents a key different from the pinned one during a connect flow
- **THEN** the flow shows a warning naming both fingerprints and does not open the connection

### Requirement: Hugging Face download flow

The system SHALL provide an interactive flow to enter a Hugging Face reference,
list its files, select files, choose a target category, confirm, and show download
progress, reporting success or a specific failure reason at the end.

#### Scenario: Completing a download

- **WHEN** the user enters a valid reference, selects files, picks a category, and confirms
- **THEN** the system downloads the files with progress and reports each as downloaded or skipped

#### Scenario: Download flow without a valid token

- **WHEN** the user starts the download flow and no valid token is configured for a gated repo
- **THEN** the system explains that a valid token is required and returns to the menu without downloading

### Requirement: Settings screen

The system SHALL provide a settings screen to view and change the repository root,
the category list, and the Hugging Face token, and to run repository re-indexing.
Long-running operations SHALL show progress and SHALL be cancellable with Ctrl+C
without corrupting persisted state.

#### Scenario: Changing the repository root

- **WHEN** the user sets a new valid repository root in settings
- **THEN** the system persists it and offers to re-index

#### Scenario: Cancelling a long operation

- **WHEN** the user presses Ctrl+C during repository re-indexing
- **THEN** the system stops the operation, keeps the last consistent index, and returns to the menu
