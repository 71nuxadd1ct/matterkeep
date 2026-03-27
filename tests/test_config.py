import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from matterkeep.config import load
from matterkeep.exceptions import ConfigError


@pytest.fixture(autouse=True)
def no_dotenv():
    with patch("matterkeep.config.load_dotenv"):
        yield


def test_load_minimal_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_URL", "https://mm.example.com")
    cfg = load()
    assert cfg.server.url == "https://mm.example.com"
    assert cfg.export.per_page == 200
    assert cfg.render.theme == "dark"


def test_load_from_yaml(tmp_path, monkeypatch):
    monkeypatch.delenv("MM_URL", raising=False)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "server": {"url": "https://mm.example.com", "insecure": True},
        "export": {"output_dir": str(tmp_path / "archive"), "per_page": 50},
        "render": {"theme": "light"},
    }))
    cfg = load(config_file)
    assert cfg.server.url == "https://mm.example.com"
    assert cfg.server.insecure is True
    assert cfg.export.per_page == 50
    assert cfg.render.theme == "light"


def test_env_overrides_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_URL", "https://override.example.com")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"server": {"url": "https://original.example.com"}}))
    cfg = load(config_file)
    assert cfg.server.url == "https://override.example.com"


def test_missing_url_raises(monkeypatch):
    monkeypatch.delenv("MM_URL", raising=False)
    with pytest.raises(ConfigError, match="Server URL"):
        load()


def test_invalid_per_page(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_URL", "https://mm.example.com")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "server": {"url": "https://mm.example.com"},
        "export": {"per_page": 999},
    }))
    with pytest.raises(ConfigError, match="per_page"):
        load(config_file)


def test_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("MM_URL", "https://mm.example.com/")
    cfg = load()
    assert not cfg.server.url.endswith("/")


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load(tmp_path / "nonexistent.yaml")
