import json
import logging
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mistune
from jinja2 import Environment, FileSystemLoader, select_autoescape

from matterkeep.config import Config
from matterkeep.exceptions import MatterkeeperError

logger = logging.getLogger(__name__)


def _templates_dir() -> Path:
    """Return the templates directory whether running normally or frozen by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "matterkeep" / "templates"  # type: ignore[attr-defined]
    return Path(__file__).parent / "templates"

_md = mistune.create_markdown(escape=True)


def _ts_to_str(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    return dt.strftime("%Y-%m-%d %H:%M")


def _build_lunr_index(
    channels_data: list[dict[str, Any]],
    channels_by_id: dict[str, Any],
    users: dict[str, Any],
) -> list[dict[str, Any]]:
    docs = []
    for ch_data in channels_data:
        ch_raw = ch_data["channel"]
        ch = channels_by_id.get(ch_raw["id"], ch_raw)
        channel_name = ch.get("display_name") or ch.get("name", "")
        channel_type = ch_raw.get("type", "O")
        for post in ch_data.get("posts", []):
            if post.get("type", ""):
                continue
            user = users.get(post.get("user_id", ""), {})
            sender = user.get("display_name") or user.get("username") or post.get("user_id", "")
            docs.append({
                "id": post["id"],
                "channel_id": ch_raw["id"],
                "channel_name": channel_name,
                "channel_type": channel_type,
                "sender": sender,
                "body": post.get("message", ""),
            })
    return docs


class Renderer:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._output = config.export.output_dir
        self._html_dir = self._output / "html"
        try:
            self._env = Environment(
                loader=FileSystemLoader(str(_templates_dir())),
                autoescape=select_autoescape(["html"]),
            )
        except Exception as e:
            raise MatterkeeperError(f"Could not load templates: {e}") from e

    def run(self) -> None:
        data_dir = self._output / "data"
        if not data_dir.exists():
            raise MatterkeeperError(f"No data directory found at {data_dir}.")

        self._html_dir.mkdir(parents=True, exist_ok=True)

        users = self._load_users()
        teams = self._load_teams()
        channels_data = self._load_channels(data_dir)

        if not channels_data:
            logger.warning("No channel data found to render.")
            return

        channels = self._enrich_channels(channels_data)
        channels_by_id = {ch["id"]: ch for ch in channels}
        lunr_docs = _build_lunr_index(channels_data, channels_by_id, users)
        self._copy_assets()
        self._write_lunr_docs(lunr_docs)
        for ch_data in channels_data:
            self._render_channel(ch_data, users, channels, teams)

        self._render_index(channels_data, channels, teams)
        self._render_media_page(channels_data, users, channels, teams)
        self._write_root_redirect()
        logger.info("HTML archive written to %s", self._html_dir)

    def _write_root_redirect(self) -> None:
        """Write a redirect index.html at the archive root for easy access."""
        redirect = (
            '<!DOCTYPE html>\n'
            '<html lang="en"><head><meta charset="utf-8">\n'
            '<meta http-equiv="refresh" content="0; url=html/index.html">\n'
            '<title>matterkeep archive</title></head>\n'
            '<body><p><a href="html/index.html">Open archive</a></p></body></html>\n'
        )
        (self._output / "index.html").write_text(redirect, encoding="utf-8")

    def _load_teams(self) -> list[dict[str, Any]]:
        f = self._output / "teams.json"
        if not f.exists():
            return []
        with f.open() as fh:
            return json.load(fh)  # type: ignore[no-any-return]

    def _load_users(self) -> dict[str, Any]:
        f = self._output / "users.json"
        if not f.exists():
            return {}
        with f.open() as fh:
            return json.load(fh)  # type: ignore[no-any-return]

    def _load_channels(self, data_dir: Path) -> list[dict[str, Any]]:
        result = []
        for f in sorted(data_dir.glob("*.json")):
            with f.open() as fh:
                result.append(json.load(fh))
        return result

    def _write_lunr_docs(self, lunr_docs: list[dict[str, Any]]) -> None:
        js = f"window.__LUNR_DOCS__ = {json.dumps(lunr_docs)};"
        (self._html_dir / "assets" / "lunr-docs.js").write_text(js, encoding="utf-8")

    def _copy_assets(self) -> None:
        assets_src = _templates_dir() / "assets"
        assets_dst = self._html_dir / "assets"
        if assets_src.exists():
            shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)

    def _self_id(self, channels_data: list[dict[str, Any]]) -> str:
        """Infer the current user's ID — the one that appears in every DM channel name."""
        me_file = self._output / "me.json"
        if me_file.exists():
            with me_file.open() as f:
                return json.load(f).get("id", "")
        from collections import Counter
        counts: Counter[str] = Counter()
        for cd in channels_data:
            ch = cd["channel"]
            if ch.get("type") == "D":
                for part in ch.get("name", "").split("__"):
                    if part:
                        counts[part] += 1
        top = counts.most_common(1)
        return top[0][0] if top else ""

    def _enrich_channels(self, channels_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self_id = self._self_id(channels_data)
        users = self._load_users()
        result = []
        for cd in channels_data:
            ch = dict(cd["channel"])
            ch["has_real_posts"] = any(not p.get("type") for p in cd.get("posts", []))
            if ch.get("type") == "D" and not ch.get("display_name"):
                parts = ch.get("name", "").split("__")
                other_id = next((p for p in parts if p and p != self_id), parts[0] if parts else "")
                other = users.get(other_id, {})
                ch["display_name"] = other.get("display_name") or other.get("username") or other_id
            result.append(ch)
        return result

    def _render_channel(self, ch_data: dict[str, Any], users: dict[str, Any], channels: list[dict[str, Any]], teams: list[dict[str, Any]]) -> None:
        ch = ch_data["channel"]
        posts = ch_data.get("posts", [])

        threads: dict[str, list[dict]] = {}
        roots: list[dict] = []
        for post in posts:
            root_id = post.get("root_id")
            if root_id:
                threads.setdefault(root_id, []).append(post)
            else:
                roots.append(post)

        rendered_posts = []
        for post in roots:
            rendered_posts.append({
                "post": post,
                "body_html": _md(post.get("message", "")),
                "timestamp": _ts_to_str(post["create_at"]),
                "user": users.get(post.get("user_id", ""), {"display_name": post.get("user_id", "?")}),
                "replies": [
                    {
                        "post": r,
                        "body_html": _md(r.get("message", "")),
                        "timestamp": _ts_to_str(r["create_at"]),
                        "user": users.get(r.get("user_id", ""), {"display_name": r.get("user_id", "?")}),
                    }
                    for r in threads.get(post["id"], [])
                ],
            })

        tmpl = self._env.get_template("channel.html")
        html = tmpl.render(
            channel=ch,
            posts=rendered_posts,
            channels=channels,
            teams=teams,
            theme=self._config.render.theme,
            inline_images=self._config.render.inline_images,
        )
        out = self._html_dir / f"{ch['id']}.html"
        out.write_text(html, encoding="utf-8")

    def _render_media_page(
        self,
        channels_data: list[dict[str, Any]],
        users: dict[str, Any],
        channels: list[dict[str, Any]],
        teams: list[dict[str, Any]],
    ) -> None:
        items = []
        for cd in channels_data:
            ch = cd["channel"]
            for post in cd.get("posts", []):
                if post.get("type"):
                    continue
                user = users.get(post.get("user_id", ""), {})
                sender = user.get("display_name") or user.get("username") or post.get("user_id", "?")
                for f in post.get("files", []):
                    size = f.get("size", 0)
                    if size >= 1_048_576:
                        size_str = f"{size / 1_048_576:.1f} MB"
                    elif size:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = ""
                    mime = f.get("mime_type", "")
                    items.append({
                        "filename": f.get("name", ""),
                        "local_path": f.get("local_path") or "",
                        "is_image": mime.startswith("image/"),
                        "size": size,
                        "size_str": size_str,
                        "channel_id": ch["id"],
                        "channel_display": ch.get("display_name", ch.get("name", "")),
                        "channel_type": ch.get("type", "O"),
                        "sender": sender,
                        "timestamp": _ts_to_str(post["create_at"]),
                        "create_at": post["create_at"],
                    })

        items.sort(key=lambda x: x["create_at"], reverse=True)

        tmpl = self._env.get_template("media.html")
        html = tmpl.render(
            items=items,
            channels=channels,
            teams=teams,
            theme=self._config.render.theme,
        )
        (self._html_dir / "media.html").write_text(html, encoding="utf-8")

    def _render_index(
        self,
        channels_data: list[dict[str, Any]],
        channels: list[dict[str, Any]],
        teams: list[dict[str, Any]],
    ) -> None:
        tmpl = self._env.get_template("index.html")
        html = tmpl.render(
            channels=channels,
            teams=teams,
            theme=self._config.render.theme,
        )
        (self._html_dir / "index.html").write_text(html, encoding="utf-8")
