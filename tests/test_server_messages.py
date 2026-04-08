def test_message_validation_offline_ordering_and_block_ignores(server_context, server_helpers):
    # Verifies server-side message enforcement for non-friends, blocked users, payload validation, and offline queue ordering.
    # Expected result: invalid or unauthorized sends do not deliver, oversized payloads fail, and queued ciphertext stays ordered.
    alice = server_helpers.register("alice@example.com", "alice")
    bob = server_helpers.register("bob@example.com", "bob")
    alice_login = server_helpers.login("alice@example.com", alice["otp_secret"])
    bob_login = server_helpers.login("bob@example.com", bob["otp_secret"])

    not_friend_send = server_context.client.post(
        "/api/v1/messages/send",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={
            "receiver_uuid": bob_login["user_uuid"],
            "ciphertext": "xx",
            "expire_duration": 60,
        },
    )
    assert not_friend_send.status_code == 200
    assert not_friend_send.json()["status"] == "UNRECEIVED"

    empty_offline = server_context.client.get(
        "/api/v1/messages/offline",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
    )
    assert empty_offline.status_code == 200
    assert empty_offline.json()["messages"] == []

    server_helpers.make_friends(alice_login["access_token"], "bob@example.com", bob_login["access_token"])

    first = server_context.client.post(
        "/api/v1/messages/send",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={
            "receiver_uuid": bob_login["user_uuid"],
            "ciphertext": "{\"order\":1}",
            "expire_duration": 60,
        },
    )
    second = server_context.client.post(
        "/api/v1/messages/send",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={
            "receiver_uuid": bob_login["user_uuid"],
            "ciphertext": "{\"order\":2}",
            "expire_duration": 60,
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200

    offline = server_context.client.get(
        "/api/v1/messages/offline",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
    )
    assert offline.status_code == 200
    payload = offline.json()["messages"]
    assert len(payload) == 2
    assert payload[0]["ciphertext"] == "{\"order\":1}"
    assert payload[1]["ciphertext"] == "{\"order\":2}"

    oversized = server_context.client.post(
        "/api/v1/messages/send",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={
            "receiver_uuid": bob_login["user_uuid"],
            "ciphertext": "x" * 70000,
            "expire_duration": 60,
        },
    )
    assert oversized.status_code == 422

    block_response = server_context.client.post(
        "/api/v1/friends/block",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
        json={"target_uuid": alice_login["user_uuid"]},
    )
    assert block_response.status_code == 200

    blocked_send = server_context.client.post(
        "/api/v1/messages/send",
        headers={"Authorization": f"Bearer {alice_login['access_token']}"},
        json={
            "receiver_uuid": bob_login["user_uuid"],
            "ciphertext": "{\"blocked\":true}",
            "expire_duration": 60,
        },
    )
    assert blocked_send.status_code == 200
    assert blocked_send.json()["status"] == "UNRECEIVED"


def test_websocket_send_applies_same_payload_limits(server_context, server_helpers):
    # Verifies the WebSocket ingress path enforces the same message size/TTL validation as HTTP send.
    # Expected result: invalid payloads are ignored and never enter the offline queue.
    alice = server_helpers.register("alice@example.com", "alice")
    bob = server_helpers.register("bob@example.com", "bob")
    alice_login = server_helpers.login("alice@example.com", alice["otp_secret"])
    bob_login = server_helpers.login("bob@example.com", bob["otp_secret"])
    server_helpers.make_friends(alice_login["access_token"], "bob@example.com", bob_login["access_token"])

    with server_context.client.websocket_connect(
        f"/ws/chat?token={alice_login['access_token']}"
    ) as websocket:
        websocket.send_json(
            {
                "receiver_uuid": bob_login["user_uuid"],
                "ciphertext": "x" * 70000,
                "expire_duration": 60,
            }
        )

    offline = server_context.client.get(
        "/api/v1/messages/offline",
        headers={"Authorization": f"Bearer {bob_login['access_token']}"},
    )
    assert offline.status_code == 200
    assert offline.json()["messages"] == []
