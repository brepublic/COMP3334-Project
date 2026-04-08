# Tests README

This folder contains the automated verification suite for the COMP3334 secure messaging project.

It has two goals:

1. Verify that the required functions in `Project_requirements.md` work correctly.
2. Verify that the design resists common attacks from the project threat model.

## How The Tests Work

The test suite uses `pytest`.

There are two main testing layers:

- Server integration tests:
  - These use FastAPI `TestClient`.
  - The real server app is imported and exercised in-process.
  - A temporary SQLite database is created for each test.
  - JWT secret and server DB path are isolated through environment variables.

- Client workflow tests:
  - These use Typer `CliRunner`.
  - The real CLI commands are executed.
  - Client state and client DB files are created in temporary per-test folders.
  - Client API calls are redirected into the in-process FastAPI test server, so the CLI is tested end-to-end without needing a separate running server.

The shared fixture setup is in [`tests/conftest.py`](/Users/tj/Downloads/project/COMP3334/tests/conftest.py).

## How To Run

Run the full suite:

```bash
pytest -q tests
```

Run only the security attack tests:

```bash
pytest -q tests/test_security_attacks.py
```

Run one file at a time:

```bash
pytest -q tests/test_server_auth.py
pytest -q tests/test_server_contacts.py
pytest -q tests/test_server_messages.py
pytest -q tests/test_client_workflows.py
```

## What Each Test File Does

### `tests/conftest.py`

This is the shared test harness.

It does the following:

- creates isolated temporary server databases
- configures test-only environment variables
- resets imported server modules between tests
- creates helper functions for:
  - registering users
  - logging in users
  - making users become friends
- creates a client CLI harness so `Client.main` commands can be tested like a real user would run them

### `tests/test_server_auth.py`

This file verifies authentication and session security.

It tests:

- registration works
- logout revokes the current token
- re-login invalidates older tokens under the single-device policy
- registration rate limiting works
- login rate limiting works

Why this matters:

- verifies account security requirements
- checks abuse controls
- checks that stolen or stale tokens cannot continue working

### `tests/test_server_contacts.py`

This file verifies friend-request and contact-management behavior.

It tests:

- incoming pending request listing
- outgoing pending request listing
- decline flow
- sender cancel flow
- blocking a user, including a non-friend
- ignoring blocked requests
- friend-request spam rate limit / cooldown

Why this matters:

- verifies the required request lifecycle
- verifies anti-spam and blocking behavior
- checks that blocked users cannot keep interacting normally

### `tests/test_server_messages.py`

This file verifies message-side server enforcement.

It tests:

- non-friends cannot actually deliver chat messages
- offline messages are returned in deterministic order
- oversized message payloads are rejected
- blocked users’ messages are ignored

Why this matters:

- verifies default anti-spam message control
- checks input validation and storage behavior
- checks blocked-user enforcement

### `tests/test_client_workflows.py`

This file verifies full client-side workflows through the real CLI.

It tests:

- encrypted client state storage after login
- CLI request management commands:
  - `pending`
  - `decline`
  - `cancel-request`
  - `block-user`
- message send / pull flow
- delivered receipt flow
- history and conversation updates
- key-change warning on normal send flow
- TTL/self-destruct cleanup in local history

Why this matters:

- verifies the user-facing commands actually work
- checks local secure storage
- checks delivery status semantics
- checks key-change visibility
- checks timed self-destruct cleanup

### `tests/test_security_attacks.py`

This file contains dedicated attack-oriented security tests.

It tests:

- replay attack resistance
- ciphertext / authenticated metadata tampering resistance
- identity-key substitution detection

Why this matters:

- these are direct checks against the threat model in the project requirements
- they verify that attacks are rejected rather than only checking normal happy paths

### `tests/SECURITY_TEST_CASES.md`

This is a written security test-case document.

It explains:

- the objective of each security test
- the attacker model
- the test procedure
- the expected secure result

Use this file when you need report-style descriptions, while `tests/test_security_attacks.py` is the executable version.

## The Security Tests One By One

### Replay attack

Implemented in:

- [`tests/test_security_attacks.py`](/Users/tj/Downloads/project/COMP3334/tests/test_security_attacks.py)

What it does:

1. Alice sends one encrypted message to Bob.
2. Bob pulls with `--no-ack`, so the ciphertext remains available.
3. Bob pulls again.

What should happen:

- the second copy is detected as replayed
- the plaintext is not accepted as a new message
- no duplicate local message is stored

### Tampering attack

Implemented in:

- [`tests/test_security_attacks.py`](/Users/tj/Downloads/project/COMP3334/tests/test_security_attacks.py)

What it does:

1. Alice sends an encrypted message while Bob is offline.
2. The stored server envelope is manually changed by modifying `ttl`.
3. Bob pulls the tampered ciphertext.

What should happen:

- decryption/validation fails
- Bob does not see valid plaintext
- no message is stored locally

### Identity-key substitution attack

Implemented in:

- [`tests/test_security_attacks.py`](/Users/tj/Downloads/project/COMP3334/tests/test_security_attacks.py)

What it does:

1. Alice syncs Bob's key.
2. Bob logs in from a fresh client profile, causing a new identity key to be uploaded.
3. Alice sends again.

What should happen:

- Alice sees a key-change warning
- the new identity is not silently treated as already trusted

## Notes

- The tests assume the project scope is single-device only.
- The tests do not require a separately running server process.
- The TLS tests in the suite verify configuration and secure defaults, not a full real-certificate network deployment.
