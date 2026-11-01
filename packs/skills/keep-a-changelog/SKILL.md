---
name: keep-a-changelog
description: Record every user-visible change in CHANGELOG.md under Unreleased, in the Keep a Changelog categories, in the same commit as the change; never date or cut a release.
---
# Changelog entries

## Where
- Edit `CHANGELOG.md` under the `## [Unreleased]` heading.
- Put the entry in one category: `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed` or `### Security`.
- A category you need is missing: create it in that order. Append your entry at the end of its list.

## When
- One entry per user-visible change: a command, a flag, an output, a config key, a file format, a behaviour.
- Put it in the same commit as the code. Never add it later as a separate fix-up commit.
- Internal refactors, test changes and comment edits get no entry.

## How to write it
- Write for the user: what changed, and what they must do about it.
- Say "breaking" when it breaks existing use, and give the replacement.
- Match the file: same bullet style, same line width, continuation lines indented under the text.

Example, under `### Changed`:

    - `report --json` now prints the verdict under `result`, not `status` (breaking: update scripts
      that read `status`).

## Never
- Add a version heading, put a date on Unreleased, or move entries into a release.
- Edit a released section.
- Bump `VERSION`. Releasing is the lead's.

## Gaps and conflicts
- No `CHANGELOG.md`, or no `## [Unreleased]` heading: report the gap and leave it. Do not invent the file or the heading.
- A merge conflict in the changelog: keep both entries. Drop neither.
