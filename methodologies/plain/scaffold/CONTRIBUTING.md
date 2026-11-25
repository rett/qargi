# Contributing to {{project}}

## Branches

- `main` is the one long-lived branch. It holds the documents as they stand. Nothing here is released: there are no feature, release or hotfix branches, no tags and no version file.
- Work happens on a short-lived branch `agent/<slug>` cut from `main`, for one document or one set of related edits. It is merged back into `main` with `--no-ff` once it has been read, and then deleted. Never commit to `main` directly except by merging a branch.

## Documents

- A document is a file under `artifacts/`. Its path names it, so keep the path stable; to rename a document, move the file in its own commit.
- Images, PDFs and other binary files are committed as they are.
- A task names the paths it may change. A change outside them is not merged.

## Review

- Someone other than the writer reads a change before it is merged, on the branch as it will be merged.
- A task carries a check that says it is done. The check is mechanical: the file exists, its format parses, its length and required headings are right, its links resolve. Whether the document is good is the reader's judgement, not the check's.

## Changes

- One logical change per commit, and the commit message says what changed and why.
- No private names (hosts, users, home paths, secrets) in files or commit messages.
