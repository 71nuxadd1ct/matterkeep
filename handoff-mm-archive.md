# Handoff: mm-archive — Mattermost Personal Archive Tool

> Generated from claude.ai conversation on 2026-03-24.
> This document contains everything needed to implement the project from scratch.

## 1. Project Overview

### Goal

A Python CLI tool that lets a **regular (non-admin) Mattermost user** back up their entire accessible message history and attached media into a self-contained, browseable, searchable offline archive. The archive should be a folder you can open in any browser — no server process, no dependencies, works air-gapped.

### Scope

**In scope (v1):**
- Authenticate via personal access token (PAT)
- Enumerate all teams, channels (public, private), DMs, and group messages the user belongs to
- Export full message history with: threads/replies, reactions, edits (where exposed by the API), usernames, and timestamps
- Download all file attachments and inline images
- Incremental sync — track per-channel export state so repeated runs only fetch new posts
- Render a static HTML archive with: channel sidebar, markdown-rendered messages, threaded replies, inline images, downloadable file links, and client-side full-text search
- Produce structured JSON sidecar files for each channel (machine-readable)
- Optional encryption of the output directory into an `age`-encrypted tarball
- Docker image for scheduled/automated runs

**Out of scope / future work:**
- Admin-level bulk export or compliance export features
- Importing archives into other platforms
- WebSocket-based live/streaming export
- Webhook or custom emoji export
- Exporting playbooks, boards, or plugin-specific data
- GUI / desktop app wrapper

### Key Decisions

- **Python 3.11+** — the user's primary language; strong ecosystem for HTTP clients, CLI tools, and templating.
- **`mattermostdriver` library** — the mature, maintained Python driver for the Mattermost APIv4 (`Vaelor/python-mattermost-driver` on GitHub). Handles auth, pagination helpers, and endpoint mapping. Falls back to raw `requests` calls only if the driver lacks a needed endpoint.
- **Personal access token auth only** — no password storage. Tokens are loaded from env var or system keyring via the `keyring` library. Never stored in config files.
- **Static HTML output with embedded search** — uses Jinja2 templates to render an `index.html` with a sidebar and per-channel message views. Client-side search powered by Lunr.js (pre-built index shipped in the archive).
- **Incremental sync via state file** — a JSON file (`sync_state.json`) in the archive root tracks `{channel_id: last_exported_post_timestamp}`. Subsequent runs resume from that point.
- **`click` for CLI** — preferred over argparse for subcommands, rich help text, and option groups.
- **No database** — the archive is flat files (JSON + HTML + media). Simplicity over query power; the search index covers the "searchable" requirement.
- **`age` for encryption** — modern, simple, auditable. Preferred over GPG for new tooling.

## 2. Architecture

### System Diagram

```
┌─────────────┐         ┌─────────────────┐        ┌──────────────────────┐
│  CLI (click) │────────▶│   Exporter       │───────▶│  Archive Writer      │
│              │         │                  │        │                      │
│  - export    │         │  - enumerate     │        │  - write JSON        │
│  - search    │         │    teams/channels│        │  - render HTML       │
│  - encrypt   │         │  - paginate posts│        │  - build search idx  │
│  - status    │         │  - download files│        │  - copy media files  │
└─────────────┘         │  - track state   │        └──────────────────────┘
                         └────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │   MM API Client  │
                         │  (mattermostdrvr)│
                         │                  │
                         │  Auth: Bearer PAT│
                         │  Rate-limited    │
                         │  Retry w/ backoff│
                         └─────────────────┘
```

### Component Breakdown

#### CLI (`cli.py`)
- **Responsibility**: Parse commands and options, wire together config + exporter + renderer, handle top-level error reporting.
- **Inputs**: Command-line arguments, environment variables.
- **Outputs**: Log messages to stderr, exit codes.
- **Commands**:
  - `mm-archive export` — run a full or incremental export
  - `mm-archive status` — show sync state (channels, last export time, post counts)
  - `mm-archive encrypt` — encrypt an existing archive with `age`
  - `mm-archive search` — CLI-based grep across exported JSON (convenience for headless use)

