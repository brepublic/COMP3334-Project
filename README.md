## COMP3334 Secure IM (E2EE) — Design & Usage

This repository implements a **1:1 secure instant messaging system** with **end-to-end encryption (E2EE)**, an **honest-but-curious** server, and a **CLI-based client** (GUI is not required).

### Project scope (explicit)
- **1:1 private chat only**: no group chats.
- **No multi-device synchronization**: each client instance is treated as a single device for the project demo.
- **Server model**: honest-but-curious (HbC). The server relays and stores **ciphertext only** and must not learn plaintext.

---

## Threat model & security goals (spec-aligned)
### Threat model
- **HbC server**: follows protocol but may inspect databases/logs and perform traffic analysis (timestamps, sizes, contact graph).
- **Network attacker**: can observe traffic; may attempt MITM if transport security is misconfigured; may duplicate/reorder packets.
- **Malicious clients/users**: can spam friend requests, send malformed messages, replay ciphertext, or attempt UI-layer impersonation.

### Security goals
- **Confidentiality vs server**: server cannot decrypt message contents.
- **Integrity + authentication**: attackers cannot forge/modify messages undetectably for conversations they are not part of.
- **Replay resistance**: duplicated/replayed ciphertext is not accepted as a new message.
- **Key change visibility**: if a contact’s identity key changes, users are warned and the policy is clear.

---

## Architecture & trust boundaries
### Client responsibilities (trusted endpoint)
- Generate and store a **per-device long-term identity keypair** locally.
- Fetch contacts’ **public keys** and establish a shared secret.
- Perform **AEAD encryption/decryption**, validate authenticated metadata (AAD), and reject tampering.
- Maintain **replay/dedup state**, **TTL self-destruct behavior**, **conversation list**, and **unread counters**.
- Produce **delivery receipts** (E2EE-protected) to define “Delivered”.

### Server responsibilities (untrusted for plaintext)
- Registration/login (password + OTP), session tokens, logout/invalidation.
- Friend request workflow, block/unblock enforcement, anti-spam defaults.
- Distribute **public keys only** (no private keys).
- Relay messages and store offline **ciphertext queues** (store-and-forward).

---

## Cryptography choices (primitives, libraries, safe usage)
This project uses well-reviewed libraries; we do **not** implement cryptographic primitives from scratch.

- **Password hashing**: Argon2 (via `argon2-cffi`), with per-user salt.
- **OTP (2FA)**: TOTP (via `pyotp`).
- **Transport security**: TLS for HTTP and WebSocket connections.
- **E2EE building blocks** (via `cryptography`):
  - **Key agreement**: X25519.
  - **KDF**: HKDF-SHA256 with domain-separated context strings.
  - **Authenticated encryption (AEAD)**: ChaCha20-Poly1305 *or* AES-256-GCM.
  - **Hash/fingerprint**: SHA-256 over canonical public key bytes.
- **Randomness**: cryptographically secure RNG from the OS (library-backed).
- **Nonce safety**: AEAD nonces are generated uniquely per message; nonce reuse under the same key is forbidden.

---

## Identity & key management (R4–R6)
### Per-device identity keypair
- Each client generates a **long-term identity keypair** on first run (per device).
- The server stores **only public keys** (per device) so others can initiate secure sessions.

### Fingerprint / verification UI
- For each contact device public key, the client computes a **fingerprint** (e.g., SHA-256 → safety number / hex) and shows it to the user.
- User can mark a contact/device as **verified** (local state is acceptable).

### Key change detection policy (explicit)
- The client stores the last-seen key hash for each contact device.
- When keys are fetched/refreshed:
  - If the key hash changes, the client **warns the user**, marks the device **unverified**, and records the change.
  - **Policy** (chosen for usability): allow continuing the conversation **with a persistent warning** until re-verified.
    - Rationale: avoids hard lockout during legitimate re-installs while still making key changes visible.

---

## Secure session establishment (R7)
To establish a shared secret for 1:1 messaging under an HbC server:
- Sender fetches receiver device public key(s) from the server.
- Sender derives a shared secret using **X25519** DH between sender identity private key and receiver identity public key.
- A session key is derived with **HKDF**:
  - input key material = DH shared secret
  - salt/info include both user IDs + device IDs + protocol version (domain separation)

Limitations (documented honestly):
- This minimal static-DH design does **not** provide strong forward secrecy comparable to full ratcheting designs (e.g., Signal Double Ratchet). It is acceptable for this course if described clearly; future work can add prekeys/ratcheting.

---

## E2EE message format, AAD binding, replay/dedup (R8–R9)
### Crypto envelope (canonical fields)
Messages are transmitted as a JSON “envelope” that contains metadata plus AEAD ciphertext:

