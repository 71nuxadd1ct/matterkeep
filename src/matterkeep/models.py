from dataclasses import dataclass, field


@dataclass
class User:
    id: str
    username: str
    display_name: str
    avatar_url: str | None = None


@dataclass
class FileAttachment:
    id: str
    name: str
    size: int
    mime_type: str
    local_path: str | None = None  # relative path within archive


@dataclass
class Reaction:
    emoji_name: str
    user_id: str
    timestamp: int


@dataclass
class Post:
    id: str
    channel_id: str
    user_id: str
    message: str
    create_at: int   # unix ms
    update_at: int   # unix ms
    root_id: str | None  # None if root post; set if reply
    type: str        # "" for normal, "system_*" for system messages
    files: list[FileAttachment] = field(default_factory=list)
    reactions: list[Reaction] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass
class Channel:
    id: str
    team_id: str
    name: str
    display_name: str
    type: str        # "O" public, "P" private, "D" DM, "G" group
    header: str = ""
    purpose: str = ""
    membership: str = "member"  # "member" or "left"


@dataclass
class Team:
    id: str
    name: str
    display_name: str


@dataclass
class SyncState:
    channels: dict[str, int] = field(default_factory=dict)
    # channel_id -> last post create_at (unix ms)
    last_run: str | None = None  # ISO 8601
    version: str = "1"
