# matterkeep

Archive your Mattermost message history and media into a self-contained, searchable offline HTML archive — no admin access required.

## Overview

matterkeep exports everything a regular Mattermost user can see: channels, private channels, DMs, group messages, threads, reactions, and file attachments. Output is a directory of flat files (JSON + media) plus a static HTML archive you can open in any browser, air-gapped.

**Key behaviours:**
- Authenticates with username + password (MFA/TOTP supported). PAT via `MM_TOKEN` env var as an alternative.
- Incremental sync — re-runs only fetch posts newer than the last export.
- `--media-only` downloads attachments without saving message history.
- `--media-manifest` writes `media/manifest.csv` — every downloaded file with sender, timestamp, and channel.
- Optional `age` encryption of the archive.
- Client-side full-text search via Lunr.js. Dark theme by default.
- Per-channel filter bar — filter messages by keyword, sender, and date range; system messages hidden while a filter is active.
- Persistent sidebar on all pages — jump between channels without returning to the index; empty channels hidden by default with a toggle to reveal them.
- Image attachments render as thumbnails inline; click to open full size.
- Media organised into human-readable folders by channel name.

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

# Exclude specific channels
matterkeep export --exclude-channels recruiting,random --output-dir ./archive

# JSON only, no file downloads, no HTML rendering
matterkeep export --skip-files --skip-render --output-dir ./archive

# Download media only (no message history written)
matterkeep export --media-only --output-dir ./archive

# Download media and write a CSV log of who sent what, when
matterkeep export --media-only --media-manifest --output-dir ./archive

# Force full re-export (ignore sync state) — use this to fetch messages
# after a prior --media-only run; already-downloaded files are skipped
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

### Getting files after a messages-only export

If you exported messages without files (e.g. `--skip-files`) and want to download them now, run a normal export without that flag. The exporter scans existing JSON for posts whose attachments weren't downloaded and fetches them — already-downloaded files are skipped.

```bash
matterkeep export --output-dir ./archive
```

If you need to re-fetch everything from scratch, use `--full`:

```bash
matterkeep export --full --output-dir ./archive
```

### Media manifest

`--media-manifest` generates `media/manifest.csv` in the archive directory. Each row covers one downloaded file:

```
timestamp,channel,sender,filename,size,mime_type,local_path
2026-01-15 10:23 UTC,recruiting,Alice Smith,interview-rubric.pdf,42.1 KB,application/pdf,media/...
```

The manifest only includes files downloaded in the current run. To get the full manifest for all files ever downloaded, use `--full --media-manifest`.

### Self-signed certificates

If your server uses a self-signed or internal CA certificate, set `MM_INSECURE=true` in `.env`, or pass `--insecure` on the command line. You can also point `REQUESTS_CA_BUNDLE` at your CA certificate instead.

## Releases

Pushing a version tag triggers a GitHub Actions workflow that builds a Windows executable (`matterkeep.exe`) on a Windows runner using PyInstaller and attaches it to the release. No Python required on the end user's machine.

```bash
git tag v0.2.0
git push origin v0.2.0
```

The `.exe` appears under **Releases** on GitHub once the workflow completes. Users download it and run it directly:

```
matterkeep.exe export --output-dir .\archive
```

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
