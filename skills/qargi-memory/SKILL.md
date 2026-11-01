---
name: qargi-memory
description: Check, reconcile and curate the two qargi memory stores of a project: the agent-written recipes store (<project>-memory) and the curated, read-only reference store (<project>-reference), both laid out by the versioned canon (shared/ plus roles/<role>/). Lint, plan/apply a migration, import a foreign store, seed a role, promote a file to shared, audit cross-role writes.
argument-hint: check|plan|apply|import|seed-role|promote|audit PROJECT ... | lint STORE_ID | split|merge|copy FROM TO
---

# /qargi-memory

**Memory store** (`<project>-memory`; agents write under their role folder, `shared/` by promotion): verified how-to facts and role
history. **Reference store** (`<project>-reference`, agents read-only): curated rules,
workflow, conventions and architecture in folders named for their scope (no numbered
prefixes). Agents propose reference changes in their report; the coordinator applies them
(write with `ant beta:memory-stores:memories`).

Both stores use one note format (canon 2): `# Title`, then `Kind`, `Applies to`, `Sources`,
and for the runnable kinds (`setup gate pitfall sandbox`) also `Check` and `Verified`; an
index row (`| Path | Purpose | Load |`) in the same change. No secrets, private names,
per-run data, backlog or plans. `_template.md` in each store is the shape to copy.

Stores are created and seeded by `/qargi-provision`, which uses the canon. `qargi canon
check` (also run by `qargi memory lint STORE_ID`) verifies the whole of it and exits 1
on any FAIL.

## The canon and the reconciler

Both stores follow the versioned canon in `canon/CANON.md` (version 2):
`/CANON.md` marker, `/README.md`, `shared/` for every role and `roles/<role>/`
(with its `INDEX.md`) per role. An agent loads the README, `shared/INDEX.md` and
only its own role's index, never another role's folder.

| Verb | Command | Notes |
|---|---|---|
| check | `qargi canon check PROJECT [--kind K]` | Conformance and version report; exit 1 on any FAIL. |
| seed-role | `qargi canon seed-role PROJECT --role R --approved "..."` | Writes the role's skeleton (`provision/role-seeds/R/`) into the stores without overwriting. |
| plan | `qargi canon plan PROJECT [--kind K] [--default-role R]` | Every step needed to reach the current canon, from whichever version the store is at. Changes nothing. |
| apply | `qargi canon apply PROJECT [--kind K] --approved "..."` | Runs the plan: renames keep identity and history, conflicts go to `/_conflicts/<date>/`, the marker is written last, a re-run resumes. Show the plan first. |
| import | `qargi canon import PROJECT --from STORE --role R --map docs-v0 [--approved "..."]` | Merges a foreign store (the old documentation store layout) into `roles/<R>/` with relevant folder names (numbered prefixes removed, references rewritten); curated parts into the reference store, history into the memory store. The source is only read. |
| promote | `qargi canon promote PROJECT --kind K --path /roles/R/... --approved "..."` | Moves a role's file to `shared/` when every role needs it. |
| audit | `qargi canon audit PROJECT` | Read-only: reports a session of one role writing under another role's folder. |

`qargi memory lint` runs `canon check` (structure, note format, indexes and hygiene).
A new project's stores start from `provision/role-seeds/`: `shared/` (gates, source map, test
conventions) and one folder per role. A seed file ships only when it has baseline content; the
notes below have none, so write each one when you have its content, from the repository, with
`Sources:` and an index row: `shared/architecture/overview.md` (components, data flow,
boundaries), `shared/knowledge/facts.md` (checked behaviour that cost time),
`roles/<role>/preferences/preferences.md` (what the maintainer stated, never inferred).
Each seed file ends with a `### Project specifics` slot: a project statement replaces the
baseline bullet it covers.

A store at an older version gets a plan that only adds what a note lacks (`Kind`, `Applies to`,
`Sources` from its folder and `Verified:` line) and never edits a body.
A new canon version means a new migration; see `canon/CANON.md` § Changing the canon.

`qargi memory split|copy|merge FROM TO` move notes between two stores (directories, `.jsonl` dumps or `memstore_` ids): `split` takes what `--prefix`, `--role` or `--note-kind` picks (`--archive` moves the originals to `/_archive/<date>/`), `copy` leaves the source alone, `merge` adds what `TO` lacks and moves a split's archived originals back. A collision goes to `/_conflicts/<date>/`, nothing is deleted, each note written records its origin in `Sources:`. Run without `--approved` to get the plan and its token, show it, and apply exactly that with `--plan TOKEN --approved "..."`; a store that changed since the plan is refused.

