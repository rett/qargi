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

Two kinds of agent do the work:

- **local**: a **member**, a Claude Code subagent you name, working in a scratch clone.
- **cloud**: a Claude Managed Agents deployment of one role, registered as an instance and
  driven through the `ant` CLI.

A **lead** coordinates members on one task (a team): this session, a cloud lead or a lead
started in the console.

Local is the default. Cloud is used only when the user asks for it in that
request.

## Naming convention

Every name follows from the project, so resources are identifiable at a glance.

| Thing | Name | Example |
|---|---|---|
| project | one lower-case token (letters, digits) | `myproject` |
| role | an ability (`build`, `write`, `review`, `test`) or `lead` | `build` |
| member (local agent) | any kebab-case name you choose | `forge` |
| instance (registry) | `<project>-<role>` | `myproject-build` |
| cloud agent | `<project>-<role>` | `myproject-build` |
| environment (shared by the roles) | `<project>-environment` | `myproject-environment` |
| deployment | `<project>-deployment-<role>` | `myproject-deployment-build` |
| memory stores (project-level) | `<project>-memory` (recipes), `<project>-reference` | `myproject-memory` |
| memory folders | `shared/`, `roles/<role>/` | `roles/build/` |
| session | `<instance>-<task-slug>` | `myproject-build-dots-in-usernames` |
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

## Roles, abilities and members

A role is named by its activity. Each of the four abilities is defined by the text
of its role, `roles/<role>/ROLE.md`, the single source: a member gets that text with the
task block (`qargi local prepare` writes it, as `qargi role prompt ROLE` prints it) and a
cloud agent of that role carries it in its prompt. A member keeps the Skill tool for the
packs attached to it, not for its ability:

| Role | Ability | Defined by | What it does |
|---|---|---|---|
| `build` | build | `roles/build/ROLE.md` | changes the code with its tests, manual page, help and changelog |
| `write` | write | `roles/write/ROLE.md` | writes the operational documentation on its own branch |
| `review` | review | `roles/review/ROLE.md` | reads a change, runs its checks and reports a verdict; changes no file |
| `test` | test | `roles/test/ROLE.md` | writes and repairs tests, proves them failing first and stable |
| `lead` | (coordinates) | `/qargi-team` | runs a team of members on one task |

