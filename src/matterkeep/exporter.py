import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from matterkeep.client import MMClient
from matterkeep.config import Config
from matterkeep.exceptions import APIError
from matterkeep.models import (
    Channel,
    FileAttachment,
    Post,
    Reaction,
    SyncState,
    Team,
    User,
)

logger = logging.getLogger(__name__)

_MAX_FILENAME_LEN = 200
_UNSAFE_FILENAME = re.compile(r'[/\\:*?"<>|\x00]')


def _sanitize_filename(name: str) -> str:
    name = _UNSAFE_FILENAME.sub("_", name)
    name = name.strip(". ")
    return name[:_MAX_FILENAME_LEN] or "file"


def _parse_post(raw: dict[str, Any], channel_id: str) -> Post:
    meta = raw.get("metadata", {}) or {}
    files = [
        FileAttachment(
            id=f["id"],
            name=_sanitize_filename(f.get("name", f["id"])),
            size=f.get("size", 0),
            mime_type=f.get("mime_type", "application/octet-stream"),
        )
        for f in meta.get("files", [])
    ]
    reactions = [
        Reaction(
            emoji_name=r["emoji_name"],
            user_id=r["user_id"],
            timestamp=r["create_at"],
        )
        for r in meta.get("reactions", [])
    ]
    return Post(
        id=raw["id"],
        channel_id=channel_id,
        user_id=raw["user_id"],
        message=raw.get("message", ""),
        create_at=raw["create_at"],
        update_at=raw.get("update_at", raw["create_at"]),
        root_id=raw.get("root_id") or None,
        type=raw.get("type", ""),
        files=files,
        reactions=reactions,
        metadata=meta,
    )


def _parse_channel(raw: dict[str, Any]) -> Channel:
    return Channel(
        id=raw["id"],
        team_id=raw.get("team_id", ""),
        name=raw["name"],
        display_name=raw.get("display_name", raw["name"]),
        type=raw.get("type", "O"),
        header=raw.get("header", ""),
        purpose=raw.get("purpose", ""),
    )


def _parse_team(raw: dict[str, Any]) -> Team:
    return Team(
        id=raw["id"],
        name=raw["name"],
        display_name=raw.get("display_name", raw["name"]),
    )


def _parse_user(raw: dict[str, Any]) -> User:
    return User(
        id=raw["id"],
        username=raw.get("username", raw["id"]),
        display_name=raw.get("nickname") or raw.get("first_name", "") + " " + raw.get("last_name", ""),
        avatar_url=None,
    )


def _write_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_sync_state(output_dir: Path) -> SyncState:
    path = output_dir / "sync_state.json"
    if not path.exists():
        return SyncState()
    with path.open() as f:
        raw = json.load(f)
    return SyncState(
        channels=raw.get("channels", {}),
        last_run=raw.get("last_run"),
        version=raw.get("version", "1"),
    )


def _save_sync_state(output_dir: Path, state: SyncState) -> None:
    state.last_run = datetime.now(timezone.utc).isoformat()
    _write_atomic(
        output_dir / "sync_state.json",
        {
            "version": state.version,
            "last_run": state.last_run,
            "channels": state.channels,
        },
    )


