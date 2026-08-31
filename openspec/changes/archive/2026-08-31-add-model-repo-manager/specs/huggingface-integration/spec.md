## Purpose

Hugging Face integration stores a Hugging Face API token and uses it to download
model files referenced by Hugging Face links into the correct category of the
central repository, then indexes them.

## ADDED Requirements

### Requirement: Hugging Face token is stored and can be overridden

The system SHALL let the user save a Hugging Face API token. The token SHALL be
stored outside the project's tracked files, in a file with owner-only read/write
permissions where the platform allows it. An environment variable
(`HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN`) SHALL take precedence over the stored
token when set. The system SHALL never print the full token; it SHALL show only a
masked form.

#### Scenario: Saving a token

- **WHEN** the user enters a Hugging Face token
- **THEN** the system writes it to the token file with restricted permissions and reports success without echoing the token

#### Scenario: Environment variable overrides stored token

- **WHEN** `HF_TOKEN` is set in the environment and a token is also stored on disk
- **THEN** the system uses the environment value for Hugging Face requests

#### Scenario: Displaying token status

- **WHEN** the user views Hugging Face settings
- **THEN** the system shows whether a token is configured and a masked preview, never the full value

### Requirement: Token can be validated

The system SHALL let the user validate the effective token against the Hugging Face
API and report whether it is accepted and, when available, the associated account
name.

#### Scenario: Valid token

- **WHEN** the user validates a token that the Hugging Face API accepts
- **THEN** the system reports the token as valid and shows the account name

#### Scenario: Invalid or missing token

- **WHEN** the user validates and no token is configured or the API rejects it
- **THEN** the system reports the token as invalid or missing and does not proceed with downloads that require it

### Requirement: A Hugging Face reference can be resolved and its files listed

The system SHALL accept a Hugging Face reference as either a repo id (`owner/name`)
or a full `huggingface.co` URL, optionally with a revision and an in-repo file
path. The system SHALL list the downloadable files of the resolved repo/revision
with their sizes so the user can choose which to download.

#### Scenario: Resolving a repo URL

- **WHEN** the user pastes `https://huggingface.co/owner/name/blob/main/model.safetensors`
- **THEN** the system resolves repo `owner/name`, revision `main`, file `model.safetensors`

#### Scenario: Listing repo files

- **WHEN** the user provides a repo id with no specific file
- **THEN** the system lists the repo's files with sizes for selection

#### Scenario: Unknown repo

- **WHEN** the reference points to a repo that does not exist or the token cannot access
- **THEN** the system reports the repo as not found or not accessible and downloads nothing

### Requirement: Selected files are downloaded into the repository

The system SHALL download each selected file into a user-chosen repository category
directory using the `huggingface_hub` library, showing download progress. On
completion the system SHALL place the file at `<repository root>/<category>/<file name>`
and hand it to the repository index so it becomes a tracked model. A file already
present in that category with the same name and byte size SHALL be reported as
already downloaded and not re-fetched unless the user requests overwrite.

#### Scenario: Downloading a model file

- **WHEN** the user selects a file, chooses category `checkpoints`, and confirms
- **THEN** the system downloads it to `<root>/checkpoints/<name>` and adds it to the model index

#### Scenario: Download progress

- **WHEN** a file is downloading
- **THEN** the system shows progress advancing toward the file's total size

#### Scenario: File already in repository

- **WHEN** the chosen category already contains a file with the same name and byte size
- **THEN** the system reports it as already downloaded and skips the transfer unless overwrite is requested

#### Scenario: Network or authentication failure during download

- **WHEN** a download fails due to a network error or an auth error
- **THEN** the system removes any partial file, reports the failure reason, and does not add a model entry
