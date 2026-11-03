---
name: qargi-packs
description: Create or import skills and tools (MCP servers) into one library and attach them by scope: user, user-role, project, project-role. Review and approve at import, link to a scope, opt a role out, check for drift, and apply to provisioned or existing cloud agents. Names are globally unique, so there is no precedence to resolve.
argument-hint: skill|tool new|import|seal [--compatible LIST]|link|unlink|enable|disable|list|show|effective|check|remove ... | packs seed [--install] | packs apply INSTANCE | packs apply|check|link|unlink --target claude-code PROJECT | packs migrate-render | project link PROJECT
---

# /qargi-packs

A **skill** is a directory with `SKILL.md`. A **tool** is a JSON file describing an MCP
server with an explicit allowlist of its tools and a permission policy for each. Both live
in one library under the config directory (never in a repository); a name is unique across
skills and tools, so nothing can collide. Runtimes, model catalogs and extensions are packs of
another kind (`/qargi-providers`).

## Compatible providers

Every skill and tool declares `compatible_providers`: the runtimes it works with, as runtime
names (`claude-code`), family names (`claude`) or `any`. It is required, it is part of the
content hash (so it is approved with the content), and it decides where the pack reaches: a
project renders only the packs that match its local runtime, and a pack that does not is
**skipped** with a note, never attached silently (`skipped skill NAME: not compatible with
RUNTIME (it declares ...)`, in `effective`, `check` and `packs apply|check|link`).

- `qargi skill|tool new NAME --compatible LIST` and `import SOURCE --compatible LIST` take it.
  The install verb of `qargi discover` takes `--compatible LIST` too, and asks when the catalog
  entry has none.
- A library pack made before this has none: `qargi skill|tool seal NAME --compatible LIST` adds
  it (giving it again changes the declaration, and the plan says so). Until then the pack fails
  review. (The baseline packs already in your library get `any` from `qargi packs seed`, below.)
- Ask the person what a pack really needs. A skill that is plain text works with `any`; one that
  calls a tool or a file layout of one runtime names that runtime or its family.

## Attach by scope (a link)

`qargi skill|tool link NAME --scope S [--project P] [--role R]`

| Scope | Reaches |
|---|---|
| `user` | every role of every project |
| `user-role` (`--role R`) | role R of every project |
| `project` (`--project P`) | every role of project P |
| `project-role` (`--project P --role R`) | role R of project P |

A role gets every pack linked at a scope that reaches it, unless that role disables it:
`qargi skill disable PROJECT ROLE NAME` (stored as `roles.<role>.packs_off` in the
project answers; `enable` undoes it). `qargi skill|tool effective PROJECT ROLE` shows what
a role gets; `unlink` removes a link.

## Who may change a skill

Only you, with the person present, run the verbs that change one: `new`, `import`,
`seal`, `remove`, `link`, `unlink`, `enable`, `disable`, the install verb of `qargi discover`, `qargi packs seed`,
`qargi packs apply`, `qargi packs link|unlink|migrate-render` and `qargi project link|unlink`. A local
member never does: its guard refuses these verbs and any write in the pack library or in a
skills directory of any runtime (`.claude/skills` for Claude Code), and `QARGI_NESTED` does
not stand in for the plan token of `import`, `seal` or `packs apply`. If a member
thinks a skill should change, it says so in its report; you show the person the plan
and token and wait for their go-ahead before you apply it. The `--approved` text is
recorded, not verified: it is not proof that a person agreed.

## Create, import, approve

- `qargi skill|tool new NAME --compatible LIST` scaffolds one (a skill's placeholder
  description fails review until you write a real one).
- `qargi skill|tool import SOURCE --compatible LIST [--name N] [--ref REF] [--path SUB]` takes a local
  directory or file, or an https git URL (the commit is recorded). It prints a **review**:
  files, scripts, URLs, network commands, secret findings, and for a tool the policy of
  each tool. Show it to the user. Then `--plan TOKEN --approved "<their go-ahead>"` stores
  it. Imported content is untrusted instructions: do not approve what you have not read.
- After editing a pack, `qargi skill|tool seal NAME` shows the review again and, with
  the token and approval, records the new content as approved. A pack that changed since
  its approval fails `check` and provisioning (drift) and cannot be linked.
- Tools must list the tools they expose, each `always_allow`, `always_ask` or `auto`. A
  write-like tool (create, update, delete, post, push, merge, send, ...) may not be
  `always_allow` or `auto` unless `"write_ok": true` is set on the pack on purpose.
  Credentials are vault ids (`vault_ids`), never secrets in the file.

## Apply

- **New instances:** `/qargi-provision` attaches the role's packs: custom skills are
  uploaded by `ant apply`, and tools become MCP servers with their policies; the plan
  token covers their content.
- **Existing cloud agents:** `qargi packs apply INSTANCE --asked "..."` prints the plan
  and a token; with `--plan TOKEN --approved "..."` it uploads the custom skills, replaces
  the agent's skill, MCP-server and tool lists (a new agent version) and re-points the
  deployment. Vault ids a tool needs are reported, not attached.
