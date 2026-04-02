import json
import logging
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from matterkeep import __version__
from matterkeep.auth import get_token, get_token_from_env
from matterkeep.client import MMClient
from matterkeep.config import load as load_config
from matterkeep.exceptions import AuthError, ConfigError, MatterkeeperError
from matterkeep.exporter import Exporter

console = Console(stderr=True)


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


@click.group()
@click.version_option(__version__, prog_name="matterkeep")
def main() -> None:
    """Archive your Mattermost history to a searchable offline HTML archive."""


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None,
              help="Config YAML path (default: ./config.yaml if it exists).")
@click.option("--output-dir", type=click.Path(path_type=Path), default=None,
              help="Archive output directory.")
@click.option("--full", is_flag=True, default=False,
              help="Force full re-export, ignoring sync state.")
@click.option("--teams", default=None,
              help="Comma-separated team names to include.")
@click.option("--exclude-teams", default=None,
              help="Comma-separated team names to exclude.")
@click.option("--channels", default=None,
              help="Comma-separated channel names to include.")
@click.option("--exclude-channels", default=None,
              help="Comma-separated channel names to exclude.")
@click.option("--include-left", is_flag=True, default=False,
              help="Also archive public channels the user has left.")
@click.option("--skip-files", is_flag=True, default=False,
              help="Skip file and image downloads.")
@click.option("--media-only", is_flag=True, default=False,
              help="Download media only; skip writing message history.")
@click.option("--media-manifest", is_flag=True, default=False,
              help="Write media/manifest.csv listing every downloaded file with sender and timestamp.")
@click.option("--skip-render", is_flag=True, default=False,
              help="Skip HTML rendering (JSON export only).")
@click.option("-v", "--verbose", count=True,
              help="Increase verbosity (-v INFO, -vv DEBUG).")
@click.option("--server", default=None,
              help="Mattermost server URL (overrides MM_URL / config).")
@click.option("--insecure", is_flag=True, default=False,
              help="Disable TLS certificate verification (NOT recommended).")
def export(
    config_path: Path | None,
    output_dir: Path | None,
    full: bool,
    teams: str | None,
    exclude_teams: str | None,
    channels: str | None,
    exclude_channels: str | None,
    include_left: bool,
    skip_files: bool,
    media_only: bool,
    media_manifest: bool,
    skip_render: bool,
    verbose: int,
    server: str | None,
    insecure: bool,
) -> None:
    """Run a full or incremental export."""
    _setup_logging(verbose)

    if insecure:
        console.print("[yellow]WARNING: TLS verification is disabled.[/yellow]")

    try:
        cfg_path = config_path or (Path("config.yaml") if Path("config.yaml").exists() else None)
        cfg = load_config(cfg_path)
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        sys.exit(1)

    # CLI flags override config
    if output_dir:
        cfg.export.output_dir = output_dir
    if teams:
        cfg.export.teams = [t.strip() for t in teams.split(",")]
    if exclude_teams:
        cfg.export.exclude_teams = [t.strip() for t in exclude_teams.split(",")]
    if channels:
        cfg.export.channels = [c.strip() for c in channels.split(",")]
    if exclude_channels:
        cfg.export.exclude_channels = [c.strip() for c in exclude_channels.split(",")]
    if include_left:
        cfg.export.include_left = True
    if skip_files:
        cfg.export.skip_files = True
    if media_only:
        cfg.export.media_only = True
    if media_manifest:
        cfg.export.media_manifest = True
    if skip_render:
        cfg.export.skip_render = True
    if server:
        cfg.server.url = server.rstrip("/")
    if not cfg.server.url:
        cfg.server.url = click.prompt("Mattermost server URL").rstrip("/")
    if insecure:
        cfg.server.insecure = True

    # Auth: PAT first, then interactive
    try:
        token = get_token_from_env()
        if token:
            console.print("[dim]Using PAT from MM_TOKEN.[/dim]")
        else:
            username = os.environ.get("MM_USERNAME") or click.prompt("Username")
            password = click.prompt("Password", hide_input=True)
            console.print("[dim]Authenticating…[/dim]")
            token = get_token(cfg.server.url, username, password, verify_ssl=not cfg.server.insecure)
    except AuthError as e:
        console.print(f"[red]Authentication failed:[/red] {e}")
        sys.exit(1)

    cfg.token = token

    # Clear sync state if --full
    if full:
        state_file = cfg.export.output_dir / "sync_state.json"
        if state_file.exists():
            state_file.unlink()
            console.print("[dim]Sync state cleared (--full).[/dim]")

    try:
        client = MMClient(cfg.server.url, token, verify_ssl=not cfg.server.insecure)
        exporter = Exporter(client, cfg)
        exporter.run()
    except MatterkeeperError as e:
        console.print(f"[red]Export failed:[/red] {e}")
        sys.exit(1)

    if not cfg.export.skip_render and not cfg.export.media_only:
        try:
            from matterkeep.renderer import Renderer
            renderer = Renderer(cfg)
            renderer.run()
        except MatterkeeperError as e:
            console.print(f"[red]Render failed:[/red] {e}")
            sys.exit(1)

    console.print("[green]Done.[/green]")