- `v`: protocol version
- `type`: `CHAT` or `RECEIPT`
- `client_msg_id`: UUID generated by sender (unique)
- `sender_uuid`, `receiver_uuid`
- `sender_device_id` (or key id / fingerprint)
- `counter`: per-(sender_device, receiver) monotonic counter
- `ttl_seconds`: time-to-live for self-destruct
- `created_at`: RFC3339 timestamp
- `nonce`: base64 AEAD nonce
- `ciphertext`: base64 AEAD ciphertext+tag

### Authenticated Associated Data (AAD)
The following fields are bound as AAD (must match exactly on decrypt):
- `v`, `type`, `client_msg_id`
- `sender_uuid`, `receiver_uuid`
- `sender_device_id`
- `counter`, `ttl_seconds`, `created_at`

This detects tampering of routing/TTL/counters even if ciphertext is unchanged.

### Replay resistance / de-duplication
Receiver enforces:
- **Uniqueness**: reject any `client_msg_id` already seen for this conversation.
- **Counter monotonicity**: track the highest counter per sender device; reject duplicated counters. To tolerate network duplication/reordering, allow a small reordering window (e.g., accept counters in \([max_seen+1, max_seen+W]\) and keep a bitmap/seen-set within the window).
- Maintain a local **SeenMessage** store (e.g., DB table) so replays remain rejected across restarts.

---

## Timed self-destruct messages (R10–R12)
### TTL policy (authenticated)
- `ttl_seconds` is included in the **AAD**, so the TTL cannot be modified without detection.
- The client computes `expires_at = created_at + ttl_seconds`.

### Client deletion behavior
- Expired messages are removed from:
  - conversation views / history output
  - local storage
- A periodic cleanup task can sweep for expired rows.

### Server best-effort behavior
- If the server stores offline ciphertext, it deletes it after expiry **best-effort** (TTL is also provided in server request fields to enable cleanup).

Limitations (explicit)
- Self-destruct cannot prevent screenshots/copy/paste or a malicious client; this is out of scope.

---

## Friends / contacts (R13–R16)
- Contacts are added via **friend request → accept/decline** workflow (no instant add by default).
- Request lifecycle:
  - receiver: accept/decline
  - sender: cancel
  - both: view pending requests
- Blocking/removing:
  - user can remove friends and block users
  - blocked users’ requests/messages are ignored
- Default anti-spam:
  - **non-friends cannot send arbitrary chat messages**
  - only friend requests are allowed from non-friends

---

## Message delivery status (R17–R19)
### Delivery states
- **Sent**: sender client successfully submitted ciphertext to the server (server accepted).
- **Delivered**: recipient client successfully decrypted a message and sent an **E2EE-protected `RECEIPT`** back to the sender.

### Metadata disclosure statement
Even with E2EE, the server can still learn:
- timing/volume of messages (traffic analysis)
- message sizes (unless padded)
- social graph (who talks to whom)
Delivery receipts can further reveal **recipient online timing** (discussed in report).

---

## Offline messaging (ciphertext store-and-forward) (R20–R22)
- If recipient is offline, server queues **ciphertext envelopes** and relays when online.
- Retention & cleanup:
  - ciphertext is deleted after recipient ACK / receipt flow (best-effort), or after a max age policy (e.g., 7 days)
  - TTL expiry should be respected best-effort for queued ciphertext
- Duplicate robustness:
  - clients must safely handle duplicates from retries
  - dedup/replay rules (client_msg_id + counters) prevent accepting old ciphertext as new

---

## Conversation list, unread counters, paging (R23–R25)
- Client maintains a **conversation list** ordered by recent activity, with last message time.
- Client maintains an **unread count** per conversation and resets it when the conversation is opened/viewed.
- Client supports **incremental history loading** (pagination) from local storage to avoid loading all history at once.

---

## Engineering requirements (security)
- **Secure randomness**: use OS CSPRNG via crypto library.
- **Secure local storage**:
  - identity private keys and session state must be protected at rest (OS keychain or encrypted local storage)
  - do not store private keys plaintext on disk
- **Input validation**: all inbound/outbound API payloads validated; enforce size limits.
- **Minimal sensitive logging**: do not log secrets; disable verbose debug logs by default.
- **Rate limiting / abuse controls**: registration/login/friend requests are rate-limited (e.g., SlowAPI).
- **Transport security**: TLS for client-server HTTP and WebSocket.

Notes on sensitive server-side secrets:
- The server may need to store an OTP seed/secret to validate TOTP codes. This is **not** an E2EE secret, but it is still sensitive and must be protected (restricted access, avoid logging, and prefer encrypt-at-rest if supported by the deployment).

---