#### API Client (`client.py`)
- **Responsibility**: Thin wrapper around `mattermostdriver` that adds rate-limit handling, retry with exponential backoff, request logging (with token scrubbing), and TLS verification control.
- **Inputs**: Server URL, personal access token, TLS settings.
- **Outputs**: Deserialized API responses, downloaded file bytes.
- **Key logic**:
  - Respect `X-Ratelimit-Limit` / `X-Ratelimit-Remaining` / `X-Ratelimit-Reset` headers. Sleep when approaching limits.
  - Retry on 429 and 5xx with exponential backoff (max 5 retries, base 1s, max 60s).
  - All requests go through a single `_request()` method that scrubs the token from any log output.

#### Exporter (`exporter.py`)
- **Responsibility**: Orchestrate the data extraction pipeline: teams → channels → posts → files.
- **Inputs**: Configured API client, sync state, output directory path, channel include/exclude filters, `include_left` flag.
- **Outputs**: Per-channel JSON files, downloaded media files, updated sync state.
- **Key logic**:
  - **Channel discovery (current membership)**: `/api/v4/users/me/channels` returns all channels the user is currently a member of — public, private, DMs, and group messages. Note: "closed" DMs (hidden from sidebar) are still returned here since closing doesn't remove membership.
  - **Channel discovery (left public channels)**: When `--include-left` is set, also call `/api/v4/teams/{team_id}/channels` (paginated, requires `view_team` permission) to enumerate ALL public channels on each team. Diff against the current membership list to identify public channels the user has left. These channels are still readable via the posts endpoint since they're public. Tag these channels as `"membership": "left"` in the exported metadata so the HTML renderer can visually distinguish them (e.g., dimmed in sidebar, labeled "left").
  - **Private channels the user has left are NOT recoverable** — the API returns 403 for non-members. The tool should log a warning noting this limitation but cannot work around it without admin access.
  - Load `sync_state.json` if it exists. For each channel, fetch posts with `since` parameter set to last exported timestamp.
  - Paginate using `page` + `per_page` (200 posts per page) until exhausted.
  - For each post with `file_ids`, download files via `/api/v4/files/{file_id}` into a `media/` subdirectory, organized as `media/{channel_id}/{file_id}_{filename}`.
  - Deduplicate files by file_id (skip download if already present on disk).
  - Collect user profiles encountered in posts into a `users.json` lookup (id → username, display_name, avatar URL).
  - Save per-channel data as `data/{channel_id}.json`.
  - Update `sync_state.json` atomically (write to temp file, then rename).

#### Renderer (`renderer.py`)
- **Responsibility**: Take the exported JSON data and produce a self-contained static HTML archive.
- **Inputs**: Archive `data/` directory with channel JSON files, `users.json`, `media/` directory.
- **Outputs**: `html/` directory containing `index.html`, per-channel HTML pages, embedded CSS/JS, and a Lunr.js search index.
- **Key logic**:
  - Use Jinja2 templates (bundled in the package under `templates/`).
  - Render Markdown in messages to HTML (using `markdown` or `mistune` library).
  - Preserve thread structure: group replies under their root post.
  - Render reactions as emoji spans with counts.
  - Inline images (`<img>` tags pointing to relative `../media/` paths).
  - Build a Lunr.js index at render time (Python-side JSON generation), embed it in the HTML for client-side search.
  - Channel sidebar grouped by: Teams > Public Channels, Private Channels, Group Messages, Direct Messages.

#### Config (`config.py`)
- **Responsibility**: Load and validate configuration from a YAML file and/or environment variables.
- **Inputs**: Config file path (optional), environment variables.
- **Outputs**: Validated `Config` dataclass.
- **Key logic**: Environment variables take precedence over config file values. Token is NEVER read from config file — only from env var or keyring.

#### Encryption (`encrypt.py`)
- **Responsibility**: Encrypt the archive directory into an `age`-encrypted tarball.
- **Inputs**: Archive directory path, age recipient (public key or passphrase mode).
- **Outputs**: Encrypted `.tar.age` file.
- **Key logic**: Shell out to `age` CLI (must be installed). Create tarball in memory/temp, pipe through `age -r <recipient>` or `age -p` for passphrase mode.

### File Layout

