# Memory

The naming of the memory stores and folders is in [Naming convention](../flow/README.md#naming-convention).

## Memory tiers

A tier is one memory store of the standard layout at a fixed rank. From the highest:
`repo` (a directory in the repository, default `qargi/memory`), `cloud` (the project's
recipes store, `<project>-memory`), `project` (`~/.qargi/memory/projects/NAME`), `shared`
(`~/.qargi/memory/shared`) and `system` (`~/.qargi/memory/system`). The reference store
is not a tier. The directory tiers can be moved with the project's answers
`memory.tiers.repo.path` (relative to the repository), `memory.tiers.project.path`,
`memory.tiers.shared.path` and `memory.tiers.system.path`, set with `qargi project set`;
a key left out takes its default.

A note lives in exactly one tier. The files that every tier needs (`CANON.md`,
`README.md`, `_template.md`, every `INDEX.md`, the role `tools/` folders, `_archive/`
and `_conflicts/`) repeat per tier and are exempt.

- `qargi memory tiers [--project P] [--json]` lists the tiers in rank order with their
  location, whether each is missing, empty or present, and the number of notes; it only reads.
- `qargi memory check [--project P]` runs the canon check on each tier that exists, then fails
  for a note path found in two or more tiers. A tier that is missing or unreachable is
  information, not a failure. Exit 1 on any FAIL.

```
$ qargi memory tiers --project acme
repo     dir    /home/u/src/acme/qargi/memory          present   12 notes
cloud    cloud  memstore_01ABC (acme-memory)           present   40 notes
project  dir    ~/.qargi/memory/projects/acme      missing   (not initialised)
shared   dir    ~/.qargi/memory/shared                 empty
system   dir    ~/.qargi/memory/system                 missing
reference: memstore_01DEF (optional, read-only, not composed)
```

`qargi memory init TIER` creates a missing directory tier (`repo`, `project`, `shared` or
`system`) as an empty store of the standard layout, and `qargi memory move PATH --from TIER
--to TIER` moves one note or a folder of notes from one tier to another. Both print a plan
and a plan token and change nothing until you apply it with `--plan TOKEN --approved "..."`.
A move deletes nothing: the original is archived under `/_archive/<date>/` of the first
tier, the copy records its origin, and the index row follows the note. A note that is also
in a third tier, or an existing store that is not a standard one, is refused. qargi never
commits the repo tier: it is written into your checkout, so review and commit it, or ignore
it in git. The plan names the branch checked out there, which is where the files must be
committed (a member's clone is made from the committed branch). If the checkout is on the
wrong branch, `--worktree DIR` on `init repo` (or on a `move` that has the repo tier at one end)
writes the tier into `DIR` instead, another worktree of the same repository, at the same path
inside it; the plan then says to commit it on the branch checked out in `DIR`, for example the
integration branch. `DIR` must be the top of a work tree of the project's repository, and the
option is refused for any other tier.

The session-start hook shows the tiers, highest first, then the README of the highest tier
that has one, each tier's indexes and the notes marked `always`, with size caps and a list of
what was not loaded. When you dispatch a member, `qargi local prepare` prints a
`TASK-BLOCK MEMORY` block with the same tier summary and the always-load notes, and warns
when the repo tier has uncommitted changes, because the member's clone has only the
committed copy.

Two rules for agents: members and cloud agents write only under `roles/<their role>/` of
the memory store, and `shared/` is curated, so an agent proposes a shared note in its report
and the lead or the person promotes it. `init` and `move` are the lead's: the guard refuses
them to a member. There are no remote shares.

## Splitting, merging and moving memory

A memory store is a directory structure of notes, and `qargi memory` moves notes between two of them. A store is a directory, a `.jsonl` dump (read-only: a source, never a target) or a `memstore_` id; `lib/membackend.py` is the one interface behind all three (the Managed Agents store is reached through `ant`; another backend can be added beside them).

- `qargi memory split FROM TO (--prefix PATH | --role R | --note-kind K) [--archive]` copies the notes the selector picks into `TO`; with `--archive` the originals move to `/_archive/<date>/` in `FROM`.
- `qargi memory copy FROM TO [selector]` copies and leaves `FROM` alone; `qargi memory merge FROM TO` adds every note of `FROM` that `TO` lacks.
- A note that exists on both sides with different content is not overwritten: the incoming one goes to `/_conflicts/<date>/`, as in the reconciler (`--policy keep` leaves it out and reports it instead).

Nothing is ever deleted, and no verb can delete: what leaves a store is archived, and every note written records where it came from by a segment appended to its `Sources:` line (`; copied from NAME:/path@abc123` or `; archived from /path@abc123 on DATE`). So every change can be undone: merging a split's target back into its source moves the archived originals back, byte for byte. A copy from another store is import-only; the source is read, never written.

A note whose name starts with a dot or ends in white space is not a note, and one the target cannot hold (too many path segments, too large for the cloud store) makes the plan refuse, naming the path; narrow the selection with `--prefix`, `--role` or `--note-kind`. `merge` and `copy` without a selector leave the source's `/_archive/` behind.

Each verb prints its plan and a plan token and changes nothing until you run it again with `--plan TOKEN --approved "<your words>"`, which is written to the audit log with the token, the selector and every step (a second line follows when the apply succeeded). A caller's own approval does not stand in for the token. The plan records the digest of every note it read; if an agent wrote to either store in between, the apply is refused before the first change.
