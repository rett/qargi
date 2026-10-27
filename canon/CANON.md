# Canon: the standard layout of memory and skills

The canon is the one layout every project's memory stores and agent skillset
follow. It is versioned. The current version is **1** (the spec is still being drafted). A store records the
version it conforms to in `/CANON.md`; `dev-agent canon` compares a store with
the current canon and, with approval, brings it in line without losing content.

## Stores

One pair per project:

| Store | Kind | Agents' access | Holds |
|---|---|---|---|
| `<project>-memory` | memory | read-write | verified how-to facts, role history |
| `<project>-reference` | reference | read-only | curated rules, workflow, conventions |

Both stores share one shape: `shared/` for what every role needs, and
`roles/<role>/` for what only that role loads.

```
/CANON.md                  marker: canon version, kind, project, roles
/README.md                 index and load rules (under 3 KB)
/_template.md              (memory) the file template
/shared/                   every role loads this
/roles/<role>/INDEX.md     one per configured role: what that role loads
/roles/<role>/...          that role's files
/_conflicts/<date>/...     content the reconciler could not place without losing
                           something; a curator resolves it, then deletes it
```

Memory store, inside `shared/` and each role: `sandbox/<topic>.md`,
`repos/<repo>/{INDEX.md,setup,gates,pitfalls}/<topic>.md`, and for roles
free-standing `<topic>.md` files, each with Kind, Applies to, Check, Verified.

Reference store, inside `shared/` and each role: folders named for their scope
(`rules/`, `workflow/`, `conventions/`, `architecture/`, `knowledge/`,
`preferences/`, `review/`, and for a role also `tools/` for scripts it runs).

**No numbered prefixes** (`01-rules`). A number in a folder name goes stale when a
folder is inserted and means different things in different roles, so order and
bindingness are stated in the index (its Load column), not in names. A folder may
keep a number only when its whole content is a sequence that needs it, and that
is listed in `canon/layout.json` under `ordered_folders`.

## What version 1 requires

Only the structure: `/CANON.md`, `/README.md`, `shared/INDEX.md`, one
`roles/<role>/INDEX.md` per configured role, nothing outside `shared/`, `roles/`
and `_conflicts/`, no folder for a role the project does not use, and no secrets.
Version 1 is deliberately minimal. The fuller rules for the files themselves
(recipe fields `Kind`, `Applies to`, `Check`, `Verified`, staleness, size, home
paths and address patterns) are not part of it: they are being completed and become
**canon version 2**. Until then `dev-agent memory lint` runs them next to `canon
check` so nothing is dropped.

## Role rules

- The role is named in the agent's prompt. An agent loads `/README.md`,
  `/shared/INDEX.md` and `/roles/<its role>/INDEX.md`, then only what the task
  needs, and never reads or writes under another role's folder.
- Roles come from the fixed list (`dev`, `review`, `docs`, `test`) and from the
  project's stored answers. A role folder for a role the project does not use is a
  deviation.
- This isolation is hygiene, not a trust boundary: a store mounts whole, so an agent can
  read or write another role's folder if it ignores its instructions. If a role must be
  truly separate, give it its own stores.
- It is by convention and made auditable, not enforced: It is made auditable,
  not enforced: `dev-agent canon audit` reads the memory version history and
  reports a session titled for one role (`<project>-<role>-<task>`) writing under
  another role's folder.
- Promote content that turns out to serve every role with `dev-agent canon
  promote`; never copy it.

## Skillset

Per role, `canon/layout.json` lists the Anthropic skills the agent carries (`pdf`
for docs) and the custom skills the tool ships for that role (none yet; the docs
role's generic methodology skills are the next addition). The project's stored
answers choose among them and `dev-agent provision` attaches them to the agent.
Checking an existing agent's skills against its role is not done by the
reconciler yet; the layout manifest is where that will read from.

## Reconciling

`dev-agent canon plan` reads a store, determines the canon version it conforms
to (a store without `/CANON.md` is recognised by its layout: `legacy`), and
prints every step needed to reach the current version. `apply` runs the same
plan with approval. Rules the reconciler always follows:

1. Never lose content. A rename keeps the memory's identity and history; where
   the destination exists with different content, the incoming file goes to
   `/_conflicts/<date>/` and the plan says so.
2. Idempotent. A plan computed again after a partial run only does what is left.
3. The `/CANON.md` marker is written last, so an interrupted run is visibly
   unfinished and is resumed by running it again.
4. Content that cannot be classified is left where it is and reported.
5. Migrations are ordered functions (version N to N+1) and chain: a store at an
   older version reaches the current one by running each step in turn.

## Changing the canon

1. Edit this document and `canon/layout.json`; raise `version` (only after a
   version has been released; until then the draft is edited in place).
2. Add the migration from the previous version in `lib/canon.py` (a function that
   turns the store's memories into a list of steps) and a test fixture.
3. Add a CHANGELOG entry and, for a breaking layout, a MINOR (before 1.0) or
   MAJOR (after) version bump.
4. Every project then sees `canon check` report the older stores and offers the
   migration.

## Earlier layouts

The reconciler recognises two states older than version 1 and migrates them:
`legacy` (the layouts before the canon: `sandbox/` and `repos/` at the root of a
memory store, folders at the root of a reference store) and `draft` (a
`/CANON.md` marker left by an earlier draft of this spec). Both are brought to
version 1 in one plan. Once version 1 is released, every later change gets its own
migration here.

## Importing a foreign store

`dev-agent canon import SOURCE --role ROLE --map NAME` merges an existing store
(for example an older documentation store) into the project's stores under
`roles/<role>/`, using a named mapping (`docs-v0` for the documentation store
layout). Curated parts go to the reference store, run history to the memory
store. Imported folders get names relevant to their scope: numbered prefixes are
removed and the references to them inside the imported files are rewritten.
Collisions go to `/_conflicts/`. The source is read, never modified.
