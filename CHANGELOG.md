# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0] - 2026-04-02

### Added
- `--teams` and `--exclude-teams` CLI options (and matching `export.teams` /
  `export.exclude_teams` config keys) to restrict the export to specific
  Mattermost teams, mirroring the existing `--channels` / `--exclude-channels`
  behaviour.

### Fixed
- Sidebar team sections now visually nest their channels beneath the team
  header via increased left-padding, making the hierarchy unambiguous.
  Each team collapses independently; Direct Messages remain pinned below
  all team sections.

## [0.8.0] - 2026-04-02

### Added
- Multi-team support: the exporter now downloads content from all Mattermost
  teams the user belongs to, and the HTML archive sidebar organises channels
  into collapsible per-team sections with a shared Direct Messages section at
  the bottom. Archives without team metadata fall back to the previous flat
  layout.

[0.8.0]: https://gitlab.andelain.test/apps/matterkeep/compare/v0.7.0...v0.8.0

[0.9.0]: https://gitlab.andelain.test/apps/matterkeep/compare/v0.8.0...v0.9.0
