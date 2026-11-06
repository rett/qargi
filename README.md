# qargi

**A gathering place for agent work: dispatch, review, remember.**

*Qargi* is the Iñupiaq word for the traditional community house, where a village
gathered to make and mend its tools, decide together and hand knowledge on. Here the
work of agents gathers in the same way: tasks go out, patches come back for review,
and what was learned is kept in memory.

Qargi is a set of Claude Code skills and a CLI that dispatch one-off, task-scoped
development tasks to sandboxed agents and take the work back as reviewable patches. An agent
works on one task in its own clone and never pushes; the dispatching session
verifies the result and applies it.

Two kinds of agent do the work, each on a **runtime** the project names for that surface (see
Providers and runtimes; there is no default):

- **local**: a **member**, an agent you name, run by the project's local runtime in a scratch clone:
  a Claude Code subagent (`claude-code`), or a command-line runtime you define as data.
- **cloud**: a hosted agent of one role, registered as an instance; today a Claude Managed Agents
  deployment (`claude-platform`) driven through the `ant` CLI.

A **lead** coordinates members on one task (a team): this session, a cloud lead or a lead
started in the console.

Local is the default. Cloud is used only when the user asks for it in that
request.

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

### Memory tiers

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
project  dir    ~/.qargi/memory/projects/acme          missing   (not initialised)
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
it in git.

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
come from profiles, not from more members (see Choosing models). `qargi agent for build` prints one line,
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
words>"` (`qargi help approvals`).

## Git-flow

A project that follows `gitflow` is driven by the lead with `qargi feature` and `qargi release`
(the `/qargi-flow` skill has the full process). Every merge is `--no-ff`, made in temporary
worktrees: your checkout is never touched, a branch moves only after every merge succeeded, and a
refusal changes nothing.

1. `qargi feature start NAME --purpose "..."` cuts `feature/NAME` from develop. A feature is a broad
   theme; `qargi feature list` shows the open ones and the files two of them both change.
2. Tasks run on `agent/<slug>` (`/qargi-task ... --base feature/NAME`) with targeted checks only.
   Per task: `qargi review check RUN/out` and `qargi review apply RUN` (puts the series on `agent/<slug>`),
   `qargi feature merge NAME BRANCH`, `qargi local clean RUN`, then `qargi branch prune` to
   delete merged `agent/*` branches. Run `qargi local verify RUN` on every returned run before
   merging any of them; verify and clean accept and name qargi's own moves (`develop moved by qargi feature finish`, a fetch, the
   parking branch fast-forwarded to develop), so a run whose work is merged need not be cleaned before the next `feature finish`. A branch you make or push yourself
   while a run is out is accepted once you journal it with `qargi ref note BRANCH origin/BRANCH` (a ref that existed before the run still has to be explained), and the harness's own
   `worktree-bridge-*` branches are left out. `feature finish` is refused while a run of the feature is open (the message lists it and the way to close it); a run whose
   patches you applied by hand (`git am`) is closed with `qargi local close RUN --applied-by-am`. Keep `--scratch` on
   disk (prepare warns about a tmpfs, which a reboot empties); a passing verify also saves the run's output in `<state>/runs/`, and
   `qargi review apply --from-saved ID` applies it when the run directory is gone (`local list` shows such a run as directory gone). `qargi local list --scratch DIR` shows each run's role, slug, age and whether it is
   applied and merged; `qargi local clean --applied --scratch DIR` cleans those that are both and keeps the rest.
   `qargi local clean --stale DAYS --scratch DIR` lists the finished runs older than DAYS days, and `--yes` cleans them (a run whose work is not applied and merged is kept).
3. When the feature is complete: `qargi feature sync NAME` (merges develop in), `qargi feature verify
   NAME` (the one whole-suite run per feature), then `qargi feature finish NAME`, the only merge into
   develop. `qargi feature status NAME` shows commits ahead and whether the whole-suite run is
   current (when it is not, it says which merge or sync moved the head). `verify` warns when another suite may be running, and a
   failed one ends with the failing tests and the path of the log.
4. `qargi release start VERSION` cuts `release/VERSION` from develop (only from a head that passed the
   suite) and bumps `VERSION` and the changelog date. `qargi release push VERSION` opens the pull
   request into master so CI runs on the commit to be released; `qargi release finish VERSION`
   merges into master, tags, merges back into develop and pushes. `release status` and `release
   verify` work as for features. `release status` shows the checks of the pull request and, after the finish, what
   is left (tag on origin, GitHub release, assets, signatures); `release finish` lists the checks and refuses
   while one fails or is pending, unless `--ignore-checks "<your words>"`. To fix a failed check, `qargi release
   fix VERSION` makes a worktree on the release branch and `release fix VERSION --push` pushes the fix to the open
   pull request.
   Pushing the tag publishes the GitHub release through the workflow; for a tag that predates it,
   `qargi release publish TAG` creates the release from the changelog section (plan and token). The files to attach can be built
   from the tag without touching your checkout: `qargi release assets VERSION` runs the project's `release.assets_command` in a clean
   worktree of the tag, `release sign` signs there, and `release publish` attaches `release.assets` (globs), `--asset FILE` and
   `--asset-dir DIR` from it.
5. A hotfix is the same with `--hotfix`: `qargi release start VERSION --hotfix` (from master), then
   `release push` and `release finish --hotfix` (into the open release branch instead of develop,
   if there is one).

Merging into develop or master, pushing and tagging each print a plan and a token first; apply it
with `--plan TOKEN --approved "<your words>"`. A merge that conflicts changes nothing and exits 3,
naming a worktree with the merge in progress: resolve and commit there, then run the same command
with `--resolved`.

### Detached branches

