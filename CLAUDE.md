# CLAUDE.md

## Project: matterkeep

CLI tool to archive a Mattermost user's message history and media into a
self-contained offline HTML archive.

## Quick Reference

- **Language**: Python 3.11+
- **Shell**: zsh
- **Package manager**: pip with pyproject.toml
- **Run**: `matterkeep export --config config.yaml`
- **Test**: `pytest tests/ -v --cov=matterkeep`
- **Lint**: `ruff check src/ tests/ && mypy src/`
- **Format**: `ruff format src/ tests/`

## Tech Stack

<!-- PRE-FILLED — review for accuracy -->

| Layer | Choice | Notes |
|-------|--------|-------|
| CLI | click | subcommands, option groups |
| HTTP client | mattermostdriver + requests | API v4 wrapper |
| Templates | Jinja2 | static HTML rendering |
| Markdown | mistune 3 | message body rendering |
| Search | Lunr.js | client-side, index pre-built at render time |
| Theme | CSS (dark default) | `prefers-color-scheme` aware; dark default |
| Config | pyyaml + python-dotenv | YAML config + .env for credentials |
| Keyring | keyring | future PAT storage |
| Encryption | age (CLI) | optional archive encryption |
| Progress | rich | progress bars, styled output |

## Architecture

```
CLI (click) → Exporter (teams → channels → posts → files)
           → API Client (mattermostdriver, rate-limit, retry)
           → Archive Writer (JSON files + Jinja2 HTML + Lunr.js index)
```

All data flows one direction: Mattermost API → local files. No database.

## Auth

- **MVP**: username + password via interactive prompt → session token held in
  memory for the run, discarded on exit. Server URL from config/env.
- **Future**: PAT via env var or keyring.
- Credentials NEVER written to disk, logs, or error output.

## Key Decisions — Do Not Revisit

- Session token auth for MVP (PAT is a future option)
- `mattermostdriver` for API access; raw `requests` only as fallback
- Static HTML output with Lunr.js client-side search
- Incremental sync via `sync_state.json` (per-channel timestamps)
- `age` for optional encryption (not GPG)
- `click` for CLI (not argparse)
- Flat file output — no database
- No admin API endpoints — user-scoped only
- `--media-only` flag to download attachments without message history

## Security Requirements

- Credentials must never appear in logs, config files, error output, or CLI args
- All filenames from server must be sanitized before disk write (path traversal prevention)
- TLS verification on by default; `--insecure` prints a warning
- Archive directory created with `0o700`, files with `0o600`
- HTML output must escape all user content (XSS prevention)

## Conventions

- Custom exceptions: `MatterkeeperError`, `AuthError`, `APIError`, `ConfigError`
- CLI catches all custom exceptions and prints clean messages; raw tracebacks only with `--verbose`
- `logging` module, stderr only, credentials-scrubbing filter
- `rich.progress` for long-running operations
- Full type annotations, `mypy --strict`
- Tests use `responses` library for HTTP mocking