```
mm-archive/
├── src/
│   └── mm_archive/
│       ├── __init__.py
│       ├── __main__.py       # `python -m mm_archive` entry point
│       ├── cli.py            # Click CLI commands
│       ├── client.py         # Mattermost API client wrapper
│       ├── config.py         # Config loading and validation
│       ├── exporter.py       # Data extraction orchestrator
│       ├── renderer.py       # Static HTML generator
│       ├── encrypt.py        # age encryption wrapper
│       ├── models.py         # Dataclasses for Post, Channel, User, etc.
│       ├── search.py         # CLI search + Lunr index builder
│       └── templates/        # Jinja2 HTML templates
│           ├── base.html
│           ├── index.html
│           ├── channel.html
│           └── assets/
│               ├── style.css
│               └── search.js  # Lunr.js + search UI logic
├── tests/
│   ├── conftest.py           # Shared fixtures, mock API responses
│   ├── test_client.py
│   ├── test_exporter.py
│   ├── test_renderer.py
│   ├── test_config.py
│   ├── test_encrypt.py
│   └── test_cli.py
├── Dockerfile
├── docker-compose.yml        # For scheduled runs with volume mounts
├── pyproject.toml            # Project metadata, dependencies, build config
├── README.md
├── LICENSE                   # MIT
├── .env.example
├── config.example.yaml
└── CLAUDE.md
```

## 3. Interfaces & Contracts

### CLI Interface

```
mm-archive export [OPTIONS]

Options:
  --config PATH          Path to config YAML (default: ./config.yaml)
  --output-dir PATH      Archive output directory (default: ./archive)
  --full                 Force full re-export, ignore sync state
  --channels TEXT        Comma-separated channel names to include (default: all)
  --exclude-channels TEXT  Comma-separated channel names to exclude
  --include-left         Also archive public channels the user has left (discoverable via team channel list)
  --skip-files           Skip file/image downloads
  --skip-render          Skip HTML rendering (JSON export only)
  --verbose / -v         Enable debug logging
  --insecure             Disable TLS certificate verification (NOT recommended)

mm-archive status [OPTIONS]

Options:
  --output-dir PATH      Archive directory to inspect

mm-archive encrypt [OPTIONS]

Options:
  --output-dir PATH      Archive directory to encrypt
  --recipient TEXT       age public key (omit for passphrase mode)
  --output PATH          Output .tar.age path

mm-archive search [OPTIONS] QUERY

Options:
  --output-dir PATH      Archive directory to search
  --channel TEXT         Limit search to specific channel
  --limit INT            Max results (default: 20)
```

### Data Models

```python
from dataclasses import dataclass, field
from datetime import datetime

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
    local_path: str | None = None  # relative path in archive

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
    create_at: int          # unix ms
    update_at: int          # unix ms
    root_id: str | None     # thread parent, None if root post
    type: str               # "", "system_*", etc.
    files: list[FileAttachment] = field(default_factory=list)
    reactions: list[Reaction] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

@dataclass
class Channel:
    id: str
    team_id: str
    name: str
    display_name: str
    type: str               # "O" public, "P" private, "D" DM, "G" group
    header: str = ""
    purpose: str = ""
    membership: str = "member"  # "member" or "left" (for --include-left public channels)

@dataclass
class Team:
    id: str
    name: str
    display_name: str

@dataclass
class SyncState:
    """Per-channel export progress."""
    channels: dict[str, int] = field(default_factory=dict)
    # channel_id -> last post create_at timestamp (unix ms)
    last_run: str | None = None  # ISO 8601
    version: str = "1"
```

### External Integrations

**Mattermost REST API v4** — the only external integration.

Key endpoints used (all user-scoped, no admin required):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v4/users/me` | GET | Verify auth, get own user ID |
| `/api/v4/users/{user_id}` | GET | Resolve user profiles |
| `/api/v4/users/me/teams` | GET | List user's teams |
| `/api/v4/users/me/channels` | GET | List all channels user belongs to (with team_id param) |
| `/api/v4/teams/{team_id}/channels` | GET | List ALL public channels on a team (for --include-left discovery) |
| `/api/v4/channels/{channel_id}` | GET | Channel metadata |
| `/api/v4/channels/{channel_id}/posts` | GET | Paginated posts (params: `page`, `per_page`, `since`) |
| `/api/v4/files/{file_id}` | GET | Download file content |
| `/api/v4/files/{file_id}/info` | GET | File metadata (name, size, mime) |
| `/api/v4/users/{user_id}/image` | GET | User avatar (optional) |
| `/api/v4/emoji` | GET | Custom emoji list (for rendering) |
| `/api/v4/emoji/{emoji_id}/image` | GET | Custom emoji image |

**Auth**: `Authorization: Bearer <personal_access_token>` header on every request.

**Rate limits**: Mattermost returns `X-Ratelimit-Limit`, `X-Ratelimit-Remaining`, and `X-Ratelimit-Reset` headers. Default is 10 req/sec. The client must respect these.

**Pagination**: Posts endpoint uses `page` (0-indexed) and `per_page` (max 200). The `since` parameter accepts a Unix millisecond timestamp and returns posts created after that time.

**Important API behavior note**: The `since` parameter on the posts endpoint returns posts *created or updated* after that timestamp, which means edits to older posts will also appear. The exporter should handle this by merging/updating existing posts in the channel JSON rather than blindly appending.

## 4. Configuration & Environment

### Config Schema

```yaml
# config.yaml
server:
  url: "https://mattermost.example.com"  # Required. Base URL, no trailing slash.
  insecure: false                         # Optional. Skip TLS verify. Default: false.

