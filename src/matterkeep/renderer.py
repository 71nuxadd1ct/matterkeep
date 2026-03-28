import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mistune
from jinja2 import Environment, PackageLoader, select_autoescape

from matterkeep.config import Config
from matterkeep.exceptions import MatterkeeperError

logger = logging.getLogger(__name__)

_md = mistune.create_markdown(escape=True)


def _ts_to_str(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")


def _build_lunr_index(channels_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs = []
    for ch_data in channels_data:
        ch = ch_data["channel"]
        for post in ch_data.get("posts", []):
            if post.get("type", ""):
                continue
            docs.append({
                "id": post["id"],
                "channel_id": ch["id"],
                "channel_name": ch.get("display_name", ch["name"]),
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
                loader=PackageLoader("matterkeep", "templates"),
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
        channels_data = self._load_channels(data_dir)

        if not channels_data:
            logger.warning("No channel data found to render.")
            return

        lunr_docs = _build_lunr_index(channels_data)
        self._copy_assets()

        channels = self._enrich_channels(channels_data)
        for ch_data in channels_data:
            self._render_channel(ch_data, users, channels)

        self._render_index(channels_data, lunr_docs, channels)
        logger.info("HTML archive written to %s", self._html_dir)

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

    def _copy_assets(self) -> None:
        assets_src = Path(__file__).parent / "templates" / "assets"
        assets_dst = self._html_dir / "assets"
        if assets_src.exists():
            shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)

    def _enrich_channels(self, channels_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for cd in channels_data:
            ch = dict(cd["channel"])
            ch["has_real_posts"] = any(not p.get("type") for p in cd.get("posts", []))
            result.append(ch)
        return result

    def _render_channel(self, ch_data: dict[str, Any], users: dict[str, Any], channels: list[dict[str, Any]]) -> None:
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
            theme=self._config.render.theme,
            inline_images=self._config.render.inline_images,
        )
        out = self._html_dir / f"{ch['id']}.html"
        out.write_text(html, encoding="utf-8")

    def _render_index(
        self,
        channels_data: list[dict[str, Any]],
        lunr_docs: list[dict[str, Any]],
        channels: list[dict[str, Any]],
    ) -> None:
        tmpl = self._env.get_template("index.html")
        html = tmpl.render(
            channels=channels,
            lunr_docs=json.dumps(lunr_docs),
            theme=self._config.render.theme,
        )
        (self._html_dir / "index.html").write_text(html, encoding="utf-8")