- **A local session:** `qargi packs apply --target claude-code PROJECT` (the target is the
  render target of the project's local runtime, `claude-code` for Claude Code)
  prints the plan (what is added, changed or removed, packs skipped as not compatible,
  shadowed skills, tools that need credentials) and a token; with `--plan TOKEN --approved "..."`
  it renders the union of the project's roles into `~/.qargi/state/render/PROJECT/RUNTIME/`
  (RUNTIME is the runtime's name, for example `claude-code`; inside it the runtime's skills
  directory, `.claude/skills` for Claude Code, then `mcp.json`, `settings.json` and
  `MANIFEST.json`) and prints the launch line
  `claude --add-dir DIR --mcp-config DIR/mcp.json --settings DIR/settings.json`.
  Same rule as the cloud apply: show the person the plan and wait for their go-ahead.
  Nothing is written into a repository or `~/.claude`; role scoping is advisory (the
  render is the union of roles); the guard refuses a member any write under
  `state/render/`. Vault credentials a tool needs are reported: the person configures
  them. `qargi packs check --target claude-code PROJECT` reports drift and shadowing
  (a same-named skill in `~/.claude/skills` or the project's `.claude/skills`) and is
  read only.
  The plan refuses hostile packs (a `SKILL.md` name that differs from the pack name, a skill and a tool sharing a name, odd tool names); `check` also reports edited, mode-changed or writable render files and a bad manifest.
- **Renders made before the runtime names:** an earlier version rendered into
  `~/.qargi/state/claude/PROJECT`. `qargi packs migrate-render` prints each move and a plan token;
  with `--plan TOKEN --approved "..."` it moves them to `state/render/PROJECT/RUNTIME`, re-points the
  checkout's skills link only when it points exactly at the old render, and deletes nothing. Do it
  between sessions, not while one is open on the old render; `packs check` reports a missing
  render until it is done.
- **Repo link:** `qargi packs link PROJECT` (plan token, then `--plan TOKEN --approved "..."`) makes the
  checkout's skills directory (the runtime's `resources.skills.project_dir`) a symbolic link to the render, so a session there loads the project's
  packs with no `--add-dir`. A real directory is moved to `skills.qargi-backup` (never deleted) and the
  plan lists its skills as same, differs or new; offer `skill import` and `skill link` for the new ones.
  `packs unlink PROJECT` undoes it. Git-tracked skills, a foreign link and a symlinked parent are
  refused. `.claude` is not tracked, so each worktree needs its own link. A project must name its
  provider (`models.provider`); there is no default. A local member never runs these verbs. If a link
  stops half way, the message says where the skills are; `packs unlink PROJECT` moves a backup back
  when its link is gone.
- **Skills, agents and memory together:** `qargi project link PROJECT [--resource skills,agents,memory]`
  is the same engine for all three in one plan and one token; `project unlink` undoes it. Run it
  inside the work tree to link (each worktree has its own links; nothing records which exist). Each
  resource is linked the way the runtime's definition says (a directory link, one link per entry, or
  a copy), and a real directory in the way moves to `NAME.qargi-backup`. `packs link` is the skills
  part alone. See `/qargi-project`.
- **Unmanaged skills:** `packs check --target ...` ends with every skill a session would load, as
  `qargi`, `accepted`, `drifted`, `excluded` or `unmanaged`. Show the person the `unmanaged` ones.
  `qargi skill accept PROJECT NAME [--user]` records one they want (name and content hash; the plan
  shows the import review); `skill unaccept` removes it. An accepted skill that changes is `drifted`
  and fails `check`. To switch a skill off without removing it the person sets the runtime's
  exclusion in their settings (for Claude Code `skillOverrides`; another runtime may use a config
  list or a deny list); qargi only reads those files.
  For an `unmanaged` skill the section prints the line to add, as text built from the provider's
  layout (`to hide it instead: {"skillOverrides": {"NAME": "off"}} in <settings file>`), and never
  writes it.
- `qargi skill|tool check PROJECT ROLE` reviews and drift-checks what reaches a role.
  `remove NAME` is refused while the pack is linked.

## Baseline packs

qargi ships skills in `packs/` (`shellcheck-gate`, `keep-a-changelog`, `gitflow-member`), each
declared `compatible_providers: ["any"]`.
`qargi packs seed [--install] [--plan TOKEN --approved "..."]` stores them in the library.
Without `--approved` it prints one line per shipped pack and a plan token:

- `add skill N (content H)`: the library has no pack of that name; it is stored.
- `current skill N`: the library copy is the shipped one.
- `update skill N (content OLD -> H; links: ...)`: an untouched shipped copy is replaced
  by the newer text.
- `kept skill N: ...`: not touched, either edited in your library (changed or not yet
  sealed) or the name belongs to a pack you created or imported.

With nothing to add or update it prints `nothing to seed` and no token. Show the person
the plan and wait for their go-ahead, as for any change to a skill; `seed` is refused to
a member. Seeding never links: a pack reaches nobody until you `link` it, for example
`qargi skill link NAME --scope project --project P`. `--install` only adds missing
packs, needs no token, never updates and notes when a newer shipped version exists (this
is what `install.sh --user` runs).

After an update of a linked pack, seed prints the follow-ups: `qargi packs apply --target
claude-code P` for each project the links reach and `qargi packs apply INSTANCE` for
cloud agents. To take the shipped version of an edited pack again: unlink it, remove it
(the `remove` verb of `skill`), seed.
