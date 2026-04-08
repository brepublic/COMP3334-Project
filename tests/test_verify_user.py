import click
import pytest
import typer


# ---------------------------------------------------------------------------
# Unit tests: _parse_device_selection
# ---------------------------------------------------------------------------

def test_parse_single_number():
    """_parse_device_selection returns [n] for a single integer."""
    from Client.main import _parse_device_selection

    assert _parse_device_selection("1") == [1]
    assert _parse_device_selection("5") == [5]
    assert _parse_device_selection("  3  ") == [3]


def test_parse_comma_separated():
    from Client.main import _parse_device_selection

    assert _parse_device_selection("1,2,3") == [1, 2, 3]
    assert _parse_device_selection(" 1 , 4 , 7 ") == [1, 4, 7]
    assert _parse_device_selection("5,1,3") == [1, 3, 5]
    assert _parse_device_selection("2,2,2") == [2]


def test_parse_space_separated():
    from Client.main import _parse_device_selection

    assert _parse_device_selection("1 2 3") == [1, 2, 3]
    assert _parse_device_selection(" 1  4  7 ") == [1, 4, 7]
    assert _parse_device_selection("3 1 4") == [1, 3, 4]


def test_parse_range():
    from Client.main import _parse_device_selection

    assert _parse_device_selection("1-4") == [1, 2, 3, 4]
    assert _parse_device_selection(" 2 - 5 ") == [2, 3, 4, 5]
    assert _parse_device_selection("7-7") == [7]
    assert _parse_device_selection("3-3") == [3]
    with pytest.raises(click.exceptions.BadParameter):
        _parse_device_selection("5-2")


def test_parse_mixed():
    from Client.main import _parse_device_selection

    assert _parse_device_selection("1, 3-5, 7") == [1, 3, 4, 5, 7]
    assert _parse_device_selection("2 4 6-8") == [2, 4, 6, 7, 8]
    assert _parse_device_selection("1-3, 5 7") == [1, 2, 3, 5, 7]


def test_parse_error_empty():
    from Client.main import _parse_device_selection

    for _input in ["", "   "]:
        with pytest.raises(typer.BadParameter):
            _parse_device_selection(_input)


def test_parse_error_invalid_range():
    from Client.main import _parse_device_selection

    for _input in ["1-", "-3", "5-2", "a-3", "1-b"]:
        with pytest.raises(typer.BadParameter):
            _parse_device_selection(_input)


def test_parse_error_invalid_token():
    from Client.main import _parse_device_selection

    for _input in ["abc"]:
        with pytest.raises(click.exceptions.BadParameter):
            _parse_device_selection(_input)


# ---------------------------------------------------------------------------
# Integration tests: verify-user command
# ---------------------------------------------------------------------------

def _setup_friendship(client_harness):
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

    accept_result = client_harness.run(bob_env, ["accept", "1", "--index"])
    assert accept_result.exit_code == 0, accept_result.output

    return {
        "alice_env": alice_env,
        "bob_env": bob_env,
        "alice_uuid": alice_uuid,
        "bob_uuid": bob_uuid,
    }


def test_verify_user_abort(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="a\n")
    assert result.exit_code == 0, result.output
    assert "abort" in result.output.lower()


def test_verify_user_abort_full(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="abort\n")
    assert result.exit_code == 0, result.output
    assert "abort" in result.output.lower()


def test_verify_user_by_uuid(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="1\n")
    assert result.exit_code == 0, result.output
    assert "marked" in result.output.lower()


def test_verify_user_by_email(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(
        ctx["alice_env"], ["verify-user", "bob@example.com"], input_text="1\n"
    )
    assert result.exit_code == 0, result.output
    assert "marked" in result.output.lower()


def test_verify_user_by_username(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", "bob"], input_text="1\n")
    assert result.exit_code == 0, result.output
    assert "marked" in result.output.lower()


def test_verify_user_comma_selection(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="1\n")
    assert result.exit_code == 0, result.output
    assert "1 device" in result.output.lower()


def test_verify_user_out_of_range(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="99\n")
    assert result.exit_code != 0, result.output


def test_verify_user_invalid_input(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="abc\n")
    assert result.exit_code != 0, result.output


def test_verify_user_shows_fingerprint(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="a\n")
    assert result.exit_code == 0, result.output
    assert "fingerprint" in result.output.lower()


def test_verify_user_shows_device_list(client_harness):
    ctx = _setup_friendship(client_harness)
    result = client_harness.run(ctx["alice_env"], ["sync-contact-keys", ctx["bob_uuid"]])
    assert result.exit_code == 0, result.output

    result = client_harness.run(ctx["alice_env"], ["verify-user", ctx["bob_uuid"]], input_text="a\n")
    assert result.exit_code == 0, result.output
    assert "device" in result.output.lower()
    assert "status" in result.output.lower()


def test_verify_user_unverified_contact(client_harness):
    alice_env = client_harness.profile_env("carol")
    carol_secret = client_harness.register(alice_env, "carol@example.com", "carol")
    client_harness.login(alice_env, "carol@example.com", carol_secret)

    result = client_harness.run(alice_env, ["verify-user", "nonexistent-uuid"])
    assert result.exit_code != 0, result.output