export:
  output_dir: "./archive"                # Optional. Default: ./archive
  channels: []                           # Optional. Include only these channel names. Empty = all.
  exclude_channels: []                   # Optional. Exclude these channel names.
  skip_files: false                      # Optional. Skip file downloads. Default: false.
  skip_render: false                     # Optional. Skip HTML generation. Default: false.
  include_left: false                    # Optional. Archive public channels user has left. Default: false.
  per_page: 200                          # Optional. Posts per API page. Default: 200 (max).

render:
  theme: "default"                       # Optional. Reserved for future themes.
  inline_images: true                    # Optional. Show images inline vs download links.
```

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `MM_ARCHIVE_TOKEN` | yes | Mattermost personal access token | — |
| `MM_ARCHIVE_URL` | no | Server URL (overrides config file) | — |
| `MM_ARCHIVE_OUTPUT` | no | Output directory (overrides config file) | `./archive` |
| `MM_ARCHIVE_KEYRING_SERVICE` | no | If set, read token from system keyring using this service name instead of env var | — |

### .env.example

```bash
# Mattermost personal access token — generate at Profile > Security > Personal Access Tokens
# NEVER commit this file with a real token.
MM_ARCHIVE_TOKEN=your-personal-access-token-here

# Optional: override server URL from config.yaml
# MM_ARCHIVE_URL=https://mattermost.example.com

# Optional: override output directory
# MM_ARCHIVE_OUTPUT=./archive

# Optional: use system keyring instead of env var for token
# MM_ARCHIVE_KEYRING_SERVICE=mm-archive
```

## 5. Security Considerations

- **Token storage**: The personal access token is the user's identity. It MUST be loaded from the `MM_ARCHIVE_TOKEN` environment variable or from the system keyring (via `keyring` library). It must NEVER appear in config files, command-line arguments (visible in `ps`), or log output. The client wrapper must scrub the token from any debug/error logs.
- **TLS verification**: Enabled by default. The `--insecure` flag exists for self-hosted instances with internal CAs but prints a visible warning to stderr when used. Ideally, users should supply their CA cert via `REQUESTS_CA_BUNDLE` env var instead.
- **Output file permissions**: The archive directory should be created with `0o700` permissions. Media files with `0o600`. The tool should explicitly set `umask` before writing.
- **Encryption at rest**: The `encrypt` subcommand uses `age` to produce an encrypted tarball. The unencrypted archive should be optionally shredded after encryption (with a `--shred` flag that overwrites files before deletion).
- **No credential caching**: The tool does not cache or persist the token between runs. Each invocation must provide it fresh.
- **Input validation**: Channel names from `--channels` / `--exclude-channels` are validated against the API response. File names from the server are sanitized (strip path separators, null bytes, limit length) before writing to disk to prevent path traversal.
- **Dependency pinning**: All dependencies should be pinned in `pyproject.toml` with hashes where feasible. Use `pip-audit` in CI.
- **Rate limit compliance**: Aggressive scraping can get a token revoked. The client must respect rate limit headers and back off appropriately.
- **Downloaded content**: Files from the server are written to disk as-is. The HTML renderer should escape all user-generated content to prevent stored XSS if someone serves the archive over HTTP.

## 6. Dependencies & Tooling

### Runtime Dependencies

```
mattermostdriver>=7.3.2     # Mattermost APIv4 Python driver
click>=8.1                  # CLI framework
pyyaml>=6.0                 # Config file parsing
jinja2>=3.1                 # HTML template rendering
mistune>=3.0                # Markdown to HTML (fast, extensible)
keyring>=25.0               # System keyring access for token
rich>=13.0                  # Pretty terminal output, progress bars
```

### Dev Dependencies

```
pytest>=8.0
pytest-cov>=5.0
pytest-mock>=3.14
responses>=0.25             # Mock HTTP requests
ruff>=0.5                   # Linter + formatter
mypy>=1.10                  # Type checking
pip-audit>=2.7              # Dependency vulnerability scanning
```

### Build & Run

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run export
export MM_ARCHIVE_TOKEN="your-token-here"
mm-archive export --config config.yaml

# Run with Docker
docker build -t mm-archive .
docker run --rm \
  -e MM_ARCHIVE_TOKEN="your-token-here" \
  -v $(pwd)/archive:/archive \
  -v $(pwd)/config.yaml:/config.yaml:ro \
  mm-archive export --config /config.yaml --output-dir /archive

# Test
pytest tests/ -v --cov=mm_archive

# Lint
ruff check src/ tests/
mypy src/
```

