# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Dispatcher skill with named instances (local subagent or cloud Managed
  Agents deployment), session tracking, a bounded watcher and an output
  collector. Cloud verbs require `--asked`, the user's request that names
  the cloud instance; sessions are archived, never deleted.
- Agent contract and a per-repository profile (`.dev-agent/profile.md`) for
  gates and rules; an example profile for a Go CLI project.
- `install.sh` to symlink the skill and the local subagent into a project.
