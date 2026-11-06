# Skills, tools and memory

The skills and the one command behind them, the packs a session loads, how memory is kept in tiers and moved, and how tools are found.

- [Skills and command](#skills-and-command)
- [Skills and tools in a local Claude Code session](local-session.md), with the baseline packs
- [Memory](memory.md): memory tiers; splitting, merging and moving memory
- [Finding tools](finding-tools.md)

## Skills and command

Eleven skills, all prefixed `qargi-`, drive one `qargi` command. `/qargi-task` dispatches work; the roles are defined by their texts (see [Roles and members](../flow/README.md#roles-and-members)), not by skills; the others configure and manage:

| Skill | Covers |
|---|---|
| `/qargi-task` | dispatch (`/qargi-task "<task>" --done "<check>"`) and session lifecycle: `send`, `start`, `status`, `watch`, `collect`, `stop`, `close` |
| `/qargi-project` | the one-time project questionnaire: repository, roles, per-role push policy, the runtime of each surface, models, skills, budget, memory, the members; `project link` |
| `/qargi-instances` | `init`, `list`, `show`, `remove`, `normalize` |
| `/qargi-provision` | `plan`, `apply`, `add-reference` |
| `/qargi-packs` | skills and tools in one library, attached by scope (user, user-role, project, project-role), declared compatible with the runtimes that may use them, reviewed at import, checked for drift |
| `/qargi-providers` | the lead's guide to runtimes: add one with data only, review and seal it, verification and `attest`, extensions, the runtime of each surface |
| `/qargi-memory` | `lint`, `get`, the canon (`check`, `plan`, `apply`, `promote`), the session-start autoload |
| `/qargi-verify` | the coordinator's procedure for verifying and applying returned patches |
| `/qargi-flow` | the lead's git-flow process: features, tasks, releases, hotfixes and resolving conflicts |
| `/qargi-team` | a team on one task: a lead coordinating members for build, write and review; led by this session, a cloud lead, or a lead started in the console |
| `/qargi-session` | the lead's handoff to a fresh session: `qargi marshal handoff` writes the note from stored state, the new session reports what it believes before it does anything |
