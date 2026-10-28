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
findings to the user and let them decide. Apply each series on its own base with `/qargi-review`. Nothing
is pushed: members never push, and a lead delivers patches.
