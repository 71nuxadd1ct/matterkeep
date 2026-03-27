import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.text import Text

from matterkeep.exceptions import MatterkeeperError

console = Console()


def cli_search(
    query: str,
    output_dir: Path,
    channel_filter: str | None = None,
    limit: int = 20,
) -> None:
    data_dir = output_dir / "data"
    if not data_dir.exists():
        raise MatterkeeperError(f"No data directory found at {data_dir}. Run an export first.")

    users = _load_users(output_dir)
    query_lower = query.lower()
    results = []

    for channel_file in sorted(data_dir.glob("*.json")):
        with channel_file.open() as f:
            data = json.load(f)

        channel = data.get("channel", {})
        if channel_filter and channel_filter not in (channel.get("id"), channel.get("name"), channel.get("display_name")):
            continue

        for post in data.get("posts", []):
            if query_lower in post.get("message", "").lower():
                results.append((channel, post))
                if len(results) >= limit:
                    break

        if len(results) >= limit:
            break

    if not results:
        console.print(f"No results for [bold]{query}[/bold]")
        return

    console.print(f"[bold]{len(results)}[/bold] result(s) for [bold]{query}[/bold]\n")

    for channel, post in results:
        ts = datetime.fromtimestamp(post["create_at"] / 1000, tz=timezone.utc)
        user = users.get(post.get("user_id", ""), {})
        username = user.get("display_name") or user.get("username") or post.get("user_id", "?")
        channel_name = channel.get("display_name") or channel.get("name", "?")

        header = Text()
        header.append(f"#{channel_name}", style="cyan")
        header.append(f"  {username}", style="bold")
        header.append(f"  {ts.strftime('%Y-%m-%d %H:%M')}", style="dim")
        console.print(header)

        message = post.get("message", "")
        idx = message.lower().find(query_lower)
        if idx >= 0:
            snippet = message[max(0, idx - 60): idx + len(query) + 60]
            highlighted = Text(snippet)
            highlighted.highlight_words([query], style="bold yellow")
            console.print(highlighted)
        else:
            console.print(message[:120])

        console.print()


def _load_users(output_dir: Path) -> dict[str, dict]:
    users_file = output_dir / "users.json"
    if not users_file.exists():
        return {}
    with users_file.open() as f:
        return json.load(f)  # type: ignore[no-any-return]
