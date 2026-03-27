import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from matterkeep.exceptions import ConfigError


@dataclass
class ServerConfig:
    url: str
    insecure: bool = False


@dataclass
class ExportConfig:
    output_dir: Path = field(default_factory=lambda: Path("./archive"))
    channels: list[str] = field(default_factory=list)
    exclude_channels: list[str] = field(default_factory=list)
    skip_files: bool = False
    skip_render: bool = False
    include_left: bool = False
    media_only: bool = False
    per_page: int = 200


@dataclass
class RenderConfig:
    theme: str = "dark"
    inline_images: bool = True


@dataclass
class Config:
    server: ServerConfig
    export: ExportConfig
    render: RenderConfig
    # Session token held here in memory only — never written to disk.
    token: str = field(default="", repr=False)


def load(config_path: Path | None = None) -> Config:
    load_dotenv()

    raw: dict[str, Any] = {}
    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        with config_path.open() as f:
            raw = yaml.safe_load(f) or {}

    server_raw = raw.get("server", {})
    export_raw = raw.get("export", {})
    render_raw = raw.get("render", {})

    url = os.environ.get("MM_URL") or server_raw.get("url") or ""
    if not url:
        raise ConfigError(
            "Server URL is required. Set MM_URL or server.url in config.yaml."
        )

    insecure_env = os.environ.get("MM_INSECURE", "").lower() in ("1", "true", "yes")
    server = ServerConfig(
        url=url.rstrip("/"),
        insecure=insecure_env or bool(server_raw.get("insecure", False)),
    )

    output_dir_raw = os.environ.get("MM_OUTPUT") or export_raw.get("output_dir", "./archive")
    export = ExportConfig(
        output_dir=Path(output_dir_raw),
        channels=export_raw.get("channels") or [],
        exclude_channels=export_raw.get("exclude_channels") or [],
        skip_files=bool(export_raw.get("skip_files", False)),
        skip_render=bool(export_raw.get("skip_render", False)),
        include_left=bool(export_raw.get("include_left", False)),
        media_only=bool(export_raw.get("media_only", False)),
        per_page=int(export_raw.get("per_page", 200)),
    )

    if export.per_page < 1 or export.per_page > 200:
        raise ConfigError("export.per_page must be between 1 and 200.")

    render = RenderConfig(
        theme=render_raw.get("theme", "dark"),
        inline_images=bool(render_raw.get("inline_images", True)),
    )

    return Config(server=server, export=export, render=render)
