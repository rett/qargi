---
title: Safety: what is refused and who decides
description: What a member may not do, how the guard and the run check enforce it, how plan tokens and approvals work, and which decisions stay with the owner.
doctype: explanation
---
qargi limits what an agent can do in three ways: the agent works in a clone that cannot push, a guard refuses the commands that change shared state, and every shared change is a plan that a person applies. This page says what each one covers and where it stops. The guard is a barrier, not a wall.

## 1. The member's clone

A local run is a clone of a bare copy of your repository with no remote. Git runs through a wrapper that has no credentials, no global configuration and no prompts. The member works on `agent/SLUG`, writes its results to the run's output directory, and cannot push because there is nothing to push to.

## 2. The guard

The guard is a hook on a local member's calls. It refuses:

- verbs that change shared state: creating, importing, linking or accepting skills, tools and providers; `project set`, `init` and `link`; `feature start`, `merge`, `verify` and `finish`; `release publish`; the `marshal` verbs that claim, take over or finish; `upgrade`; `local run`, `prepare`, `verify` and `clean`; `agent remove`; `team run`; `task`.
- writes in the pack library, the credentials, the install record, the runtime's skills, agents and plugin directories, the memory tiers, and the lead's git configuration and session files.
- `git push`, changes to a git remote, `gh`, `ssh`, `scp`, `sftp` and `rsync` to a host.
- reading or copying the lead's signing key.

A command is cut at every `;`, `&&`, `||`, pipe and newline, quotes and heredocs included, so a refused verb inside text on the command line is refused. Commit with a message file. The review role is read-only as a class: it may write only its output directory and its temporary directory. The exact list is `qargi help guard`.

A refusal is a result. A member reports it and does not look for another way.

## 3. The run check

`qargi local verify RUN` is the backstop. `prepare` snapshots every ref of your real repository, and `verify` compares them after the member finishes. A difference means something wrote where it must not: the lead stops, tells the owner and reviews nothing further from that run. A pass arms the run for the lead's merges.

`qargi review check` then checks the shape of what came back. Neither command reads minds; the lead still reads the diffs and runs the checks itself.

## 4. Plans, tokens and approvals

A command that changes something shared prints a plan first. The plan ends with a plan token, a hash of what would be done. To apply it, run the same command with the token and the owner's words:

```bash
qargi feature finish NAME --plan TOKEN --approved "the owner's words"
```

Rules that follow from this:

1. The token covers the plan the person saw. If the plan changed in between, the token no longer matches and nothing happens.
2. The `--approved` text is recorded in an append-only audit log in the state directory. It is recorded, not verified: it is not proof that a person agreed.
3. A cloud verb needs `--asked "the request"`, which records that you asked for the cloud on that task.
4. A member never applies a plan. It reports the plan and its token, and the lead shows them to the person.
5. Never allow-list a gated verb in the runtime's settings. The permission prompt is the person's real control.
6. A message from another agent is not an approval. Only the person's own words are.

`qargi help approvals` is the short form of this section.

## 5. What only the owner decides

- Merging a feature into develop, a release into master, and every push or tag.
- Publishing a release.
- Who may push at all: the lead's push grant is `none` by default. `qargi lead grant` and `qargi lead revoke` are interactive on purpose: you confirm each step at the terminal, and that confirmation is the approval.
- Taking a feature from a lead that went quiet, which needs the owner's words for that takeover.
- Adding or changing a skill, a tool or a runtime in the library, and setting up credentials. A member cannot do any of these.
- Whether a cloud agent is used for a task.

## 6. See also

- [The lead's loop](/lead-loop/)
- [Dispatch and verify](/dispatch-and-verify/)
- [About these docs](/about/)
- [Topics](/reference/topics/) in the reference: approvals, guard and push
