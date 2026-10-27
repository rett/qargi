---
name: dev-review
description: Coordinator procedure for verifying and applying the patches a dev agent returned (local or cloud): check the manifest, scrub, apply on a scratch branch, re-run gates and the DONE check yourself, then report and apply only with the user's approval.
argument-hint: <run directory with patches/ and manifest.json>
---

# /dev-review (you are the coordinator)

Gates come from the repository's profile, which is the single source of which gates run (the reference store explains them, it does not add or drop any) (`$XDG_CONFIG_HOME/dev-agent/profiles/<repo>.md`;
examples in `examples/`); without one, use the repository's own documented checks.

1. `manifest.json`: base SHA equals the current base; `done.exit_code`; gate
   verdict lines; touched paths inside SCOPE; status DONE.
2. Read every patch, each commit's diff on its own and not just the series, and the agent's
   commit advice. Check that each commit is change-specific (one logical change, its tests, docs
   and changelog entry with it). Run the profile's private-name or secret scrub on the
   patches; grep commit messages for private names and trailers
   (`git interpret-trailers`). Refuse on a hit.
3. Scratch checkout of the base: `git am --3way` on the collected `*.patch` files in name order (a cloud collect is a flat directory, a local run has `OUT/patches/`); rebuild
   generated files the profile names; run the profile's gates (long ones with
   `run_in_background`, trusting only their verdict lines); then run the DONE
   command verbatim. Only your own runs count.
4. Anything the profile marks for a second-model review gets one before it is
   applied.
5. Report to the user: DONE or BLOCKED, evidence, deviations, the agent's
   "noticed, not acted on". On approval apply to the feature branch (`git am`),
   apply the profile's coordinator steps (for example renumbering a changelog
   item), strip trailers, commit. **Never squash.** Apply the agent's commits as the separate,
   change-specific commits they are (`git am`, author reset to the user); if one mixes
   unrelated changes, send it back to the agent to split, or split it by file yourself; do not
   fold commits together to tidy history. Check that each commit builds
   (`git rebase --exec 'go build ./...' <base>`, or the profile's equivalent) before you report. Ask before any push. Never merge to a
   long-lived branch unless told. Then `dev-agent mark SID applied|rejected`
   and `dev-agent close SID` for cloud sessions.
