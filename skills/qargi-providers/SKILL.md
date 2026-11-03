---
name: qargi-providers
description: Add, review, verify and enable the runtimes qargi dispatches to (runtime, catalog and extension packs in the provider library), including a command-line or local model runtime defined with data only and no code. Plan, token and approval for every change, approval of each executable by name, what verification and attest mean, and which runtime a project uses on its local and cloud surface. For the lead or a Claude Code session, never for a member.
argument-hint: provider list|show|check|new|import|seal|remove|enable|disable|attest|accept ... | project set P models.provider.local|cloud NAME
---

# /qargi-providers

A **runtime** is one way of running agents on one surface: `local` (on this machine) or
`cloud` (hosted). Claude ships as two, `claude-code` (local) and `claude-platform` (cloud),
which share the model catalog of the family `claude`. A runtime is **data**, a JSON
definition, not code. Three kinds of pack share the provider library
(`~/.qargi/config/packs/providers/NAME/`, never in a repository):

| Kind | What it is |
|---|---|
| `provider` (runtime) | one runtime on one surface; `family` names the catalog it shares, or `null` |
| `catalog` | the models of a family (tiers, effort levels, when and where each was verified) |
| `extension` | capabilities added to a runtime, for the projects that enable it |

A name is used once among these packs and the shipped definitions. `qargi provider list`,
`show NAME` and `check NAME|DIR` read them; `show NAME --project P` shows the runtime composed
with P's extensions.

## Which runtime a project uses

There is no default. Ask for each surface, and leave one out if the project never uses it:
`qargi project set P models.provider.local NAME` and `models.provider.cloud NAME` (also `project
new|attach --provider-local X --provider-cloud Y`). A family name works when exactly one runtime
of it serves that surface; a runtime that does not serve the surface is refused. A verb that needs
a surface the answers leave out stops with exit 2 and says which.

## Add a runtime with no code

1. `qargi provider new fakecli [--from minimal|command|hook-cli|RUNTIME]` scaffolds an unsealed
   pack (unusable until sealed).
2. Edit `~/.qargi/config/packs/providers/fakecli/definition.json`: `models`, `render`, `link`,
   `dispatch`, `barrier`, `session`. Load `definition.md` for the fields and a complete example.
3. `qargi provider check fakecli` validates the schema, prints the review and runs the hermetic
   cases; fix every failure. Then `qargi provider seal fakecli` and `check` again: a library pack
   records what it verified only once sealed.
4. `qargi project set P models.provider.local fakecli`. It refuses, naming each role, when a
   role's stored `model` does not match the runtime's `pattern`; change the roles' models in the
   answers first. Render its skills with `qargi packs apply --target fakecli P` (`/qargi-packs`).

`qargi provider import SOURCE [--name N] [--ref REF] [--path SUB]` takes a runtime someone else
wrote (a directory, a JSON file or an https git URL). It is stored sealed on approval and never
enabled or linked by the import.

## Plan, token, approval

Every verb that changes the library (`new`, `import`, `seal`, `remove`, `enable`, `disable`,
`attest`) prints the review and a plan token first; apply with `--plan TOKEN --approved "<their
words>"` after the person's go-ahead (`qargi help approvals`). A pack that holds executables also
needs `--approve-exec a,b` naming EVERY executable the review listed: a missing or an extra name
refuses. `remove` is refused while a project or an extension still uses the pack.

## Executables are text

A pack holds text only: scripts a person can read (a renderer, a transform, an adapter). Binaries,
archives, symlinks and secrets are refused; opaque blobs and scripts that fetch code are flagged.
A vendor CLI is not in the pack: the person installs it and the definition names it. Read each
executable in the review in full before approving: it runs with the person's rights, and the
member guard cannot contain it.

## Verification

A capability counts only when the definition claims it AND it is verified; otherwise it counts as
`no`, and the roles that need it (review needs a read-only barrier) are not served. A library
definition is verified by `qargi provider check NAME` on the sealed pack; a fact no hermetic case
can show by `qargi provider attest NAME CAP`, which is asked each time and may spend money: never
run a live check on your own initiative. Load `verify.md` before you verify, attest or enable.

## Using a runtime

Members are written by the local runtime (`/qargi-instances`), linked by `qargi project link P`
(`/qargi-project`) and dispatched as `/qargi-task` says; a pack reaches a project only if its
`compatible_providers` matches (`/qargi-packs`). Only you, with the person present, change a
runtime (`qargi help guard`); the person decides every import, seal, enable, attest and spend.
