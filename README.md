# matterkeep

Archive your Mattermost message history and media into a self-contained, searchable offline HTML archive — no admin access required.

## Overview

matterkeep exports everything a regular Mattermost user can see: channels, private channels, DMs, group messages, threads, reactions, and file attachments. Output is a directory of flat files (JSON + media) plus a static HTML archive you can open in any browser, air-gapped.

**Key behaviours:**
- Authenticates with username + password (MFA/TOTP supported). PAT via `MM_TOKEN` env var as an alternative.
- Incremental sync — re-runs only fetch posts newer than the last export.
- `--media-only` downloads attachments without saving message history.
- Optional `age` encryption of the archive.
- Client-side full-text search via Lunr.js. Dark theme by default.

**Architecture:** CLI (click) → Exporter → API Client (mattermostdriver) → Archive Writer (JSON + Jinja2 HTML).

## Requirements

- Python 3.11+
- `age` CLI (optional, for archive encryption — [filippo.io/age](https://filippo.io/age))

## Usage

### Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Configure

Copy the example env file and fill in your server URL:

```bash
cp .env.example .env
```

`.env` variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `MM_URL` | yes | Mattermost server URL |
| `MM_USERNAME` | no | Username or email (prompted if not set) |
| `MM_TOKEN` | no | Personal Access Token (skips password prompt) |
| `MM_INSECURE` | no | Set `true` to disable TLS verification |
| `MM_OUTPUT` | no | Override output directory |

You can also use `config.yaml` (see `config.example.yaml`).

### Export

```bash
# Full export — prompts for password (and MFA code if required)
matterkeep export --output-dir ./archive

# Limit to specific channels
matterkeep export --channels general,random --output-dir ./archive

# JSON only, no file downloads, no HTML rendering
matterkeep export --skip-files --skip-render --output-dir ./archive

# Download media only (no message history written)
matterkeep export --media-only --output-dir ./archive

# Force full re-export (ignore sync state)
matterkeep export --full --output-dir ./archive
```

Open `archive/html/index.html` in a browser to browse the archive.

### Other commands

```bash
# Show sync state (channels, last export time)
matterkeep status --output-dir ./archive

# Encrypt archive with age
matterkeep encrypt --output-dir ./archive --recipient <age-public-key>
matterkeep encrypt --output-dir ./archive  # passphrase mode

# Search exported JSON from the terminal
matterkeep search "keyword" --output-dir ./archive
```

### Self-signed certificates

If your server uses a self-signed or internal CA certificate, set `MM_INSECURE=true` in `.env`, or pass `--insecure` on the command line. You can also point `REQUESTS_CA_BUNDLE` at your CA certificate instead.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Test
pytest tests/ -v --cov=matterkeep

# Lint / type check
ruff check src/ tests/
mypy src/
```

Tests use mocked HTTP (`responses` library) — no real Mattermost instance needed.
