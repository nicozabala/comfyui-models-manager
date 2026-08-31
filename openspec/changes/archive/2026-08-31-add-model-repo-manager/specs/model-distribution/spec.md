## Purpose

Model distribution copies models from the central repository to registered hosts
over SSH/SFTP, records where each model ends up, and lets the user see the full
model-to-host coverage matrix.

## ADDED Requirements

### Requirement: Repository models can be copied to hosts

The system SHALL let the user select one or more indexed repository models and one
or more registered hosts, and copy each selected model to each selected host over
SFTP. The remote destination SHALL be `<host remote models base path>/<category>/<file name>`.
The system SHALL create the remote category directory if it does not exist.

#### Scenario: Copying a model to a host

- **WHEN** the user copies a `loras` model to a host and the transfer completes
- **THEN** the file exists at `<base>/loras/<name>` on the host with the same byte size as the repository copy

#### Scenario: Remote category directory missing

- **WHEN** the user copies a model whose category directory does not yet exist on the host
- **THEN** the system creates the category directory before transferring the file

#### Scenario: Copying multiple models to multiple hosts

- **WHEN** the user selects 2 models and 3 hosts and starts the copy
- **THEN** the system performs 6 transfers and reports the per-transfer outcome

### Requirement: Transfers show progress and handle failure safely

The system SHALL display transfer progress (bytes transferred and percentage) for
each file. On failure or interruption the system SHALL remove the partial remote
file and SHALL NOT record a placement for that transfer.

#### Scenario: Transfer in progress

- **WHEN** a model file is being transferred to a host
- **THEN** the system shows a progress indicator advancing toward the file's total size

#### Scenario: Transfer fails midway

- **WHEN** a transfer is interrupted before completion
- **THEN** the system deletes the incomplete remote file and reports the transfer as failed with a reason

### Requirement: Placements are recorded and queryable

The system SHALL record a placement (model present on host) for every successful
transfer, storing the model identity, the host, and a timestamp. The system SHALL
answer, for any model, which hosts hold it, and for any host, which repository
models it holds.

#### Scenario: Placement recorded after success

- **WHEN** a transfer of a model to a host completes successfully
- **THEN** the system stores a placement linking that model and host with the current timestamp

#### Scenario: Querying hosts for a model

- **WHEN** the user asks which hosts hold a given model
- **THEN** the system lists exactly the hosts with a recorded placement for that model

### Requirement: Model already present on a host is detected

Before transferring, the system SHALL check whether a file with the same name and
byte size already exists at the remote destination. If so, the system SHALL record
the placement without re-transferring and SHALL report the transfer as skipped,
unless the user has requested an overwrite.

#### Scenario: Identical file already on host

- **WHEN** the user copies a model and the host already has a file of the same name and byte size at the destination
- **THEN** the system skips the transfer, records the placement, and reports "already present"

#### Scenario: Same name but different size on host

- **WHEN** the destination file has the same name but a different byte size
- **THEN** the system reports a conflict and transfers only if the user confirms overwrite

### Requirement: Host placements can be reconciled by scanning

The system SHALL let the user scan a host: list the model files under each category
of the host's remote models base path, ignoring the tool's own `*.cnt-part` transfer
temporaries, and reconcile the index and placements with what is actually on the
host. For each scanned file:

- If a model with the same category and file name is indexed and the byte sizes
  match, the system SHALL ensure a placement links that model and host.
- If no model with that category and file name is indexed, the system SHALL register
  a new model from the file (category, file name, byte size, marked as discovered on
  a host) and add a placement for that host.
- If a model with that category and file name is indexed but the byte sizes differ,
  the system SHALL report the file as a discrepancy and SHALL NOT add a placement or
  register a model.

The system SHALL remove placements for the scanned host whose file is no longer
present, and after the scan SHALL delete host-discovered models that no longer have
a placement on any host. The scan SHALL report the placements added, the models
newly registered, the placements removed, and the discrepancies.

#### Scenario: Indexed model found on host with no placement

- **WHEN** a host scan finds a file matching an indexed model by category, file name, and byte size, with no existing placement
- **THEN** the system adds a placement for that model and host

#### Scenario: Host file not in the index is registered

- **WHEN** a host scan finds a model file whose category and file name are not in the index
- **THEN** the system registers it as a model discovered on a host and adds a placement for that host

#### Scenario: Same name but different size is a discrepancy

- **WHEN** a host scan finds a file whose category and file name match an indexed model but whose byte size differs
- **THEN** the system reports it as a discrepancy and adds neither a placement nor a model

#### Scenario: Recorded placement no longer on host

- **WHEN** a host scan finds that a file for a recorded placement is absent from the host
- **THEN** the system removes that placement and reports it as removed

#### Scenario: Host-discovered model with no remaining placements is dropped

- **WHEN** a host scan removes the last placement of a model that was discovered on a host
- **THEN** the system deletes that model from the index

#### Scenario: Transfer temporaries are ignored

- **WHEN** a host scan encounters a `*.cnt-part` file
- **THEN** the system ignores it and does not treat it as a model

### Requirement: Model-to-host matrix is available

The system SHALL produce a matrix with one row per indexed model — whether it is
backed by the central repository, a Hugging Face download, or discovered on a host —
and one column per registered host, marking each cell as present or missing based on
recorded placements, and summarizing per-model host coverage.

#### Scenario: Viewing the matrix

- **WHEN** the user opens the model-to-host matrix
- **THEN** the system shows every indexed model against every host with present/missing cells and a coverage count per model

#### Scenario: Host-discovered model appears in the matrix

- **WHEN** a model exists only because it was discovered on one host
- **THEN** the matrix shows a row for it, present on that host and missing on the others

#### Scenario: Matrix with no hosts or no models

- **WHEN** the user opens the matrix and there are no registered hosts or no indexed models
- **THEN** the system shows an empty-state message rather than an empty grid
