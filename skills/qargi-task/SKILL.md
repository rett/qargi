---
name: qargi-task
description: Dispatch a one-off, task-scoped development task to a member (a local subagent you named) or a registered cloud instance (Managed Agents deployment) with /qargi-task "<task>" --done "<check>", and manage its sessions: send, start, status, watch, collect, stop, close. Agents work in their own clone, return patches, never push. Local is the default; cloud only when the user's request names a cloud instance.
argument-hint: "<task>" --done "<check>" [--instance NAME] [--base B] [--scope PATHS] | send|start|status|watch|collect|stop|close ...
---

# /qargi-task (dispatch and session lifecycle)

A **role** says what a task is for (`qargi role list`): build, write, review and test ship with
qargi, and you can add your own (`~/.qargi/config/roles/NAME/` with `role.json` and `ROLE.md`). Its
**class** (write or read-only) is what the guard enforces; its text cannot change that. A **member** is a
local agent you named and gave roles (`qargi agent add`), written by the project's local runtime from
one member definition (`/qargi-instances`); an **instance** is a registered cloud agent of
one role (see `/qargi-instances`). All
of them obey the contract in `contract/contract.md`: one task,
own clone, patches back, never push, no backlog. The CLI is `qargi` on
PATH; related skills: `/qargi-instances` (register, list), `/qargi-provision`
(create cloud resources), `/qargi-memory` (memory stores), `/qargi-verify`
(verify and apply returned patches).

A task whose change affects usage may be run as a team (a lead and members for build, write and
review): see `/qargi-team`. Teams are opt-in and chosen by the user for the task.

## Quick form

`/qargi-task "<task>" --done "<executable check>" [--role ROLE] [--instance NAME] [--base BRANCH] [--scope PATHS]`

If the first argument is not one of the session verbs (`send`, `start`, `status`, `watch`, `collect`, `stop`, `close`: cloud.md), it is a task: build the
task block (see below) and send it to the instance, which defaults to the
member that serves the task's role (`qargi agent for ROLE`, whose first word is the member). `--role` defaults to build; take it from the
user's words (a review, tests, documentation, or a role they named). A cloud instance only when the
user's request named it.

## Hard rules

- **Cloud only when the user asks**: load cloud.md when the user's request names a cloud instance. Never choose cloud on your own or fall back between local and cloud: report instead.
- Local is the default. With no instance named, use the member `qargi agent for ROLE [--profile NAME]` prints (its first word).
- Agents never push.
- An approval applies to the plan the user saw. Plans print a `plan token`; the matching
  apply (`provision apply`, `canon apply|import`, `instances normalize`, an agent update)
  must be given `--plan TOKEN` and refuses if the plan has changed. Never allow-list these
  verbs in the Claude Code settings: the permission prompt is the user's real control.
  Every gated verb is also logged in `~/.qargi/state/audit.log`.
