---
name: qargi-verify
description: Take in the patches a member or cloud agent returned: verify every open run, scrub, apply on a scratch branch, re-run the gates and the DONE check yourself, report, and merge only with the user's approval. Use when a dispatched run has finished or the user asks to review, apply or merge returned work.
argument-hint: <run directory with patches/ and manifest.json>
---

# /qargi-verify (you are the coordinator)

The one take-in sequence, for one returned run or several. Gates come from the repository's profile, the only source of gates (`~/.qargi/config/profiles/<repo>.md`); without one, use the repository's own documented checks. An **open** run is a local run made by `qargi local prepare` that `qargi local verify` has not yet passed; a cloud collect is never open.

## 1. Verify every open run before applying any

For each run:

1. `qargi local verify RUN_DIR` (a cloud collect has none). A change in the real repository's refs means the agent pushed or wrote there: stop, tell the user, review nothing further. A pass arms the run for your merges.
2. `qargi review check OUT` (`RUN_DIR/out`, or a cloud collect directory): one numbered patch per commit, a matching manifest and `series.md`. A FAIL goes back to the agent.
3. `manifest.json`: base SHA equals the current base; `done.exit_code`; gate verdict lines; touched paths inside SCOPE; status DONE.
4. Read each commit's diff on its own, with the agent's commit advice: one logical change, its tests, docs and changelog entry. Run the profile's private-name or secret scrub on the patches and grep commit messages for private names and trailers (`git interpret-trailers`). Refuse on a hit.

## 2. Apply and check

- Local: `qargi review apply RUN_DIR` makes `agent/<slug>` (the run's slug, which the command prints) in a temporary worktree at the run's base. Cloud: `git am --3way` the `*.patch` files in name order on a scratch checkout of the base.
- Rebuild the generated files the profile names, run its gates yourself (trust only their verdict lines), then the DONE command verbatim. Check that each commit builds.
- Anything the profile marks for a second-model review gets one first.

## 3. Report, then merge

Report DONE or BLOCKED, evidence, deviations and the agent's `noticed_not_acted_on` notes (`qargi noticed list`, then `qargi noticed resolve`). Ask before any push; merge to a long-lived branch only when told.

On approval, for each run in turn, with an open feature: `qargi feature merge NAME agent/<slug>` (the run's slug). For a cloud collect or a project with no open feature, apply the series with `git am` onto the branch the user names (authors reset to the user), or split a mixed commit by file yourself. Apply the profile's coordinator steps and strip trailers. **Never squash**: keep the agent's separate commits; send one that mixes changes back to be split.

## 4. Clean up, after the merge

Only when the merge is confirmed, `qargi local clean RUN_DIR` removes the run. It refuses an unmerged run (`--discard` drops it on purpose), changed refs, and a run with no collected manifest. `qargi local list --scratch DIR` shows which runs are applied and merged; `qargi local clean --applied --scratch DIR` removes those and keeps the rest. Then `qargi branch prune`. No need to clean each run before the next `qargi feature finish`: verify and clean accept qargi's own moves. Never delete files in /dev/shm by pattern; only a run's own TMP is yours. Cloud: `qargi mark SID applied|rejected [--why CODE]` (ask the user for the reason code on a rejection or when rework was needed; `qargi mark --help` lists codes), then `qargi close SID`.

## Never

- Apply any run before every open run is verified.
- `qargi local clean` before its merge is confirmed.
- `qargi feature finish`, `qargi feature merge` or a commit while any run is open.
- Go on with a loop over runs past a failure: stop at the first, before any `qargi local clean`.
