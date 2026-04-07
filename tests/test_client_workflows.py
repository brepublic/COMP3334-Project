import re
import time


def _request_id_from_output(output: str) -> str:
    match = re.search(r"[0-9a-f]{8}-[0-9a-f-]{27}", output)
    assert match, output
    return match.group(0)


def setup_two_clients_and_friendship(client_harness):
    alice_env = client_harness.profile_env("alice")
    bob_env = client_harness.profile_env("bob")

    alice_secret = client_harness.register(alice_env, "alice@example.com", "alice")
    bob_secret = client_harness.register(bob_env, "bob@example.com", "bob")
    alice_uuid, _ = client_harness.login(alice_env, "alice@example.com", alice_secret)
    bob_uuid, _ = client_harness.login(bob_env, "bob@example.com", bob_secret)

    add_result = client_harness.run(alice_env, ["add-friend", "bob@example.com"])
    assert add_result.exit_code == 0, add_result.output

    pending_result = client_harness.run(bob_env, ["pending", "--direction", "incoming"])
    assert pending_result.exit_code == 0, pending_result.output
    request_id = _request_id_from_output(pending_result.output)

    accept_result = client_harness.run(bob_env, ["accept", request_id])
    assert accept_result.exit_code == 0, accept_result.output

    return {
        "alice_env": alice_env,
        "bob_env": bob_env,
        "alice_secret": alice_secret,
        "bob_secret": bob_secret,
        "alice_uuid": alice_uuid,
        "bob_uuid": bob_uuid,
    }


def test_client_login_encrypts_saved_state(client_harness):
    # Verifies local client session state is protected at rest after login.
    # Expected result: the saved state file contains encrypted token material, not a plaintext access token.
    alice_env = client_harness.profile_env("alice")
    otp_secret = client_harness.register(alice_env, "alice@example.com", "alice")
    _, login_output = client_harness.login(alice_env, "alice@example.com", otp_secret)

    state_payload = client_harness.read_state(alice_env)
    assert "Logged in as user UUID" in login_output
    assert "access_token" not in state_payload
    assert "access_token_encrypted" in state_payload
    assert "access_token_nonce" in state_payload


def test_client_pending_decline_cancel_and_block_commands(client_harness):
    # Verifies the CLI contact-management commands end to end.
    # Expected result: pending listings, decline, cancel-request, and block-user all behave correctly through the real client.
    alice_env = client_harness.profile_env("alice")
    bob_env = client_harness.profile_env("bob")

    alice_secret = client_harness.register(alice_env, "alice@example.com", "alice")
    bob_secret = client_harness.register(bob_env, "bob@example.com", "bob")
    alice_uuid, _ = client_harness.login(alice_env, "alice@example.com", alice_secret)
    _, _ = client_harness.login(bob_env, "bob@example.com", bob_secret)

    first_request = client_harness.run(alice_env, ["add-friend", "bob@example.com"])
    assert first_request.exit_code == 0, first_request.output

    alice_outgoing = client_harness.run(alice_env, ["pending", "--direction", "outgoing"])
    assert "outgoing" in alice_outgoing.output.lower()
    assert "bob" in alice_outgoing.output

    bob_incoming = client_harness.run(bob_env, ["pending", "--direction", "incoming"])
    request_id = _request_id_from_output(bob_incoming.output)
    decline_result = client_harness.run(bob_env, ["decline", request_id])
    assert "Rejected" in decline_result.output

    second_request = client_harness.run(alice_env, ["add-friend", "bob@example.com"])
    assert second_request.exit_code == 0, second_request.output
    outgoing_again = client_harness.run(alice_env, ["pending", "--direction", "outgoing"])
    cancel_id = _request_id_from_output(outgoing_again.output)
    cancel_result = client_harness.run(alice_env, ["cancel-request", cancel_id])
    assert "revoked" in cancel_result.output.lower()

    block_result = client_harness.run(bob_env, ["block-user", alice_uuid])
    assert "Blocked User" in block_result.output

    ignored_request = client_harness.run(alice_env, ["add-friend", "bob@example.com"])
    assert "ignored" in ignored_request.output.lower()


