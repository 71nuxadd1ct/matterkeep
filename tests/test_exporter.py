import json
from pathlib import Path
from unittest.mock import MagicMock

from matterkeep.client import MMClient
from matterkeep.config import Config, ExportConfig, RenderConfig, ServerConfig
from matterkeep.exceptions import APIError
from matterkeep.exporter import Exporter, _sanitize_filename

# ── helpers ──────────────────────────────────────────────────────────────────

def make_config(output_dir: Path, **export_kwargs) -> Config:
    return Config(
        server=ServerConfig(url="https://mm.example.com"),
        export=ExportConfig(output_dir=output_dir, **export_kwargs),
        render=RenderConfig(),
        token="test-token",
    )


def make_post(id: str, channel_id: str = "ch1", message: str = "hello",
              create_at: int = 1000, root_id: str | None = None,
              file_ids: list | None = None) -> dict:
    post = {
        "id": id,
        "channel_id": channel_id,
        "user_id": "u1",
        "message": message,
        "create_at": create_at,
        "update_at": create_at,
        "root_id": root_id or "",
        "type": "",
        "metadata": {},
    }
    return post


def make_posts_response(posts: list[dict]) -> dict:
    return {
        "order": [p["id"] for p in posts],
        "posts": {p["id"]: p for p in posts},
    }


def make_client(server_url: str = "https://mm.example.com", token: str = "tok") -> MagicMock:
    client = MagicMock(spec=MMClient)
    return client


SELF_USER = {"id": "me1", "username": "testuser"}


# ── filename sanitization ─────────────────────────────────────────────────────

def test_sanitize_filename_strips_path_separators():
    assert "/" not in _sanitize_filename("../../etc/passwd")
    assert "\\" not in _sanitize_filename("..\\windows\\system32")


def test_sanitize_filename_strips_null_bytes():
    assert "\x00" not in _sanitize_filename("file\x00name.txt")


def test_sanitize_filename_truncates():
    long_name = "a" * 300
    assert len(_sanitize_filename(long_name)) <= 200


def test_sanitize_filename_fallback():
    assert _sanitize_filename("") == "file"
    assert _sanitize_filename("...") == "file"


# ── exporter pipeline ─────────────────────────────────────────────────────────

def test_export_creates_output_dir(tmp_path):
    output = tmp_path / "archive"
    cfg = make_config(output)
    client = make_client()

    client.paginate.return_value = iter([{"id": "t1", "name": "team1", "display_name": "Team 1"}])
    client.get.side_effect = [
        SELF_USER,
        [],  # users/me/channels (DMs)
        [{"id": "ch1", "team_id": "t1", "name": "general", "display_name": "General",
          "type": "O", "header": "", "purpose": ""}],
        make_posts_response([make_post("p1")]),
        {"id": "u1", "username": "alice", "nickname": "", "first_name": "Alice", "last_name": ""},
    ]

    exporter = Exporter(client, cfg)
    exporter.run()

    assert output.exists()
    assert (output / "data" / "ch1.json").exists()
    assert (output / "sync_state.json").exists()
    assert (output / "users.json").exists()


def test_export_writes_correct_post_data(tmp_path):
    output = tmp_path / "archive"
    cfg = make_config(output)
    client = make_client()

    client.paginate.return_value = iter([{"id": "t1", "name": "team1", "display_name": "Team 1"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "general", "display_name": "General",
          "type": "O", "header": "", "purpose": ""}],
        make_posts_response([make_post("p1", message="Hello world", create_at=5000)]),
        {"id": "u1", "username": "alice", "nickname": "Alice", "first_name": "", "last_name": ""},
    ]

    Exporter(client, cfg).run()

    with (output / "data" / "ch1.json").open() as f:
        data = json.load(f)

    assert data["channel"]["name"] == "general"
    assert len(data["posts"]) == 1
    assert data["posts"][0]["message"] == "Hello world"
    assert data["posts"][0]["create_at"] == 5000


def test_incremental_sync_uses_since(tmp_path):
    output = tmp_path / "archive"
    cfg = make_config(output)

    # Pre-populate sync state
    output.mkdir(parents=True)
    with (output / "sync_state.json").open("w") as f:
        json.dump({"version": "1", "last_run": None, "channels": {"ch1": 9000}}, f)

    client = make_client()
    client.paginate.return_value = iter([{"id": "t1", "name": "team1", "display_name": "Team 1"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "general", "display_name": "General",
          "type": "O", "header": "", "purpose": ""}],
        {"order": [], "posts": {}},
    ]

    Exporter(client, cfg).run()

    # Verify 'since' was passed
    call_args = client.get.call_args_list
    posts_call = next(c for c in call_args if "posts" in str(c))
    assert posts_call.kwargs["params"]["since"] == 9000