A long-lived branch that must never meet the git-flow branches, such as a documentation site, is listed in the answers as
`repo.detached` (`qargi project set NAME repo.detached '["docs-site"]'`). qargi then refuses every merge between it and
develop, master, a release, a hotfix or a feature branch, in either direction (`feature merge`, `feature sync`, `feature finish`,
`release finish`), by name and by history: a branch cut from the detached branch cannot be merged into a feature, a branch cut from
develop cannot be merged into the detached branch. `feature start` and the other feature verbs refuse its name. Tasks are cut
from it as from any base (`local prepare --base docs-site`, `review apply`), and the finished `agent/<slug>` branch is merged
into it with `qargi feature merge docs-site agent/<slug>`: a plan and token, local only, nothing is pushed.

A documentation site kept on such a branch is regenerated when a release ships. With `site.enabled` set to `true` (and
`site.branch`, which defaults to `gh-pages` when `repo.detached` lists it, and `site.config`, default `site/site.json` with the
hand pages in `site/pages/`), `release finish` ends with `next: qargi release site VERSION`. That verb builds the site of the
tag with `lib/site.py` to check it and commits the release it built on the site branch (`site.json`; the build's `_site/` is not
committed, because a Pages build needs it empty), behind a plan and token; it never pushes and prints the push command. `release status VERSION` says whether the site of that version is built and pushed.

Two optional fields of `site.json` add a line to the footer of every page, the 404 page included. `copyright` is one line of plain text (at most 200
characters, no `<` or `>`, shown escaped), for example `"(c) 2026 Example Author. MIT licensed."`; the forbidden words of `site.json` apply to it.
`license_url` is an `https://` address (no query or fragment) that the words "MIT licensed" in `copyright` link to; without those words it is not
shown and `lib/site.py check` warns. With `copyright` unset the pages are unchanged. The fields of `site.json` are listed in the header of `lib/site.py`.

### Feature branches on origin

