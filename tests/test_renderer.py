import json
from pathlib import Path

import pytest

from matterkeep.config import Config, ExportConfig, RenderConfig, ServerConfig
from matterkeep.exceptions import MatterkeeperError
from matterkeep.renderer import Renderer, _build_lunr_index, _ts_to_str


# ── helpers ───────────────────────────────────────────────────────────────────

def make_config(output_dir: Path, theme: str = "dark") -> Config:
    return Config(
        server=ServerConfig(url="https://mm.example.com"),
        export=ExportConfig(output_dir=output_dir),
        render=RenderConfig(theme=theme),
        token="tok",
    )


def write_channel(output_dir: Path, channel_id: str, posts: list[dict], channel_meta: dict | None = None) -> None:
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ch = channel_meta or {
        "id": channel_id, "team_id": "t1", "name": channel_id,
        "display_name": channel_id.title(), "type": "O",
        "header": "", "purpose": "", "membership": "member",
    }
    with (data_dir / f"{channel_id}.json").open("w") as f:
        json.dump({"channel": ch, "posts": posts}, f)


def make_post(id: str, message: str = "Hello", user_id: str = "u1",
              create_at: int = 1_700_000_000_000, root_id: str | None = None) -> dict:
    return {
        "id": id, "channel_id": "ch1", "user_id": user_id,
        "message": message, "create_at": create_at, "update_at": create_at,
        "root_id": root_id, "type": "",
        "files": [], "reactions": [],
    }


def write_users(output_dir: Path, users: dict | None = None) -> None:
    (output_dir).mkdir(parents=True, exist_ok=True)
    with (output_dir / "users.json").open("w") as f:
        json.dump(users or {"u1": {"id": "u1", "username": "alice", "display_name": "Alice"}}, f)


# ── timestamp helper ──────────────────────────────────────────────────────────

def test_ts_to_str_format():
    result = _ts_to_str(0)
    assert result == "1970-01-01 00:00"


# ── lunr index ────────────────────────────────────────────────────────────────

def test_build_lunr_index_excludes_system_posts():
    channels_data = [
        {
            "channel": {"id": "ch1", "name": "general", "display_name": "General"},
            "posts": [
                {"id": "p1", "type": "", "message": "hello"},
                {"id": "p2", "type": "system_join_channel", "message": "joined"},
            ],
        }
    ]
    docs = _build_lunr_index(channels_data, {}, {})
    ids = [d["id"] for d in docs]
    assert "p1" in ids
    assert "p2" not in ids


def test_build_lunr_index_includes_channel_name():
    channels_data = [
        {
            "channel": {"id": "ch1", "name": "general", "display_name": "General"},
            "posts": [{"id": "p1", "type": "", "message": "test"}],
        }
    ]
    docs = _build_lunr_index(channels_data, {}, {})
    assert docs[0]["channel_name"] == "General"


# ── renderer output ───────────────────────────────────────────────────────────

def test_renderer_creates_html_files(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    write_channel(tmp_path, "ch1", [make_post("p1")])

    Renderer(cfg).run()

    assert (tmp_path / "html" / "index.html").exists()
    assert (tmp_path / "html" / "ch1.html").exists()


def test_renderer_index_contains_channel_link(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    write_channel(tmp_path, "general", [make_post("p1")])

    Renderer(cfg).run()

    index_html = (tmp_path / "html" / "index.html").read_text()
    assert "general" in index_html


def test_renderer_message_appears_in_channel_html(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    write_channel(tmp_path, "ch1", [make_post("p1", message="unique-test-message-xyz")])

    Renderer(cfg).run()

    channel_html = (tmp_path / "html" / "ch1.html").read_text()
    assert "unique-test-message-xyz" in channel_html


def test_renderer_escapes_xss(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    write_channel(tmp_path, "ch1", [make_post("p1", message="<script>alert('xss')</script>")])

    Renderer(cfg).run()

    channel_html = (tmp_path / "html" / "ch1.html").read_text()
    assert "<script>alert" not in channel_html


def test_renderer_threaded_replies(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    root = make_post("root1", message="Root post")
    reply = make_post("reply1", message="Reply post", root_id="root1")
    write_channel(tmp_path, "ch1", [root, reply])

    Renderer(cfg).run()

    channel_html = (tmp_path / "html" / "ch1.html").read_text()
    assert "Root post" in channel_html
    assert "Reply post" in channel_html
    # reply should be inside a thread div
    root_pos = channel_html.find("Root post")
    reply_pos = channel_html.find("Reply post")
    thread_pos = channel_html.find('class="thread"', root_pos)
    assert root_pos < thread_pos < reply_pos


def test_renderer_dark_theme_in_html(tmp_path):
    cfg = make_config(tmp_path, theme="dark")
    write_users(tmp_path)
    write_channel(tmp_path, "ch1", [make_post("p1")])

    Renderer(cfg).run()

    index_html = (tmp_path / "html" / "index.html").read_text()
    assert 'data-theme="dark"' in index_html


def test_renderer_left_channel_badge(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    ch_meta = {
        "id": "old-ch", "team_id": "t1", "name": "old-channel",
        "display_name": "Old Channel", "type": "O",
        "header": "", "purpose": "", "membership": "left",
    }
    write_channel(tmp_path, "old-ch", [make_post("p1")], channel_meta=ch_meta)

    Renderer(cfg).run()

    index_html = (tmp_path / "html" / "index.html").read_text()
    assert "left" in index_html


def test_renderer_no_data_dir_raises(tmp_path):
    cfg = make_config(tmp_path)
    with pytest.raises(MatterkeeperError, match="No data directory"):
        Renderer(cfg).run()


def test_renderer_inline_image(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    post = make_post("p1")
    post["files"] = [{
        "id": "f1", "name": "photo.jpg", "size": 1024,
        "mime_type": "image/jpeg", "local_path": "media/ch1/f1_photo.jpg",
    }]
    write_channel(tmp_path, "ch1", [post])

    Renderer(cfg).run()

    channel_html = (tmp_path / "html" / "ch1.html").read_text()
    assert "<img" in channel_html
    assert "photo.jpg" in channel_html


def test_renderer_non_image_attachment_shows_link(tmp_path):
    cfg = make_config(tmp_path)
    write_users(tmp_path)
    post = make_post("p1")
    post["files"] = [{
        "id": "f1", "name": "report.pdf", "size": 2048,
        "mime_type": "application/pdf", "local_path": "media/ch1/f1_report.pdf",
    }]
    write_channel(tmp_path, "ch1", [post])

    Renderer(cfg).run()

    channel_html = (tmp_path / "html" / "ch1.html").read_text()
    assert "report.pdf" in channel_html
    assert "<img" not in channel_html
