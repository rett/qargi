---
name: qargi-providers
description: Add, review, verify and enable the runtimes qargi dispatches to (runtime, catalog and extension packs in the provider library), including a command-line or local model runtime defined with data only and no code. Plan, token and approval for every change, approval of each executable by name, what verification and attest mean, and which runtime a project uses on its local and cloud surface. For the lead or a Claude Code session, never for a member.
argument-hint: provider list|show|check|new|import|seal|remove|enable|disable|attest|accept ... | project set P models.provider.local|cloud NAME
---

# /qargi-providers

A **runtime** is one way of running agents on one surface: `local` (on this machine) or
`cloud` (hosted). Claude ships as two, `claude-code` (local) and `claude-platform` (cloud),
which share the model catalog of the family `claude`. A runtime is **data**, a JSON
definition, not code: its models, where its skills and agents live and how they are linked,
how a member is dispatched, and how a read-only member is held. Three kinds of pack share the
provider library (`~/.qargi/config/packs/providers/NAME/`, never in a repository):

| Kind | What it is |
|---|---|
| `provider` (runtime) | one runtime on one surface; `family` names the catalog it shares, or `null` |
| `catalog` | the models of a family (tiers, effort levels, when and where each was verified) |
| `extension` | capabilities added to a runtime, for the projects that enable it |

A name is used once among these packs and the shipped definitions: one defined both shipped and
in the library is refused, and so is importing under a shipped name. `qargi provider list`,
`show NAME` and `check NAME|DIR` read them; `show NAME --project P` shows the runtime composed
with P's extensions.

## Which runtime a project uses

There is no default. Ask for each surface, and leave one out if the project never uses it:

- `qargi project set P models.provider.local NAME` and `models.provider.cloud NAME` (also
  `project new|attach --provider-local X --provider-cloud Y`, or `--provider X` for one name).
- A family name works when exactly one runtime of it serves that surface (name the
  runtime itself, `claude-code` or `claude-platform`; the bare name `claude` is the family of both and
  works only by that rule). A runtime that does not serve the surface is refused.
- A verb that needs a surface the answers leave out stops with exit 2 and says which.

## Add a runtime with no code

1. `qargi provider new fakecli [--from minimal|command|hook-cli|RUNTIME]` scaffolds an unsealed
   pack (`--from claude-code` starts from a shipped runtime). An unsealed pack is unusable.
