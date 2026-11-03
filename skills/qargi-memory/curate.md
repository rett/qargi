Load when you import a foreign store, seed a role, promote a note to shared, audit cross-role writes, or split, copy or merge stores.

# Curating the stores

| Verb | Command | Notes |
|---|---|---|
| seed-role | `qargi canon seed-role PROJECT --role R --approved "..."` | Writes the role's skeleton (`provision/role-seeds/R/`) into the stores without overwriting. |
| import | `qargi canon import PROJECT --from STORE --role R --map docs-v0 [--approved "..."]` | Merges a foreign store (the old documentation store layout) into `roles/<R>/`, numbered prefixes removed, references rewritten; curated parts into the reference store, history into the memory store. The source is only read. |
| promote | `qargi canon promote PROJECT --kind K --path /roles/R/... --approved "..."` | Moves a role's file to `shared/` when every role needs it. |
| audit | `qargi canon audit PROJECT` | Read-only: reports a session of one role writing under another role's folder; a cloud base session is attributed through its role in the local session tracker, and one that cannot be attributed is counted in a NOTE. |

A new project's stores start from `provision/role-seeds/`: `shared/` (gates, source map, test
conventions) and one folder per role. A seed file ships only with baseline content; write the rest
when you have it, from the repository, with `Sources:` and an index row: `shared/architecture/overview.md`,
`shared/knowledge/facts.md` (checked behaviour that cost time) and
`roles/<role>/preferences/preferences.md` (what the maintainer stated, never inferred). A seed
file ends with a `### Project specifics` slot: a project statement replaces the baseline bullet it
covers.

`qargi memory split|copy|merge FROM TO` move notes between two stores (directories, `.jsonl` dumps
or `memstore_` ids): `split` takes what `--prefix`, `--role` or `--note-kind` picks (`--archive`
moves the originals to `/_archive/<date>/`), `copy` leaves the source alone, `merge` adds what `TO`
lacks and moves a split's archived originals back. A collision goes to `/_conflicts/<date>/`,
nothing is deleted, each note written records its origin in `Sources:`. Without `--approved` they
print the plan and its token; apply exactly that with `--plan TOKEN --approved "..."`.