def test_edited_post_merged_not_duplicated(tmp_path):
    output = tmp_path / "archive"
    cfg = make_config(output)
    client = make_client()

    post_v1 = make_post("p1", message="original", create_at=1000)
    post_v2 = make_post("p1", message="edited", create_at=1000)  # same id, updated message

    client.paginate.return_value = iter([{"id": "t1", "name": "t1", "display_name": "T"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "ch", "display_name": "Ch",
          "type": "O", "header": "", "purpose": ""}],
        make_posts_response([post_v1]),
        {"id": "u1", "username": "u", "nickname": "", "first_name": "", "last_name": ""},
    ]
    Exporter(client, cfg).run()

    # Second run — edited post returned
    client.paginate.return_value = iter([{"id": "t1", "name": "t1", "display_name": "T"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "ch", "display_name": "Ch",
          "type": "O", "header": "", "purpose": ""}],
        make_posts_response([post_v2]),
        {"id": "u1", "username": "u", "nickname": "", "first_name": "", "last_name": ""},
    ]
    Exporter(client, cfg).run()

    with (output / "data" / "ch1.json").open() as f:
        data = json.load(f)

    assert len(data["posts"]) == 1
    assert data["posts"][0]["message"] == "edited"


def test_media_only_skips_writing_data(tmp_path):
    output = tmp_path / "archive"
    cfg = make_config(output, media_only=True, skip_files=True)
    client = make_client()

    client.paginate.return_value = iter([{"id": "t1", "name": "t1", "display_name": "T"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "ch", "display_name": "Ch",
          "type": "O", "header": "", "purpose": ""}],
        make_posts_response([make_post("p1")]),
        {"id": "u1", "username": "u", "nickname": "", "first_name": "", "last_name": ""},
    ]
    Exporter(client, cfg).run()

    assert not (output / "data" / "ch1.json").exists()
    # But sync state should still be written
    assert (output / "sync_state.json").exists()
    with (output / "sync_state.json").open() as f:
        state = json.load(f)
    assert "ch1" in state["channels"]


def test_api_error_on_posts_logs_warning_continues(tmp_path, caplog):
    import logging
    output = tmp_path / "archive"
    cfg = make_config(output)
    client = make_client()

    client.paginate.return_value = iter([{"id": "t1", "name": "t1", "display_name": "T"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "ch", "display_name": "Ch",
          "type": "O", "header": "", "purpose": ""}],
        APIError("forbidden", status_code=403),
    ]

    with caplog.at_level(logging.WARNING):
        Exporter(client, cfg).run()

    assert any("Could not fetch" in r.message for r in caplog.records)


def test_file_download_403_skipped(tmp_path, caplog):
    import logging
    output = tmp_path / "archive"
    cfg = make_config(output)
    client = make_client()

    post_with_file = make_post("p1")
    post_with_file["metadata"] = {
        "files": [{"id": "f1", "name": "photo.jpg", "size": 1024, "mime_type": "image/jpeg"}]
    }

    client.paginate.return_value = iter([{"id": "t1", "name": "t1", "display_name": "T"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "ch", "display_name": "Ch",
          "type": "O", "header": "", "purpose": ""}],
        make_posts_response([post_with_file]),
        {"id": "u1", "username": "u", "nickname": "", "first_name": "", "last_name": ""},
    ]
    client.get_stream.side_effect = APIError("access denied", status_code=403)

    with caplog.at_level(logging.WARNING):
        Exporter(client, cfg).run()

    assert any("access denied" in r.message for r in caplog.records)


def test_sync_state_written_atomically(tmp_path):
    output = tmp_path / "archive"
    cfg = make_config(output)
    client = make_client()

    client.paginate.return_value = iter([{"id": "t1", "name": "t1", "display_name": "T"}])
    client.get.side_effect = [
        SELF_USER,
        [],
        [{"id": "ch1", "team_id": "t1", "name": "ch", "display_name": "Ch",
          "type": "O", "header": "", "purpose": ""}],
        make_posts_response([make_post("p1", create_at=7777)]),
        {"id": "u1", "username": "u", "nickname": "", "first_name": "", "last_name": ""},
    ]

    Exporter(client, cfg).run()

    with (output / "sync_state.json").open() as f:
        state = json.load(f)
    assert state["channels"]["ch1"] == 7777
    assert state["last_run"] is not None
