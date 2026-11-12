# Members

See also [Choosing models](models.md), [Providers and runtimes](providers.md) and [Codex as lead and as member](codex.md).

qargi ships one neutral member definition (`agents/member.json` and its prompt
`agents/member.body.md`) and installs none: you create the members with `qargi agent add`, which
renders it through the project's local runtime. The render is kept in the configuration directory
(`~/.qargi/config/agents/PROJECT/NAME.EXT`, beside `agents.json` and outside every repository) and
written from there to the runtime's agents location, so a checkout that is cleaned or cloned afresh
gets its members back with `qargi agent refresh NAME --project P`; `agent list` names that command
beside a member that is `MISSING`, `STALE` or `DRIFT`. The runtime's definition says how (`renderers.agent`)
and which of its own tools the neutral names (shell, read, edit, write, search, monitor, skill, ...)
become. On `claude-code` a new member is available in the sessions started after it is added. A runtime that keeps no
member files has no `agent add`: a project on `codex` runs each task with `qargi local prepare` and `qargi local run`
([Codex as lead and as member](codex.md#a-complete-local-run)).

## The tools a member has

For Claude Code a member may call `Bash`, `Read`, `Edit`, `Write`,
`Grep`, `Glob`, `Monitor`, `TaskStop`, `ToolSearch` and `Skill`, and the MCP tools of the tool packs its roles are given (below); every call of `Bash`, `Monitor`, `Edit`, `Write`, `NotebookEdit`, `Read` and `Grep`, and of every MCP tool (`mcp__.*`), passes `qargi __guard`
(a runtime states its own hook protocol, or has
none: then a read-only run needs its declared barrier or your acceptance, and `qargi local verify`
is the proof). A `Monitor` command is judged exactly as a `Bash` command is; `Glob`, `TaskStop`,
`ToolSearch` and `Skill` are not hooked, since they run no command and change no file.

### MCP tools

A member has no MCP tool unless a tool pack reaches one of its roles (`qargi tool link`, see
[Skills and tools in a local Claude Code session](../skills-tools-and-memory/local-session.md)). `qargi agent add` and
`agent refresh` write into the member's tool list the tools of those packs, under the names the runtime gives them
(for Claude Code `mcp__SERVER__TOOL`, with every character of a name other than a letter, a digit, `_` and `-` written
as `_`: the tool `platform.list_items` of the pack `kb` is `mcp__kb__platform_list_items`). A tool that is `always_ask`
is left out, since a member runs unattended, and a member of read-only roles alone gets only the declared reads. The
member is `STALE` after a link, an unlink or a seal changes those packs, and `agent refresh` renders it again.

The guard judges every call of an MCP tool by the policy the packs of the role give that tool. It refuses

- a tool that is in no tool pack linked to the role, in every run;
- a tool whose pack is missing from the library, changed since you approved it or fails its review;
- an `always_ask` tool: it waits for a person, and a member runs unattended;
- a name that stands for two tools of the role (`a.b` and `a_b` of one server are written the same way);
- in a read-only run (review), every tool that is not a declared read: `always_allow`, a name that is not write-like and,
  when the pack was approved with the server's tool listing (`qargi tool import|seal --tool-list FILE`), `readOnlyHint: true` there.

The role is the one of the run, as the lead's registry of local runs records it. An MCP call names no path, so the
guard finds the run from the directory the call is made in; a member that a session starts works in the session's
directory, outside its run, and for that case the hook command of a member with MCP tools names its project and roles
(`qargi __guard --project P --roles build,review`): the call must then be allowed for every one of those roles, each held
to its class. A member that serves a read-only role beside write roles therefore calls only declared reads unless the
guard finds its run; give a member that needs a write tool the write roles alone.

## What the guard refuses

The guard refuses `git push`, `gh`,
`ssh`, `scp`, `sftp` and changes to a git remote.

It also makes review read-only as a
rule rather than a missing tool: a member that only reviews names its class in the hook
command of its definition, and `qargi local prepare --role review` records the role
(as `RUN/ability`) for a member that serves several roles (the guard refuses any
write to that record). Under review the guard refuses an edit outside the run's output
directory and a Bash command that writes into the clone. So one definition
serves every role; what a role does comes from its role text and the contract, not
from the definition.

Whatever the role,
the guard also refuses a member the verbs that change a skill (`qargi skill|tool new`,
`import`, `seal`, `remove`, `link`, `unlink`, `enable`, `disable`, `qargi discover
install`, `qargi packs apply`), the verbs that change a runtime (`qargi provider new|import|seal|remove|enable|disable|attest|accept`),
link a work tree (`qargi project link|unlink`, `qargi packs link|unlink`) or start a command runtime (`qargi local run`),
and any write in the pack library, in `credentials/` or `install.json` of the
configuration directory (not the rest of it), under `state/render`, and in the skills and agents
directories the runtimes declare, outside its clone (for Claude Code `~/.claude/skills`, `.claude/skills`,
`~/.claude/agents` and `~/.claude/plugins`); the `skills/` and `.claude/skills` directories of the repository in
the member's clone stay writable, since they are the work product.

## What the guard is

The guard refuses a call
it cannot read or decide (an internal error, input that is not JSON). The Claude Code member file sets `onFailure: "block"` on the hook (Claude
Code 2.1.295 or later) so that a hook that cannot start, for example because `qargi` is not on `PATH`,
blocks the call; on a runtime that does not enforce it such a call goes through. Frontmatter
hooks of a project-level agent run only once you trust the workspace.

The guard is a second barrier beside the credential-free git
wrapper. It is a best-effort text check of the command or the path of a call, which refuses the ordinary ways to push, reach out, change a skill or write where a role may not. It is not a sandbox. A local member runs as your operating-system user, so an agent that goes out of its way can get around it; a real sandbox is not yet built. `qargi local verify` and `qargi review check` are the backstop: they check what came back, not what was attempted.

A member of a command runtime started by `qargi local run` (the `codex` runtime) has no guard hook at all: what holds it is the runtime's own sandbox (for Codex, the read-only or workspace-write sandbox of the run's class, with no network for its commands), the credential-free git wrapper and a clone whose only remote is the run's copy with its push URL disabled, and the same backstop. Neither the guard nor the sandbox makes a push impossible; they leave an ordinary push nothing to reach or authenticate with, and `qargi local verify` shows whether any ref of the real repository moved. See [Codex as lead and as member](codex.md).

Permission decisions require a supported class in the lead's registry; a missing or invalid class refuses the operation and preserves the run for investigation. The member's copy of its class is not authoritative.

Clone inspection supports ordinary prepared clones only within the [supported layouts and limits](providers.md) described below: plain clone and `.git` directories, files ref storage, SHA-1 or SHA-256, and no Git extensions beyond `objectFormat`. It copies the entire object and ref stores along with HEAD, config, index and packed refs. The total copied regular-file bytes may not exceed 512 MiB; config alone may not exceed 1 MiB. There are at most 100,000 traversal/read steps, 64 directory levels below each copied top-level entry, a 60-second copy traversal budget and a 60-second timeout for each Git subprocess. Steps include directory enumeration, copied nodes and each read block of up to 1 MiB. These fixed limits remain in 0.2.13, including for an ordinary prepared clone with a large object store.

Inspection refuses metadata indirection, disables transports, replacement objects and helper execution, and isolates Git from the owner's configuration and credentials. `local run`, `local verify`, `review check` and `local clean` show a sanitized failure reason, such as a byte, traversal, depth or time limit, unsupported metadata or unreadable storage, without config values or subprocess error text. Failure is unknown, never a clean worktree or zero commits. Ordinary clean preserves the run, TMP, output, saved evidence and state when worktree inspection is unknown, even when commit inspection succeeds; unknown commit state also refuses ordinary clean. Before deliberately dropping a run with `--discard`, preserve its patches, report, refreshed sign-in residue and any wanted files by copying them out. A clean copy does not itself reduce an oversized object store, and config cannot raise these limits. Do not run Git in a member's clone. Copies can combine concurrent states; inspection is not an immutable snapshot and cannot contain processes that leave the original group. SIGKILL can leave a private inspection directory in lead state; this change adds no stale-directory sweeper.