2. Edit `~/.qargi/config/packs/providers/fakecli/definition.json`. The parts that matter:
   - **models**: `pattern` (a model not matching it is refused) and `tiers` (`fast`, `balanced`,
     `deep`, `frontier`; `"*"` fills every tier for a one-model runtime), each with
     `model`, `alias`, `verified_on`, `source`; `effort` is a map or `null` (no effort control).
   - **render** (`agents`, `renderers.agent`): how a member is written as the runtime's own file
     (markdown with front matter, YAML, TOML, JSON or text, fields mapped from the neutral
     member). `"agents": null` means the runtime has no agent files; `local run` then composes
     the member's prompt into the run.
   - **link** (`resources`): `skills`, `agents`, `mcp`, `settings`, `memory`: the project and
     user directory or file, one item per directory or file, how it is linked
     (`dir-symlink`, `entry-symlinks`, `copy` or `none`) and, for skills, how the runtime
     switches one off (`exclusion`; qargi only reads that setting). A resource left out is
     unsupported: the verb that needs it says `provider NAME has no FACILITY`.
   - **dispatch**: `mode` is `in-session` (the lead's session spawns the member with the Agent
     tool), `command` (a headless CLI, run by `qargi local run`) or `adapter`. A command is an
     `argv` ARRAY, never a shell string, with `{model}`, `{effort_native}`, `{clone}` and the
     like, `{"if": ...}` and `{"class": "read-only", ...}` groups, `class_argv`, `prompt` (`via`
     stdin, file or arg), `cwd`, `env_pass` (the only variables handed on; secrets travel by
     name), `timeout_s` and `output`.
   - **barrier**: how a read-only member is held: `hook` (the runtime calls `qargi __guard
     --provider NAME` before a tool runs), `sandbox-args` (the runtime's own flags in
     `class_argv`), `adapter` or `none`.

   A minimal command runtime, complete:

   ```json
   {"schema": 2, "kind": "provider", "provider": "fakecli", "family": null, "surface": "local",
    "description": "fakecli, a command-line model runner",
    "models": {"pattern": "^fake-.+$", "effort": null,
               "tiers": {"*": {"model": "fake-1", "alias": null, "verified_on": null, "source": "fakecli --list-models"}}},
    "capabilities": {"skills": {"value": "yes"}},
    "resources": {"skills": {"project_dir": ".fake/skills", "items": "dir-per-item", "entry": "SKILL.md",
                             "format": "skill-md", "link": {"project": "dir-symlink", "user": "none"}}},
    "agents": null,
    "dispatch": {"mode": "command", "argv": ["fakecli", "run", "--model", "{model}"],
                 "class_argv": {"read-only": ["--sandbox", "read-only"]}, "prompt": {"via": "stdin"},
                 "cwd": "{clone}", "env_pass": ["FAKECLI_API_KEY"], "timeout_s": 1800, "output": {"format": "text"}},
    "barrier": {"kind": "sandbox-args"},
    "session": {"render_target": "fakecli"}}
   ```

   `session.render_target` is the name `packs apply --target` takes for this runtime, and the
   optional `session.launch` the command line that starts an interactive session on the render.
   Without a `render_target` qargi makes no render of the project's skills for the runtime, so
   there is nothing for `project link` to link.

   `fakecli` itself is installed by the person and found on `PATH`; the review lists it as
   "needs on PATH". Run `qargi provider show claude-code` for a runtime with agents, a hook
   barrier and in-session dispatch.
