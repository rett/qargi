---
name: qargi-flow
description: The git-flow process for a project that follows the gitflow methodology, driven with the qargi commands - features, tasks, the one whole-suite run per feature, releases, hotfixes, and resolving merge conflicts. Load it when you lead or coordinate work on such a project, start or finish a feature or a release, or a merge conflicts. For the lead or a Claude Code session, never for a member.
argument-hint: feature NAME | release VERSION | hotfix VERSION | status
---

# /qargi-flow (the lead's process, by git-flow)

The model is the one its author described (master: tagged production releases; develop: integration; feature, release and
hotfix branches, every merge `--no-ff`). qargi runs the commands for you in temporary worktrees: your checkout is never touched,
a branch moves only after every merge succeeded, and a refusal changes nothing. Merging into develop or master, pushing and
tagging need a plan token and the user's words as `--approved` (print the plan, show it, apply exactly that; never invent
an approval). Projects follow it through their stored answers (`qargi project attach` or `new`); `qargi methodology show gitflow`
prints the model.

## The loop (many features may be open at once)

1. **Start a feature**: `qargi feature start NAME --purpose "what it is about"`. A feature is a broad, related theme, not a
   task; unrelated work gets its own feature. `qargi feature list` shows every open feature, its purpose and any file two of them
   both change: if they overlap, put the work in one feature or expect to resolve a conflict.
2. **Run tasks inside it** with `/qargi-task`: `--base feature/NAME`, as large as the feature allows (a long, proactive session
   beats many small ones), each with its own `--slug` and a `SCOPE` that does not overlap another task's. Tasks that touch
   different paths run in parallel; the same file goes one after the other. A task runs targeted checks only.
3. **Take each task in**: `/qargi-verify` the series and apply it to a branch, then `qargi feature merge NAME BRANCH`, then
   `qargi local clean RUN`.
4. **When the feature is complete**: `qargi feature sync NAME` (pulls in what other features landed; a conflict stops here, see
   below), then `qargi feature verify NAME` (the one whole-suite run), then `qargi feature finish NAME` (plan, then apply with
   `--plan` and `--approved`). That is the only merge into develop. Its run carries over to develop's new head, so a release
   needs no further run.
5. **Release** when the user says develop is ready: `qargi release start VERSION` (refuses unless develop's head passed the
   whole suite; the first commit bumps VERSION and dates the changelog; bump any other file that carries the version on this
   branch; only minor fixes belong here), `qargi release push VERSION` (opens the pull request into master, so CI runs on the
   commit that will be released), wait for its checks, then `qargi release finish VERSION`: master `--no-ff`, an annotated tag,
   develop `--no-ff`, branch deleted, master, develop and the tag pushed together.
6. **Hotfix** a critical bug in production: `qargi release start VERSION --hotfix` (from master), fix, `release push`,
   `release finish --hotfix` (merges into the open release branch instead of develop when one exists).

`qargi feature status NAME` and `qargi release status VERSION` show where a branch stands and whether the whole-suite run is
current. Any merge into a branch, or a change of the test command, makes an earlier run stale: say so and run it again rather
than finishing on it.

## When a merge conflicts (exit 3)

Nothing was changed. The message names a worktree under the state directory with the merge in progress and the conflicted files.
Resolve there (yourself, or delegate it as a build task: the executor works in its own clone and returns the resolution),
`git add`, `git commit`, then run the same command again with `--resolved`. It uses exactly your merge, refuses one that is
not finished or no longer matches the branches, and a rerun without `--resolved` while a resolution waits is refused, not
overwritten. A conflict over the version number when merging back is the one the model warns about: keep the release's version.
After a resolution the whole-suite run is stale again; sync, verify, finish.

## Rules

- Never commit to master or develop by hand, never force-push, never delete a branch qargi did not create.
- Do not run the whole suite for any reason but a checkpoint above (feature complete, release verify); tasks and merges use
  targeted checks.
- A tag, once pushed, is final. Say what will be tagged before the plan is applied.
- Anything unexpected (a refusal you do not understand, a record that looks wrong): stop and tell the user.
