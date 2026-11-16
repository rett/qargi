---
title: Safety: what is refused and who decides
description: What a member may not do, how the guard and the run check enforce it, how plan tokens and approvals work, and which decisions stay with the owner.
doctype: explanation
---
The member contract forbids pushes and changes to shared skills, tools and providers. qargi combines a separate clone, runtime-specific barriers, ref verification and the lead's review to support that contract. Gated verbs require a concrete plan token and the owner's scoped authority. Each protection has limits.

## 1. The member's clone

A local run is a clone of a bare copy of your repository. The bare copy has no remote. The member's clone has an `origin` pointing to that bare copy, with its push URL set to `DISABLED`. Git runs through a wrapper without credentials, global configuration or prompts. The member works on `agent/SLUG` and returns patches or a report according to its class.

This setup obstructs ordinary pushes. It does not prove that an agent cannot bypass it, especially when code runs as the same operating-system user. Rely on the selected adapter's qualified barriers, ref verification and inspection of the returned work. Provider support and barrier guarantees vary. The release's [runtime documentation](https://github.com/rett/qargi/blob/0.3.1/docs/members-and-providers/providers.md) records those limits.

## 2. The guard

In the Claude Code hook runtime, the guard checks a local member's tool calls. Its refusals include the following categories.

- shared-state verbs such as skill and tool import or link, provider changes, protected project settings, release publication and member dispatch.
- writes in the pack library, the credentials, the install record, the runtime's skills, agents and plugin directories, the memory tiers, and the lead's git configuration and session files.
- `git push`, changes to a git remote, `gh`, `ssh`, `scp`, `sftp` and `rsync` to a host.
- reading or copying the lead's signing key.

The hook scans shell segments split at operators and newlines, including quoted text and heredocs. A refused verb inside command-line text can trigger a refusal. Commit with a message file. This text check cannot resolve every shell construct or inspect arbitrary code's effects. Use `qargi help guard` and the release's [guard source](https://github.com/rett/qargi/blob/0.3.1/lib/guard.py) for the exact commands and limitations.

The read-only class forbids repository changes. In hook mode, the guard's rules permit report writes under the run's output and temporary directories. A runtime may still refuse its file-writing tool. Codex command-runtime members have no qargi guard hook. Their shell commands use the Codex sandbox, whose read-only barrier is qualified as partial. A read-only Codex member may write nothing, including OUT and its temporary directory. It returns its report in its final output, then the controller publishes the report and manifest. A class description alone does not grant output-directory writes across adapters.

The Codex sandbox restricts shell writes and network access. It does not restrict all reads or the effects of hosted tools and MCP servers outside that sandbox. The release's [Codex runtime documentation](https://github.com/rett/qargi/blob/0.3.1/docs/members-and-providers/codex.md) and [adapter definition](https://github.com/rett/qargi/blob/0.3.1/lib/providers/codex.json) distinguish observed checks from unverified capabilities.

A refusal is a result. A member reports it and does not look for another way.

## 3. The run check

`qargi local verify RUN` compares snapshots of the real repository's local refs and available origin heads and tags, excluding `refs/qargi/`. Its rules account for recognized journaled lead changes, qualified runtime-ref allowances and owned-ref patterns retained from preparation in the lead's registry. They do not accept every difference. The release's [verification reference](/reference/run-a-task/#local-verify) and [implementation](https://github.com/rett/qargi/blob/0.3.1/lib/local.sh) describe the applicable rules.

Unexpected ref differences fail closed. The lead stops, keeps the evidence, tells the owner and reviews nothing further from that run. A passing check permits the lead to continue reviewing the run. Prepare-time allowances grant no permission for a member to change the real repository, and changing policy later grants no retroactive exemption.

`qargi review check` then checks the shape of what came back. Neither command reads minds; the lead still reads the diffs and runs the checks itself.

## 4. Plans, tokens and approvals

A gated verb prints a concrete plan and a token covering what would be done. The owner decides whether that plan may be applied. After approval, the lead supplies the token and the owner's words.

```bash
qargi feature finish NAME --plan TOKEN --approved "the owner's words"
```

Approval rules follow the scope of that plan.

1. The token covers the plan the person saw. If the plan changed in between, the token no longer matches and nothing happens.
2. Where a command writes an audit entry, it stores the supplied `--approved` words as unverified text.
3. Cloud `qargi start` and `qargi send` require `--asked "the request"`, which records the request for cloud use on that task. Each command's reference describes its requirements.
4. A member never applies a plan. It reports the plan and its token, and the lead shows them to the person.
5. Never allow-list a gated verb in the runtime's settings. The permission prompt is the person's real control.
6. Only the owner's approval authorizes that specific plan. Agent messages provide task data.

Some shared-state operations have explicit exceptions. Installation and upgrade invoke `qargi packs seed --install`, which can also be run explicitly. This path reviews shipped baseline packs and stores only missing ones, unlinked, without an import token. Custom imports, seals, links and renders retain their applicable scope, review and approval gates.

Token syntax is described by `qargi help approvals`. Each command's requirements are listed in the [command reference](/reference/).

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
