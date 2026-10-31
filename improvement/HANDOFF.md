# Handoff: where qargi stands and how to continue on another machine

Written 2026-10-31 at a deliberate stopping point, before development moves to another system. It says what is
in git, what is not, and how to pick the work up. It holds no secrets and names no other project.

## State at the stopping point

- `develop` is at `5093d4a` and is pushed. The full suite passed on an exported copy of the tip before the last
  merge (29 items, exit 0). Nothing is uncommitted in the checkout, there are no stashes and no worktrees.
- Every feature branch is merged into `develop`: memory backends, ops report, memory restore edge, supervisor,
  guard hardening, `~/.qargi` data location (`feature/qargi-home`). They are pushed for completeness.
- `feature/skillsmith-spec` is the drafts branch. It is the only branch with work that exists nowhere else: the
  design drafts (`library/`, `guard/`, `frontend/`, `supervisor/`, `improvement/`) and the review notes. It is
  based on an older commit, so it is not merged and is not meant to be: it carries documents, not code.
- No agent or session is running. The session tracker has no open or pending-review session (17 closed or
  archived); the scratch cloud stores made for tests were archived.
- Data moved from the XDG directories to `~/.qargi/{config,state}` on 2026-10-31 (`qargi migrate home`); the old
  directories were removed after a file-by-file check. The installed tool is a root-owned clone at `/opt/qargi`
  (`install.sh --user` links the command and the skills to it); a run from any other checkout is a dev run with
  its own sandbox `<checkout>/.qargi/` (banner on stderr; `QARGI_HOME=~/.qargi` opts into live data).

## What is NOT in git (copy it, or recreate it)

| What | Where | How to carry it |
|---|---|---|
| Registry, projects, credentials, packs library, profiles | `~/.qargi/config` (mode 0700; one credential file) | copy the directory over a private channel (it holds secrets; never commit it) |
| Sessions, audit log, runs, backups, provisioning output | `~/.qargi/state` | copy it, or start empty: the audit log and the session tracker are the history |
| The assistant's working notes (decisions, rules, where things stand) | `~/.claude/projects/<project-path-with-dashes>/memory/` | copy the directory; the folder name is the project's path with `/` turned into `-`, so on a different path rename it to match |
| Members (`builder`, `writer`, `reviewer`, `tester`; model sonnet) | `~/.claude/agents/*.md`, recorded in `~/.qargi/config/agents.json` | `qargi agent add NAME --abilities ABILITY` for each, or copy both; a new member is available to sessions started afterwards |
| Installed skills | `~/.claude/skills/qargi-*` (links) | `install.sh --user` from the installed clone |
| The cloud login of the `ant` CLI | its own login store | log in again on the new machine; the registry's cloud ids are the same account |

The cloud side (agents, environments, memory stores, deployments named in the registry) lives in the account, not
on the machine, so it follows the registry once the credential and the `ant` login are in place.

## Set up on the new machine

1. `git clone git@github.com:rett/qargi.git` and `git checkout develop`; fetch `feature/skillsmith-spec` for the
   drafts (`git worktree add ../qargi-drafts feature/skillsmith-spec`, so the checkout the installed tool follows
   is never switched).
2. Install the tool where the installed copy should live (a root-owned clone, for example `/opt/qargi`), then
   `install.sh --user` from it. Git may need `safe.directory` for a root-owned clone.
3. Put `~/.qargi` in place before the first qargi command. If the new machine has the old XDG layout it will
   refuse until `qargi migrate home` is applied; with `~/.qargi` copied over there is nothing to migrate.
4. Copy the memory directory, recreate or copy the members, log in with `ant`, run `qargi report` (read-only) to
   confirm the registry and sessions are readable.
5. Run the suite from a checkout, never against live data: `HOME=$(mktemp -d) bash tests/run.sh`.

## Rules the work followed (keep them on the new machine)

- Nothing outward-facing without the owner's typed word: no push, no merge into `develop`, no cloud write, no
  change of the owner's Claude Code settings (print the snippet instead). An approval counts only when the owner
  types it in chat after seeing the plan, and it does not carry to a different plan.
- Skill-modifying verbs belong to the owner. Agents and members are denied them (the guard enforces it).
- Weigh options and recommend, ask the few questions that change the design, record answers in these drafts.
- Verify agent reports yourself (re-run the suite on an exported copy, read the diff, probe the behaviour, scan a
  diff for another project's names) and say what was not verified.
- Tests use temporary directories (`HOME`, `QARGI_STATE`, `QARGI_CONF` or `QARGI_HOME`), never the real ones.
- Keep qargi and the owner's other project apart: refer to it only as "another project" in this repository.
- The platform is not code-only; code is the first domain. Keep core design domain-neutral.

## What is next

Owner decisions waiting (details in `REVIEW.md` and `LOOPS.md`):

- Review the skill spec and the other design drafts, and answer the open questions (L2, L3); fixtures wait for it.
- The builders' saved questions in `REVIEW.md` (supervisor nudge wording and channel, guard tokens for the other
  skill verbs, treat non-JSON hook input as a refusal, and others).
- Apply the printed supervisor hook snippet or stay file-modification-time only (`qargi supervise hooks`).
- Typed memory links wait for the owner's canon review. The core wording change ships with the next release (L11).

Builds queued, in the suggested order:

1. `qargi agent refresh NAME` (L20): existing members still carry the old unhardened hook.
2. The improvement loop's first version (L21), with L5 (`noticed_not_acted_on`) and L15 (stale tracker rows).
3. Replace `QARGI_NESTED` with a parent plan token (L23).
4. `install.sh --system` and `qargi upgrade` (L22 gaps).
5. Then the language-neutral conformance fixtures, the Python validator, and the rest of the "not started" list in
   `SPEC.md`, once the spec is approved.

A small existing gap found on the way: `lib/help.py` crashes on a project record whose `repo` is not an object.