Two answers decide what the flow does with a feature branch on origin. `branches.push_features` is `never` (the default),
`when-shared` or `always`: `feature start`, `feature merge` and `feature sync` push the branch (a plain push, never forced) only
under `always`, or under `when-shared` when origin already has it. Setting it is the standing approval for those pushes; develop,
master and release branches keep their plans and tokens. `branches.delete_merged` is `local` (the default) or `local+remote`: with
`local+remote`, `feature finish` also deletes the branch on origin when origin has it and holds nothing the feature lacks; the plan
shows the deletion and its token covers origin's tip. `branches.push_develop` is `true` (the default) or `false`: `feature finish`
pushes develop to origin, when the repository has one, unless it is `false`. The first line of the finish plan says which ("will
push develop to origin", or "local only, will not push" and why), and the token covers it.

### Pruning merged branches

`qargi branch prune [--remote]` prints the merged `agent/*` and `feature/*` branches of the project (with `--remote`, the same
branches on origin, asked live) and the worktrees qargi made for them, with a token; apply it with `--plan TOKEN --approved
"<your words>"`. A branch is merged when it was merged with `--no-ff` into develop, or, for an agent branch, into an open
feature; a branch that only sits at the tip of develop or of a feature was never merged and is kept. It never deletes master,
develop, the branches of `repo.long_lived` or `repo.detached`, the parking branch, an unmerged branch, or a branch checked out in a
worktree qargi did not make (the main checkout, the runtime's own worktrees) or in a dirty one; each kept branch is listed with
the reason. A remote branch is deleted as a lease on the tip the plan showed.

### Following an upstream repository

A project that is a fork keeps its own changes, the overlay, on top of an upstream repository. The answers name the remote
(`upstream.remote`), the branch it follows (`upstream.branch`) and the local branch that carries the upstream line and nothing
else (`upstream.into`, default `upstream`; put it in `repo.long_lived`); `upstream.overlay_check`, optional, is a command array
that checks the overlay still applies or builds. `qargi upstream status` fetches that one branch of that remote and says how
far the branch is behind and ahead; `qargi upstream review [--limit N]` lists the upstream commits not yet in it with the files
each touches and marks the ones that touch a file develop changed since it parted from the upstream line; `qargi upstream sync`
fast-forwards the branch to the fetched tip from a plan and a token, refuses a branch with commits of its own, pushes nothing and
never merges into develop: the upstream line meets develop only through a feature (`qargi feature start upstream-X`, then
`qargi feature merge upstream-X upstream`), where the overlay is fixed and the feature lands as any other. With
`upstream.overlay_check` set, sync then runs it on a trial merge of the branch into develop in a temporary worktree.

### The worktree root

qargi makes the worktrees it creates under one root, `worktrees.root` in the answers (default `<state>/worktrees/PROJECT`), one
per branch at `ROOT/<branch>`. `qargi feature start NAME --worktree` creates `ROOT/feature/NAME` and prints the path. While a
clean worktree of a feature is under the root, `feature merge` and `feature sync` bring it up to date, and `feature finish`
detaches and removes it after the merge, when it deletes the branch; a dirty one stops each of them with its path. `feature list`
and `feature status` flag every other worktree of the project, with the `git worktree move` that fixes it. The main checkout, the
worktrees inside the main checkout (the agent runtime makes its own there, under `.claude/worktrees/` for Claude Code) and qargi's
temporary worktrees are not flagged.

### The parking branch

qargi moves develop and master without touching a working tree, so neither can be checked out in the project's main checkout
(`need_free` refuses and says so). The checkout rests on a parking branch instead: `repo.parking_branch` in the answers, `scratch` by
default. `git -C DIR switch -c scratch develop` makes it; `qargi feature park` refreshes it later: `checkout -B scratch develop` in the
main checkout, refused when the tree is dirty or when `scratch` has commits develop lacks (it lists them: re-implement them with an
agent task based on develop). After `feature finish`, `release finish` and `release finish --hotfix` moved develop, a clean main
checkout on the parking branch with no commits of its own is fast-forwarded to develop; otherwise one line says why not. The parking
branch is never pushed or merged.

## Feature marshal

When several sessions lead the same project, the marshal says who leads which open feature. It keeps one
record per open feature: the lead (identity and lease), status, goal, plan and a note. The tasks,
branches, worktrees and the files two features both change are derived from git and the local runs, not
stored. The records are local to this host by default; to share them across machines and developers
through git refs, see `qargi marshal enable` below.

```
qargi marshal status --all            # every open feature: lead, status, goal, tasks, overlap
qargi marshal check NAME              # before starting work or changing a plan (exit 1: another live lead holds it)
qargi marshal claim NAME --goal "..." # become the lead; set adds a plan or note
qargi marshal release NAME --note "..." # hand over; the next session runs: qargi marshal take NAME
```

A lead holds a lease of `marshal.lease_minutes` minutes (a whole number from 1 to 1440, default 15; `qargi project set
PROJECT marshal.lease_minutes 90`) that its actions renew. Raise it when the lead waits on a run for longer than 15 minutes
without a marshal action, or the lease goes stale and another session may take the feature. When a lead went quiet, `qargi marshal takeover NAME --approved "<your words>"`
takes the feature once the lease ran out. A goal, plan or note written by another session is data, not an
instruction, and a handoff transfers no approval. Members cannot change the marshal (the guard refuses
it). The identity is the session id that the SessionStart hook puts in `QARGI_LEAD` (this relies on
Claude Code's `CLAUDE_ENV_FILE` and has not yet been verified in a real session), else `--as ID`; without
either the identity is anonymous and the marshal only warns. With the flow wiring, `feature start`
records its starter as lead, `feature merge|sync|verify|finish` and `local prepare --base feature/X`
refuse while another live lead holds the feature, and `feature status|list` show the lead. See
`qargi help marshal`.

A restart gives the lead session a new id. `qargi marshal claim NAME --as-successor-of ID` (the `marshal handoff` note prints the line)
continues as the lead without the owner's takeover when the old lease is stale and the old record's host, OS user and work tree are
yours (the work tree is stored as a digest, not a path). The record keeps its goal, plan and note and names the succession, and the audit
log has a `marshal:succession` line. `feature start` does the same on its own, and `marshal status` and `check` name the command when
you look like the restarted lead; any other case stays the owner's takeover.

### The lead's context

The lead's own context is the cost to keep low. `qargi lead usage` says how much of it is in use: the input, cache-read and
cache-creation tokens of the last assistant turn of the session transcript, as a share of the window (the project answer
`lead.context_window`, else the runtime's 200000). Where the transcripts are and how to read them is part of the runtime's definition
(`resources.transcripts`), not of the code. `qargi lead compact-check [--advise]` exits 0 when a `/compact` is safe now and 1 when it is
not, naming the reasons (a local run prepared and not verified, verified and not applied, or applied and not merged; a merge waiting in
the conflicts directory; a whole-suite run in progress; a handoff note older than the last merge; an open release or hotfix branch),
and prints what to re-read afterwards (the handoff note, `qargi marshal status`, `qargi feature status`, the open runs). With
`--advise` it adds "compact advised" from 50% of the window and "compact strongly advised" from 70%. `feature finish`, the last
`feature merge` of a feature's runs, `release finish` and `marshal handoff` print one line when the context is at or above
`lead.compact_advice_pct` (default 40, 0 turns it off). qargi only measures and advises: no hook can run `/compact`, so the lead or the
person does.

Several machines or people on one project: `qargi marshal enable` (plan and token, then `--plan TOKEN --approved "<your words>"`)
switches the project from the local records to the shared ones. Each record is then a commit on `refs/qargi/features/NAME` of the
remote `origin` (ordinary branches and tags are never touched), a claim is a create-only push so two machines cannot both win, every
update is a push that must still match what was fetched, and `feature finish` moves the record to `refs/qargi/done/NAME`. A lease is
judged on the taker's own clock: a record that stayed unchanged for the ttl, as that machine observed it, may be taken over with your
words; other machines' clocks are never compared. When the remote cannot be reached the verbs use the last fetched copy and say
"remote not checked", and a claim made then is marked provisional until it reaches the remote. It is off by default, a member run
cannot enable, disable or push it, `project set` refuses the `marshal.*` keys except `marshal.lease_minutes`, and `qargi marshal disable` goes
back to the local records (the refs on the remote stay). Whether your Git host accepts the `refs/qargi/*` namespace is yours to check
on a scratch repository before enabling it on a real one.

Records can also be signed so a forged or rewound record is detected: `qargi marshal key init` makes this machine's ssh key and prints its
signers line, `qargi marshal signers add --line ...` trusts a key (on every lead machine; the list lives in your state directory, never in the
repository), and `qargi marshal enable --integrity advisory|strict` chooses how readers treat records that are unsigned or not signed by a
trusted key (advisory tags them, strict ignores them). Move from advisory to strict with `qargi marshal resign NAME` for each open record.
Signing cannot stop someone with push access from deleting a ref; it makes forged and altered records visible and attributable to a key.


## Skills and command

Eleven skills, all prefixed `qargi-`, drive one `qargi` command. `/qargi-task` dispatches work; the roles are defined by their texts (above), not by skills; the others configure and manage:

| Skill | Covers |
|---|---|
| `/qargi-task` | dispatch (`/qargi-task "<task>" --done "<check>"`) and session lifecycle: `send`, `start`, `status`, `watch`, `collect`, `stop`, `close` |
| `/qargi-project` | the one-time project questionnaire: repository, roles, per-role push policy, the runtime of each surface, models, skills, budget, memory, the members; `project link` |
| `/qargi-instances` | `init`, `list`, `show`, `remove`, `normalize` |
| `/qargi-provision` | `plan`, `apply`, `add-reference` |
| `/qargi-packs` | skills and tools in one library, attached by scope (user, user-role, project, project-role), declared compatible with the runtimes that may use them, reviewed at import, checked for drift |
| `/qargi-providers` | the lead's guide to runtimes: add one with data only, review and seal it, verification and `attest`, extensions, the runtime of each surface |
| `/qargi-memory` | `lint`, `get`, the canon (`check`, `plan`, `apply`, `promote`), the session-start autoload |
| `/qargi-verify` | the coordinator's procedure for verifying and applying returned patches |
| `/qargi-flow` | the lead's git-flow process: features, tasks, releases, hotfixes and resolving conflicts |
| `/qargi-team` | a team on one task: a lead coordinating members for build, write and review; led by this session, a cloud lead, or a lead started in the console |
| `/qargi-session` | the lead's handoff to a fresh session: `qargi marshal handoff` writes the note from stored state, the new session reports what it believes before it does anything |

## Skills and tools in a local Claude Code session

Packs are enabled for a project by links (`qargi skill|tool link NAME --scope project ...`, see `/qargi-packs`). Each pack declares `compatible_providers` (runtime names, family names or `any`; required, and part of the content hash), and a project renders only the packs that match its local runtime: the others are skipped with a note, never attached silently (`--compatible LIST` on `skill|tool new|import|seal`). To use the packs in a Claude Code session on your machine, render them. `qargi packs apply --target claude-code PROJECT` prints a plan and a token; run it again with `--plan TOKEN --approved "<your words>"` to apply (the target is the render target of the project's local runtime).

The apply renders the union of the packs of all the project's roles into `~/.qargi/state/render/PROJECT/RUNTIME/` (RUNTIME is the runtime's name, here `claude-code`; `QARGI_HOME` or `QARGI_STATE` move it): the runtime's skills directory (`.claude/skills` for Claude Code), `mcp.json` and `settings.json` for the tools, and `MANIFEST.json` with the hash of every file. It then prints the launch line that starts Claude Code with the render:

```
claude --add-dir DIR --mcp-config DIR/mcp.json --settings DIR/settings.json
```

(the `--mcp-config` and `--settings` parts appear only when the project has tools). `qargi packs check --target claude-code PROJECT` reports drift (a pack changed since you approved it, or the render no longer matches its manifest) and shadowing (a skill of the same name in `~/.claude/skills` or in the project's own `.claude/skills`, which would override or hide the rendered one). It only reads and changes nothing. A project that was never applied is not a failure: the check says `not applied` and how to apply it, and exits 0. The answer `packs.none: true` says the project uses no project packs; the check then passes with no render (and fails if a pack is linked to a role of the project). Either way the section of the skills a session would load, the unmanaged ones in `~/.claude/skills` included, is still printed.

To load the render without typing the launch line, `qargi packs link PROJECT` makes the repository's `.claude/skills` a symbolic link to it (plan token and approval as for apply): any session opened in that checkout then loads the project's packs. A real `.claude/skills` is moved to `skills.qargi-backup` (nothing is deleted) and `qargi packs unlink PROJECT` puts it back; `packs link` lists which of its skills are new to the library first, and `qargi skill import` brings them in. `.claude` is not tracked, so a new worktree needs its own link. `qargi project link PROJECT [--resource skills,agents,memory]` does the same for the skills, the members and the memory in one plan and one token, each placed the way the runtime's definition says (a directory link, one link per entry, or a copy), and `project unlink` undoes it. `packs check` also lists every skill a session would load that qargi does not manage (`unmanaged`); `qargi skill accept PROJECT NAME` records one you want (for example a skill in `~/.claude/skills`) by name and content hash.

The plan refuses, writing nothing, a skill whose `SKILL.md` name differs from its pack name (or whose front matter is not closed or has two `name` keys), a skill and a tool with the same name, and a tool allowlist name with anything but letters, digits, `_`, `.` and `-`. Concurrent applies serialize on a lock (the second refuses if the render changed meanwhile), and the swap installs only the tree the token approved; the token also covers file modes. `check` also reports a rendered file that differs from the library copy, a mode change, a group- or world-writable render, a malformed manifest, and a manifest for another project or with role scoping other than advisory.

`qargi local prepare` warns too: when the project has a render that has drifted, it prints a WARNING block to stderr with the findings and the fix (`qargi packs apply --target claude-code PROJECT`); the run goes on and its output is unchanged.

- Applying a render writes nothing into a repository or into `~/.claude`: it lives in the state directory only. Only the links you apply (`packs link`, `project link`) put anything in a checkout.
- Role scoping is advisory here: Claude Code cannot hold a session to one role's skills, so the render is the union over the project's roles.
- A member cannot change the render: the guard refuses its writes under `state/render/`. Only you apply it.
- A tool whose pack lists vault credentials (`vault_ids`) cannot authenticate locally; the plan names it and you configure its credentials yourself.

### Baseline packs

qargi ships seven skills of its own in `packs/` (listed in `packs/baseline.json`, one `skills/NAME/SKILL.md` each), written to be portable:

- `shellcheck-gate`: lint every shell file you add or change with shellcheck and quote the verdict among the gates.
- `keep-a-changelog`: record each user-visible change under Unreleased in `CHANGELOG.md`, in the same commit.
- `gitflow-member`: a member's part of a git-flow project (its own `agent/<slug>` branch, no merges, only the checks that cover its change).
- `review-findings`: how a reviewer writes findings (severity order, `file:line`, one-sentence defect, failure scenario, `CONFIRMED` or `PLAUSIBLE`, no patches).
- `secrets-scan`: run a secret scanner over your commits before the report, if one is installed, and quote its verdict among the gates; the lead scans again.
- `docs-site-member`: work on a documentation branch that shares no history with the main branches, based on that branch and never merged into a long-lived one.
- `qargi-contributing`: habits for a member who changes qargi itself (quoting, commit messages, sleep, stash, fail-first tests, shrink-only ceilings, targeted tests).

Install and upgrade add the ones your library lacks with `qargi packs seed --install`, which needs no token and links nothing. `qargi packs seed` shows a plan (one line per pack: `add`, `update`, `current` or `kept`) and a plan token; `--plan TOKEN --approved "<your words>"` applies it, adding missing packs and replacing a copy you never edited when qargi ships a newer text. A copy you edited and sealed, or a pack of your own with the same name, is kept and never overwritten. To take the shipped version of an edited pack again, unlink it, remove it (`qargi skill remove NAME`) and seed.

Seeding never links. To enable a baseline pack for a project: `qargi skill link NAME --scope project --project P`, then render it as above. Not done yet: link proposals when a project is created or attached, user-scope links, and more packs.

## Help, manual page and completion

- `qargi help` lists the commands by task; `qargi help COMMAND` shows its verbs and `qargi help COMMAND VERB` the arguments and options of one. Every command also takes `--help`. `qargi help concepts`, `roles`, `approvals`, `naming`, `memory`, `push`, `files` and `dev` explain the ideas.
- `man qargi` is the complete reference (`qargi help --man | man -l -` if it is not installed).
- Tab completion for bash, zsh and fish offers commands, verbs, options (each once, also as `--option=value`; with a one-line description in zsh and fish) and the values that exist on your machine, each with its description in zsh and fish: your projects (for `lead` and `team`, those that define teams), instances (cloud ones for `start`, `send`, `track`, `instances budget`), sessions narrowed to what the verb can act on (`stop` a running one, `collect` one whose outputs are not downloaded, `close` and `watch` the open ones), a project's teams, roles and packs (skills or tools by command), memory store and deployment ids, model ids, the branches of the project's repository for `--base`, the keys of a project's answers for `project set` with the values each takes, and the usual spend ceilings and wait times. `install.sh --user` installs all three; zsh needs `fpath=(~/.local/share/zsh/site-functions $fpath)` in `~/.zshrc` before `compinit`.
- Inside a project's repository you can leave out the project: `qargi lead status`, `qargi team brief code-docs ...`, `qargi canon check`. A role stands for the instance: `qargi instances show build`. `QARGI_PROJECT` names the project from anywhere. A project you type always wins.

All three, and the checks that keep them true, come from one description of the commands in `lib/commands.py`; `tests/test_help.py` compares it with the scripts. After changing a flag or a verb, describe it there and regenerate the page with `python3 lib/help.py man > man/qargi.1`.

## Members

qargi ships one neutral member definition (`agents/member.json` and its prompt
`agents/member.body.md`) and installs none: you create the members with `qargi agent add`, which
renders it through the project's local runtime. The render is kept in the configuration directory
(`~/.qargi/config/agents/PROJECT/NAME.EXT`, beside `agents.json` and outside every repository) and
written from there to the runtime's agents location, so a checkout that is cleaned or cloned afresh
gets its members back with `qargi agent refresh NAME --project P`; `agent list` names that command
beside a member that is `MISSING`, `STALE` or `DRIFT`. The runtime's definition says how (`renderers.agent`)
and which of its own tools the neutral names (shell, read, edit, write, search, monitor, skill, ...)
become. For Claude Code a member may call `Bash`, `Read`, `Edit`, `Write`,
`Grep`, `Glob`, `Monitor`, `TaskStop`, `ToolSearch` and `Skill`, and every Bash, Edit,
Write and NotebookEdit call passes `qargi __guard` (a runtime states its own hook protocol, or has
none: then a read-only run needs its declared barrier or your acceptance, and `qargi local verify`
is the proof). The guard refuses `git push`, `gh`,
`ssh`, `scp`, `sftp` and changes to a git remote. It also makes review read-only as a
rule rather than a missing tool: a member that only reviews names its class in the hook
command of its definition, and `qargi local prepare --role review` records the role
(as `RUN/ability`) for a member that serves several roles (the guard refuses any
write to that record). Under review the guard refuses an edit outside the run's output
directory and a Bash command that writes into the clone. Whatever the role,
the guard also refuses a member the verbs that change a skill (`qargi skill|tool new`,
`import`, `seal`, `remove`, `link`, `unlink`, `enable`, `disable`, `qargi discover
install`, `qargi packs apply`), the verbs that change a runtime (`qargi provider new|import|seal|remove|enable|disable|attest|accept`),
link a work tree (`qargi project link|unlink`, `qargi packs link|unlink`) or start a command runtime (`qargi local run`),
and any write in the pack library, in `credentials/` or `install.json` of the
configuration directory (not the rest of it), under `state/render`, and in the skills and agents
directories the runtimes declare, outside its clone (for Claude Code `~/.claude/skills`, `.claude/skills`,
`~/.claude/agents` and `~/.claude/plugins`); the `skills/` and `.claude/skills` directories of the repository in
the member's clone stay writable, since they are the work product. The guard fails closed on an
internal error, and the Claude Code member file sets `onFailure: "block"` on the hook (Claude
Code 2.1.295 or later) so that a hook that cannot run blocks the call; frontmatter
hooks of a project-level agent run only once you trust the workspace. So one definition
serves every role; what a role does comes from its role text and the contract, not
from the definition. The guard is a second barrier beside the credential-free git
wrapper; `qargi local verify` remains the proof. A new member is available in Claude
Code sessions started after it is added.

## Choosing models

qargi ships one table (`lib/model-defaults.json`) with two **bases**, one per guard class, and a set of **profiles**. The bases are members: `worker` (roles build, write and test; write class) and `reviewer` (review; read-only). A profile is not a member; it is `{base, tier, effort, purpose}`, resolved at dispatch:

| Profile | Base | Tier | Effort | Purpose |
|---|---|---|---|---|
| `build` | worker | balanced | high | changes the code |
| `write` | worker | balanced | medium | writes the documentation |
| `test` | worker | balanced | low | writes and repairs tests |
| `review` | reviewer | deep | high | judges a change, read-only |
| `auditor` | reviewer | fast | low | checks a diff or a feature in a clone of its own |
| `advisor` | reviewer | deep | high | reviews the lead's synthesized diff before sign-off |
| `researcher` | reviewer | frontier | high | research and design judgment on a hard question; opt-in only |
| `lead` | none | balanced | medium | the lead's own session; never dispatched |

A **tier** (`fast`, `balanced`, `deep`, `frontier`) is mapped by the model catalog of the runtime's family (`lib/providers/catalogs/claude.json` for `claude`) to a full model id for cloud (`claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`) and to an alias for local dispatch (`haiku`, `sonnet`, `opus`, `fable`); a runtime with a single model writes it once for every tier. A project picks the runtime of each surface with `models.provider.local` and `models.provider.cloud` in its answers; there is no default, so a verb that needs a surface (`agent`, `provision`, a read-only `local prepare`, a cloud session, `packs apply --target`) refuses a project that leaves it out (exit 2, naming `qargi project set PROJECT models.provider.SURFACE NAME`), and a name with no definition is refused. `qargi project attach` and `qargi project new` store them with `--provider-local` and `--provider-cloud` (or `--provider NAME` for one name), and nothing without. The `frontier` tier is an opt-in escalation: no default profile except `researcher` uses it, and `researcher` is used only when you or the lead name it for the task.

A project adds or overrides profiles in its answers as `profiles.<name>` (`base`, `tier`, `model`, `effort`, `purpose`, `abilities`, the roles it may serve). A profile whose base class conflicts with its `abilities`, or with the role being dispatched, is refused.

`qargi agent for ROLE [--profile NAME] [--project P] [--json]` prints one line, `MEMBER MODEL EFFORT PROFILE`; MODEL is the alias, or `-` when there is none. The lead spawns the Agent tool with `subagent_type` MEMBER, `model` MODEL (omitted when `-`) and `effort` EFFORT: the call's model and effort override the member definition. `qargi local prepare ... --role R [--profile P]` resolves the profile before it clones anything, records it in `RUN/profile` and prints `PROFILE=`, `MEMBER=`, `MODEL=` and `EFFORT=` (`PROFILE=<role>` without `--profile`). Advisor sign-off uses `--profile advisor` on review, a per-task diff check `--profile auditor`, and `researcher` only when the owner or the lead names it. `qargi agent models [--project P] [--json]` shows the bases, the profiles (the project's merged over the shipped ones) and the members of that project (`--project`, else the project in effect; with neither, exit 2); a member that is not a base is flagged.

Search is not a role: mapping the repository and finding call sites is done by a read-only exploration subagent on a small model inside the lead's context. The lead's own session model is chosen in Claude Code (`/model` or settings), not by qargi; the `lead` profile is the recommendation and the cloud lead's default `lead.model`.

The earlier suggested members auditor, advisor and researcher are profiles now; `qargi agent remove` them if you added them.

Cloud: the four role agents (`<project>-build`, `-write`, `-review`, `-test`) keep working with explicit model ids from the runtime's catalog and the project's answers (`roles.<role>.model` and `effort`). A project can also provision the two bases, `<project>-worker` and `<project>-reviewer`, and start a session of a role and profile on one with `qargi start|send <project>-worker --role build --profile build --asked ...`: the model and effort are overridden for that session (always as a full model object), the role's prompt is rendered for it, and the tools stay those of the base. `qargi agent for ROLE --surface cloud --project P` prints the base it would use; it exits 1 when the base is not registered and 2 when the provider's cloud override capabilities are not verified (a role agent is never chosen for you: start a session on it by its name). A reviewer base needs the project's `qargi provider accept NAME --surface cloud --no-barrier --asked ...` first, because the cloud has no read-only barrier.

## Providers and runtimes

A **runtime** is one way of running agents on one surface (local or cloud), and it is data: a JSON definition (`lib/providers/schema-2.json`) with the models of each tier and the date and source each was verified on, the effort levels it understands, a capability matrix (model and effort overrides at dispatch, a fixed tool list per agent, a read-only barrier, a session budget ceiling, memory stores, skills, MCP), where its skills, agents, MCP file, settings and memory live and how each is linked into a work tree (a directory link, one link per entry, a copy), how a member is written as the runtime's own file, how a member is dispatched, and how a read-only member is held. A **family** groups the runtimes that share a **model catalog**. Claude ships as the family `claude` with the catalog `claude` and two runtimes, `claude-code` (local) and `claude-platform` (cloud). Three kinds of pack share the provider library, `~/.qargi/config/packs/providers/NAME/`: `provider` (a runtime), `catalog` and `extension` (capabilities a project adds to a runtime). `qargi provider list`, `show NAME` and `check NAME` print them, the matrix and what degrades; a project picks one runtime per surface with `models.provider.local` and `models.provider.cloud`, and there is no default.

Add a runtime with no code: `qargi provider new NAME`, edit the definition (CONTRIBUTING has a worked example), `provider check NAME`, `provider seal NAME`, then `qargi project set P models.provider.local NAME`. A command-line runtime is dispatched by `qargi local run RUN` (`--dry-run` prints the argv, the working directory and the prompt): the argv is an array in the definition, never a shell string, and only the environment variables it names reach the process. `provider import SOURCE` takes someone else's pack from a directory, a JSON file or an https git URL. Every change to the library (`new`, `import`, `seal`, `remove`, `enable`, `disable`, `attest`) is a plan, a token and your approval, and a pack with executables also needs `--approve-exec` naming every one. A pack holds text only: scripts you can read, never a compiled program, an archive or a symlink; secrets are refused, opaque blobs and scripts that fetch and run code are flagged, and a vendor CLI is installed by you and only named. An approved executable is code that runs with your rights; the guard does not contain it, so read it before you approve it.

A capability counts only when the definition claims it and it is verified. A shipped definition carries a `verified_on` date for each; a library definition is verified by `provider check` (the hermetic cases: the agent render, the skills link, the read-only corpus through the guard, an adapter's stub), which records it bound to the definition's hash, so an edit or a reseal makes it stale. What no hermetic case can show (an operating-system sandbox that really holds, a real model id) is recorded with `qargi provider attest NAME CAPABILITY`, which runs and spends nothing itself and is asked each time, with the command, the scratch resources, the smallest model, the ceiling and the expected cost stated first. An extension is enabled for one project with `provider enable PROJECT EXTENSION`; two extensions that add the same thing are refused, and what one provides counts only after its own check.

The rules that do not depend on the runtime: a surface whose read-only barrier is not supported cannot serve the review role, unless you accept that for the project with `qargi provider accept NAME --surface S --no-barrier --asked "..."` (it prints a plan and a token, records `models.accept_no_barrier` and writes the audit log); a runtime with no effort control has the effort dropped and `qargi agent models` says so; a runtime without a per-dispatch model override runs the base with its own model, and a profile with another model is refused; and the output of a read-only run is never applied as patches. For `claude-code` the local barrier is the guard hook (partial: shell writes are caught heuristically and `local verify` is the backstop); the cloud review agents of `claude-platform` have no barrier, so a cloud review role needs your acceptance before it is provisioned or started. A runtime that is not a hook runtime holds a read-only member another way (the runtime's own sandbox flags, or an adapter) or not at all, and what qargi guarantees for any runtime is the same: no push, patches reviewed before they are applied, and the class recorded by qargi and not by the task text.

A runtime's adapter (`lib/providers/NAME/adapter`, or a file of the pack) is optional code behind a small JSON contract (`lib/providers/adapter-schema.json`: resolve, dispatch-local, barrier-check, provision, start-session, status, collect, stop, cost; exit 3 for what the definition says is unsupported), and `bash tests/conformance.sh NAME` runs the conformance cases against it, including a corpus of calls a read-only barrier must allow or deny. The `claude-code` adapter has the local verbs, the `claude-platform` adapter the cloud start-session request builder; its other cloud verbs still run through the existing scripts. A data-only runtime has none.

## Splitting, merging and moving memory

A memory store is a directory structure of notes, and `qargi memory` moves notes between two of them. A store is a directory, a `.jsonl` dump (read-only: a source, never a target) or a `memstore_` id; `lib/membackend.py` is the one interface behind all three (the Managed Agents store is reached through `ant`; another backend can be added beside them).

- `qargi memory split FROM TO (--prefix PATH | --role R | --note-kind K) [--archive]` copies the notes the selector picks into `TO`; with `--archive` the originals move to `/_archive/<date>/` in `FROM`.
- `qargi memory copy FROM TO [selector]` copies and leaves `FROM` alone; `qargi memory merge FROM TO` adds every note of `FROM` that `TO` lacks.
- A note that exists on both sides with different content is not overwritten: the incoming one goes to `/_conflicts/<date>/`, as in the reconciler (`--policy keep` leaves it out and reports it instead).

Nothing is ever deleted, and no verb can delete: what leaves a store is archived, and every note written records where it came from by a segment appended to its `Sources:` line (`; copied from NAME:/path@abc123` or `; archived from /path@abc123 on DATE`). So every change can be undone: merging a split's target back into its source moves the archived originals back, byte for byte. A copy from another store is import-only; the source is read, never written.

A note whose name starts with a dot or ends in white space is not a note, and one the target cannot hold (too many path segments, too large for the cloud store) makes the plan refuse, naming the path; narrow the selection with `--prefix`, `--role` or `--note-kind`. `merge` and `copy` without a selector leave the source's `/_archive/` behind.

Each verb prints its plan and a plan token and changes nothing until you run it again with `--plan TOKEN --approved "<your words>"`, which is written to the audit log with the token, the selector and every step (a second line follows when the apply succeeded). A caller's own approval does not stand in for the token. The plan records the digest of every note it read; if an agent wrote to either store in between, the apply is refused before the first change.

## Finding tools

`qargi discover` finds, recommends and installs tools for the roles of a project: skills, MCP servers, packages for the sandbox and built-in tools of the agent.

- `qargi discover search QUERY [--kind K] [--role R] [--online]` searches the reviewed catalog (`catalog/tools.json`) and your library; `--online` adds the official MCP registry and Anthropic's skills repository. Online results are marked as not reviewed.
- `qargi discover recommend [PROJECT] [--role R]` ranks the catalog for each role by the stack it sees in the repository (Go, shell, bats, man pages, Actions, ...) and marks what the role has already.
- `qargi discover show ID` prints an entry: its risk, what it installs and what was verified.
- `qargi discover install ID` asks where it should reach (`user`, `user-role`, `project`, `project-role`) and then uses the existing gates: a skill or an MCP server is imported with its review and your approval of exactly that content, linked at the scope and offered to the cloud agents it reaches (the plan is shown first). A package is added to the role's `apt` list in the project answers; a built-in tool is added to the definitions of the members it reaches. An MCP server from the registry does not list its tools, so you get a draft pack to complete; nothing found online is installed on trust.

## Export and import

`qargi export` writes one archive of what you select, and `qargi import` restores it, on this machine or another:

- **config**: project answers, the instance registry, profiles, the skill and tool library.
- **definitions**: the cloud agents, deployments and environment as they are now, read from the cloud with secret values removed. Import restores them as files; rebuild with `qargi provision`.
- **memories**: every note of the memory and reference stores. Import writes them to the stores named in the project's answers.
- **state**: the session tracker and the audit log (the audit log is only ever appended to).
- **credentials**: token files. Only an encrypted archive may hold them; the tokens in the cloud vault are not exported.

Both ask what to include (or take `--only`/`--project`). Export asks for an optional password; with one the whole archive is encrypted with gpg (AES-256) and the password never appears in a command line (`--password-file` for scripts). Import asks for the password if the archive is encrypted, shows what is inside, asks which parts and projects, and for each part how to treat what exists: `merge` (add what is missing), `overwrite` (also replace what differs) or `replace` (make it match the archive, removing the rest; you must type `replace` to allow the removals). It prints the plan, writes nothing until you confirm, and saves whatever it replaces or removes under `~/.qargi/state/backups/`. The archive is treated as untrusted: names, kinds of entry and checksums are verified before anything is read. `qargi import FILE --dry-run` prints the plan without a terminal.

## Install

```sh
./install.sh --user                    # skills in ~/.claude, command in ~/.local/bin
./install.sh --project /path/to/repo   # skills for one repository only
qargi agent add worker --project P                     # then the read-only base:
qargi agent add reviewer --project P
```

qargi needs Python 3.11 or later (the standard library reads the TOML files some runtimes keep their settings in). The `agent add` lines need a project whose `models.provider.local` is set (see Providers and runtimes).

To set up a checkout of this repository for development, preview with `make -n bootstrap`, install with `make bootstrap` and verify with `make doctor`; see `AGENTS.md`, Development environment.

Both link to this checkout, so `git pull` updates them; add `--copy` for real
files (the whole tool is copied to `~/.local/share/qargi` for `--user`),
`--uninstall` to remove. The install records every path it wrote (links, copied
files, the directories it had to create) in `install.manifest` beside
`install.json`, and `--uninstall` removes exactly those, copies included, and
nothing else: a file of yours inside a copied skill is kept, and so is `~/.qargi`,
unless the install made its `config` directory and nothing else is left in it.
An install made before the manifest existed cannot be told from your own files;
`--uninstall` says so and removes only the fixed paths it writes, and only with
`--force`. An existing real directory is never replaced without `--force`. The
skills directories come from the definition of the runtime whose session loads the
skills (`--runtime NAME`, default `claude-code`: `~/.claude/skills`); a runtime
with none is refused. Install at one level only. The command is
always user-level, so install `--user` before `--project`. The instance
registry, session tracker and profiles are per user, under `~/.qargi/config` and
`~/.qargi/state` (`QARGI_HOME` replaces `~/.qargi`), whichever level installs the skills. Repository rules for
agents go in a profile under `~/.qargi/config/profiles/`, also
outside the repository: nothing qargi related is added to a project's
committed files. `qargi project profile check [NAME] [--profile FILE]` reads the
profile and changes nothing: it exits 1 while the profile still carries the shipped
example's title and "Copy to" line (`project validate` warns of the same), and warns
of a gate command in its Gates section that the repository's `CLAUDE.md`,
`AGENTS.md` and `Makefile` targets do not know. `--project` installs are hidden from git through the
repository's local `.git/info/exclude`.

Installing also adds the baseline packs that ship with qargi (`packs/`) to your pack library, without linking any of them (see Baseline packs).

### Where the data lives

Everything qargi keeps about you is under `~/.qargi`: `config/` (projects, instances, profiles, the pack library of skills, tools and provider packs, credentials, `install.json`) and `state/` (the session tracker, the audit log, runs, backups, the renders under `render/`, the provider verification records). `QARGI_HOME` replaces the root; `QARGI_CONF` and `QARGI_STATE` name either directory and win over it. `XDG_CONFIG_HOME` and `XDG_STATE_HOME` are not used (the `ant` CLI keeps its login there).

### Running a branch checkout

`install.sh --user` records the tool it installed in `~/.qargi/config/install.json`. A checkout run from anywhere else, for example `bin/qargi` in a worktree, is then a dev run: it keeps its data in `<checkout>/.qargi` (ignored by git), prints `qargi: dev run from ...; data in ...` on stderr once per command, and never touches your live projects, credentials or audit log. The installed copy (for example `/opt/qargi`) is for confirming committed work and managing live projects, and never writes into its own directory. Without `install.json` a checkout behaves as the installed one. To point a dev run at live data on purpose set `QARGI_HOME=~/.qargi`; any explicit `QARGI_HOME`, `QARGI_CONF` or `QARGI_STATE` overrides the sandbox. Members call `qargi __guard` and the hooks from `PATH`, which is the installed copy: put `<checkout>/bin` first on `PATH` to test a branch's guard or hooks.

## Cloud (ant) profiles per project

`qargi cloud set PROJECT --profile NAME --workspace-id wrkspc_...` binds a project to an `ant` profile and the workspace it must
reach; `qargi cloud login PROJECT` logs that profile in on your terminal, and `qargi cloud check` verifies it. `qargi cloud list` and `show`
print the bindings, and `qargi cloud unset PROJECT` removes one. (These are `ant` profiles; the model profiles of a base session are
described under Choosing models.) From then on every
command about the project runs `ant` under that profile and refuses to touch another workspace. Without a binding, `ant`'s
active profile is used.

## Upgrading the installed tool

`qargi upgrade --branch develop` fetches that branch of the installed checkout's origin (for example `/opt/qargi`), shows the commits and files that would change and prints a plan token; `qargi upgrade --branch develop --plan TOKEN --approved "..."` applies exactly that (fast-forward only on the current branch, `--tag T` for a tag), re-runs `install.sh --user` and lists the members to refresh. When `~/.qargi/config/agents.json` is in an earlier shape, which every `qargi agent` verb refuses, the plan and the end of the upgrade warn about it and say to move it aside and add the members again with `qargi agent add NAME --project P`; the upgrade itself does not touch it. The git commands that write into the root-owned checkout run through `sudo`.

Status: pre-release, see [CHANGELOG.md](CHANGELOG.md). Licensed under the MIT
license, see [LICENSE](LICENSE).

Copyright (c) 2026 Everett C. Haimes III
