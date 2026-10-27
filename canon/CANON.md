# Canon: the standard layout of memory and skills

The canon is the one layout every project's memory stores and agent skillset
follow. It is versioned. The current version is **2**. A store records the
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
/_template.md              the note template of that store's kind
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

## What version 2 requires

**Structure** (unchanged from version 1): `/CANON.md`, `/README.md`, `/_template.md`,
`shared/INDEX.md`, one `roles/<role>/INDEX.md` per configured role, nothing outside
`shared/`, `roles/` and `_conflicts/`, no folder for a role the project does not use.

**One note format for both stores.** Every Markdown file that is not `CANON.md`,
`README.md`, `_template.md` or an `INDEX.md`, and does not sit under a `tools/` folder,
is a *note*: a `# Title` line, then these header lines (conventionally in this order,
before the body; a header line inside a fenced code block is not one), then the body.

| Field | Required | Holds |
|---|---|---|
| `Kind:` | always | one value of the store's vocabulary (below) |
| `Applies to:` | always | the project, repository and ref range, or `any` |
| `Sources:` | always | where the content comes from: repository files with a ref (`docs/x.md@abc1234`), the run or session, or `maintainer, YYYY-MM-DD` |
| `Check:` | runnable kinds | one command whose output shows the note still holds |
| `Verified:` | runnable kinds (optional otherwise) | `YYYY-MM-DD by <who> on <environment>` |
| `Supersedes:` | optional | the path of the note this replaces, or `none` |

Kinds, by store:

| Store | Runnable kinds (need `Check:` and `Verified:`) | Document kinds |
|---|---|---|
| memory | `setup`, `gate`, `pitfall`, `sandbox` | `history`, `status` |
| reference | none | `rule`, `convention`, `workflow`, `architecture`, `knowledge`, `preference`, `review`, `guide` |

In a memory store the folder and the kind agree: `setup/` holds `setup`, `gates/` holds
`gate`, `pitfalls/` holds `pitfall`, `sandbox/` holds `sandbox`. In a reference store
the folder names the scope (`rules/`, `conventions/`, ...), and a kind that does not
match the folder is only a warning.

**Shape of the body.** A runnable note is one verified fact (`Fact:`, `Do:`, then the
header's `Check:` and `Verified:`); a document note is one topic under `## Contents`.
Size: a runnable note over 3000 characters warns (split it), a document note over 10000
warns (an agent loads a note whole, so split one by topic). File names are lowercase with hyphens (digits and dots are fine; numbered folder prefixes stay
forbidden). A `README.md` inside a folder is a note like any other, and its name
is exempt from the lowercase rule. Under `roles/<role>/tools/` live the role's scripts and
they are not notes.

**Freshness.** A runnable note whose `Verified:` is older than 90 days warns; a date in
the future fails. A `Sources:` that says the origin was not recorded warns: it marks
content carried over without provenance that a curator should source or remove.

**Indexes.** Every file is listed in the nearest index (`shared/INDEX.md`,
`roles/<role>/INDEX.md`, or `repos/<repo>/INDEX.md` for a repository's files) as a row of
the table `| Path | Purpose | Load |` with paths relative to the index. A row that points
at a file that does not exist warns. The Load column is `always` or the task that needs the note (`when writing a test`,
`before committing`, `running make lint`): a trigger an agent can act on, never "when unsure", "if needed" or "working on <project>" (which is `always` in disguise). It is the only place that order or bindingness is stated.
An index over 2500 characters warns.

**Budget.** What a role loads before it knows its task (the README, `shared/INDEX.md`, its role index, and every
note an index marks `always`) is at most 8000 characters per store; over that `canon check` warns. Everything
else is loaded when its Load trigger applies.

**Hygiene.** A value that looks like a credential fails; a home path or a dotted-quad
address outside the documentation and private ranges warns (a heuristic: a version number
written as four numbers after a space looks like an address). In a memory store a path
that suggests backlog or planning material warns; a reference store may hold plans on
purpose.

The reconciler's mechanical checks are the whole of this list; `dev-agent canon check`
runs it, and so does `dev-agent memory lint`.

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

The reconciler recognises these states older than version 2 and migrates them in one
plan: `legacy` (the layouts before the canon: `sandbox/` and `repos/` at the root of a
memory store, folders at the root of a reference store), `draft` (a `/CANON.md` marker
left by an earlier draft of this spec, numbered 0) and
`1` (the structure-only version).

The migration from version 1 to 2 only adds: it inserts the header lines a note lacks
(`Kind` from its folder, `Applies to` from its repository or the project, `Sources` from
its `Verified:` line, or a marker that the origin was not recorded) and never edits a
body, placing each in the canonical order after the fields already there. It renames the
`Load when` header to `Load`, replaces the root README and the template with the version 2
text (one that differs from the seed of the version it came from is first copied to
`/_conflicts/<date>/`, in every chain), and writes the marker last. A marker newer than
this dev-agent knows is reported and left alone, never downgraded. A note without a
`Check:` or `Verified:` where its kind needs one is reported by `canon check`, not
invented.

## Importing a foreign store

`dev-agent canon import SOURCE --role ROLE --map NAME` merges an existing store
(for example an older documentation store) into the project's stores under
`roles/<role>/`, using a named mapping (`docs-v0` for the documentation store
layout). Curated parts go to the reference store, run history to the memory
store. Imported folders get names relevant to their scope: numbered prefixes are
removed and the references to them inside the imported files are rewritten.
Collisions go to `/_conflicts/`. The source is read, never modified.
