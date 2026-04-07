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
  - if a user sends **10 or more friend requests within 1 minute**, the user is blocked from sending new friend requests for **30 minutes**

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
- [x] **1. Register & Login (R1–R3)** — implemented
  - [x] implemented: register with email/username, store Argon2-hashed password
  - [x] implemented: login with password + TOTP
  - [x] implemented: session token expiry + logout/session invalidation (`POST /api/v1/logout` revokes current token, `POST /api/v1/logout-all` invalidates older sessions via user cutoff timestamp)
- [x] **2. Identity key management (R4–R6)** — implemented
  - [x] implemented: per-device identity keypair stored locally (encrypted with a KEK derived from login password)
  - [x] implemented: server stores device public keys
  - [x] implemented: fingerprint display + verified flag (`sync-contact-keys`, `show-fingerprints`, `verify-device`)
  - [x] implemented: key change detection (warn + re-verify policy, with persistent unverified state until user verifies)
- [x] **3. E2EE messaging (R7–R9)** — implemented
  - [x] implemented: session establishment via X25519 + HKDF-SHA256 (`derive_session_key` with protocol/device/user context binding)
  - [x] implemented: per-message AEAD (AES-256-GCM) with canonical JSON AAD over routing/message metadata
  - [x] implemented: replay/dedup via `client_msg_id` seen-set + per-sender-device inbound counter checks
  - [x] note: current counter policy is strict monotonic (`incoming_counter > latest_seen`) and does not yet implement an out-of-order acceptance window
- [x] **4. Contact management (R13–R16)** — implemented
  - [x] implemented: request/accept/decline; block/unblock
  - [x] implemented: default anti-spam: non-friends cannot message
  - [x] implemented: friend-request spam control (`>=10 / 1 minute` triggers `30 minutes` cooldown)
- [x] **5. Offline messages (R20–R22)** — implemented
  - [x] implemented: ciphertext queue store-and-forward
  - [x] implemented: ACK/cleanup policy (ack delete + periodic expiry cleanup)
- [x] **6. Timed self-destruct (R10–R12)** — implemented
  - [x] implemented: TTL is authenticated in AAD, and client performs local expiry cleanup before pull/history/conversations views
  - [x] implemented: server best-effort expiry cleanup for queued ciphertext
- [x] **7. Conversation list/unread/paging (R23–R25)** — implemented
  - [x] implemented: `conversations` command ordered by `last_activity` and showing unread counters
  - [x] implemented: `history <contact_uuid> --limit N --before <rfc3339>` incremental local pagination
- [x] **8. Delivery receipts semantics (R17–R19)** — implemented
  - [x] implemented: Delivered is defined by E2EE `RECEIPT` (recipient decrypts CHAT then sends encrypted receipt back)

---

## Data model (design sketch)
This section describes **intended** storage (server stores ciphertext; client stores local state). Final schema may evolve; security constraints above are normative.

### Server-side storage (conceptual)
Table `User`:
- `uuid` (PK)
- `email` (unique)
- `user_name`
- `password_hash`
- `otp_secret` (or equivalent; protect appropriately)

Table `Device`:
- `device_id` (PK)
- `user_uuid` (FK)
- `device_hash`
- `device_public_key`

Table `Friendship`:
- `relation_id` (PK)
- `user_id_a` (FK)
- `user_id_b` (FK)
- `status` (pending/accepted/blocked/etc.)

Table `FriendRequest`:
- `request_id` (PK)
- `sender_uuid` (FK)
- `receiver_uuid` (FK)
- `status`
- `expires_at`

Table `OfflineMessage`:
- `message_id` (PK)
- `sender_uuid` (FK)
- `receiver_uuid` (FK)
- `ciphertext_envelope`
- `expires_at`

### Client-side storage (conceptual)
Table `LocalIdentity`:
- `user_uuid` (PK)
- `public_key`
- `private_key_encrypted`

Table `Conversation`:
- `contact_uuid` (PK)
- `contact_name`
- `unread_count`
- `last_activity`

Table `ContactDevice`:
- `contact_device_id` (PK)
- `contact_uuid` (FK)
- `public_key`
- `fingerprint`
- `is_verified`
- `last_seen_key_hash`

Table `Message`:
- `client_msg_id` (PK)
- `conversation_id` (FK)
- `direction` (INBOUND/OUTBOUND)
- `status` (SENT/DELIVERED)
- `message_type` (CHAT/RECEIPT)
- `created_at`
- `expires_at`
- `plaintext_local` (optional; if stored, must be protected at rest)

Table `SeenMessage` (dedup):
- `client_msg_id`
- `conversation_id`
- `received_at`

---

## Deployment & usage (Ubuntu / Windows 11)
### Prerequisites
- Python 3.10+ recommended
- `pip` + virtual environment

### Install
Create a venv and install dependencies:
- `pip install -r requirements.txt`

### Run (client demo flow)
The client uses environment variables to choose where to store local state and the local DB:
- `CLIENT_STATE_PATH` (e.g., `/tmp/client-a-state.json`)
- `CLIENT_DB_PATH` (e.g., `/tmp/client-a.db`)

Run a single command (existing behavior):
- `python -m Client.main --help`
- `python -m Client.main login --help`

Run interactive CLI mode (new behavior):
- Start REPL: `python -m Client.main interactive`
- In REPL, execute normal command names directly, for example:
  - `friends`
  - `pending`
  - `help chat`
- Prompt format:
  - logged-out: `guest@client>`
  - logged-in: `<username>@client>`
- `chat` command (interactive session):
  - `chat <username>`: open chat directly; if duplicate usernames exist, the client shows numbered candidates (`username + email + uuid`) to choose from
  - `chat` (without args): opens friend list (`No + Username + LastMessage`) for selection
  - in chat session:
    - plain text sends a message with default TTL
    - `/ttl <seconds> <message>` sends a self-destruct message with custom TTL
    - `/refresh` reloads recent local chat view
    - `/back` exits chat session
- `remove-friend <username>`:
  - remove a friend by username
  - duplicate usernames are disambiguated via numbered selection (`username + email + uuid`)
- Exit REPL with `exit`, `quit`, or `Ctrl+D`.
- Pressing `Ctrl+C` inside REPL cancels current input and keeps the session running.

Typical demo steps (two terminals, two users) are documented in:
- `Client/ReadMe/what_to_test.md`

---

## Requirements mapping (R1–R25)
This section maps the spec requirements to the README’s design sections (and acts as a checklist for implementation completion).

- **R1–R3 Accounts & authentication**: “Cryptography choices”, “Engineering requirements”, “Roadmap / module checklist”.
- **R4–R6 Identity & key management**: “Identity & key management”.
- **R7–R9 E2EE messaging**: “Secure session establishment”, “E2EE message format…”.
- **R10–R12 Self-destruct**: “Timed self-destruct messages”.
- **R13–R16 Friends/contacts**: “Friends / contacts”.
- **R17–R19 Delivery status**: “Message delivery status”.
- **R20–R22 Offline messaging**: “Offline messaging”.
- **R23–R25 Conversations/unread/paging**: “Conversation list, unread counters, paging”.