### Compatibility Notes

- Python 3.11+ required (uses `str | None` union syntax, `tomllib`, etc.)
- Shell: zsh assumed for any helper scripts or Makefile targets
- OS: Linux primary target. macOS should work. Windows is not a priority but shouldn't be actively broken.
- Docker: Alpine-based image for small footprint. `age` must be installed in the image for the encrypt command.

## 7. Acceptance Criteria

1. `mm-archive --help` prints usage for all subcommands and exits 0.
2. `mm-archive export` with a valid token and server URL successfully authenticates and exports at least one channel's messages to JSON.
3. Exported JSON files are valid, parseable, and contain posts with all fields from the `Post` model.
4. File attachments are downloaded to `media/{channel_id}/` with correct content (byte-identical to source).
5. Running `mm-archive export` twice produces the same result for the first run, and the second run only fetches new posts (incremental sync works).
6. The HTML archive opens in a browser and displays: channel sidebar, messages with markdown rendering, threaded replies grouped under root posts, inline images, and reaction emoji.
7. Client-side search in the HTML archive finds messages by keyword across all channels.
8. `mm-archive status` displays per-channel sync state with human-readable timestamps and post counts.
9. `mm-archive encrypt` produces an `age`-encrypted tarball that can be decrypted with `age -d`.
10. The token never appears in log output, config files, or error messages — even with `--verbose`.
11. Invalid or missing token produces a clear error message, not a Python traceback.
12. Invalid server URL or network errors produce clear error messages with suggested fixes.
13. TLS certificate errors produce a clear message suggesting `--insecure` or `REQUESTS_CA_BUNDLE`.
14. Rate-limited responses (429) are retried with backoff, not treated as fatal errors.
15. File names from the server are sanitized — a malicious filename like `../../etc/passwd` does not write outside the archive directory.
16. `pytest tests/` passes with no warnings and ≥80% coverage.
17. `ruff check` and `mypy` pass cleanly.
18. `docker build` succeeds and the container runs the export command correctly.
19. With `--include-left`, public channels the user has left are discovered, archived, and visually distinguished in the HTML sidebar (e.g., labeled or dimmed).

## 8. Implementation Notes

### Recommended Order

1. **Models + Config** — define the dataclasses and config loading first. Everything else depends on these.
2. **API Client** — implement the `client.py` wrapper with auth, rate limiting, and retry. Write tests with mocked HTTP responses.
3. **Exporter** — build the team → channel → post → file pipeline. Start with a single channel, then generalize. Implement sync state tracking.
4. **CLI (basic)** — wire up `click` commands for `export` and `status` so you can test end-to-end.
5. **Renderer** — build Jinja2 templates and the HTML generation pipeline. Start with a minimal template, iterate on layout.
6. **Search index** — add Lunr.js index generation to the renderer.
7. **Encryption** — implement the `encrypt` subcommand.
8. **CLI search** — add the `search` subcommand for headless JSON grep.
9. **Docker** — write the Dockerfile and docker-compose.yml.
10. **Polish** — error messages, progress bars (via `rich`), README.

### Patterns & Conventions

- **Error handling**: Use custom exception classes (`MMArchiveError`, `AuthError`, `APIError`, `ConfigError`). The CLI catches these at the top level and prints a human-readable message + exit code. Never let raw tracebacks reach the user unless `--verbose` is set.
- **Logging**: Use Python's `logging` module. Default level: `WARNING`. With `-v`: `INFO`. With `-vv`: `DEBUG`. All log output to stderr. The token is scrubbed from debug logs via a custom `logging.Filter`.
- **Progress reporting**: Use `rich.progress` for long-running operations (channel enumeration, post pagination, file downloads). Show channel name, post count, and download progress.
- **Naming**: snake_case for all Python identifiers. Kebab-case for CLI commands and flags. Channel JSON files named by channel_id (not display name) to avoid filesystem issues.
- **Type hints**: Full type annotations on all public functions. Run `mypy --strict` in CI.
- **Tests**: Unit tests mock the API client. Use `responses` library to mock HTTP. Integration tests (optional, in a separate directory) can run against a real Mattermost instance if `MM_TEST_URL` and `MM_TEST_TOKEN` env vars are set.

