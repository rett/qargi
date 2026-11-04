---
title: The lead's loop
description: The daily loop of the lead, from claiming a feature to finishing it: dispatch tasks, verify and apply what comes back, merge, run the suite once, finish.
doctype: how-to
---
This is the loop for a project that follows git-flow: `master` holds tagged releases, `develop` integrates, and work happens on `feature/NAME` branches. Every merge is a merge commit that keeps the branch visible (no fast-forward). You are the lead: the session that dispatches, verifies, applies and merges. Members never merge.

qargi makes each merge in a temporary worktree. Your checkout is not touched, a branch moves only after every merge in the command succeeded, and a refusal changes nothing.

## 1. Claim the feature

A feature is a broad, related theme, not one task. Unrelated work gets its own feature.

```bash
qargi marshal check NAME
qargi marshal status --all
qargi marshal claim NAME --goal "what the feature should achieve"
qargi feature start NAME --purpose "what it is about"
```

`marshal check` exits 1 when another live lead holds the feature. `feature list` shows every open feature and any file two of them both change: if they overlap, put the work in one feature or expect a conflict.

## 2. Dispatch tasks

Each task is one change with an executable check. Give each its own slug and a scope that does not overlap another task's. Tasks on different paths run in parallel; tasks on the same file go one after the other, the second based on the first's merge.

```bash
qargi agent for build
qargi local prepare --repo . --base feature/NAME --slug rename-verb --scratch ~/qargi-runs --role build
```

`prepare` makes the run and prints the paths for the task block. The task and its check, the member and the checks to run are in [dispatch and verify](/dispatch-and-verify/). A task runs targeted checks only, never the whole suite.

## 3. Verify every returned run first

When a member reports, before you apply anything:

```bash
qargi local verify RUN
```

This compares every ref of the real repository with the snapshot taken by `prepare`. A change means the member wrote where it must not: stop and tell the owner of the project, and review nothing further from that run.

## 4. Review the series

```bash
qargi review check RUN/out
```

It checks numbered patches, one per commit, commit messages with a body, and a manifest that matches the patches. A `FAIL` line goes back to the member. Then read the manifest (status, the `done` result, the gates, the files touched against the scope) and each commit on its own.

## 5. Apply and check it yourself

```bash
qargi review apply RUN
```

This puts the series on `agent/rename-verb`, in a temporary worktree at the run's base. Run the gates and the task's check yourself, in that branch; trust the verdict lines you produced, not the ones in the report.

## 6. Merge into the feature

```bash
qargi feature merge NAME agent/rename-verb
qargi local clean RUN
qargi review prune
```

`feature merge` keeps the member's commits separate. `local clean` removes the run and refuses one whose work was not merged; `review prune` lists merged `agent/*` branches, and `review prune --yes` deletes them. Never clean a run before its merge is confirmed.

If the merge conflicts, the command exits 3 and changes nothing. It names a worktree with the merge in progress: resolve there, `git add`, `git commit`, then run the same command again with `--resolved`.

## 7. Verify the feature once

When the feature is complete and still yours:

```bash
qargi marshal check NAME
qargi feature sync NAME
qargi feature verify NAME
qargi feature status NAME
```

`sync` merges develop in. `verify` runs the project's whole test suite on the feature's head and records the result: this is the only whole-suite run of the feature. A merge or a change of the test command afterwards makes it stale, and `status` says so.

## 8. Finish the feature

`feature finish` is the only merge into develop. It prints a plan and a token first; show them to the owner of the project and apply exactly that plan with their words.

```bash
qargi feature finish NAME
qargi feature finish NAME --plan TOKEN --approved "the owner's words"
```

Then release the claim with `qargi marshal release NAME --note "finished"`. A release is a separate step with its own plan: `qargi release start VERSION`, `release push`, `release finish`, and the same pattern for a hotfix with `--hotfix`.

## 9. See also

- [Dispatch and verify](/dispatch-and-verify/): one task, from task block to merge
- [Safety](/safety/): plan tokens, approvals and what only the owner does
- [First project](/first-project/)
- [feature](/reference/run-a-task/#feature) and [release](/reference/run-a-task/#release) in the reference