3. `qargi provider check fakecli` (a library pack, or a directory before you import it)
   validates the schema, prints the review and runs the hermetic cases: the agent render twice
   and read back, the skills link planned, applied and undone in a temporary repository, the
   read-only corpus through the guard, an adapter's stub. Fix every failure. Then `qargi provider
   seal fakecli`, then `check` again: a library pack records what it verified only once sealed.
4. `qargi project set P models.provider.local fakecli`, then use it (below). The answers must
   stay valid: a role's stored `model` that does not match the runtime's `pattern` makes
   `project set` refuse, naming each role. Start the project with the runtime
   (`project new|attach --provider-local fakecli`), or edit the roles' models in an answers file
   (`qargi project show P`, `project validate FILE`, `project init P --answers FILE --force`). Its skills are
   rendered with `qargi packs apply --target fakecli P` (`/qargi-packs`) and linked by `project link`.

`qargi provider import SOURCE [--name N] [--ref REF] [--path SUB]` takes a runtime someone else
wrote, from a directory, a JSON file or an https git URL. It is stored sealed on approval and
never enabled or linked by the import; a shipped or existing name is refused.

## Plan, token, approval

Every verb that changes the library (`new`, `import`, `seal`, `remove`, `enable`, `disable`,
`attest`) is two steps. Without `--approved` it prints the review of what would be stored and a
plan token over that content. Show the review to the person, wait for their go-ahead, then run
the same command with `--plan TOKEN --approved "<their words>"`. A pack that changed since the
plan is refused. A pack that holds executables also needs `--approve-exec a,b` naming EVERY
executable the review listed: a missing or an extra name refuses. The `--approved` text is
recorded in the audit log, not verified; it is not proof that a person agreed. `remove` is
refused while a project or an extension still uses the pack.

## Executables are text, and examined

A pack may hold text only: scripts (a renderer, a transform, an adapter) that a person can read
before approving them. Compiled programs, archives, symlinks, and secrets are refused; opaque
blobs (encoded data, very long lines) and scripts that download or run fetched code are
flagged. A vendor CLI is not in the pack: the person installs it and the definition names it.
The review gives each executable's path, sha256, interpreter and first lines, the URLs and
network commands it mentions, and the commands the argv would run. Read each executable in
full before approving it. An approved executable is code the person runs with their rights; the
member guard cannot contain it, and qargi runs it only from a private copy after its hash and the
pack's were checked against the sealed record. Never approve what you have not read.

## Verification, and attest

A capability counts only when the definition claims it AND it is verified; otherwise it counts as
`no`, and the roles that need it (review needs a read-only barrier) are not served.

- A shipped definition is verified by the `verified_on` date and `source` of each cell.
- A library definition is verified by `qargi provider check NAME` on the sealed pack, which
  records every capability whose hermetic cases all pass in `state/providers/NAME/verified.json`,
  bound to the content hash. An edit and a reseal, or a reseal of the runtime an extension
  extends, make the record stale until `check` is run again.
- A fact no hermetic case can show (an OS sandbox that really holds, a real model id, a cost
  report) is `qargi provider attest NAME CAP`. It records a check that the person ran; it runs
  nothing and spends nothing itself. **Attest is asked each time.** Never run a live check, or
  suggest the person has pre-approved one, on your own initiative. Without the facts the verb
  prints what is needed. Before any run, tell the person: the runtime and the capability; the
  exact command or API calls and the scratch resources; the smallest model and effort; the hard
  ceiling in cents or tokens; the expected cost and how it is cleaned up. Only on their go-ahead,
  after the run: `qargi provider attest NAME CAP --asked "<their words>" --did "<what was run>"
  --result pass|fail --cost-cents N --cleanup "<state>" [--note TEXT]`, then the plan token as
  above. A failed result removes the earlier record. A free local check that makes no API call
  needs no spend ask but is recorded the same way (`--cost-cents 0`).
- A read-only role on a surface whose barrier is not supported is refused unless the person
  accepts that for the project: `qargi provider accept NAME --surface S --no-barrier --asked "..."`
  (plan token, then `--plan TOKEN --approved "..."`).

## Extensions

`qargi provider new NAME --kind extension` scaffolds one: `extends` (a runtime or family),
`provides` (capabilities), `requires` and `adds.capabilities` (plus barrier, dispatch variants,
renderers, resources). Seal it, then `qargi provider enable PROJECT NAME` (a plan and approval, with
`--approve-exec` for executables); `disable PROJECT NAME` undoes it. Extensions are per project
only (`models.extensions` in the answers). Nothing is overridden: two extensions that add the
same thing, or one that adds what the runtime already has, are refused, naming both. What an
extension provides counts only after `qargi provider check NAME [--project P]` passes for it, or
an attest, and `provider show RUNTIME --project P` shows which pack provided each capability.

## Using a runtime

- Members are written by the project's local runtime: `qargi agent add NAME --abilities LIST
  --project P` (see `/qargi-instances`). A runtime without agent files refuses `agent add`.
- `qargi project link P` links the project's skills, agents and memory into the work tree you run
  it in, the way the runtime says (`/qargi-project`).
- An `in-session` runtime is dispatched with the Agent tool; a `command` runtime with `qargi local
  prepare` then `qargi local run RUN [--dry-run]` (`/qargi-task`).
- A pack reaches a project only if its `compatible_providers` matches the runtime (`/qargi-packs`).

## Who may change a runtime

Only you, with the person present. A local member's guard refuses `provider new`, `import`,
`seal`, `remove`, `enable`, `disable`, `attest` and `accept`, `project link`, `unlink`
and `local run`, and any write in the pack library or `state/render`; `QARGI_NESTED` does not
stand in for a plan token. If a member thinks a runtime should change, it says so in its report.
The person decides, always: which runtime serves each surface of a project, every import,
seal and enable and each executable in it, every attest and any spend, moving the old renders
(`packs migrate-render`) and refreshing members (`agent refresh`).
