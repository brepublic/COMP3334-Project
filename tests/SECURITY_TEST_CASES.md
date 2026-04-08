# Security Test Cases

These security test cases are written to verify whether the system resists the attacks required by the project threat model.

## STC-01 Replay Attack

- Goal: verify replay resistance and de-duplication.
- Threat: a malicious client or network attacker replays an old ciphertext so the receiver accepts it as a new message.
- Automated test: [`tests/test_security_attacks.py`](/Users/tj/Downloads/project/COMP3334/tests/test_security_attacks.py) `test_attack_replay_ciphertext_is_rejected`
- Procedure:
  1. Alice sends one encrypted message to Bob.
  2. Bob pulls with `--no-ack` so the ciphertext stays on the server.
  3. Bob pulls again and receives the same ciphertext a second time.
- Expected result:
  - The second pull must reject the ciphertext as replayed.
  - The plaintext must not be stored as a second local message.
  - Unread/history state must not duplicate.

## STC-02 Ciphertext / Metadata Tampering Attack

- Goal: verify end-to-end integrity and authenticated metadata.
- Threat: an attacker modifies stored ciphertext or AAD-bound metadata such as TTL before delivery.
- Automated test: [`tests/test_security_attacks.py`](/Users/tj/Downloads/project/COMP3334/tests/test_security_attacks.py) `test_attack_tampered_envelope_is_not_accepted`
- Procedure:
  1. Alice sends one encrypted message to Bob while Bob is offline.
  2. The stored server envelope is modified by changing `ttl`.
  3. Bob pulls the tampered ciphertext.
- Expected result:
  - Decryption/validation must fail.
  - Bob must not see valid plaintext.
  - No local message row should be created for the tampered content.

## STC-03 Identity Key Substitution Attack

- Goal: verify key-change visibility and prevent silent trust of a new identity key.
- Threat: the contact identity key is replaced, simulating key substitution by a malicious server or account reinstallation attack.
- Automated test: [`tests/test_security_attacks.py`](/Users/tj/Downloads/project/COMP3334/tests/test_security_attacks.py) `test_attack_identity_key_substitution_triggers_warning`
- Procedure:
  1. Alice syncs Bob's fingerprint.
  2. Bob logs in from a fresh local profile and publishes a different identity key.
  3. Alice sends again to Bob.
- Expected result:
  - Alice must see a key-change warning.
  - The replacement key must not remain silently trusted.
  - The contact should require re-verification.

## STC-04 Stolen / Old Token Reuse

- Goal: verify session invalidation and single-device token revocation.
- Threat: an attacker tries to reuse a logged-out token or a token from an older login session.
- Automated coverage: [`tests/test_server_auth.py`](/Users/tj/Downloads/project/COMP3334/tests/test_server_auth.py) `test_register_login_logout_and_single_device_invalidation`
- Expected result:
  - A logged-out token must return `401`.
  - A token from an older login must return `401` after a newer successful login.

## STC-05 Registration and Login Abuse

- Goal: verify basic abuse controls.
- Threat: an attacker tries repeated registration/login attempts to brute-force or spam the service.
- Automated coverage:
  - [`tests/test_server_auth.py`](/Users/tj/Downloads/project/COMP3334/tests/test_server_auth.py) `test_registration_rate_limit`
  - [`tests/test_server_auth.py`](/Users/tj/Downloads/project/COMP3334/tests/test_server_auth.py) `test_login_rate_limit`
  - [`tests/test_server_contacts.py`](/Users/tj/Downloads/project/COMP3334/tests/test_server_contacts.py) `test_friend_request_rate_limit_enforced`
- Expected result:
  - Registration is rate-limited.
  - Login failures are rate-limited.
  - Excessive friend requests trigger cooldown / blocking.
