# Architecture

How qargi is put together, for someone who changes it. Every statement here can be found in the code; the paths are the ones
to grep. See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the workflow and [Help, manual page and completion](../reference/README.md#help-manual-page-and-completion)
for what is generated from the command table.

## Where each kind of record lives

User-installation configuration and state default to `~/.qargi`. Development runs can use `<checkout>/.qargi`.
`QARGI_HOME` replaces the root, and `QARGI_CONF` and `QARGI_STATE` name the two halves separately
(`lib/paths.py`, `lib/lib.sh`). Qargi creates these directories with mode 700. Repo-tier memory can be committed
in the project, and shared marshal records are commits on its remote as described below.

Configuration (`config/`), what you set up and rarely change:

| Path | Holds |
|---|---|
| `install.json` | the tool root `install.sh --user` recorded, with its version and whether it is linked or copied; decides installed run or dev run |
| `install.d/` | the install manifests (`runtime-NAME`, `shared`, `project-N-NAME`): every path `install.sh` wrote, for `--uninstall` |
| `install.lock` | held by `install.sh` while it reads or changes the manifests |
| `projects/NAME.json` | a project's stored answers (repository, branches, models, gates, release, ...) |
| `instances.json` | the registered cloud instances |
| `agents.json`, `agents/PROJECT/` | the named members and the canonical copy of each one's render |
| `credentials/` | token files, mode 600 |
| `packs/` | the library of skills, tools and providers, with `accepted.json` |
| `roles/`, `methodologies/` | your own roles and methodologies, beside the ones the tool ships |

State (`state/`), what the commands write as they run:

| Path | Holds |
|---|---|
| `audit.log` | one JSON line per action that calls `audit_log`, containing time, verb, detail and supplied `--asked` and `--approved` words, with command-specific coverage |
| `local-runs.jsonl` | the lead's registry of local runs, written by `local prepare`; the only record `verify`, `clean` and `review apply` believe about a run |
| `runs/ID/` | the lead's copy of a verified run's output, so `review apply --from-saved ID` works after the run directory is gone |
| `apply/ID.json` | the record that a run was applied, and how far the apply got |
| `scrub_ok/ID` | the hash of a series whose take-in scrub passed |
| `finish-intent/` | the intent of a `feature finish` or `release finish`, so a re-run after a death completes it |
| `conflicts/` | the kept worktree of a merge that conflicted, to resolve and resume |
| `suite-logs/` | the last whole-suite log and gate list of each project and branch |
| `ref-journal.jsonl` | recorded lead branch moves used by the snapshot comparison acceptance rules |
| `features/`, `marshal/` | the marshal's local records, and per project its switch and trusted signers |
| `sessions.json` | the tracker of cloud sessions (role, profile, model, effort, state) |
| `campaigns/UUID/` | declaration objects, the publishing head and permanent local writer lock (`lib/campaign_store.py`) |
| `render/`, `providers/`, `env/` | rendered packs, provider verification records, environment records |

With the shared marshal backend the records of open features are also commits on `refs/qargi/features/NAME`, and finished ones
on `refs/qargi/done/NAME`, of the project's remote (`lib/marshal_refs.py`).

## The layers

- `bin/qargi` is the dispatcher. It answers `help`, `version`, completion and the guard itself, wraps `--json`, runs a
  preamble (`lib/help.py`: dev-run banner, the project implied by the current directory) and then `exec`s the script of the command.
- `lib/commands.py` is the one description of the commands, verbs and options. Help, the manual page and completion are generated from it.
- `lib/campaign.py` routes native campaign reports; its member-safe `check --spec` imports no store or configuration. State commands are lead-only. `lib/campaign_doc.py` owns the pure closed schema, normalization and parent-relative transitions; `lib/campaign_store.py` owns private local storage, CAS publication, durability outcomes and bounded ancestry proofs. See [Campaign records v1](../reference/campaign-records.md) for the normative contract.
- `lib/*.sh` are the verbs. Each takes its arguments, calls `lib/lib.sh` helpers (state paths, `audit_log`, `need_plan`, locks) and git.
- `lib/*.py` are the engines that need real parsing or data structures: the guard, the marshal, packs, the provider and
  render machinery, the take-in check, help, the site generator.
- Providers are data: `lib/providers/NAME.json` describes a runtime (its tools, hook protocol, barrier, dispatch, renderers).
  Code reads the definition; the adapter of a runtime (`lib/providers/claude-code/adapter`) is the code for what data cannot say.
- Packs are skills and tools with a content hash, imported, sealed and linked by scope. `packs/` ships ten skills, including opt-in [release documentation review guidance](../../packs/skills/release-docs-review/SKILL.md). Distribution and informational proposal hints leave activation to the existing approval workflow.
- A methodology (`methodologies/NAME/methodology.json` and `scaffold/`) is data read by `project new|attach|adopt`; see
  [Flow](../flow/README.md#methodologies) for what it configures.
- `skills/`, `roles/`, `contract/` and `agents/` are prompts: the lead's skills, the role texts, the member contract and the
  neutral member definition. They are text, tested for size and duplicated sentences (`tests/skill-budget.txt`).

## The life of a local run

`lib/member_skills.py` implements default-off canonical role-specific command snapshots. Direct project set/unset of `packs.member_skills` refuses; whole-file enabling or boolean changes also refuse, while unchanged input and removal/narrowing remain supported. Members cannot mutate the dedicated flag through its public verb or helper. The enable plan inventories currently dispatchable known work roles, including library roles without project entries, excludes coordinator lead and distinguishes invalid metadata; it does not freeze future role configuration. Prepare freezes bounded nofollow copies inside exclusive private lifecycle authority. Only included compatible skills require approval and passing current review; excluded bodies confer no authority. `prepared.skills` is a closed manifest reference/hash beside the unchanged prepared request; bodies stay outside lifecycle JSON/stdin. Preflight checks current request/composition, review and selection drift read-only. Save, verify and saved-copy retrieval instead prove original manifest identity, full bytes, normalized modes and lifecycle generation, independently of current configuration or review rules. No snapshot adds no new current-configuration dependency at verification. Integrity grants no launch permission.

After native attempt begin, allocation and partial copying occur through held descriptors inside the controller-only lifecycle directory. An allocation intent records the original private and delivery parents before mkdir; the exclusive private subtree owns partial allocation recovery, never a directory discovered in RUN. Persisted identity precedes atomic no-replace publication onto the same filesystem. Validate the published identity before launch. Cleanup requires recorded process-group quiescence, holds the original parents and directory descriptors, records intent, stages back into private authority and checks the staged identity before one-filesystem deletion. An absent delivery under its identity-matched original parent can retire the record after begin; read-only dry-run never retires it. Interrupted copy, staging, deletion and retirement retain recoverable private phases. Foreign/replaced delivery or staged-identity mismatch preserves data and evidence and refuses with inspection/re-prepare guidance. This cooperative Linux boundary trusts controller-only private state and the OS, excludes escaped process groups, arbitrary hostile same-user/root mutation and device/inode reuse as an independent proof. Delivery and private state must share a filesystem and support atomic no-replace rename; select `--scratch` accordingly. RUN mirrors confer no authority. See [the delivery contract](../../skills/qargi-packs/member-skills.md) for bounds and upgrade boundaries. Generic dispatch stays provider-neutral; structural support and actual loading qualification remain separate.

1. `local prepare` makes a bare copy of the repository and removes that copy's origin. It clones the bare copy into the run directory, leaving the clone's origin pointed at the bare copy with push URL `DISABLED`. It supplies a credentialless Git wrapper, records the run in `local-runs.jsonl`, snapshots the real repository's refs and writes the task block (`lib/local.sh`).
2. A member works in the clone under its runtime's configured protections. Write members deliver patches and a manifest in `OUT`. Report-only runs return a report without patches. For command runtimes using `{final_message}`, the lead's controller publishes the final message as `OUT/report.md`. For a registered read-only run with an ok outcome, a published report and no patches, it also writes a report-only manifest from lead-owned records (`lib/local_run.py`). The member follows its runtime's output rules, which can forbid writing even to `OUT`.
3. `local verify` compares snapshots of the real repository's local refs and origin's heads and tags, excluding `refs/qargi/`, and saves passing output. Initial strict comparisons accept differences including journaled lead moves, remote-tracking refs following origin, fetched tags, parking-branch fast-forwards to develop and qualifying bridge branches. The full set of cases is implemented in `lib/local.sh`'s `compare`. Runtime-owned ref patterns (`runs.owned_refs`) are frozen in the lead's registry at prepare and apply in either phase, subject to the matcher restrictions. After the first passing verify, comparisons against the verified snapshot also accept unjournaled fast-forwards of develop, master and `agent|feature|release|hotfix/*` branches, and new branches in those slash namespaces. These comparisons cover the recorded destinations and observation times. Transient pushes and activity at other destinations require separate evidence.
4. `review check` reads the series and the manifest (the shape of the patches and the commits, paths against SCOPE, the scrub when the project has one); a review run returns a report instead and is checked for its findings and verdict line.
5. `review apply` puts the series on `agent/<slug>`, then `feature merge` brings it into the feature branch.
6. `local clean` removes the run and its temporary directory; `feature verify` and `feature finish` end the feature.

A cloud run replaces step 1 and 2 with `start` and a session of an instance (`lib/session.sh`) and is collected with `collect`.

The wrapper uses a run-specific home, disables global and system Git configuration, clears inherited credentials and disables Git SSH transport and prompts. Together with the disabled push URL, these protections block ordinary pushes through the supplied setup. They do not prove that a push is impossible. Runtime sandbox and guard behavior has its own qualified scope, described for [members and providers](../members-and-providers/README.md) and [Codex](../members-and-providers/codex.md).

The memory packet uses the clone's committed repo tier as its base and directs members to avoid tier writes and propose new or changed notes in the report for the lead to file. It lists other configured tiers and their locations. Filesystem permissions depend on the runtime and run class. A write member can have a writable clone. `lib/tiercontext.py` reports tier availability and uncommitted repo-tier changes. Tier precedence and locations are described in the [memory tiers documentation](../skills-tools-and-memory/memory.md#memory-tiers).

## What is advice and what is checked

- Campaign records have declarations-only authority: source observation is not performed, acceptance is not recorded, measurements are not computed and invalidation policy is undecided. Briefings and evidence links remain supplied claims and unresolved pointers. Fresh actual-dependency review is required before merge acceptance, but these records do not enforce it. The store qualifies cooperating local writers, not orchestration or a provider adapter.
- The member guard (`lib/guard.py`) is a best-effort text check of a member's tool calls. It is advice that refuses the ordinary
  ways. A member runs as the lead's operating-system user, so the guard provides no operating-system isolation. The [Codex runtime](../members-and-providers/codex.md#platform-and-sandbox) uses a sandbox with separately qualified limits.
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
