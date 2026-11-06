# Members

See also [Choosing models](models.md) and [Providers and runtimes](providers.md).

qargi ships one neutral member definition (`agents/member.json` and its prompt
`agents/member.body.md`) and installs none: you create the members with `qargi agent add`, which
renders it through the project's local runtime. The render is kept in the configuration directory
(`~/.qargi/config/agents/PROJECT/NAME.EXT`, beside `agents.json` and outside every repository) and
written from there to the runtime's agents location, so a checkout that is cleaned or cloned afresh
gets its members back with `qargi agent refresh NAME --project P`; `agent list` names that command
beside a member that is `MISSING`, `STALE` or `DRIFT`. The runtime's definition says how (`renderers.agent`)
and which of its own tools the neutral names (shell, read, edit, write, search, monitor, skill, ...)
become. For Claude Code a member may call `Bash`, `Read`, `Edit`, `Write`,
`Grep`, `Glob`, `Monitor`, `TaskStop`, `ToolSearch` and `Skill`, and every Bash, Edit,
Write and NotebookEdit call passes `qargi __guard` (a runtime states its own hook protocol, or has
none: then a read-only run needs its declared barrier or your acceptance, and `qargi local verify`
is the proof). The guard refuses `git push`, `gh`,
`ssh`, `scp`, `sftp` and changes to a git remote. It also makes review read-only as a
rule rather than a missing tool: a member that only reviews names its class in the hook
command of its definition, and `qargi local prepare --role review` records the role
(as `RUN/ability`) for a member that serves several roles (the guard refuses any
write to that record). Under review the guard refuses an edit outside the run's output
directory and a Bash command that writes into the clone. Whatever the role,
the guard also refuses a member the verbs that change a skill (`qargi skill|tool new`,
`import`, `seal`, `remove`, `link`, `unlink`, `enable`, `disable`, `qargi discover
install`, `qargi packs apply`), the verbs that change a runtime (`qargi provider new|import|seal|remove|enable|disable|attest|accept`),
link a work tree (`qargi project link|unlink`, `qargi packs link|unlink`) or start a command runtime (`qargi local run`),
and any write in the pack library, in `credentials/` or `install.json` of the
configuration directory (not the rest of it), under `state/render`, and in the skills and agents
directories the runtimes declare, outside its clone (for Claude Code `~/.claude/skills`, `.claude/skills`,
`~/.claude/agents` and `~/.claude/plugins`); the `skills/` and `.claude/skills` directories of the repository in
the member's clone stay writable, since they are the work product. The guard fails closed on an
internal error, and the Claude Code member file sets `onFailure: "block"` on the hook (Claude
Code 2.1.295 or later) so that a hook that cannot run blocks the call; frontmatter
hooks of a project-level agent run only once you trust the workspace. So one definition
serves every role; what a role does comes from its role text and the contract, not
from the definition. The guard is a second barrier beside the credential-free git
wrapper; `qargi local verify` remains the proof. A new member is available in Claude
Code sessions started after it is added.
