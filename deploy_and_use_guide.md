# Deployment And Usage Guide

This document explains how to deploy and use the COMP3334 secure messaging application for local development or demo use.

Project scope assumptions:
- 1:1 private chat only
- single-device only
- no multi-device sync
- TLS is required for client-server communication

## 1. Prerequisites

Install these first:
- Python 3.10 or newer
- `pip`
- `mkcert`

Recommended:
- a Python virtual environment
- an authenticator app for TOTP, such as Google Authenticator, Microsoft Authenticator, or 1Password

## 2. Clone The Project

From your terminal:

```bash
git clone https://github.com/ShadowGuo-Touhou/COMP3334
cd COMP3334
```

## 3. Create A Virtual Environment

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Generate Local TLS Certificates

Do this once per machine.

Install the local CA:

```bash
mkcert -install
```

Generate a certificate for local development:

```bash
mkdir -p certs
mkcert -cert-file certs/dev.crt -key-file certs/dev.key localhost 127.0.0.1 ::1
```


## 5. Configure Server Environment

Copy the template:

```bash
cp .env.example .env
```

The default `.env` values are suitable for local use if you generated:
- `certs/dev.crt`
- `certs/dev.key`

Check that `.env` contains:

```env
JWT_SECRET_KEY=replace-with-a-long-random-secret
TLS_CERT_FILE=certs/dev.crt
TLS_KEY_FILE=certs/dev.key
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
LOG_LEVEL=warning
```

Replace `JWT_SECRET_KEY` with a real random value before sharing the project or demoing it.

Example:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 6. Start The Server

Run this from the project root:

```bash
python Server/MainServer.py
```

If startup succeeds, the server listens at:
- `https://127.0.0.1:8000`

Leave this terminal running.

## 7. Verify The Client CLI

From another terminal in the project root:

```bash
source .venv/bin/activate
python -m Client.main --help
```

You should see commands such as:
- `register`
- `login`
- `add-friend`
- `pull`
- `conversations`
- `history`
- `interactive`

## 8. Configure One Client Profile

Each user profile needs its own local state file and local database.

For user A:

```bash
export CLIENT_SERVER_BASE_URL=https://127.0.0.1:8000/api/v1
export CLIENT_WEBSOCKET_URL=wss://127.0.0.1:8000/ws/chat
export CLIENT_DB_PATH=/tmp/alice.db
export CLIENT_STATE_PATH=/tmp/alice-state.json
export CLIENT_STATE_KEY_PATH=/tmp/alice-state.key
```

For user B, use different files:

```bash
export CLIENT_SERVER_BASE_URL=https://127.0.0.1:8000/api/v1
export CLIENT_WEBSOCKET_URL=wss://127.0.0.1:8000/ws/chat
export CLIENT_DB_PATH=/tmp/bob.db
export CLIENT_STATE_PATH=/tmp/bob-state.json
export CLIENT_STATE_KEY_PATH=/tmp/bob-state.key
```

Do not share client state files between users.

## 9. Register A User

Register the first user:

```bash
python -m Client.main register --email alice@example.com --user-name alice --password Password123
```

The client prints:
- the user UUID
- the OTP secret
- a QR code for your authenticator app

Register the second user in another terminal configured with a different client profile:

```bash
python -m Client.main register --email bob@example.com --user-name bob --password Password123
```

## 10. Set Up OTP

When `register` runs, it prints an OTP secret and a provisioning QR code.

Use one of these methods:
- scan the QR code with your authenticator app
- manually enter the printed OTP secret into your authenticator app

You will need a fresh 6-digit code when logging in.

## 11. Log In

Log in as Alice:

```bash
python -m Client.main login --email alice@example.com --password Password123 --otp-code <current-otp-code>
```

Log in as Bob from Bob's profile terminal:

```bash
python -m Client.main login --email bob@example.com --password Password123 --otp-code <current-otp-code>
```

After login, the client stores:
- encrypted session state
- local device ID
- local encrypted identity private key

## 12. Add A Friend

From Alice's terminal:

```bash
python -m Client.main add-friend bob@example.com
```

From Bob's terminal, list incoming requests:

```bash
python -m Client.main pending --direction incoming
```

Copy the request ID, then accept it:

```bash
python -m Client.main accept <request-id>
```

You can also decline instead:

```bash
python -m Client.main decline <request-id>
```

## 13. Verify Fingerprints

Before relying on the conversation, compare fingerprints out of band.

Alice can view Bob's known device fingerprints:

```bash
python -m Client.main show-fingerprints <bob-user-uuid>
```

Bob can show his own current device fingerprint:

```bash
python -m Client.main my-fingerprint
```

After verifying the fingerprint through a trusted side channel, Alice can mark Bob's device as verified:

```bash
python -m Client.main verify-device <bob-user-uuid> <bob-device-id>
```

If a contact's identity key changes later, the client warns you and resets verification for that device.

## 14. Send Messages

The `chat` command opens an interactive chat session.

Open chat by username:

```bash
python -m Client.main chat bob
```

Inside chat:
- typing plain text sends a normal message
- `/ttl <seconds> <message>` sends a timed self-destruct message
- `/refresh` reloads recent local chat history
- `/back` exits the chat session

Example:

```text
/ttl 30 this message will expire in 30 seconds
```

## 15. Pull Offline Messages

If Bob was offline when Alice sent a message, Bob can pull queued ciphertext:

```bash
python -m Client.main pull --password Password123
```

This does the following:
- downloads queued ciphertext
- decrypts and validates the message locally
- rejects tampered or replayed messages
- stores valid plaintext in Bob's local history
- sends encrypted delivery receipts
- acknowledges server queue items after processing

## 16. Check Conversations And History

List conversations:

```bash
python -m Client.main conversations
```

Show paged message history for one contact:

```bash
python -m Client.main history <contact-uuid> --limit 20
```

Load older messages using pagination:

```bash
python -m Client.main history <contact-uuid> --limit 20 --before 2026-04-07T22:00:00Z
```

## 17. Useful Contact Management Commands

List friends:

```bash
python -m Client.main friends
```

List outgoing pending requests:

```bash
python -m Client.main pending --direction outgoing
```

Cancel an outgoing request:

```bash
python -m Client.main cancel-request <request-id>
```

Block a user:

```bash
python -m Client.main block-user <target-user-uuid>
```

Remove a friend:

```bash
python -m Client.main remove-friend <username>
```

## 18. Interactive Client Mode

You can start a REPL-like mode instead of typing `python -m Client.main` every time:

```bash
python -m Client.main interactive
```

Then run commands directly:

```text
friends
pending --direction incoming
chat bob
help history
```

Exit with:
- `exit`
- `quit`
- `Ctrl+D`

## 19. Running A Full Demo With Two Users

Minimal demo flow:

1. Start the server.
2. Open terminal A and configure Alice's client environment variables.
3. Open terminal B and configure Bob's client environment variables.
4. Register Alice.
5. Register Bob.
6. Log in as Alice.
7. Log in as Bob.
8. Alice sends a friend request to Bob.
9. Bob accepts the request.
10. Optionally compare fingerprints and mark the device as verified.
11. Alice sends a message to Bob.
12. Bob runs `pull --password Password123`.
13. Alice runs `pull --password Password123` to receive the delivery receipt.
14. Use `conversations` and `history` to inspect the local message view.

## 20. Teammate Setup Checklist

Each teammate should do this on their own machine:

1. Clone the repo.
2. Create a virtual environment.
3. Install dependencies.
4. Run `mkcert -install`.
5. Generate `certs/dev.crt` and `certs/dev.key`.
6. Copy `.env.example` to `.env`.
7. Set a local `JWT_SECRET_KEY`.
8. Start the server.
9. Create separate client state/db paths for each demo user profile.

Do not share:
- `.env`
- generated certs
- client state files
- local DB files

## 21. Troubleshooting

### TLS certificate file does not exist

Cause:
- you did not generate `certs/dev.crt` and `certs/dev.key`

Fix:

```bash
mkdir -p certs
mkcert -cert-file certs/dev.crt -key-file certs/dev.key 127.0.0.1 localhost
```

### Client rejects `http` or `ws`

Cause:
- the client requires `https://...` and `wss://...`

Fix:
- use `https://127.0.0.1:8000/api/v1`
- use `wss://127.0.0.1:8000/ws/chat`

### Login fails with OTP error

Cause:
- expired code or wrong authenticator secret

Fix:
- generate a fresh code
- verify you used the OTP secret printed at registration

### No messages appear

Check:
- both users are logged in
- the friend request was accepted
- the recipient ran `pull --password <login-password>`
- the client profiles are using different local DB and state file paths

## 22. Shutdown

To stop the server:
- press `Ctrl+C` in the server terminal

To clear demo client state, remove the local files you configured in:
- `CLIENT_DB_PATH`
- `CLIENT_STATE_PATH`
- `CLIENT_STATE_KEY_PATH`
