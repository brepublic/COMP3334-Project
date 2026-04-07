import json

from Client.CdbManager import ClientDBManager
from Client.CLient_db import Message
from test_client_workflows import setup_two_clients_and_friendship


def test_attack_replay_ciphertext_is_rejected(client_harness, server_context):
    # Simulates a replay attack by pulling the same ciphertext twice before it is acknowledged.
    # Expected result: the second copy is flagged as replayed and is not stored as a second plaintext message.
    setup = setup_two_clients_and_friendship(client_harness)

    client_harness.send_message(
        setup["alice_env"],
        setup["bob_uuid"],
        "replay attack sample",
        ttl=300,
    )

    first_pull = client_harness.run(
        setup["bob_env"],
        ["pull", "--no-ack", "--password", "Password123"],
    )
    assert first_pull.exit_code == 0, first_pull.output
    assert "replay attack sample" in first_pull.output

    second_pull = client_harness.run(
        setup["bob_env"],
        ["pull", "--password", "Password123"],
    )
    assert second_pull.exit_code == 0, second_pull.output
    assert "replayed-client-msg-id=" in second_pull.output
    assert "replay attack sample" not in second_pull.output

    bob_db = ClientDBManager(client_harness.profile_env("bob")["CLIENT_DB_PATH"])
    with bob_db.get_session() as db:
        stored_messages = db.query(Message).filter(Message.content_plaintext == "replay attack sample").all()
    assert len(stored_messages) == 1


def test_attack_tampered_envelope_is_not_accepted(client_harness, server_context, server_helpers):
    # Simulates ciphertext/AAD tampering by editing the stored offline envelope before delivery.
    # Expected result: decryption fails and the tampered plaintext is never accepted into local history.
    setup = setup_two_clients_and_friendship(client_harness)

    client_harness.send_message(
        setup["alice_env"],
        setup["bob_uuid"],
        "tamper attack sample",
        ttl=300,
    )

    with server_helpers.db_session() as db:
        offline = (
            db.query(server_context.models.OfflineMessage)
            .filter(server_context.models.OfflineMessage.receiver_uuid == setup["bob_uuid"])
            .one()
        )
        envelope = json.loads(offline.ciphertext)
        envelope["ttl"] = 999
        offline.ciphertext = json.dumps(envelope, separators=(",", ":"))

    pull_result = client_harness.run(
        setup["bob_env"],
        ["pull", "--password", "Password123"],
    )
    assert pull_result.exit_code == 0, pull_result.output
    assert "decrypt-failed" in pull_result.output
    assert "tamper attack sample" not in pull_result.output

    with server_helpers.db_session() as db:
        remaining = (
            db.query(server_context.models.OfflineMessage)
            .filter(server_context.models.OfflineMessage.receiver_uuid == setup["bob_uuid"])
            .count()
        )
    assert remaining == 0

    bob_db = ClientDBManager(client_harness.profile_env("bob")["CLIENT_DB_PATH"])
    with bob_db.get_session() as db:
        stored_messages = db.query(Message).filter(Message.content_plaintext == "tamper attack sample").all()
    assert stored_messages == []


def test_attack_malformed_offline_envelope_is_dropped_after_rejection(client_harness, server_context, server_helpers):
    # Simulates a malicious ciphertext blob that is not even valid JSON.
    # Expected result: the client rejects it and acknowledges it so it does not poison every future pull.
    setup = setup_two_clients_and_friendship(client_harness)

    with server_helpers.db_session() as db:
        db.add(
            server_context.models.OfflineMessage(
                sender_uuid=setup["alice_uuid"],
                receiver_uuid=setup["bob_uuid"],
                ciphertext="not-json",
                expire_duration=300,
            )
        )

    first_pull = client_harness.run(
        setup["bob_env"],
        ["pull", "--password", "Password123"],
    )
    assert first_pull.exit_code == 0, first_pull.output
    assert "invalid-envelope-json" in first_pull.output

    second_pull = client_harness.run(
        setup["bob_env"],
        ["pull", "--password", "Password123"],
    )
    assert second_pull.exit_code == 0, second_pull.output
    assert "No offline messages." in second_pull.output


def test_attack_identity_key_substitution_triggers_warning(client_harness, capsys):
    # Simulates identity-key substitution by forcing the contact to upload a fresh key from a new profile.
    # Expected result: the next send path warns about the key change instead of silently trusting it.
    setup = setup_two_clients_and_friendship(client_harness)

    initial_sync = client_harness.run(
        setup["alice_env"],
        ["sync-contact-keys", setup["bob_uuid"]],
    )
    assert initial_sync.exit_code == 0, initial_sync.output

    bob_rekey_env = client_harness.profile_env("bob-security-rekey")
    _, _ = client_harness.login(bob_rekey_env, "bob@example.com", setup["bob_secret"])

    client_harness.send_message(
        setup["alice_env"],
        setup["bob_uuid"],
        "key substitution probe",
        ttl=300,
    )

    output = capsys.readouterr().out
    assert "Warning: key changed" in output
