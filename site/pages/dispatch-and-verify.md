---
title: Dispatch, verify and apply
description: Hand one task to a member with an executable check, read the patches it returns, verify the run, apply the series on a branch and merge what you checked.
doctype: how-to
---
This page follows one task from the task block to the merge. For where it sits in a feature, see [the lead's loop](/lead-loop/). Local is the default: the member runs on your machine in a scratch clone. Use a cloud agent only when your request for that task names one.

## 1. Write the task

A task has two parts that matter: what to change, and a check that decides it is done.

- The check, called DONE, is a command whose exit status decides. If you only have a description such as "the tests pass", turn it into a command first: a test file or a script, as narrow as you can make it, not the whole suite.
- The scope is the set of paths the member may change. It is a hard limit: a member whose task needs a change outside it stops and reports.
- The base is the branch the work starts from, for example `feature/NAME`.

A role says what a task is for. `qargi role list` shows the roles qargi knows, `qargi role show build` its class (write or read-only) and `qargi role prompt build` the text a member gets with the task.

## 2. Pick the member

```bash
qargi agent for build
qargi agent for review --profile advisor
```

The first word of the output is the member. If none serves the role, add one with `qargi agent add NAME --roles build --project PROJECT`; do not use another kind of agent. A member that `agent list` shows as `STALE` or `DRIFT` is out of date: look at why before you refresh it.

## 3. Prepare the run

```bash
qargi local prepare --repo . --base feature/NAME --slug rename-verb --scratch ~/qargi-runs --role build
```

This makes a clone on `agent/rename-verb` of a bare copy that has no remote, an output directory, a temporary directory, a copy of the member contract and a git wrapper without credentials. It prints `RUN`, `ROLE`, `CLASS`, `CLONE`, `OUT`, `TMP`, `GIT`, `BASE_SHA` and `CONTRACT`. A warning about uncommitted memory means the member sees only the committed copy.

## 4. Send the task block

The task block carries the role and its class, the role text, the task, DONE, the project's rules for the repository if you keep any, the base and its SHA, the scope, and the paths `prepare` printed. Paste those paths verbatim. Start the member the way the project's local runtime says: `qargi provider notes spawn` prints it.

The member works in its clone, runs the checks that cover its change, and writes to `OUT`: one patch per commit, a series description, a manifest and a report. It does not push, tag, merge or open a pull request, and it cannot: the clone has no remote and the guard refuses the verbs that change shared state (see [safety](/safety/)).

## 5. Verify the run, then check the series

```bash
qargi local verify RUN
qargi review check RUN/out
```

`local verify` must pass before you read anything else. `review check` prints `OK`, `WARN` or `FAIL` lines and exits 1 on a `FAIL`. It refuses a single combined patch, a commit without a message body and a manifest that does not match the patches. A review run passes with a report that has a Findings section and no patches.

Then read the manifest:

1. The base SHA equals the current head of the base branch. If the base moved, the lead syncs; the member does not rebase.
2. `status` is DONE and `done.exit_code` is 0.
3. Each gate has a verdict line; those marked not run are not evidence.
4. The touched paths are inside the scope.
5. The notes the member left about things it noticed and did not act on: `qargi noticed list`, then `qargi noticed resolve` when you have dealt with one.

Read each commit's diff on its own, with the member's commit advice. A commit that mixes two changes goes back to be split. Never squash.

## 6. Apply it on a branch

```bash
qargi review apply RUN
```

This creates `agent/rename-verb`, the run's slug, in a temporary worktree at the run's base. Run the gates for the paths it touches and then the DONE command verbatim, yourself. Check that each commit builds. Anything the project marks for a second opinion gets one before the merge.

## 7. Merge or send it back

```bash
qargi feature merge NAME agent/rename-verb
qargi local clean RUN
```

Merge only when you are satisfied, one run at a time, and stop at the first failure. If there is no open feature, apply the series to the branch the owner names with `git am` and reset the authors to your own. `qargi local clean` removes the run only after its merge is confirmed; `--discard` drops a run on purpose.

When several runs are open, `qargi local list --scratch ~/qargi-runs` shows each run's role, age and whether it is applied and merged, and `qargi local clean --applied --scratch ~/qargi-runs` removes those that are both.

## 8. If something is refused

A refusal from the guard or from a command is a result. Read the message, report it and decide; do not work around it. A conflict in `feature merge` exits 3 and changes nothing; the message names the worktree in which to resolve it.

## 9. See also

- [The lead's loop](/lead-loop/)
- [Safety](/safety/)
- [First project](/first-project/)
- [local](/reference/run-a-task/#local) and [review](/reference/review-and-apply/#review) in the reference
