---
name: qargi-verify
description: Take in the patches a member or cloud agent returned: verify every open run, scrub, apply on a scratch branch, re-run the gates and the DONE check yourself, report, and merge only with the user's approval. Use when a dispatched run has finished or the user asks to review, apply or merge returned work.
argument-hint: <run directory with patches/ and manifest.json>
---

# /qargi-verify (you are the coordinator)

Gates come from the repository's profile alone (`~/.qargi/config/profiles/<repo>.md`), else its own documented checks. An **open** run is a local run made by `qargi local prepare` that `qargi local verify` has not passed; a cloud collect is never open.

## 1. Verify every open run before applying any

For each run:

1. `qargi local verify RUN_DIR`. A change in the real repository's refs means the agent pushed or wrote there: stop and tell the user. A pass arms the run for merges.
2. `qargi review check RUN_DIR/out` (or a cloud collect directory): one numbered patch per commit, a matching manifest and `series.md`, paths inside SCOPE. A FAIL goes back to the agent. A read-only run with no report in OUT gave it in its final message: `qargi review save RUN_DIR` stores it.
3. `manifest.json`: base SHA equals the current base; `done.command` is the DONE of `RUN_DIR/task.md`, with `done.exit_code`; gate verdict lines; status DONE.
4. Read each commit's diff on its own, with the agent's commit advice: one logical change with its tests, docs and changelog entry. Run the profile's private-name or secret scrub on the patches and grep commit messages for private names and trailers (`git interpret-trailers`). Refuse on a hit.

## 2. Apply and check

- Local: `qargi review apply RUN_DIR` makes `agent/<slug>` (the slug it prints) in a temporary worktree at the run's base. Cloud: `git am --3way` the `*.patch` files in name order on a scratch base checkout.
- Rebuild the generated files the profile names, run its gates yourself (trust only their verdict lines), then the DONE of `RUN_DIR/task.md` verbatim. Check each commit builds.
- Anything the profile marks for a second-model review gets one first.

## 3. Report, then merge

Report DONE or BLOCKED, evidence, deviations and the agent's `noticed_not_acted_on` notes (`qargi noticed list`, then `resolve`). Ask before any push; merge to a long-lived branch only when told.

On approval, for each run in turn, with an open feature: `qargi feature merge NAME agent/<slug>` (the run's slug). For a cloud collect or a project with no open feature, apply the series with `git am` onto the branch the user names (authors reset to the user), or split a mixed commit by file yourself. Apply the profile's coordinator steps and strip trailers. Colliding changelog numbers: `qargi changelog renumber`, then commit. **Never squash**: keep the agent's separate commits; send one that mixes changes back to be split.

## 4. Clean up, after the merge

Once the merge is confirmed, `qargi local clean RUN_DIR` removes the run. It refuses an unmerged run (`--discard` drops it on purpose), changed refs, and a run with no collected manifest, except a read-only run (advisor or review) with a `report.md` and no changed ref, which closes with a plain `qargi local clean RUN`. `qargi local clean --applied --scratch DIR` removes the applied and merged runs (`qargi local list --scratch DIR` shows them). Then `qargi branch prune`. `qargi feature finish` refuses while a run is open (unverified, unapplied, or applied and not merged); close one applied by hand (`git am`) with `qargi local close RUN --applied-by-am`. Before a reboot, apply verified runs or rely on their saved copy (`qargi review apply --from-saved ID`). Never delete in /dev/shm by pattern; only a run's own TMP. Cloud: `qargi mark SID applied|rejected [--why CODE]` (ask the user for the reason code on a rejection or rework; `--help` lists codes), then `qargi close SID`.

## Never

- Apply any run before every open run is verified.
- `qargi local clean` before its merge is confirmed.
- `qargi feature finish`, `qargi feature merge` or a commit while any run is open.
- Go on with a loop over runs past a failure: stop at the first, before any `qargi local clean`.