def test_client_non_message_command_works_without_in_memory_session_password(client_harness):
    # Verifies non-message commands still work in a fresh CLI process where no session password is cached in memory.
    # Expected result: add-friend succeeds using saved auth state only and does not crash with NameError.
    alice_env = client_harness.profile_env("alice")
    bob_env = client_harness.profile_env("bob")

    alice_secret = client_harness.register(alice_env, "alice@example.com", "alice")
    bob_secret = client_harness.register(bob_env, "bob@example.com", "bob")
    _, _ = client_harness.login(alice_env, "alice@example.com", alice_secret)
    _, _ = client_harness.login(bob_env, "bob@example.com", bob_secret)

    client_harness.client_main._SESSION_PASSWORD = None

    add_result = client_harness.run(alice_env, ["add-friend", "bob@example.com"])
    assert add_result.exit_code == 0, add_result.output
    assert "Successfully" in add_result.output


def test_client_send_pull_receipt_and_history(client_harness):
    # Verifies the core encrypted messaging flow including receipt-based delivery status.
    # Expected result: Bob decrypts the message, Alice later receives a delivered receipt, and history reflects DELIVERED.
    setup = setup_two_clients_and_friendship(client_harness)

    client_harness.send_message(
        setup["alice_env"],
        setup["bob_uuid"],
        "hello from alice",
        ttl=300,
    )

    bob_pull = client_harness.run(
        setup["bob_env"],
        ["pull", "--password", "Password123"],
    )
    assert bob_pull.exit_code == 0, bob_pull.output
    assert "hello from alice" in bob_pull.output

    bob_conversations = client_harness.run(setup["bob_env"], ["conversations"])
    assert bob_conversations.exit_code == 0, bob_conversations.output
    assert "\t1" in bob_conversations.output

    alice_pull = client_harness.run(
        setup["alice_env"],
        ["pull", "--password", "Password123"],
    )
    assert alice_pull.exit_code == 0, alice_pull.output
    assert "status=DELIVERED" in alice_pull.output

    alice_history = client_harness.run(
        setup["alice_env"],
        ["history", setup["bob_uuid"], "--limit", "20"],
    )
    assert alice_history.exit_code == 0, alice_history.output
    assert "hello from alice" in alice_history.output
    assert "DELIVERED" in alice_history.output


def test_client_key_change_warning_on_send(client_harness, capsys):
    # Verifies key-change visibility during a normal send path after the contact's identity key changes.
    # Expected result: the sender sees a warning instead of silently trusting the replacement key.
    setup = setup_two_clients_and_friendship(client_harness)

    sync_result = client_harness.run(setup["alice_env"], ["sync-contact-keys", setup["bob_uuid"]])
    assert sync_result.exit_code == 0, sync_result.output

    bob_rekey_env = client_harness.profile_env("bob-rekey")
    _, _ = client_harness.login(bob_rekey_env, "bob@example.com", setup["bob_secret"])

    client_harness.send_message(
        setup["alice_env"],
        setup["bob_uuid"],
        "warning check",
        ttl=300,
    )
    output = capsys.readouterr().out
    assert "Warning: key changed" in output


def test_client_expired_messages_are_cleaned_from_history(client_harness):
    # Verifies timed self-destruct cleanup on the client side.
    # Expected result: a short-lived message is visible before expiry and absent from history after cleanup runs.
    setup = setup_two_clients_and_friendship(client_harness)

    client_harness.send_message(
        setup["alice_env"],
        setup["bob_uuid"],
        "short ttl",
        ttl=1,
    )

    bob_pull = client_harness.run(
        setup["bob_env"],
        ["pull", "--password", "Password123"],
    )
    assert bob_pull.exit_code == 0, bob_pull.output
    assert "short ttl" in bob_pull.output

    time.sleep(2)

    history = client_harness.run(
        setup["bob_env"],
        ["history", setup["alice_uuid"], "--limit", "10"],
    )
    assert history.exit_code == 0, history.output
    assert "short ttl" not in history.output
