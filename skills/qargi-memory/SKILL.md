---
name: qargi-memory
description: Run the lead's maintenance of a qargi project's memory - lint or check a store against the canon, plan and apply a canon migration, import a foreign store, seed a role's skeleton, promote a note to shared, audit cross-role writes, split, copy or merge stores, and set up or move notes between the memory tiers (repo, cloud, project, shared, system). Covers the recipes and reference stores. For the lead, never for a member.
argument-hint: check|plan|apply|import|seed-role|promote|audit PROJECT ... | lint STORE_ID | split|merge|copy FROM TO | memory tiers|check|init|move|get
---

# /qargi-memory

**Memory store** (`<project>-memory`): verified how-to facts and role history. **Reference store**
(`<project>-reference`, agents read-only): curated rules, workflow, conventions and architecture in
folders named for their scope (no numbered prefixes). Members propose notes, reference changes
included, in their report; the lead files them (the reference store through the cloud CLI).

Both use one note format (canon 2): `# Title`, then `Kind`, `Applies to`, `Sources`, and for the
runnable kinds (`setup gate pitfall sandbox`) also `Check` and `Verified`; an index row
(`| Path | Purpose | Load |`) in the same change. No secrets, private names, per-run data, backlog
or plans. `_template.md` in each store is the shape to copy.

## The canon and the reconciler

The versioned canon is in `canon/CANON.md`: `/CANON.md` marker, `/README.md`,
`shared/` for every role and `roles/<role>/` (with its `INDEX.md`) per role. An agent loads the
README, `shared/INDEX.md` and its own role's index only. `qargi canon check` (run by `qargi memory lint STORE_ID` too) verifies structure,
note format, indexes and hygiene, and exits 1 on any FAIL.

| Verb | Command | Notes |
|---|---|---|
| check | `qargi canon check PROJECT [--kind K]` | Conformance and version report. |
| plan | `qargi canon plan PROJECT [--kind K]` | Every step to set up an empty store at the current canon. A store at an older canon is `unknown`: plan nothing, bring it in by hand or `canon import`. Changes nothing. |
| apply | `qargi canon apply PROJECT [--kind K] --approved "..."` | Runs the plan: creates the missing files and updates the README's role list, the marker is written last, a re-run resumes. Show the plan first. |

A store at the current canon is kept current (missing indexes, the marker's roles); a new canon version means a
new migration (`canon/CANON.md` § Changing the canon). The other verbs (`seed-role`, `import`, `promote`, `audit`, and
`qargi memory split|copy|merge`) and how a new project's stores are seeded: load `curate.md`.

## Memory tiers

A tier is one store of the standard layout at a fixed rank, highest first: `repo` (a directory in
the repository, default `qargi/memory`) > `cloud` (the project's recipes store) > `project`
(`~/.qargi/memory/projects/NAME`) > `shared` (`~/.qargi/memory/shared`) > `system`
(`~/.qargi/memory/system`). The directory tiers are moved with the answers
`memory.tiers.<tier>.path` (`qargi project set PROJECT memory.tiers.repo.path ...`; `repo` is
relative to the repository, the others absolute or `~`-prefixed). The reference store is not a
tier. A note lives in exactly one tier; `CANON.md`, `README.md`, `_template.md`, every `INDEX.md`,
`roles/<role>/tools/`, `_archive/` and `_conflicts/` repeat per tier and are exempt.

- `qargi memory tiers [--project P] [--json]` lists each tier with its location, state (missing,
  empty, present, unreachable) and note count. Reads only.
- `qargi memory check [--project P]` runs the canon check on each existing tier and reports a note
  path in two or more tiers as a FAIL; it exits 1 on any FAIL. A missing, empty or unreachable tier is an INFO line.
- `qargi memory init TIER [--project P] [--plan TOKEN --approved "..."]` creates the tier `repo`,
  `project`, `shared` or `system` as an empty store. Without `--approved` it prints the plan, a
  token and, for `repo`, a warning. It refuses `cloud` (`qargi provision` creates that one), invalid
  answers, a `repo` tier outside its checkout, a location that is or nests with another tier's, and
  a non-empty directory that is not a canon-2 store; an existing tier says so and exits 0.
- `qargi memory move PATH --from TIER --to TIER [--project P] [--plan TOKEN --approved "..."]` moves
  notes between two tiers that both exist with the current marker. PATH is one note (ending in
  `.md`) or a prefix under `/shared/` or `/roles/<role>/` that selects notes only. Nothing is
  deleted: each copy records `copied from tier-FROM:PATH@hash` in `Sources:`, the original goes to
  `/_archive/<date>/` of the first tier, and the index row moves with the note. A tier whose notes
  changed since the plan is refused, and so is a path held by a third tier, a note that
  already differs in the target and a missing tier. A move to or from the cloud tier writes the
  target first and is not atomic across stores: if it stops half way, plan again. An unreachable third tier only warns that collisions with it were not checked.

`shared/` is curated, written by promotion or by the person. qargi never commits the repo tier:
`init` and `move` leave the files uncommitted for the lead to review and commit.
Dispatched agents see only the committed copy.

The SessionStart hook (`qargi hook session-start`) composes the tiers inside a registered project's
repository: the tiers highest first with location and state, the README of the highest tier that
has one, each tier's indexes and the notes they mark `always` for the role, then the reference
store's. Each file is capped (4000 characters) and the whole (16000); what did not fit, was not
UTF-8 or could not be reached is listed as `not loaded`: read it with `qargi memory get STORE_ID
/path.md` or from the tier's directory. No cloud CLI marks the cloud tier unreachable, and a
repo tier with uncommitted changes adds a warning.