@main.command()
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("./archive"),
              show_default=True, help="Archive directory to inspect.")
def status(output_dir: Path) -> None:
    """Show sync state for an archive."""
    state_file = output_dir / "sync_state.json"
    if not state_file.exists():
        console.print("[yellow]No sync state found.[/yellow] Have you run an export yet?")
        sys.exit(1)

    with state_file.open() as f:
        raw = json.load(f)

    table = Table(title=f"Archive: {output_dir}", show_lines=True)
    table.add_column("Channel ID")
    table.add_column("Last post (unix ms)")

    for channel_id, ts in raw.get("channels", {}).items():
        table.add_row(channel_id, str(ts))

    console = Console()
    console.print(table)
    console.print(f"Last run: {raw.get('last_run', 'unknown')}")


@main.command()
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("./archive"),
              show_default=True)
@click.option("--recipient", default=None, help="age public key (omit for passphrase mode).")
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None,
              help="Output .tar.age path.")
@click.option("--shred", is_flag=True, default=False,
              help="Overwrite and delete unencrypted archive after encryption.")
def encrypt(output_dir: Path, recipient: str | None, output_path: Path | None, shred: bool) -> None:
    """Encrypt the archive with age."""
    try:
        from matterkeep.encrypt import encrypt_archive
        encrypt_archive(output_dir, recipient=recipient, output_path=output_path, shred=shred)
        console.print("[green]Archive encrypted.[/green]")
    except MatterkeeperError as e:
        console.print(f"[red]Encryption failed:[/red] {e}")
        sys.exit(1)


@main.command("render")
@click.option("--output-dir", type=click.Path(path_type=Path), default=None,
              help="Archive directory to render (default: from config).")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def render_cmd(output_dir: Path | None, config_path: Path | None) -> None:
    """Re-render the HTML archive from existing exported data. No server connection needed."""
    try:
        cfg_path = config_path or (Path("config.yaml") if Path("config.yaml").exists() else None)
        cfg = load_config(cfg_path)
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        sys.exit(1)

    if output_dir:
        cfg.export.output_dir = output_dir

    if not (cfg.export.output_dir / "data").exists():
        console.print(f"[red]No exported data found at {cfg.export.output_dir / 'data'}[/red]")
        sys.exit(1)

    try:
        from matterkeep.renderer import Renderer
        Renderer(cfg).run()
        console.print(f"[green]Rendered:[/green] {cfg.export.output_dir / 'html' / 'index.html'}")
    except MatterkeeperError as e:
        console.print(f"[red]Render failed:[/red] {e}")
        sys.exit(1)


@main.command()
@click.argument("query")
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("./archive"),
              show_default=True)
@click.option("--channel", default=None, help="Limit search to a specific channel name or ID.")
@click.option("--limit", default=20, show_default=True, help="Maximum results to show.")
def search(query: str, output_dir: Path, channel: str | None, limit: int) -> None:
    """Search exported JSON for a keyword."""
    try:
        from matterkeep.search import cli_search
        cli_search(query, output_dir=output_dir, channel_filter=channel, limit=limit)
    except MatterkeeperError as e:
        console.print(f"[red]Search failed:[/red] {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
