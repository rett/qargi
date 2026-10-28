---
name: qargi-team
description: Run a team on one task, opt-in: a lead coordinating role agents (developer, docs writer, reviewer) so a change to the code and the documentation that describes it are made, reviewed and delivered together. Led by this Claude Code session, by a cloud lead agent, or by a lead session started in the console.
argument-hint: brief PROJECT TEAM --task T --done C [--base B] | check DIR | contract
---

# /qargi-team

A team is for a task whose change affects usage (a renamed command, a changed output), where the
code, the documentation and an independent check should move together. Most tasks are one role:
use `/qargi-task`. A team costs two to three times a single run and is chosen by the user for the
task; `qargi` may recommend one when the developer's `usage_impact` is not empty.

## Definition (in the project's stored answers, outside every repository)

`lead` (model, effort) and `teams.<name>`: `members` (roles of the project), `max_rounds`,
`budget_cents`, `standards` (store paths the reviewer judges against), `scopes` (per role, the paths it
may change), `done` (a DONE check per role). Set with `qargi project set`.

## Who owns what

The developer owns everything that ships with the code: manual page, help text, completion, the
project's `docs/` pages and the changelog. The docs role owns the operational documentation on its own
branch (`site/` on `gh-pages`), exclusively. In a team it also reviews the developer's user-facing wording
for friendliness. The reviewer judges both series against the standards and returns a verdict. Each member
works in its own clone and returns its own series against its own base; series are never merged.

## Three ways to lead (one contract: `qargi team contract`)

| Lead | How |
|---|---|
| **This session** (default) | The session-start hook has loaded the lead's resources. You dispatch each member yourself with `/qargi-task` (local subagent, or a cloud role agent when the user's request names the cloud), in order: developer; docs with `USAGE_IMPACT` and the developer's series; reviewer; revise rounds up to `max_rounds`. You verify every run and apply with the user's approval. |
| **A cloud lead** | `qargi team brief PROJECT TEAM --task ... --done ... --base ...` prints the brief. `qargi start PROJECT-lead --asked "..."`, then `qargi send PROJECT-lead --label SLUG "<brief>" --asked "..."`. The lead starts the members as threads, runs the rounds and reports; `qargi watch`, `qargi collect SID DIR` (it splits the outputs per member), then `qargi team check DIR`. |
| **A lead started in the console** | Start a session from the lead deployment (`PROJECT-deployment-lead`) and give it a plain task: the team definitions are in its prompt. Afterwards `qargi track SID`, `qargi collect SID DIR`, `qargi team check DIR`. |

Cloud verbs need `--asked "<the user's request>"`, and the cloud is used only when the request names it.

## Verify before anything is applied

`qargi team check DIR` runs the patch or report check on every member and reads the lead's
`team.json`. A team that did not reach `accept` is not applied: read `lead/summary.md`, report the open
findings to the user and let them decide. Apply each series on its own base with `/qargi-review`.

## Who pushes

Only the lead, never a member, and only as the project's `lead.push` grant says (default: nothing).
- **This session as lead:** with `lead.push.local`, it pushes `agent/*` branches and opens pull requests
  without asking each time (the session-start autoload says so). Without the grant it asks before every push.
- **A cloud or console lead:** with `lead.push.cloud: branches`, it has a GitHub tool with a fixed allowlist:
  read tools, branch, file and pull-request writes unattended, `merge_pull_request` asked of the person by the
  platform (a tool confirmation, answered in the console), nothing destructive. Set it up with
  `qargi lead grant PROJECT` in a terminal: it says how to create the fine-grained token (the one
  repository, Contents and Pull requests read and write, nothing else), checks it, and then shows and asks
  about each of its three steps (token and vault; the GitHub tool; the Push rules), skipping what is already
  in place. `qargi lead status PROJECT` shows what is in place and what is missing; `qargi lead revoke
  PROJECT` takes the grant away. From Claude Code run them with `!`. The steps are also available one by
  one (`credential setup lead-push`, `packs apply`, `instances refresh-prompt`) for an agent to run with your
  words in `--approved`.
- **A series too large to carry.** The GitHub tool takes the full content of every changed file for each commit, so a series that touches large files (a 500 KB man page changed in several commits) can be too big for the lead to carry. It then reports BLOCKED for delivery only, leaves the member's `run.bundle`, and its `team.json` says so. The coordinator (this session, with the `lead.push.local` grant) carries it: apply the patches on the base, set the author to the person (the members' commits are authored by the agent), verify with `/qargi-review`, push `agent/<slug>` and open the pull request. `qargi team check` reports the lead's BLOCKED status and reason.
- **Merges and releases** always need the person's explicit approval for that pull request or release. The
  GitHub tool cannot create releases; a release is made by this session after "release it".
- Branch rulesets on the repository remain the backstop: protected branches and release tags refuse any token.

