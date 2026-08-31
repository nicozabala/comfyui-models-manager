## Purpose

The central model repository is the single local location that holds the canonical
copies of AI model files, organized by category, and indexed so the tool can list
every model and report its metadata.

## ADDED Requirements

### Requirement: Repository location is configured

The system SHALL store a single configurable filesystem path as the central model
repository root. The system SHALL treat the repository as unconfigured until a path
is set, and SHALL reject a path that does not exist or is not a directory.

#### Scenario: Setting a valid repository path

- **WHEN** the user sets the repository root to an existing directory
- **THEN** the system persists the path and reports the repository as configured

#### Scenario: Setting an invalid repository path

- **WHEN** the user sets the repository root to a path that does not exist or is a file
- **THEN** the system rejects the value with an error and leaves the previous path unchanged

#### Scenario: Operating without a configured repository

- **WHEN** any repository operation is requested and no repository root is configured
- **THEN** the system reports that the repository must be configured first and performs no indexing

### Requirement: Models are organized by category

The system SHALL organize models into named categories that map to subdirectories of
the repository root (for example `checkpoints`, `loras`, `vae`, `controlnet`,
`clip`, `unet`, `upscale_models`, `embeddings`). The system SHALL allow the category
set to be extended by configuration, and SHALL ignore repository files that are not
inside a known category subdirectory.

#### Scenario: File inside a known category

- **WHEN** the repository is indexed and a file exists at `<root>/loras/style.safetensors`
- **THEN** the system records a model with category `loras` and file name `style.safetensors`

#### Scenario: File outside any known category

- **WHEN** the repository is indexed and a file exists directly under the repository root or under an unknown subdirectory
- **THEN** the system does not record it as a model

### Requirement: A model is identified by category, file name, and byte size

The system SHALL identify each model by the triple (category, file name, byte size)
and SHALL expose this identity for comparison against files on hosts and against
Hugging Face downloads. Content hashing SHALL NOT be required for identity.

#### Scenario: Two files with the same name in different categories

- **WHEN** `checkpoints/model.safetensors` and `unet/model.safetensors` both exist
- **THEN** the system records them as two distinct models

#### Scenario: Reporting model metadata

- **WHEN** the user views a model
- **THEN** the system reports its category, file name, byte size, and last-indexed time

### Requirement: Repository can be indexed and re-indexed

The system SHALL scan the repository on demand and maintain a persisted index of the
models it contains. On re-index the system SHALL add newly found files, update the
byte size of files that changed, and remove entries that are backed by the central
repository but whose files no longer exist. Models that exist only because they were
discovered on a host SHALL NOT be removed by a central re-index.

#### Scenario: New file added to the repository

- **WHEN** a new model file is placed in a category directory and the repository is re-indexed
- **THEN** the system adds the model to the index

#### Scenario: File removed from the repository

- **WHEN** a model file backed by the central repository is deleted from disk and the repository is re-indexed
- **THEN** the system removes the model from the index

#### Scenario: File size changed

- **WHEN** an existing model file's byte size changes and the repository is re-indexed
- **THEN** the system updates the stored byte size for that model

#### Scenario: Host-discovered model survives a central re-index

- **WHEN** a model that exists only because it was discovered on a host is in the index and the repository is re-indexed
- **THEN** the system keeps that model in the index

### Requirement: A model may exist without a central repository copy

The index MAY contain models that have no file in the central repository — for
example a model discovered on a host during a host scan. Such a model SHALL carry
its identity (category, file name, byte size) and SHALL participate in the model
list and the model-to-host matrix like any other. The system SHALL retain it across
central re-indexes and SHALL remove it only when no host holds it.

#### Scenario: Host-only model in the model list

- **WHEN** a model was registered from a host scan and has no central repository file
- **THEN** the model list includes it with its category, file name, and byte size

#### Scenario: Host-only model removed when no host holds it

- **WHEN** the last placement of a host-only model is removed
- **THEN** the system removes that model from the index

### Requirement: Model list is queryable

The system SHALL expose the indexed models as a list that can be filtered by
category and by file-name substring, sorted by category then file name.

#### Scenario: Listing all models

- **WHEN** the user requests the model list with no filter
- **THEN** the system returns every indexed model grouped by category

#### Scenario: Filtering the model list

- **WHEN** the user requests the model list filtered by category `vae` and name fragment `sdxl`
- **THEN** the system returns only `vae` models whose file name contains `sdxl`
