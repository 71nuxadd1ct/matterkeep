import pytest


@pytest.fixture
def server_url() -> str:
    return "https://mattermost.example.com"


@pytest.fixture
def token() -> str:
    return "test-session-token-abc123"
