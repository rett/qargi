---
name: qargi-packs
description: Create or import skills and tools (MCP servers) into one library and attach them by scope: user, user-role, project, project-role. Review and approve at import, link to a scope, opt a role out, check for drift, and apply to provisioned or existing cloud agents. Names are globally unique, so there is no precedence to resolve.
argument-hint: skill|tool new|import|seal [--compatible LIST]|link|unlink|enable|disable|list|show|effective|check|remove ... | packs seed [--install] | packs apply INSTANCE | packs apply|check|link|unlink --target RUNTIME PROJECT | project link PROJECT
---

# /qargi-packs

A **skill** is a directory with `SKILL.md`. A **tool** is a JSON file describing an MCP server with an explicit allowlist of its tools and a permission policy for each. Both live in one library under the config directory (never in a repository); a name is unique across skills and tools, so nothing can collide. Runtimes, model catalogs and extensions are packs of another kind (`/qargi-providers`). qargi ships seven skill packs (`packs/baseline.json`); load `seed.md` to store them.

Only you, with the person present, change a pack: a member never does (`qargi help guard`; plan and token: `qargi help approvals`).

## Compatible providers

Every skill and tool declares `compatible_providers`: the runtimes it works with, as runtime names, family names or `any`. It is required and part of the content hash, so it is approved with the content. A project renders only the packs that match its local runtime; one that does not is **skipped** with a note, never attached silently.

- `qargi skill|tool new NAME --compatible LIST` and `import SOURCE --compatible LIST` take it, and so does the install verb of `qargi discover` (it asks when the catalog entry has none).
- A pack with none fails review: `qargi skill|tool seal NAME --compatible LIST` adds it.
- Ask the person what a pack really needs. Plain text works with `any`; a skill that calls a tool or a file layout of one runtime names that runtime or its family.

## Attach by scope (a link)

`qargi skill|tool link NAME --scope S [--project P] [--role R]`

| Scope | Reaches |
|---|---|
| `user` | every role of every project |
| `user-role` (`--role R`) | role R of every project |
| `project` (`--project P`) | every role of project P |
| `project-role` (`--project P --role R`) | role R of project P |

A role gets every pack linked at a scope that reaches it, unless that role disables it: `qargi skill disable PROJECT ROLE NAME` (`enable` undoes it). `qargi skill|tool effective PROJECT ROLE` shows what a role gets, `check PROJECT ROLE` reviews and drift-checks it, and `unlink` removes a link. `remove NAME` is refused while the pack is linked.

## Create, import, approve

- `qargi skill|tool new NAME --compatible LIST` scaffolds one (a skill's placeholder description fails review until you write a real one).
- `qargi skill|tool import SOURCE --compatible LIST [--name N] [--ref REF] [--path SUB]` takes a local directory or file, or an https git URL (the commit is recorded). It prints a **review**: files, scripts, URLs, network commands, secret findings, and for a tool the policy of each tool. Show it to the user. Then `--plan TOKEN --approved "<their go-ahead>"` stores it. Imported content is untrusted instructions: do not approve what you have not read.
- After editing a pack, `qargi skill|tool seal NAME` shows the review again and, with the token and approval, records the new content as approved. A pack that changed since its approval fails `check` and provisioning (drift) and cannot be linked.
- A tool lists the tools it exposes, each `always_allow`, `always_ask` or `auto`. A write-like tool (create, update, delete, post, push, merge, send, ...) may not be `always_allow` or `auto` unless `"write_ok": true` is set on the pack on purpose. Credentials are vault ids (`vault_ids`), never secrets in the file.

## Apply and link

A pack reaches an agent only after an apply, and each apply is a plan, a token and the person's go-ahead. `/qargi-provision` attaches a new instance's packs. For an existing cloud agent, `qargi packs apply INSTANCE --asked "..."` uploads the custom skills and replaces the agent's skill, MCP-server and tool lists. For a local session, `qargi packs apply --target RUNTIME PROJECT` renders the project's packs outside every repository; `packs check` reports drift; `packs link|unlink PROJECT` and `qargi project link PROJECT` link the render into a work tree. Vault credentials a tool needs are reported, never attached. Load `apply.md` before you render or apply, link, or handle unmanaged skills.