## Roadmap / module checklist (tracked against spec)
- [x] **1. Register & Login (R1–R3)**\n  - register with email/username, store Argon2-hashed password\n  - login with password + TOTP\n  - session token expiry + logout/session invalidation
- [ ] **2. Identity key management (R4–R6)**\n  - per-device identity keypair stored locally (encrypted)\n  - server stores device public keys\n  - fingerprint display + verified flag\n  - key change detection (warn + re-verify policy)
- [ ] **3. E2EE messaging (R7–R9)**\n  - session establishment via X25519 + HKDF\n  - AEAD per message + AAD-bound metadata\n  - replay/dedup via client_msg_id + counters
- [x] **4. Contact management (R13–R16)**\n  - request/accept/decline; block/unblock\n  - default anti-spam: non-friends cannot message
- [x] **5. Offline messages (R20–R22)**\n  - ciphertext queue store-and-forward\n  - ACK/cleanup policy
- [ ] **6. Timed self-destruct (R10–R12)**\n  - TTL authenticated + client deletion + server best-effort deletion
- [ ] **7. Conversation list/unread/paging (R23–R25)**\n  - conversation list ordering + unread counters\n  - incremental history loading
- [ ] **8. Delivery receipts semantics (R17–R19)**\n  - E2EE receipt messages define Delivered

---

## Data model (design sketch)
This section describes **intended** storage (server stores ciphertext; client stores local state). Final schema may evolve; security constraints above are normative.

### Server-side storage (conceptual)
Table `User`:\n- `uuid` (PK)\n- `email` (unique)\n- `user_name`\n- `password_hash`\n- `otp_secret` (or equivalent; protect appropriately)\n\nTable `Device`:\n- `device_id` (PK)\n- `user_uuid` (FK)\n- `device_hash`\n- `device_public_key`\n\nTable `Friendship`:\n- `relation_id` (PK)\n- `user_id_a` (FK)\n- `user_id_b` (FK)\n- `status` (pending/accepted/blocked/etc.)\n\nTable `FriendRequest`:\n- `request_id` (PK)\n- `sender_uuid` (FK)\n- `receiver_uuid` (FK)\n- `status`\n- `expires_at`\n\nTable `OfflineMessage`:\n- `message_id` (PK)\n- `sender_uuid` (FK)\n- `receiver_uuid` (FK)\n- `ciphertext_envelope`\n- `expires_at`\n\n### Client-side storage (conceptual)\nTable `LocalIdentity`:\n- `user_uuid` (PK)\n- `public_key`\n- `private_key_encrypted`\n\nTable `Conversation`:\n- `contact_uuid` (PK)\n- `contact_name`\n- `unread_count`\n- `last_activity`\n\nTable `ContactDevice`:\n- `contact_device_id` (PK)\n- `contact_uuid` (FK)\n- `public_key`\n- `fingerprint`\n- `is_verified`\n- `last_seen_key_hash`\n\nTable `Message`:\n- `client_msg_id` (PK)\n- `conversation_id` (FK)\n- `direction` (INBOUND/OUTBOUND)\n- `status` (SENT/DELIVERED)\n- `message_type` (CHAT/RECEIPT)\n- `created_at`\n- `expires_at`\n- `plaintext_local` (optional; if stored, must be protected at rest)\n\nTable `SeenMessage` (dedup):\n- `client_msg_id`\n- `conversation_id`\n- `received_at`\n\n---

## Deployment & usage (Ubuntu / Windows 11)
### Prerequisites
- Python 3.10+ recommended
- `pip` + virtual environment

### Install
Create a venv and install dependencies:
- `pip install -r requirements.txt`

### Run (client demo flow)
The client uses environment variables to choose where to store local state and the local DB:
- `CLIENT_STATE_PATH` (e.g., `/tmp/client-a-state.json`)\n- `CLIENT_DB_PATH` (e.g., `/tmp/client-a.db`)

Typical demo steps (two terminals, two users) are documented in:\n- `Client/ReadMe/what_to_test.md`

---

## Requirements mapping (R1–R25)
This section maps the spec requirements to the README’s design sections (and acts as a checklist for implementation completion).

- **R1–R3 Accounts & authentication**: “Cryptography choices”, “Engineering requirements”, “Roadmap / module checklist”.\n- **R4–R6 Identity & key management**: “Identity & key management”.\n- **R7–R9 E2EE messaging**: “Secure session establishment”, “E2EE message format…”.\n- **R10–R12 Self-destruct**: “Timed self-destruct messages”.\n- **R13–R16 Friends/contacts**: “Friends / contacts”.\n- **R17–R19 Delivery status**: “Message delivery status”.\n- **R20–R22 Offline messaging**: “Offline messaging”.\n- **R23–R25 Conversations/unread/paging**: “Conversation list, unread counters, paging”.\n*** End of File