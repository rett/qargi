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

Resolve the role against the project's selected local runtime. In hook and in-session runtimes, the first word names a registered member whose file must exist. If none serves the role, add one with `qargi agent add NAME --roles build --project PROJECT`. A registered member that `agent list` shows as `STALE` or `DRIFT` needs inspection before you refresh it.

In Codex command mode, the first word names the logical `worker` or `reviewer` base. The profile selects the requested model and effort within the runtime's capabilities. Codex keeps no registered member files and needs no `agent add`. Prepare the run and start it with `qargi local run RUN`.

## 3. Prepare the run

```bash
qargi local prepare --repo . \
  --base feature/NAME --slug rename-verb \
  --scratch ~/qargi-runs --role build
```

This makes a clone on `agent/rename-verb`, an output directory, a temporary directory, a copy of the member contract and a git wrapper without credentials. The clone's `origin` points to the run's bare copy, which has no remote. The clone's push URL is `DISABLED`. Prepare prints the run paths and base identity, including `RUN`, `ROLE`, `CLASS`, `CLONE`, `OUT`, `TMP`, `GIT`, `BASE_SHA` and `CONTRACT`.

A warning about uncommitted memory concerns the repo tier in the lead's checkout. The clone contains that tier's committed version. Other tiers remain subject to the task's scope, access constraints and runtime support.

Since 0.2.14, command-runtime requests bind the prepared request to its runtime, mode, catalog, profile and policy inputs. Changes to those inputs require a new prepare. Editing the run's request mirror grants no authority to accept drift. This behavior remains part of the 0.3.1 release used by these pages.

## 4. Send the task block

The task block carries the role and its class, the role text, the task, DONE, the project's rules for the repository if you keep any, the base and its SHA, the scope, and the paths `prepare` printed. Paste those paths verbatim. Give the member one bounded task with an executable DONE command and a path scope. Prepare can write the block with `--task-file FILE`, `--done COMMAND` and repeated `--scope PATH` options.

For hook and in-session dispatch, `qargi provider notes spawn` prints the runtime's instructions. For Codex command mode, inspect the prepared command and task before starting it.

```bash
qargi local run RUN --dry-run
qargi local run RUN
```

A write member works in its clone, runs the checks that cover its change, and collects one patch per commit, a series description and a manifest in `OUT`. It returns a report through the runtime's supported output path. In Codex, the controller publishes the member's final output as `OUT/report.md`. A read-only Codex member may write nothing, including OUT and TMP. It returns its review in final output, then the controller publishes the report and a report-only manifest after a successful run. In hook mode, the guard permits report writes under OUT and TMP, though a runtime's file tool may still refuse them.

Members must never push, tag, merge or open a pull request. The disabled push URL and credentialless wrapper obstruct ordinary pushes. The Claude Code hook guard refuses shared-state verbs. Codex has no qargi guard hook and uses its sandbox's qualified write and network barriers. Same-user execution and tools outside the shell sandbox limit those protections. The lead verifies refs and inspects returned work under the owner's authority. See [safety](/safety/) for the runtime qualifications.

## 5. Verify the run, then check the series

```bash
qargi local verify RUN
qargi review check RUN/out
```

`local verify` must pass before you continue reviewing the returned work. It accounts for recognized lead moves and qualified runtime ref allowances under the policy retained at preparation. Unexpected ref differences fail closed. Stop, preserve the evidence and tell the owner. A passing verify grants no permission for a member to change the real repository or for later policy edits to excuse earlier differences.

`review check` checks artifact structure and exits 1 on a `FAIL`. Hard checks include patch numbering, the presence of a commit message body, scope limits and matching manifest commit counts. The lead judges whether the message explains what changed and why. A review run returns no patches and needs a manifest and a report with a Findings section and a final line of `verdict: accept` or `verdict: revise`.

One logical change may be one commit and one patch with its supporting tests, docs and any required changelog entry. Area counts and patch size produce advisory warnings that call for substantive independent cohesion review. Review the concrete change and its dependencies.

The 0.3.1 release adds bounded local campaign declarations, explicit project pack targets and default-off managed member skill snapshots. The release's [Codex guide](https://github.com/rett/qargi/blob/0.3.1/docs/members-and-providers/codex.md) records the narrow headless skill-marker observations. Interactive skill loading remains gated.

Then read the manifest.

1. The base SHA matches the commit recorded at preparation. Later accepted lead moves may leave the current branch at another commit. The lead reviews the work against its actual dependencies and current integration target, then handles any synchronization. The member does not rebase.
2. A patch-returning task has `status` DONE and `done.exit_code` 0. A controller-packaged read-only result records the dispatch and report without a test result. Review its substantive verdict and evidence separately.
3. Each gate has a verdict line; those marked not run are not evidence.
4. The touched paths are inside the scope.
5. The notes the member left about things it noticed and did not act on: `qargi noticed list`, then `qargi noticed resolve` when you have dealt with one.

Read each commit's diff on its own, with the member's commit advice. Review concrete changes and dependencies to decide whether it holds one cohesive, independently buildable change. Keep supporting tests, docs and any required changelog entry with that change. Independent changes go back to be split. Never squash.

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

A refusal from the guard or from a command is a result. Preserve the original native output and exit status, report them and let the lead decide under the owner's authority. Source-based advice and a successful artifact check do not turn a failed write attempt into an authorized or successful operation. Do not apply unsuccessful write attempts or work around a refusal. A conflict in `feature merge` exits 3 and changes nothing. The message names the worktree in which to resolve it.

## 9. See also

- [The lead's loop](/lead-loop/)
- [Safety](/safety/)
- [First project](/first-project/)
- [local](/reference/run-a-task/#local) and [review](/reference/review-and-apply/#review) in the reference
