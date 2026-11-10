# Architecture

How qargi is put together, for someone who changes it. Every statement here can be found in the code; the paths are the ones
to grep. See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the workflow and [Help, manual page and completion](../reference/README.md#help-manual-page-and-completion)
for what is generated from the command table.

## Where each kind of record lives

All of it is outside every repository, under one root: `~/.qargi`, or `<checkout>/.qargi` in a dev run, or `QARGI_HOME`
(`lib/paths.py`, `lib/lib.sh`; `QARGI_CONF` and `QARGI_STATE` name the two halves separately). The directories are mode 700.

Configuration (`config/`), what you set up and rarely change:

| Path | Holds |
|---|---|
| `install.json` | the tool root `install.sh --user` recorded; decides installed run or dev run |
| `projects/NAME.json` | a project's stored answers (repository, branches, models, gates, release, ...) |
| `instances.json` | the registered cloud instances |
| `agents.json`, `agents/PROJECT/` | the named members and the canonical copy of each one's render |
| `credentials/` | token files, mode 600 |
| `packs/` | the library of skills, tools and providers, with `accepted.json` |
| `roles/`, `methodologies/` | your own roles and methodologies, beside the ones the tool ships |

State (`state/`), what the commands write as they run:

| Path | Holds |
|---|---|
| `audit.log` | one JSON line per action that calls `audit_log` (gated and cloud verbs): time, verb, detail, `--asked`, `--approved` |
| `local-runs.jsonl` | the lead's registry of local runs, written by `local prepare`; the only record `verify`, `clean` and `review apply` believe about a run |
| `runs/ID/` | the lead's copy of a verified run's output, so `review apply --from-saved ID` works after the run directory is gone |
| `apply/ID.json` | the record that a run was applied, and how far the apply got |
| `scrub_ok/ID` | the hash of a series whose take-in scrub passed |
| `finish-intent/` | the intent of a `feature finish` or `release finish`, so a re-run after a death completes it |
| `conflicts/` | the kept worktree of a merge that conflicted, to resolve and resume |
| `suite-logs/` | the last whole-suite log and gate list of each project and branch |
| `ref-journal.jsonl` | every branch move the lead made, so `verify` and `clean` can tell them from a member's |
| `features/`, `marshal/` | the marshal's local records, and per project its switch and trusted signers |
| `sessions.json` | the tracker of cloud sessions (role, profile, model, effort, state) |
| `render/`, `providers/`, `env/` | rendered packs, provider verification records, environment records |

With the shared marshal backend the records of open features are also commits on `refs/qargi/features/NAME`, and finished ones
on `refs/qargi/done/NAME`, of the project's remote (`lib/marshal_refs.py`).

## The layers

- `bin/qargi` is the dispatcher. It answers `help`, `version`, completion and the guard itself, wraps `--json`, runs a
  preamble (`lib/help.py`: dev-run banner, the project implied by the current directory) and then `exec`s the script of the command.
- `lib/commands.py` is the one description of the commands, verbs and options. Help, the manual page and completion are generated from it.
- `lib/*.sh` are the verbs. Each takes its arguments, calls `lib/lib.sh` helpers (state paths, `audit_log`, `need_plan`, locks) and git.
- `lib/*.py` are the engines that need real parsing or data structures: the guard, the marshal, packs, the provider and
  render machinery, the take-in check, help, the site generator.
- Providers are data: `lib/providers/NAME.json` describes a runtime (its tools, hook protocol, barrier, dispatch, renderers).
  Code reads the definition; the adapter of a runtime (`lib/providers/claude-code/adapter`) is the code for what data cannot say.
- Packs are skills and tools with a content hash, imported, sealed and linked by scope; `packs/` ships seven.
- A methodology (`methodologies/NAME/methodology.json` and `scaffold/`) is data read by `project new|attach|adopt`; see
  [Flow](../flow/README.md#methodologies) for what it configures.
- `skills/`, `roles/`, `contract/` and `agents/` are prompts: the lead's skills, the role texts, the member contract and the
  neutral member definition. They are text, tested for size and duplicated sentences (`tests/skill-budget.txt`).

## The life of a local run

1. `local prepare` clones the repository into a run directory with no remote and a git wrapper without credentials, records
   the run in `local-runs.jsonl`, takes the refs of the real repository, and writes the task block.
2. A member works in the clone under the guard and writes patches and a manifest to `OUT`.
3. `local verify` compares every ref of the real repository (and its remote) with the ones taken at prepare, and saves the output.
4. `review check` reads the series and the manifest (the shape of the patches and the commits, paths against SCOPE, the scrub when the project has one); a review run returns a report instead and is checked for its findings and verdict line.
5. `review apply` puts the series on `agent/<slug>`, then `feature merge` brings it into the feature branch.
6. `local clean` removes the run and its temporary directory; `feature verify` and `feature finish` end the feature.

A cloud run replaces step 1 and 2 with `start` and a session of an instance (`lib/session.sh`) and is collected with `collect`.

## What is advice and what is checked

- The member guard (`lib/guard.py`) is a best-effort text check of a member's tool calls. It is advice that refuses the ordinary
  ways; a member runs as the lead's operating-system user, so it is not a boundary. A real sandbox is not yet built.
- The checks are what run after the member: `local verify` (refs), `review check` (series, SCOPE, manifest, scrub),
  `feature verify` and `release verify` (the project's gates or test command, run by qargi), and the lead's own re-run of the DONE command.
- A plan token binds the plan the person saw to the apply (a hash of the state the plan describes); `--approved` words are
  recorded in `audit.log` and never verified, so they show that a plan was applied, not that a person read it.
- The marshal is advisory: the flow verbs ask it before they act, but when it cannot be asked they say so and go on. Integrity (signed records) is off by default.
- The audit log is appended by the verbs that call `audit_log`; it is not signed and the same user owns the file.

## What is neutral data and what is per platform

- Neutral, in data: the command table, provider definitions (hook protocol, tool names, render targets, dispatch argv, barrier
  kind), pack content and `compatible_providers`, methodology files, role and contract text, the guard's decisions (they see a
  neutral call built from the hook data).
- Per platform, in code: the adapter of the `claude-code` runtime; the `claude-platform` cloud surface, which most cloud verbs
  still call directly through the vendor CLI (`ant`), so a second cloud provider cannot be added as data yet (`tests/neutral-allowlist.txt` lists what is left).
- Per host: Linux and GNU tools throughout (`readlink -f`, `sha256sum`, `flock`, `/proc`, `stat -c`, `date -d`); state is per machine under the home directory.
