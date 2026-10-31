---
name: qargi-verify
description: Coordinator procedure for verifying and applying the patches a member or a cloud agent returned: check the manifest, scrub, apply on a scratch branch, re-run gates and the DONE check yourself, then report and apply only with the user's approval.
argument-hint: <run directory with patches/ and manifest.json>
---

# /qargi-verify (you are the coordinator)

Gates come from the repository's profile, which is the single source of which gates run (the reference store explains them, it does not add or drop any) (`~/.qargi/config/profiles/<repo>.md`;
examples in `examples/`); without one, use the repository's own documented checks.

0. `qargi review check RUN_DIR`: confirms the output is a numbered series with one patch
   per commit, each with its own message body, a manifest that matches, patch groups and
   a `series.md`, and flags a monolithic patch or a batch of commits made at the end. A FAIL
   means send it back to the agent; do not review a monolithic patch.
1. `manifest.json`: base SHA equals the current base; `done.exit_code`; gate
   verdict lines; touched paths inside SCOPE; status DONE.
2. Read every patch, each commit's diff on its own and not just the series, and the agent's
   commit advice. Check that each commit is change-specific (one logical change, its tests, docs
   and changelog entry with it). Run the profile's private-name or secret scrub on the
   patches; grep commit messages for private names and trailers
   (`git interpret-trailers`). Refuse on a hit.
3. Scratch checkout of the base: for a local run `qargi review apply RUN_DIR` (it runs `review check` and `local verify`, creates
   `agent/<slug>` in a temporary worktree at the run's base, applies the series and prints the next commands); for a cloud collect
   `git am --3way` the flat directory of `*.patch` files in name order. Rebuild
   generated files the profile names; run the profile's gates (long ones with
   `run_in_background`, trusting only their verdict lines); then run the DONE
   command verbatim. Only your own runs count.
4. Anything the profile marks for a second-model review gets one before it is
   applied.
5. Report to the user: DONE or BLOCKED, evidence, deviations, the agent's
   "noticed, not acted on". On approval, for a local run, take the branch in with
   `qargi feature merge NAME BRANCH`, then `qargi local clean RUN_DIR`, then `qargi review prune [--yes]` (lists, or with `--yes` deletes,
   the merged `agent/*` branches); otherwise apply to the feature branch (`git am`). Apply the profile's coordinator steps (for example renumbering a changelog
   item), strip trailers, commit. **Never squash.** Apply the agent's commits as the separate,
   change-specific commits they are (`git am`, author reset to the user); if one mixes
   unrelated changes, send it back to the agent to split, or split it by file yourself; do not
   fold commits together to tidy history. Check that each commit builds
   (`git rebase --exec 'go build ./...' <base>`, or the profile's equivalent) before you report. Run `qargi local verify RUN_DIR` on EVERY returned run before merging any of them: a passing verify arms the run, after which
   the lead's own fast-forwards are accepted, but a run never verified before the first merge fails the strict check. Ask before any push. Never merge to a
   long-lived branch unless told. Then `qargi mark SID applied|rejected [--why CODE]`
   (ask the user for the reason code when they reject, or when rework was needed; codes: `qargi mark --help`)
   and `qargi close SID` for cloud sessions. List the manifest's `noticed_not_acted_on` notes to the user
   (`qargi noticed list`; collecting records them) and record what they decide with `qargi noticed resolve`.