- Every submitted patch is reviewed (`/qargi-verify`) before it is applied, and it is applied as
  separate, change-specific commits, never squashed. The agent commits as it goes and returns
  one patch per commit (with each commit's reasoning in its message), grouped by the change
  they implement, never one combined patch; `qargi review check RUN_DIR` verifies it. The
  agent advises how its work should be committed; the coordinator decides.

## Task block

ROLE (`ROLE: build (class write)`; the class is `qargi role show ROLE`'s), ROLE_TEXT (locally the output of
`qargi role prompt ROLE`, inlined; a cloud agent has it in its system prompt), TASK, DONE (executable check; if the user
gave prose, get an executable form first), PROFILE (the text of the repository's profile, inlined), BASE (default:
the dispatching session's branch; explicit if that is master or develop), base
SHA, SCOPE (hard limit, optional), OUT (a cloud run's: cloud.md), CLONE, TMP (local runs: `prepare`'s).

## Profiles (kept outside the repository)

A profile holds a repository's gates, rules and coordinator review steps. It
lives under the user's config directory, never in the project:
`~/.qargi/config/profiles/<name>.md`, where `<name>` is the
repository directory's name. No command reads it: before a `send`, the
coordinator reads the file itself and inlines its text as PROFILE. (`--profile`
on `start`, `send` and `local prepare` is the model profile of the role, not
this file.) No profile is fine. Nothing
qargi related is ever added to a project's committed files.

## Local flow (default)

The local agent gets no way to push, and you check afterwards that it did not.

1. `qargi local prepare --repo <repo> --base <base> --slug <slug> --scratch <scratchpad> --role <role> [--profile <profile>]`
   makes a bare copy of the repository with no remote, a clone of that copy on
   `agent/<slug>` (push URL disabled), an output directory, and a `git` wrapper that
   runs with no credentials (no home, no global config, no ssh, no prompts). It resolves the profile before it
   clones anything, records it in `RUN/profile` and prints `PROFILE`, `MEMBER`, `MODEL` and `EFFORT` (`PROFILE=<role>` without
   `--profile`): spawn that member with that model and effort, so step 2 can use those values. It also prints
   `RUN`, `ROLE`, `CLASS`, `CLONE`, `OUT`, `TMP`, `GIT` and `BASE_SHA`, then, after a blank line, a `TASK-BLOCK PATHS` block
   to paste into the task block exactly as printed, then (inside a registered project) a `TASK-BLOCK MEMORY` block
   to paste in the same way: it lists the memory tiers (the repo tier as the clone's committed copy), the role's
   always-load notes, and the rule that the executor writes no tier and proposes notes in its report
   for the lead to file. When the repo tier has uncommitted changes in your checkout it adds a warning (also on
   stderr): the executor sees only the committed copy, so commit them first if it needs them. Nothing is stored; a
   failure prints nothing and does not change `prepare`'s result. It records every ref of the real
   repository and of its remote, and writes the role to `RUN/ability` and its class to `RUN/class`: under a
   read-only class (review) the guard refuses every change to the clone, so it writes only to `OUT`.
2. How the member starts depends on the project's local runtime (`dispatch.mode` in its definition;
   `qargi provider show RUNTIME`).
   - **In-session runtime** (Claude Code). Take MEMBER, MODEL and EFFORT from step 1, or run `qargi agent for <role> [--profile NAME]`, which prints one line, `MEMBER MODEL EFFORT PROFILE` (MODEL is the alias, `-` when none;
     `qargi agent models` shows the bases and profiles they came from). Spawn it as `qargi provider notes spawn` says, with the task block plus
     `CLONE`, `OUT`, `GIT` and `BASE_SHA`. A profile whose base class does not fit the role is refused. No member serves the role: ask the user to add
     one (`qargi agent add NAME --roles <role> --project P`), never use another agent type. A member that
     `qargi agent list` shows `STALE` or `DRIFT` runs from an out-of-date or hand-edited file: tell the user, and `qargi agent refresh NAME`
     only with their go-ahead. The agent must run every git command through `GIT`. No opinions on the solution.
   - **Command runtime** (`dispatch.mode` is command: a headless CLI, no member file): load local-run.md.
3. When it reports, run `qargi local verify <RUN>` **first**: it compares all refs
   of the real repository and its remote with the snapshot. A change means the agent
   (or something it ran) pushed or wrote to the real repository: stop, tell the user,
   and do not review further until they have seen it. Verify every returned run before merging any of them (a run never verified
   before the first merge fails the strict check).
4. Then `/qargi-verify` on `OUT`.
5. When the series is merged (or rejected) and you hold what you need, `qargi local clean <RUN>` removes the run:
   the clone, the bare copy, the output and the run's private TMP directory (on /dev/shm), so nothing is left behind.
   It refuses an unmerged run (commits never applied and merged; `--discard` drops them on purpose), one whose
   repository refs changed, and one with no collected manifest (`--discard` for one that produced none). Never chain it after `review apply` or `feature merge` in a loop without stopping on the first failure. Never delete files in /dev/shm by pattern: only a run's own TMP is yours to remove.

## Features and releases

The work of a project that follows git-flow runs inside features: tasks use `--base feature/NAME` and run targeted checks only (the lead runs the one whole-suite run per feature), and the features, releases and
conflicts are the lead's process in `/qargi-flow`. Before dispatching a task into a feature, the lead runs `qargi marshal check NAME` (the feature marshal: who leads it; see `/qargi-flow`); members never run the verbs that change the marshal.

## Parallel tasks and targeted tests

Split a change into tasks whose paths do not overlap and dispatch them together (one `prepare` and one member launch
each, in the same message, every task with its own `--slug`, `SCOPE` and `TMP`). Give each task the narrowest executable
`DONE` (a test file or a script, not the suite); the full suite is run by you once, after the tasks of a collection are
merged. Tasks that touch the same file go one after the other, the second based on the first's merged result.

The barrier stops every ordinary push. It is not a sandbox against an agent that goes
out of its way (it runs as your user); `verify` is what makes that visible.
