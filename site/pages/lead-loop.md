---
title: The lead's loop
description: The daily loop of the lead, from claiming a feature to finishing it: dispatch tasks, verify and apply what comes back, merge, run the suite once, finish.
doctype: how-to
---
This is the loop for a project that follows git-flow: `master` holds tagged releases, `develop` integrates, and work happens on `feature/NAME` branches. Every merge is a merge commit that keeps the branch visible (no fast-forward). You are the lead: the session that dispatches, verifies, applies and merges. Members never merge.

qargi performs merges in temporary worktrees and journals lead ref movements. The plan describes the branch and push effects. Interrupted operations retain recovery state for native retry.

## 1. Claim the feature

A feature is a broad, related theme, not one task. Unrelated work gets its own feature.

```bash
qargi marshal check NAME
qargi marshal status --all
qargi marshal claim NAME \
  --goal "what the feature should achieve"
qargi feature start NAME \
  --purpose "what it is about"
```

`marshal check` exits 1 when another live lead holds the feature. `feature list` shows every open feature and any file two of them both change: if they overlap, put the work in one feature or expect a conflict.

## 2. Dispatch tasks

Each task is one change with an executable check. Give each its own slug and a scope that does not overlap another task's. Tasks on different paths run in parallel; tasks on the same file go one after the other, the second based on the first's merge.

```bash
qargi agent for build
qargi local prepare --repo . \
  --base feature/NAME --slug rename-verb \
  --scratch ~/qargi-runs --role build
```

`prepare` makes the run and prints the paths for the task block. The task and its check, the member and the checks to run are in [dispatch and verify](/dispatch-and-verify/). A task runs targeted checks only, never the whole suite.

## 3. Verify every returned run first

When a member reports, before you apply anything:

```bash
qargi local verify RUN
```

This compares observed snapshots of local refs and available origin heads and tags, excluding `refs/qargi/`. It accounts for recognized journaled lead changes and qualified runtime allowances retained at preparation. Unexpected differences stop acceptance. Preserve the evidence and tell the owner. The [safety reference](/safety/) describes coverage and transient-activity limits.

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
qargi branch prune
```

`feature merge` keeps the member's commits separate. `local clean` removes the run and refuses one whose work was not merged; `branch prune` lists the merged `agent/*` and `feature/*` branches with a plan token; run it again with `--plan TOKEN --approved "..."` to delete them. Never clean a run before its merge is confirmed.

If the merge conflicts, the command exits 3 and changes nothing. It names a worktree with the merge in progress: resolve there, `git add`, `git commit`, then run the same command again with `--resolved`.

## 7. Verify the feature once

When the feature is complete and still yours:

```bash
qargi marshal check NAME
qargi feature sync NAME
qargi feature verify NAME
qargi feature status NAME
```

`sync` merges develop in. `verify` runs the project's whole test suite on the feature's head and records the result. Run it when the feature is complete. A failed checkpoint requires repair and a fresh pass. A later merge or test-command change makes the result stale, and `status` says so.

## 8. Finish the feature

`feature finish` is the only merge into develop. It prints a plan and a token first; show them to the owner of the project and apply exactly that plan with their words.

```bash
qargi feature finish NAME
qargi feature finish NAME --plan TOKEN \
  --approved "the owner's words"
```

Finishing marks the feature's marshal record finished. A release follows its own plan through `qargi release start VERSION`, `release push` and `release finish`. A hotfix uses the same pattern with `--hotfix`.

## 9. See also

- [Dispatch and verify](/dispatch-and-verify/): one task, from task block to merge
- [Safety](/safety/): plan tokens, approvals and what only the owner does
- [First project](/first-project/)
- [feature](/reference/run-a-task/#feature) and [release](/reference/run-a-task/#release) in the reference
