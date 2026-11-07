# Flow

How the work is named, who does it, how a project is developed and released, and how several sessions share the lead.

- [Naming convention](#naming-convention)
- [Roles and members](#roles-and-members)
- [Methodologies](#methodologies)
- [Git-flow](git-flow.md): features, tasks, releases, hotfixes, detached branches, feature branches on origin, pruning, following an upstream repository, the worktree root, the parking branch
- [Feature marshal](marshal.md): who leads which open feature, the lead's context, sharing the records, signing

## Naming convention

Every name follows from the project, so resources are identifiable at a glance.

| Thing | Name | Example |
|---|---|---|
| project | one lower-case token (letters, digits) | `myproject` |
| role | `build`, `write`, `review`, `test` or `lead` | `build` |
| member (local agent) | any kebab-case name you choose | `forge` |
| instance (registry) | `<project>-<role>` | `myproject-build` |
| cloud agent (role) | `<project>-<role>` | `myproject-build` |
| cloud agent (base) | `<project>-worker` (write class), `<project>-reviewer` (read-only) | `myproject-worker` |
| environment (shared by the roles) | `<project>-environment` | `myproject-environment` |
| deployment | `<project>-deployment-<role>` (a base: `-worker`, `-reviewer`) | `myproject-deployment-build` |
| memory stores (project-level) | `<project>-memory` (recipes), `<project>-reference` | `myproject-memory` |
| memory folders | `shared/`, `roles/<role>/` | `roles/build/` |
| session | `<instance>-<task-slug>` | `myproject-build-dots-in-usernames` |
| session on a base | `<project>-worker-<task-slug>`, `<project>-reviewer-<task-slug>` | `myproject-worker-dots-in-usernames` |
| branch (in the agent's clone) | `agent/<task-slug>`, the same slug | `agent/dots-in-usernames` |

Memory belongs to the project, not the instance: every instance of a project
mounts the same recipes store and reference store (read-only), so what one agent
learns serves the next. Agents write to the recipes store only under their own
`roles/<role>/` folder; `shared/` is curated and a note reaches it by promotion
(`qargi canon promote --approved`) or by the person. Provisioning attaches existing stores of
that name and creates them only for a new project. `qargi instances normalize
NAME` renames an existing instance's resources to match, and `instances show`
lists the deviations. The role list can be extended with `QARGI_ROLES`.

## Roles and members

A role is named by its activity. Each of the four work roles is defined by the text
of its role, `roles/<role>/ROLE.md`, the single source: a member gets that text with the
task block (`qargi local prepare` writes it, as `qargi role prompt ROLE` prints it) and a
cloud agent of that role carries it in its prompt. A member keeps the Skill tool for the
packs attached to it, not for its role:

| Role | Defined by | What it does |
|---|---|---|
| `build` | `roles/build/ROLE.md` | changes the code with its tests, manual page, help and changelog |
| `write` | `roles/write/ROLE.md` | writes the operational documentation on its own branch |
| `review` | `roles/review/ROLE.md` | reads a change, runs its checks and reports a verdict; changes no file |
| `test` | `roles/test/ROLE.md` | writes and repairs tests, proves them failing first and stable |
| `lead` | `/qargi-team` | runs a team of members on one task |

The members are yours to name: `qargi agent add forge --roles build,test --project P` renders
the one member definition qargi ships through the project's local runtime into that runtime's own
file (for Claude Code `forge.md`, in the repository's agents directory, hidden from git, or in the
project's member render once `qargi project link` is applied), with the roles it serves (all
four by default; `worker` and `reviewer`, the two base names, default to their base's roles). Every member belongs to a project: `agent add` requires `--project NAME`, and the runtime is that project's `models.provider.local`; with none, `agent add` refuses, and so does a runtime that keeps no agent files. Nothing is written to the runtime's user-level directory (`~/.claude/agents`). `agent list` and `agent models` flag a member `STALE` when the definition, the model catalog or the renderer changed since it was written and `DRIFT` when its file was edited by hand; `agent refresh NAME` writes it again. Two base members cover
the two guard classes: `worker` (build, write and test; write class) and `reviewer` (review; read-only). Models and efforts
come from profiles, not from more members (see [Choosing models](../members-and-providers/models.md)). `qargi agent for build` prints one line,
`MEMBER MODEL EFFORT PROFILE`, and dispatch spawns that member with that model and effort; `qargi agent list`, `rename`,
`refresh` (re-render from the current definition) and `remove` manage the members. Dispatch resolves only the project's base
members: a member named otherwise serves nobody, and `qargi agent models` flags it.

A role is a directory with `role.json` (its class, write or read-only, and a description) and
`ROLE.md` (its instructions). The four above ship with qargi; `review` is read-only. Add your own
under `~/.qargi/config/roles/NAME/` (one lower-case token, never `lead`). The class decides what the
guard allows; the text of a role cannot change it. `qargi role list` shows the roles and where they
live, `role show NAME` prints one, `role prompt NAME` prints its instructions as a task block carries
them, and `role check [NAME]` validates one role or all. `qargi local prepare --role ROLE` prepares a
local run for that role (default `build`): a read-only role keeps the clone unchanged.

## Methodologies

A methodology is the way a project is developed and released, as data: its branches, versioning and
changelog, test tiers, CI, release steps, deployment options and the generic files a new project
starts with. One ships, `gitflow`; add your own under `~/.qargi/config/methodologies/NAME/`
(`methodology.json` and a `scaffold/` directory). `qargi methodology list` shows them, `show NAME`
prints one, and `check [NAME]` validates one or all. These verbs only read.

- `qargi project new NAME [--dir DIR] [--param test_command='make test'] [--url URL]` starts a new
  project on the methodology's branches with its generic files.
- `qargi project attach [DIR]` reads an existing repository, shows the answers it would store and the
  gaps against the methodology, and changes nothing in the repository.
- `qargi project adopt PROJECT` closes the safe gaps of an attached repository: it creates the missing long-lived
  branches locally and writes the missing methodology files as one commit on `agent/adopt-<methodology>` for you to review.
  It never overwrites a file or pushes; changelog format, tag format and CI content stay yours.

Each prints a plan and a token; they write only when you apply it with `--plan TOKEN --approved "<your
words>"` (`qargi help approvals`). With `--json` on any of these (or any other gated verb) the plan comes as one JSON object,
`{"verb", "plan", "token", "apply", "exit"}`, so a lead reads the token and the command that applies it instead of scraping the text; `apply`
holds the call without `--json` plus `--plan TOKEN --approved "<the user's go-ahead>"`, and the words are the person's to fill in. A call with
no plan token (it ran, or refused) gives `plan` and `token` as `null` and the text in `output`; the exit status is the verb's. `--json` never
supplies `--plan` or `--approved`.