### Known Edge Cases

- **Left public channels**: With `--include-left`, the tool discovers public channels the user is no longer a member of. Posts are still readable, but file downloads may fail if the server restricts file access to channel members. The exporter should handle 403 on file downloads gracefully (log warning, skip file, continue).
- **Left private channels**: Completely inaccessible without admin help. The tool cannot even detect which private channels the user was previously in. Worth logging a one-time informational note about this limitation.
- **Deleted users**: Posts may reference user IDs that return 404. The exporter should handle this gracefully (use the raw user_id as a fallback display name).
- **Edited posts**: The `since` parameter returns posts with `update_at` after the timestamp, which includes edits to old posts. The exporter must merge these into existing data rather than duplicating.
- **Large files**: Some attachments may be very large. Implement streaming downloads (don't load entire files into memory). Consider a `--max-file-size` option.
- **System messages**: Posts with `type` starting with `system_` (e.g., user joined, channel renamed) should be rendered differently in HTML — styled as system events, not chat messages.
- **Custom emoji**: If the server has custom emoji, the renderer needs to fetch and store their images. Fall back to the emoji name as text if unavailable.
- **Unicode channel names**: Some teams use non-ASCII channel names. Sanitize for filesystem use but preserve display names in the HTML.
- **API pagination inconsistency**: The Mattermost posts endpoint returns posts in a `posts` dict keyed by post ID plus an `order` array. The order array defines display order. Use `order`, not dict key order.
- **Rate limit edge case**: Some Mattermost deployments (behind reverse proxies) may not send rate limit headers. The client should still have a configurable default delay between requests as a safety net.

### Extension Points

These should be structurally accommodated but NOT implemented in v1:

- **Plugin for other output formats**: The renderer should be a protocol/interface so future formats (PDF, Markdown, MBOX) can be added.
- **Webhook/bot export**: The models support bot-posted messages already; a future version could export webhook configs.
- **Selective restore/import**: The JSON format should be rich enough that a future `mm-archive import` command could push data into a new instance.
- **Watch mode**: A future `mm-archive watch` could use the WebSocket API for near-realtime archiving.
- **Multi-user archives**: Currently single-user. The archive format should not preclude merging multiple user exports.

## 9. Suggested CLAUDE.md

```markdown
# CLAUDE.md

## Project: mm-archive

Mattermost personal archive tool — CLI that exports a user's messages and media
into a searchable, self-contained static HTML archive.

## Quick Reference
- Language: Python 3.11+
- Shell: zsh
- Package manager: pip with pyproject.toml
- Run: `mm-archive export --config config.yaml`
- Test: `pytest tests/ -v --cov=mm_archive`
- Lint: `ruff check src/ tests/ && mypy src/`
- Format: `ruff format src/ tests/`

## Architecture
CLI (click) → Exporter (orchestrates API calls) → API Client (mattermostdriver + rate limiting)
→ Archive Writer (JSON files + Jinja2 HTML renderer with Lunr.js search index).
All data flows one direction: API → local files. No database.

## Key Decisions — Do Not Revisit
- Token auth only (env var or keyring, NEVER config file or CLI arg)
- mattermostdriver library for API access
- Static HTML output with Lunr.js client-side search
- Incremental sync via sync_state.json (per-channel timestamps)
- age for encryption (not GPG)
- click for CLI (not argparse)
- No admin API endpoints — user-scoped only

## Security Requirements
- Token must never appear in logs, config files, error output, or CLI args
- All file names from server must be sanitized before disk write
- TLS verification on by default; --insecure prints a warning
- Archive directory created with 0o700, files with 0o600
- HTML output must escape all user content (XSS prevention)

## Conventions
- Custom exceptions for all error categories; CLI catches and prints cleanly
- logging module, stderr only, token-scrubbing filter
- rich.progress for long operations
- Full type annotations, mypy --strict
- Tests use responses library for HTTP mocking
```
