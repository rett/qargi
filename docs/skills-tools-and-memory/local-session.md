# Skills and tools in a local Claude Code session

Packs are enabled for a project by links (`qargi skill|tool link NAME --scope project ...`, see `/qargi-packs`). Each pack declares `compatible_providers` (runtime names, family names or `any`; required, and part of the content hash), and a project renders only the packs that match its local runtime: the others are skipped with a note, never attached silently (`--compatible LIST` on `skill|tool new|import|seal`). To use the packs in a Claude Code session on your machine, render them. `qargi packs apply --target claude-code PROJECT` prints a plan and a token; run it again with `--plan TOKEN --approved "<your words>"` to apply (the target is the render target of the project's local runtime).

The apply renders the union of the packs of all the project's roles into `~/.qargi/state/render/PROJECT/RUNTIME/` (RUNTIME is the runtime's name, here `claude-code`; `QARGI_HOME` or `QARGI_STATE` move it): the runtime's skills directory (`.claude/skills` for Claude Code), `mcp.json` and `settings.json` for the tools, and `MANIFEST.json` with the hash of every file. It then prints the launch line that starts Claude Code with the render:

```
claude --add-dir DIR --mcp-config DIR/mcp.json --settings DIR/settings.json
```

(the `--mcp-config` and `--settings` parts appear only when the project has tools). `qargi packs check --target claude-code PROJECT` reports drift (a pack changed since you approved it, or the render no longer matches its manifest) and shadowing (a skill of the same name in `~/.claude/skills` or in the project's own `.claude/skills`, which would override or hide the rendered one). It only reads and changes nothing. A project that was never applied is not a failure: the check says `not applied` and how to apply it, and exits 0. The answer `packs.none: true` says the project uses no project packs; the check then passes with no render (and fails if a pack is linked to a role of the project). Either way the section of the skills a session would load, the unmanaged ones in `~/.claude/skills` included, is still printed.

To load the render without typing the launch line, `qargi packs link PROJECT` makes the repository's `.claude/skills` a symbolic link to it (plan token and approval as for apply): any session opened in that checkout then loads the project's packs. A real `.claude/skills` is moved to `skills.qargi-backup` (nothing is deleted) and `qargi packs unlink PROJECT` puts it back; `packs link` lists which of its skills are new to the library first, and `qargi skill import` brings them in. `.claude` is not tracked, so a new worktree needs its own link. `qargi project link PROJECT [--resource skills,agents,memory]` does the same for the skills, the members and the memory in one plan and one token, each placed the way the runtime's definition says (a directory link, one link per entry, or a copy), and `project unlink` undoes it. `packs check` also lists every skill a session would load that qargi does not manage (`unmanaged`); `qargi skill accept PROJECT NAME` records one you want (for example a skill in `~/.claude/skills`) by name and content hash.

The plan refuses, writing nothing, a skill whose `SKILL.md` name differs from its pack name (or whose front matter is not closed or has two `name` keys), a skill and a tool with the same name, and a tool allowlist name with anything but letters, digits, `_`, `.` and `-`. Concurrent applies serialize on a lock (the second refuses if the render changed meanwhile), and the swap installs only the tree the token approved; the token also covers file modes. `check` also reports a rendered file that differs from the library copy, a mode change, a group- or world-writable render, a malformed manifest, and a manifest for another project or with role scoping other than advisory.

`qargi local prepare` warns too: when the project has a render that has drifted, it prints a WARNING block to stderr with the findings and the fix (`qargi packs apply --target claude-code PROJECT`); the run goes on and its output is unchanged.

- Applying a render writes nothing into a repository or into `~/.claude`: it lives in the state directory only. Only the links you apply (`packs link`, `project link`) put anything in a checkout.
- Role scoping is advisory here: Claude Code cannot hold a session to one role's skills, so the render is the union over the project's roles.
- The guard refuses a member's ordinary writes under `state/render/`; only you apply the render, and `local verify` is the backstop.
- A tool whose pack lists vault credentials (`vault_ids`) cannot authenticate locally; the plan names it and you configure its credentials yourself.

## Baseline packs

qargi ships seven skills of its own in `packs/` (listed in `packs/baseline.json`, one `skills/NAME/SKILL.md` each), written to be portable:

- `shellcheck-gate`: lint every shell file you add or change with shellcheck and quote the verdict among the gates.
- `keep-a-changelog`: record each user-visible change under Unreleased in `CHANGELOG.md`, in the same commit.
- `gitflow-member`: a member's part of a git-flow project (its own `agent/<slug>` branch, no merges, only the checks that cover its change).
- `review-findings`: how a reviewer writes findings (severity order, `file:line`, one-sentence defect, failure scenario, `CONFIRMED` or `PLAUSIBLE`, no patches).
- `secrets-scan`: run a secret scanner over your commits before the report, if one is installed, and quote its verdict among the gates; the lead scans again.
- `docs-site-member`: work on a documentation branch that shares no history with the main branches, based on that branch and never merged into a long-lived one.
- `qargi-contributing`: habits for a member who changes qargi itself (quoting, commit messages, sleep, stash, fail-first tests, shrink-only ceilings, targeted tests).

Install and upgrade add the ones your library lacks with `qargi packs seed --install`, which needs no token and links nothing. `qargi packs seed` shows a plan (one line per pack: `add`, `update`, `current` or `kept`) and a plan token; `--plan TOKEN --approved "<your words>"` applies it, adding missing packs and replacing a copy you never edited when qargi ships a newer text. A copy you edited and sealed, or a pack of your own with the same name, is kept and never overwritten. To take the shipped version of an edited pack again, unlink it, remove it (`qargi skill remove NAME`) and seed.

Seeding never links. To enable a baseline pack for a project: `qargi skill link NAME --scope project --project P`, then render it as above. Not done yet: link proposals when a project is created or attached, user-scope links, and more packs.