class Exporter:
    def __init__(self, client: MMClient, config: Config) -> None:
        self._client = client
        self._config = config
        self._output = config.export.output_dir
        self._users: dict[str, User] = self._load_existing_users()

    def run(self) -> None:
        self._output.mkdir(parents=True, exist_ok=True)
        os.chmod(self._output, 0o700)

        state = _load_sync_state(self._output)
        if self._config.export.media_only and not (self._output / "data").exists():
            logger.info("--media-only on fresh run: posts fetched but not saved to data/")

        teams = self._fetch_teams()
        channels = self._fetch_channels(teams)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        ) as progress:
            task = progress.add_task("Exporting channels", total=len(channels))
            for channel in channels:
                progress.update(task, description=f"[cyan]{channel.display_name}")
                self._export_channel(channel, state)
                progress.advance(task)

        if not self._config.export.skip_files:
            self._download_missing_files(channels)

        self._save_users()
        _save_sync_state(self._output, state)
        logger.info("Export complete. Sync state saved.")

    def _fetch_teams(self) -> list[Team]:
        raw_teams = list(self._client.paginate("users/me/teams"))
        return [_parse_team(t) for t in raw_teams]

    def _fetch_channels(self, teams: list[Team]) -> list[Channel]:
        cfg = self._config.export
        channels: dict[str, Channel] = {}

        for team in teams:
            raw = self._client.get("users/me/channels", params={"team_id": team.id})
            for c in raw:
                ch = _parse_channel(c)
                ch.team_id = team.id
                channels[ch.id] = ch

        if self._config.export.include_left:
            for team in teams:
                try:
                    for raw_ch in self._client.paginate(
                        f"teams/{team.id}/channels",
                        per_page=200,
                    ):
                        ch_id = raw_ch["id"]
                        if ch_id not in channels:
                            ch = _parse_channel(raw_ch)
                            ch.team_id = team.id
                            ch.membership = "left"
                            channels[ch_id] = ch
                except APIError as e:
                    logger.warning("Could not list all channels for team %s: %s", team.id, e)

        result = list(channels.values())

        if cfg.channels:
            names = set(cfg.channels)
            result = [c for c in result if c.name in names or c.display_name in names]
        if cfg.exclude_channels:
            names = set(cfg.exclude_channels)
            result = [c for c in result if c.name not in names and c.display_name not in names]

        return result

    def _export_channel(self, channel: Channel, state: SyncState) -> None:
        cfg = self._config.export
        data_dir = self._output / "data"
        channel_file = data_dir / f"{channel.id}.json"

        existing_posts: dict[str, dict] = {}
        if channel_file.exists():
            with channel_file.open() as f:
                saved = json.load(f)
                for p in saved.get("posts", []):
                    existing_posts[p["id"]] = p

        since = state.channels.get(channel.id, 0)

        params: dict[str, Any] = {"per_page": cfg.per_page}
        if since:
            params["since"] = since

        page = 0
        latest_ts = since
        new_count = 0

        while True:
            params["page"] = page
            try:
                raw = self._client.get(f"channels/{channel.id}/posts", params=params)
            except APIError as e:
                logger.warning("Could not fetch posts for %s: %s", channel.display_name, e)
                break

            order: list[str] = raw.get("order", [])
            posts_by_id: dict[str, Any] = raw.get("posts", {})

            if not order:
                break

            for post_id in order:
                raw_post = posts_by_id.get(post_id)
                if raw_post is None:
                    continue
                post = _parse_post(raw_post, channel.id)

                if not cfg.media_only:
                    existing_posts[post.id] = _post_to_dict(post)

                if post.create_at > latest_ts:
                    latest_ts = post.create_at

                if not cfg.skip_files:
                    self._download_files(post, channel)

                self._collect_user(post.user_id)
                new_count += 1

            if len(order) < cfg.per_page:
                break
            page += 1

        if latest_ts > since:
            state.channels[channel.id] = latest_ts

        if not cfg.media_only:
            ordered = sorted(existing_posts.values(), key=lambda p: p["create_at"])
            channel_data = {
                "channel": _channel_to_dict(channel),
                "posts": ordered,
            }
            _write_atomic(channel_file, channel_data)

        logger.debug(
            "Channel %s: %d posts processed (since=%d)",
            channel.display_name,
            new_count,
            since,
        )

    def _download_files(self, post: Post, channel: Channel) -> None:
        media_dir = self._output / "media" / channel.id
        media_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(media_dir, 0o700)

        for attachment in post.files:
            dest = media_dir / f"{attachment.id}_{attachment.name}"
            if dest.exists():
                attachment.local_path = str(dest.relative_to(self._output))
                continue
            try:
                chunks = self._client.get_stream(f"files/{attachment.id}")
                with dest.open("wb") as f:
                    for chunk in chunks:
                        f.write(chunk)
                os.chmod(dest, 0o600)
                attachment.local_path = str(dest.relative_to(self._output))
                logger.debug("Downloaded %s", dest.name)
            except APIError as e:
                if e.status_code == 403:
                    logger.warning("File %s: access denied, skipping.", attachment.id)
                else:
                    logger.warning("File %s: download failed (%s), skipping.", attachment.id, e)

    def _collect_user(self, user_id: str) -> None:
        if user_id in self._users:
            return
        try:
            raw = self._client.get(f"users/{user_id}")
            self._users[user_id] = _parse_user(raw)
        except APIError:
            self._users[user_id] = User(id=user_id, username=user_id, display_name=user_id)

    def _download_missing_files(self, channels: list[Channel]) -> None:
        """Download any files from existing JSON that were never fetched."""
        data_dir = self._output / "data"
        if not data_dir.exists():
            return

        channel_map = {ch.id: ch for ch in channels}

        for channel_file in data_dir.glob("*.json"):
            channel_id = channel_file.stem
            channel = channel_map.get(channel_id)
            if channel is None:
                continue

            with channel_file.open() as f:
                data = json.load(f)

            changed = False
            for post_dict in data.get("posts", []):
                for file_dict in post_dict.get("files", []):
                    if file_dict.get("local_path"):
                        full_path = self._output / file_dict["local_path"]
                        if full_path.exists():
                            continue
                    # Missing — download it
                    attachment = FileAttachment(
                        id=file_dict["id"],
                        name=file_dict["name"],
                        size=file_dict.get("size", 0),
                        mime_type=file_dict.get("mime_type", "application/octet-stream"),
                        local_path=file_dict.get("local_path"),
                    )
                    media_dir = self._output / "media" / channel_id
                    media_dir.mkdir(parents=True, exist_ok=True)
                    dest = media_dir / f"{attachment.id}_{attachment.name}"
                    try:
                        chunks = self._client.get_stream(f"files/{attachment.id}")
                        with dest.open("wb") as f:
                            for chunk in chunks:
                                f.write(chunk)
                        os.chmod(dest, 0o600)
                        file_dict["local_path"] = str(dest.relative_to(self._output))
                        changed = True
                        logger.debug("Downloaded missing file %s", dest.name)
                    except APIError as e:
                        if e.status_code == 403:
                            logger.warning("File %s: access denied, skipping.", attachment.id)
                        else:
                            logger.warning("File %s: download failed (%s), skipping.", attachment.id, e)

            if changed:
                _write_atomic(channel_file, data)

    def _load_existing_users(self) -> dict[str, User]:
        path = self._output / "users.json"
        if not path.exists():
            return {}
        try:
            with path.open() as f:
                raw = json.load(f)
            return {
                uid: User(
                    id=uid,
                    username=u.get("username", uid),
                    display_name=u.get("display_name", uid),
                )
                for uid, u in raw.items()
            }
        except Exception:
            return {}

    def _save_users(self) -> None:
        _write_atomic(
            self._output / "users.json",
            {uid: {"id": u.id, "username": u.username, "display_name": u.display_name.strip()}
             for uid, u in self._users.items()},
        )


def _post_to_dict(post: Post) -> dict[str, Any]:
    return {
        "id": post.id,
        "channel_id": post.channel_id,
        "user_id": post.user_id,
        "message": post.message,
        "create_at": post.create_at,
        "update_at": post.update_at,
        "root_id": post.root_id,
        "type": post.type,
        "files": [
            {
                "id": f.id,
                "name": f.name,
                "size": f.size,
                "mime_type": f.mime_type,
                "local_path": f.local_path,
            }
            for f in post.files
        ],
        "reactions": [
            {"emoji_name": r.emoji_name, "user_id": r.user_id, "timestamp": r.timestamp}
            for r in post.reactions
        ],
    }


def _channel_to_dict(channel: Channel) -> dict[str, Any]:
    return {
        "id": channel.id,
        "team_id": channel.team_id,
        "name": channel.name,
        "display_name": channel.display_name,
        "type": channel.type,
        "header": channel.header,
        "purpose": channel.purpose,
        "membership": channel.membership,
    }