The members are yours to name: `qargi agent add forge --abilities build,test` renders
the one member definition qargi ships into `~/.claude/agents/forge.md` (`--project
NAME` puts it in that repository, hidden from git), with the abilities it serves (all
four by default; `worker` and `reviewer`, the two base names, default to their base's abilities). Two base members cover
the two guard classes: `worker` (build, write and test; write class) and `reviewer` (review; read-only). Models and efforts
come from profiles, not from more members (see Choosing models). `qargi agent for build` prints one line,
`MEMBER MODEL EFFORT PROFILE`, and dispatch spawns that member with that model and effort; `qargi agent list`, `rename`,
`refresh` (re-render from the current definition) and `remove` manage the members. A member named otherwise (builder, writer,
tester, or any one-per-ability member) still resolves when no base exists and is flagged by `qargi agent models`.

A role is a directory with `role.json` (its class, write or read-only, and a description) and
`ROLE.md` (its instructions). The four above ship with qargi; `review` is read-only. Add your own
under `~/.qargi/config/roles/NAME/` (one lower-case token, never `lead`). The class decides what the
guard allows; the text of a role cannot change it. `qargi role list` shows the roles and where they
live, `role show NAME` prints one, `role prompt NAME` prints its instructions as a task block carries
them, and `role check [NAME]` validates one role or all. `qargi local prepare --role ROLE` prepares a
local run for that role (default `build`): a read-only role keeps the clone unchanged.

Installations made with the earlier names (roles `dev` and `docs`, the fixed agents
`qargi-dev`, `qargi-docs`, `qargi-review`, `qargi-test`, cloud agents named
`<project>-agent-<role>`) move to these with `qargi migrate roles`: it prints a plan
with every cloud call and a plan token, and applies exactly that plan with `--apply
--plan TOKEN --asked "<your words>"`.

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

Both print a plan and a token; they write only when you apply it with `--plan TOKEN --approved "<your
words>"` (`qargi help approvals`).

## Git-flow

A project that follows `gitflow` is driven by the lead with `qargi feature` and `qargi release`
(the `/qargi-flow` skill has the full process). Every merge is `--no-ff`, made in temporary
worktrees: your checkout is never touched, a branch moves only after every merge succeeded, and a
refusal changes nothing.

1. `qargi feature start NAME --purpose "..."` cuts `feature/NAME` from develop. A feature is a broad
   theme; `qargi feature list` shows the open ones and the files two of them both change.
2. Tasks run on `agent/<slug>` (`/qargi-task ... --base feature/NAME`) with targeted checks only.
   Per task: `qargi review check RUN` and `qargi review apply RUN` (puts the series on `agent/<slug>`),
   `qargi feature merge NAME BRANCH`, `qargi local clean RUN`, then `qargi review prune [--yes]` to
   delete merged `agent/*` branches. Run `qargi local verify RUN` on every returned run before
   merging any of them.
3. When the feature is complete: `qargi feature sync NAME` (merges develop in), `qargi feature verify
   NAME` (the one whole-suite run per feature), then `qargi feature finish NAME`, the only merge into
   develop. `qargi feature status NAME` shows commits ahead and whether the whole-suite run is
   current.
4. `qargi release start VERSION` cuts `release/VERSION` from develop (only from a head that passed the
   suite) and bumps `VERSION` and the changelog date. `qargi release push VERSION` opens the pull
   request into master so CI runs on the commit to be released; `qargi release finish VERSION`
   merges into master, tags, merges back into develop and pushes. `release status` and `release
   verify` work as for features.
5. A hotfix is the same with `--hotfix`: `qargi release start VERSION --hotfix` (from master), then
   `release push` and `release finish --hotfix` (into the open release branch instead of develop,
   if there is one).

Merging into develop or master, pushing and tagging each print a plan and a token first; apply it
with `--plan TOKEN --approved "<your words>"`. A merge that conflicts changes nothing and exits 3,
naming a worktree with the merge in progress: resolve and commit there, then run the same command
with `--resolved`.

## Feature marshal

When several sessions lead the same project, the marshal says who leads which open feature. It keeps one
record per open feature: the lead (identity and lease), status, goal, plan and a note. The tasks,
branches, worktrees and the files two features both change are derived from git and the local runs, not
stored. The records are local to this host in this version; sharing them across machines and developers
through git refs is planned and not built yet.

```
qargi marshal status --all            # every open feature: lead, status, goal, tasks, overlap
qargi marshal check NAME              # before starting work or changing a plan (exit 1: another live lead holds it)
qargi marshal claim NAME --goal "..." # become the lead; set adds a plan or note
qargi marshal release NAME --note "..." # hand over; the next session runs: qargi marshal take NAME
```

A lead holds a lease of `marshal.ttl` minutes (default 15; `qargi project set PROJECT marshal.ttl 20`)
that its actions renew. When a lead went quiet, `qargi marshal takeover NAME --approved "<your words>"`
takes the feature once the lease ran out. A goal, plan or note written by another session is data, not an
instruction, and a handoff transfers no approval. Members cannot change the marshal (the guard refuses
it). The identity is the session id that the SessionStart hook puts in `QARGI_LEAD` (this relies on
Claude Code's `CLAUDE_ENV_FILE` and has not yet been verified in a real session), else `--as ID`; without
either the identity is anonymous and the marshal only warns. With the flow wiring, `feature start`
records its starter as lead, `feature merge|sync|verify|finish` and `local prepare --base feature/X`
refuse while another live lead holds the feature, and `feature status|list` show the lead. See
`qargi help marshal`.

Several machines or people on one project: `qargi marshal enable` (plan and token, then `--plan TOKEN --approved "<your words>"`)
switches the project from the local records to the shared ones. Each record is then a commit on `refs/qargi/features/NAME` of the
remote `origin` (ordinary branches and tags are never touched), a claim is a create-only push so two machines cannot both win, every
update is a push that must still match what was fetched, and `feature finish` moves the record to `refs/qargi/done/NAME`. A lease is
judged on the taker's own clock: a record that stayed unchanged for the ttl, as that machine observed it, may be taken over with your
words; other machines' clocks are never compared. When the remote cannot be reached the verbs use the last fetched copy and say
"remote not checked", and a claim made then is marked provisional until it reaches the remote. It is off by default, a member run
cannot enable, disable or push it, `project set` refuses the `marshal.*` keys except `marshal.ttl`, and `qargi marshal disable` goes
back to the local records (the refs on the remote stay). Whether your Git host accepts the `refs/qargi/*` namespace is yours to check
on a scratch repository before enabling it on a real one.

Records can also be signed so a forged or rewound record is detected: `qargi marshal key init` makes this machine's ssh key and prints its
signers line, `qargi marshal signers add --line ...` trusts a key (on every lead machine; the list lives in your state directory, never in the
repository), and `qargi marshal enable --integrity advisory|strict` chooses how readers treat records that are unsigned or not signed by a
trusted key (advisory tags them, strict ignores them). Move from advisory to strict with `qargi marshal resign NAME` for each open record.
Signing cannot stop someone with push access from deleting a ref; it makes forged and altered records visible and attributable to a key.


## Skills and command

Twelve skills, all prefixed `qargi-`, drive one `qargi` command. `/qargi-task` dispatches work; four define the abilities (above); the others configure and manage:

| Skill | Covers |
|---|---|
| `/qargi-task` | dispatch (`/qargi-task "<task>" --done "<check>"`) and session lifecycle: `send`, `start`, `status`, `watch`, `collect`, `stop`, `close` |
| `/qargi-project` | the one-time project questionnaire: repository, roles, per-role push policy, models, skills, budget, memory, the members |
| `/qargi-instances` | `init`, `list`, `show`, `remove`, `normalize` |
| `/qargi-provision` | `plan`, `apply`, `add-reference` |
| `/qargi-packs` | skills and tools in one library, attached by scope (user, user-role, project, project-role), reviewed at import, checked for drift |
| `/qargi-memory` | `lint`, `get`, the canon (`check`, `plan`, `apply`, `import`, `promote`), the session-start autoload |
| `/qargi-verify` | the coordinator's procedure for verifying and applying returned patches |
| `/qargi-flow` | the lead's git-flow process: features, tasks, releases, hotfixes and resolving conflicts |
| `/qargi-team` | a team on one task: a lead coordinating members for build, write and review; led by this session, a cloud lead, or a lead started in the console |

## Skills and tools in a local Claude Code session

Packs are enabled for a project by links (`qargi skill|tool link NAME --scope project ...`, see `/qargi-packs`). To use them in a Claude Code session on your machine, render them. `qargi packs apply --target claude-code PROJECT` prints a plan and a token; run it again with `--plan TOKEN --approved "<your words>"` to apply.

The apply renders the union of the packs of all the project's roles into `~/.qargi/state/claude/PROJECT/` (`QARGI_HOME` or `QARGI_STATE` move it): the skills under `.claude/skills`, `mcp.json` and `settings.json` for the tools, and `MANIFEST.json` with the hash of every file. It then prints the launch line that starts Claude Code with the render:

```
claude --add-dir DIR --mcp-config DIR/mcp.json --settings DIR/settings.json
```

(the `--mcp-config` and `--settings` parts appear only when the project has tools). `qargi packs check --target claude-code PROJECT` reports drift (a pack changed since you approved it, or the render no longer matches its manifest) and shadowing (a skill of the same name in `~/.claude/skills` or in the project's own `.claude/skills`, which would override or hide the rendered one). It only reads and changes nothing.

The plan refuses, writing nothing, a skill whose `SKILL.md` name differs from its pack name (or whose front matter is not closed or has two `name` keys), a skill and a tool with the same name, and a tool allowlist name with anything but letters, digits, `_`, `.` and `-`. Concurrent applies serialize on a lock (the second refuses if the render changed meanwhile), and the swap installs only the tree the token approved; the token also covers file modes. `check` also reports a rendered file that differs from the library copy, a mode change, a group- or world-writable render, a malformed manifest, and a manifest for another project or with role scoping other than advisory.

`qargi local prepare` warns too: when the project has a render that has drifted, it prints a WARNING block to stderr with the findings and the fix (`qargi packs apply --target claude-code PROJECT`); the run goes on and its output is unchanged.

- Nothing is written into a repository or into `~/.claude`; the render lives in the state directory only.
- Role scoping is advisory here: Claude Code cannot hold a session to one role's skills, so the render is the union over the project's roles.
- A member cannot change the render: the guard refuses its writes under `state/claude/`. Only you apply it.
- A tool whose pack lists vault credentials (`vault_ids`) cannot authenticate locally; the plan names it and you configure its credentials yourself.

### Baseline packs

qargi ships three skills of its own in `packs/` (listed in `packs/baseline.json`, one `skills/NAME/SKILL.md` each), written to be portable:

- `shellcheck-gate`: lint every shell file you add or change with shellcheck and quote the verdict among the gates.
- `keep-a-changelog`: record each user-visible change under Unreleased in `CHANGELOG.md`, in the same commit.
- `gitflow-member`: a member's part of a git-flow project (its own `agent/<slug>` branch, no merges, only the checks that cover its change).

Install and upgrade add the ones your library lacks with `qargi packs seed --install`, which needs no token and links nothing. `qargi packs seed` shows a plan (one line per pack: `add`, `update`, `current` or `kept`) and a plan token; `--plan TOKEN --approved "<your words>"` applies it, adding missing packs and replacing a copy you never edited when qargi ships a newer text. A copy you edited and sealed, or a pack of your own with the same name, is kept and never overwritten. To take the shipped version of an edited pack again, unlink it, remove it (`qargi skill remove NAME`) and seed.

Seeding never links. To enable a baseline pack for a project: `qargi skill link NAME --scope project --project P`, then render it as above. Not done yet: link proposals when a project is created or attached, user-scope links, and more packs.

## Help, manual page and completion

- `qargi help` lists the commands by task; `qargi help COMMAND` shows its verbs and `qargi help COMMAND VERB` the arguments and options of one. Every command also takes `--help`. `qargi help approvals`, `naming`, `memory`, `push`, `concepts` and `files` explain the ideas.
- `man qargi` is the complete reference (`qargi help --man | man -l -` if it is not installed).
- Tab completion for bash, zsh and fish offers commands, verbs, options (each once, also as `--option=value`; with a one-line description in zsh and fish) and the values that exist on your machine, each with its description in zsh and fish: your projects (for `lead` and `team`, those that define teams), instances (cloud ones for `start`, `send`, `track`, `instances budget`), sessions narrowed to what the verb can act on (`stop` a running one, `collect` one whose outputs are not downloaded, `close` and `watch` the open ones), a project's teams, roles and packs (skills or tools by command), memory store and deployment ids, model ids, the branches of the project's repository for `--base`, the keys of a project's answers for `project set` with the values each takes, and the usual spend ceilings and wait times. `install.sh --user` installs all three; zsh needs `fpath=(~/.local/share/zsh/site-functions $fpath)` in `~/.zshrc` before `compinit`.
- Inside a project's repository you can leave out the project: `qargi lead status`, `qargi team brief code-docs ...`, `qargi canon check`. A role stands for the instance: `qargi instances show build`. `QARGI_PROJECT` names the project from anywhere. A project you type always wins.

All three, and the checks that keep them true, come from one description of the commands in `lib/commands.py`; `tests/test_help.py` compares it with the scripts. After changing a flag or a verb, describe it there and regenerate the page with `python3 lib/help.py man > man/qargi.1`.

## Members

qargi ships one member definition (`agents/member.md`) and installs none: you create
the members with `qargi agent add`. A member may call `Bash`, `Read`, `Edit`, `Write`,
`Grep`, `Glob`, `Monitor`, `TaskStop`, `ToolSearch` and `Skill`, and every Bash, Edit,
Write and NotebookEdit call passes `qargi __guard`. The guard refuses `git push`, `gh`,
`ssh`, `scp`, `sftp` and changes to a git remote. It also makes review read-only as a
rule rather than a missing tool: a member that only reviews names its class in the hook
command of its definition, and `qargi local prepare --ability review` records the ability
in the run directory for a member that serves several abilities (the guard refuses any
write to that record). Under review the guard refuses an edit outside the run's output
directory and a Bash command that writes into the clone. Whatever the ability,
the guard also refuses a member the verbs that change a skill (`qargi skill|tool new`,
`import`, `seal`, `remove`, `link`, `unlink`, `enable`, `disable`, `qargi discover
install`, `qargi packs apply`) and any write in the pack library, in `credentials/` or `install.json` of the
configuration directory (not the rest of it), in `~/.claude/skills` or
a `.claude/skills` directory outside its clone (also `~/.claude/agents` and
`~/.claude/plugins`); the `skills/` and `.claude/skills` directories of the repository in
the member's clone stay writable, since they are the work product. The guard fails closed on an
internal error, and the member definition sets `onFailure: "block"` on the hook (Claude
Code 2.1.295 or later) so that a hook that cannot run blocks the call; frontmatter
hooks of a project-level agent run only once you trust the workspace. So one definition
serves every ability; what an ability does comes from its role text and the contract, not
from the definition. The guard is a second barrier beside the credential-free git
wrapper; `qargi local verify` remains the proof. A new member is available in Claude
Code sessions started after it is added.

## Choosing models

qargi ships one table (`lib/model-defaults.json`) with two **bases**, one per guard class, and a set of **profiles**. The bases are members: `worker` (abilities build, write and test; write class) and `reviewer` (review; read-only). A profile is not a member; it is `{base, tier, effort, purpose}`, resolved at dispatch:

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

A **tier** (`fast`, `balanced`, `deep`, `frontier`) is mapped by `lib/providers/claude.json` to a full model id for cloud and for the template (`claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`) and to an alias for local dispatch (`haiku`, `sonnet`, `opus`, `fable`). A project picks the provider with `models.provider` in its answers (default `claude`); a name without a file under `lib/providers/` is refused. Another provider needs its own file there, and until a backend for it exists the file is reference data only. The `frontier` tier is an opt-in escalation: no default profile except `researcher` uses it, and `researcher` is used only when you or the lead name it for the task.

A project adds or overrides profiles in its answers as `profiles.<name>` (`base`, `tier`, `model`, `effort`, `purpose`, `abilities`). A profile whose base class conflicts with its abilities, or with the role being dispatched, is refused.

`qargi agent for ROLE [--profile NAME] [--project P] [--json]` prints one line, `MEMBER MODEL EFFORT PROFILE`; MODEL is the alias, or `-` when there is none. The lead spawns the Agent tool with `subagent_type` MEMBER, `model` MODEL (omitted when `-`) and `effort` EFFORT: the call's model and effort override the member definition. `qargi local prepare ... --role R [--profile P]` resolves the profile before it clones anything, records it in `RUN/profile` and prints `PROFILE=`, `MEMBER=`, `MODEL=` and `EFFORT=` (`PROFILE=<role>` without `--profile`). Advisor sign-off uses `--profile advisor` on review, a per-task diff check `--profile auditor`, and `researcher` only when the owner or the lead names it. `qargi agent models [--project P] [--json]` shows the bases, the profiles (the project's merged over the shipped ones) and the members; members that predate the bases are flagged as legacy.

Search is not a role: mapping the repository and finding call sites is done by a read-only exploration subagent on a small model inside the lead's context. The lead's own session model is chosen in Claude Code (`/model` or settings), not by qargi; the `lead` profile is the recommendation and the cloud lead's default `lead.model`.

Moving from one-per-ability members: `qargi agent add worker` and `qargi agent add reviewer` (each defaults to its base's abilities), `qargi agent models` to see the legacy members flagged, then retire builder, writer and tester with `qargi agent remove`. The earlier suggested members auditor, advisor and researcher are profiles now; `qargi agent remove` them if you added them.

Cloud: the four role agents (`<project>-build`, `-write`, `-review`, `-test`) keep working with explicit model ids from the provider file and the project's answers (`roles.<role>.model` and `effort`). A project can also provision the two bases, `<project>-worker` and `<project>-reviewer`, and start a session of a role and profile on one with `qargi start|send <project>-worker --role build --profile build --asked ...`: the model and effort are overridden for that session (always as a full model object), the role's prompt is rendered for it, and the tools stay those of the base. `qargi agent for ROLE --surface cloud --project P` prints the instance it would use; a base is used only when registered and the provider's cloud override capabilities are verified, otherwise the role agent serves and a profile that needs a different model is refused. A reviewer base needs the project's `qargi provider accept NAME --surface cloud --no-barrier --asked ...` first, because the cloud has no read-only barrier.

## Providers

A provider is a descriptor, `lib/providers/NAME.json`, and every provider uses the same schema (`lib/providers/schema.json`): the model each tier (fast, balanced, deep, frontier) maps to, each with the date and source it was verified on; the effort levels it understands; the surfaces it serves (local, cloud); and a capability matrix per surface (model and effort overrides at dispatch, a fixed tool list per agent, a read-only barrier, a session budget ceiling, memory stores, skills, MCP). A capability that has no verification date counts as not supported. `qargi provider list`, `show NAME` and `check NAME` print the descriptors, the matrix and what degrades; a project picks its provider with `models.provider` in its answers (default `claude`).

The rules that do not depend on the provider: a surface whose read-only barrier is not supported cannot serve the review role, unless you accept that for the project with `qargi provider accept NAME --surface S --no-barrier --asked "..."` (it prints a plan and a token, records `models.accept_no_barrier` and writes the audit log); a provider with no effort control has the effort dropped and `qargi agent models` says so; a provider without a per-dispatch model override must have one member per profile; and the output of a read-only run is never applied as patches. For the bundled `claude` descriptor the local barrier is the guard hook (partial: shell writes are caught heuristically and `local verify` is the backstop); the cloud review agents have no barrier, so a cloud review role needs your acceptance before it is provisioned or started.

A provider's adapter (`lib/providers/NAME/adapter`) implements a small JSON contract (resolve, dispatch-local, barrier-check, provision, start-session, status, collect, stop, cost; exit 3 for what the descriptor says is unsupported), and `bash tests/conformance.sh NAME` runs the conformance cases against it, including a corpus of calls a read-only barrier must allow or deny. Only the local verbs of the `claude` adapter exist so far; its cloud verbs still run through the existing scripts.

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
  An archive made with the earlier role names (`dev`, `docs`) is imported under the current ones.
- **definitions**: the cloud agents, deployments and environment as they are now, read from the cloud with secret values removed. Import restores them as files; rebuild with `qargi provision`.
- **memories**: every note of the memory and reference stores. Import writes them to the stores named in the project's answers.
- **state**: the session tracker and the audit log (the audit log is only ever appended to).
- **credentials**: token files. Only an encrypted archive may hold them; the tokens in the cloud vault are not exported.

Both ask what to include (or take `--only`/`--project`). Export asks for an optional password; with one the whole archive is encrypted with gpg (AES-256) and the password never appears in a command line (`--password-file` for scripts). Import asks for the password if the archive is encrypted, shows what is inside, asks which parts and projects, and for each part how to treat what exists: `merge` (add what is missing), `overwrite` (also replace what differs) or `replace` (make it match the archive, removing the rest; you must type `replace` to allow the removals). It prints the plan, writes nothing until you confirm, and saves whatever it replaces or removes under `~/.qargi/state/backups/`. The archive is treated as untrusted: names, kinds of entry and checksums are verified before anything is read. `qargi import FILE --dry-run` prints the plan without a terminal.

## Install

```sh
./install.sh --user                    # skills in ~/.claude, command in ~/.local/bin
./install.sh --project /path/to/repo   # skills for one repository only
qargi agent add worker                       # then the read-only base:
qargi agent add reviewer
```

Both link to this checkout, so `git pull` updates them; add `--copy` for real
files (the whole tool is copied to `~/.local/share/qargi` for `--user`),
`--uninstall` to remove (copies need `--force`). An existing real directory is
never replaced without `--force`. Install at one level only. The command is
always user-level, so install `--user` before `--project`. The instance
registry, session tracker and profiles are per user, under `~/.qargi/config` and
`~/.qargi/state` (`QARGI_HOME` replaces `~/.qargi`), whichever level installs the skills. Repository rules for
agents go in a profile under `~/.qargi/config/profiles/`, also
outside the repository: nothing qargi related is added to a project's
committed files. `--project` installs are hidden from git through the
repository's local `.git/info/exclude`.

Installing also adds the baseline packs that ship with qargi (`packs/`) to your pack library, without linking any of them (see Baseline packs).

### Where the data lives

Everything qargi keeps about you is under `~/.qargi`: `config/` (projects, instances, profiles, the pack library, credentials, `install.json`) and `state/` (the session tracker, the audit log, runs, backups). `QARGI_HOME` replaces the root; `QARGI_CONF` and `QARGI_STATE` name either directory and win over it. `XDG_CONFIG_HOME` and `XDG_STATE_HOME` are not used (the `ant` CLI keeps its login there).

An earlier version kept the data in `~/.config/qargi` and `~/.local/state/qargi`. While only those exist, every command except `help`, `version`, the completion, the guard and the run-event hooks stops and tells you to run `qargi migrate home`. It prints the plan (every file, mode and digest, and the files whose old paths it rewrites; the records `audit.log`, `supervisor.log` and `run-events/` are copied byte for byte) and a token; with `--plan TOKEN --approved "<words>"` it copies, checks every file by digest and leaves the old directories untouched as a backup. It never creates an empty `~/.qargi` next to old data.

### Running a branch checkout

`install.sh --user` records the tool it installed in `~/.qargi/config/install.json`. A checkout run from anywhere else, for example `bin/qargi` in a worktree, is then a dev run: it keeps its data in `<checkout>/.qargi` (ignored by git), prints `qargi: dev run from ...; data in ...` on stderr once per command, and never touches your live projects, credentials or audit log. The installed copy (for example `/opt/qargi`) is for confirming committed work and managing live projects, and never writes into its own directory. Without `install.json` a checkout behaves as the installed one. To point a dev run at live data on purpose set `QARGI_HOME=~/.qargi`; any explicit `QARGI_HOME`, `QARGI_CONF` or `QARGI_STATE` overrides the sandbox, and `qargi migrate home` refuses in a dev run unless one of them is set. Members call `qargi __guard` and the hooks from `PATH`, which is the installed copy: put `<checkout>/bin` first on `PATH` to test a branch's guard or hooks.

## Cloud profiles per project

`qargi cloud set PROJECT --profile NAME --workspace-id wrkspc_...` binds a project to an `ant` profile and the workspace it must
reach; `qargi cloud login PROJECT` logs that profile in on your terminal, and `qargi cloud check` verifies it. From then on every
command about the project runs `ant` under that profile and refuses to touch another workspace. Without a binding, `ant`'s
active profile is used.

## Upgrading the installed tool

`qargi upgrade --branch develop` fetches that branch of the installed checkout's origin (for example `/opt/qargi`), shows the commits and files that would change and prints a plan token; `qargi upgrade --branch develop --plan TOKEN --approved "..."` applies exactly that (fast-forward only on the current branch, `--tag T` for a tag), re-runs `install.sh --user` and lists the members to refresh. The git commands that write into the root-owned checkout run through `sudo`.

Status: pre-release, see [CHANGELOG.md](CHANGELOG.md). Licensed under the MIT
license, see [LICENSE](LICENSE).
