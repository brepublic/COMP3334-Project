  Phase 1: Make The Client Runnable
  Goal: one command can register, login, and talk to the server.

  TODO:

  - Add dependencies: httpx, websockets, cryptography, typer or argparse, pyotp optional, keyring optional.
  - Add main.py with commands like:
      - register
      - login
      - friends
      - add-friend
      - pending
      - accept
      - chat
      - pull
  - Add config handling for:
      - server base URL
      - websocket URL
      - local DB path
      - local device ID
  - Add token persistence to local storage.
  - Add a startup check that initializes the local DB.

  Phase 2: Local Data Model
  Your current local schema is not enough for the rubric.

  TODO:

  - Extend Client/CLient_db.py with missing client-side fields:
      - Conversation.last_activity
      - Conversation.last_message_preview optional
      - Message.client_msg_id
      - Message.server_msg_id nullable
      - Message.direction (INBOUND/OUTBOUND)
      - Message.status (SENT/DELIVERED/FAILED)
      - Message.message_type (CHAT/RECEIPT)
      - Message.created_at
      - Message.expires_at
      - ContactDevice.fingerprint
      - ContactDevice.last_seen_key_hash
      - ContactDevice.verified_at optional
  - Add a table for dedup/replay tracking if needed:
      - SeenMessage(client_msg_id, conversation_id, received_at)
  - Add a table for session/app state if needed:
      - current user UUID
      - JWT
      - device hash
  - Encrypt the stored private key before writing it to DB. Do not leave it plaintext.

  Phase 3: Auth And Identity
  Goal: the client can create and persist its identity and authenticate cleanly.

  TODO:

  - On first run, generate a stable local device_hash.
  - On first login/register, generate an X25519 keypair if one does not exist.
  - Store the private key encrypted locally.
  - Convert the public key to base64 for device_public_key.
  - Implement register using POST /api/v1/register.
  - After register, display or save the OTP secret from the response.
  - Implement login using POST /api/v1/login.
  - Persist:
      - user_uuid
      - JWT
      - device hash
      - local keypair
  - Treat the app as single-device for now because the server currently deletes previous devices on login.

  Phase 4: API Client
  Goal: isolate all backend calls behind one clean layer.

  TODO:

  - Implement HTTP methods for:
      - POST /api/v1/register
      - POST /api/v1/login
      - POST /api/v1/friends/request
      - GET /api/v1/friends/pending
      - POST /api/v1/friends/action
      - GET /api/v1/friends
      - POST /api/v1/friends/block
      - GET /api/v1/friends/{contact_uuid}/keys
      - DELETE /api/v1/friends/request/{request_id}
      - POST /api/v1/messages/send
      - GET /api/v1/messages/offline
      - POST /api/v1/messages/ack
  - Add auth header injection automatically.
  - Add retry and timeout policy.
  - Validate all responses with Client/Schema.py.

  Phase 5: Crypto Envelope
  Goal: define one stable message format and use it everywhere.

  Use a JSON envelope serialized into the server ciphertext string:

  {
    "v": 1,
    "type": "CHAT",
    "client_msg_id": "uuid",
    "sender_uuid": "uuid",
    "receiver_uuid": "uuid",
    "sender_kid": "fingerprint-or-device-id",
    "counter": 12,
    "ttl": 300,
    "created_at": "2026-04-06T12:34:56Z",
    "nonce": "base64",
    "ciphertext": "base64"
  }

  AAD should include:

  - v
  - type
  - client_msg_id
  - sender_uuid
  - receiver_uuid
  - counter
  - ttl
  - created_at

  TODO:

  - Implement canonical encoding for AAD.
  - Encrypt plaintext with AEAD.
  - Decrypt and verify AAD on receive.
  - Reject invalid or tampered envelopes.
  - Add receipt envelope:

  {
    "v": 1,
    "type": "RECEIPT",
    "client_msg_id": "receipt-msg-id",
    "ack_client_msg_id": "original-msg-id",
    ...
  }

  Phase 6: Contacts, Key Fetching, Fingerprints
  Goal: satisfy identity management requirements on the client.

  TODO:

  - Fetch friend list from server and create/update local conversations.
  - Fetch contact device keys using GET /friends/{uuid}/keys.
  - Compute and store fingerprint for each contact device.
  - Add CLI command to show a contact’s fingerprint.
  - Add CLI command to mark a device/contact as verified.
  - On every key refresh:
      - compare current key hash against stored key hash
      - if changed, mark device unverified
      - warn user clearly
  - Define policy:
      - simplest: allow sending but show a warning until re-verified
      - stricter: block sending until re-verified

  Phase 7: Sending Messages
  Goal: end-to-end encrypted outgoing chat works.

  TODO:

  - Before sending, fetch or refresh the contact public key.
  - Derive the shared secret.
  - Build encrypted envelope.
  - Save outbound plaintext locally first with status SENT.
  - Send via HTTP first for reliability, or WS for realtime if connected.
  - If using HTTP:
      - call POST /messages/send
      - store returned server_msg_id if any
      - mark as SENT
  - If using WS:
      - send same payload shape expected by /ws/chat
  - Include TTL in the encrypted envelope and also in the server request field.

  Recommended practical choice:

  - Use HTTP send as the default path because it gives a structured response.
  - Use WS mainly for receiving realtime pushes.
  - Later, if stable, add WS send mode.

  Phase 8: Receiving Messages
  Goal: online and offline receive paths behave the same.

  TODO:

  - On startup/login:
      - call GET /messages/offline
      - decrypt each message
      - store locally
      - update conversation unread counters
      - collect message_ids
      - call POST /messages/ack
  - Run websocket loop:
      - connect to /ws/chat?token=...
      - receive NEW_MESSAGE
      - decrypt envelope
      - store locally
      - update unread count
  - After accepting a valid CHAT message:
      - automatically send an encrypted RECEIPT message back to sender
  - On receiving a RECEIPT:
      - mark the original outbound message as DELIVERED

  This gives you delivered semantics without changing the server.

  Phase 9: Self-Destruct
  Goal: satisfy the timed self-destruct requirement on the client.

  TODO:

  - Compute expires_at = created_at + ttl.
  - Store expires_at locally per message.
  - On message load and on periodic sweep:
      - delete expired messages from local DB
      - remove from UI/CLI views
  - Show remaining TTL when displaying a self-destructing message if useful.
  - Never trust server TTL alone; trust the authenticated TTL inside the envelope.

  Phase 10: Conversation List And Unread Counters
  Goal: satisfy the usability requirements.

  TODO:

  - Create/update Conversation rows whenever:
      - a friend is added
      - a message is sent
      - a message is received
  - Maintain:
      - last_activity
      - unread count
  - Add commands:
      - conversations
      - open <contact>
      - history <contact> --limit 20 --before <timestamp>
  - Reset unread count when a conversation is opened.
  - Implement incremental history loading from the local DB.

  Phase 11: Replay Protection
  Goal: satisfy the replay/dedup requirement.

  TODO:

  - Add client_msg_id to every message.
  - Add counter per conversation or sender-device pair.
  - Keep a local seen-set for inbound client_msg_id.
  - Reject:
      - duplicate client_msg_id
      - stale counters if you enforce monotonicity
  - Log replay attempts locally for debugging.

  Phase 12: Demo-Ready CLI
  Goal: make the project easy to show.

  Minimum CLI commands:

  - register
  - login
  - friends list
  - friends add <email>
  - friends pending
  - friends accept <request_id>
  - keys show <contact_uuid>
  - keys verify <contact_uuid>
  - chat send <contact_uuid> "hello" --ttl 30
  - chat pull
  - chat listen
  - chat history <contact_uuid>
  - chat open <contact_uuid>

  Phase 13: Testing
  Goal: avoid a last-minute integration failure.

  TODO:

  - Unit test:
      - key generation
      - shared-secret derivation
      - encrypt/decrypt roundtrip
      - fingerprint generation
      - replay rejection
      - TTL deletion
  - Integration test:
      - register two users
      - login both
      - send friend request
      - accept request
      - fetch keys
      - send encrypted message
      - receive via offline pull
      - receive via websocket
      - receipt updates sender status to delivered
  - Manual demo script:
      - fresh DB
      - two terminals
      - full chat flow
      - key verification flow
      - key change warning flow
      - self-destruct flow

  Order To Build
  Build in this exact order:

  1. Runnable CLI skeleton
  2. Local DB extensions
  3. Auth + token persistence
  4. Local keypair generation
  5. HTTP API wrapper
  6. Offline pull + ack
  7. Crypto envelope
  8. Send/receive one encrypted message
  9. Websocket listener
  10. Delivery receipts
  11. Fingerprint/verification/key-change warning
  12. Self-destruct
  13. Conversation list/unread/history
  14. Tests and demo script

  What You Can Implement Without Server Changes
  You can finish almost all client requirements without changing the shared server schema:

  - E2EE
  - fingerprints
  - verified state
  - key-change warnings
  - receipts
  - replay protection
  - self-destruct
  - conversation list
  - unread counters
  - pagination/history

  What To Coordinate With The Server Teammate
  These are the only things I would raise early:

  - Confirm single-device login is intentional because server deletes old devices on login.
  - Confirm whether you should treat “Delivered” as your own encrypted receipt message.
  - Confirm whether any server changes are allowed if you later want better WS delivery semantics.
  - Confirm final report will explain the crypto design and limitations.

  Practical Recommendation
  Do not start with GUI.
  Ship a clean async CLI first, with:

  - login
  - friend workflow
  - key display/verify
  - encrypted send/receive
  - receipts
  - TTL deletion
  - unread counters