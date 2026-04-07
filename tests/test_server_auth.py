import pyotp

from conftest import new_device_material


def test_register_login_logout_and_single_device_invalidation(server_context, server_helpers):
    # Verifies token lifecycle security: current logout revokes access and a newer login invalidates older sessions.
    # Expected result: logged-out and superseded tokens return 401, while the newest token remains valid.
    registration = server_helpers.register("alice@example.com", "alice")

    first_login = server_helpers.login("alice@example.com", registration["otp_secret"])
    protected_response = server_context.client.get(
        "/api/v1/friends",
        headers={"Authorization": f"Bearer {first_login['access_token']}"},
    )
    assert protected_response.status_code == 200

    logout_response = server_context.client.post(
        "/api/v1/logout",
        headers={"Authorization": f"Bearer {first_login['access_token']}"},
    )
    assert logout_response.status_code == 200

    after_logout = server_context.client.get(
        "/api/v1/friends",
        headers={"Authorization": f"Bearer {first_login['access_token']}"},
    )
    assert after_logout.status_code == 401

    second_login = server_helpers.login("alice@example.com", registration["otp_secret"])
    third_login = server_helpers.login("alice@example.com", registration["otp_secret"])

    old_session = server_context.client.get(
        "/api/v1/friends",
        headers={"Authorization": f"Bearer {second_login['access_token']}"},
    )
    current_session = server_context.client.get(
        "/api/v1/friends",
        headers={"Authorization": f"Bearer {third_login['access_token']}"},
    )

    assert old_session.status_code == 401
    assert current_session.status_code == 200


def test_registration_rate_limit(server_context):
    # Verifies abuse protection on registration.
    # Expected result: the fourth registration attempt from the same client is blocked with 429.
    for idx in range(3):
        response = server_context.client.post(
            "/api/v1/register",
            json={
                "email": f"user{idx}@example.com",
                "user_name": f"user{idx}",
                "password": "Password123",
            },
        )
        assert response.status_code == 200, response.text

    limited_register = server_context.client.post(
        "/api/v1/register",
        json={
            "email": "user4@example.com",
            "user_name": "user4",
            "password": "Password123",
        },
    )
    assert limited_register.status_code == 429


def test_login_rate_limit(server_context, server_helpers):
    # Verifies brute-force resistance on login attempts.
    # Expected result: repeated failed logins are allowed only up to the configured threshold, then return 429.
    registration = server_helpers.register("login-target@example.com", "target")
    _, device_public_key = new_device_material()
    for _ in range(5):
        response = server_context.client.post(
            "/api/v1/login",
            json={
                "email": "login-target@example.com",
                "password": "WrongPassword123",
                "otp_code": pyotp.TOTP(registration["otp_secret"]).now(),
                "device_hash": "12345678-device",
                "device_public_key": device_public_key,
            },
        )
        assert response.status_code == 401, response.text

    rate_limited_login = server_context.client.post(
        "/api/v1/login",
        json={
            "email": "login-target@example.com",
            "password": "WrongPassword123",
            "otp_code": pyotp.TOTP(registration["otp_secret"]).now(),
            "device_hash": "12345678-device2",
            "device_public_key": device_public_key,
        },
    )
    assert rate_limited_login.status_code == 429
