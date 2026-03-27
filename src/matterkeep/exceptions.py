class MatterkeeperError(Exception):
    """Base exception for all matterkeep errors."""


class AuthError(MatterkeeperError):
    """Authentication or authorisation failure."""


class APIError(MatterkeeperError):
    """Unexpected response from the Mattermost API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfigError(MatterkeeperError):
    """Invalid or missing configuration."""
