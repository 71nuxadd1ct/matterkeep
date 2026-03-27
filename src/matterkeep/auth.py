import logging
import os

import click
import requests

from matterkeep.exceptions import AuthError

logger = logging.getLogger(__name__)

_MFA_ERROR_ID = "mfa.validate_token.authenticate.app_error"


def get_token(server_url: str, username: str, password: str, verify_ssl: bool = True) -> str:
    """Authenticate with username + password (+ TOTP if MFA is required)."""
    resp = _login(server_url, username, password, totp=None, verify_ssl=verify_ssl)

    if resp.status_code == 401:
        body = _safe_json(resp)
        logger.debug("Login 401 response body: %s", body)
        if body.get("id") == _MFA_ERROR_ID:
            totp = click.prompt("MFA code (Google Authenticator)", hide_input=False)
            resp = _login(server_url, username, password, totp=totp.strip(), verify_ssl=verify_ssl)
            if resp.status_code == 401:
                raise AuthError("Invalid username or password.")
        else:
            raise AuthError("Invalid username or password.")

    if resp.status_code == 403:
        raise AuthError("Account is disabled or access denied.")
    if not resp.ok:
        raise AuthError(f"Login failed with status {resp.status_code}: {resp.text[:200]}")

    token = resp.headers.get("Token")
    if not token:
        raise AuthError("Login succeeded but no session token was returned.")
    return token


def _login(
    server_url: str,
    username: str,
    password: str,
    totp: str | None,
    verify_ssl: bool,
) -> requests.Response:
    payload: dict[str, str] = {"login_id": username, "password": password}
    if totp:
        payload["token"] = totp
    try:
        return requests.post(
            f"{server_url}/api/v4/users/login",
            json=payload,
            verify=verify_ssl,
            timeout=30,
        )
    except requests.exceptions.SSLError as e:
        raise AuthError(
            f"TLS certificate verification failed: {e}\n"
            "Use --insecure to skip verification, or set REQUESTS_CA_BUNDLE "
            "to your CA certificate path."
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise AuthError(f"Could not connect to {server_url}: {e}") from e
    except requests.exceptions.Timeout:
        raise AuthError(f"Connection to {server_url} timed out.")


def _safe_json(resp: requests.Response) -> dict:  # type: ignore[type-arg]
    try:
        return resp.json()  # type: ignore[no-any-return]
    except Exception:
        return {}


def get_token_from_env() -> str | None:
    """Return PAT from MM_TOKEN env var, or None if not set."""
    return os.environ.get("MM_TOKEN") or None
