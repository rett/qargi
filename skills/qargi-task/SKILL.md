---
name: qargi-task
description: Hand a one-off development task (build, write, review or test) to a member that works in its own clone and returns patches, with /qargi-task "<task>" --done "<check>". Use when the user asks to dispatch, delegate or run a task through an agent, or to drive the session of a named cloud instance (send, watch, collect, stop, close). Local by default; cloud only when the request names an instance. Taking the patches in is /qargi-verify; a team run is /qargi-team.
argument-hint: "<task>" --done "<check>" [--instance NAME] [--base B] [--scope PATHS] | send|start|status|watch|collect|stop|close ...
---

# /qargi-task (dispatch and session lifecycle)

A **role** says what a task is for (`qargi role list`): build, write, review and test ship with
qargi; add your own in `~/.qargi/config/roles/NAME/`. Its
**class** (write or read-only) is what the guard enforces; its text cannot change that. A **member** is a
local agent you named and gave roles (`qargi agent add`), written by the project's local runtime from
one member definition (`/qargi-instances`); an **instance** is a registered cloud agent of
one role (see `/qargi-instances`). All
of them obey the contract in `contract/contract.md`: one task,
own clone, patches back, never push, no backlog.

## Quick form

`/qargi-task "<task>" --done "<executable check>" [--role ROLE] [--instance NAME] [--base BRANCH] [--scope PATHS]`

If the first argument is not a session verb (`send`, `start`, `status`, `watch`, `collect`, `stop`, `close`: cloud.md), it is a task: build the
task block (below) and dispatch it to the member that serves the task's role (`qargi agent for ROLE`, whose first word is the member). `--role` defaults to build; take it from the
user's words. Inside a feature, use `--base feature/NAME` and run `qargi marshal check NAME` first; `/qargi-flow` owns the rest.

## Hard rules

- **Local is the default.** Load cloud.md only when the user's request names a cloud instance; never choose cloud on your own or fall back between local and cloud: report instead.
- Agents never push. What the guard refuses: `qargi help guard`. Plan and token rules: `qargi help approvals`.
- Every returned series goes through `/qargi-verify` before anything is applied.

## Task block

ROLE (`ROLE: build (class write)`; the class is `qargi role show ROLE`'s), ROLE_TEXT (locally
`qargi role prompt ROLE`, inlined), TASK, DONE (executable check; if the user
gave prose, get an executable form first), PROFILE (the text of the repository's profile, inlined), BASE (default:
the dispatching session's branch; explicit if that is master or develop), base
SHA, SCOPE (hard limit, optional), OUT (a cloud run's: cloud.md), CLONE, TMP (local runs: `prepare`'s).

## Profiles

A profile holds a repository's gates, rules and coordinator review steps, in `~/.qargi/config/profiles/<name>.md` (`<name>` is the repository directory's name), never in the project. No command reads it: read the file and inline its text as PROFILE. `--profile` on `send` and `local prepare` is the role's model profile, not this file. No profile is fine; nothing qargi related is ever added to a project's committed files.

## Local flow

1. `qargi local prepare --repo <repo> --base <base> --slug <slug> --scratch <scratchpad> --role <role> [--profile <profile>]`
   makes the run: a clone on `agent/<slug>` of a bare copy with no remote, an output directory and a credential-less `git` wrapper. It prints `RUN`, `ROLE`, `CLASS`, `CLONE`, `OUT`, `TMP`, `GIT`,
   `BASE_SHA`, `PROFILE`, `MEMBER`, `MODEL` and `EFFORT`, then the TASK-BLOCK sections (`PATHS`, and `MEMORY` inside a registered project): paste them into the task block verbatim.
   A warning about uncommitted memory means the executor sees only the committed copy. For a private repository not checked out here, use `--repo-url URL --credential-file FILE` in place of `--repo`.
2. Start the member as the project's local runtime says (`qargi provider show RUNTIME`).
   - **In-session runtime.** Take MEMBER, MODEL and EFFORT from step 1 (or `qargi agent for <role> [--profile NAME]`). Spawn it as `qargi provider notes spawn` says, with the task block plus
     `CLONE`, `OUT`, `GIT` and `BASE_SHA`. No member serves the role: ask the user to add
     one (`qargi agent add NAME --roles <role> --project P`), never use another agent type. A member `qargi agent list` shows `STALE` or `DRIFT` is out of date: tell the user, and `qargi agent refresh NAME` only with their go-ahead.
   - **Command runtime** (`dispatch.mode` is command: a headless CLI, no member file): load local-run.md.
3. When it reports, run `qargi local verify <RUN>` first: a change in the real repository's refs means stop and tell the user.
4. Then `/qargi-verify` on `OUT`.
5. Take-in (apply, merge, `qargi local clean`) is `/qargi-verify`'s one sequence.

## Parallel tasks

Split a change into tasks whose paths do not overlap and dispatch them together (one `prepare` and one member launch
each, in the same message, every task with its own `--slug`, `SCOPE` and `TMP`). Give each task the narrowest executable
`DONE` (a test file or a script, not the suite); the full suite is run by you once, after the tasks of a collection are
merged. Tasks that touch the same file go one after the other, the second based on the first's merged result.
