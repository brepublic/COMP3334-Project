import pyotp
from argon2 import PasswordHasher


def _request_id_from_pending(payload: list[dict]) -> str:
    assert payload
    return payload[0]["request_id"]


def test_pending_directions_decline_cancel_and_block_non_friend(server_context, server_helpers):
    # Verifies the full friend-request lifecycle plus blocking behavior, including blocking a non-friend.
    # Expected result: incoming/outgoing pending views work, decline/cancel succeed, and blocked requests are ignored.
    alice = server_helpers.register("alice@example.com", "alice")
    bob = server_helpers.register("bob@example.com", "bob")
    alice_login = server_helpers.login("alice@example.com", alice["otp_secret"])
    bob_login = server_helpers.login("bob@example.com", bob["otp_secret"])

    request_response = server_context.client.post(
        "/api/v1/friends/request",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={"target_email": "bob@example.com"},
    )
    assert request_response.status_code == 200

    alice_outgoing = server_context.client.get(
        "/api/v1/friends/pending?direction=outgoing",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
    )
    bob_incoming = server_context.client.get(
        "/api/v1/friends/pending?direction=incoming",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
    )
    assert alice_outgoing.status_code == 200
    assert bob_incoming.status_code == 200
    assert alice_outgoing.json()[0]["direction"] == "outgoing"
    assert alice_outgoing.json()[0]["counterparty_name"] == "bob"
    assert bob_incoming.json()[0]["direction"] == "incoming"
    assert bob_incoming.json()[0]["counterparty_name"] == "alice"

    request_id = _request_id_from_pending(bob_incoming.json())
    decline_response = server_context.client.post(
        "/api/v1/friends/action",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
        json={"request_id": request_id, "action": "REJECT"},
    )
    assert decline_response.status_code == 200

    second_request = server_context.client.post(
        "/api/v1/friends/request",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={"target_email": "bob@example.com"},
    )
    assert second_request.status_code == 200

    alice_outgoing_again = server_context.client.get(
        "/api/v1/friends/pending?direction=outgoing",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
    )
    cancel_id = _request_id_from_pending(alice_outgoing_again.json())
    cancel_response = server_context.client.delete(
        f"/api/v1/friends/request/{cancel_id}",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
    )
    assert cancel_response.status_code == 200

    block_response = server_context.client.post(
        "/api/v1/friends/block",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
        json={"target_uuid": alice_login["user_uuid"]},
    )
    assert block_response.status_code == 200

    ignored_request = server_context.client.post(
        "/api/v1/friends/request",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={"target_email": "bob@example.com"},
    )
    assert ignored_request.status_code == 200
    assert "ignored" in ignored_request.json()["message"].lower()

    bob_pending_after_block = server_context.client.get(
        "/api/v1/friends/pending?direction=incoming",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
    )
    assert bob_pending_after_block.status_code == 200
    assert bob_pending_after_block.json() == []


def test_friend_request_rate_limit_enforced(server_context, server_helpers):
    # Verifies anti-spam controls for friend requests.
    # Expected result: after enough rapid requests, the sender is rate-limited and receives 429.
    sender = server_helpers.register("sender@example.com", "sender")
    sender_login = server_helpers.login("sender@example.com", sender["otp_secret"])
    password_hasher = PasswordHasher()

    for idx in range(11):
        target_email = f"target{idx}@example.com"
        with server_helpers.db_session() as db:
            db.add(
                server_context.models.User(
                    email=target_email,
                    user_name=f"target{idx}",
                    password_hash=password_hasher.hash("Password123"),
                    otp_secret=pyotp.random_base32(),
                )
            )
        response = server_context.client.post(
            "/api/v1/friends/request",
            headers={"Authorization": f"Bearer {sender_login['access_token']}"},
            json={"target_email": target_email},
        )
        if idx < 10:
            assert response.status_code == 200, response.text
        else:
            assert response.status_code == 429
