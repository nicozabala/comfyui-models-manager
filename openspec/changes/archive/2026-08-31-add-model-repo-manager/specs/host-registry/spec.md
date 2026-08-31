## Purpose

The host registry is the persisted list of remote machines that receive model
copies, holding each host's SSH connection details and the base path of its model
directory tree so the tool can reach it.

## ADDED Requirements

### Requirement: Hosts can be added to the registry

The system SHALL let the user add a host with: a unique display name, an address
(hostname or IP), an SSH port (default 22), an SSH username, an authentication
method (SSH agent, explicit private key path, or password), and a remote models
base path. When the authentication method is password, the system SHALL let the
user enter a password and SHALL store it encrypted (see "SSH password is stored
encrypted"). The system SHALL reject an add whose display name or address+port+user
combination already exists.

#### Scenario: Adding a new host

- **WHEN** the user adds a host with a name and connection details not already registered
- **THEN** the system persists the host and includes it in the host list

#### Scenario: Adding a password-authenticated host

- **WHEN** the user adds a host with authentication method password and enters a password
- **THEN** the system persists the host with the password stored only in encrypted form

#### Scenario: Adding a duplicate host

- **WHEN** the user adds a host whose display name matches an existing host
- **THEN** the system rejects the add with an error and the registry is unchanged

#### Scenario: Missing required connection detail

- **WHEN** the user attempts to add a host without an address, username, or remote models base path
- **THEN** the system rejects the add and reports which field is missing

### Requirement: Hosts can be edited and removed

The system SHALL let the user edit any field of an existing host and remove a host
from the registry. When editing a password host, the system SHALL re-encrypt and
store a newly entered password, SHALL keep the existing stored password when the
password entry is left blank, and SHALL discard the stored password when the
authentication method is changed away from password. Removing a host SHALL also
remove that host's recorded placements and its stored password.

#### Scenario: Editing a host

- **WHEN** the user changes the remote models base path of an existing host
- **THEN** the system persists the new value and leaves other fields unchanged

#### Scenario: Editing a password host without changing the password

- **WHEN** the user edits a password host and leaves the password entry blank
- **THEN** the system keeps the previously stored encrypted password unchanged

#### Scenario: Switching a host away from password authentication

- **WHEN** the user changes an existing password host to agent or private key authentication
- **THEN** the system discards the stored encrypted password for that host

#### Scenario: Removing a host

- **WHEN** the user removes a host that has recorded placements
- **THEN** the system deletes the host, all placements referencing it, and any stored password

### Requirement: Host list is viewable

The system SHALL present the registered hosts with their name, address, port, user,
authentication method, whether an SSH password is stored, the trusted host-key
fingerprint (or that no key is trusted yet), remote models base path, and last
known connectivity result. The system SHALL NOT display any password or private
key material.

#### Scenario: Viewing hosts

- **WHEN** the user opens the host list
- **THEN** the system shows every registered host with its connection summary, authentication method, trusted-key state, and last connectivity result

#### Scenario: Credentials are never shown

- **WHEN** the user views a host that has a stored password
- **THEN** the system indicates that a password is stored without revealing the password itself

#### Scenario: Empty registry

- **WHEN** the user opens the host list and no hosts are registered
- **THEN** the system shows an empty-state message inviting the user to add a host

### Requirement: SSH password is stored encrypted

The system SHALL store an SSH password only in encrypted form. When a host is added
or edited with password authentication and a password is provided, the system SHALL
encrypt it with a key held in a local key file with owner-only permissions and
persist only the resulting ciphertext. The system SHALL NOT write the password to
storage in cleartext, SHALL NOT log it, and SHALL NOT display it — only whether a
password is stored. When connecting to a password host, the system SHALL decrypt
the stored password using the local key. If the key file is missing or the
ciphertext cannot be decrypted, the system SHALL report this and fall back to
prompting the user for the password for that session.

#### Scenario: Password persisted as ciphertext only

- **WHEN** the user stores a password for a host
- **THEN** the persisted host record contains only ciphertext and the cleartext password appears in no stored file or log

#### Scenario: Decrypting the password to connect

- **WHEN** the tool connects to a password host and the local key file is present
- **THEN** the system decrypts the stored password with the local key and authenticates with it

#### Scenario: Key file missing at connect time

- **WHEN** the tool connects to a password host and the local key file is missing or the ciphertext cannot be decrypted
- **THEN** the system reports that the stored password is unavailable and prompts the user for the password for that session

### Requirement: Host key is verified on connect (trust on first use)

Every SSH connection the tool opens to a host SHALL verify the server's host key.

- The first time the tool connects to a host whose host key is not already trusted
  (neither pinned for that host nor present in the operator's system known-hosts),
  the system SHALL present the key's `SHA256` fingerprint and SHALL ask the user to
  confirm. On confirmation the system SHALL pin that key to the host and SHALL NOT
  ask again; on refusal the connection SHALL fail with reason `host-key-unknown`.
- When a host presents a key that differs from the one pinned for it, the system
  SHALL refuse the connection with reason `host-key-changed` and SHALL NOT proceed.
- After any successful connection to a host that had no pinned key, the system SHALL
  pin the key the server presented.
- A host may be marked to trust its key without prompting; connecting then pins the
  presented key without asking, but a later changed key is still refused.

#### Scenario: Trusting a host key on first connection

- **WHEN** the tool connects to a host whose key is not yet trusted and the user confirms the shown fingerprint
- **THEN** the system pins that key to the host and completes the connection

#### Scenario: Declining an unknown host key

- **WHEN** the tool connects to a host whose key is not yet trusted and the user declines
- **THEN** the connection fails with reason `host-key-unknown` and nothing is pinned

#### Scenario: Host key changed

- **WHEN** the tool connects to a host that presents a key different from the pinned one
- **THEN** the connection fails with reason `host-key-changed` and the connection is not used

#### Scenario: Already-trusted host key does not prompt

- **WHEN** the tool connects to a host whose presented key matches the pinned key
- **THEN** the connection proceeds without any prompt

### Requirement: Host connectivity can be tested

The system SHALL let the user test connectivity to a host by opening an SSH session,
confirming the remote models base path exists and is a directory, and recording the
result with a timestamp. A failed test SHALL record a reason drawn from
`authentication`, `unreachable`, `timeout`, `missing/inaccessible base path`,
`host-key-unknown`, `host-key-changed`, and `sftp-unavailable`, and the recorded
reason SHALL include the underlying detail (for example the transport error message
or the offending fingerprint) so the failure can be diagnosed.

#### Scenario: Successful connectivity test

- **WHEN** the user tests a host that is reachable, authenticates, and whose base path is a directory
- **THEN** the system records a success result with the current timestamp

#### Scenario: Unreachable host

- **WHEN** the user tests a host whose address cannot be reached within the timeout
- **THEN** the system records a failure result with reason "unreachable" or "timeout" plus the underlying detail

#### Scenario: Base path missing on host

- **WHEN** the user tests a reachable, authenticating host whose remote models base path does not exist
- **THEN** the system records a failure result with reason "missing/inaccessible base path"

#### Scenario: Host key not trusted

- **WHEN** the user tests a host whose key is unknown and does not confirm the fingerprint
- **THEN** the system records a failure result with reason "host-key-unknown"

#### Scenario: SFTP subsystem unavailable

- **WHEN** the user tests a host that authenticates over SSH but whose SFTP subsystem cannot be opened
- **THEN** the system records a failure result with reason "sftp-unavailable" plus the underlying detail
