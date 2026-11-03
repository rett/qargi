Load when you render or apply packs, link a project or repository, or handle unmanaged skills.

# Apply and link

Every apply here prints a plan and a token first; show the person the plan and wait for their
go-ahead before `--plan TOKEN --approved "..."`.

- **New instances:** `/qargi-provision` attaches the role's packs: custom skills are uploaded,
  and tools become MCP servers with their policies; the plan token covers their content.
- **Existing cloud agents:** `qargi packs apply INSTANCE --asked "..."` prints the plan and a
  token; with `--plan TOKEN --approved "..."` it uploads the custom skills, replaces the agent's
  skill, MCP-server and tool lists (a new agent version) and re-points the deployment. Vault ids
  a tool needs are reported, not attached.
- **A local session:** `qargi packs apply --target claude-code PROJECT` (the target is the render
  target of the project's local runtime) prints the plan (what is added, changed or removed,
  packs skipped as not compatible, shadowed skills, tools that need credentials). With the token
  and approval it renders the union of the project's roles into
  `~/.qargi/state/render/PROJECT/RUNTIME/` (RUNTIME is the runtime's name; inside it the runtime's
  skills directory, then `mcp.json`, `settings.json` and `MANIFEST.json`) and prints the launch
  line. Nothing is written into a repository or the runtime's user directory; role scoping is
  advisory (the render is the union of roles). Vault credentials a tool needs are reported: the
  person configures them. `qargi packs check --target claude-code PROJECT` reports drift and
  shadowing (a same-named skill in the user's or the project's skills directory) and is read
  only. The plan refuses hostile packs (a `SKILL.md` name that differs from the pack name, a skill
  and a tool sharing a name, odd tool names); `check` also reports edited, mode-changed or
  writable render files and a bad manifest.
- **Renders made before the runtime names:** an earlier version rendered into
  `~/.qargi/state/claude/PROJECT`. `qargi packs migrate-render` prints each move and a plan token;
  with `--plan TOKEN --approved "..."` it moves them to `state/render/PROJECT/RUNTIME`, re-points
  the checkout's skills link only when it points exactly at the old render, and deletes nothing.
  Do it between sessions, not while one is open on the old render; `packs check` reports a missing
  render until it is done.
- **Repo link:** `qargi packs link PROJECT` (plan token, then `--plan TOKEN --approved "..."`)
  makes the checkout's skills directory (the runtime's `resources.skills.project_dir`) a symbolic
  link to the render, so a session there loads the project's packs with no `--add-dir`. A real
  directory is moved to `skills.qargi-backup` (never deleted) and the plan lists its skills as
  same, differs or new; offer `skill import` and `skill link` for the new ones. `packs unlink
  PROJECT` undoes it. Git-tracked skills, a foreign link and a symlinked parent are refused. The
  link is not tracked, so each worktree needs its own. A project must name its provider
  (`models.provider`); there is no default. If a link stops half way, the message says where the
  skills are; `packs unlink PROJECT` moves a backup back when its link is gone.
- **Skills, agents and memory together:** `qargi project link PROJECT [--resource
  skills,agents,memory]` is the same engine for all three in one plan and one token; `project
  unlink` undoes it. Run it inside the work tree to link (each worktree has its own links; nothing
  records which exist). Each resource is linked the way the runtime's definition says (a
  directory link, one link per entry, or a copy), and a real directory in the way moves to
  `NAME.qargi-backup`. `packs link` is the skills part alone. See `/qargi-project`.
- **Unmanaged skills:** `packs check --target ...` ends with every skill a session would load, as
  `qargi`, `accepted`, `drifted`, `excluded` or `unmanaged`. Show the person the `unmanaged` ones.
  `qargi skill accept PROJECT NAME [--user]` records one they want (name and content hash; the
  plan shows the import review); `skill unaccept` removes it. An accepted skill that changes is
  `drifted` and fails `check`. To switch a skill off without removing it the person sets the
  runtime's exclusion in their settings (`qargi provider notes skills-dir`; another runtime may use
  a config list or a deny list); qargi only reads those files. For an `unmanaged` skill the section
  prints the line to add (`to hide it instead: ...`), as text built from the provider's layout,
  and never writes it.
