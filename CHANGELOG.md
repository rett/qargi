# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Dispatcher skill with named instances (local subagent or cloud Managed
  Agents deployment), session tracking, a bounded watcher and an output
  collector. Cloud verbs require `--asked`, the user's request that names
  the cloud instance; sessions are archived, never deleted.
- Agent contract and a per-repository profile (kept under the user's config directory) for
  gates and rules; an example profile for a Go CLI project.
- `install.sh` to symlink the skill and the local subagent into a project.
- `provision.sh`: create the cloud resources for an instance (environment,
  agent, recipes memory store, manual-run deployment) from templates with
  `ant apply`, with a plan step that changes nothing and an apply step that
  needs the user's go-ahead; the lock file stays in the state directory.
- `install.sh --user` and `--project DIR`, with symlink (default) or `--copy`
  installs, `--uninstall`, and a refusal to replace existing real files
  without `--force`.
- Profiles live outside the repository (`profiles/<name>.md` in the config
  directory) and are inlined into the task block; no file is ever added to a
  project's committed files. Project-level installs are excluded from git
  through `.git/info/exclude` and refused if the target paths are tracked.
- Memory store structure with a seed (`provision/memory-seed/`): a short
  README index loaded at session start, `sandbox/` and `repos/<repo>/{setup,gates,pitfalls}/`
  files that follow one template (Kind, Applies to, Check, Verified), and
  rules against secrets, per-run data and backlog material. `memory.sh seed`
  writes it without overwriting; `memory.sh lint` checks layout, index
  coverage, required fields, size, secrets and staleness. Provisioning seeds
  new stores with it.
- `init` selects agent details: `--model` and `--effort` for local instances
  (recorded and passed to the subagent at dispatch), for new cloud resources
  (`--provision`, plan first, create only with `--approved`), and for an
  existing deployment's agent (prints a plan, then updates the agent and
  re-points the deployment only with `--approved`). `list` shows model and
  effort.

### Fixed
- A session budget can only be set when a session is created, so it is now
  set on the deployment (`init --budget CENTS`, or `provision.sh --budget`,
  default 500) and sessions inherit it. The tracker records the session's
  actual budget and warns when a session has none.
- `session.sh close --no-outputs` for tasks that produce no files (memory curation), recorded as not-applicable in the tracker.
- Resources are named `<project>-<role>-<component>` (agent, environment,
  memory, deployment); `provision.sh --project P --role R` creates them that
  way and `registry.sh normalize NAME` renames an existing instance to match.
- Development reference store (`<project>-<role>-reference`): a curated,
  read-only, numbered-folder reference for application development (rules,
  workflow, gates, code/test/change/commit conventions, architecture, checked
  facts, preferences, review checklist), mirroring the structure of a
  documentation store. `provision/reference-seed/` is the skeleton;
  provisioning creates and attaches it read-only; `provision.sh add-reference`
  adds it to an existing instance; `memory.sh seed-reference` and
  `memory.sh lint --kind reference` seed and check it.
- The tool is one `dev-agent` command (`bin/dev-agent`) with the scripts in
  `lib/`, and five skills named `dev-agent`, `dev-instances`, `dev-provision`,
  `dev-memory` and `dev-review`. `install.sh` installs them at user level
  (skills, subagent and command) or per project (skills and subagent, hidden
  from git).
- Fixed `collect`: `ant` reads a piped stdin as a request body, which truncated multi-file downloads; collected output is a flat directory (the file listing has base names only).
- The dispatch skill is now `/dev-task` (`/dev-task "<task>" --done "<check>"`), alongside `/dev-instances`, `/dev-provision`, `/dev-memory` and `/dev-review`. `install.sh` removes leftover `dev-agent` and `dev` skill links. The command, project and subagent keep the name `dev-agent`.
- Naming convention enforced: project and role tokens with a fixed role list, `<project>-<role>-<component>` for agent, environment and deployment, project-level `<project>-memory` and `<project>-reference` stores that provisioning attaches instead of duplicating, and sessions named `<instance>-<task-slug>` (`--label` is now required for cloud sends). `instances normalize` renames to match and `instances show` reports deviations.
- `dev-agent project template|init|show|list|validate` and the `/dev-project` skill: the preliminary questions asked once per project (repository, long-lived branches, roles, per-role base branch, push policy none/coordinator/agent with a branch pattern and credential, model and effort, packages, Anthropic skills, budget, memory), validated and stored outside the repository.
- Never push is the default for every role in the project template and the questionnaire. A role that pushes (`push.mode` `coordinator` or `agent`, with a branch pattern that cannot match a long-lived branch, and a credential for `agent`) is an explicit answer given at project init, for example for a docs agent that already pushes `docs/<slug>`.
- `dev-agent project set NAME PATH VALUE` changes one stored answer (validated first); `dev-agent instances budget NAME CENTS` changes a live deployment's spend ceiling; `provision` takes model, effort, packages, Anthropic skills, budget and stores from the stored project answers (flags override), and attaches the `pdf` skill to agents whose role lists it.
- The canon (`canon/CANON.md`, `canon/layout.json`): a versioned standard layout for memory stores (`/CANON.md` marker, `shared/` plus `roles/<role>/`), with `dev-agent canon check|plan|apply|import|promote|audit`. The reconciler migrates a store from whichever version it is at to the current one without losing content (renames keep identity and history, conflicts go to `/_conflicts/`, the marker is written last, re-runs resume), imports a foreign store such as the old documentation store into a role folder, and audits cross-role writes from the memory version history. `memory lint` hands canon-2 stores to `canon check`. `tests/canon_sim.py` proves a migration is idempotent and conformant.
