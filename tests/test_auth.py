import pytest
import responses as rsps_lib

from matterkeep.auth import get_token, get_token_from_env
from matterkeep.exceptions import AuthError


@rsps_lib.activate
def test_successful_login():
    rsps_lib.add(
        rsps_lib.POST,
        "https://mm.example.com/api/v4/users/login",
        json={"id": "user1", "username": "alice"},
        headers={"Token": "session-xyz"},
        status=200,
    )
    token = get_token("https://mm.example.com", "alice", "password")
    assert token == "session-xyz"


@rsps_lib.activate
def test_invalid_credentials_raises():
    rsps_lib.add(
        rsps_lib.POST,
        "https://mm.example.com/api/v4/users/login",
        json={"id": "api.user.login.invalid_credentials_email.app_error"},
        status=401,
    )
    with pytest.raises(AuthError, match="Invalid username or password"):
        get_token("https://mm.example.com", "alice", "wrong")


@rsps_lib.activate
def test_mfa_required_then_success(monkeypatch):
    # First call: MFA required
    rsps_lib.add(
        rsps_lib.POST,
        "https://mm.example.com/api/v4/users/login",
        json={"id": "mfa.validate_token.authenticate.app_error"},
        status=401,
    )
    # Second call: with TOTP succeeds
    rsps_lib.add(
        rsps_lib.POST,
        "https://mm.example.com/api/v4/users/login",
        json={"id": "user1"},
        headers={"Token": "mfa-session-token"},
        status=200,
    )
    monkeypatch.setattr("click.prompt", lambda *a, **kw: "123456")
    token = get_token("https://mm.example.com", "alice", "password")
    assert token == "mfa-session-token"
    # Verify the second request included the token field
    assert rsps_lib.calls[1].request.body is not None
    import json
    body = json.loads(rsps_lib.calls[1].request.body)
    assert body["token"] == "123456"


@rsps_lib.activate
def test_mfa_wrong_code_raises(monkeypatch):
    rsps_lib.add(
        rsps_lib.POST,
        "https://mm.example.com/api/v4/users/login",
        json={"id": "mfa.validate_token.authenticate.app_error"},
        status=401,
    )
    rsps_lib.add(
        rsps_lib.POST,
        "https://mm.example.com/api/v4/users/login",
        json={"id": "api.user.login.invalid_credentials_email.app_error"},
        status=401,
    )
    monkeypatch.setattr("click.prompt", lambda *a, **kw: "000000")
    with pytest.raises(AuthError, match="Invalid username or password"):
        get_token("https://mm.example.com", "alice", "password")


@rsps_lib.activate
def test_missing_token_in_response_raises():
    rsps_lib.add(
        rsps_lib.POST,
        "https://mm.example.com/api/v4/users/login",
        json={"id": "user1"},
        status=200,
        # No Token header
    )
    with pytest.raises(AuthError, match="no session token"):
        get_token("https://mm.example.com", "alice", "password")


def test_get_token_from_env_present(monkeypatch):
    monkeypatch.setenv("MM_TOKEN", "my-pat")
    assert get_token_from_env() == "my-pat"


def test_get_token_from_env_absent(monkeypatch):
    monkeypatch.delenv("MM_TOKEN", raising=False)
    assert get_token_from_env() is None
