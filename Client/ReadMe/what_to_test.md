  What to test

  1. Client help

  python3 -m Client.main --help

  2. Register

  python3 -m Client.main register --email alice@example.com --user-name alice --password password123

  Expected:

  - prints user UUID
  - prints OTP secret

  3. Login

  python3 -m Client.main login --email alice@example.com --password password123 --otp-code <real-code>

  Expected:

  - prints logged-in UUID
  - prints local device ID
  - writes token/device state to your CLIENT_STATE_PATH
  - creates local DB and local identity row

  4. Friend request
     From Alice:

  python3 -m Client.main add-friend bob@example.com

  From Bob:

  python3 -m Client.main pending
  python3 -m Client.main accept <request_id>
  python3 -m Client.main friends

  From Alice:

  python3 -m Client.main friends

  Expected:

  - request shows in Bob’s pending list
  - accept succeeds
  - both friend lists show the relationship

  5. Message send/pull
     From Alice:

  python3 -m Client.main chat <bob_uuid> "hello from alice" --ttl 300

  From Bob:

  python3 -m Client.main pull

  Expected:

  - Alice gets server message ID and status
  - Bob sees the message printed from offline pull
  - pull ACKs by default, so running pull again should show no offline messages

  6. Identity key encryption at rest

  Login once:

  python3 -m Client.main login --email alice@example.com --password password123 --otp-code <real-code>

  Then inspect local DB:

  sqlite3 /tmp/client-a.db 'select uuid, public_key, private_key, private_key_encrypted, private_key_kdf from local_identity;'

  Expected:

  - `private_key` is NULL (or migrated away from legacy plaintext)
  - `private_key_encrypted` is populated
  - `private_key_kdf` is `scrypt`

  7. Fingerprint sync and verify flow

  Fetch and sync keys for Bob from Alice terminal:

  python3 -m Client.main sync-contact-keys <bob_uuid>
  python3 -m Client.main show-fingerprints <bob_uuid>

  Mark one device as verified:

  python3 -m Client.main verify-device <bob_uuid> <device_id>
  python3 -m Client.main unverified-keys

  Expected:

  - key fingerprints are shown for each active device
  - verification state changes after `verify-device`
  - `unverified-keys` only lists devices still unverified

  8. Key-change detection policy

  Trigger a key change by re-login from Bob with a fresh local identity DB, then on Alice:

  python3 -m Client.main sync-contact-keys <bob_uuid>

  Expected:

  - warning indicates key changed device(s)
  - changed device is automatically marked unverified
  - conversation remains allowed (policy: allow with persistent warning until re-verified)

  How to inspect whether local state is working
  Check the saved state file:

  cat /tmp/client-a-state.json

  You should see:

  - access_token
  - user_uuid
  - local_device_id

  Check the local DB:

  sqlite3 /tmp/client-a.db '.tables'
  sqlite3 /tmp/client-a.db 'select * from local_identity;'

  That proves:

  - DB bootstrap ran
  - identity generation ran

  What “good Phase 1” looks like
  Phase 1 is doing fine if all of these pass:

  - python3 -m Client.main --help works
  - register works
  - login works and persists token/device ID
  - friend request flow works
  - message send works
  - offline pull works
  - local DB file is created
  - local state file is created

  Known limitations of current Phase 1
  These are expected and not failures yet:

  - chat sends plaintext placeholder into the server ciphertext field
  - there is no E2EE yet
  - there is no websocket listen command yet
  - there is no conversation list/unread logic yet
  - identity key decryption currently depends on the login password provided during CLI login (single-password UX; no second passphrase)