## Memory tiers

A tier is one memory store of the standard layout at a fixed rank, highest first: `repo` (a
directory in the repository, default `qargi/memory`) > `cloud` (the project's recipes store)
> `project` (`~/.qargi/memory/projects/NAME`) > `shared` (`~/.qargi/memory/shared`) >
`system` (`~/.qargi/memory/system`). The directory tiers are moved with the project's answers
`memory.tiers.<tier>.path` (`qargi project set PROJECT memory.tiers.repo.path ...`; `repo`
is relative to the repository, the others absolute or `~`-prefixed; a key left out takes its
default). The reference store is not a tier.

A note lives in exactly one tier. `CANON.md`, `README.md`, `_template.md`, every `INDEX.md`,
`roles/<role>/tools/`, `_archive/` and `_conflicts/` repeat per tier and are exempt.

- `qargi memory tiers [--project P] [--json]` lists each tier with its location, state
  (missing, empty, present, unreachable) and note count. Reads only.
- `qargi memory check [--project P]` runs the canon check on each existing tier and reports a
  note path present in two or more tiers as a FAIL. A missing, empty or unreachable tier is
  an INFO line. Exit 1 on any FAIL; the last line is `N fail, M warn, K tiers checked`.

Rules for agents: write only under `roles/<your role>/` of the memory store. `shared/` is
curated, written by promotion (`qargi canon promote --approved`) or by the person; propose a
shared note in your report, never write it.

- `qargi memory init TIER [--project P] [--plan TOKEN --approved "..."]` creates the tier
  `repo`, `project`, `shared` or `system` as an empty store of the standard layout (the
  `shared` and `system` tiers carry `project: shared` and `project: system` in their marker).
  Without `--approved` it prints the plan, a plan token and, for `repo`, a warning, and
  changes nothing; apply exactly that plan with `--plan TOKEN --approved "..."`. It refuses
  (exit 1, nothing changed): `cloud` (`qargi provision` creates that one), invalid answers,
  a `repo` tier without a repository or outside its checkout, a location that is or nests
  with another tier's, and a non-empty directory that is not a canon-2 store. A tier that
  is already set up says so and exits 0.
- `qargi memory move PATH --from TIER --to TIER [--project P] [--plan TOKEN --approved "..."]`
  moves notes between two tiers that both exist with the current marker. PATH is one note
  (ending in `.md`) or a prefix under `/shared/` or `/roles/<role>/` that selects notes only,
  never indexes, tools, `_archive/` or `_conflicts/`. Nothing is deleted: each copy records
  `copied from tier-FROM:PATH@hash` in `Sources:`, the original goes to `/_archive/<date>/`
  of the first tier, and the index row moves with the note. The plan is shown and
  tokened as for `init`, and a tier whose notes changed since the plan is refused (plan
  again). It refuses a path that is also held by a third tier (resolve it with
  `qargi memory check`), a note that already differs in the target, and a missing tier.
  An unreachable third tier only warns that collisions with it were not checked. A move
  to or from the cloud tier writes the target first and is not atomic across stores: if it
  stops half way, plan again.

qargi never commits the repo tier. `init` and `move` write into the repository checkout and
leave the files uncommitted: the lead reviews and commits them, or ignores them in git.
Dispatched agents see only the committed copy.

The SessionStart hook composes the tiers. Its text lists the tiers, highest first, with
location and state; then the README from the highest tier that has one; then for each tier
its indexes and the notes its indexes mark `always` for the role; then the reference store's.
Each file is capped (4000 characters), the whole is capped (16000), and what did not fit,
was not UTF-8 or could not be reached is listed as `not loaded`; read it with `qargi memory
get` or from the tier's directory. Cloud reads have short timeouts, a missing `ant` marks
the cloud tier unreachable and the directory tiers still load, and a repo tier with
uncommitted changes adds a warning.

Agents never run `init` or `move` (the guard refuses them) and still write only under
`roles/<their role>/`; they propose changes in their report and the lead files them.

`qargi memory get STORE_ID /path.md` reads one note. In Claude Code, the SessionStart hook runs `qargi hook session-start`: inside a registered project's repository it loads the memory tiers and the reference store as described above (a README, the indexes and the `always` notes, capped); other notes are read on demand.
