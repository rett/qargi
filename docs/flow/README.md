# Flow

How the work is named, who does it, how a project is developed and released, and how several sessions share the lead.

- [Naming convention](#naming-convention)
- [Roles and members](#roles-and-members)
- [Methodologies](#methodologies)
- [The plain methodology](plain.md): a project whose output is documents, with one branch and no releases
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
four by default; `worker` and `reviewer`, the two base names, default to their base's roles). Every member belongs to a project: `agent add` requires `--project NAME`, and the runtime is that project's `models.provider.local`; with none, `agent add` refuses, and so does a runtime that keeps no agent files. Nothing is written to the runtime's user-level directory (for Claude Code `~/.claude/agents`). `agent list` and `agent models` flag a member `STALE` when the definition, the model catalog or the renderer changed since it was written and `DRIFT` when its file was edited by hand; `agent refresh NAME` writes it again. Two base members cover
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

A methodology file describes the way a project is developed and released: its branches, versioning and
changelog, test tiers, CI, release steps, deployment options and the generic files a new project
starts with. Two ship, `gitflow` and [`plain`](plain.md) (for a project whose output is documents); add your own under `~/.qargi/config/methodologies/NAME/`
(`methodology.json` and a `scaffold/` directory). `qargi methodology list` shows them, `show NAME`
prints one, and `check [NAME]` validates one or all. These verbs only read.

Methodologies are not pluggable in behaviour yet. What a methodology file sets today is the scaffold: the files
and parameters (`test_command`, the task runner, CI timeout, the first version) that `project new` and `project adopt`
write, the integration branch `project attach` looks for (the last of `branches.long_lived`), the release and hotfix
branch name patterns that `release` reads, and the `after_release` steps that `release finish` and `release status` print. What it does not set is the flow itself: the
`feature`, `release` and `branch` verbs name `develop`, `master` and the `feature/` and `agent/` prefixes literally,
so a second methodology can change the files a project starts with and those patterns, not how features and releases
merge. Until the verbs read the branch roles from the file, `gitflow` is the only flow qargi runs for a project that has releases. The key `flow` of
`methodology.json` names the one other shape, `plain` (one long-lived branch, no feature, release or hotfix branches, no tags): on such a project
the `feature`, `release`, `branch prune`, `upstream` and `changelog renumber` verbs refuse (`methodology-no-flow`, exit 2, nothing changed), and
the `local`, `review` and `backlog` verbs work with `--base` set to its branch.

- `qargi project new NAME [--dir DIR] [--param test_command='make test'] [--url URL]` starts a new
  project on the methodology's branches with its generic files.
- `qargi project attach [DIR]` reads an existing repository, shows the answers it would store and the
  gaps against the methodology, and changes nothing in the repository.
- `qargi project adopt PROJECT` closes the safe gaps of an attached repository: it creates the missing long-lived
  branches locally and writes the missing methodology files as one commit on `agent/adopt-<methodology>` for you to review.
  It never overwrites a file or pushes; changelog format, tag format and CI content stay yours. What the project
  declares is not a gap: `release.version_file none`, and a versioned unreleased heading right after a release ("no
  unreleased section yet; the last release is X"), are printed apart as "noted, not gaps". The environment gaps are
  measured against the effective environment (`env.bootstrap_command`, `env.doctor_command` in the answers close the
  target gaps), and a file it writes never names a bootstrap, dry-run or doctor command the repository lacks. The
  changelog sentence of `CLAUDE.md` and `CONTRIBUTING.md` and the heading of a new `CHANGELOG.md` follow
  `release.changelog.unreleased` and `release.changelog.numbered`. A repository with its own `CLAUDE.md` or `AGENTS.md`
  gets a list of what adopt does about each (it edits neither; with a `CLAUDE.md` and no `AGENTS.md` it writes
  `AGENTS.md` with the Development environment section only, and the `@AGENTS.md` import line in `CLAUDE.md` is yours
  to add). `qargi project adopt PROJECT --show` prints everything the plan token covers: the refs, the branches, and the
  full content of each file to write.

  A deviation you accept on purpose is recorded by the lead in the answer `methodology_accepted`, a list of
  `{gap, reason, date}` with the gap written as attach prints it (`file: CONTRIBUTING.md`, `branch: develop`, `env: doctor
  target`): `qargi project set NAME methodology_accepted '[{"gap":"file: CONTRIBUTING.md","reason":"the workflow is in the
  wiki","date":"2026-11-10"}]'`. A member run may not set it. `project attach`, `project adopt` and `marshal handoff` print the
  accepted deviations apart from the open gaps; adopt writes no accepted file and creates no accepted branch; an accepted
  deviation whose gap is gone reads "accepted, no longer applies".

- `qargi project remove PROJECT` retires a project: it removes the stored answers, the project's members (what
  `qargi agent remove` takes away for each: the member file, the copy of its render in the configuration directory and its entry
  in `agents.json`) and the approved `verify.environment` declaration the state keeps for it, so that a project made later under
  the same name is not compared with it. The plan lists exactly those files and a token; the apply needs `--plan TOKEN --approved
  "<the owner's words>"`; it reads what could hold the removal back once more and the approved declarations, writes the audit line `project:remove` with the
  words before the first removal (`begun`) and a last one when it is done (`removed`), and touches nothing in the repository: no branch,
  no checkout, no git operation that changes anything. The marshal records, the audit log, the project's memory, the rendered
  packs and member render under `~/.qargi/state`, and the stored plans stay; the plan lists the files of the marshal that are there
  (the switch file of a project on the local backend, the allowed signers) as `stays:` lines. A removal that fails part way (a file that cannot be removed) leaves what was already
  removed removed and the stored answers in place, writes an audit line that says after how many members it stopped, and exits 1; a new
  plan lists what is left, and the apply of it finishes. A hold that appears between the plan and the apply refuses the apply as it
  refuses the plan. The token covers the project, the hash of the answers
  file, the approved declaration, the hash of the project's raw record in `agents.json` and each member, and nothing that could hold the removal back, so it stays good after a
  refusal. It is refused (exit 2, nothing changed, with the plan as with the apply) when something still names the project, each
  refusal naming the one command that clears it:

  | Refusal | When | Clear it with |
  | --- | --- | --- |
  | `project-remove-unknown` | no stored answers for the name | `qargi project list` |
  | `project-remove-feature` | a branch `feature/*` of the repository is open | `qargi feature finish FEATURE` |
  | `project-remove-run` | a run of the project is not cleaned or closed | `qargi local clean RUN` |
  | `project-remove-lease` | a marshal record has a lead that renewed it less than `marshal.lease_minutes` ago (a record that cannot be read counts) | `qargi marshal release FEATURE --project NAME` |
  | `project-remove-release` | a release cut record has not reached `finish` | `qargi release finish VERSION --project NAME` |
  | `project-remove-linked` | `project link` left a link in the repository's checkout or in one of its work trees | `qargi project unlink NAME`, run inside that work tree |
  | `project-remove-cloud` | the project has a cloud binding (the answer `cloud`) | `qargi cloud unset NAME` |
  | `project-remove-instances` | `instances.json` has an entry named `NAME-...` | `qargi instances remove INSTANCE` |
  | `project-remove-unreadable` | something that could hold it back exists and cannot be read: the stored answers (not JSON, not an object), git in the repository (`for-each-ref`, `worktree list`), the plan of `project unlink` in a work tree, `instances.json`, the registry of runs (the file or a line of it), the `features/` or `release/` directory of the state, and the marshal of a project on the shared refs backend (its switch file `marshal/NAME.enabled` is there: the leases are in refs of the remote, which the records of this machine do not hold) | the command or file the refusal names (for the refs backend: `qargi marshal release FEATURE --project NAME`, then `qargi marshal disable --project NAME`) |

  When several hold it the first of these is the refusal and a note names the others. A member never runs it (its guard refuses
  it, and so does the verb in a member's run directory), and a coordinator session (`QARGI_ACTOR`) may not.

Each prints a plan and a token; they write only when you apply it with `--plan TOKEN --approved "<your
words>"` (`qargi help approvals`). With `--json` on any of these (or any other gated verb) the plan comes as one JSON object,
`{"verb", "plan", "token", "apply", "exit"}`, so a lead reads the token and the command that applies it instead of scraping the text; `apply`
holds the call without `--json` plus `--plan TOKEN --approved "<the user's go-ahead>"`, and the words are the person's to fill in. A call with
no plan token (it ran, or refused) gives `plan` and `token` as `null` and the text in `output`; the exit status is the verb's. `--json` never
supplies `--plan` or `--approved`.
