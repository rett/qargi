# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Ordinary clean retains the read-only product refusal independently of refs-only observation: unexpected patches or a bundle preserve the run even with zero extra clone commits. An unchanged internal refs verdict grants neither verification nor artifact acceptance; explicit discard deliberately recovers it and reports actual refs.
- Inspection failures now show sanitized reasons in run, verify, review check and clean. The 0.2.13 limits stay fixed: 512 MiB copied metadata (the whole object store included), 1 MiB config, 100,000 traversal/read steps, 64 directory levels and 60 seconds for copy traversal and each Git subprocess. Ordinary prepared clones are supported only within those bounds. Ordinary clean preserves every artifact when worktree state is unknown, including when commit inspection succeeds; explicit discard remains deliberate recovery after preserving wanted work.
- Inspection disables replacement objects, preserves the difference between valueless (true) and explicit empty (false) Git booleans, and uses a minimal format-0 config for SHA-1 while keeping explicit SHA-256 format support. Regressions include replacement refs and a same-length, restored-mtime racy-index case with a negative control.
- Classless registered legacy discard reports the authoritative refs verdict, including unexplained real ref changes. Its internal refs-only observation neither verifies the run nor saves accepted output or grants class permissions; ordinary unknown-class refusal remains.
- Unexpected runner failures retain nonsecret start/process and home metadata, cleanup status and refreshed-file residue for list and verify. Retry checks the original group for every dispatch outcome and refuses known or unknown survivors until quiescence can be established, without signalling a potentially recycled PID. A partial home setup whose cleanup also fails keeps an explicit cleanup note alongside the planned link names.
- `feature finish` validates project identity/answers and strictly parses and enumerates the same registry snapshot. Missing/malformed answers, dangling/unreadable/malformed registries and reader failures refuse; empty exit 1 and traceback output are distinguished from valid open-run rows. General diagnostic readers remain tolerant. This removes the double-read path but provides no coordination of new preparation through the eventual merge.
- Local runs stop remaining members of the original process group before removing authentication links and inspecting output, including on normal exit and unexpected runner errors; surviving members fail an otherwise successful run. Unexpected errors retain the original exception even if cleanup also fails, and an unreadable survivor count stays unknown.
- The lead verbs and guard MCP policy validate the decoded JSON class against the exact supported registry strings before shell decoding and preserve malformed runs for investigation. Explicit `clean --discard` remains a recovery route for known registered legacy runs without a class; it intentionally drops evidence and cannot discard unregistered runs. A member's `review check` requires its marker to resolve to the inspected run, then checks structure without lead registry authority, verification, scrub marks or cache. Lead review checks validate class before renewing the lease. Pre-existing guard shell/write tightening still consults the member class file; those paths and their heuristics are unchanged.
- Clone inspection reads a bounded private metadata copy in trusted lead state with a minimal configuration and an absolute Git resolved once from the lead's controlled PATH, so even a newly inserted filter cannot execute during inspection. The copy preserves index timestamps for same-length write detection and supports SHA-1 and SHA-256. Unsupported metadata layouts and inspection failures stay unknown; ordinary clean preserves unknown commit state. Copies may combine concurrent states and do not contain escaped sessions.
- Expected setup refusals retain planned sign-in link names if partial cleanup fails, so list and verify can locate residue. Unreadable process-group probes no longer prevent TERM-to-KILL escalation; an unreadable final count remains unknown. Cleanup records closure without granting verification, including when no prior verify was run.

## [0.2.12] - 2026-11-11

### Added
- The model catalog of the family `openai` (`lib/providers/catalogs/openai.json`), the table a runtime of that family names with `models.catalog`: the tiers fast `gpt-6-luna`, balanced `gpt-6.1-terra`, deep `gpt-6.1-sol` and frontier `gpt-6-astra` (ids of the pattern `^gpt-[a-z0-9.-]+$`, passed as ids, with no alias), and the effort levels `low` to `max` under the same names. No tier is verified yet (`verified_on` is null until a real run uses it); the vendor's sixth effort level, `ultra`, has no qargi level and is not mapped.
- The local runtime `codex` (`lib/providers/codex.json`, data only, no code of its own): a project whose local provider is `codex` runs its members with `qargi local run`, which starts `codex exec --json --ephemeral --ignore-rules --strict-config -C CLONE [-m MODEL] [-c model_reasoning_effort=EFFORT] -o FINAL` in the run's clone with the prompt on standard input, adding `--sandbox workspace-write --add-dir OUT --add-dir CLONE/.git` for a write run and `--sandbox read-only` for a read-only one (`--dry-run` prints it). The clone's `.git` is added because workspace-write keeps it read-only, so `git add` failed on `index.lock` and a build member could not commit (a live check with codex-cli 0.167.1 showed `git add` and `git commit` working with it). The cost of that grant: a write member can change its own clone's git configuration and hooks. The clone's only remote is the run's own bare copy, with its push URL disabled, the sandbox has no network, the lead takes the work from the patches in OUT, and `qargi local verify` compares the real repository's refs; a read-only run never gets the grant. A path of the run in a definition's argv (`{clone}`, `{out_dir}`, `{run_dir}`, alone or with a path after it, such as `{clone}/.git`) must stay inside its directory and pass through no link, or `qargi local run` refuses the run: a `.git` an earlier member left as a link would otherwise point the sandbox's writable directory anywhere. The read-only barrier is that sandbox alone (`barrier.kind` `sandbox-args`, claimed `partial`): it holds a member's shell commands, not its reads, and no guard hook runs. Headless dispatch, the read-only barrier (partial) and the token report are verified by live checks with codex-cli 0.167.1 on 2026-11-11 (`verified_on` and `source` in the definition name the evidence), so a review role on `codex` runs with the barrier's note and needs no `provider accept`; the model and effort overrides (accepted in a run, but no event names the model or effort used), skills and MCP stay unverified and count as not supported. The member's last message goes to a new file of the run (`FINAL`, below) and becomes `OUT/report.md`, and the run's contract addenda (`lib/providers/codex/local-run.md`) say so. `--ignore-rules` keeps every Codex execpolicy rules file out of a run (a rule can let a command run outside the sandbox), and `--strict-config` makes Codex refuse a key of the run's configuration file it does not know, so a baseline key a later CLI renames stops the run instead of being ignored. A Codex member gets the MCP tools of its role and the runtime's baseline in the configuration file of its run home (below), and no resumed session. It gets no qargi skill: its `CODEX_HOME` and `HOME` are the run home, which has no skills directory, its clone carries only the skills the repository commits under `.agents/skills` (a session's untracked links do not travel to a clone), and the baseline turns Codex's bundled skills off, so a member receives the contract and the task, and never a lead-management skill (a test runs a member with `qargi-flow`, `qargi-verify` and `qargi-task` linked where a Codex lead finds them and checks that it sees none). `qargi provider notes` answers `spawn`, `session-model`, `exploration`, `skills-dir`, `identity` and `commands` for it.
- A command runtime is told where to write the member's last message with the placeholder `{final_message}`: a file in a directory of the run that `qargi local run` makes new for each run (`RUN/final.XXXXXXXXXXXX/message.md`, mode 700), never a file of OUT, so the runtime never writes into OUT itself. When the process has ended the file is taken only as a regular file with one name, of UTF-8 text, at most 1 MiB, opened without following a link or waiting on a pipe; it is published as `OUT/report.md` by renaming a new file (mode 644) over that name, so a link, a pipe or a second name a member left there is replaced and never written through. A link, a pipe or a second name at the private file is removed (what it points to is untouched), a directory there is left, and a file that is too large or not text is kept for you to read; none of them is published. The output says what became of it (`REPORT=OUT/report.md (N bytes ...)` or `REPORT=none: WHY`), and `RUN/dispatch.json` records it (`report`: `state`, `why`, `bytes`, `kept`, `previous`). On `--again` the report of the earlier run is set aside as `OUT/report.md.previous` just before the member starts: a run that publishes a report replaces it, or one an earlier rerun set aside (`PREVIOUS_REPORT=replaced`), and a run that publishes none, a failed or refused one included, leaves it there (`PREVIOUS_REPORT=kept as ...`), where neither `review check` nor `local verify` takes it for this run's report. A `report.md` that is not a plain file of its own (a link, a pipe, a directory, a second name) refuses the run before anything starts. `--dry-run` prints `FINAL_MESSAGE=`. The `codex` runtime passes it as `-o {final_message}` in place of `-o OUT/report.md`, which let the vendor CLI write through whatever an earlier member had left at that name. The codex stub of the conformance suite now writes a last message where `-o` says, as the CLI does.
- A read-only run whose report is the runtime's last message (`{final_message}`, the `codex` runtime's `-o`) gets its manifest from the lead: `qargi local run` writes `OUT/manifest.json` in the minimal report-only format of `qargi review save` (`status`, `base`, `commits: []`, the report in `artifacts`) with a `run` object of what the lead recorded (the run's id, role, runtime, class, the model and effort qargi passed, start, seconds, exit, outcome and `packaged_by`), taken from the lead's registry and from `RUN/refs.before` as read before the member started, never from the member. A Codex reviewer, which may write nothing, OUT included, had a report and no manifest, so `qargi review check` failed every one of its runs. The manifest is written only when the run's outcome is ok, its report was published and OUT holds no patch; otherwise `MANIFEST=none: WHY` says why, and a missing report, a report without a Findings heading or a valid last verdict line, and patches in a read-only OUT fail `review check` and `local verify` as before. It claims no test and no verdict (`done.exit_code` null, no gates); its status is `BLOCKED` when the first line of the report says `BLOCKED`, also under Markdown marks or as `Status: BLOCKED` (`**BLOCKED**`, `# BLOCKED`, `**Status:** BLOCKED`). The manifest of an earlier run is set aside as `OUT/manifest.json.previous` with the report (`PREVIOUS_MANIFEST=`), and a `manifest.json` there that is not a plain file of its own refuses a read-only run before anything starts. A write run's manifest stays the member's. `RUN/dispatch.json` records `manifest` (`state`, `why`, `previous`). The Codex addenda and the providers page say so.
- A runtime started by `qargi local run` can have a home directory of its own (`dispatch.home` in `lib/providers/schema-2.json`: `{env, dir, link: [{from, to}]}`): the member gets `RUN/home/DIR` in the variable `env`, and each file `from` of your home is linked into it as `to` when the run starts and unlinked when the run ends, also when it fails or times out. The file is never copied; `--dry-run` prints `HOME_ENV=`, `HOME_DIR=` and `HOME_LINKS=` with the link names only, and `dispatch.json` records the names, never a source path or a value. A source that does not exist is not linked (a note says so). What the runtime does to the link during the run (a sign-in it refreshes) loses nothing, and qargi never writes the source: written through the link, it lands in the source, which qargi cannot prevent (a note); the link deleted, the source is untouched (a note); the link replaced by a file of its own (an atomic replace), that file is kept as `NAME.from-run` (mode 600) in the run home, never written over the source (another run, a session of the runtime or a sign-in of yours may have written it meanwhile), named in a `HOME_RESIDUE=` line and in `home.residue` of `dispatch.json`, with a note that says whether the source is still the file it was when the run started (the same real path and the same sha256, taken in memory then and never printed or recorded); you reconcile it yourself (`docs/members-and-providers/codex.md` says how), `qargi local list` and `verify` name it and `qargi local clean` removes it. No note or record holds a value. A variable of the run home (`CODEX_HOME`) set in your environment to another directory is a note, without its value: the run links the sources the definition names. The directory is made and the links removed without following a link a member may have put in the run directory. `provider check`, `provider import` and `local run` refuse a variable that qargi sets or never hands on (`HOME`, `PATH`, `GIT_*`, `QARGI_*`, `XDG_*`, the loader variables and the others `env_pass` refuses, and `LANG`, `LC_ALL`, `TZ`, `TERM`) or that `env_pass` also names, a `dir` outside the run home, a `from` that is not a plain path under your home or that lies in qargi's directory, a credential store of your other tools (ssh, gpg, git, forges, clouds, keyrings), a startup file of your shell (`~/.bashrc`, `~/.profile` and their kin), what your desktop or service manager starts (`~/.config/autostart`, `~/.config/systemd`, `~/.config/environment.d`) or `~/.local/bin` (checked again where the file really resolves when the run starts), a `to` that is not a plain file name, more than 8 links, an unknown key, and a run home on a runtime that is not a command runtime. The `codex` runtime uses it: `CODEX_HOME` is `RUN/home/.codex` with your `~/.codex/auth.json` linked in, so a member keeps your Codex sign-in and plan, and its Codex loads nothing else of your Codex home (its settings, sessions and hook trust). This is configuration separation, not secrecy: the sandbox holds writes, not reads, so a member can still read the linked file and the rest of your `~/.codex` (sessions, history) by path.
- `qargi packs apply --target codex PROJECT` renders the tool packs of a project whose local runtime is `codex` into `config.toml`: one `[mcp_servers.PACK]` table per tool pack with its `url` and `enabled_tools`, the tools a member may call for the roles the pack reaches (the policy of the member tool lists: never an `always_ask` tool, and for a role of the read-only class only a declared read). A pack with no such tool gets no table, and the plan lists the tools of each table or says that the table is left out. Two tools Codex would name alike are refused as for Claude Code. The format is data: `resources.mcp.format` `toml` is written by a small TOML writer (tables, texts, whole numbers, booleans and lists of texts, every text escaped; anything else is refused), and `resources.mcp.tool_lists` (`allow`, `deny`: JSON pointers into the server entry) in `lib/providers/schema-2.json` says where a runtime takes the tools of a server. `provider check` refuses tool lists that are not pointers, that land on a key the entry template sets, or that come without a `permission_rule` naming `{server}` and `{tool}`, and an entry template that TOML cannot hold. `codex` claims `mcp` (`yes`, not yet verified) and has the render target `codex` and no launch line: `apply` prints `launch: none` instead of failing. The render needs the `skills` claim of `codex` verified, as every render does, so until then `apply` exits 3.
- `qargi local run` records the tokens a command runtime reports on its standard output: a definition's `dispatch.output.usage` (the keys of the transcript usage rule, `select`, `skip`, `tokens`, `fields` and `model`, now one node `usage` of `lib/providers/schema-2.json` that both use) picks the JSON lines of `OUT/transcript` that report a turn's usage, and when the run ends each field is added up over them into `RUN/dispatch.json` (`usage`: `events`, `tokens` per field, and `model` when the rule names it) and printed as `USAGE=input_tokens=N ... (K events)`, or `USAGE=none` when no line matched. Only whole numbers count; a line that is not JSON is passed over. A field that no matched line reports is not recorded as 0: it is left out of `tokens`, named in `unreported` and on the `USAGE=` line (`not reported, so not counted: ...`), since absent is not zero. `provider check` and `local run` refuse a rule on an output that is not `jsonl`, a rule without `tokens` or `fields`, a key that is not a JSON pointer where one is needed, and an unknown key. The `codex` runtime adds up the `usage` of its `turn.completed` events (input, cached input, cache write, output and reasoning output tokens) and claims `cost_report` `partial`: tokens only, since a ChatGPT sign-in reports no money per run, and not verified until a real run.
- A member started by `qargi local run` gets its own MCP file when its runtime declares `dispatch.run_config` (`{in, file}` in `lib/providers/schema-2.json`): when the run starts, the file is rendered from the runtime's `resources.mcp` for the run's role, as the lead's registry records it (an ability file rewritten in the run directory changes nothing), and the run's class: each server lists the tools a member may call (never an `always_ask` tool, under the read-only class only a declared read), and a pack with none gets no server. It goes into the run home (`in: home`) or `RUN/config` (`in: run`), mode 600, never through a link a member may have put there; the new placeholder `{run_config}` is its path for a runtime that takes it by a flag, and has no value when no tool pack reaches the role: then nothing is written, and a file of that name left there is removed. `--dry-run` prints `RUN_CONFIG=` (the path, or `none` with the reason) and `RUN_CONFIG_TOOLS=` (the tool names), and `dispatch.json` records the path, the role and the tool names; the servers' addresses are printed nowhere and no vault value is read. `provider check` refuses it on a runtime that is not a command runtime, in the home without `dispatch.home`, under the name of a link of the run home, and without `resources.mcp.tool_lists`. A definition can give the file a `baseline` (`dispatch.run_config.baseline`): settings of the runtime's own configuration, written at the root of every run's file whatever tools reach the role, so a run with no MCP server and a run with one get the same settings; with one the file is written for every run, `--dry-run` prints `RUN_CONFIG_BASELINE=` and `dispatch.json` records it in `run_config.baseline`. `provider check` refuses a baseline that is empty, holds an empty object or a value the file's writer does not take, or sets anything at or below `resources.mcp.root_pointer`, which only the tool packs fill. The `codex` runtime uses it: a member's MCP tools and its baseline are the `config.toml` of its `CODEX_HOME` in the run home, the user-level configuration of its Codex, so `codex exec` gets no `--ignore-user-config`, which would drop that file too (your own Codex configuration stays out of the run, because `CODEX_HOME` is the run's). The baseline sets `approval_policy` `never`, under `workspace-write` no shell network and no `/tmp` (the run's `TMPDIR` stays writable), hosted web search `disabled`, the features `apps`, `plugins`, `remote_plugin`, `hooks`, `computer_use`, `browser_use`, `in_app_browser`, `image_generation`, `tool_suggest` and `skill_mcp_dependency_install` off, and the bundled skills off; it holds no trust entry, so the clone's own `.codex/` (its configuration, MCP servers, rules and hooks) is not loaded, while its `AGENTS.md` is. codex-cli 0.167.1 reads each key (seen offline: a value of the wrong type is refused naming the key, the features list shows them off, the prompt input says the approval policy is never and lists no bundled skill, and `codex sandbox` with those keys refuses `/tmp` and the network); that each holds in a real run is not yet verified, and a system-wide or managed Codex configuration is not excluded.
- `qargi provider check` has a case for the barrier kind `sandbox-args`, `barrier-sandbox-args`: the argv `qargi local run` builds for a read-only run must carry the definition's read-only arguments (its `class_argv` and `{"class": "read-only"}` groups), set their flags nowhere else in the argv, where they could be overridden, and carry no flag with its value of the write class's arguments, a write grant such as `--add-dir CLONE/.git` (conformance case 11 is the same case). The case can only hold `read_only_barrier` back: when it fails the capability stays unverified, and when it passes it verifies nothing, because it shows what qargi passes and not that the runtime's sandbox holds, which is still recorded with `qargi provider attest`.
- The conformance suite (`bash tests/conformance.sh NAME`, `lib/conformance/run.sh`) checks a command runtime, one whose `dispatch.mode` is `command`, which it used to skip when the runtime had no adapter. `qargi local run` starts the runtime's stub (`tests/providers/NAME/stub`, or `--stub DIR`) in place of the command: case 11 is the `sandbox-args` case of `provider check`; case 12 makes a write run and a read-only run and checks that the stub gets the argv `RUN/dispatch.json` records, the prompt with the task block and the class, the arguments of its own class and none of the other's, that `OUT/transcript` is what it printed, and that the usage rule adds up a usage from it; case 13 checks the command's environment: its own `HOME`, no variable of yours that `env_pass` does not name, and the run home's variable and links while it runs, with the linked file's content and source path in no output or record; case 14, for a runtime with a `dispatch.run_config.baseline`, checks that a write run and a read-only run each get the configuration file holding the baseline and nothing else, found by the command in its run home while it runs and recorded in `RUN/dispatch.json`. The adapter cases 1 to 10 are left out, with one line, for a runtime with no adapter. `codex` has its stub, which replays the JSON lines of a `codex exec --json` run with two `turn.completed` usages, and `bash tests/conformance.sh codex` is a step of the suite.
- The review of a provider pack (`qargi provider import`, `seal` and `enable`) shows the runtime's run home: the variable it is named by, its directory under the run's home, and each file of your home it links into every run, as the definition names it (`run home (dispatch.home): CODEX_HOME is RUN/home/.codex; files of your home linked into it for each run: ~/.codex/auth.json as auth.json`). It names the files only; it never reads them or shows where they resolve.
- The `qargi-providers` skill says how a runtime held by `sandbox-args` is checked live (`verify.md`): its barrier with the runtime's own sandbox command and no model call (for `codex`, `codex sandbox`, at no cost), one smoke run on the fast tier at `low` effort for the sign-in through the run home's link, the report file and the tokens (a model or effort override is verified only when an event names what was used), and, before members rely on it, a sign-in rewritten through the link, the MCP tool names, `enabled_tools` hiding a server's other tools and commits under `workspace-write` with the clone's `.git` added; a shipped runtime records each result as `verified_on` and `source` in its definition, and what the shipped `codex` has verified and what not. Its definition page names `dispatch.home`, `dispatch.run_config`, `dispatch.output.usage` and `resources.mcp.tool_lists`.
- The addenda of a Codex run (`lib/providers/codex/local-run.md`) tell the member that its MCP tools are the ones its run's configuration lists, and no others. The providers page has a table of what the `codex` runtime is and is not (its barrier the operating-system sandbox, claimed partial; MCP held by `enabled_tools`; no guard hook; sign-in by a link; tokens only; one local runtime per project, so no mixed runtimes), and the models page its catalog `openai`.
- `qargi local run` ends a run cleanly however it ends, and says how. It writes `RUN/dispatch.json` when the run starts (`outcome` `running`, the process ids of the runner and, once started, of the member, and the run home's links) and again at the end, so an earlier run's outcome never stays: a command that cannot be started is `transport` (exit 4) and a run home, MCP file or transcript that cannot be made is `refused`, each with its `error`. SIGINT, SIGTERM and SIGHUP to the runner stop the member's process group (TERM to the group, which is then watched, not only the member, for up to 5 seconds, so a child that ignores TERM after the member ended on it is not missed; then KILL for what is left, watched the same way), remove the run home's links and record `interrupted` with the `signal` and `group_left`, the number of the group's processes still alive (exit 128+N); the output says the group was stopped only when none of it is alive, and otherwise how many of its processes survived (the same for a run past its bound). A process that moved to a process group of its own, and one left running after the member ended by itself, are not stopped; one that comes after the member ended is only noted, and a signal the runner was started with ignored (`nohup`) stays ignored. SIGKILL cannot be caught, so the start record stays: the next start refuses while that runner or its member still runs (naming the member's process group to stop; the runner is told by the run's real path, also when it was started by a relative one from another directory) and otherwise needs `--again`, which replaces the links left in the run home and removes stale last-message directories; `qargi local list` (a `residue:` line under the run) and `qargi local verify` (a note) name the links left, and `qargi local clean` removes the run with them and says so. A run home the member moved or replaced is searched for the links qargi made, which are removed where found; a link not found is named, never said to be gone.
- The documentation page Codex as lead and as member (`docs/members-and-providers/codex.md`): what is verified live, by what, on which CLI version and date, and what is not; the platform (qargi runs on Linux, where codex-cli's sandbox is bubblewrap; its macOS sandbox plays no part), what a member run loads and what it does not (your Codex configuration, the clone's untrusted `.codex/`, a system-wide configuration that is not excluded), the run baseline key by key, what a member can reach (files, `TMPDIR`, the shell's network against hosted search and MCP, git, no guard hook, the sign-in it can read), its skills and MCP tools (raw names in `enabled_tools`, `mcp__` names for the model, the limits for an authenticated server), the output of a run (report overwrite on `--again`, the lead's manifest of a read-only run, refused uncommitted changes, token-only usage where an absent count is not zero), a Codex lead's setup (`install.sh --user --runtime codex`, what a Codex session lists, what is not verified), a complete build and review run from `prepare --task-file --done` to `local clean`, and sending a message to a Codex session with `codex queue`. `qargi provider notes message` gives a lead the `codex queue` line and says a queued message is never an approval. The providers, models, members, install and local-session pages and the `qargi-providers` skill say the same where they name Codex; the models page says that a catalog id is not model access and that the tier order is no benchmark.
- A command runtime can declare the places its sandbox hides from the member (`dispatch.hidden_paths` in `lib/providers/schema-2.json`: `prefixes`, per class the run paths it `shown` anyway, and a `note`), and `qargi local prepare` and `qargi local run` refuse a run whose member would not see a path it works with (exit 2, before anything is made or started; a dry run too), naming each path (and its real path when a link leads there), the prefix and the fix: `--scratch` on another filesystem (a directory under your home, such as `~/.cache/qargi-runs`; one under `/tmp` is not advised, since no check has shown a run there working), or `QARGI_RUN_TMP` for a hidden TMP. A read-only member works with CLONE, CONTRACT and GIT, a write member also with OUT and TMP; the task block reaches it in its prompt. `codex` declares `/dev`: its Linux sandbox mounts a `/dev` of its own, so a run under `/dev/shm` left a read-only member without its clone and contract and a write member without its contract, and nothing said so. A codex run with `--scratch` on disk works, its TMP on `/dev/shm` included (a write run's TMP is bound into its sandbox; a read-only member writes none). The conformance suite has a case for it (15).
- `qargi local run` notes a change a member made to what git in its clone would run. A member that can write the clone's `.git` (the write class of `codex` adds it as a writable directory) can set a hook, `core.fsmonitor`, an alias or a filter driver there, which runs as you when you run git in that clone. For every run whose argv grants the clone's `.git`, and every run whose class gets no sandbox arguments from its runtime, the lead reads `.git/config`, `.git/hooks/` and `.git/info/` before the member starts (without following a link or running git there) and compares them when it ends: a configuration key added, changed or removed, other than what `git branch` sets (`branch.NAME.remote`, `merge`, `rebase`, `description`), and an entry of `hooks/` or `info/` added, removed or changed, are named in a `GITDIR=changed:` line and recorded in `git_dir` of `RUN/dispatch.json` (`watched`: `granted` or `unsandboxed`, and `changed`), by key and entry name, never a value. Nothing is restored. The line, the `WORKTREE=uncommitted` refusal and the `qargi local verify` message for a run that did not collect now say never to run git in a write member's clone: take the work from the patches in OUT, copy files out, or make a clean copy first with `git clone --no-local`, as git(1) advises under SECURITY. They said to take the change or the commits from the clone yourself.

### Changed
- `qargi provider notes skills-dir` for `codex` names `~/.agents/skills` beside `~/.codex/skills` and the install that links qargi's skills there, and says a member run loads only the skills its repository commits, where it said a member ignores the user's configuration. The documentation no longer says that a run's `config.toml` is the one configuration file a Codex member reads, or that an agent is given no way to push: the pages state what holds instead (a git without credentials, a remote with its push URL disabled, no network for a sandboxed member's commands, and `qargi local verify` comparing the real repository's refs).
- The README says what qargi supports of an agent and a push (a git without credentials and a clone whose only remote is a copy with its push URL disabled, so an ordinary push has nothing to reach or authenticate with, and a check that the real repository's refs did not move), where it said an agent is given no way to push. Its quick start, and the members page, say that a project on `codex` has no `qargi agent add` and runs each task with `qargi local prepare` and `qargi local run`.
- `qargi help local` and the manual page call a local run one whose git has no credentials (`Prepare, verify, close, list and clean a local run, its git without credentials`), where they said it has no way to push.
- A write run that leaves a change to a tracked file uncommitted and returns no patches is a refusal, not a finished task. `qargi local run` ends such a run `refused` (exit 2) when its runtime ended ok and OUT holds no patch or bundle, prints `WORKTREE=uncommitted: CLONE holds N changed tracked file(s) ...` and records `worktree` (`tracked`, `untracked`, `patches`, `refused`) in `RUN/dispatch.json`; new files never added (untracked) alone are said (`WORKTREE=untracked`, which says they are not a refusal and are lost when the run is cleaned) and not refused, and `qargi local clean` warns when it removes a clone that holds what no commit has (new files or changes to tracked files), with their counts. `qargi review check` fails a run with no patches whose clone holds such a change unless its manifest says `BLOCKED` (then a note), with or without `--allow-empty` and also when OUT holds a report with Findings and a verdict; untracked files are a warning. The clone's state is read with git run so that nothing the member put in the clone's git configuration runs: no system or global configuration, the work tree named outright, no fsmonitor, every filter driver the clone names emptied, no optional locks.
- The help of `qargi local prepare` and `qargi local run` and the manual page say that the runtime may refuse a run whose paths its sandbox hides from the member (`dispatch.hidden_paths`, `/dev` for `codex`), before anything is made or started, naming the path and the fix; the help of `local run` also names the `GITDIR=changed:` line and says never to run git in a clone whose `.git` the member could write.
- The README and the documentation overview describe qargi as a CLI and a set of skills that any lead loads, where they called it a set of Claude Code skills: the lead is the agent session you work in, Claude Code and Codex are the leads and local runtimes qargi ships, and another runtime is defined as data. The quick start installs the skills for a Claude Code or a Codex lead (`--runtime codex`), starts a project on `claude-code` or on `codex`, and says that `/qargi-task` is Claude Code's slash command, which another lead replaces by loading the skill or running `qargi local prepare` and `qargi local run`; the install and flow pages name `~/.claude` and `/qargi-task` as Claude Code's.

### Fixed
- The `qargi-task` skill loads in a Codex session: the `argument-hint` of its front matter, a double-quoted string followed by more text, was not YAML, and codex-cli 0.167.1 dropped the skill without a word. It is now one quoted string with the same text. `tests/test_install.sh` checks the front matter of every skill under `skills/` with a strict rule (an unquoted value that starts with a YAML indicator or holds `: ` or ` #` fails, and so does text after a quoted value); `qargi-packs`, `qargi-session`, `qargi-team` and `qargi-verify` failed it too (a `: ` in the description, or the `argument-hint` `[NAME]`, which YAML reads as a list; codex-cli 0.167.1 listed them, a strict YAML parser did not read them), and each value is now one quoted string with the same text, so every skill passes the rule.
- `qargi local run` starts the real program of a command runtime, never a version manager's wrapper. The command word is resolved on your `PATH`, entry by entry, to the first regular executable file whose real path has that name (or the name with an extension, a launcher such as `codex.js`, or with a suffix after a dash, a release binary such as `codex-x86_64-unknown-linux-musl`), and that absolute path runs: `--dry-run` prints it as `COMMAND=` (it printed the bare word) and `RUN/dispatch.json` records it as `command`. A wrapper or shim that is a link to a program of another name is passed over with a note; when nothing else is left the run is refused with exit 3, naming each entry passed over and why. A `codex` that was such a wrapper looked for Codex under the run's home, so the sandbox could not start it again and every shell command of the member failed. The member's own `PATH` is unchanged; a version manager's wrapper on it for another tool (`go`, `node`, `python`) also runs under the run's home, which the Codex page says, with the fix (the directories the tools are installed in first on `PATH`).
- `qargi packs apply --target TARGET PROJECT` records the apply in the audit log as `packs-apply-TARGET`, the render target it applied (`packs-apply-codex` for a Codex project). Every render was logged as `packs-apply-claude-code`, whatever its target.
- The review of a provider pack (`qargi provider import`, `seal` and `enable`) no longer lists the words of a definition's command line and notes as `eval or exec` constructs: the definition of `codex` had eight such flags, one for every `codex exec` in its argv and its notes. In `definition.json` an `eval` or `exec` is flagged only as code, a call (`exec(...)`), an `eval` or `exec` of an expansion (`$VAR`, `$(...)`, a backquote) or the `shell=True` and `os.system(` forms; in the pack's scripts and other files it is flagged as before.

## [0.2.11] - 2026-11-11

### Added
- `qargi tool import SOURCE --tool-list FILE` and `qargi tool seal NAME --tool-list FILE` judge the tools of a tool pack by the server's own tool listing: FILE is the JSON result of the server's MCP `tools/list` (or the response that holds it as `result`), saved to a file; qargi reads the file and never contacts a server. A tool that the listing does not annotate `readOnlyHint: true`, or does not name, may not be `always_allow` or `auto` unless the pack sets `"write_ok": true`; a tool annotated `destructiveHint: true` and a tool the listing does not name are reported in the review as `NOTE` lines; the check of the tool's name still applies. The pack's record keeps the sha256 of the listing and what it says of each tool of the pack (`tool_list`: `read-only`, `write` or `destructive` per tool; `qargi tool show NAME` prints it). `tool_list` is part of the content hash and of the plan token, so it is approved with the pack and a change of it is drift; a pack without one hashes as before. A later `seal` without the option keeps the record's listing, and a tool added to the pack since then counts as not listed. A file that is no listing ends the verb with exit 1, and the option with any other verb is a usage error (exit 2). Without a listing the review is the name check alone, as before.

### Fixed
- The review of a tool pack finds a write-like tool however the MCP server spells its name. The check only saw a write word at the start of a name or after `_`, so `platform.delete_knowledge`, `repo/push`, `issue-close` and `deleteItem` passed as `always_allow` or `auto` without `write_ok`. A name is now cut into words at every character that is not a letter (`_`, `.`, `-`, `/`, digits) and at a camelCase boundary (`deleteItem`, `HTTPPost`), and a word that starts with a write word (create, update, delete, remove, post, push, write, merge, send, set, add, edit, close, comment) makes the tool write-like, also in a name with no separator (`deleteall`, `sendmail`). A write word in the middle or at the end of a word does not count (`offset`, `dataset`), and the words `settings`, `setting`, `address`, `addresses`, `postal`, `postcode`, `postcodes`, `additional` and `closest` are taken for the names of things that are read, so `settings_view`, `address_list` and `postal_code_lookup`, which the old check refused, pass. The rule is written once, in `lib/packs_check.py`, and every review asks it (`tool import`, `seal`, `show`, `link`, `check`, the renders). A pack in your library that has such a tool unattended now fails `qargi tool check` and is not rendered until the tool is `always_ask` or the pack sets `"write_ok": true`, and you seal it again.
- `qargi packs apply --target claude-code PROJECT` writes the permission rule of a tool under the name Claude Code gives the tool: `mcp__SERVER__TOOL` with every character of a name other than a letter, a digit, `_` and `-` written as `_`, so the tool `platform.list_items` of the pack `kb` gets the rule `mcp__kb__platform_list_items`. The rule held the name as the pack writes it, which matched no tool when the name had a dot, and a name with a slash was refused. How a runtime writes a name is data of its definition (`resources.mcp.name_key` in `lib/providers/schema-2.json`: `nonword-underscore`, or absent for a name left as written; a runtime without it still takes only plain names). Two tools that would get the same rule (`a.b` and `a_b` of one server) are refused by the plan, since a rule for one would hold for the other. A render that holds a tool pack with a dotted name differs from what `packs check` now expects: apply it again.
- The review of a tool pack checks the names in its `tools` map: letters, digits and `_ . - /`, 1 to 128 characters, the first a letter, a digit or `_`, so the dotted and slashed names that servers publish are accepted and a name with a blank, a control character, a quote or a wildcard fails with the name written as a JSON string. A tool pack that is not one JSON object, or whose `tools` is not an object (a list), fails its review; both passed before, because the check ended in an error and said nothing. The name of the pack keeps its rule (lower-case letters, digits, `-`).
- A member's calls of MCP tools pass its guard, and a member has the MCP tools of its roles' tool packs and no others. The hook of a member matched `Bash`, `Monitor`, `Edit`, `Write`, `NotebookEdit`, `Read` and `Grep`, and the member definition listed no MCP tool: a call of an MCP tool was not judged, so a read-only (review) run that reached a tool pack could have called a write tool. The hook matcher now also covers `mcp__.*`, and the guard judges a call by the policy the tool packs of the role give that tool. It refuses a tool that is in no tool pack linked to the role, in every run; a tool whose pack is missing, changed since its approval or fails its review; an `always_ask` tool, since a member runs unattended; a name that stands for two tools of the role; and, in a read-only run, every tool that is not a declared read (`always_allow`, a name that is not write-like and, where the pack was approved with the server's tool listing, `readOnlyHint: true`). The role is the one of the run, as the lead's registry of local runs records it; the run is found from the member mark of `qargi local run` or from the directory of the call. `qargi agent add` and `agent refresh` write into a member's tool list the tools of the packs that reach its roles, under the names the runtime gives them (`mcp__kb__platform_list_items`), without the `always_ask` ones and, for a member of read-only roles alone, the declared reads only. The hook command of such a member names its project and roles (`qargi __guard --project P --roles build,review`), because an MCP call names no path and a member a session starts works outside its run directory: a call made where no run is found must be allowed for every one of those roles, each held to its class, and with neither a run nor those names the call is refused. Every member is `STALE` after this release, since the hook matcher changed, and again whenever a link, an unlink or a seal changes the tool packs of its roles: `qargi agent refresh NAME --project P` renders it. A runtime other than Claude Code is judged by the names its definition gives (`resources.mcp.permission_rule` and `name_key`), and one that gives none has no MCP calls to judge.

## [0.2.10] - 2026-11-10

### Added
- `qargi local report RUN [--findings] [--from FILE] [--force]`: a read-only member's own way to put its report into OUT when its runtime refuses the file tool for `report.md`. The member writes the text under another name in OUT with its file tool and runs the verb with `--from NAME`, or gives it on standard input; the verb writes `OUT/report.md` (`--findings`: `OUT/findings.md`, which `review check` does not read as a report) and, when OUT has none, a minimal `manifest.json` that names it. It reads only standard input or a regular file under OUT (a link, a path that leaves OUT, a file over one megabyte and an empty report are refused), writes only in the OUT of a read-only run that the lead's registry names, keeps a report that is there unless `--force`, refuses a build run and, with the member mark set, any run but the member's own. It is not `review save` (the lead's, which stores a final message): the guard needs no change, because `local report` is on none of its lists of the lead's verbs. The member contract says to use it when the file tool is refused for `report.md`.
- The CI scan of `qargi release verify` can be told which jobs are not unmatched. A gate may carry `ci_jobs`, a list of CI job names or ids that run its check under another name: the scan reports each as a note, `covered by gate NAME`, and does not warn. The new answer `ci.not_gates` is a list of job names or ids that are aggregate or publish jobs and not gates; the scan leaves them out. A name listed in either that no workflow has is a warning, unless a workflow or a job name could not be read. `--strict` counts neither covered nor listed jobs. `project validate` and `project set` check both lists (non-empty names, each once).
- A feature gate may carry `covered_by: NAME`, NAME being a release-tier gate whose command runs the same check. `qargi release verify` lists the gate as `covered by NAME` and does not run it; its result in the run record and the `gates:` line is `covered by NAME` when NAME passed, and `not run` when NAME failed or was not reached. `qargi feature verify` still runs it. `project validate` and `project set` refuse a `covered_by` that names no release gate (or that is on a release gate), naming the entry.
- `qargi project adopt NAME --show` prints, with the plan, everything the plan token covers: the refs it starts from, the branches to create, and the full content of each file to write (the sha256 in the basis is that of the content shown). It changes nothing and takes neither `--plan` nor `--approved`.
- `qargi project adopt` lists the repository's own agent instructions (`CLAUDE.md`, `AGENTS.md`) and what it does about each, in the plan (`instructions` in the plan JSON): it edits neither; with a `CLAUDE.md` and no `AGENTS.md` it writes an `AGENTS.md` that holds the Development environment section only, and says that the `@AGENTS.md` import line in `CLAUDE.md` is for the owner to add.
- The gitflow scaffold has the parameters `unreleased_heading` and `changelog_entry`.
- The answer `methodology_accepted`, a list of `{gap, reason, date}` (the gap written as attach prints it, for example `file: CONTRIBUTING.md`), records the deviations from the methodology the lead accepts. The lead sets it with `qargi project set`; it is validated, and `project set` refuses it in a member run. `project attach`, `project adopt` and `marshal handoff` (a `== methodology deviations` section, and `deviations` in `--json`) print the accepted deviations apart from the open gaps; adopt writes no accepted file and creates no accepted branch; an accepted deviation whose gap is gone reads "accepted, no longer applies". (The key is top-level because `methodology` is a plain string.)
- `qargi release plan VERSION [--hotfix] [--date D] [--keep] [--allow-empty-notes] [--again]`: one plan and one approval for the whole release cut. It prints every step with what moves (start, push when the repository has an origin, finish, site when `site.enabled`) and ONE plan token (publish is not in the cut: it has its own plan); the start step is planned by `release start` itself, so its refusals come before a token does. `release plan VERSION --plan TOKEN --approved "<words>"` records the approval once (the words, the plan, the date, an audit line `release:cut`) in `STATE/release/PROJECT-VERSION.cut.json`, lead only. Then `release start`, `push`, `finish` and `site` each take `--plan TOKEN` alone: the words are the record's and are on that step's audit line, every step records that it ran (`plan` again and `release status` show the steps and the next command, so a cut resumes after a refusal or a death), and each step runs only while what the plan fixed holds: `start` finds its own plan as it was frozen, `push` the branch where `start` left it, `finish` the branch where `push` left it (the head the checks ran on) with master, the second target and `--keep` as planned, `site` the tag on the commit `finish` tagged. `release publish` refuses the cut's token (run it with its own plan and approval): the notes and the release files it creates, whose hashes exist only after the tag, are shown by its own plan. A step under the cut is the lead's as approving it is, and is refused in a member run and when `QARGI_NESTED` is set; a `--plan` that is not the recorded cut's token, without `--approved`, is refused naming that a cut is recorded (it does not print a plan of its own). A step that no longer matches is refused before anything moves and is run with its own plan and approval, which the cut records; the single verbs and their own tokens work as before. `finish` stays the push and tag gate: the approval words are the owner's, and `--ignore-checks WORDS` at the call is recorded as before. The `qargi-flow` skill, `docs/flow/git-flow.md`, the help and the manual page describe it.
- `qargi project unset NAME PATH` removes one answer of a project. It refuses what `project set` refuses (the marshal backend; `models.extensions` and `models.accept_no_barrier`, also inside a whole `models` object, with exit 2 and the verb that takes a plan token), refuses a key that is not set, refuses the removal of an answer the project needs (validate runs first and the file is not touched), and is refused in a member run (the run directory or the member mark in the environment) with exit 2.
- The answers `backlog.section` (a heading of the backlog file: only the list under it, up to the next heading of the same or a higher level, holds items) and `backlog.archive` (a directory that receives `NAME-archive-YYYY-MM.md`, or a path ending in `.md` for one archive file; by default the archive is beside the file) shape `qargi backlog list` and `done`. A heading the file lacks is an error. `lib/backlog.py` takes them as `--section` and `--archive`.
- `qargi backlog add ID "text" [--detail "..."]` appends the item `- [ID] text` (the detail as indented lines) at the end of the list, of the `backlog.section` list when that is set, with an audit line. It refuses an id that is not a slug and an id already used anywhere in the file, and then leaves the file alone. `qargi backlog done ID [ID...] --evidence TEXT` takes several ids as one batch: one plan, one token, the same evidence archived with each id, applied together (the archive is written once, then the backlog); a missing, ambiguous or repeated id refuses the whole batch before a plan is printed. Both are the lead's, as `done` was: the guard refuses every backlog verb but `list`.
- The answer `review.reject_trailers`, a list of trailer keys (letters, digits and hyphens, `*` for any run of them) refused besides the built-in `Co-Authored-By` and `Generated-with` under `review.trailer_policy` `reject`; `project validate` refuses it while the policy is not `reject`, and a member's guard refuses setting it. The scrub verdict for a rejected trailer names the commit, the line of its message and what matched (`review.trailer_policy is reject` or `review.reject_trailers names KEY`), and an entry that is no trailer key fails the scrub. The scrub reads the list from the run's copy of the answers in the lead's registry, as it does `review.scrub`.
- `qargi doctor` has a `project-env` check: `last env check <verdict> at <time>` from the record `qargi env check` keeps in `state/env/PROJECT.json` (a warning when the verdict is not `ENV OK`), or `unknown  never run` when none was recorded. It only reads the record and never runs the project's code; the help of `doctor` and of `env check` name each other.
- `qargi memory init repo --worktree DIR` (and `memory move` with the repo tier at one end) writes the repo tier into DIR, another worktree of the project's repository, at the same path inside it, instead of the main checkout. DIR must be the top of a work tree of that repository; the option is refused for any other tier and for a move that has no repo tier. The plan (and its token) are of that worktree.
- Tab completion of `qargi project set` offers the answers `ci.not_gates`, `methodology_accepted`, `review.reject_trailers`, `backlog.archive` and `backlog.section`.
- `qargi doctor` has a `tools` check: `flock` (the locks of the finishing verbs and the ref journal) and `timeout` (the bound on a question put to a remote) must be on PATH, and a missing one warns, naming what it is for and the package that has it. `flock` and `timeout` are in the Makefile `TOOLS` list (`make doctor` has a line for each), in the bootstrap lines (`util-linux`, `coreutils`) and in the tools `AGENTS.md` lists.
- The answer `release.hotfix_preflight`, a command line or a command as a list of words (`{version}` replaced, `QARGI_RELEASE_VERSION` set): `qargi release push` runs it for a hotfix, in a copy of the branch before anything is pushed, instead of `release.preflight`, for a project whose stored preflight needs content only the fix has or does not suit a hotfix. The plans of `release start --hotfix` and `release push` name the answer that runs. A release keeps `release.preflight`; a member may not set the answer (`project set` refuses every `release.*` answer).
- The answer `release.finish_check`, a command line or a command as a list of words (`{version}` replaced, `QARGI_RELEASE_VERSION` set): `qargi release finish` runs it in a copy of the branch once its plan is approved and before any merge, tag or push, and a non-zero exit refuses with the tail of its output and nothing moved. The finish plan and the `release plan` cut plan list it. Off unless set; a member may not set it (`project set` refuses every `release.*` answer).

### Changed
- With workflows and no gate declared, the CI scan of `qargi release verify` prints one note naming all the jobs (`no gate is declared, so the CI jobs are not compared with gate names (jobs: ...)`) instead of a warning for each job. `--strict` still refuses, its message saying that no gate is declared.
- `qargi help feature verify` names the exact lines a gate or test command may print for the failure report that ends a failed `feature verify` or `release verify`: `^FAILED: ` for a failing step, `^FAIL( |:)` and now `^--- FAIL: ` (a Go test run's line) for a failing test, and `^logs of the failed steps: ` for where the runner kept its logs. Before, a gate that printed `--- FAIL: TestX` was reported as having no failing test name.
- The refusal of a restricted environment variable under the read-only class (`PATH`, `TMPDIR`, `HOME`, `GIT_*`, `LD_*`, `PAGER`, `BASH_ENV` ...) says what it is for: a read-only member may not assign the name (inline, with `env`, `export` or `declare`) and runs with the one it was given; a build, vet or test command with that environment is not refused. It read "TMPDIR is not set", which read as if the variable were missing from the environment of a command that only uses it. The rule is the same; only the wording changed.
- `qargi help guard` (and the GUARD section of the manual page) and the `review` role text tell a read-only member what it may run (build, vet and test commands with the environment it was given; only an assignment of `PATH`, `TMPDIR`, `GIT_*` and the like is refused), that its `TMPDIR` is the run's TMP (a Go test writes there; the class writes only OUT and TMP), and that a piece after a separator that starts with `git push`, `git tag NAME`, `ssh`, `scp`, `sftp` or `gh` is refused even in text, while the same words in the middle of a sentence are not read. The topic stays within its 400 words, so a few of its sentences are shorter. The guard's reading of a command is unchanged. The member definition (`agents/member.md`) is unchanged, so `qargi agent refresh` is not needed; the prompt of a cloud agent of the `review` role carries the role text, so `qargi instances refresh-prompt` brings it in line, and a run prepared earlier keeps the old role text in its `task.md`.
- `qargi branch prune` counts the remote-tracking branch `origin/BRANCH` of each `repo.detached` branch as a place a branch is merged into (with the same `--no-ff` rule), because a detached branch that origin changes only through a pull request lags behind origin locally; `--remote` now fetches before it reads the history, not after. `docs/flow/git-flow.md` (Detached branches) and the `qargi-flow` skill describe that flow: a short-lived `agent/pr-SLUG` branch cut from `origin/BRANCH` in a worktree, `local prepare --base` on it, `review apply`, a fast-forward, a push, and a pull request merged with a merge commit; a squash or rebase merge leaves no merge commit and its branches are deleted by hand.
- The changelog sentence of the `CLAUDE.md` and `CONTRIBUTING.md` that `project adopt` writes, and the heading of a new `CHANGELOG.md`, follow the project's `release.changelog.unreleased` heading and `release.changelog.numbered` ("as the next numbered item under `Next`"), where the scaffold said `[Unreleased]` always. The files of a project without release answers are as before.
- The `AGENTS.md` that `project adopt` writes names only the bootstrap, dry-run and doctor commands the repository has or declares (`env.*` in the answers); a line for a command it lacks (a task runner without the conventional targets) is left out.
- `qargi project attach` and `qargi project adopt` print a declared setting, or a state that is not a problem, apart from the gaps, under "noted, not gaps (nothing to close)": `release.version_file none` (no `VERSION` is planned, and it is no longer listed under "left for you to judge"), and a changelog whose unreleased heading carries the version (`release.changelog.unreleased` with `{version}`) that has none right after a release ("no unreleased section yet; the last release is X"; before, a format gap). The plan JSON of adopt has an `info` list for them, and so has the detection JSON of attach.
- `qargi marshal claim` and `qargi marshal check` refuse when the remote of the shared records cannot be reached (exit 3, nothing changed), where they went on: a claim stayed provisional and a check answered from the last fetched copy, with a warning. The message says what could not be reached (the records of the project, `refs/qargi/features/NAME` on the remote) and why, and how to go on. The new `--assume-unreachable-ok` lets the lead go on (the old behaviour) and records `marshal:unreachable-ok` in the audit log (project, feature, verb, remote, the reason). The other changes of a shared record (set, renew, release, take, takeover, finish, resign) already exited 3 without the remote; their message now names what was unreachable too, and says there is no override. `marshal status` still shows the cache with its notice. The flow verbs that ask the marshal first (`feature start`, `sync`, `merge`, `verify` and `finish`) refuse the same way (exit 3, nothing changed; `feature start` before it makes the branch or the record), where they warned and went on, and the message names the flag. They take the same `--assume-unreachable-ok`, which goes on and writes the same audit line `marshal:unreachable-ok` (verb `start` or `check`). A project whose marshal is local or off, an explicit refusal by another lead (exit 1), and a marshal that is missing or fails in some other way (a warning) behave as before; `local prepare` is not changed.
- The warning that `memory init repo` and a move into the repo tier print says on which branch the files must be committed (the branch checked out where they are written), that a member's clone has them only once committed, and that `--worktree DIR` writes them into another worktree. The lead's session-start warning for an uncommitted repo tier says the same (the branch and the directory to commit in).
- `qargi project set` prints `was: OLD` after its line (the JSON the answer held, or `(not set)` for an absent key) and, like `project unset`, writes an audit line (`project:set` and `project:unset`, with the path and the old value, cut at 200 characters). `set` wrote none before.
- A null stored for an optional answer is the same as not set, for every optional answer: `project validate` accepted it for `gates` and `git.author` and refused it for `review.scrub`, `review.trailer_policy`, `review.keep_author` and `backlog.file`. It now accepts it for all of them (the readers already treated a null as unset); `qargi project unset` removes the key itself. The help of `project set` says so.
- `qargi import`: an archive's project answers never add or change `ci.not_gates`, `methodology_accepted`, `review.reject_trailers`, `backlog.archive` or `backlog.section` either, which a member's `project set` is refused, as they never add or change `models.extensions` and `models.accept_no_barrier`: the stored value stays (an entry may be dropped, none is added), or the key is left out, and a note names the keys. The answers were imported as the archive held them.
- The providers page says that the guard fails closed on a provider definition in the library that does not load (a draft made with `provider new` counts): every call of a member that writes or reads a protected place is refused until `provider check NAME` is clean or the pack is removed, and that a pack that may be broken for a while is better edited outside the library. Tests keep the help topics apart from the command names (`qargi help NAME` shows the topic first) and `CONTRIBUTING.md` in step with the rules of the hermetic lint and the legacy lint.
- The `qargi-verify` skill names `qargi local report` (the member's own writer of a read-only report) beside `qargi review save` (the lead stores a final message) for a read-only run with no report in OUT.
- The requirements line of the README names `timeout` (GNU coreutils) and says `flock` is for the locks.
- The skills page of the documentation (`docs/skills-tools-and-memory`) has a section on the answers and verbs the lead reaches for that no page of its own listed: `project unset`, `methodology_accepted`, `project adopt --show`, `backlog.section`, `backlog.archive`, `backlog add`, `backlog done` with several ids, `review.reject_trailers`, `ci.not_gates`, `release plan` and `local report`, each with a line and a link to the page that holds the detail.
- `qargi role list|show|prompt|check` is one Python process (`lib/role.py`, imported by the dispatcher as the guard is, so its bytecode is cached) where `lib/role.sh` started `jq` a dozen times. The output and the exit statuses of every verb are those of the script, also for a `role.json` that is an array, `null`, empty, holds several values or a description that is not text; only what `jq` printed to standard error about a `role.json` that does not parse is worded by qargi now. `role list` takes about 85 ms where it took about 120 ms (the four built-in roles, the tool compiled); the startup ceiling of `role list` in `tests/startup-budget.txt` is 260 ms (twice the 130 ms the test measures, with no bytecode cache and the test shim in front of `python3`), down from 350.
- A read of the shared marshal records (`marshal status`, `claim`, `check`, `renew` and every other verb that loads the cache of the remote's `refs/qargi/`) lists the refs with one `git for-each-ref` and reads their commits, trees and `record.json` files with two `git cat-file` processes, instead of three git processes per ref (14 refs: 43 git processes became 3). The records, the warnings and their order, and every verb's output are the same, a `record.json` over 64 KiB is still never read, every signature is still verified on every read, and a push is still made with a lease on the oid that was read; when git cannot answer in a batch the read goes back to one ref at a time.
- The listing of `qargi marshal status` (every feature, or one) asks git once for what is the same for all features: the work trees, the lists of feature and agent branches, whether `develop` exists. It asked again for each feature (14 features: 100 git processes became 40). The output is the same; the answers are kept only while one listing runs, so a later command asks git again.
- With integrity `advisory` or `strict`, the signatures of one read of the shared marshal records are verified at the same time (up to 8 `ssh-keygen -Y` runs at once) instead of one after the other. Every signature is still verified on every read, a record that fails is refused or tagged exactly as before, and nothing is remembered between reads; with 14 signed records a read is about 150 ms faster.
- `qargi local prepare --task-file F --done COMMAND` checks the command word of every simple command of the DONE line, not only of a line with no operator: the word that starts the line and each word after `;`, `&`, `&&`, `||`, `|`, `(` or `$(` (past `NAME=value` words and redirections) must be an executable on `PATH`, a shell builtin or keyword, or a script. Prose that merely contains an operator (`coverage > 80%`, `tests pass & lint is clean`) used to pass because bash parses it; it is now refused with exit 2 and no run is made. The words of a `[[ ]]` test are not read, and a line that holds a `case`, `function` or `select` command, `((` (an arithmetic command or a `for ((` header) or an array assignment (`NAME=(`) is checked only up to that point and the rest is accepted on syntax alone (`bash -n`), so `[[ -f out.txt ]] && echo yes`, `case $x in a) make a;; esac`, `for ((i=0;i<3;i++)); do echo $i; done`, `function g { make; }; g` and `arr=(a b c); echo "${arr[@]}"` are DONE lines; the lookup of a builtin or keyword compares the word as a fixed string, so `[[` is no longer read as a pattern. A path is looked up at BASE or under `--scope` only as the first command; a later one may follow a `cd`. Arguments are never checked.
- `qargi review check` fails a manifest whose `done.command` is not the `DONE:` line of `RUN/task.md` (the check the lead set; the line before `PROFILE:` or `BASE:`, so a `DONE:` line in the task text does not stand for it), naming both commands. A manifest with no `done.command` passes with a warning that names the DONE. A run with no `task.md` is unchanged.
- `qargi local prepare` exits 2, not 1, for every call that cannot be right, as its other usage errors already did: neither `--repo` nor `--repo-url` (the message was `--repo must be a git working tree`, about a path never given; it now says `prepare needs --repo DIR ... or --repo-url URL`), a `--repo` that is no working tree, a `--repo-url` that is not https or carries a user name, a `--credential-file` that is not there, an unknown `--role`, a bad `--slug`, and a `--task-file` that is a link, missing, empty, over 1 MiB, holds a NUL byte or has a `SCOPE:` line. `qargi local clean RUN --yes` and `--scratch DIR` (options of other forms of clean) exit 2 too. A failure of the work itself (a clone that fails, an unreadable answer) still exits 1; no run is made in either case.
- `qargi skill check`, `tool check`, `packs check` and `skill|tool list` do the work for the packs of a role in one process (`lib/packs_check.py`) instead of about 15 `python3`, 34 `jq` and 18 `find` calls per pack: the content hash, the drift and review lines, the compatibility with the project's provider, the render inputs and the library facts of the skills a session would load. Their output and exit status are the same, byte for byte, and so is every content hash (the approvals stored with the packs stay valid); the order of the names in the hash follows the locale's collation, as `sort` did. One difference in `skill|tool list PROJECT ROLE`: a pack is marked `[attached to ...]` when its name equals an entry of the role's packs, where the shell matched the name as a pattern (a name with a `.` also matched other characters).
- `lib/procenv.py` holds the helpers that `lib/env_check.py`, `lib/env_apply.py`, `lib/local_run.py`, `lib/tools.py`, `lib/supervise.py` and `lib/discover.py` each defined for themselves: the PATH of a child process without empty and relative entries (`clean_path`), the base environment of a child (`child_env`) the time stamp of a record (`now`), the plan token hash (`plan_token`) the line of the audit log (`audit`, same fields and order as before), `die` and the runner of the git commands of `env check` and the tool checks (`git`). The output of every verb is unchanged, with one exception: when the caller's PATH has no absolute entry, the doctor that `qargi env check` runs and the tool lookups of `qargi env check` and `qargi env plan` fell back to `/usr/bin:/bin` (two of the three copies); every copy now falls back to `/usr/local/bin:/usr/bin:/bin`, as `qargi env apply` and `qargi local run` already did.
- The message of a conflict in the second merge of `qargi release finish` (the tagged master merge commit into develop, or into the open release branch) names the tag and not a bare sha: `merging tag VERSION (the master merge commit abc1234) conflicts`. The refusal of `--resolved` for a commit that is not that merge names it the same way.
- The prompt texts (`contract/*.md`, `roles/*/ROLE.md`, `agents/member.md` and `agents/member.body.md`, `packs/skills/*/SKILL.md`, `skills/*/*.md`, `provision/templates/*.md`, `lib/providers/*/*.md`) are one paragraph per line, a list item on one line, where they were hard-wrapped at about 80 to 100 columns (some lines were far longer after later edits) and showed as ragged fragments in a viewer narrower than the lines. Only line breaks changed: not a word is added, removed or reordered, so the word ceilings of `tests/skill-budget.txt` stand and the golden task blocks differ by line joins. `tests/test_prose_lint.py` (fast tier) keeps it so: outside front matter and fenced code a line that continues a paragraph or a list item, or ends in spaces, fails. `CONTRIBUTING.md` names the rule. Rendered members are STALE after this release because their prompt text changed in form: `qargi agent refresh` renders them again, and a cloud agent takes it with `qargi instances refresh-prompt`.
- `qargi help project` (`set`) lists everything a member's guard refuses to set (also `upstream.*`, `ci.*`, `methodology_accepted`, `git.*` and `review.*`), and `qargi help import` names the five lead answers besides `models.extensions` and `models.accept_no_barrier` that an archive may not add or change (`ci.not_gates`, `methodology_accepted`, `review.reject_trailers`, `backlog.archive`, `backlog.section`).
- The wording about a memory store that cannot be listed no longer names the cloud command-line tool outside the cloud runtime's own code: the help of `qargi canon` says "the cloud tool missing, not logged in, no access", and the reason `canon` prints for a list that failed with no error text of its own is `the store list failed (status N)` (it was `ant failed (status N)`). `tests/test_neutral.sh` found the three lines (it is in the fast tier and covers every file), and the allowlist of `tests/neutral-allowlist.txt` only shrinks, so the lines were reworded and not listed. The manual page is regenerated.
- `lib/provider.py`, `lib/marshal_store.py`, `lib/help.py`, `lib/gates.py` and `lib/lead_usage.py` are imported by `bin/qargi` and by the scripts of `lib/` instead of run as scripts, so python reuses the compiled form that `install.sh --user` and `qargi upgrade` leave (a script is compiled on every run, a module is cached). The scripts call the one helper `pymod MODULE ARGS...` of `lib/lib.sh` (`bin/qargi`, which does not source `lib/lib.sh`, holds the same text and execs); it runs the module's `main()` as the script's `__main__` block does and answers with its exit status, and `sys.argv` is what the script had. Every verb prints what it printed and exits with the status it had (the modules still run as scripts too, `python3 -I lib/provider.py list`). With the tool compiled, `agent for build` takes about 420 ms where it took 525, `marshal status --brief --no-fetch` 235 ms (275), `provider list` 117 ms (153), `help role` 46 ms (58) and a completion 36 ms (49). `tests/test_startup_modules.py` checks that each module answers as its script did, that its bytecode is cached, and that `bin/qargi` and `pymod` hold the same text.
- `tests/startup-budget.txt` has ceilings for `qargi agent for build` (850 ms) and `qargi marshal status --brief --no-fetch` (470 ms), twice the median of 421 and 235 ms that `tests/test_startup_modules.py` measures with the tool compiled, a project, a member and an open feature (the same verbs took 525 and 275 ms before the five large modules were imported). Like the one of `role list` they warn and do not fail.
- The test budgets (`tests/suite.txt`, fourth column) and `tests/durations.txt` are re-recorded from one whole-suite run (134 steps, 829 s, eight CPUs, in parallel): a budget is the last recorded duration of the step on the reference machine, rounded up by a tenth, and the run reports a step that takes more than 1.5x its budget. The rule that a budget only shrinks is gone from the manifest header, `tests/run.sh` and `CONTRIBUTING.md`; `tests/test_ci.py` checks instead that every step is well formed (a budget of at least a second, a timeout of at least 1.5x the budget). The timeout of `tests/test_review.sh` is raised to 1356 s with its budget, and the CI jobs' `timeout-minutes` from 35 to 55, which the new budgets ask for (a shard plans 1756 s).

### Removed
- `lib/role.sh`, replaced by `lib/role.py` (see Changed). The shell helpers `role_dir`, `role_names` and `role_class` of `lib/lib.sh`, which other scripts use, stay.

### Fixed
- `qargi release start VERSION --hotfix` works on a master whose `CHANGELOG.md` has no unreleased heading when `release.changelog.unreleased` carries `{version}` (such as `## {version} (unreleased)`: the heading is renamed at a release, so master keeps none); with any other unreleased heading, the default `## [Unreleased]` included, a master without it is refused for a hotfix as for a release ("add one"). It used to stop with `has no '...' section to release`, with or without `--allow-empty-notes`. The hotfix branch now gets the heading for VERSION (the released template with the version and the date), empty, above the first heading that follows the released template (any version and date; else the first heading of the unreleased heading's level, ignoring fenced code; at the end when there is none), so a `## Format` note above the version sections is not where it goes, and a file with CRLF line endings keeps them (it is read and written without newline translation); the plan says it was added because master had none, and `release finish` of a hotfix refuses (before anything is merged, tagged or pushed, at its plan as well) while the `CHANGELOG.md` of the branch has no entries under the heading of VERSION, whatever the layout (a branch with no `CHANGELOG.md` is not checked); the refusal names the file and the heading and says to record the entries under it on the branch. `release push` runs only the preflight the project set, as before. A release (not a hotfix) is still refused, and a master that has the unreleased heading is handled as before.
- `qargi canon plan` and `canon apply` on a project that records no memory store (or no reference store, with `--kind`) stop with `the project has no memory store recorded` and a non-zero status. Before, the `die` inside the plan step ended only the command substitution it ran in, so the verb went on: it printed `jq: error: Could not open file` three times and a plan token (that of an empty plan), and exited 0.
- `qargi canon plan` and `canon apply` build the plan of each store once (they built it twice, once for the token and once to show or run it, and read the store again each time) and leave no temporary directory behind: every temporary file of a canon verb is made under one directory that a trap removes when the verb ends, whether it succeeds or dies. Before, each plan left a `mktemp -d` directory in `TMPDIR`.
- `qargi canon check|plan|apply|seed-role|promote` no longer take a store that cannot be listed (ant missing, not logged in, no access) for an empty one. A failing list is an error: `check` prints `unreachable: <reason>` under each such store, as `memory tiers` does, and exits 1 without advising `canon plan`; `plan` and `apply` refuse and make no plan; `seed-role` and `promote` write nothing. Before, the list failure was discarded, so `check` said the store was empty and told you to plan, and `plan` offered to create the whole seed over a store that already held notes. A project with no store recorded still checks clean. `mem_dump` returns 1 and the first line of the error on standard error when the list fails.
- A write by a read-only member to its run's temporary directory (TMP, usually below `/dev/shm`) is matched to its run by the path, through the lead's registry of local runs, when the call's working directory is in no run. It was refused as "no run directory is found from this directory" (a Go test run from elsewhere, a redirection after a `cd`). Every other refusal is kept: a path outside OUT and TMP, a registry line that names no run, a relative or missing directory, a path beside or above the registered directory.
- The environment gaps of `project attach` and `project adopt` are measured against the effective environment: a command the project's answers declare (`env.bootstrap_command`, `env.doctor_command`) is not reported as a missing target, and the files adopt writes name the declared commands. `project attach` of a stored project reads its answers (`attach.py detect --answers FILE`), so its `release` answers (version file, changelog headings) apply too.
- The lock that `release finish` (and every finishing verb) takes checks the exit status of `flock`: a `flock` that fails or is not installed ends the verb with "could not take the lock", naming the cause (the command missing, or the lock directory's file system), and nothing is changed; before, the verb went on as if it held the lock, so two runs of it were not kept apart. `tests/test_release_cut.sh` is the new test of the release ceremony.
- `qargi release start` removes the bookkeeping files (`STATE/conflicts/PROJECT-release-VERSION-into-*.master` and `.done`, or `hotfix-` for a hotfix) that an earlier finish of the same version parked and that were never used again when that release was given up; before, they stayed for good, and a file in that directory is what the lead's compact check reads as a merge waiting to be resolved. Only files are removed, never a merge waiting in a worktree. A plan alone removes nothing.
- `qargi release start VERSION --hotfix` is no longer refused by a stored `release.preflight` that needs content only the hotfix brings (a file, a changelog entry): a hotfix is cut from master, which cannot have it, so hand-cutting the branch was the only way. For a hotfix `start` does not run the preflight and its plan says so, naming the command, where it runs and when ("It runs in a copy of hotfix/VERSION when you push"); `release push` runs it in a copy of the branch before anything is pushed, as it always did, and refuses until the fix is committed. A release (not a hotfix) is checked at `start` as before, and its plan now says the preflight passed and that it runs again at `push`.
- The member's guard matches a write to a temporary directory (TMP) to a run by the path only for the member's own run when the hook's environment carries `QARGI_MEMBER_RUN`: a read-only member of one run could write the TMP of another run by its path. Without the mark the path match is as before. The text of the guard that said input that is not JSON is let through now says it is refused, as it has been.
- A member's guard refuses `qargi project set` of `ci` (`ci.not_gates` takes a CI job out of the comparison with the gates) and of `methodology_accepted` (the deviations the lead accepts), as it refuses the other answers the lead owns; `review.reject_trailers`, `backlog.archive` and `backlog.section` were already refused with their parents. A `project unset` whose verb or path a variable, a substitution, a brace, a glob or `xargs` builds is refused like the same form of `project set`; a plain `project unset` is still refused in a member run by the verb itself.
- `qargi provider accept` without `--no-barrier` or without `--asked` exits 2 (a usage error), as the manual page promises for a usage error; it exited 1.
- The home page that `lib/site.py` generates when a site has no hand-written home page no longer says the agents are sandboxed; its description says the guard is a best-effort text check, not a sandbox (the README says the same).
- `qargi local prepare` copies `review.reject_trailers` into the run's line of the lead's registry, with `review.keep_author`, `review.scrub` and `review.trailer_policy`. It copied only those three, and the scrub reads the list from that copy, so the answer was not enforced for a prepared run (a commit with `Signed-off-by` passed under the policy `reject`). A run prepared before this change has no list in its copy and is not held to it; the list taken at prepare stays the run's, as the other review answers do.
- `qargi lead compact-check` no longer reports `a merge waits to be resolved or applied` for the `.master` file of a release finish (`STATE/conflicts/PROJECT-KIND-VERSION-into-BRANCH.master`, the master merge commit the second merge takes, left by a finish that stopped after writing it) nor for anything in `finish-intent/`: only a parked worktree (a directory under `conflicts/`) and the `.done` mark of a resolved merge count.
- `qargi local clean RUN` (and so `--applied` and `--stale`, which clean each run by the same rules) refuses a run while its `qargi review apply` is running, `--discard` or not: the apply holds a pid lock in the lead's state (`apply/RUN-ID.json.run`), and removing the run under it left the apply writing into a directory that was gone. A lock whose process is dead, or whose pid another process now has, does not block; clean removes it with the run.
- The bookkeeping file `STATE/conflicts/PROJECT-KIND-VERSION-into-TARGET.master`, which keeps the master merge commit of a finish that parked a conflict in its second merge, is used again only when the commit it names is a merge of exactly the master and the release branch head the finish now has (two parents, in that order). A file that names any other commit (edited, left by another run, a commit that is not that merge) is removed and the merge is made anew; before, any commit that existed was tagged and merged as if it were the master merge.
- The record a finishing verb writes before it tags or pushes (the intent record) is written under a lock that is checked like the verb's own: a `flock` that fails or is not installed ends the verb with "could not take the lock for the intent record", naming the cause, and no record is written; before, the write went on as if the lock were held. The ref journal says the same in its warning (`the flock command (util-linux) is not installed`, or `flock on FILE failed`) when its line could not be written for that reason.
- The plan line `backlog items named in these commits` of `feature finish` and `release finish` reads only the list under `backlog.section` when that answer is set, as the `backlog` verbs do; before, it looked in the whole file and named items outside the section. A heading the file lacks names nothing.
- The key completion offers `release.finish_check` and `release.hotfix_preflight`, and the text `project validate` prints for a `release` answer that is not an object lists every key the release answers accept (it is built from the list the check uses, which had grown past the copy of it).
- `qargi lead compact-check` counts a parked or resolved merge as the project's only when its entry in the conflicts directory is `PROJECT-KIND-...` with the kind `feature`, `detached`, `release` or `hotfix`; before, any entry starting with `PROJECT-` counted, so the merges of another project whose name continued after a hyphen (`app-web` for `app`) made the check unsafe.
- The audit log (`state/audit.log`) is appended to under an exclusive lock. `audit_log` in the shell library and the python writers (`procenv.audit`, which the supervisor and `env apply` use, the audit of `export` and `import` including the lines `import` adds from an archive, and the audit of the `provider` verbs) each take `flock` on `audit.log.lock` beside the log and write whole lines under it, so lines of verbs running at the same time no longer run into each other (a long line was written in several pieces and another writer's could land between them). The line format is unchanged. A lock that cannot be had (no `flock` command, no `fcntl`, a lock file that cannot be opened, a refused lock) ends the verb with a message naming the cause and writes nothing, as the pid lock does.
- `tests/test_canon_reach.sh` asserts the absence of a jq error with `jq:` (the prefix of every jq error message) and not with the bare `jq`, which a random temporary path in the output can hold (the `absent` rule of the hermetic lint, `tests/hermetic_lint.py`). `tests/test_hermetic.sh` failed on it.
- Three more findings of the hermetic lint on the same head, which kept `tests/test_hermetic.sh` failing, are fixed: the shim of `tests/test_marshal_batch.sh` that makes a verification take 0.3 s on purpose says so (`hermetic: allow sleep`, nothing waits for it), `tests/test_procenv.py` builds the run and temporary names of its `child_env` call under the test's own temporary directory, and `tests/test_release_cut.sh` gives `journal_line` the test's own state directory as the repository instead of `/tmp`.
- The member contract's sentence on `qargi local report` names the run as the parent directory of OUT, not as `RUN_DIR`. `RUN_DIR` is a name only a local task block has (a cloud member's prompt gives OUT alone), and `tests/test_prompt.sh` keeps the contract from naming it as a place; the sentence failed that check. The word ceiling of `contract/contract.md` is 1010.
- A missing argument or option that the message itself asks for ends with exit 2, a usage error, not exit 1 (a refusal): `qargi packs load` with no project to infer (`name the project with --project P`), `qargi skill import` and `tool import` whose source gives no usable name (`pass --name`) and `qargi instances init --location cloud` whose deployment gives no usable name (`pass --name`). The manual page promises 1 for a refusal and 2 for a usage error.
- A value an option cannot take ends with exit 2, a usage error, not exit 1: `--kind` of `canon`, `--path` of `canon promote`, `--roles`, `--model` and `--effort` of `agent add`, `--profile` and `--surface` of `agent for`, `--model`, `--effort` and `--budget` of `instances init`, `--budget` and `--networking` of `provision`, `--scope` of `skill|tool link|unlink`, `--role` of `packs load` and of `start` on a base, `--why` of `mark`, `--warn` of `watch` and `--date` of `release start|plan`. `skill link` and `unlink` with a bad `--scope` stop at once with that status: the check ran in a command substitution whose exit ended only the substitution, so the verb went on to a later failure.
- A member's guard refuses `qargi project unset` in its plain form, whatever the path, with a reason of its own (it removes an answer of the project the lead runs on, has no plan token, and the removal is to be proposed in the report), as it refuses `project link` and `project unlink`. Only the unreadable forms were refused before; the refusal of the plain form was left to `lib/project.sh`, which asks for a member's run directory or mark, so a member started some other way removed `gates`, `review.scrub`, `release.finish_check` or any other answer whose `set` the guard refuses for it after a `cd /`. The change is in the guard's table of verbs, not in how it reads shell text.
- `qargi project unset` refuses (exit 2) when its check for a member run cannot answer. The check's failure (python missing, `marshal_refs` unreadable, a traceback) was sent to `/dev/null` and read as "not a member", so the removal went on; it now stops with a message that says the check failed, and python's own error stays on stderr.

## [0.2.9] - 2026-11-09

### Added
- `qargi local prepare --task-file FILE --done COMMAND [--scope PATH]...` writes the whole task block to `RUN/task.md` for every runtime (before, only a command runtime had one, and the lead assembled it by hand): ROLE with its class, ABILITY (the role's text), TASK (the file), DONE, PROFILE (the text of the repository's profile, `~/.qargi/config/profiles/<repository>.md`, when there is one), BASE, BASE_SHA, one `SCOPE:` line (the paths comma separated, or `none`), the run's paths, and SUBMODULES and MEMORY when there are any; prepare prints `TASK_FILE=RUN/task.md`. It refuses, and makes no run, a task file that is empty, a link, not a regular file or over 1 MiB, or has a line of its own that starts `SCOPE:`; a DONE that is plainly not a command line (empty, several lines, or text `bash -n` cannot parse; for a simple command with no operator, a first word, after `NAME=value` words, that is not an executable, a shell builtin or keyword, or a script: a path is looked up at BASE in the object store, not in the lead's checkout, and a file under a `--scope` path counts because the task may create it; a line with `;`, `&&`, `||`, `|`, `(`, `$(` or a redirection is accepted when bash parses it, so only its syntax is checked, which lets the isolated-suite command line `T=$(mktemp -d -p /dev/shm); mkdir $T/h; HOME=$T/h bash tests/run.sh` through); a missing `--done`; and a `--scope` that is absolute, empty or holds a space, a comma or `..`. Without the flags prepare is unchanged. `tests/test_taskblock.sh` compares the block of a build run and of a review run with `tests/golden/taskblock-build.md` and `taskblock-review.md`
- `qargi review check` fails a patch series that touches a path outside SCOPE: the `SCOPE:` line of the run's task block (`RUN/task.md`, which a member cannot write) when it records one, else the manifest's `scope[]`; a rename's new name and the manifest's `touched_paths[]` count too. The contract tells a member to compare `git diff --name-only BASE_SHA` with SCOPE before each commit, to report BLOCKED naming the path when DONE needs a change outside it, and to put anything else under `noticed_not_acted_on`; the "Needs from the lead" instruction is gone. `contract/output-format.md` names the manifest's required keys (status, base, done, gates, commits, scope, touched_paths) and `contract/manifest.example.json` shows a complete manifest. The help of `qargi review check`, the manual page and the review role describe the rule as it is: a report-only run needs its `manifest.json` and a `report.md` whose last non-empty line is `verdict: accept` or `verdict: revise`, a patch outside SCOPE fails, and commits dated within two minutes of each other warn
- `qargi review save RUN [--force]`: stores the final message of a read-only run (standard input) as `RUN/out/report.md`, and writes a minimal `manifest.json` (status, base, done, gates, `commits: []`, touched_paths, the report in artifacts) when OUT has none. It is the report path with no shell text: a reviewer whose file tool is refused returns its report as its final message and the lead stores it, instead of a heredoc that the guard reads line by line. It refuses a directory that is not a run of the lead's registry, a run that is not read-only, a run directory or OUT that is a link, an empty message and an existing `report.md` (without `--force`); `qargi review check RUN/out` then decides whether the report has the required form. The verb is the lead's: the guard refuses it from a member, as it refuses `review apply`.
- `docs/development/architecture.md`: where each kind of record lives (configuration and state), the layers of the code, the life of a local run, what the guard advises and what the checks verify, and which parts are data and which are per platform. `docs/development/README.md` says in a sentence what each of its links is for.

### Changed
- `qargi __guard`, the hook command a member runs before every tool call, loads `lib/guard.py` as an imported module instead of running it as a script, so python reuses its compiled form (a script is compiled on every run: the 235 KB guard took more than half of each call). A harmless `ls` call takes a median of 48 ms instead of 105 ms, a `Write` call 60 ms instead of 118 ms (20 runs, minimal environment). The exit status, standard output and standard error, the options and the refusal messages are unchanged. `install.sh --user` compiles the tool's `lib/` as you (`compileall`), and `qargi upgrade` compiles the root-owned checkout through `QARGI_SUDO` before it relinks; nothing is written outside the tool's own `__pycache__` directories. A tool you cannot write to and that nobody compiled (a first `sudo git clone` install) works as before, only slower: `install.sh --user` says so and prints the one command that compiles it.
- `tests/startup-budget.txt` has a ceiling for `qargi __guard` (120 ms, the median of 20 runs on a harmless call in a compiled tool, about twice the 48-60 ms measured), and unlike the `role list` ceiling, which only warns, it fails: a line marked `enforced` fails the test when the median is over its ceiling in three measurements in a row, so a loaded machine does not.
- `paths.installed_tool_root()` (asked dozens of times in one guarded call) reads `install.json` again only when the file changed (inode, size, modification and change time), not on every call; what it returns is unchanged, and a record that is rewritten, replaced or removed, or a configuration directory that moves, is seen at once. 28 calls take 0.4 ms instead of 1.2 ms.
- The `build` and `write` role texts point at the reference store only when the task block has a `MEMORY` section or a store is mounted (a local member has none; `qargi role prompt` prints these texts to it), and the contract says a member without one follows the task block, the contract and the repository. The six-step order of work (orient, baseline, implement, check, commit as you go, report) is a numbered list in the contract, which every member loads, and no longer only in the build seed's workflow note
- The advisor sign-off of the `qargi-flow` skill is a run: write the combined diff to a scratch file, prepare a review run with `qargi local prepare --role review --profile advisor`, dispatch it with a full task block (TASK, the diff path, and as its DONE a command, `qargi review check ../out`, which the member runs from its clone: a sentence is not a DONE, `local prepare` refuses it), take it in with `qargi review check OUT` and close it with `qargi local clean`; before, the advisor was spawned on a bare file with no task block and no output directory
- One review vocabulary. A read-only role returns `report.md` and `manifest.json`: `# Findings` (each finding with severity `high`, `medium` or `low`, `file:line`, what is wrong, the evidence, a suggested fix as a fenced diff), then `# Checked` (what was run with its exit status; what was only read), and a last line `verdict: accept` or `verdict: revise`. The output format, the review role, the `review-findings` pack and the review role seed's findings format and workflow use these words; `CONFIRMED`, `PLAUSIBLE` and "not ready, ready with changes, ready" are gone. `qargi review check` now fails a report-only run without its `manifest.json` (`PREFIXmanifest.json` beside `PREFIXreport.md`) or whose last non-empty line is not the verdict line, and warns when there is no `# Checked` section
- The member contract says to record each check in `log.txt` when it runs (command, exit status, last lines), to report only what was run in this run, and that a check reasoned about but not run is `not run` with the reason, never `pass`; and to commit as you go, each change once its checks pass, a series committed all at once at the end being sent back. `qargi review check` raises its note on commits all dated within two minutes to a warning
- The member contract no longer says "never stash: use a WIP commit", which collided with the rules against rewriting history and for commits that pass alone. It says to check BASE out beside the work with `git worktree add` to see how BASE behaves, to `git restore` an experiment, and that a one-task member has nothing to set aside; the `gitflow-member` and `qargi-contributing` packs drop their copies
- The member contract says once how to write a report and a commit message: with the file-writing tool, never with shell text (echo, heredoc), and a commit with `git commit -F FILE`; a read-only role whose file tool is refused puts the whole report in its final message, and a guard refusal is reported, not rephrased. The shell-heredoc fallback and the copies of the commit-message rule are gone from the contract, the `gitflow-member` and `qargi-contributing` packs, the Claude Code addendum and its `member-out` note; `qargi-verify` tells the lead to store such a report with `qargi review save`
- The `qargi-task` skill has the lead write the task to a file and call `qargi local prepare ... --task-file F --done CMD [--scope PATH]...`, then hand the member the path of `RUN/task.md` ("read it and follow it", with `CLONE`, `OUT`, `GIT` and `BASE_SHA` when the runtime needs them); the list of sections to assemble by hand and the step that pastes `prepare`'s output into the block are gone. `qargi-verify` compares the manifest's `done.command` and the DONE check it re-runs with the DONE of `RUN/task.md`, and `review check` applies its SCOPE
- `make bootstrap` installs and `make doctor` checks `ssh-keygen` (OpenSSH: `openssh` on Arch, `openssh-client` on Debian and Ubuntu, `openssh-clients` on Fedora), which the marshal's signed records and the test suite need; `AGENTS.md` lists it
- A plan token is checked by default. `need_plan` (lib/lib.sh) no longer reads `QARGI_NESTED`: it always compares the token, so a verb that forgot to clear the variable can no longer skip it. `need_plan_nested` is the one variant that honours the variable, and `qargi canon apply` (which provisioning runs nested after its own plan check) is the only caller; `tests/test_nested_plan.sh` fails when it appears anywhere else. The `QARGI_NESTED=''` prefixes and `unset QARGI_NESTED` lines on the other verbs are gone. The `nested` field of an audit line is true only when a call skipped its check through the variable, and no longer when the variable merely was set. `qargi help guard` and the manual page say that only `canon apply` honours `QARGI_NESTED`, where they said it "skips a plan token check".
- Documentation and help say what the guard is and no more. The README, the introduction of `qargi help`, the members page, the marshal page, the local-session page, the `qargi-task` skill and the member prompt (`agents/member.md`, `agents/member.body.md`) no longer say "sandboxed agents", that a member "cannot" do what the guard refuses, or that the guard "enforces" a class. They say it is a best-effort text check of the ordinary ways, not a sandbox; a local member runs as the lead's operating-system user and a real sandbox is not yet built; `qargi local verify` and `qargi review check` are the backstop. `qargi help guard` opens with that. Run `qargi agent refresh` to render the new member prompt into existing members.
- `qargi help memory` shows the help of the `memory` command, not the topic of the same name. The topic is now `memory-stores` (`qargi help memory-stores`, and the MEMORY-STORES section of the manual page), and the command's help names it.
- Documentation brought in step with the code: the local-session page describes the `review-findings` pack (severity, `file:line`, the closing `verdict:` line) and the `qargi-contributing` pack as they are now, CONTRIBUTING lists every rule of the hermetic lint (`absent` included) and the legacy lint, and the members page and step 2 of the git-flow page (each one long paragraph or list item) are split into short paragraphs and list items with the same meaning.
- The documentation and `qargi help methodology` say that methodologies are not pluggable in behaviour yet: a methodology file sets the scaffold (files and parameters), the integration branch `project attach` looks for, the release and hotfix branch patterns and the `after_release` steps, while the `feature`, `release` and `branch` verbs name `develop`, `master` and the `feature/` and `agent/` prefixes themselves. The README states the requirements: Linux, bash, GNU coreutils and findutils, git, jq, python3 3.11 or newer, `flock` and `ssh-keygen`, and that nothing checks the platform before a verb runs.
- `lib/local.sh` no longer clears `QARGI_NESTED` before the plan check of `local clean --orphans` (`need_plan` ignores the variable, so the prefix did nothing), and `run_class` is called with the run alone (the second argument was ignored). `tests/test_nested_plan.sh` now covers `lib/local.sh` in its static check of redundant clears, and fails on a `run_class` call with a second argument.
- The note that `qargi local verify` and `qargi local clean` print when OUT holds no report no longer sends the member to the shell and a heredoc. It says the member writes its OUT files with its file tool, and that a read-only member whose file tool is refused returns the report as its final message, which the lead stores with `qargi review save RUN < MESSAGE`.
- The DONE that `qargi team brief` gives the review member is what `qargi review check` requires of a report-only run, where it asked for a Findings heading alone: the report has a Findings heading and its last non-empty line is `verdict: accept` or `verdict: revise`, and the prefixed manifest (`review--manifest.json`) is a JSON file. It is plain `grep`, `sed` and `python3 -m json.tool`, which a hosted member has (it has no `qargi`); `tests/test_team.sh` runs it on files and requires `qargi review check` to agree on each case.
- The contract directory of a local run holds `manifest.example.json` beside `contract.md` and `output-format.md` (`qargi local prepare` copied only the `.md` files, so the example the output format refers to was out of the member's reach), and the output format says in one sentence to see it beside the file. `contract/output-format.md` is five words longer (the ceiling in `tests/skill-budget.txt` is 323). The prompt of a cloud agent is the same texts without the file, so a deployed agent shows as stale until `qargi instances refresh-prompt`.
- The member contract asks for `qargi review check` to report no failure (`0 fail`, or `OK report-only run`) and says to explain a warn in the report, where it asked for `0 warn`: the warning for commits made within two minutes of each other cannot be cleared without rewriting history, which the contract forbids. The check is unchanged. The ceiling of `contract/contract.md` in `tests/skill-budget.txt` is 982.
- `qargi release finish` (and `--hotfix`) merges the tagged master merge commit into develop, or into the open release branch for a hotfix, instead of merging the release branch a second time (`Merge tag 'VERSION' into develop`, `--no-ff`). Master and develop used to differ by one merge commit per release (GitHub showed develop "N behind master" with equal trees, and `git describe` on develop did not reach the release tags); now the release's commits and every merge commit master holds arrive in develop with the one merge, so `git rev-list develop..master` is empty after a finish (not after a hotfix finished into an open release branch, which develop gets with that branch) and `git describe --tags develop` names the tag. `release start`'s list of the features merged since the previous tag works on develop for the same reason. History already on master is not rewritten: the first finish of this shape brings the earlier master-only merge commits into develop. The plan reads "merge tag VERSION (the master merge commit) into develop"; the intent record, the resume after a death following the push, the refusals and the exit 3 on a conflict are unchanged, and the conflict worktree now holds a merge of the master commit (kept beside it, so a run with `--resolved` uses the same commit). The `qargi help release finish` text, the manual page, the git-flow page and the `qargi-flow` skill (still 1145 words) say so. `tests/test_release_master_merge.sh` is the test.

### Removed
- Code and text that served records and layouts of earlier versions (qargi keeps no backwards compatibility). `install.sh --uninstall` with no install manifest removes nothing and says so (exit status 1), with or without `--force`; it no longer guesses at the fixed paths of an install that predates the manifest. `qargi upgrade` no longer warns about an `agents.json` of another shape (the agent verbs still refuse one, exit 2, and `agent add` still starts a fresh file). The class of a local run is the registry's alone (a record with no class counts as a run of work; a `class` file in the run directory is never read), the answers of a run are its registry snapshot alone (a record with none has none, and the stored project's file is not read in its place), and the project of a run is the one `prepare` recorded. `memplan.migrate(store, to_version, ...)` is `memplan.canon_plan(store, ...)` (the version argument and its check are gone), and the notes `canon plan` adds a missing `Sources` to say `carried over by the canon 2 plan`, not `migration`. The messages for a canon version other than 2, and for an archive manifest without file modes, no longer speak of migration or an older qargi; the report's limits no longer mention runs made before the registry existed; the migration prose is gone from the models page.
- `tests/test_legacy_lint.py` fails when `lib/` holds the phrases `older record`, `migrat` or `earlier version` outside `tests/legacy-allowlist.txt`, a list with a reason on every line that can only shrink (a line that matches nothing fails). The list is empty.
- The reading of an acceptance record that names no provider as the project's provider's (`lib/packs_audit.py`) and its line in `tests/legacy-allowlist.txt`. A skill acceptance counts only when its record names both the resource (`skills`) and the project's provider, as the verbs write it. A record that lacks either is nobody's: the audit shows the skill as not accepted (unmanaged), `acceptance` and `unaccept` say it is not accepted and change nothing, and a new accept is stored under `skills/PROVIDER/NAME` beside the old record, which is not rewritten. Accept such a skill again with `qargi skill accept`.

### Fixed
- The guard refuses a hook call whose input is empty or is not JSON (a hook cut off on the way, a runtime that sent nothing) instead of letting it through: exit status 2 and one line on standard error, `the hook input is empty` or `the hook input is not valid JSON (cause), so the guard cannot read the call; refusing it`. Every protocol the guard supports sends JSON, so no genuine call is affected.
- The guard refuses a call when the `class` or `ability` file of the run it works in exists and cannot be read (a directory in its place, a mode that bars it, a loop of links), instead of reading it as a run that is not read-only: one line, `the class file of the run RUN cannot be read (cause), so the guard cannot tell whether the run is read-only; refusing the call until the run directory is fixed`. A run with no such file is still a write run, and the `--class` of the hook still decides first.
- The guard refuses a call that needs the protected directories when a provider definition of the library does not load (unreadable, a name clash, a name that disagrees with its directory), instead of skipping the definition with a note and leaving its skills and agents directories unprotected: one line, `provider definitions that do not load: NAME (cause); ... refusing the call until the library is fixed (qargi provider check NAME, or remove the definition)`. A call that writes nowhere and reads no protected place (`ls`, `git status`) is not asked and still runs.
- The member's guard hook covers the `Monitor` tool, which a member has and which runs a shell command in the background: a `Monitor` call carrying `git push` (or any command the guard refuses from `Bash`) was let through because the hook matcher omitted it. The matcher is now `Bash|Monitor|Edit|Write|NotebookEdit|Read|Grep` in the Claude Code definition and the member template, `Monitor` is a shell tool in the hook data, and its `command` is judged by the same code as a `Bash` command. A member made before this change keeps the old matcher until `qargi agent refresh` (it shows as STALE). The members page lists exactly the tools the matcher has, and a test keeps the four places in step.
- `qargi credential setup lead-push` no longer puts the GitHub write token in the argument list of the `jq` call that builds the vault credential, where any user of the machine could read it with `ps`; the token goes to `jq` on standard input, as the file header already said it would. The body sent to the vault is unchanged, and `tests/test_leadcred.sh` records the arguments of every `jq` call of an apply and fails when the token is among them.
- `qargi feature finish` and `qargi release finish` can be run again after a death that came after their push. They pushed origin first and moved the local branches after it, so a process that died in between left origin finished and the local refs where they were, and the re-run died at "develop is behind or differs from origin/develop" or "the tag exists already". Both now write an intent record under the state (`finish-intent/PROJECT-release-VERSION.json`, `-hotfix-`, `-feature-NAME`) before they tag or push: the verb, the local and origin values of each ref before and the value the finish gives it, and the steps done. A re-run that finds it asks origin live: when origin holds exactly the intended refs it prints what is left (move the branches, delete the release or feature branch and the one on origin, the audit line, the after-steps) with a plan token, and `--plan TOKEN --approved "..."` does only those steps, each marked in the record so a second death repeats nothing; when origin still has the old values the push never happened, so the tag and the record are dropped and the finish starts again (by the apply, after its plan token is checked: a plan alone says they will be removed and removes nothing); when origin holds anything else, or only some of the refs, or cannot be asked, it refuses, names the ref and changes nothing, and says how to give the record up: the `rm` of the record and, for a release, the `git tag -d` of the tag the dead run made here, which would otherwise stop the next finish at "the tag exists already". A finish holds a pid lock (`finish-intent/PROJECT-KEY.json.run`) while it runs, so a second finish of the same name is refused instead of mistaking the record of a running one for a cut-off one; a lock whose process is gone is taken over, and of several verbs that find it at the same moment exactly one does (the check and the takeover are one step under a short `flock`). A push that exits non-zero keeps the record (and the release's local tag) and says that origin may hold the result anyway, since a lost answer looks the same as a refused push: the re-run asks origin and completes the finish, or starts it over. The record is removed when the last step is done. `tests/test_resume.sh` kills the verb right after the push with a `git` shim, and `tests/test_resume_push.sh` makes the push exit 1 after it reached origin and without reaching it, and each checks these.
- `qargi review apply` keeps its record of the apply in the lead's state (`apply/RUN-ID.json`), made before the branch is, and no longer relies on the `applied` file of the run directory (which a member can write; it is still written, because `local` reads it): a run whose file was removed is still refused as applied. A death after the branch was made used to leave a run that could not be applied again until the branch was deleted by hand; the re-run now removes a branch that is the base plus some of the patches and applies the series again (status `started`), or, when the branch was built (status `built`, with its tip), finishes the journal line, audit line, `applied` file and snapshot without applying the patches again, and refuses with what differs when the branch is no longer at the recorded tip. `tests/test_review.sh` covers the three cases. Two applies of one run cannot run at once: an apply holds a pid lock (`apply/RUN-ID.json.run`) and writes its pid and start token in the record, a second apply is refused while the first's process is alive and leaves its worktree, branch and record alone (it used to remove them, and the first apply's failure path then removed the second's), and only a record whose process is gone (or whose pid now belongs to another process) is resumed.
- A usage error exits 2, as the manual page says, where these verbs exited 1: every usage error of `qargi release` (no version, a version that is not one, an unknown option, an option that belongs to another verb, `release step` with no name or a blank `--evidence`), an unknown option of `qargi lead usage` and `compact-check`, `qargi feature merge` with no branch in a detached feature, `qargi mark` with a bad state, and `qargi discover show` and `install` with no ID. `tests/test_valued_opts.sh` no longer exempts `release.sh`.
- The guard protects the `finish-intent/` and `apply/` directories of the state, where the finishing verbs of a feature and a release and `qargi review apply` keep the records a re-run completes from, like `scrub_ok/` and `runs/`: a member's file tool or shell can no longer write, replace or remove one (it could have named the branch an apply makes or the tip it believes was built); reading stays allowed. The refusal names both directories.
- `qargi local clean RUN` also removes the run's apply record (`apply/RUN-ID.json` in the state, with its locks) and the temporary directories and worktree a `qargi review apply` of the run left when it was killed; a worktree is pruned from its repository, so the branch it held is free again, and a link in the name of such a directory is left alone and said. The two directories of an apply are now named with the run's id (`apply-in.RUN-ID.XXXXXX` holds the copy of the patches, `apply-wt.RUN-ID.XXXXXX` the worktree), which is how clean attributes them. `qargi local clean --orphans` also lists the `apply-in.*` and `apply-wt.*` directories of the state that no run of the registry accounts for (the run is cleaned or unknown, or the name carries no run id), under the same age rule and behind the same plan token and the lead's words as the `qargi-run.*` ones; a run still in the registry keeps its own, for clean RUN to remove.
- The provider adapters (`lib/providers/claude-code/adapter`, `claude-platform/adapter`), the guard command the claude-code adapter runs, `lib/conformance/cases.py`, `lib/env_apply.py` (`env check`) and `lib/tiers.py` (the canon check) start python again with `-I` and now add `-B` when the process that starts them writes no bytecode (`sys.dont_write_bytecode`), as the tests' `python3` wrapper does. The conformance suite wrote `lib/__pycache__` in a test run because `-I` ignores `PYTHONDONTWRITEBYTECODE`; `tests/test_hermetic.sh` now runs the suite of both shipped runtimes on a copy of the tool and fails when a `.pyc` appears under `lib/`. A normal run (nothing asked to skip bytecode) is unchanged.
- The copy of a passed run that `qargi local verify` saves in the lead's state (`runs/RUN-ID/`) includes `task.md`, so `qargi review apply --from-saved` applies the SCOPE of the run's task block, as the apply of the run directory does, instead of falling back to the member's own `scope[]` (a run whose directory was lost could be applied with paths the task forbade).

## [0.2.8] - 2026-11-09

### Fixed
- `qargi local clean RUN` also removes the saved scrub record of the run (`scrub_ok/RUN-ID` in the state, written by `qargi review check`), so a run that was checked and never applied leaves no record behind.
- `qargi release step` tells a failed write of the step record in plain words instead of printing raw `jq` text: when another command marked the step first, it says so and to run again with `--again`; otherwise it says the record cannot be written and to check that it and its directory can be written and that the record is valid JSON (commands that write the record wait for each other, so another command is not named as the cause). The exit status is unchanged.

### Changed
- `qargi project attach` and `qargi project show` name the declared `gates` where they showed only the test command: attach lists them (tier, name, command, feature tier first) after the `test command:` line of a stored project and says they replace it; `project show` keeps the answers as JSON on standard output and prints the same list on standard error. Without gates nothing changes.
- `qargi marshal handoff` lists the declared gates in a `== gates` section after the features (tier, name, command; they replace `test_command`), and `--json` carries them as `gates` (an empty list without gates). Without gates the note is as before. `qargi help` and the manual page describe this output, that of `project show` and `project attach` above, and the `--param gates=JSON` of `project new`.
- The gitflow scaffold (`qargi methodology files`, and the files `qargi project adopt` writes) renders the declared gates where it rendered only `{{test_command}}`: `README.md`, `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md` list them (name, tier, command) and `.github/workflows/test.yml` has one job for each gate, named after it (the name is a YAML single-quoted scalar, so the scan reads any name back; a feature-tier gate's job runs on every pull request, a release-tier gate's job only on a pull request from a `release/` or `hotfix/` branch or when started by hand; the jobs run in parallel while `verify` runs the gates in order, and `CONTRIBUTING.md` says so), so the CI scan of `release verify` finds every job matched. The markdown files write a name and a command as inline code in a fence of backticks longer than any run in them (`{{gate_name_code}}`, `{{gate_command_code}}`), so a backtick in a gate does not end the span. The new optional methodology parameter `gates` (one line of JSON) carries them; a template marks its parts with `{{#gates}}`, `{{^gates}}` and a `{{#gate}}` loop, each alone on its line. `qargi project new` with `--url` and `--param gates=JSON` stores the same gates in the project's answers, so the files, `feature verify` and the CI scan agree (without `--url` nothing is stored, as for every answer). A gate name or command, and any methodology parameter, may not hold a character that ends a line (U+2028, U+2029, U+0085, a vertical tab and the like, besides a newline), which would break the YAML and the markdown list. Without gates the files are byte for byte what they were.
- The `qargi-flow` skill and the `gitflow-member` pack say that a project may declare gates, that `feature verify` and `release verify` run them in order and stop at the first failure, and that a member runs only the checks of its own change (the pack's line about the checks of the touched paths calls them the PROFILE checks, so the word gates means only the declared ones). Their word ceilings in `tests/skill-budget.txt` are raised by 35 and 22 words, with the reason on the line.
- Every plan-token check except canon apply's now ignores `QARGI_NESTED`: the checks of branch prune, credential setup lead-push, the marshal owner verbs, project new, attach and adopt, provider accept, provision apply and the cloud instances verbs (agent update, normalize, refresh-prompt) are written `QARGI_NESTED='' need_plan`, as those of release, local, feature, upstream and backlog already were, so a nested environment can no longer apply a plan without its token. The verbs that clear the variable themselves (memory, tier writes, packs, project link) are unchanged, and canon apply still honours it because provisioning runs it that way. A new test, `tests/test_nested_plan.sh`, covers one verb of each file and checks statically that every `need_plan` call in `lib/` is prefixed or on a short list with its reason (canon apply, and the verbs that unset the variable first).

## [0.2.7] - 2026-11-09

### Added
- `qargi doctor [PROJECT] [--json] [--strict]`: a read-only check of the host, first slice. One line per check, `ok|warn|unknown  name: detail`, and under a warning the lines that say
  what you can do (nothing is run for you). The exit status is 0 whatever it finds, or 1 with `--strict` when a check warns. Four checks: `remove-ipc` warns when logind has
  `RemoveIPC` on (read with `busctl`, `QARGI_BUSCTL`) and the user has no linger (`loginctl`, `QARGI_LOGINCTL`), because logind then removes what lives in `/dev/shm` when the last
  session ends, and prints the drop-in `/etc/systemd/logind.conf.d/remove-ipc.conf` or `loginctl enable-linger`; `guard` warns when `qargi __guard` is not on `PATH` or does not
  answer as the guard (and when a member of the project is missing, stale or edited); `shm` warns on less than 10% free under `/dev/shm` (`QARGI_RUN_TMP`) or on an orphaned `qargi-run.*`
  directory; `window-source` names where the context-window table of the project's runtime comes from and warns on a model id of the project's roles that is not in it. Without
  systemd or a tool a check says `unknown`. A member may run it. The orphan listing of `qargi local clean --orphans` moved to `lib/orphans.sh` so both read the same code; `clean --orphans` prints what it printed.
- `qargi backlog`: a generic backlog kept in a markdown file that the new project answer `backlog.file` names (a path, `~/...`, or relative to the repository; it may be outside the
  repository, a memory store for instance; `project set` and `project validate` check it). An item is a top-level list line `- [ID] text` (ID a lowercase slug of two characters or
  more) with its indented lines; any other top-level list line is listed as unnumbered. `qargi backlog list [--json]` shows the open items and flags a duplicated id.
  `qargi backlog done ID --evidence TEXT` prints a plan with a token, and with `--plan` and `--approved` appends the item, the date and the evidence to `NAME-archive-YYYY-MM.md`
  beside the backlog file (created when absent) and removes it from the backlog, with an audit log line. The plans of `feature finish` and `release finish` add the line
  `backlog items named in these commits: ID, ...` for the open items whose id the merged commit messages name (information only, outside the token; nothing when the answer is
  unset or the file is missing). A member's guard refuses `backlog done` and `project set` of `backlog.file`; `backlog list` only reads.
- Declared gates: the project answer `gates` is an ordered list of `{name, command, tier}` (`command` a command line or a list of words, as `test_command`; `tier` `feature` or
  `release`; names unique and non-empty). `qargi project set` and `project validate` check it and name the entry that is wrong. `qargi feature verify` then runs the gates of tier
  `feature` in order and stops at the first failure; `qargi release verify` runs the feature gates, then the release gates. Declared gates replace `test_command` and
  `release.test_command` (a note says when one of them is not the command of a gate); the verdict line is still `full suite: pass|fail at SHA`, so `feature finish` and the
  release steps work as before. The run record lists each gate with its result (`pass`, `fail`, `not run`), `feature status` and `release status` show a `gates:` line, and a failed
  run names the failing gate. Without the answer nothing changes. A member's `project set` of `gates` is refused by the guard, as it is for `test_command`.
- `qargi release verify` reads `.github/workflows/*.yml` and `*.yaml` of the tree it verifies (standard library only, no YAML dependency) and warns on standard error, naming each
  CI job whose name and id match no declared gate name; a job whose name cannot be read (an expression, a block scalar, a flow mapping) is a note and never a failure.
  `release verify --strict` refuses, before anything runs, on any such job. With no workflow it prints nothing new; with workflows and no gate declared every job is named.
- A test (`tests/test_release_unrelated.sh`) covers the fallback line of `release finish --hotfix` when the hotfix branch has no merge base with develop but develop and master are
  related (master merges two histories): finish refuses with a line about the branch and develop only, without the advice for an unrelated develop and master.

### Changed
- `docs/flow/git-flow.md` says that `qargi review apply` runs the take-in scrub too, unless a passing `review check` recorded the same series (then it prints
  `scrub: skipped (review check passed it for this series)`), and names `qargi local clean --orphans` beside the other `local clean` forms.

### Fixed
- `QARGI_NESTED` no longer skips the plan token of `qargi feature finish`, `qargi feature merge` into a detached branch and `qargi upstream sync`: as for the release verbs and
  `local clean --orphans`, a caller that is itself approved has not approved this plan, so the token is always needed. Tests cover all three.
- `qargi backlog done` needs its plan token under `QARGI_NESTED` too, as the verbs above: with the variable set it archived and removed the item with no `--plan` or with a wrong
  one. Tests cover both and check that the backlog and the archive stay as they were.
- `qargi marshal handoff` judges the whole-suite record of a project with declared gates by the gates: the record's command is then `gates: NAME=COMMAND; ...`, which the note compared
  with `test_command`, so every feature showed as "another test command" even right after a passing `feature verify` at the tip. The identity is now built in one place,
  `lib/gates.py` (`gates.py identity ANSWERS TIER...`, which `feature verify` and the note both use), and the help of `marshal handoff` says what makes a run apply. Tests cover a
  gated project with a run at the tip and with a changed gate.
- `qargi doctor` changes nothing on the host, as it says. It ran `lib/orphans.sh` and `qargi agent list`, and loading `lib/lib.sh` made the config and state directories, set them
  to mode 700 (and `~/.qargi`), and created `instances.json`, `sessions.json` and `agents.json`: a host that had never run qargi got them from its first doctor. `lib/lib.sh` now skips
  that setup when `DA_NOSETUP` is set; the orphan scan sets it when run as a program, and doctor sets it for `agent list` and skips the member check when `agents.json`
  does not exist (see the next entry). The test starts with the data directories absent, and snapshots them, `HOME` and the directories of a host that has them (types, modes, sizes, times) before and
  after.
- `qargi doctor PROJECT` on a host with no members file says `ok ... no member is recorded on this host, so there is none to be stale` in its guard check. It said `unknown ... the members
  of project PROJECT could not be read (qargi agent list)`, which read like a failure; `unknown` stays for a `qargi agent list` that fails.
- The gate results of a whole-suite run are kept per run, beside its log (`STATE/suite-logs/PROJECT.feature-NAME.gates.jsonl`, `PROJECT.release-VERSION.gates.jsonl`), and not in one
  file per project: two verifies at once truncated and appended to the same file, so a record could list a gate twice or the gates of the other run. The verdict line was never
  affected. A test runs two verifies at once and checks each record. Two verifies of the same feature still share a log and a results file (the warning about other runs stays).
- The member guard no longer refuses a script written with a heredoc because of what its text mentions. A body that `cat`, `tee`, `grep` or `git commit` receives is
  now data in a line with other commands too (`cat > run.sh <<'E' ... E` then `chmod +x run.sh`), as it already was when every command of the line was one of those: a body
  with `project set $X` in a sentence was refused as the `project` verb with an expansion. The other commands of the line must only look at files, make, move or remove
  them (`chmod`, `mkdir`, `ls`, `mv`, `cp`, `rm` ...): a shell, `make`, `source`, a script, an alias or an `export` in the line keeps the plain reading, since the file could be
  run there. The lines of such a body that start a lead-only verb (`qargi ...`, also behind `sudo`, `env`, a shell, a keyword, a redirection or a continuation, the word
  `project`, `QARGI_LEAD`, `QARGI_NESTED`, `QARGI_MEMBER_RUN`, `marshal_`, `$'..'`) stay refused, and so do the lines an unquoted delimiter lets the shell expand. A body a
  shell reads (`bash <<E`, `source /dev/stdin`) or a pipe carries on (`cat <<E | sh`) is read whole. Tests cover the data, the nearest real violations and the linear time.
- The member guard no longer reads a parameter expansion with a subscript or an operator as a glob on the signing key: `${PIPESTATUS[0]}`, `${arr[@]+...}`,
  `"${files[@]}"`, `${!a[@]}` and `${#a[@]}` (so a loop over an array next to the word `marshal`, which was refused as a read of `credentials/marshal_*`) are allowed.
  A name that starts with `marshal_`, a glob in a default word (`${X:-*}`) and a recursive reader still are refused.
- The member guard reads the elements of an array literal as it reads the words of `for x in WORDS`: a glob inside `NAME=(...)`, `NAME+=(...)` or
  `declare|typeset|local|readonly [-aA] NAME=(...)` (also `[k]=` entries, and a relative glob after a `cd` into the credentials directory) that reaches
  `credentials/marshal_*` is refused when the array literal names the credentials directory, in plain words or through a variable the line sets (the entry below). Trimming
  the subscript off `${a[@]}` (the entry above) had let that through. A word with a variable after the path of the credentials directory (`credentials/${X:-ma}rshal_ed25519`,
  `credentials/m${X}shal_ed25519`, `cd credentials; cat $X`) is refused too, as the name the variable builds could be the key; the entry below widens this to a glob in the path.
- The member guard reads the signing key through a name it did not resolve before. It follows the plain assignments of the line (`NAME=VALUE`, also after `export`,
  `declare`, `typeset`, `local` and `readonly`, `NAME+=VALUE`, the variable of `for NAME in WORDS`, one value built from another) and reads `$NAME` and `${NAME}` in the
  later words, in `cd $NAME`, and in a string handed to `eval` or a shell, as each value the line gave: `d=~/.qargi/config/credentials; cat $d/marshal_ed25519`,
  `d=DIR; a=($d/*); cat ${a[@]}` and `for d in DIR; do cat $d/marshal_ed25519; done` are refused. A glob in the directory part before a variable
  (`cat DIR/../cred*/${X:-ma}rshal_ed25519`), a backtick substitution in the name (as `$(...)` already was) and an extglob pattern (`@(m)arshal_ed25519`, `!(other.token)`,
  with or without `shopt -s extglob` in the line: the pattern is read as `*`) are refused when they lead into the credentials directory. A name whose value the guard
  cannot read (`d=$(cmd)`, a variable the line does not set) is refused after a path in that directory, and also when it stands in the directory part before a name that
  starts with `marshal_` (see the next entry). The guard is best-effort: it reads the text of a command and cannot resolve every
  shell construct; the "Not covered" paragraph of its description in `lib/guard.py` names what it does not see. Tests cover each form and the nearest allowed ones
  (`d=DIR; cat $d/other.token`, `d=src; cat $d/marshal_x`, a loop over other directories).
- The member guard refuses a word whose last component starts with `marshal_` (the signing key's name) when an earlier component holds a variable, a command substitution or a
  backtick it cannot resolve: `cat $X/marshal_ed25519`, `cat $(cmd)/marshal_ed25519`, `d=$(cmd); cat $d/marshal_ed25519`, `cat DIR/../$X/marshal_ed25519` and the backtick
  forms, as the directory could be the credentials directory. The reason says the guard cannot tell what the word names and asks for a literal path. A variable the line assigns
  in plain words is resolved first and the real path is judged, so `d=src; cat $d/marshal_ed25519` stays allowed; a name the line also gives a value the guard cannot read
  (`d=src; d=$(cmd)`) is no longer taken for its other value, and `d=$(cmd)` is no longer read as an empty string. `$LIB/marshal_refs.py` is refused, as `${LIB}/marshal_refs.py`
  already was. A variable before a name that does not start with `marshal_` (`$X/other.token`) is allowed. Still not seen: an unresolved directory followed by a glob or
  another name (`$X/m*`, `cd $X; cat *`), a bare `$d` that stands for the credentials directory, and a script written and run. The assignments of the line are followed
  for the reads of the key and for a change of directory only; the target of a write is not read through them (`p=DIR; echo x > $p/f`), as before.
- A `cd` to a word with a variable keeps the directory unknown for a relative write after it, also when the line assigns the variable in plain words (a write after
  `d=src; cd $d` is refused, as it was before the assignments of the line were read): bash can give the name another value the guard does not follow (`read`, `printf -v`,
  a nameref, `declare -l`, `select`, `for d` with no `in`) or split the value into an option and a directory (`d="-L DIR"; cd $d`). The directories the values name are
  still judged for a read of the key (`d=DIR; cd $d; cat *`). Any relative write after a cd through a variable the line sets is refused again (for example
  `repo=DIR; cd $repo; echo x > a`); write the cd with a literal directory instead (`cd DIR/src`).
- The member guard judges a line of a thousand dependent assignments (`x1=$x0/b; x2=$x1/b; ... x1000=$x999/b`) in under a second; it refused it as too slow after 5 seconds, the time
  growing with the cube of the chain. The real path of a long name is now walked one name at a time and, from the first name that is not there, taken as written, so a path
  under a directory that does not exist costs the names that exist (it is the same path `os.path.realpath` gives, tested on links, `.` and `..`). The values of the assignments
  are resolved once, in the order of the line. A word read through variables as more than 256 words and a value built from other names longer
  than 16384 characters (no path is longer than 4096) are refused with a reason that says so, as a brace expression of more than 256 words is, and are not cut: a chain that
  squares its values at every step is refused at once and no longer searches. A name given more than 32 values (a loop over more words than that, the same name set many
  times, six appends `opts+=' -x'`) is unknown from then on, like a variable the guard cannot read: the command is judged as before, but a path through that name before a name that
  starts with `marshal_` is refused, and so is a relative write after a `cd` to it. An append (`opts+=...`) goes on from the values the line gave the name but still doubles them
  (2, 4, 8, 16, 32 values after 1 to 5 appends); the sixth append makes the name unknown. A long literal text (`x=<50000 characters>`) is no chain and is judged as before. A name used in
  one assignment before the chain assigns it (`a=$b/x; b=DIR`) stays as written there.
- The reason the member guard gives for a variable, a substitution or an extglob pattern after a path in the credentials directory no longer says the command "would read the
  signing key": it says the guard cannot tell what the word names, so it cannot rule the key out, and asks for the name written out (a literal path such as `credentials/other.token`).
  A glob or a name that does reach the key keeps the old wording. What is refused does not change.
- A heredoc body written in a line that also runs `install` is read whole again: `install --strip-program=PROG` runs PROG, so `install` is no longer one of the commands that
  run nothing (`chmod`, `mkdir`, `ls` ...). `coproc` starts the command after it, so a body line that starts with it is read as the lead-only verb it starts.

## [0.2.6] - 2026-11-07

### Added
- A test (`tests/test_release_snapshot_cycle.sh`) runs a whole release through plan tokens on a repository whose master is an unrelated snapshot commit, with a local bare
  origin that refuses non-fast-forward pushes: `release start`, `push` (which joins the history of master) and `finish` merge and tag master, merge develop, push
  by fast-forward only, and leave every earlier commit reachable. It found no bug.
- `qargi local clean --orphans [--days N]` lists the `qargi-run.XXXXXX` directories under `/dev/shm` (or `QARGI_RUN_TMP`) that no run of the lead's registry names, each
  with its age and whether it is named (a run's own directory, live or gone, is named; a link and a file are named and left). It prints a plan and a token and removes
  nothing; `--plan TOKEN --approved WORDS` removes only the unnamed directories older than N days (default 2, at least 1) with nothing newer inside, each checked again
  just before it goes, and logs the removal. The existing `--stale DAYS --scratch DIR` (finished runs) is unchanged.

### Changed
- `qargi project adopt` names the next step when two long-lived branches share no history (a master made as a snapshot, say), not only the problem: the first release
  joins them (`qargi release start VERSION`, then `release push VERSION`, whose plan joins the history of the first branch into the release branch, then `release finish
  VERSION`), or one merge by hand (`git switch develop && git merge -s ours --allow-unrelated-histories master`, which keeps develop's tree). Adopt still changes no branch.
- `qargi release start --hotfix` (its plan, and `release status`) and the refusal of `release finish --hotfix` say what to do when develop shares no history with master
  and no release is open: the hotfix could not be merged into develop. The line names the way out, the next release (`qargi release start VERSION`, `push` and
  `finish`: the push joins the history of master) or one merge on develop by hand (`git switch develop && git merge -s ours --allow-unrelated-histories master`), then
  `qargi release finish VERSION --hotfix`. It was a refusal at `finish` that only said to join by hand.
- `qargi review apply` runs the declared take-in scrub (the answers `review.scrub` and `review.trailer_policy`) before it makes anything, as `review check` does, so a lead
  cannot apply a series the scrub refuses: a failing scrub prints `scrub: FAIL ...`, refuses the apply and changes nothing. It skips the scrub, with the one line
  `scrub: skipped (review check passed it for this series)`, when a passing `review check` recorded the same series: `review check` writes, in the lead's state directory
  (`scrub_ok/RUN-ID`, not in the member's run directory), a hash of the patches in order and of the declared scrub, and apply compares it; a series (or a scrub answer)
  changed since the check is scrubbed again, and a check that failed leaves no record. `--from-saved` follows the same rule. A member's apply does not run the scrub
  (`scrub: not run`), as its check does not.
- `qargi local clean` and `qargi local close --applied-by-am`, when they refuse a run whose applied branch the lead rewrote by hand (the branch is not at the tip that
  `review apply` journaled, the two trees are the same and no rewrite is recorded), also name the fix with the real branch and tips: `git branch -f BRANCH OLD`, then
  `qargi ref record --rewrite BRANCH OLD NEW --why ...`. The other refusals keep their text.
- Where the runtime refuses a member's write tool for a report file, OUT never gets the report. The contract and the runtime's addendum now say to write OUT files
  with the shell (a heredoc) then, the runtime's notes have a `member-out` topic, and `qargi local verify` (an uncollected run, or a read-only run whose OUT has no
  report, as a note) and `qargi local clean` (an OUT with no manifest and no report) name that cause. A test shows the guard lets a build member write OUT files with
  a heredoc.

### Fixed
- The session-start hook's read of the open features (`qargi marshal status --all --brief --no-fetch`, 5 s) takes `QARGI_HOOK_MARSHAL_SECS`, a whole number of seconds from 1
  to 9999 (anything else is ignored; the default stays 5 and the hook stays bounded). `tests/test_marshal_refs.sh` failed once in a parallel suite run because that call,
  which takes 1.3 s alone on its hostile-records fixture, took 4 to 6 s under load: the read was cut off, the marshal block was empty, and with no tier files so was the
  context. The test now gives the hook 60 s and, when the hook's output is wrong, prints how long the status call took.
- The guard refuses input it cannot decode. A hook input that is not valid UTF-8 was taken for "not JSON" and let through; it is now refused (exit 2, one line on
  stderr). Input that decodes but is not JSON is still no call to judge and is allowed, as before.
- `qargi lead grant` and `qargi lead revoke` read each step's plan text and token from the step's `--json` output (the `plan` and `token` fields) and no longer parse the token out of text with sed. The steps run through `bin/qargi`; what is shown and applied is as before.
- `qargi project set` adds "(applies to the next provision ...)" only for the answers a provision reads (the list is `provision_reads` in `lib/project.sh`: repo.url and repo.long_lived, teams, roles, profiles, budget_cents, memory stores, models.provider, lead model, effort and push, packs, cloud). Every other answer (`runs.owned_refs`, `lead.context_window`, `release.*`, `review.*`, `deployment`, `test_command`, ...) prints only what was set. `deployment` no longer keeps the note for a value that names a cloud deployment: no provision reads it.
- `qargi release start VERSION [--hotfix]` is behind a plan token like `release push`, `finish`, `fix`, `publish` and `step`. Without `--approved` it changes nothing:
  it prints the plan (the branch, the base it is cut from and that base's head, the one commit that bumps the version, the files the commit changes, the date)
  and a token. `--plan TOKEN --approved "..."` creates the branch and writes the `release:start` line of the audit log, which `start` never wrote. The checks
  (the suite verdict, the preflight, the changelog and man page) run for the plan too, so a refusal comes before a token does; the token covers the head of
  the base and the date. The apply line it prints repeats `--date` and `--allow-empty-notes`. The tests, the skill, the manual page and the docs that start a release pass a plan.
- Two `qargi release step` calls at the same moment (or a step and `release finish`) no longer lose a step: the after-steps record was written through one
  fixed temporary file with no lock, so the slower call overwrote the other. The record is now read, changed and replaced under a lock (the one the registry of
  local runs uses) through a temporary file of its own name; a step another call marked done in the meantime is refused unless `--again`.
- The guard protects `scrub_ok/` of the state directory like `features/`, `runs/` and `handoff/`: a write, redirect, heredoc, `cp`, `mv`, `tee` or `ln` into it is refused,
  reading stays allowed. The record `review check` keeps there (the hash of a series that passed its declared scrub, which `review apply` takes as the scrub done) was
  writable by a member running as the same user, who could compute the hash and make the apply skip the scrub.
- `qargi review apply` copies `OUT/patches/*.patch` once into a directory of its own in the lead's state directory and hashes, scrubs and applies (`git am`) that copy.
  It read the patches three times from the run directory, so a member process still alive could change a patch after it was scrubbed and before it was applied. A
  patch that stops being a regular file while it is copied refuses the apply; the copy is removed however the verb ends.
- `qargi release start|push|finish|publish|site ... --approved WORDS` and `qargi local clean --orphans --approved WORDS` need the plan token even when `QARGI_NESTED` is
  set. `need_plan` returns without a check when that variable is set, so `release start 1.2.3 --approved x` created the branch, and `local clean --orphans --days 2
  --approved x` removed the directories it listed, with no token. A caller that is itself approved has not approved this plan; the packs, memory and tier-write verbs
  already refused to honour it. The lead-only verbs (`assets`, `sign`, `site`) still refuse a nested call as before.

## [0.2.5] - 2026-11-06

### Added
- Tracked post-release steps. An entry of the answer `release.after_steps` may now be an object `{name, command, who, evidence}` (`who` is `lead` or `owner`;
  `evidence` says what shows the step was done), besides a plain string, which stays valid and is a step named by its text, for the lead, with no evidence required.
  `qargi release finish` records the steps as pending and shows each as `[pending] NAME (WHO): COMMAND`; the new `qargi release step VERSION NAME [--evidence TEXT] [--again]`
  marks one done with the time and the evidence (a step that needs evidence refuses without it; an unknown name or version, and a step done already unless `--again`,
  are refused), changing only the record and never running the command; `qargi release status` shows `[done] ...` and, last, the pending steps, an owner's marked
  "waits for the owner: run COMMAND". A member's guard refuses `release step`.
- `--json` on any verb (`qargi AREA VERB ... --json`) prints the result as one JSON object, so a lead does not read a plan token out of text. When the verb printed a plan
  token: `{"verb", "plan", "token", "apply", "exit"}`, where `plan` is the text without the token line and `apply` is the call without `--json` plus `--plan TOKEN --approved
  "<the user's go-ahead>"` (the words are the person's to fill in). When it printed none (it ran or refused): `{"verb", "plan": null, "token": null, "output", "exit"}`. The
  exit status is the verb's and its errors stay on stderr. `--json` never supplies `--plan` or `--approved`; a call that carries them runs as before with a null token. It
  is one global option, handled in `bin/qargi` (`lib/jsonplan.py`) and described in `qargi help`, the manual page and completion; a verb with a `--json` of its own keeps it,
  and a member's guard treats the verb exactly as without it.
- The answer `release.version_files` (a list of paths relative to the repository) names other files that carry the version. `qargi release start`, once it has
  bumped VERSION, warns of the listed files that do not contain it (as a whole version: `0.2.1` is not found in `0.2.10`) and says to bump them on the release
  branch; `release status` and `release verify` show the same check on the branch. A warning, not a refusal; without the answer nothing is checked.
- `qargi release push` checks the answer `release.notes_file` (the notes file `release publish` already uses): its plan warns of the items of the version's
  `CHANGELOG.md` section that the file does not mention. An item is mentioned when its leading `` `backticked term` ``, else its first three words, occurs in the
  file, ignoring case and spacing. A warning only: the plan keeps its token. Without the answer nothing is checked.

### Fixed
- `qargi project validate` reports a role whose value is not an object (`roles.build = "x"`, `null`) as the finding `roles.NAME: an object`, and goes on to
  check the other roles, instead of failing with a traceback.
- Setting `repo.detached` or a `site` answer with `qargi project` prints only what was set; it no longer says the answer "applies to the next provision",
  which a provision does not read.
- `tests/test_local_run.sh` prints a failing `dispatch.json` check on one line (the file compacted, with the expected argv), so a parallel CI log shows it.
- `qargi branch prune` now treats an `agent/*` branch merged (`--no-ff`) into a branch of `repo.detached` or `repo.long_lived` as merged, so a task branch
  merged into a detached branch such as `gh-pages` is pruned like one merged into develop. Unmerged branches, branches at a tip, protected branches and
  branches held by a worktree qargi did not make are kept as before.
- A declared take-in scrub: the project answer `review.scrub` (a command line or a list of words, as `release.test_command`) is run by `qargi review check` in a throw-away
  checkout of the applied series, with the range in `QARGI_SCRUB_BASE` and `QARGI_SCRUB_TIP`, and `review.trailer_policy` (`none` by default, or `reject`) fails any commit
  with a `Co-Authored-By` or `Generated with` style trailer. The check prints one line, `scrub: ok` or `scrub: FAIL` and the first lines of the output, leaves no
  branch, tag or worktree entry in the repository, and a failing scrub fails the check. Both answers are the run's own copy taken at `local prepare` and a member's guard
  refuses setting them; with neither set nothing changes. A member's own `review check` (the member mark set) does not run it and says so; the lead's check does.

## [0.2.4] - 2026-11-06

### Added
- `qargi project adopt` names, among what is left for you, long-lived branches that share no history (a master made as a snapshot of the code has no merge
  base with develop): it changes no existing branch, so it does not join them, and the line says that `qargi release push` joins the history of master into
  the release branch. The branches adopt creates start at the tip of the default branch, so they are related to it and to each other.
- The `gitflow` methodology says what a master created as a snapshot of the code means: it has no merge base with develop, and the release branch is joined
  to it before the push by a merge of master that keeps the release tree. The release steps of `methodology.json` say that `qargi release push` does it, and
  the `CONTRIBUTING.md` scaffold (which never names qargi) describes the same merge for a person doing it by hand.
- `tests/test_docs_links.py` checks that every relative link of `README.md`, `CONTRIBUTING.md` and `docs/` resolves (to a heading, when it has a fragment), that
  the Documentation table of `README.md` lists each `docs/<topic>/README.md`, that `README.md` stays short, and that the `qargi` commands of its quick start exist.
- `qargi review apply` resets the author of every commit it applies to the lead's identity: the answer `git.author` (a string `Name <email>`, checked by
  `project validate` and set with `qargi project set PROJECT git.author 'Example Author <author@example.com>'`), else the repository's `user.name` and
  `user.email`; with neither, the member's author stays and the output says so. The committer and the dates are unchanged, history already applied is not
  rewritten, and the member's author is recorded in the ref journal and the audit log, not in the commit. The answer `review.keep_author` (`true`;
  default `false`) keeps the member's author instead. The guard refuses `git.*` and `review.*` in `project set` to a member.
- `qargi project template` carries `lead.context_window` as `null` (derive the window from the model of the session) and `project init` says
  which window the lead gets; `project validate` refuses a value that is not a number of tokens of at least 1000 (or null). The
  `qargi-project` skill lists the question.
- The runtime definition takes `resources.transcripts.windows`, a first-match list of `{model, tokens}` where `*` in the pattern stands for any run of
  characters (`claude-code` ships `*[1m]` and `*-1m` as 1000000). `lead usage --json` keeps its keys and adds `window_source`: `answer`, `model` or `assumed`.
- When the window is only the runtime's single `window` (no answer, no model in its table), `lead usage`, `lead compact-check --advise` (also its
  `--json` advice) and the line the stage verbs print say `(window assumed 200,000; set lead.context_window)`, so the percentage is not presented
  as fact; with the answer or a recognised model there is no such note.
- The project answer `runs.owned_refs` (a list of glob patterns for full ref names, such as `refs/heads/foo-*`; only the lead sets it, the guard refuses
  `project set` of it to a member) declares the refs a runtime or harness creates in the repository. `qargi local verify` and `local clean` accept a local
  ref that matches one, in either phase, and name it (`foo-x created; accepted: refs/heads/foo-* (owned by the runtime, per runs.owned_refs)`). A pattern
  needs a literal prefix of at least 3 characters after `refs/NAMESPACE/` and may not match `develop`, `master`, a `repo.long_lived` branch or the git-flow
  branches (`project validate` says so); a ref is never taken as owned when it is the base of a run that is not cleaned or closed, and a ref that matches
  no valid pattern is checked as before, in the strict phase too. The built-in rule for the harness's `worktree-bridge-*` branches stays.

### Changed
- When the window of `lead usage` is only assumed and the tokens in use exceed it, the real window is larger, so no percentage is printed as fact: the text,
  the `lead compact-check --advise` advice and the stage-verb line say `tokens exceed the assumed window 200,000; set lead.context_window`. `lead usage --json`
  keeps `percent` and adds `window_exceeded` (`true` only in that case; `false` otherwise). The `(window assumed N; ...)` label is unchanged for the rest.
- `README.md` is a front page: a short description, a quick start, a table of the documentation and the license. Its detail moved, text unchanged,
  into `docs/` by topic (`docs/install-and-upgrade/`, `flow/`, `members-and-providers/`, `skills-tools-and-memory/`, `reference/` and
  `development/`, each with a `README.md`, and `docs/README.md` for the overview). The comments and the help line that pointed at README sections
  point at the new pages.
- The line the stage verbs print and the verdict of `lead compact-check --advise` show the token count beside the percentage, for example
  `lead: 90%, 180k tokens of context; compact is safe now: run /compact`.
- A read-only run (an advisor or a review: a report, no patches) closes with a plain `qargi local clean RUN` once its output holds a `report.md`, its
  refs are unchanged and its clone holds no commit; `--discard` is no longer needed and no manifest is asked for. A run of work still needs its manifest.
- `feature finish`, refused while a run of the feature is open, now names each open run with the exact command that closes it (a read-only run: `qargi
  local clean RUN`; a run of work: the step it is waiting for), and `lead compact-check` does the same for a read-only run.

### Fixed
- `qargi project validate` no longer crashes (`NameError`) on answers with no roles: it reports the finding `roles: enable at least one role`. Its
  `tools_off` and `skills` checks ran only for the last role listed; they now run for every role.
- `qargi lead usage` and `lead compact-check --advise` no longer divide the context in use by a fixed 200000 window. The window is the answer
  `lead.context_window`, else the one the runtime's table gives for the model id of the session's last assistant turn (the entries `claude-code` ships
  match ids that end in `[1m]` or `-1m`), else an assumed 200,000 that the output labels as assumed, with the way to set the answer. A plain model id with no
  such suffix (for example `claude-sonnet-5-5`) matches no entry and gets the assumed window.
- `qargi release` works with a master that shares no history with the release branch (for example one parentless snapshot commit). `release start` and
  `release status` say that master and the branch have no merge base, and `release finish` refuses with the fix instead of printing
  `fatal: ... no merge base` and stopping at `refusing to merge unrelated histories` with nothing to resolve. `release push` joins the histories first: its plan
  has the line `join the history of master: merge master into the release branch keeping the release tree (-s ours --allow-unrelated-histories)`, covered by the
  plan token; once approved it makes that merge as a commit of its own on the branch, before the push, so CI runs on the joined head and the finish is an
  ordinary `--no-ff` merge. The tree of the branch must be the same before and after, and the commit must merge exactly the branch and master; otherwise the
  branch does not move and nothing is pushed. A repository whose histories are related gets no extra commit.
- `lead compact-check` and `feature finish` settle a run as merged by the same test as `local list` and `local clean` (`lib/merged.py`, one function
  for the three). A run whose applied tip the lead rewrote with `qargi ref record --rewrite` counts as merged when the commit it was rewritten to is on
  a branch other than `agent/*`, so a long-merged run in an old scratch directory is no longer listed as applied and not merged.
- `runs.owned_refs` can no longer reach the git-flow branches or the tags by a glob: a pattern is refused when it can match anything inside `refs/heads/agent/`,
  `feature/`, `release/`, `hotfix/` or `refs/tags/` (`refs/heads/rel*/0*`, `refs/heads/age*t/foo-*` and `refs/tags/v0.*` passed validation before, because only one sample
  name was tried), and a name under those, a tag or a `worktree-bridge-*` branch is never accepted as owned at the time of the check, whatever a hand-edited answer says.
- `local prepare` takes the answers that decide what verification accepts (`runs.owned_refs`, `repo.long_lived`, `repo.parking_branch`, `git.author`,
  `review.keep_author`) and the stored project's name into the lead's registry line of the run, and `local verify`, `local clean`, `local run` and `review apply`
  read them from there. They used to read the first `projects/*.json` whose `repo.path` was the repository, and `<conf>/projects` is not protected, so a member
  could add a `projects/aaa.json` naming the real repository with its own `runs.owned_refs` or `git.author`. A change of those answers now takes effect on
  the runs prepared after it; a run recorded by an earlier version, which has no copy, is read as before.
- A run is settled as merged (`local list`, `local clean`, `lead compact-check`, `feature finish`) only by a branch that settles it: a `worktree-bridge-*`
  branch and a ref the run's answers declare owned (`runs.owned_refs`) no longer count, so a member cannot create one at the applied tip and have the run
  closed as merged. The applied tip is the one the lead's ref journal records for the `review:apply` of the run's branch; `RUN/applied`, which a member can
  write, is read only for a run with no such line.
- The join of `release push` is made against the master its plan showed: it is refused when master moved between the plan and the join (a preflight, say), where
  it read master again. The merge no longer runs the lead's hooks or signs (`core.hooksPath=/dev/null`, `--no-gpg-sign`, as `review apply` makes its commits),
  and the plan warns when the release branch is checked out where the join would be refused (the main checkout, a worktree outside qargi's root, uncommitted changes).
  A hotfix whose develop shares no history with master and with no release open is told so, instead of being told to finish a release that does not exist.
- `review apply` resets the author of an applied commit with `--cleanup=verbatim`, so a repository with `commit.cleanup=strip` no longer drops the message lines
  that start with `#`; and the identity it takes from the repository's `user.name` and `user.email` (no `git.author`) is checked as `git.author` is (no angle
  bracket or control character in the name) and refused, with nothing applied, when it is not a plain `Name <email>`.
- Whether a local run is read-only is the lead's registry's to say: `local prepare` records the class of the run there, and `local clean`, `local verify`,
  `local close`, `local run`, `review apply` and `lead compact-check` read it from there. They read `RUN/class`, a file a member can write, and counted a run
  with none as read-only, so a write run could be closed with a plain clean and a fake report. Only a record of an earlier version, which has no class, falls back
  to the file, and a run with neither is a run of work. `local clean` and `lead compact-check` agree on what a report is: a regular file (not a link) named
  `report.md` or `NAME-report.md` directly in OUT.

### Security
- A member's guard refuses `qargi review apply`: it creates a branch in the lead's repository from a run's patches, with the lead's identity, and records it in the
  lead's ref journal, so it is the lead's like `local verify` and `local close`. (`qargi ref record` and `qargi branch prune` were already refused.)

## [0.2.3] - 2026-11-05

### Added
- `site.json` takes an optional `copyright` (one line of plain text, at most 200 characters, no markup; the forbidden words apply) that every page of the
  site shows, escaped, in its footer, the 404 page included, and an optional `license_url` (an `https://` address) that the words "MIT licensed" in it link
  to. With `copyright` unset the pages are unchanged. The fields of `site.json` are now listed in the header of `lib/site.py`.
- `qargi ref note REF...` journals a branch the lead made by hand, or pushed (`origin/NAME` for a branch of origin, whose live value is asked), so
  `qargi local verify` and `local clean` of a run prepared before accept it and name it a ref the lead noted. The journal line starts at an absent ref
  (or at the lead's own earlier note of that ref, as with a second push), so a ref that existed when the run was prepared, and any ref nobody noted,
  is still found. The guard refuses it to a member.
- `qargi local close RUN --applied-by-am` closes a verified run whose patches the lead applied by hand (`git am`): the lead's registry records it (`closed`,
  `closed_by`), the files are kept, and the run is no longer open: `lead compact-check` and the compaction advice stop counting it as applied and not merged,
  `feature finish` is not blocked by it, `marshal status` and the handoff note list it as closed, `local list` shows `closed`, and `local clean` removes it
  without asking for an applied tip. `review apply` refuses a closed run.
- `lib/site.py check` and `build` refuse a line of a hand page, or of `CHANGELOG.md`, outside a code fence that starts (also behind `>` and list
  markers) with an HTML-like tag, with the file, the line and the fix. A Kramdown (Jekyll) page reads such a line, for example a hard-wrapped code span
  whose placeholder lands at the start of a line, as a raw HTML block and shows everything after it as plain text, while every other check stays green.
  The site's own converter already refused raw HTML in a hand page, so its output cannot show the defect; its message now names the fix too.
- `lib/site.py check-output DIR --pages PAGES` compares each built page with its source: the h2 and h3 headings in order, as many pre elements as fenced
  blocks and table elements as tables. With or without `--pages` it refuses Markdown marks left in the text outside code (a backtick, `**`, `](`, `~~~`,
  a line starting with `#` or `|`; a backtick is accepted in the command reference). `build` runs the same check on its output and removes a build that
  does not show its pages.
- The answer `branches.push_develop` (`true`, the default, or `false`; set it with `qargi project set PROJECT branches.push_develop
  false`) decides whether `qargi feature finish` pushes develop to origin. The first line of the finish plan now says "will push
  develop to origin" or "local only, will not push" with the reason (no origin, or the answer), and the plan token covers it.
- `qargi feature verify` and `qargi release verify` warn on standard error, and go on, when another suite may be running: a
  whole-suite run of the project in progress, a local run of the repository with a file changed in the last 10 minutes
  (`QARGI_ACTIVE_MINUTES` changes that), or a `tests/run.sh` process in the repository (Linux).
- `qargi release fix VERSION` makes a worktree on the release branch under the worktree root and prints its path; after the
  fix is committed there, `release fix VERSION --push` (the same as `release push`) pushes it to the open pull request.
  `release finish` removes that worktree with the branch.
- `qargi release status` shows the checks of the release branch's pull request (name and pass, fail or pending), and for a tag a
  checklist of what is left after the release: the tag on origin, the GitHub release published or missing, the assets of
  `release.assets` present, the signatures of `release.sign.files` attached or unsigned, and the optional `release.after_steps`.
- `qargi release finish` lists the pull request's checks in its plan and refuses, without a token, while one fails or is
  pending, unless `--ignore-checks "<your words>"` is given (recorded in the output and the audit log when a check was actually ignored); a missing gh or
  pull request is a warning in the plan, and the apply refuses then unless the words are given.
- `qargi release assets VERSION` builds the release files from the tag: it makes a clean detached worktree of the tag under the
  state directory, runs the project answer `release.assets_command` (a command line, or a list of words with `{version}` replaced)
  in it, records the worktree, and prints where the files are and the next command (`qargi release sign`). `--recreate` builds
  again. `release sign` and `release publish` take the files from that worktree, so the repository's own checkout is not used.
- `release publish --asset-dir DIR` attaches every regular file of a directory; `--asset` also takes a full path inside any
  worktree of the repository; the answer `release.assets` may list globs (and `{version}`), taken in the asset worktree when
  there is one, else in the repository. A glob that matches nothing, a symbolic link that leaves the worktrees, a path with a `.git` component and two files of one base
  name refuse.
- The project answer `release.after_steps`: a list of commands or reminders (`{version}` replaced) that `qargi release finish`
  prints as `after the release: STEP` lines and records under the state (`release/PROJECT-VERSION.after.json`) so `release status`
  can show them. qargi never runs them.

### Changed
- `qargi feature finish` is refused first (exit 1, nothing changed) while a run prepared against the feature is open, with each open run listed and the way to
  close it (`local clean`, or `local close --applied-by-am`). A run that was cleaned, discarded, closed, or applied and merged does not block.
- The member text says that DONE of a write role requires `ls OUT/patches`.
- The lead's lease on a feature no longer lapses during a long worker run: every command of the current lead on the feature renews
  it (`feature merge`, `sync`, `status`, `verify` and `finish`; `local prepare`, `verify` and `clean`; `review check` and `apply`),
  once a third of the lease has passed and also when it lapsed meanwhile, as long as nobody else took the feature over. Another
  identity is still refused while the lease is live, and `marshal check` itself stays a read.
- `marshal release NAME` after `feature finish` (or on a feature that is abandoned, already released, or has neither a record nor
  a branch) exits 0 with one line, "nothing to release", instead of "you are not the lead of NAME, which is without a lead"; it
  needs no `--note` then. A feature held by another lead, or one with a branch that was never claimed, is still refused.
- `qargi feature status` says why a whole-suite result is stale: it lists the commits on the branch since the run (a merge of a task
  branch, a merge of develop, a plain commit) and names the next step, `qargi feature verify NAME`; a feature never verified names it
  too.
- A failed `qargi feature verify` (and `qargi release verify`) ends its output with the failing steps and tests that the suite
  runner's report names, where the runner kept the logs of the failed steps, and the path of a log of the whole run
  (`STATE/suite-logs/PROJECT.feature-NAME.log`, mode 600, the last run of each). The suite's output is shown as before, now with its
  error stream on standard output.
- `qargi review check RUN_DIR` checks `RUN_DIR/out` when it is given a run directory (no patches or manifest.json in it, an `out`
  directory in it) and says so in a note, so naming the run instead of its output directory is harmless. The `qargi-verify`
  skill names `RUN_DIR/out`.
- The `keep-a-changelog` pack tells a member to add an unnumbered bullet instead of numbering a changelog item itself, so parallel
  tasks do not conflict on the same number; the lead renumbers at merge with `qargi changelog renumber` (a member may only run it with
  `--check`), which `/qargi-verify` now names.
- The write role's text says that documentation follows the code: when the brief and the code disagree, the member follows the code and
  reports the disagreement.
- The `docs-site-member` pack tells a member that no line may start with a less-than sign (keep a code span that holds a placeholder on one line, or put the
  placeholder after other text) and to run the render check, not only the Markdown checks, before reporting.
- A wrapped code span in `CONTRIBUTING.md` no longer starts a line with a less-than sign.

### Fixed
- `qargi local verify` no longer reports the harness's bridge branch as a changed ref: a branch `worktree-bridge-NAME` held by a worktree
  directory `bridge-NAME` under a `worktrees` directory (or gone) is left out, and a branch of that name that no such worktree holds is still found.
- `qargi local verify` fails first, with exit 1 and "OUT is empty: the member did not collect", when the clone holds commits past BASE_SHA and OUT has no
  patches and no report, instead of leaving the lead to read the refs and the empty directory. `local clean --discard` is not affected.
- The advisor sign-off in the `qargi-flow` skill tells the lead to put "do not run the test suite while a feature verify is
  running" in the brief it writes for the advisor.
- `qargi release push` for a branch whose pull request is open says `updated PR #N` instead of failing with `gh pr create failed`.
- `qargi release site` no longer commits the built `_site/` on the site branch: a Pages build of the branch needs `_site/` empty.
  The build still runs, so a page that does not build refuses; the commit now records the release in `site.json` and removes a
  `_site/` that an earlier build committed.
- The verify rule of `local verify` and `local clean` accepts a `worktree-bridge-NAME` branch as the harness's own only when the worktree that holds it is
  the real path `<main worktree>/.claude/worktrees/bridge-NAME` and is locked, and a move of it is a fast-forward; a rewrite of the branch, a worktree of
  that name added elsewhere or left unlocked, and a deletion while a worktree of that name is still there are found.
- The guard refuses `qargi release assets` (it runs the project's `release.assets_command` with the lead's rights) and `qargi release fix` (it makes a
  worktree on the release branch and pushes it with `--push`) to a member, as it does `release publish`, `sign` and `site`; the guard's docstring, `qargi help
  guard` and the manual page list them.
- `qargi ref note` refuses a second note of a ref whose earlier noted value is not an ancestor of its current one (the ref was rewritten between the notes),
  says so and points to `ref record --rewrite` for an agent branch that keeps its tree, prints the author and subject of the tip it notes, and takes
  `NAME@SHA` to note a ref only while it is at SHA.
- `qargi local verify` of a run whose clone has commits and whose OUT is empty now also compares the refs and prints the verdict (exit 2 when they changed,
  else 1) next to "OUT is empty: the member did not collect", so a run that both broke out and did not collect is not told only the second; nothing is
  recorded, and the message says the run is not verified and that apply and close need a passing verify.
- `qargi local close RUN --applied-by-am` runs the refs check again (the refs-only verify that `local clean` runs) before it marks the run closed, so a ref
  that changed after the run's passing verify keeps the run open instead of being hidden by the close.
- `qargi review check RUN_DIR`, given the run directory instead of its `out`, renews the lease of the feature the run is based on (it looked for the run in
  the scratch directory before); the usage text and the header of `lib/review.sh` list `check`.
- `qargi marshal release NAME` for a name with no record and no branch (a typo) now fails with "no feature NAME in PROJECT"; the quiet success ("nothing to
  release", exit 0) stays for a feature that was finished, abandoned or released.
- A member run no longer renews the lead's lease from another directory: `qargi local run` puts `QARGI_MEMBER_RUN` (the run directory) in the member's
  environment, the marshal treats a process that has it as a member run as well as one working below a run directory (so `feature status|merge|sync` and
  `review check` renew nothing for it), and the guard refuses a command that sets or unsets it. A member started some other way is still told by its working
  directory alone. The comment on the guard's open `feature` verbs now says that status, merge and sync renew a lease.

## [0.2.2] - 2026-11-05

### Added
- `tests/run.sh --changed-from REF` (or `--changed-files FILE`, one path per line) adds to the fast tier the steps whose `covers`
  globs match a file changed since REF (`git diff REF...HEAD`) and those whose command names a changed file; a step with no `covers`
  is not added by its globs. `--plan` prints the selection and the shard plan and runs nothing, and a sharded run ends with a
  `shard i/K: planned Ns, the steps took Ns together` line.
- `tests/durations.txt` holds the recorded duration of every step, from a whole run, for `--shard i/K --durations
  tests/durations.txt`: the four parts of the suite plan within 1.3 times of each other (CONTRIBUTING, Tests, says how to
  regenerate it). `tests/test_ci.py` checks the CI workflow and the shard balance.
- The methodology parameter `ci_timeout_minutes` (default 30; a positive whole number, a parameter may carry a `pattern`) sets the
  `timeout-minutes` of the CI job the gitflow scaffold writes, so a project sets it from its own suite budgets.
- `qargi release status` shows, in the suite record's verdict, how long the run took and the mode its command names (`-j N`,
  `shard I/K`): `pass at this head (command: C; ran AT; took 412s; -j 8)`. `release verify` and `feature verify` record both; a
  record made before shows the command and the time only.
- Catalog entries for common development tooling, found with `qargi discover search` and installed as role packages:
  `pkg-golangci-lint`, `pkg-bats`, `pkg-podman`, `pkg-mandoc`, `pkg-golang` (the Go toolchain and a C compiler, so
  `go test -race` runs) and `pkg-gh` (the GitHub command line, for its release commands). A test checks every entry of the
  shipped catalog against the schema of its kind.
- `qargi project profile check [NAME] [--profile FILE]` (read only, so a member may run it) reads a repository's profile
  (`~/.qargi/config/profiles/<repository>.md`, the repository being the project's directory name, or FILE). It exits 1 while the
  profile still carries the shipped example's title or "Copy to" line, and warns (exit 0) of each backticked command in the
  profile's Gates section that is in none of the repository's `CLAUDE.md`, `AGENTS.md` and Makefile targets. No profile is fine.
  `project validate` prints the header finding as a `WARN:` line.
- `roles.ROLE.tools`: the tools a role needs beyond its apt packages, declared once in the project's answers as a list of
  `{kind, name, ...}` entries. `go` (a package path and a tagged version: `go install NAME@VERSION`), `binary` (a file name, version,
  the URL of the file and its sha256: downloaded to `~/.local/bin` and kept only when the hash matches) and `submodule` (a name and
  the path of a submodule of the repository). `project validate` checks each kind's keys and that two roles do not pin one tool
  differently. `qargi env plan` lists every tool with its state here (ok, missing, wrong, path) and the token covers the list;
  `qargi env apply` installs the go tools (go must be in `--approve-exec`) and binaries that are missing or wrong, after the
  bootstrap, and records them; `qargi env check` reports a tool that is not installed, is another version (`go version -m`) or
  another file (sha256), sits in a directory PATH lacks, or a declared submodule that is not initialised or at another commit.
  `qargi local prepare` checks the role's declared submodules out in the member's clone from the lead's copy of their objects,
  offline (a mirror with no remote under `RUN/sub`, push URL disabled) and prints `SUBMODULES=path,...`; a commit the lead's copy
  lacks, a submodule not initialised there, or a run made with `--repo-url`, is a note and nothing is fetched (`lib/tools.py`).
- Providers as data, one runtime per surface. Claude ships as two runtimes of one family, `claude-code` (local) and
  `claude-platform` (cloud), with a shared model catalog. The family name `claude` resolves per surface (a notice says so) in a
  project's `models.provider` and in `provider of`; every `provider` verb that takes a NAME takes a runtime name (there is no
  runtime named `claude`). Definitions follow `schema-2.json`: tiers with the date and source each model was verified, effort
  levels, a capability matrix, a `layout` (skills, agents, settings, memory, transcripts, render target, launch line; a verb that
  needs a facility the runtime lacks says `provider NAME has no FACILITY`, exit 3), a renderer for the member file, a dispatch
  (in-session or a command), a barrier and `notes`.
- `models.provider` per surface: `qargi project set P models.provider.local|cloud NAME` (a runtime that does not serve that
  surface is refused, exit 2), and `project new|attach` take `--provider NAME` or `--provider-local` and `--provider-cloud`;
  nothing is guessed. `project validate`, `init`, `attach` and `new` print `finding: models.provider is not set` (exit status
  unchanged); a verb that needs a surface the answers leave out exits 2 and says which.
- Provider notes: a definition's `notes` (up to 16 topics, one line each, plain text) say what the skills would otherwise have to
  say about the runtime. `qargi provider notes [TOPIC] [--project P] [--surface cloud]` prints one of the project's runtime (exit 1
  for a topic it lacks, exit 2 for a project with no runtime or one that cannot be used as it stands). `provider check` fails a bad
  note and warns when an in-session local runtime has no `spawn` note; an extension cannot add notes. `claude-code` ships `spawn`,
  `session-model`, `exploration`, `skills-dir`, `identity` and `commands`; `claude-platform` ships `output-dir` and `clone-dir`.
- Contract addenda: a definition lists `resources.contract_addenda`, text files of its own directory (16 KB each, no control or
  format characters) that are added to a member's contract, so the neutral contract never names a surface. `claude-platform`
  carries `cloud-run.md` (the detached-gate recipe, the no-wrapper git case, `/workspace/<repo>`, `/mnt/session/outputs`);
  `claude-code` carries `local-run.md` (background commands, `Monitor`, no foreground `sleep`). `qargi provider addenda NAME
  SURFACE` prints them. A cloud agent's prompt is the contract, the output format and the addenda of the project's cloud runtime
  (the prompt hash covers them); `local prepare` copies the local runtime's into the run's `CONTRACT` directory as
  `runtime-addenda.md`. `instances refresh-prompt` stops with `could not render the system prompt` when an addendum cannot be read.
- Provider packs in the library: `qargi provider new|import|seal|remove|enable|disable|attest` for provider, catalog and extension
  packs, each a plan, a token and your approval, with `--approve-exec` naming every executable. A pack holds text only (binaries,
  archives, links and secrets are refused). A pack counts only while it is what you sealed, and a capability counts only with a
  `verified.json` record bound to the definition's hash, written by `provider check` (hermetic cases) or `provider attest` (asked
  each time; it never runs or spends anything). A name defined both shipped and in the library is refused. The conformance harness
  is `lib/conformance/` (`tests/conformance.sh` still runs it).
- Extensions: a project's `models.extensions` compose onto its runtime; two that provide the same thing, or one that collides with
  the runtime, are refused, and an extension's capability counts only after `provider check` or `attest` of it passes.
  `provider show|check|layout|require-skills|launch --project P` and `provider effective ... --project P` show the composed view,
  and `agent for`, `provider accept`, `session` and `provision` read it. A member whose text depends on an extension shows `STALE`
  until `qargi agent refresh`.
- `qargi provider adapter-run NAME SURFACE VERB [--check]` runs a verb of a runtime's adapter (a library adapter only as a sealed
  private copy; a verb the definition does not list exits 3), and `qargi provider model NAME SURFACE TIER` prints a tier's model.
- `qargi local run RUN [--dry-run]` runs a task through a runtime whose dispatch is a command (a vendor CLI): the argv comes from
  the definition, with no shell and a scrubbed environment (only the names in `dispatch.env_pass`, shown in the review), and the
  output goes to `OUT/transcript`. It builds from the project's composed definition; a read-only run is refused when the barrier
  comes from an extension, or the runtime's own barrier is a hook or adapter, unless the project recorded `provider accept`. A
  runtime that works inside the session is refused.
- `qargi project link|unlink PROJECT [--resource skills,agents,memory]`: one plan and token links the project's skills, agents and
  memory into the work tree, each as the runtime's definition says (a directory link, one link per entry, or a copy; the memory
  directory becomes a link into `~/.qargi/memory/projects/PROJECT`). A real directory in the way moves to `NAME.qargi-backup`.
- `qargi packs link|unlink PROJECT`: the project's skills directory in the repository becomes a link to the render of `packs apply
  --target`, so a session in the checkout loads the packs without `--add-dir`. The plan lists what a real directory there holds
  (same as the library, differs, or new); apply moves it to `skills.qargi-backup`, `unlink` moves it back (also when the link is
  already gone); nothing is deleted. A foreign link, a symlinked parent, files tracked by git and a missing render are refused.
- `qargi packs check --target` ends with the skills a session would load, each `qargi`, `accepted`, `drifted`, `excluded` or
  `unmanaged` (only `drifted` changes the exit status), says when the checkout is not linked, and reads the exclusion from the
  runtime's settings in every form. `qargi skill accept|unaccept PROJECT NAME [--user]` records a skill qargi does not manage, by
  name and content hash. `project attach` hints when the repository has its own skills.
- Members are rendered from one neutral definition (`agents/member.json`, `member.body.md`) through the runtime's renderer.
  `agent list` and `agent models` show `STALE` (definition, catalog, renderer or an enabled extension changed) and `DRIFT` (file
  edited by hand).
- The render of a member is kept in the configuration directory, `~/.qargi/config/agents/PROJECT/NAME.EXT` (beside `agents.json`,
  outside every repository), and the runtime's file is written from it: `agent add`, `rename` and `refresh` write both, `remove`
  deletes both. A checkout that is cleaned or cloned afresh gets its members back with `qargi agent refresh NAME --project P`, which
  also hides the file from git again. `agent list` and `agent models` show `MISSING` (the runtime's file is gone), `STALE` (the copy
  in config is gone or changed, or the inputs of the render did) or `DRIFT` (the file was edited by hand), each with that command.
  `env check` reads the new form.
- Every skill and tool pack declares `compatible_providers` (runtime names, family names or `any`) as part of its content hash:
  `skill|tool new|import --compatible LIST` and `seal --compatible`. A project's runtime skips a pack it is not on, with a note in
  `effective`, `check`, `packs apply|check|link` and `discover install [--compatible]`.
- The member guard takes its hook protocol and protected directories from the provider definitions (`qargi __guard --provider
  NAME`).
- `qargi help guard` says in one place what a local member's guard refuses and what it allows, and `qargi help approvals` says that
  a token covers the plan seen, that `--approved` is recorded and not verified, that gated verbs are never allow-listed and that a
  member never applies. The manual page has a GUARD section.
- `qargi project validate` prints a `WARN:` line for each pack linked to a role of the project that is not in the pack library.
  `packs check --target` and `skill|tool check PROJECT ROLE` print `no pack is linked to any role of PROJECT` when none is.
- `qargi marshal handoff [NAME] [--write FILE] [--json]`: a read-only note for a fresh session, built from stored facts only
  (repository, HEAD, base, host, features, the marshal record, the packs check and launch line, the last `env check` and `env
  apply`), with the lead-only `qargi-session` skill.
- `qargi marshal claim NAME --as-successor-of ID`: a lead session that was restarted continues as the lead, without the owner's
  takeover, when the record's lead is ID, its lease is stale and the host, OS user and work tree are the same. Anything else stays
  the owner's `takeover`. `feature start` continues the same way, and `marshal status`, `marshal check` and `marshal handoff` name
  the command.
- `qargi lead usage [--project P] [--session ID | --transcript FILE] [--json]` says how much of the lead session's context is in
  use. `qargi lead compact-check [--advise] [--json]` says whether a `/compact` is safe now (exit 0) or not (exit 1) with every
  reason (an open local run, a merge waiting in the conflicts directory, a whole-suite run in progress, a handoff note older than
  the last merge, an open release or hotfix branch) and prints what to re-read after it. The window is the project answer
  `lead.context_window` (default: the runtime's `resources.transcripts`, which `claude-code` ships). qargi cannot run `/compact`.
- `feature finish`, the `feature merge` that closes a feature's last open run, `release finish` and `marshal handoff` end with
  `lead: N% context; compact is safe now: run /compact` (or why not) at or above the answer `lead.compact_advice_pct` (default 40;
  0 turns it off). They never fail or wait for it.
- `qargi env show [--project P] [--repo DIR] [--json]` prints what a repository declares about its development environment, read as
  text from files it already has: the `AGENTS.md` or `README.md` section headed Development environment, Environment or Setup;
  version pins (`go.mod`, `.tool-versions`, `mise.toml`, `.python-version`, `.nvmrc`, `package.json` `engines`); `.gitmodules`; the
  `bootstrap` and `doctor` targets of a Makefile, justfile, Taskfile or mise tasks; a devcontainer. It derives the doctor,
  bootstrap and dry-run commands. The project answers `env.doctor_command`, `env.bootstrap_command`, `env.dry_run_command` and
  `env.known_failures` override them. A member may run it. See `qargi help environment`.
- `qargi env check [--project P] [--repo DIR] [--timeout SECONDS] [--json]` says whether a checkout is set up the way its project
  declares and ends with `ENV OK` or `ENV INCOMPLETE: N missing (...)` (exit 0, 1, or 2 for usage). It runs the doctor command once
  (no shell, standard input closed, a minimal environment, a time limit of 300 s by default), so it runs the project's code. A
  doctor line that begins with `missing`, `fail`, `error`, `not ok`, `stale` or `[x]`, or ends with `missing`, `not found` or `not
  installed`, is a missing item; one that begins with `expected` or holds an `env.known_failures` entry is accepted. With no doctor
  command a built-in minimum runs (submodules, tags, pinned tools on `PATH`); for a stored project it adds whether skills, agents
  and memory are linked, `STALE` and `DRIFT` members, `packs check` and `memory check`. The verdict is recorded in
  `state/env/PROJECT.json`. A member may run it.
- `qargi env plan [--project P] [--repo DIR] --approve-exec NAME` and `qargi env apply --plan TOKEN --approved WORDS --approve-exec
  NAMES [--allow-root]` (the lead's) look at, then run, a project's bootstrap. The plan runs the dry-run command (which can run
  project code, so it exits 2 without `--approve-exec` naming its executable), shows its output with privileged lines (`sudo`,
  `doas`, `pkexec`, `su`, `run0`) apart, and prints a token. Apply runs the dry run again, refuses when the token or the approved
  executables differ or when privileged lines are present without `--allow-root`, then runs the bootstrap on your terminal and ends
  with `env check`, so a bootstrap that leaves the environment incomplete exits 1. The member guard refuses both.
- `qargi project attach` prints a `development environment found:` line and lists `env` gaps (no Development environment section in
  `AGENTS.md` or `README.md`, no bootstrap or doctor target). `qargi project adopt` writes a missing `AGENTS.md` and, when there is
  no task runner, a Makefile with stub targets; it never edits an existing file. `qargi project new` (the gitflow scaffold) writes
  the same `AGENTS.md` and Makefile stubs, and the scaffold's `CLAUDE.md` starts with `@AGENTS.md`. `qargi provision plan` prints the
  bootstrap command as a suggested setup script for the cloud environment. `qargi help environment` states the doctor line
  convention. This repository declares its own environment the same way (`make -n bootstrap`, `make bootstrap`, `make doctor`).
- Release publishing: pushing a tag `X.Y.Z` runs `.github/workflows/release.yml`, which creates the GitHub release with the
  version's changelog section as notes and the source archive and its SHA-256 as files (a tag not on `master`, or an existing
  release, is left alone; it can be run by hand for an earlier tag). `qargi release publish TAG` does the same through `gh`
  (`QARGI_GH`) with a plan and token. `release status|verify` warn about a tag with no release and a commit without the workflow.
  `lib/changelog_section.sh VERSION [FILE [HEADING]]` prints a section.
- Release signing is optional and off unless the project answers hold `release.sign` (`key`, `namespace`, `files`, optional
  `verify_command`). `qargi release sign VERSION` signs the listed files with `ssh-keygen -Y sign` on your own terminal (the
  passphrase never passes through qargi, a log or an agent; no ssh agent is asked), runs `verify_command` and records the result
  under `state/release/`. It runs only from the tag after `finish` and before `publish`, and is refused without a terminal, in a
  member run and under `QARGI_NESTED`. `release publish` attaches assets in the same call (`--asset FILE`, repeatable, and
  `release.assets`; `--notes-file FILE` or `release.notes_file` replaces the changelog notes) and, with `release.sign` set, refuses
  until a signature that still holds is recorded. `release status` says `awaiting signature` or `VERSION is ready for signing:
  qargi release sign VERSION`.
- Release answers that fit a project's own layout, all optional and checked by `project validate`, `init` and `set`:
  `release.version_file` (default `VERSION`; `none` for a project with no version file), `release.changelog.unreleased` and
  `release.changelog.released` (heading templates with `{version}` and `{date}`), `release.man_pages`, `release.test_command` and
  `release.preflight` (a command, `{version}` replaced, run by `release start` and `release push` before they change anything).
  `project attach` and `adopt` read the changelog heading and version file by them.
- Detached long-lived branches: the answer `repo.detached` lists branches (a documentation site, say) that never meet develop,
  master, release, hotfix or feature branches. qargi refuses every merge between them by name and by history. Tasks are cut from
  such a branch as from any base, and `qargi feature merge BRANCH agent/SLUG` with the detached branch as NAME merges a finished
  task into it (plan and token, local only).
- Parking branch: the answer `repo.parking_branch` (default `scratch`) names the branch the main checkout rests on while qargi moves
  develop; a refusal because develop is checked out suggests `git -C DIR switch -c scratch develop`. `qargi feature park [--project
  P]` refreshes it (a dirty tree, or a parking branch with commits develop lacks, is refused). After `feature finish` and `release
  finish` a clean main checkout on the parking branch is fast-forwarded to develop. The parking branch is never pushed or merged.
- Branch lifecycle answers: `branches.push_features` (`never`, `when-shared`, `always`; default `never`) decides whether `feature
  start|merge|sync` push the feature branch, and `branches.delete_merged` (`local`, `local+remote`; default `local`) decides
  whether `feature finish` also deletes it on origin (the plan shows it, and a branch with commits the feature lacks is kept).
- Worktree root: the answer `worktrees.root` (default `<state>/worktrees/PROJECT`) is where qargi makes worktrees, at
  `ROOT/<branch>`. `qargi feature start NAME --worktree` creates `ROOT/feature/NAME`; `feature merge|sync` update a clean worktree
  of the feature, and `feature finish` removes it. `feature list|status` flag other worktrees of the project with the `git worktree
  move` that fixes it.
- `qargi branch prune [--project P] [--remote]`: a plan and token for the merged `agent/*` and `feature/*` branches (with `--remote`
  also on origin, as a lease on the tip the plan showed) and the worktrees qargi made for them; `--plan T --approved WORDS` deletes
  them. A branch counts as merged only when it was merged with `--no-ff`; long-lived and detached branches, the parking branch,
  unmerged branches and branches checked out in a worktree qargi did not make are never touched, and each kept branch is listed
  with its reason. The member guard refuses it and `feature park` with sentences of their own.
- `lib/site.py`, a documentation site generator (Python 3.11 or later, standard library only; `python3 -I lib/site.py`).
  `build --release X.Y.Z --source DIR --out DIR [--pages DIR] [--url URL]` writes a static site: a command reference generated from
  `lib/commands.py` (one page per command group, plus the help topics, files and environment variables), a releases page from
  `CHANGELOG.md`, the hand pages of `--pages` (Markdown with `title` and `description` front matter, converted by a strict subset
  converter that refuses what it does not support with the line number), `sitemap.xml` (dates from the last commit, never the build
  time), `robots.txt`, `404.html` and `.nojekyll`. Each page has a title, description, canonical address, social-preview tags and
  structured data that describes only what the page shows; the stylesheet follows the reader's light or dark setting and needs no
  JavaScript. `check` validates the hand pages against the source (every `qargi` command and option they name exists in
  `lib/commands.py`, links and anchors resolve, the description is 120 to 155 characters), `check-output DIR` validates a built tree
  (well-formed HTML, unique ids, links, sitemap, no scripts, frames, forms or unsafe link schemes) and `diff OLD NEW --source-old
  DIR --source-new DIR` lists the commands, verbs and options that changed and the hand pages that still name what is gone. The
  build refuses paths outside the source tree, symbolic links, an `--out` that is not new or empty and a config or `static/` folder
  other users can write; it reads the source's `lib/commands.py` in a boxed child process, so give it only a source you trust.
- `qargi release site VERSION` regenerates the documentation site when a release ships: it builds the site of the tag VERSION with
  `lib/site.py` (the tag's tree is the source; the hand pages and `site.json` are those of the detached site branch) in a temporary
  worktree of that branch and commits it there as `Site: built from release VERSION` (`site.json` records the release, `_site/`
  holds the built site), behind a plan token and an approval, touching no working tree. It never pushes and prints the
  `git push` command instead; a build error refuses with the generator's report. The answers are `site.enabled`, `site.branch`
  (default `gh-pages` when `repo.detached` lists it) and `site.config` (default `site/site.json`, the hand pages in `pages/`
  beside it). With `site.enabled`, `release finish` ends with `next: qargi release site VERSION` (the new `after_release` step
  of the gitflow methodology, checked by `methodology check` and shown by `methodology show`) and `release status` says
  `site: not built for VERSION`, `site: built at SHA, not pushed` or `site: pushed`. The member guard refuses it.
- `qargi local list [--scratch DIR]` lists the local runs the registry names, with role, slug, age, applied and merged. `qargi local
  clean --applied --scratch DIR` cleans every applied and merged run and keeps the rest (exit 1 when one was kept); `local clean
  --stale DAYS --scratch DIR [--yes]` lists finished runs older than DAYS and, with `--yes`, cleans each by the rules of `clean RUN`.
- `qargi provision plan|apply --force` passes `ant apply --force` for a resource changed on the server; the token covers the flag.
- Four baseline packs, each `compatible_providers: ["any"]`: `review-findings`, `secrets-scan`, `docs-site-member` and
  `qargi-contributing`. The `qargi-providers` skill ships with the others, and `install.sh` refuses a python3 older than 3.11.
- `python3 lib/help.py man --keep-date FILE` keeps the `.TH` date of `man/qargi.1`, so regenerating the page after `release start`
  no longer undoes the date.
- Tests: `tests/test_skill_budget.sh` holds every text a member or lead loads to an exact word ceiling (`tests/skill-budget.txt`; a
  ceiling raised above its value at the merge base needs a `# raised:` comment), forbids a 12-word sentence in two texts
  (`tests/skill-dup-allowlist.txt`), requires every `qargi X Y` example to name a real verb, and requires every reference file under
  `skills/*/` to start with `Load when ...` and to be sent to ("load `FILE`") by its `SKILL.md`; a runtime's `notes` count as one
  text. `tests/test_neutral.sh` fails a vendor, model family or cloud CLI name in `skills/`, `roles/`, `agents/`, `contract/`,
  `packs/skills/`, `provision/templates/*.md` and `methodologies/` beyond the counts in `tests/vendor-words-allowlist.txt`, which can
  only shrink. `tests/test_tool_copy.sh` keeps `install.sh --copy`'s `tool_dirs`, the tests' `TOOL_DIRS` (one `copy_tool` helper in
  `tests/hermetic.sh`) and the top-level directories in step. `tests/test_valued_opts.sh` covers every option parser.
- Numbered changelog items, opt-in with the answer `release.changelog.numbered: true`. Under the unreleased heading
  (`release.changelog.unreleased`, default `## [Unreleased]`) an item is a line that starts `N. ` or `- N. `; the lines up to the
  next item belong to it. `qargi changelog renumber [--project P] [--check]` finds duplicate item numbers (two branches that each
  added an item 5), numbers the items again in file order from the first one's number and rewrites the `(item N)` cross-references
  (with a duplicated N, to the nearest item numbered N at or before the reference, else the nearest after it). It works on the
  `CHANGELOG.md` of the work tree around the current directory and leaves the change uncommitted; `--check` only reports and exits 1
  on a duplicate. `feature sync` warns about duplicates after the merge, and `feature finish` refuses (exit 1, nothing changed)
  until they are renumbered, committed and verified. A member may run only `--check`; `renumber` without it is refused by the guard.
- `qargi upstream status|review|sync` for a project that is a fork of an upstream repository and keeps its own changes, the
  overlay, on top of it. The answers name the remote (`upstream.remote`), the branch it follows (`upstream.branch`) and the
  local branch that carries the upstream line and nothing else (`upstream.into`, default `upstream`); `upstream.overlay_check`,
  optional, is a command array. `status` fetches that one branch of that remote (no tags, the only verb that reaches the
  network) and reports how far the branch is behind and ahead with the newest upstream commits; `review [--limit N]` lists
  the upstream commits not yet in the branch with the files each touches and marks the ones that touch a file develop changed
  since it parted from the upstream line; `sync` fast-forwards the branch to the fetched tip from a plan and a token
  (`--plan`, `--approved`), creates it at the tip when it does not exist, journals the move, refuses a branch with commits of
  its own, pushes nothing and never merges into develop (the next step, `feature start upstream-X` then `feature merge`, is
  printed); with `upstream.overlay_check` it then runs the command on a trial merge of the branch into develop in a temporary
  worktree (exit 1 on a failure or a conflict; the fast-forward stands). `project validate` checks the `upstream` answers.
  The guard refuses a member `upstream status` (its fetch changes the remote-tracking refs of the lead's repository, which
  `local verify` compares) and `upstream sync`, and `project set` of any `upstream` answer; `review` stays allowed.
  `tests/test_upstream.sh` runs the verbs against a local bare repository acting as upstream.
- `qargi ref record --rewrite REF OLD NEW --why "TEXT"`: the lead rewrites an `agent/*` branch to a commit with the same tree
  (`git rev-parse OLD^{tree}` must equal NEW's) while REF is at OLD, and the move is journaled with the reason, so `local verify`
  and `local clean` of a run prepared before it accept it and name it as a rewrite, and `local clean` and `local list` count the
  run's applied tip as merged when the commit it was rewritten to is. Refused to a member.
- Local runs survive a reboot. `local prepare` warns on stderr when `--scratch` is on a tmpfs (a reboot loses the run; use a
  directory on disk). A passing `local verify` copies OUT, a run bundle beside it and the run's snapshots to
  `<state>/runs/<run id>/`; `qargi review apply --from-saved ID` applies from that copy with the same checks as a normal apply
  (review check, `local verify --saved ID`, the registry's repository, slug and base, applied once), and the guard keeps a member
  out of `<state>/runs/`. `local list` and `qargi report` show a run whose directory is gone as `directory gone`, with its saved
  copy; `local clean RUN --discard` drops the registry entry (and the saved copy) of such a run, and `clean RUN` does once its
  saved work is applied and merged. A clean marks the run cleaned in the registry and removes its saved copy.
- `qargi release site` now ends with a reminder to preview the built site locally before pushing it, naming the site branch's build
  script and a local web server for the output.
- The generated documentation site has a left sidebar in place of the top navigation list, and a search box. The sidebar is on
  every page but `404.html` (which keeps a simple header and absolute links) and lists Guides (the hand pages, in `site.json`
  order), Reference (each command group folds its commands) and Releases; the page you are on has `aria-current="page"` and its
  section is open, the others closed. On a screen up to 48rem wide the sidebar sits behind a Menu button that needs no script.
  The build writes `assets/search-index.json` (one entry per page and per section, plain text, bounded to 256 KiB, its size
  printed as a note; the forbidden words of `site.json` are checked in the text of the generated pages) and `assets/search.js`
  (one small file: no libraries, no `eval`, no inline code), which adds a search box at the top of the sidebar, ranks title matches
  first, answers to the arrow keys, Enter and Escape, announces the number of results, and finds the index next to itself, so it
  works under any base path. Without script the box is not there and nothing else changes. `check-output` also requires the
  sidebar with exactly one current page, the script and the index (valid, bounded, an entry for every page, every entry pointing
  at a page or heading) and refuses an inline script.

### Changed
- The CI workflow `.github/workflows/test.yml` (no scheduled run): a pull request into a branch other than master runs the fast
  tier and the steps its changed files cover, or the whole suite when it carries the label `full-suite`; a push to develop, a pull
  request into master (the release pull request) and a manual run run the whole suite in four shards, balanced by
  `tests/durations.txt`, and a last job, `result`, is red when any shard failed. A pull request replaces its own earlier run, a push
  to develop is never cancelled. Each job has a time limit computed from the manifest's budgets (35 minutes; the former 30 minutes for
  the whole suite in one job was less than the budgets add up to, and the job was cancelled), the packages jq and shellcheck come
  from a cache keyed by their list (`.github/actions/tools`), and every action is pinned to a full commit SHA.
- `tests/run.sh` reads its steps from the manifest `tests/suite.txt` (tier, parallel-safe or serial, timeout, time budget, optional
  `covers` globs) and runs them `-j N` at a time (default: the CPUs, at most the cgroup quota; `-j 1` is the former serial run).
  `--tier fast` runs a fast tier of about a minute that covers every area, `--only PATTERN` selects steps, `--shard i/K` deals
  them to K parts by recorded duration or budget, `--shuffle SEED` and `--repeat N` look for a test that fails now and then, and
  `--enforce-budgets` fails a step over 1.5 times its budget (otherwise a warning). Each step has its own session, `HOME`, no
  standard input and a timeout, and fails when it leaves a process running; its output is printed as one block when it ends,
  and the summary lists the failed steps and the slowest ten before the `total:` line. The linter runs through `xargs -P`.
  The runner fails when a `tests/test_*` file is not in the manifest or a listed file does not exist; `tests/test_gitflow_detached.sh`,
  which no list ran, is now listed. `tests/test_runner.sh` tests the runner.
- `tests/run.sh` gives every step a `TMPDIR` of its own under the runner's directory, and compares the set of directories at the top
  level of the suite's `TMPDIR` before and after each step: a step that removed one it did not make, or left a new one, is named
  with the directories in its block (`WARN directories outside its own changed: removed ..., left ...`) and in a summary section.
  It is a warning, never a failure: with `TMPDIR` unset that place is `/tmp`, which every process on the host shares.
- Every command starts faster: what `bin/qargi` does before a verb runs (the dev-run banner, the arguments filled in from the
  current directory, the project's cloud binding) is one python process, `lib/help.py preamble`, instead of three, and the model
  list behind the completion of a model value is read from the runtime descriptors only then, not on every start. `qargi role list`
  takes about half the time it did. `tests/test_startup.py` keeps the count at one process and the time under the shrink-only
  ceiling of `tests/startup-budget.txt`.
- The tests are hermetic and safe to run concurrently with each other and with another whole suite: `tests/hermetic.sh` and
  `tests/hermetic.py` build one environment (fresh HOME, TMPDIR, config and state under one directory, UTC, C.UTF-8, umask 022, git
  without the host's configuration, no bytecode, no colour), and a lint (`tests/hermetic_lint.py`, run by `tests/test_hermetic.sh`)
  fails on a test that does not source it, names a literal `/tmp`, `/dev/shm` or `/run` path, kills by pattern, waits with a bare
  `sleep`, removes a directory it did not make, binds a fixed port, keeps a lock outside its directory or compares a wall-clock
  difference with a constant.
- `QARGI_WATCH_INTERVAL` sets the poll interval of `qargi watch` in seconds (default 30), so a test of the watch runs in two seconds
  and not in a minute.
- `roles.ROLE.go` is gone: a Go tool is a `roles.ROLE.tools` entry of kind `go`, and the cloud provision takes the environment's go
  packages from there (`NAME@VERSION`). `project validate` refuses the old key and says so. `roles.ROLE.apt` and `.pip` stay as
  they are: plain package lists of the cloud environment, with nothing pinned or hashed in them.
- Breaking: nothing assumes Claude any more. Set a runtime per surface for every project (`qargi project set P models.provider.local
  claude-code` and `models.provider.cloud claude-platform`, or `models.provider claude` for the family). `agent`, `provision`,
  `local prepare`, `local run`, session starts, `project validate`, `packs apply|check|link|unlink`, `skill accept` and `marshal
  handoff` take the runtime from the project and exit 2 with `set one with qargi project set P models.provider NAME` when it is
  unset; a name that is not a project says `no such project`; `--target` must be the runtime's `layout.render_target`.
- Breaking: members belong to a project. `~/.qargi/config/agents.json` is `{schema: 2, projects: {P: {NAME: record}}}` and any other
  shape makes every `agent` verb exit 2 without touching the file (`qargi upgrade` warns): move it aside and add the members again
  with `qargi agent add NAME --project P`. `--user` is gone from `agent add|refresh|rename` and nothing is written to a runtime's
  user-level directory. Two projects can each have a `worker`. `agent list` shows PROJECT, NAME, ROLES, MODEL/EFFORT, FILE;
  `agent remove NAME --project P` is new; `rename`, `refresh` and `remove` take `--project` (else the project in effect, set by
  `QARGI_PROJECT` or the checkout) and act only on that project's member; `agent models` needs a project and says `roles`, not
  `abilities`, in `--json`. A member that an earlier `agent refresh` wrote into the checkout is not moved: remove it and add it
  again.
- Breaking: the packs render lives in `~/.qargi/state/render/PROJECT/RUNTIME/` (it was `state/claude/PROJECT`; nothing converts the
  old directory: render again with `qargi packs apply --target RUNTIME PROJECT`, then `qargi packs link PROJECT` so a session in the
  checkout loads it, and remove the old directory by hand). `lib/packs_render.py` takes the skills directory, MCP file and settings
  from the runtime's definition. The link engine behind `packs link` handles a directory link, one link per entry, or a copy.
- Breaking: library skill and tool packs need `compatible_providers`: `qargi skill seal NAME --compatible any` (or a list); `packs
  seed` declares it on the baseline packs. Skill content hashes are stricter (symlinks, the executable bit and nested files count),
  so an accepted skill shows `drifted` once: `qargi skill accept` it again. Members show `STALE` until `qargi agent refresh NAME`,
  and cloud agents' prompts are stale: `qargi instances refresh-prompt NAME --if-stale`.
- Breaking: a usage error exits 2, as the manual page says (an unknown option, a usage line, a missing NAME, RUN or project, options
  that need each other); it was 1 in every shell verb and in `discover`, `export`, `import` and `methodology`. A refusal that depends
  on state or on an approval is still exit 1. A valued option given as the last word (`qargi agent for build --surface`, `upgrade
  --branch`, `project new --dir`) now ends with exit 2 and `OPT needs a value`.
- Breaking: the marshal lease length is the project answer `marshal.lease_minutes` (it was `marshal.ttl`; set the new key and drop
  the old one), a whole number of minutes from 1 to 1440, default 15. `project set` and `project validate` refuse any other value.
- Breaking: `feature finish` no longer deletes the feature branch on origin by default (it did whenever a tracking ref existed). Set
  `branches.delete_merged` to `local+remote` for that.
- Breaking: `models.extensions` and `models.accept_no_barrier` change only through `provider enable|disable` and `provider accept`.
  `project set` refuses them with exit 2 (it was 1), and `project init|attach|new` and `qargi import` refuse a file that adds or
  changes an entry (dropping one is allowed; restore a project by `project init`, then `provider enable`).
- Breaking: `install.sh --uninstall` removes exactly the paths an install recorded in `install.manifest` beside `install.json`
  (links, copied files, created directories; a directory that still holds a file you added is kept and said). With no manifest
  (an install made before this release) it removes nothing and says so, and `--uninstall --force` removes only the fixed paths the
  script writes. The directories come from the runtime definition's layout, and `--runtime NAME` chooses the runtime (default
  `claude-code`; an unknown one, or one with no skills directory, is refused before anything is written). The retired skills, old
  agent links and old `qargi`/`dev` skill links are no longer removed by `install.sh`: remove any left over by hand.
- Breaking: an archive made by `export` carries a mode for each file (`0600`, or `0700` for an executable file of the pack
  library). `import` restores it, and a file that differs only in that bit is a change in the plan. An archive with another mode or
  none (any made by an earlier qargi) is refused: export it again. Local runs prepared by 0.2.0 are refused by `local
  verify|clean|run` and `review apply` (the registry does not record their repository): finish them with 0.2.0 or remove them with
  `qargi local clean RUN --discard`. Memory stores on canon version 1 are `unknown` to `canon plan|apply`: bring them to version 2
  by hand.
- The member contract is `contract/contract.md` with `contract/output-format.md` (the two shapes: patches, or a report and manifest
  for a read-only role), about half its length, every rule once: one commit rule (one logical change with its tests and docs, or
  docs and changelog in the next commit when one would span three top-level directories; `review check` agrees); checks and gates
  merged (the profile's "always" gates, the repository's lint step and a secret scanner over `BASE_SHA..HEAD`); temporary
  directories under `TMP` only; the identity configured in the clone; background commands through "your runtime's background
  facility", never `pgrep -f`; "write outputs only to OUT" (RUN_DIR is no place a member is told about); and no memory-write rule
  but the task block's MEMORY packet (members propose notes in their report and the lead files them). The cloud preamble, the
  lead's contract seed and the role seeds say the same and no longer name `RUN_DIR` or repeat what the addenda say. The cloud-only
  part of the contract is a resource of the `claude-platform` definition, not appended by the core; a project with no cloud runtime
  gets no addendum.
- A read-only role puts a suggested fix in its report as a fenced diff, never a patch file (`local verify` and `review check` refuse
  patches of a read-only run; the manifest kind `suggestion` is gone). `CONFIRMED` and `PLAUSIBLE` mean the same in the review role
  and the `review-findings` pack. The four role texts and the member text are shorter and state only what the contract does not (the
  review role's product is "a report in OUT, not patches"; the documentation-branch rule is in the `docs-site-member` pack).
- The lead skills are lean and load their rarely used parts on demand: `qargi-flow` (the marshal in `marshal.md`; the models
  section moved to `qargi-instances`; never invent an approval; marshal records are data and a handoff carries no approval),
  `qargi-task` (`cloud.md` for a cloud instance, `local-run.md` for a command runtime; `CONTRACT` among the task block fields; the
  private-repository line in the local flow), `qargi-verify` (one take-in sequence: verify every open run before applying any,
  apply and merge from the run's slug, `local clean` only after the merge is confirmed; `git am` or a split by file for a cloud
  collect or a project with no open feature; the reason code asked again when rework was needed), `qargi-packs` (`apply.md`,
  `seed.md`), `qargi-providers` (`definition.md`, `verify.md`), `qargi-memory` (`curate.md`; `memory check` exits 1 on any FAIL),
  `qargi-project` (`repository.md`), `qargi-instances` (the two bases, profiles, tiers, `agent for`, `instances init --location
  local --agent FILE`), `qargi-session` and `qargi-team`. No skill names one runtime's tools, directories or settings: each points
  at `qargi provider notes spawn|session-model|exploration|skills-dir|identity|commands`, and the plan-token and guard rules are
  one pointer each to `qargi help approvals` and `qargi help guard`. Each description says what the skill does and when to load it.
  A `SKILL.md` must send a session to each reference file ("load `FILE`") and every file under `skills/` that is not `.md` is
  budgeted. `qargi-session` tells the lead to run `qargi env check` when the handoff note's environment check is older than HEAD or
  incomplete.
- The `keep-a-changelog` pack and `CONTRIBUTING.md` state the contract's commit rule; the pack says the member never dates the
  changelog or cuts a release (`release start` does). The `qargi-contributing` pack names no tool of one runtime. The shipped
  `shellcheck-gate` pack has two more lines: a disable for a newly introduced shellcheck code names the version that introduced it,
  and a lint severity the project configures itself beats `-S warning` (`packs seed` offers the update).
- `qargi local prepare` gives the run its own copy of the contract and prints `CONTRACT=` in the first, eval-able block and in the
  TASK-BLOCK PATHS block; it records a relative `--repo` and `--scratch` as real paths and `tmpdir` in the registry. Its help lists
  every key it prints.
- `qargi team brief` and `qargi collect` read the hosted output and clone directories from the cloud runtime's notes (`output-dir`,
  `clone-dir`); a brief for a project with no cloud runtime is refused. `collect` finds the project from the session's instance.
- `provider check` is no longer on the member guard's read-only list (it records a result); `provider model` and `provider
  notes|addenda` are allowed to a member (they only print). `provider check` runs adapters with a fixed environment.
- The member guard reads the text of a quoted argument or heredoc body as data when every command of the line is `echo`, `cat`,
  `tee`, `grep` or `git commit|log|status|diff|show|add`, so a commit message that mentions a refused verb is no longer refused.
  Any other program, a comment, a backslash, a substitution, `$'..'`, `${..}`, an unclosed quote or an assignment keeps the plain
  split, and `git push`, `gh` and `ssh` in text are refused as before. Under the read-only class a Bash command may write OUT and
  the run's temporary directory, as the Write tool does, and `git tag` with no argument or with `-l`/`--list` lists tags.
- `qargi project set P deployment VALUE` says only what was set for a methodology option. `skill import` prints `note: the source's
  top-level .pack.json ...` when the source holds a record of its own.
- Help and manual wording: `agent`, `concepts` and `roles` speak of roles, not abilities; `provider` describes one runtime on one
  surface; `local run`, `local prepare` and the render warning name no vendor and say `--target RUNTIME`; `local run` lists its exit
  statuses 0 to 4 and `review check` its exit 1; a refusal of the read-only class says "under the read-only class"; the manual
  page's SEE ALSO lists every shipped skill (a copy without `skills/` names them generically). `qargi help guard` names every verb the guard refuses, the protected files and
  directories (the pack library, credentials, `install.json`, `state/render`, the memory tiers, the state's `providers/`, the ref
  journal and the run registry, the marshal and feature directories, the runtimes' skills, agents and plugin directories, the
  lead's git configuration and session files), the rules for `cd`, the 5-second budget and the `git commit -F FILE` advice, within
  330 words; `tests/test_help.py` fails when a refused verb is in neither the topic nor a documented exemption, and compares the
  manual page's APPROVALS and GUARD sections with the topics.
- `qargi feature finish NAME` refuses a feature that is behind develop when both sides changed the same files since their merge
  base (exit 1, nothing changed). It lists those files and says to run `qargi feature sync NAME` first. A feature behind develop
  with no file in common is refused as before, without the list.
- `qargi release status VERSION` shows, next to the full-suite verdict, the command that produced it and when it ran (from the suite
  record). When `release.test_command` is set and is not that command, or the project's `test_command` changed since the run, a line
  of its own says so, so the pass is not read as the release gate. A record made by another command is shown, not reported as "not run".
- `qargi release start VERSION` lists, after it creates the branch, the features merged into develop since the previous tag (the
  `--no-ff` merges whose message is "Merge branch 'feature/...'"), one per line with the short sha, or says there are none.
- `local verify` and `local clean` accept qargi's own moves and name them (`develop moved by qargi feature finish`), so a run no
  longer has to be cleaned before the next `feature finish`. The ref journal also records the pushes, the deletions on origin and
  the tags of `feature finish`, `release finish` (and hotfix), `release push`, `branch prune --remote` and the pushes of
  `branches.push_features` (lines with `remote: "origin"` and the origin URL); verify accepts a remote-tracking ref of origin that
  says what origin has (a fetch), a tag fetched from origin, the parking branch fast-forwarded to develop's tip (by hand too), and
  every journaled move after a passing verify as well as before (a journaled deletion failed there).

### Removed
- Schema 1 provider definitions (`lib/providers/claude.json`, `schema.json`, the `claude/adapter` router) and all schema-1 code.
  `claude` is a family, not a runtime (`unknown provider 'claude'` from the verbs that take a runtime name). `project template`
  reads no Claude file: roles carry `model: null` until a runtime is set.
- `qargi migrate` (`roles` and `home`), the refusal that told you to run it, the import of archives made with the old role names,
  and `lib/roles.py`; the guard no longer protects `~/.config/qargi`.
- `qargi canon import` (`--map docs-v0`), the `imports` list of `canon/layout.json` and the canon section that described it: move
  the notes of such a store into the layout by hand. Canon chains older than version 2 (`canon plan|apply --default-role`,
  `provision/canon-seed/v1/`, `tests/canon_sim.py`); setting up an empty store has its own step.
- `qargi review prune [--yes]` (use `qargi branch prune`, which shows a plan and a token, also clears merged `feature/*` branches
  and the worktrees qargi made, and checks that a branch was merged with `--no-ff`; `review prune` deleted any `agent/*` branch
  that was an ancestor of develop or a feature).
- `agent add --abilities` (use `--roles`), `local prepare --ability` (use `--role`) and the `ABILITY=` line of `local prepare`.
- The one-per-role fallback: `agent for ROLE` resolves only the project's `worker` or `reviewer` (exit 1 with the `agent add`
  command when the base is missing; `--json` has no `legacy`; `agent models` says `not a base`), on the cloud surface too
  (`agent for ROLE --surface cloud --project P` prints the base or refuses: exit 1 unregistered, exit 2 overrides not verified). An
  instance of one role still works by name (`qargi send <project>-build ...`).
- The judgement of a local run made before `RUN/class` and `RUN/started` existed: no `class` counts as read-only, no `started` has
  no ref-journal entry and no age (`local list` shows `?`, `--stale` names it as skipped).
- `qargi credential askpass FILE` (internal, nothing called it) and the unreachable second `version)` branch of `bin/qargi`.
- From the role texts and the contract: the paragraphs that repeated the contract, the "Before DONE" tail, the build role's
  "Return numbered patches" line, the review role's enforcement note, the PDF-skill sentence and the memory-store bullets.

### Fixed
- The memory packet `local prepare` prints keeps to its cap of 3000 characters also when it ends with the line that says rows were left out
  (it could exceed it by up to 33 characters, more or fewer depending on the paths in the rows).
- The memory packet `local prepare` prints keeps to its cap of 3000 characters also when it ends with the line that says rows were left out
  (it could exceed it by up to 33 characters, more or fewer depending on the paths in the rows).
- `marshal status`, `marshal handoff` and `feature status` list an unmerged agent branch only under the feature its run was
  prepared against (`local prepare --base feature/NAME`, the base the registry of local runs records), not under every feature;
  the agent branches of no open feature are said once, on one `unattributed agent branches` line. The handoff note lists only the
  agent branches merged since the feature was cut from develop, not every merged branch in the history (the `(and 51 more)` tail).
- Task lines tell the truth: `marshal status`, `marshal handoff` and `feature status` said `not verified` of a run that had passed
  `local verify`, been applied, merged and cleaned. A passing `local verify` marks the run's line in the registry of local runs
  verified and `local clean` marks it cleaned (the line stays, one per run, rewritten under the registry's lock); a task reads
  `verified`, `applied` or `not verified` as the registry and the run directory say, and a cleaned run is listed only on a
  `cleaned:` line, never as an open task. `feature merge` of an agent branch whose run exists and has no passing verify warns.
- `packs check --target T PROJECT` no longer reports `manifest missing` for a project that was never applied, which looked like a
  broken render. It prints `not applied: ... (qargi packs apply ...)` and exits 0, and a render directory without its manifest still
  fails. The answer `packs.none: true` (`qargi project set P packs.none true`; `project set` of `packs` is refused to a member) says the
  project uses no project packs: the check passes with no render, and fails when a pack is linked to a role of the project. The
  section of the skills a session would load, the unmanaged ones in `~/.claude/skills` included, is printed in every case.
- `qargi project set P PATH false` stored the string `false`; it stores the JSON value, like `true` and numbers.
- `local clean --stale DAYS --scratch DIR` reported 0 runs when the run directories were gone (a reboot that emptied a tmpfs): it
  now plans and, with `--yes`, drops the records of such runs older than DAYS, keeping the one whose saved copy holds work that was
  never applied; a scratch directory that is gone itself is still read from the registry (`local list --scratch` too).
- `agent` verbs check the records of the project they are about, not every project; `agent rename` keeps a member file edited by
  hand and says so; a record that lacks `roles` or `file` is refused with one line naming the member.
- The dispatcher finds the project of an instance `PROJECT-ROLE` for every role, not only the four built-in ones and lead.
- The git authentication helper is a fixed script, `lib/askpass.sh`, reading the file in `QARGI_ASKPASS_FILE`; it left a
  `qargi-askpass.*` file in the temporary directory on every call.
- `qargi release`: `finish` names the repository without `.git` and reaches GitHub only through `$QARGI_GH`; `start` refuses a
  version whose tag exists; the pull request is titled `PROJECT VERSION`; `publish` shares the one exit handler. `release start`
  always sets the date and version of every manual page (an empty `.TH` date is filled) and `release finish` refuses a page that
  lost them, and, when `release.version_file` is `none`, a changelog with no section for the version.
- `qargi review check OUT` reads the patches from `OUT/patches/*.patch` only (it also took `OUT/*.patch`, which `review apply`
  never read), accepts a read-only run's report under an `OUT_PREFIX`, says `OUT` where it said `RUN_DIR`, and refuses an unknown
  option or a second directory with exit 2. `review apply` takes the patch files as a list (a space in a name is one patch) and
  finds the run by its real path. The `qargi-verify` skill and the README say `review check` takes the output directory.
- `qargi local clean`: refuses a run whose commits were never applied or whose applied branch is merged into no branch but
  `agent/*` (`--discard` drops them on purpose and says how many); `--discard` also removes a run whose refs changed (verify's
  outcome is a warning). It removes the temporary directory the lead's registry names for the run (only a real path directly under
  `/dev/shm`, `QARGI_RUN_TMP` or the run, never through a link or a trailing slash; a run prepared before this has none, so its
  directory is left), and only `RUN/tmp` when the registry has no line. `local list|clean` check the second word of `applied`
  before giving it to git, and `local list` prints the role, slug and path without control bytes. `local run` takes `TMPDIR` from
  the registry too. `local verify` and `local clean` no longer refuse the move that `feature merge DETACHED BRANCH` made to a
  detached branch.
- `qargi memory check` reports a half-initialised tier as `INFO ... (qargi memory init NAME finishes it)` instead of asking you to
  correct the path; an interrupted set-up of a store or tier can be finished by running it again.
- `export` and `import` can move a project between hosts: a name in an archive may begin with a dot (so the library's `.pack.json`
  records pass; `.` and `..` do not), a memory note's name is checked with the same rule as every other name, `export` checks
  every name before it writes and stops, naming the file and how to go on (rename it, or `--only`), and says when it leaves out a
  symbolic link or a note whose name the reader would refuse. A script in a skill keeps its executable bit.
- Importing a pack directory that carries qargi's own record follows one rule shared by import, review, content hash, render and
  audit: the top-level `.pack.json` is qargi's metadata and is ignored and not copied; a deeper one is skill content, so the review
  fails it and the hash counts it.
- `install.sh --user --copy` copied the tool without `canon/` and `catalog/`; it copies from one list (`tool_dirs`), and
  `tests/test_install.sh` runs `qargi help` and `qargi discover search` from the copy.
- A cloud agent's prompt and `local prepare` stop with the reason when the project's runtime is set but does not resolve, instead
  of leaving the addenda out; `instances refresh-prompt` records no hash for a prompt that failed to render, so `instances show`
  says `unknown`. No project, a project not stored, or no runtime for the surface still means no addendum.
- `packs check --target claude-code` no longer reports "shadowing" for every rendered skill once the checkout's skills directory is
  the link made by `packs link`. `packs link|unlink` work through no-follow descriptors and say where your skills are when something
  fails; names in offers are quoted and control characters stripped; an unusual name is `skipped: unusual name`.
- The member guard no longer refuses valid work: a file write because one provider definition in the library is broken (it skips it
  with one note); `qargi provider model`; `tee OUT/report.md < r.md`; `$OUT` and `${OUT}` in a write (they mean `RUN/out` unless the
  command could give `OUT` a value); `git commit -m push`, `git log -S push`, `git grep push` and `git branch push` (it looks only
  at the git subcommand); a copy into the home directory (`cp src/a.go ~/`, `rsync -a build/ ~/`, `grep -r TODO ~`, `find ~`),
  which is no read of the signing key (copying or searching the credentials directory itself still is); an `mv` into a directory
  that only lies above a protected place; a trimming expansion such as `${f%%:*}`; the script of `sed -i -e`, `sed -i -f` and `perl
  -pi -e`; `cd ../../out && echo "$(date)" > report.md`; and a build member editing the repository's own `docs/tmpdir`. A directory
  of the clone that holds a file named like the run's record is not taken for the run. Its tool names are the member's matcher's
  (`MultiEdit` and `NotebookRead` are gone from the hook data and the shipped definition).
- The member guard stays within the hook's time: a command it cannot check within 5 seconds is refused (a killed hook does not
  block), and two quadratic regular expressions (a long run of blanks; many `marshal handoff` or `project set` words) are gone. A
  brace expression is expanded whole or the call is refused (more than 256 words for one word or 20000 for the command).
- The guard's refusals to a read-only member say the report goes to `OUT` (they said `RUN_DIR`), and the refusal of a skill change
  says to propose it in the report.
- `qargi env check` printed `packs: no drift` for a project whose packs were never applied, since `packs check` passes then; it prints
  `packs: not applied (qargi packs apply --target T PROJECT)`, a note and not a missing item.
- `qargi env check` counted a `STALE`, `DRIFT` or `MISSING` member as current when the path of its file made the `agent list` line
  longer than 160 characters: the line was cut before its state was read.
- `install.sh --project DIR --uninstall` (and `--user --uninstall`) left an empty `~/.qargi/config` behind. The install records the
  config directory and the parents it had to create, and the uninstall removes them once nothing else is left in them.
- `tests/run.sh` printed nothing for a failed step that wrote to standard error (every failed Python test): the loop that closes a step's
  stray descriptors also closed the saved copy of its standard error, which stayed pointed at /dev/null. The block now carries the
  step's own output, and an `exit status N, M bytes of output` line.

### Security
- A member's `qargi project set` of `roles.ROLE.tools` (or of a whole role, or of `roles`) is refused, as `env.*`, `release.*` and
  `test_command` are: the list names what `env apply` installs and runs with the lead's rights and what `local prepare` checks out.
- The member guard refuses more of what runs a refused verb or `git push`, and allows nothing the earlier guard refused:
  - It cuts a Bash command at every `;`, `&&`, `||`, `|`, `&` and newline, inside quotes, comments and heredocs too (write a commit
    message to a file and `git commit -F FILE`), reads a command substitution as a command of its own wherever it sits, a verb
    after `then`, `do`, `!`, `(`, `{`, a case pattern, a redirection or a function definition, `git push` and `gh` inside `sh -c`,
    `$'...'` and `$"..."` quoting as the plain string, a subcommand or verb that a variable or substitution builds, and the command
    after `find -exec` or in `parallel`'s operands. It refuses `git send-pack`, `http-push`, `svn dcommit`, an rsync operand of the
    form `host:path`, `git -c` with an alias or program key, `--config-env`, `--exec-path` and the `GIT_CONFIG_*`, `GIT_EXEC_PATH`
    and `GIT_SSH_COMMAND` variables.
  - A command with a NUL byte, over 262144 characters, nested more than 40 substitutions deep, with a glob that needs more than 4000
    directory entries, with more than 24 directories at once, or taking over 5 seconds to check is refused, because a hook killed
    at its timeout does not block.
  - Redirections before the program or standing alone, `>|`, `<>`, `>&FILE`, `git log|diff|show --output`, `format-patch -o`,
    `archive -o`, `bundle create`, `sort -o`, `uniq IN OUT`, `cp|mv|install|ln -t`, `dd of=`, `sed -i`, `tee`, `tar`, `unzip`,
    `curl`, `wget`, `patch`, `git apply --directory`, `git clone|init|worktree add DIR`, `awk -i inplace`, `ex|vi|vim|nvim|ed`,
    `rename`, `sqlite3`, `setfacl`, `mkfifo`, `find -delete|-exec rm`, `ln` of a protected location, and the git subcommands that
    write objects or the index are writes to their target; the Edit and Write tools are held to the same. A target built by a
    glob, a variable or a substitution is refused when it could be a file of the run's record or hide it, as is a file name with a
    `;`, `|`, `&` or newline that leads into a protected location.
  - A `cd` is followed only when it surely happens (a plain top-level command, or a chain of cds after `&&`); otherwise the
    commands after it are judged from every directory the shell may be in. After a `cd` it cannot read (`cd "$d"`, `env -C`,
    `CDPATH`) a relative write is refused until an absolute `cd`. `git --work-tree=DIR` and `GIT_WORK_TREE` count like `-C DIR`.
    `${NAME...}` forms are read by the environment's value.
  - A line with `printf -v` (and `read` or `local`) is no longer read as text only, since it assigns a variable; a heredoc
    delimiter that starts with `#` is left to the plain split.
  - The run's record (`ability`, `class`, `profile`, `refs.before`, `refs.before.new`, `applied`, `repo.path`, `repo.url`,
    `cred.path`, `dispatch.json`, `task.md`, `tmpdir`, `started`, `verified`, `refs.after`, `refs.diff`, `git`) cannot be written,
    moved, removed, copied, linked or truncated, nor the run directory itself used as a destination (`cp -r Y/. ../..`, `tar -C
    ../.. -xf`, `unzip -d ../..`); `notes`, `out/`, `clone/` and `tmp/` stay writable. The read-only class holds when its hook
    passes `--class read-only` even if `ability` and `refs.before` were moved away, and refuses `git bisect`, `symbolic-ref` with a
    value, `reflog expire|delete`, `hash-object -w`, `unpack-objects`, `git lfs` writes, a `git tag` that makes, replaces or
    deletes a tag (options read as git reads them, abbreviations included) and setting `PATH`, `GIT_*`, `PAGER`, `BASH_ENV`,
    `RIPGREP_CONFIG_PATH`, `LD_*`.
  - For every member: the lead's git configuration (`~/.gitconfig`, `~/.config/git`, `git config --global|--system|--file`
    outside the clone, `git init` of the home directory), session settings and startup files (`~/.claude/settings.json`,
    `settings.local.json`, `CLAUDE.md`, `commands/`, `hooks/`, `~/.claude.json`, `~/.bashrc` and the other shell startup files,
    `~/.ssh/config`, `authorized_keys`), the run registry and its lock, the lead's run and agent verbs (`local prepare|verify|
    clean`, `agent remove`, `project new`, `team run`, `task`, also through `local.sh`, `agent.sh`, `team.sh`), `project set|init|
    link|unlink` whenever its words cannot be read statically, `provider check` and `provider adapter-run`, and the link and
    render scripts of the tool itself. Every read of the signing key is refused, also through a leading or numbered redirection
    (`<KEY cat`, `exec 3<KEY`), and `mv -T` into a protected place is too.
- `local verify|clean|run`, `local list`, `review apply` and `clean --applied|--stale` act only on runs the lead's registry
  (`state/local-runs.jsonl`) names, and take the run's repository (`repo`, or `url` and `cred`, the path of the credential file and
  never a token), slug, base and temporary directory from it, not from files in the run directory that a member can write. A
  repository a member chose ran its own `.git/config` in the lead's shell, and a `repo.url` with a `cred.path` sent any readable
  file as a token to a host of the member's choice. A run whose files differ from the registry is refused with the difference
  named; a run the registry does not name, or names with no repository, is refused too, and `clean --discard` still removes it.
  `local list` reads `started` as a number and prints `?` for anything else (the text was used in shell arithmetic).
- `qargi local run` writes `OUT/transcript`, `OUT/transcript.err` and `RUN/dispatch.json` only as a new or a regular file with no
  second name, opened without following a link or waiting for a reader, and checks `dispatch.json` before it starts the process;
  `OUT` must be a directory of the run. It reads `RUN/task.md`, `profile` and `ability` the same way, and a run with no `ability`
  is refused with a message. `qargi review apply` writes the run's `applied` record and `refs.before` snapshot in the lead's state
  directory and renames them into the run (`mv -T`), and an `applied` that is a link or not a plain file refuses the apply.
- A runtime's adapter (`provider adapter-run`, so `agent for --surface cloud` and the session verbs) ran with the caller's whole
  environment, forge tokens and ssh agent included. It gets the small environment a pack gets plus `dispatch.env_pass`, which also
  refuses `HOME`, `PATH`, `LD_*`, `GH_*`, `SSH_*`, `JDK_JAVA_OPTIONS`, `FPATH`, `ZDOTDIR`, `KSH_ENV`, `LUA_*`, `LESSOPEN`,
  `GLIBC_TUNABLES`, `NPM_CONFIG_*`, `GOFLAGS`, `GOENV`, `INPUTRC`, `TERMINFO` and `SUDO_ASKPASS`. A member's command also gets
  `LC_ALL` and `TZ`.
- A library provider pack with no record (placed by hand) is not loaded, run, checked or attested: seal or import it. Skill and tool
  packs are held to the text-only policy of provider packs (no binaries, archives, links, special files or file over 1 MB; scripts
  stay allowed and listed); the review refuses control and bidi characters, also as JSON escapes, and prints everything escaped. The
  content hash of a skill pack also covers a link, a pipe, a socket, an empty directory and a file with a second name; a pack
  without any of them hashes as before, so no approval is lost.
- A runtime that claims `read_only_barrier` with barrier kind `none` and no read-only arguments fails `provider check` and import
  and reads as no barrier, as does a barrier hook whose refusal cannot be told from an allow (equal exit codes, or an empty stdout
  object); a `local run` of a read-only member is refused for it unless the project ran `provider accept`.
- `qargi local prepare` refuses a `--repo-url` that carries a user name or a password; the token goes in `--credential-file`.
- `qargi project link` (memory) compares real paths, so a link below the memory root that leads outside it is refused, and a project
  whose tiers resolve without a project tier is refused with a message, not a traceback.
- `qargi project set` of `release.*`, `test_command`, `env.*` or `site.*` is refused to a member, as `models.*` is: the lead later runs
  those commands, or builds and commits the documentation site from `site.*` (`qargi release site`), so a member that set them would
  run its own command with the lead's rights.
- The member guard refuses `git config` that writes a key which makes git run a program, read another configuration file or give a command or a remote
  another name, as it refused the one-shot `git -c` form: `git config core.fsmonitor ...`, `git config alias.x '!...'`, `git config include.path ...`,
  `git config core.hooksPath ...` and `git config alias.p push` (then `git p` pushed) were allowed since 0.2.0. Both forms share one list (core.fsmonitor, hooksPath,
  sshCommand, editor, pager, askPass, gitProxy, include.path, `includeIf.*.path`, `alias.*`, filter, diff, merge and tool drivers, credential, sequence.editor, gpg,
  uploadpack, receivepack, `remote.*.url|pushurl|uploadpack|receivepack`, `url.*.insteadOf`, `submodule.*.update`, protocol.ext.allow), read in any case, in every scope
  and file, after `-C`, in the `git config set` syntax; `--edit`, a renamed section and a key that a variable or xargs brings are refused too. `user.name`,
  `user.email` and the other plain settings stay allowed, and `GIT_CONFIG=FILE` in front of `git config` names the file it writes, so a protected one is refused.
- On a line that also runs git, the member guard also refuses a write under `.git/modules/`, `.git/worktrees/` or to a `config.worktree` (the configuration and
  hooks of a submodule or a worktree), as it did for `.git/config` and `.git/hooks`.
- The member guard reads the program a shell takes from its standard input: `echo "qargi upgrade" | bash`, `bash <<< "qargi upgrade"`, `sh -s <<< ...`,
  `. /dev/stdin <<< ...`, `echo ... | source /dev/stdin`, `echo ... | xargs -0 sh -c`, `printf '%s' ... | bash` and `echo ... > f; sh f` ran the verb unseen since 0.2.0.
  The text the line shows (a here-string, an echo or printf piped in or written to the file the shell runs) is now read as `sh -c` text is, and a program it cannot see
  (`cat file | bash`, `curl ... | sh`, `bash < file`, a process substitution, a file `cp` writes in the same command) is refused: write the script with the file tool
  and run `bash FILE`.
- The member guard finds the lead identity `QARGI_LEAD` among the names a command sets the way it finds `QARGI_NESTED`: `printf -vQARGI_LEAD x` (the name
  glued to `-v`), `mapfile` and `readarray` into it, and `env -uQARGI_LEAD` were not refused.

## [0.2.0] - 2026-11-02

### Added
- `qargi marshal forget NAME`: drops this machine's accepted marshal mark of one feature, so a stale mark (left after the feature was
  deleted or re-created on the remote) stops reporting `rollback detected`. It needs integrity advisory or strict and a mark for NAME,
  prints the mark's revision and commit in a plan whose token covers both, applies with `--plan` and your words (audited as
  `marshal:forget`), touches no other feature and nothing on the remote, and is refused in a member run.
- `qargi project adopt PROJECT`: closes the safe gaps of an attached repository. With a plan token and your words it creates the missing
  long-lived branches locally (at the default branch tip; none is moved) and writes the methodology files that do not exist as one commit
  on `agent/adopt-<methodology>` cut from develop, for you to review. It never overwrites a file, never pushes, leaves the working tree
  alone, refuses a dirty tree, a detached HEAD and a member run, and lists the changelog format, tag format and CI content as left for you.
- Signed marshal records. With the shared marshal, each lead machine can have its own ssh key (`marshal key init`), a per-project
  signers file lists the trusted keys (`marshal signers add|remove|list`, never in the repository or the refs), and
  `marshal enable --integrity off|advisory|strict` sets the mode. Records are signed with `ssh-keygen -Y` (namespace `qargi-marshal`) over
  a canonical payload that names project, feature, kind, revision, parent and lead, so a record cannot be altered or moved to another
  feature. Advisory tags records signed, unsigned or INVALID; strict ignores unsigned and invalid ones and falls back to the last
  accepted record. A local high-water mark detects a rewound ref (`rollback detected`), and junk or replayed pushes neither renew a lease
  nor block a feature. `marshal resign NAME` signs an existing record when moving from advisory to strict. Keys, signers and the mode
  are yours to set; nothing is signed until you choose a mode. Members cannot read the signing key or change the signers.
  Review hardening: a lagging machine builds on the newest signed record rather than overwriting it; advisory builds on an unsigned head
  instead of dropping it; a signed finish records the last features commit so a reused name keeps its rollback mark; records are
  identified by what the signature covers, so a re-committed head is the same record; `resign` shows the head, lead and goal in a plan
  whose token covers that head and refuses a lead other than the accepted one; `disable` needs the plan token and your words while
  integrity is on; the guard follows `pushd`/`popd`, refuses links and moves of the key, and normalises `/./` in scanned text.
  Member definitions now also hook the guard on the Read and Grep tools (to keep the key unread); members created earlier keep the old
  matcher until they are refreshed (`qargi agent refresh NAME`).
- Shared marshal. `qargi marshal enable|disable` switch a project between the local records and a shared backend that keeps each
  feature record as a commit on `refs/qargi/features/NAME` of the remote origin: create-only claims, leased updates, an atomic move
  to `refs/qargi/done/NAME` on finish, a fetch that never brings other refs, and takeover judged on the taker's own monotonic clock.
  It is off by default, needs the plan token and your typed words, is audited, cannot be used from a member run, and `project set`
  refuses `marshal.*` except `marshal.ttl`. Offline verbs use the cache and say `remote not checked`; an offline claim is
  `provisional`. `local verify` ignores `refs/qargi/`; `marshal status|check` take `--no-fetch` (the session hook uses it).
  Hardening from review: an offline claim is dropped, not pushed, when another machine finished the feature meanwhile; remote records with
  wrong field types are ignored instead of crashing readers; `takeover` of a provisional claim is refused; the lease renewer survives an
  unreachable remote (exit status 3, `remote not checked`) and stops only on a lost lease; the fetch leaves `FETCH_HEAD` alone (git 2.29+);
  `marshal` ignores `APPROVED` and `PLAN_ARG` from the environment; and `qargi feature start|finish|verify` are refused to a member.
- Cloud profiles. A project can provision two cloud base agents, `<project>-worker` (write class) and `<project>-reviewer` (read-only),
  and start a session of a role and profile on one: `qargi start|send <project>-worker --role build --profile build`. The model and
  effort are overridden per session with a full model object and the role's prompt is rendered fresh, so the base needs no prompt
  refresh; its tools stay fixed on the agent. `agent for ROLE --surface cloud` resolves the instance and uses a base only when it is
  registered and the provider's cloud override capabilities are verified (they now are for `claude`, from a scratch run on
  2026-11-01); otherwise the four role agents keep serving, and a profile with a different model than the role agent refuses.
  A reviewer base needs the project's `provider accept` for the missing cloud read-only barrier before it is provisioned or started.
  The claude adapter gained a `start-session` request builder, with a conformance check that a body never carries tools, skills or
  MCP servers.
- Providers. Each model provider is a descriptor (`lib/providers/NAME.json`, one schema) with its tier-to-model map and verification
  dates, effort levels, surfaces and a per-surface capability matrix; `qargi provider list|show|check` prints and validates them,
  and `check` says what degrades (an unverified capability counts as unsupported). The `claude` provider has a local adapter
  (`lib/providers/claude/adapter`: resolve, dispatch-local, barrier-check) behind which members are rendered, and the Claude model ids
  and id pattern that were spread through the code now come from its descriptor. A surface with no read-only barrier cannot serve
  the review role unless the project records `models.accept_no_barrier` with `qargi provider accept` (plan and token, audit-logged);
  for `claude` that means a cloud review role needs your acceptance, while the local guard counts as a partial barrier. A provider with
  no effort control has the effort dropped and `agent models` says so, `agent for` refuses a profile on a provider that cannot override
  the model per dispatch, and `local verify` and `review apply` never apply patches from a read-only run. `bash tests/conformance.sh NAME`
  runs a conformance suite (verb shapes, unsupported verbs, secrets out of argv, a barrier corpus, the read-only definition) against an
  adapter, with a deliberately broken adapter proving the suite catches faults. A member cannot run `provider accept`.
- Base members and profiles. Two base members, one per guard class: `worker` (build, write, test) and `reviewer` (review, read-only);
  `qargi agent add worker|reviewer` defaults to the base's own abilities and refuses abilities of the other class. Specializations
  are profiles {base, tier, effort, purpose}, resolved at dispatch: shipped `build`, `write`, `test`, `review`, `auditor` (Haiku),
  `advisor` (Opus) and the opt-in `researcher` (frontier tier), plus your own under `profiles.NAME` in a project's answers (validated;
  a profile whose abilities do not fit its base's class is refused). `qargi agent for ROLE [--profile NAME] [--json]` now prints one
  line, `MEMBER MODEL EFFORT PROFILE`, and the lead passes the model and the effort to the Agent tool, which override the member
  definition. `qargi local prepare --profile NAME` resolves the profile before any clone, records it in `RUN/profile` (a file the guard
  keeps from the member) and prints `PROFILE`, `MEMBER`, `MODEL` and `EFFORT`. The tier-to-model table lives in the provider file
  (`lib/providers/claude.json`, with an alias per tier for local dispatch). `qargi agent models` flags legacy per-ability members,
  a missing base, refused profiles and mixed-class members. The earlier model-table entry is superseded: `roles` and `suggested`
  became `profiles`, and `auditor`, `advisor` and `researcher` are profiles, not members.
- Model selection. One table (`lib/model-defaults.json`) names a tier and an effort for the lead and each role (Sonnet 5.5 for the
  lead, build, write and test, Opus 5.5 for review), and `lib/providers/claude.json` maps the tiers (fast, balanced, deep,
  frontier) to models; a project chooses the provider with `models.provider`. `qargi agent add` takes its model and effort from
  the project's answers, else the table, and writes the effort into the member definition (so does `agent refresh`); the project
  template does the same, and its write role is now Sonnet rather than Opus. `qargi agent models [--project P] [--json]` shows
  the table, the project's overrides, the shipped profiles (`auditor` on Haiku, `advisor` on Opus, `researcher` on the opt-in
  frontier tier, Fable 5.1) and each member, marking an alias as unpinned and a frontier member as opt-in. The flow skill has an
  advisor sign-off before `feature finish` and says search is a read-only exploration on a small model, not a role.
- `qargi marshal status --all` (and `--brief`, `--json`, and the session-start hook that uses them) lists only the open features;
  `--history` adds the finished and abandoned records after them. `qargi marshal check NAME` for a name that has no branch and no
  record now exits 1 with `no feature NAME`, and so do the flow verbs and `local prepare --base feature/NAME` for such a name.
  The error for a branch that is checked out elsewhere says how to free it (`git -C DIR checkout --detach`).
- Memory tiers (writing, second slice). The session-start hook now lists the notes of the tiers, highest first, as data after the
  marshal block (at most 4000 characters per note and 16000 in all; a tier that is missing or unreadable is skipped and named).
  `qargi memory init TIER` creates a tier from the standard layout and `qargi memory move PATH --from TIER --to TIER` moves a
  note, or a folder of notes, between tiers; both print a plan and a token and apply only with your approval, and nothing is
  synced or deleted without it. A repo tier with notes that are not committed warns with the count. `local prepare` prints a
  TASK-BLOCK MEMORY packet for the member, and the guard refuses a member every verb and script that writes a tier. The memory,
  task and canon documents describe the tiers.
- Baseline packs. qargi ships three packs under `packs/`: `shellcheck-gate` (lint every shell file you touch and quote the verdict),
  `keep-a-changelog` (one Unreleased entry per user-visible change, in the same commit) and `gitflow-member` (a member's part of
  a git-flow project). `qargi packs seed` stores them in your library: it prints one line per pack (add, update, current or
  kept) and a plan token, and applies with your approval; an untouched shipped copy is updated when qargi ships newer text, a
  copy you edited and sealed or a pack of your own with the same name is kept and never overwritten, and seeding never links a
  pack. `install.sh` (and so `qargi upgrade`) adds the packs your library lacks with `packs seed --install`, which needs no token
  and never updates. Link a pack to a project with `qargi skill link`; proposing links when a project is created or attached is
  not built yet. A member cannot run `packs seed`.
- Memory tiers (read-only, first slice). A project's memory is five ranked tiers, highest first: repo, cloud, project, shared,
  system. A tier is a memory store of the standard layout in a directory (defaults under the qargi root; `memory.tiers` in the
  project answers moves any of them) or, for cloud, the project's memory store. `qargi memory tiers [--json]` lists them with
  their state and note counts; `qargi memory check` runs the canon check on each tier that exists and fails when a note path
  is present in two tiers (README, INDEX and the like repeat per tier by design). The reference store is not a tier. Nothing is
  written to a tier; creating and moving notes between tiers, and the session hook composing them, come later.
- Agents write verified facts only under their own role folder of the memory store; `shared/` is curated and reached by
  promotion (`qargi canon promote --approved`) or by the person, and an agent proposes a shared note in its report. The cloud
  preamble, the store README, the lead contract, the build role and skill and the canon say so. `canon audit` still reports
  only cross-role writes, so an agent writing under `shared/` is not yet detected. The cloud prompts change: refresh them.
- A lead-only ref journal (`ref-journal.jsonl` in the state directory) records every local branch that qargi's own verbs create,
  move or delete (`feature start|merge|sync|finish`, `release`, `review apply|prune`). `local verify` now accepts a branch
  change since the run was prepared when the journal leads from the snapshot to the branch's current value, so several runs
  prepared in parallel all verify after the lead merged the first one. Remote refs, tags and any unjournaled move are still
  refused, and the refusal says so. The guard keeps members from writing the journal; it is trusted only as far as the state
  directory is (signed records come later). `local prepare` records `RUN/started`.
- `qargi marshal` keeps one record per open feature: its lead (a Claude Code session, identified by the session id the SessionStart
  hook exports as `QARGI_LEAD`, or `--as`), a lease, status, goal, plan and note. `claim`, `status [--all] [--brief|--json]`,
  `set`, `check`, `renew`, `release --note`, `take`, `takeover --approved` and `finish`. Tasks, agent branches, worktrees and
  files that two features both change are derived from git and the local runs, not declared. Query it before starting work:
  `qargi marshal check NAME` refuses when another live lead holds the feature and warns about a stale lead, an anonymous
  identity and overlap. The lease is `marshal.ttl` minutes per project (default 15; `qargi project set PROJECT marshal.ttl N`),
  renewed by the lead's actions and for the whole run of `feature verify` and `feature finish`, so a suite of any length is
  safe. A feature whose lead stopped is taken over only after the lease ran out and with your words, which are audited.
  Records are local to the host unless the project switches to the shared backend (`marshal enable`).
- `feature start|merge|sync|verify|finish` and `local prepare --base feature/X` ask the marshal first and refuse when another
  live lead holds the feature; `feature start` records the starter as lead, `finish` marks the record finished, `feature
  status` ends with the marshal's view and `feature list` shows each lead. A marshal that is absent or fails never blocks.
  `local-runs.jsonl` lines gain `lead`.
- The session-start hook lists the open features as data for the lead session. The guard keeps members from the mutating
  marshal verbs, from the state `features/` directory and from setting `QARGI_LEAD`.
- `qargi release start` has a preflight. Before it creates the branch it checks what a release must update and refuses,
  changing nothing, with a message naming the file and the fix: a man page (`man/*.1`) needs a `.TH` line with a date and a
  version field, and the first commit now sets them to the release's date and `VERSION`; a `CHANGELOG.md` needs a
  `## [Unreleased]` section with content (`--allow-empty-notes` waives that). Projects without a man page or changelog are
  not checked for that part.
- Roles. A role is a directory with `role.json` (its class, `write` or `read-only`, and a description) and `ROLE.md` (its
  instructions). `build`, `write`, `review` and `test` ship in `roles/`; add your own under `~/.qargi/config/roles/NAME/`
  (one lower-case token, never `lead`, never a built-in's name). `qargi role list|show|prompt|check`. A local task names its
  role (`qargi local prepare --role R`, which records the class in `RUN/class`; `--ability` still works), the task block
  carries the role's text, `qargi agent add --abilities` and `qargi agent for` take any role (a role of yours without a member
  falls back to a member of the built-in role of the same class), and a cloud agent of a role gets its text in its system
  prompt. The class, not the name `review`, decides what the guard allows and which cloud tools are off.

- `qargi local clean RUN` removes a collected, verified local run (clone, bare copy, output) and its private temporary
  directory. `qargi local prepare` makes that directory (`TMP`, on `/dev/shm` when it exists, `QARGI_RUN_TMP` moves it) for
  the agent's test sandboxes, so parallel runs never share files and a run leaves nothing behind. The agent contract asks for
  targeted checks per task (the full suite belongs to the coordinator after a collection), and the task skill describes
  dispatching non-overlapping tasks in parallel.

- Methodologies. A methodology is the way a project is developed and released, as data: branches (long-lived, release
  `feature/<version>`, task `agent/<slug>`), versioning and changelog, test tiers (targeted per task, the whole suite once per
  collection), CI, release steps, deployment options with instructions, and the generic files a new project starts with
  (README, VERSION, CHANGELOG, CONTRIBUTING, CLAUDE.md, .gitignore, a GitHub Actions test workflow). `gitflow` ships in
  `methodologies/`; add your own under `~/.qargi/config/methodologies/NAME/`. `qargi methodology list|show|check|files|deployment`
  only read; the scaffold carries no reference to qargi.

- `qargi project attach [DIR]` attaches qargi to an existing repository without changing it. It reads the remote, branches, tags,
  version and changelog files, test command and CI, prints the answers it would store, the gaps against the methodology and
  what it could not determine, and a plan token; with `--plan` and `--approved` it stores the answers outside the repository.
  The safe gaps are closed by `qargi project adopt`, the rest by hand.

- `qargi project new NAME` starts a project from a methodology: it prints a plan (directory, branches, files, deployment
  options with instructions) and a token; with `--plan` and `--approved` it creates the directory, runs `git init`, writes the
  generic files in a first commit and creates the long-lived branches, leaving you on `develop`. With `--url` the qargi answers are
  stored too. Nothing is pushed and no remote is created. `--deployment ID` records a deployment option and prints how to do it.
  The generated `.gitignore` excludes `.claude/worktrees/` and `.claude/settings.local.json`.

- Git-flow, as its author described it. `qargi feature start|list|sync|merge|status|verify|finish`: a feature is a broad, related branch
  cut from `develop`; verified task branches are merged into it with `--no-ff`; the whole suite runs once when it is complete, and
  only then is it merged into `develop` (one merge per feature). Several features can be open at once; `feature list` shows their
  purposes and the files two of them both change. `qargi release start|status|verify|push|finish VERSION [--hotfix]`:
  `release/<version>` from `develop` (a hotfix from `master`), the version bump as its first commit, a pull request into `master`
  so CI runs on the commit that will be released, then merge into `master` with `--no-ff`, an annotated tag, merge into
  `develop` (a hotfix: into the open release branch), delete, push. Merges are made in temporary worktrees and a branch moves only
  after every merge succeeded; a conflict changes nothing, keeps the merge in progress in a worktree it names (exit 3), and
  `--resolved` applies the merge you resolved. Merging and pushing need a plan token and an approval; a release starts only from
  a `develop` whose head passed the whole suite. A finished feature's whole-suite run carries over to `develop`'s new head, and
  a feature must contain `develop` to finish, so a release needs no extra run. A release or hotfix finishes only on the commit that is
  on origin with passing checks, and pushes master, develop and the tag together or not at all.

- The `feature finish` and `release finish` plans list the commits and files being merged, so the approval is informed.
- The `qargi-flow` skill: the lead's git-flow process with the qargi commands (features and tasks, the one whole-suite run per feature,
  releases, hotfixes, resolving conflicts). A session that leads is pointed at it when it starts.

- `qargi review apply RUN_DIR` puts a collected run on a task branch of the project's repository: it needs `review check` and
  `local verify` to pass, creates `agent/<slug>` (or `--branch`) at the commit the base had when the run was prepared and applies
  the patches with `git am` in a temporary worktree, so your checkout is never touched. A patch that does not apply removes the
  branch again; a run is applied once. `qargi review prune [--yes]` lists, or deletes, the `agent/*` branches already merged into
  `develop` or a `feature/*` branch.

- `qargi packs apply --target claude-code PROJECT` renders the skills and tools a project has enabled into a managed state
  directory, `$QARGI_STATE/claude/PROJECT`, replacing the previous render atomically, and prints the exact
  `claude --add-dir ...` line that loads it. It needs no `--asked`; without `--approved` it prints a plan token. Skills render
  under `.claude/skills`, tool packs as `mcp.json` and `settings.json`, with a manifest. Claude Code cannot enforce role scoping,
  so the render is the union of the project's roles and role scoping is advisory there. Nothing is written into a repository or
  into `~/.claude`. `qargi packs check --target claude-code PROJECT` (read only) exits 1 on drift: a changed or unreviewed pack,
  a tampered, extra or missing rendered file, an enablement change, a rendered skill shadowed by `~/.claude/skills` or the
  checkout's `.claude/skills`, or a missing manifest. `--target managed-agents` is the existing cloud update of an instance.
- `qargi packs apply --target claude-code` refuses at plan time, naming the pack and writing nothing: a `SKILL.md` whose name
  differs from the pack name or whose front matter is not closed or has two `name` keys, a skill and a tool with the same name,
  and a tool allowlist name outside letters, digits, `_`, `.` and `-`. Each plan stages into its own hidden directory under a
  lock, so concurrent applies serialize and the second refuses if the render changed meanwhile.
- `qargi packs check --target claude-code` also reports a rendered file that differs from the library copy, a changed file mode,
  a group- or world-writable render, a malformed manifest, and a manifest naming another project or with role scoping other
  than advisory.
- `qargi local prepare` prints a WARNING block to stderr when the project's Claude Code render has drifted (the project is found
  by matching the repository against the stored answers), with the findings and the fix, `qargi packs apply --target claude-code
  PROJECT`. The run goes on; stdout and the TASK-BLOCK PATHS block are unchanged.
- The guard protects that directory: members can no longer write under the state's `claude/` directory, and the operands of
  `packs render` are judged as write destinations.
- A GitHub Actions workflow runs the whole test suite on pull requests and on pushes to `develop`.
- `qargi packs load [PACK] --role R [--project P]`: read-only. Without a pack it lists what the role has enabled, with each
  description; with one it prints its approved text and the library path of its other files. It reads the links when called,
  so linking, unlinking, enabling and disabling take effect at once, and it refuses a pack that fails its review or changed
  since it was approved. Members may run it.
- `qargi upgrade [--branch B | --tag T]`: plan, then apply with `--plan TOKEN --approved "..."`: moves the installed tool (the root-owned checkout
  `install.sh` recorded) to a newer branch (fast-forward only on its current branch) or tag of its origin, re-runs
  `install.sh --user` and lists the members to refresh. The writing git commands run through `sudo`; members cannot use the verb.
- `qargi cloud list|show|set|unset|check|login`: bind a project to an `ant` profile and the workspace it must reach
  (the project's optional `cloud` answer). Every command about that project then runs `ant` under that profile,
  and a cloud call is refused if the profile no longer reaches the workspace; a conflicting `ANTHROPIC_PROFILE` is
  refused. Projects without a binding are unchanged. qargi never reads or writes a token: `login` runs
  `ant auth login` on your own terminal, and members cannot use `set`, `unset` or `login`; the guard also protects
  `~/.config/anthropic`.
- `qargi mark SID applied|rejected --why CODE` records a reason (codes in `lib/reasons.json`); `qargi report` counts them.
  `mark` now refuses a session the tracker does not know.
- `qargi noticed list|resolve`: collecting a session records the `noticed_not_acted_on` notes of its manifest
  (short, secret-looking strings redacted, once each) in the append-only `events.jsonl` beside the audit log;
  each stays open until given a disposition (followup, dismissed with `--why`, accepted, superseded);
  `qargi report` shows how many are open and how old the oldest is, never the text.
- `qargi agent refresh NAME`: re-render a member from the member definition qargi ships now, keeping its
  name, abilities and model, so members created before a change (such as the hardened hook) can catch up
  without being removed and re-added.
- `qargi memory split|merge|copy FROM TO`: move memory between two stores, each a directory of
  notes, a `.jsonl` dump or a `memstore_` id. Nothing is deleted: what a split archives goes to
  `/_archive/<date>/` and a collision to `/_conflicts/<date>/`, with the origin of every note
  written added to its `Sources:` line, so each change can be undone (merging a split's target
  restores the archived originals byte for byte). Without `--approved` they print the plan and its
  token and change nothing; a store whose notes changed since the plan is refused and left as it
  was. On a directory store qargi's own writers are serialised by an exclusive lock, and each write
  re-reads the note immediately before replacing it or releasing its name, so a change made by an
  editor in that instant is refused and kept, not overwritten; an editor that writes in the last
  instant after that read is still not prevented (the lock is advisory), which is why the digest
  check exists. `lib/membackend.py` is the backend interface (directory, fixture dump and Managed Agents
  store through `ant`) with one ops executor, `lib/memplan.py` the pure planning;
  `lib/canon.py` gains `make_plan`, the migration plan `canon plan` prints, for reuse.
  A `.jsonl` dump is read-only (a source, never a target of split, merge or copy). A note named
  with a leading dot or trailing white space is not a note, and a note the target cannot hold
  (too many path segments or too large for a Managed Agents store) makes the plan refuse and name
  it. The plan token is always required: `QARGI_NESTED` does not stand in for it, and the audit log
  records the token, the selector and every step, with a second line once the apply succeeded.
  `merge` and `copy` without a selector leave the source's `/_archive/` behind. A
  provenance segment counts only when its digest matches the note it was added to. `/_archive/`
  is a tolerated folder of canon 2 (`canon check` warns about a note there without our segment).
  Known limit: `canon apply` is not run through the new executor; `memplan.migrate` exists for it.
- `qargi report [--since DATE] [--instance NAME] [--stale-after D] [--local-stale-after D] [--runs-root DIR] [--json]`: a read-only report from the session tracker (spend and spend per applied session, sessions pending review oldest first, sessions that look stale, idle sessions by why they stopped, time from creation to close) and from local run directories (finished DONE or BLOCKED, no manifest and still changing, no manifest and quiet: possibly stalled). It states what it cannot tell and never prints a session's note or request.
- `qargi local prepare` appends one JSON line per run (run directory, slug, ability, base, start time) to `local-runs.jsonl` in the state directory, so `report` can list local runs.
- `instances refresh-prompt --if-stale`: does nothing, with no cloud call, when the prompt rendered now has the hash recorded at the last provision or refresh. The registry entry of a cloud instance gets a `prompt` object (`sha`, `skill`, `at`); `instances list` marks a changed prompt `prompt STALE`, and `instances show` says which part changed. An entry without a hash (older release, or `instances init`) is unknown, not stale.
- `qargi supervise tick|status|nudge|delivered|hooks`: the first version of the stalled-agent supervisor. Hooks only record; one idempotent tick (the only writer of `runs.json`, under a lock) folds the per-run event files, the local-run registry and the session tracker, classifies every unfinished run in a fixed order (waiting on an approval, API stop failure, interim with a cap, looping on three identical tool digests, suspected dead on stale activity; cloud: `requires_action`, `budget_reached`, stale while running, idle awaiting review) and acts only by printing `QARGI SUPERVISE <class> <run> <next-action>` lines, appending to `supervisor.log` and the audit log (origin `supervisor`), and preparing a nudge in `nudges.jsonl`. A nudge is a fixed template, at most 2 per run with at least 10 minutes between them, never while the run waits or has little budget left, and never an approval; a local one is delivered by the coordinating session and counts once `qargi supervise delivered KEY` records it, a cloud one is sent only by `qargi supervise nudge SID --asked ...`. Nothing is sent automatically (a standing permission is a documented extension point, off). Thresholds are data in `lib/supervise-defaults.json`: conservative floors until `qargi report` shows real run lengths. `status` warns when the last tick is older than twice the interval.
- `qargi hook subagent-start|subagent-stop|tool-use|tool-failure|notification|stop-failure|pre-compact`: handlers for the Claude Code hooks that append one small line (ids, times, the tool name and a hash of its input; never a command, message or error text) to `run-events/<agent_id>.jsonl` in the state directory. They exit 0 at once, even on malformed input. `qargi supervise hooks` prints the settings snippet; it never writes `settings.json`.
- `qargi report` has a short Supervisor section (suspected stalls by class, what waits on you, prepared nudges awaiting action) once a tick has run.
- The audit log may carry an `origin` field (`supervisor`); the tracker row records `last_processed_at` (the session's `updated_at`) on refresh.
- Sessions record `interrupt_sent_at` when `qargi stop` sends the interrupt (an interrupted turn also ends with `end_turn`) and `stop_event_ids` for `requires_action`.
- `QARGI_HOME` replaces the root `~/.qargi` that holds `config/` and `state/`; `QARGI_CONF` and `QARGI_STATE` still win over it.
- `qargi migrate home`: copies the data from the earlier XDG directories to `~/.qargi/config` and `~/.qargi/state`. Without `--approved` it prints the plan (every directory, file and link with mode and digest, the `*.lock` files it skips, the files in which it rewrites old absolute paths: a project's credential file, `local-runs.jsonl`, anything else naming the old directories; the records `audit.log`, `supervisor.log` and `run-events/` are copied byte for byte and the plan lists them on a "Copied verbatim (records)" line) and a plan token covering it, and changes nothing. With `--plan TOKEN --approved "<words>"` it copies (the old directories stay as a backup), keeps modes (credentials 0700, files 0600), checks every file by digest, removes what it made if a step fails, refuses when the new root exists and is not empty, and logs an `audit.log` line. Run again it says there is nothing to do.
- Dev runs: `install.sh --user` records the tool it installed in `<config>/install.json` (`--uninstall` removes it; `--project` writes nothing). A checkout run from any other place, with none of `QARGI_HOME`, `QARGI_CONF` and `QARGI_STATE` set, keeps its data in `<checkout>/.qargi` (git-ignored), prints one `qargi: dev run from ...` line on stderr per command (none for `help`, `version`, completion, the guard and the run-event hooks), and never touches live data; with no `install.json` a checkout behaves as the installed one. `qargi migrate home` refuses in a dev run unless a location is named. See `qargi help dev`.
- `lib/paths.py` and the top of `lib/lib.sh` are the one place each language resolves these locations; the nine copies of the XDG logic are gone.

### Changed
- The plan token of `packs apply --target claude-code` also covers file modes, the manifest records them, and the swap installs
  only the tree the token approved.
- `qargi local verify` and `qargi local clean` accept the lead's own work. After a passing verify the run records `RUN/verified`,
  and later checks compare with it: fast-forwards of `develop`, `master` and `agent|feature|release|hotfix/*` branches and new
  branches there are accepted, while remote refs, tags, deletions and rewrites still fail. A change now exits 2 (it was 1). Run
  `qargi local verify` on every run before merging any of them.
- `qargi local prepare` ends its output with a blank line and a `TASK-BLOCK PATHS` block (`RUN_DIR`, `CLONE`, `OUT`, `TMP`, `GIT`,
  `BASE_SHA`); a caller that evals the output must stop at the blank line.
- `qargi project attach` reads the tree of the integration branch (`develop`, else the default branch, else `HEAD`) and says which,
  not the working tree. It prints origin as read and the normalised url. When answers are already stored it shows stored against
  detected and the fields the stored file lacks, stays read-only and gives no plan token; with `--force` the plan keeps what it
  cannot detect (the roles' models and effort, cloud, memory, budget).
- `qargi feature start` refuses a name origin already has, asked live with `git ls-remote`.
- `qargi feature status|finish` and `qargi release status|push|finish` ask the live origin with `git ls-remote` where the branches
  are (`QARGI_REMOTE_TIMEOUT` seconds, default 10) instead of the last fetch, and print `remote not checked` when origin cannot
  be reached.
- `tests/run.sh` runs without the caller's cloud binding or any `QARGI_*` or `ANTHROPIC_*` variable and with a fresh `HOME`, and
  every test is hermetic (`tests/hermetic.sh`, `tests/hermetic.py`): fresh qargi config and state, and failing `ant` and `claude`
  stubs first on `PATH`.
- The role and contract text lists the rules to follow before DONE. Every cloud agent's prompt changes: run
  `qargi instances refresh-prompt NAME --if-stale` for each.
- `qargi feature verify` and `qargi release verify` run the project's test command without the project's cloud binding
  (`ANTHROPIC_PROFILE`, `QARGI_CLOUD_WORKSPACE`, `QARGI_CLOUD_PROJECT`), and `tests/run.sh` unsets them, so a project with
  a cloud binding can get a passing whole-suite record.
- The cloud agent contract, the member definition and the task skill speak of a role and its text instead of loading an
  ability skill. Every cloud agent's prompt changes: run `qargi instances refresh-prompt NAME --if-stale` for each. The
- Breaking before 1.0: the default locations are `~/.qargi/config` and `~/.qargi/state`, not `$XDG_CONFIG_HOME/qargi` and `$XDG_STATE_HOME/qargi`; the XDG variables no longer move qargi's data. While only the earlier directories exist, every command except `help`, `version`, completion, `__guard`, the run-event hooks and `migrate home` stops and asks you to run `qargi migrate home`; qargi never creates an empty `~/.qargi` next to old data, and `install.sh --user` does not record the install until then.
- The member guard protects the pack library, `<config>/credentials/` and `<config>/install.json` at the new location (the resolved configuration directory, `$QARGI_HOME/config`, the live one and `~/.qargi/config`) and keeps the earlier XDG paths protected as a backup. The rest of the configuration directory stays writable (the guard decides by path, not by qargi verb), and reading a protected path is still allowed.
- The member guard refuses a member every skill-modifying verb: `qargi skill|tool new|import|seal|remove|unlink|link|enable|disable`, `qargi discover install`, `qargi packs apply` and `qargi import` (found after wrappers, in `sh -c`, `eval` and `$(...)`, and when `packs.sh` or `discover.py` is run directly), setting `QARGI_NESTED`, and writes under the pack library (`$QARGI_CONF/packs`, honouring the XDG defaults), `~/.claude/skills`, `~/.claude/agents`, `~/.claude/plugins` and any `.claude/skills` directory outside the run's clone (inside the clone it is the work product, reviewed as a patch; paths are resolved first, so a link in the clone to a protected location is still refused). Edit, Write and NotebookEdit are decided by the resolved path; Bash by a documented conservative heuristic (redirections, tee, cp, mv, rm, ln, install, rsync, `sed -i`, `dd of=`, find, tar and so on). The repository's own `skills/` directory in a member's clone and its run directories stay writable. Read-only verbs (`list`, `show`, `check`, `effective`, `search`, `render`) are unchanged. A barrier, not proof; code that writes a file itself (`python -c`) is not covered.
- The guard fails closed: an unexpected exception inside it is exit 2 with the reason on stderr, not a silent pass. `agents/member.md` sets `onFailure: "block"` and a `timeout` on the hook, so a hook that cannot start, crashes, times out or exits other than 0 or 2 blocks the call (needs Claude Code 2.1.295 or later; an older one runs the call, per the hooks documentation). Frontmatter hooks of a project-level agent file run only once the workspace is trusted.
- `QARGI_NESTED` no longer stands in for the plan token of `skill|tool new|import|seal|remove|link|unlink|enable|disable` and `packs apply`; `import`, `seal` and `packs apply` always need `--plan`, and an empty expected token is an error. Nothing nested them (`discover install` already cleared it, provisioning only renders). `--approved` remains recorded text: proof that a person approved is still the owner's chat approval.

### Removed
- The four ability skills `qargi-build`, `qargi-write`, `qargi-review` and `qargi-test` are gone: nothing loaded them. A member
  follows the role text that comes with the task block (`roles/<role>/ROLE.md`), and `qargi help roles`, `qargi help agent`
  and the manual page no longer name them. `install.sh --user` removes the leftover links to them.

### Fixed
- `qargi canon audit` now attributes a session of a cloud base (`<project>-worker`, `<project>-reviewer`) to the role recorded in the local
  session tracker, so its cross-role writes are reported; a session it cannot attribute is counted once in a NOTE line, not guessed.
- `qargi cloud show|check|login|unset` now refuse `--profile` and `--workspace-id` (only `set` takes them) instead of ignoring them;
  `qargi agent for --surface` completes `local` and `cloud`; the test that keeps the help in step with the scripts now also covers
  `lib/provider.sh`.
- Read-only cloud roles now have the `write` built-in tool off as well as `edit` (a reviewer could still create files through
  `write`); an unknown class now counts as read-only instead of write, and `worker` and `reviewer` are reserved role names.
- `qargi provision apply` no longer fails on the second and later roles of a project: an empty package list became `[""]`, which the shared environment update rejected, before the stores were attached and the instance registered.
- `qargi memory split|merge|copy`: a note whose own `Sources:` line is exactly `origin not recorded (qargi memory)` (written by an earlier copy or by hand) is no longer mistaken for the line qargi inserts into a note that has none. Undoing a copy or an archive (merging a split's target) now returns both kinds of note byte for byte; which one it was is read from the digest already in the origin segment, so the segment format is unchanged and notes written by earlier versions restore as before.
- The tracker's `stop_reason` was empty for every session: the session object has no such field. `status`, `watch`, `send`, `close` and `track` now read it from the last `session.status_idle` event of an idle session. `watch` can now print `budget_reached`.

### Security
- A review member could lift its own read-only limit: the guard took the ability from `RUN/ability`, a file the member could
  write. The guard now refuses any write to a run's `ability` and `refs.before`, and a member that only reviews names its
  class in the hook command of its definition (under the protected agents directory), which holds on every task whatever the
  run file says. Run `qargi agent refresh NAME` for existing members to get the new hook; a guard given an unknown class
  refuses every call.
- A member could rewrite the installed tool through the links in `~/.claude/skills` (they resolve into the installed copy,
  which was not a protected location) and a project's `.claude/agents` definitions (which carry the hook that guards a
  member). The guard now protects the installed tool root recorded in `install.json` and `.claude/agents` outside the run's
  clone, as it already did `.claude/skills`. Reading stays allowed.

## [0.1.0] - 2026-10-28

### Added
- Six skills behind one `qargi` command: `/qargi-task` (dispatch and session
  lifecycle), `/qargi-project` (the one-time questionnaire), `/qargi-instances`,
  `/qargi-provision`, `/qargi-memory` and `/qargi-verify`. `install.sh` installs them at
  user level (skills, command, manual page, completion) or per project (skills,
  hidden from git through `.git/info/exclude`), as symlinks or copies.
- Named instances, local or cloud (a
  Managed Agents deployment), registered outside every repository with model and
  effort chosen at `init`. Cloud verbs need `--asked`, the user's request naming
  the cloud instance; sessions are tracked, watched by a bounded poller,
  collected into a fresh directory and archived, never deleted. A session budget
  can only be set at creation, so the spend ceiling lives on the deployment
  (`instances budget` changes it).
- The agent contract (one task, own clone, patches back, never push, no backlog)
  and per-repository profiles for gates and rules, kept under the user's config
  directory and inlined into the task block, so nothing qargi related is
  added to a project's committed files.
- Project initialisation (`project template|init|show|list|validate|set`): the
  preliminary questions asked once per project (repository, long-lived branches,
  roles, per-role base branch, push policy, model, effort, packages, Anthropic
  skills, budget, stores), validated and stored. Never push is the default for
  every role; a role that pushes is an explicit answer with a branch pattern that
  cannot match a long-lived branch and, for the agent itself, a credential.
- Provisioning with `ant apply` (`provision plan|apply|add-reference`): plan
  first, create only with the user's go-ahead; model, effort, packages, skills,
  budget and stores come from the stored answers.
- A naming convention: `<project>-<role>-<component>` for agent, environment and
  deployment (roles `build`, `review`, `write`, `test`), project-level
  `<project>-memory` and `<project>-reference` stores that are attached rather than
  duplicated, and sessions named `<instance>-<task-slug>`. `instances normalize`
  renames to match and `instances show` reports deviations.
- The canon (`canon/CANON.md`, `canon/layout.json`, version 1, still a draft): the
  standard layout of the two memory stores. Both hold a `/CANON.md` marker, a README,
  `shared/` for every role and `roles/<role>/` with an `INDEX.md` per role; folders
  are named for their scope, with no numbered prefixes. Agents load the README,
  `shared/INDEX.md` and their own role's index, never another role's folder.
- `qargi canon check|plan|apply|import|seed-role|promote|audit`: the reconciler
  brings a store to the current version without losing content (renames keep
  identity and history, conflicts go to `/_conflicts/`, the marker is written last,
  re-runs resume; the legacy layouts and earlier drafts are recognised), imports a
  foreign store such as the old documentation store into a role folder with
  relevant names, writes a role's skeleton, moves a file to `shared/`, and reports
  cross-role writes from the memory version history. `tests/canon_sim.py` proves a
  migration is idempotent and conformant.
- Provisioning creates the project's stores in the canon layout and seeds each
  enabled role's skeleton (`provision/role-seeds/<role>/`); the cloud agent prompt
  names the agent's role and the folders it may load.
- A generic `write` role skeleton (`provision/role-seeds/write/`): the write ability (accuracy first, profile-defined checks and formats, conflict resolution, history logging), reference files for rules, workflow with the definition of done, per-release sync and review, writing conventions, styling, facts and preferences, and memory files for history and open items, distilled from a working documentation methodology. A role's ability skill is appended to its cloud agent's prompt; `tests/role_seed_sim.py ROLE` proves a role seed conforms to the canon.
- Cross-role content of a project's reference store lives in `shared/` (rules every role follows, the approved example values, architecture, source map, checked facts); a role's folder holds only that role's own.
- Approvals bind to the plan: plans print a token, the matching apply needs `--plan TOKEN` and refuses if the plan changed; every gated verb is appended to an audit log. Sessions without a spend budget are refused.
- Local dispatch has a technical barrier (`qargi local prepare|verify`): a clone of a remote-less bare copy, a credential-less git wrapper, and a comparison of every ref of the real repository and its remote before and after.
- The push policies `coordinator` and `agent` are designed but not built; the project validator refuses them instead of accepting an answer nothing honours. The unused `vault_ids`, `profile` and credential answers were removed.
- Gates have one source of truth, the repository profile; the reference store explains them.
- Canon version 2: both stores use one note format (`Kind`, `Applies to`, `Sources`, and `Check`/`Verified` for the runnable kinds), one index form (`| Path | Purpose | Load |`), a kind vocabulary per store, freshness, size and hygiene rules; `canon check` verifies all of it and `memory lint` is the same check. A version 1 store migrates by adding what a note lacks and never editing a body; imports get the header too; both stores carry a `_template.md`. Reconciler fixes: interrupted migrations resume, maintenance creates missing role indexes, an unrecognised layout is an error. `tests/run.sh` runs the whole suite.
- Private repositories: an optional `repo.credential_file` in the project answers (a token file only you can read, outside every repository). `qargi credential check` proves the token reads and warns if it can also push; a cloud session is created with the repository mounted when a credential is set; `local prepare --repo-url --credential-file` clones a private repository. The token goes to `ant` on stdin or to git through an askpass helper and is in no argument, tracker, audit log or repository; `tests/test_cred.sh` proves it with a fake `ant`.
- The secret rule flags an assignment of a long mixed value, not prose about tokens; the `/home/user/` placeholder is allowed.
- Skills and tools (`/qargi-packs`, `qargi skill|tool ...`): one library with globally unique names, attached by links at four scopes (user, user-role, project, project-role) and opted out per role with `packs_off`. A skill is a directory with `SKILL.md`; a tool is an MCP server with an explicit allowlist and a permission policy per tool (write-like tools cannot run unattended unless marked on purpose). Import takes a local path or a pinned git URL and shows a review (files, scripts, URLs, secret findings) that must be approved with the plan token; any later change is drift and fails `check` and provisioning until `seal`ed. Provisioning attaches a role's packs, and `packs apply INSTANCE` updates an existing cloud agent behind a plan token. `tests/test_packs.sh` covers it offline.
- Commit rules: agents commit change-specific units (a change with its tests, docs and changelog entry), never squash or rewrite, and advise in the manifest and report how the work should be committed (`commit_advice`); the coordinator reviews every patch and applies the commits separately, never squashed, checking that each one builds.
- `qargi instances refresh-prompt NAME`: rebuilds a cloud agent's system prompt from the current preamble, contract and role addendum (shared with provisioning), prints what changes, and applies behind a plan token, so an agent can always be brought back in line after the contract changes.
- Patches travel with their context: agents commit as they go, put the reasoning in each commit message, and return one numbered patch per commit plus `series.md` and `patch_groups` in the manifest (related commits grouped under the change they implement), never one combined patch. `qargi review check RUN_DIR` refuses a monolithic patch, a commit without a message body and a manifest that does not match the patches, and notes commits made in one batch. `tests/test_review.sh` covers it.
- `qargi review check` accepts a review run that returns a report instead of patches: a non-empty `report.md` with a Findings section passes, an empty run or a report without findings is refused. `tests/test_review.sh` covers it.
- Baseline seeds for every role (`provision/role-seeds/<role>/`). `build` gets real generic guidance (rules, workflow and definition of done by kind of change, gates, conventions for code, tests, user-visible changes and commits, a self-review checklist); `review` and `test` are new, each with its ability (a review returns a report and never edits the project; a test must be seen failing for the right reason, run three times, and never skipped or weakened), reference files, and a memory note (recurring findings, known flaky tests). Every file keeps a marked "Project specifics" slot for what only the repository can say. `tests/role_seed_sim.py` runs for all four roles in the suite.
- The manifest has an `artifacts[]` key for deliverables that are not patches. The review ability states that a review has no patches (`commits: []`, the report as an artifact, a scratch CLONE) and the test ability says where its evidence lives (`fail-first`, `pass` and `stability-N` entries in `gates[]`, ten runs as the floor). The cloud preamble no longer repeats the stores' own load rules.
- Seeds are leaner and have one home per fact: gates, source map and test conventions are `shared/` seeds (`canon seed-role --role shared`, run first by provisioning); a role's rules are not repeated from the contract; placeholder-only files are no longer shipped (the skill lists what to author); the per-file source line and the store-maintenance boilerplate are gone from indexes; the review checklist gains design and readability, the test conventions the test pyramid and assertion messages, the dev conventions secure-coding habits. A project statement replaces the baseline bullet it covers.
- Canon token rules: a note over 10000 characters warns (an agent loads a note whole), an index over 2500 characters warns, what a role loads before it knows its task (README, indexes, notes marked `always`) is at most 8000 characters per store, and an index Load cell must be `always` or a task, never "when unsure", "if needed" or "working on <project>". `canon check` reports each.
- The README seeds are about 40% smaller (the layout diagram the indexes already cover is gone), so a role's up-front load fits the budget with room for its rules.
- The project is named qargi: the command is `qargi`, the skills are `qargi-task`, `qargi-project`, `qargi-instances`, `qargi-provision`, `qargi-memory`, `qargi-packs`, `qargi-verify` and `qargi-team`, the ability skills `qargi-build`, `qargi-write`, `qargi-review` and `qargi-test`, the environment variables are `QARGI_*`, and the configuration, state and data directories are named `qargi`.
- Resource names follow `<project>-<component>[-<role>]`: the agent `<project>-<role>`, `<project>-deployment-<role>`, the project-wide `<project>-environment` (shared by the roles, holding the packages of all enabled roles), and the existing `<project>-memory` and `<project>-reference`. Provisioning, `instances normalize` and `show` use the new names; an instance is still `<project>-<role>` and a session `<instance>-<task-slug>`.
- The reconciler keeps the README's list of roles in step with the project's roles when one is added.
- Teams (opt-in, `/qargi-team`): a `lead` and named `teams` in the project answers; a lead role of its own (`PROJECT-lead`, a platform coordinator whose members are the role agents, pinned to their versions, with the team definitions in its prompt); `qargi team brief|check|contract`; a team's outputs are role-prefixed and `collect` splits them per member; the build member owns what ships with the code (manual page, help, completion, `docs/`), the write member owns the operational docs on its branch. The lead can be this Claude Code session, a cloud lead, or a session started in the console. `qargi hook session-start` loads the lead's READMEs and indexes at the start of a Claude Code session inside a registered project; `qargi memory get` reads a note. The shared environment is reused when a second role is provisioned. `tests/test_team.sh` covers it offline.
- Push grant for the lead (`lead.push` in the project answers; default none). Only the lead ever pushes, members never do. `local`: the Claude Code session leading may push `agent/*` branches and open pull requests without asking each time (the autoload says so, or says to ask before every push); `cloud: branches`: a cloud or console lead may do the same with a fine-grained token file kept outside every repository and different from the read-only repository token. Merges and releases are `ask` (the person confirms each one) or `never`; there is no automatic merge or release, and a branch pattern outside `agent/` is refused. The lead's prompt carries a Push section that grants exactly this, or says it never pushes.
- `review check --allow-empty`: a team member that returns no commits (blocked, or nothing to change) passes `team check`; a single run that claims DONE with no commits still fails.
- `qargi credential setup lead-push PROJECT`: one command for the cloud lead's write token. It reads a fine-grained token from a file or stdin (never an argument), checks against GitHub that it reaches only this repository and cannot administer it (classic tokens are refused), stores it mode 600 outside every repository, creates a vault of its own with a bearer credential for the GitHub tool, attaches the vault to the lead's deployment and records the grant in the project answers. It prints a plan first and applies behind a plan token. The lead then gets a fixed GitHub allowlist (`packs render`, `packs apply`): read tools and branch, file and pull-request writes unattended, `merge_pull_request` asked of the person, no delete tools and no release tool. `tests/test_leadcred.sh` covers it offline.
- `credential setup lead-push` tests the token itself: a push dry-run over https for Contents write, and a branch-protection read that only a token with Administration can make. The repository answer shows your own role, so it is no longer used to judge the token.
- `credential setup lead-push` no longer counts the repositories a token can see (a fine-grained token reads every public repository). It probes each repository the account can see with a push dry-run and refuses a token that can write anywhere but the project repository, unless `--allow-more-repos`.
- `qargi lead grant|status|revoke PROJECT`: the cloud lead's push grant as one guided flow. `grant` explains how to create the fine-grained token, reads it hidden, and walks through three steps (token and vault, the GitHub tool, the Push rules), printing each plan and asking at the terminal; your answer is the recorded approval, and it never runs without a terminal. Steps already in place are skipped, so running it again is safe. `status` shows what is in place and what is missing, including members pinned at old versions; `revoke` removes the tool and the Push rules, archives the credential, detaches the vault and deletes the token file, and reminds you to revoke the token on GitHub. `tests/test_lead.sh` covers it offline. `collect` also accepts a lead-only run.
- Help, a manual page and bash completion, all generated from one description of the commands (`lib/commands.py`): `qargi help [COMMAND [VERB]|TOPIC]`, `--help` on every command and verb, topics (`concepts`, `approvals`, `naming`, `memory`, `push`, `files`), `man/qargi.1` (`qargi help --man`), and `completions/qargi.bash`, which also completes your projects, instances, a project's teams, sessions and packs. `install.sh --user` installs the page and the completion and `--uninstall` removes them. Inside a project's repository a missing PROJECT is filled in from the current directory (`QARGI_PROJECT` overrides, an argument you give wins) and a role stands for the instance (`dev` for `PROJECT-dev`); outside one, a missing project says which projects exist. `tests/test_help.py` checks the description against the scripts, the page against the generator, and the completion and the inference.
- Tab completion for zsh (`completions/_qargi`) and fish (`completions/qargi.fish`) beside bash, from the same description, with a one-line description for each command, verb and option in the menu. `install.sh --user` installs and `--uninstall` removes them. `tests/test_help.py` runs both shells when they are installed.
- Tab completion is comprehensive: values come from your own state, each with a description in zsh and fish, and are narrowed to what the verb can act on (sessions by state, cloud instances for cloud verbs, projects with teams for `lead` and `team`, a project's roles, skills or tools by command). New: memory store, deployment and model ids; the branches of the project's repository for `--base`; the keys of a project's answers for `project set` and the values each takes; spend ceilings and wait times; the verbs of a command after `help COMMAND`; `--option=value` in all three shells (bash puts the word back together); options already given are not offered again, and `--help` is offered with them. A test fails when a new kind of value in `lib/commands.py` has no completer.
- `qargi export` and `qargi import`: save and restore selected components (config, definitions, memories, state, credentials) as one archive, optionally encrypted with a password (gpg, AES-256; never in argv). Import verifies the archive (names, entry kinds, checksums, format), asks which parts and projects and how to treat what exists (merge, overwrite, replace), prints the plan, writes nothing before you confirm, backs up what it replaces, and treats the audit log as append-only. Credentials only in an encrypted archive; definitions are restored as files; memory notes are written to the project's stores.
- `qargi discover sources|search|recommend|show|install`: tool discovery for the roles of a project. Searches a reviewed catalog and your library, and with `--online` the official MCP registry and Anthropic's skills; recommends by role and by the stack seen in the repository; installs through the existing pack gates (review, your approval of the exact content, scope choice, link, optional apply to cloud agents), or edits the role's apt list or the local agent's tools line after a confirmation. Entry IDs tab-complete.
- `qargi watch SID [MAX_SECONDS] [--warn PCT]` ends early with `budget_tight <cost>/<ceiling>` when a cloud session's cost reaches PCT percent of its ceiling (default 85, 0 turns it off), so the coordinator can offer the user a raise (`qargi instances budget NAME CENTS --session SID`) before the session stops at `budget_reached`.
- A `PreToolUse` guard (`qargi __guard`) on the members' Bash, Edit, Write and NotebookEdit calls refuses `git push`, `gh`, `ssh`, `scp`, `sftp` and changes to a git remote; `qargi discover install` edits the tools line of the members that serve a role (or of all). The agent contract now separates how to wait for a long command locally (`run_in_background`) and in the cloud (detach and poll) and asks for a `gitleaks` pass before the report, which the coordinator repeats.
- Cloud agents get a per-role list of built-in tools to switch off (`roles.<role>.tools_off` in the project answers; default `web_search` and `web_fetch` for every role, plus `edit` for review and the lead), rendered by provisioning as toolset `configs` and carried to existing agents by `qargi packs apply`, whose plan lists them. The shared environment can also hold `roles.<role>.pip` and `roles.<role>.go` (merged like `apt`), and `--networking limited` now renders `allow_package_managers` and `allow_mcp_servers` so the platform accepts it. The built-in GitHub tool for the lead no longer lists four pull-request read tools the server does not expose, and states `write_ok` for its unattended writes.
- Roles are named by their activity: the abilities `build`, `write`, `review` and `test`, plus `lead`. Each ability is defined by a skill (`qargi-build`, `qargi-write`, `qargi-review`, `qargi-test`), which a member loads when the task block names it (`ABILITY: build — load skill qargi-build`) and a cloud agent of that role carries in its prompt. The memory folders are `roles/<role>/`, the project answers `roles.<role>`, the instances `<project>-<role>`, a team's output prefixes `<role>--`, and `team brief` takes `--write-done` and `--review-done`. `qargi help roles` has the table.
- Members: the local workers are agents you name. qargi ships one member definition (`agents/member.md`, with `Skill` among its tools) and installs none; `qargi agent add NAME [--abilities LIST] [--model M] [--effort E] [--project P]` renders it (all four abilities by default; a name that exists, is not kebab-case or is a built-in Claude Code agent type is refused), `qargi agent for ABILITY` prints the member dispatch spawns, and `list`, `rename` and `remove` manage them. `/qargi-project` asks for the members once.
- Review is read-only as a rule: `qargi local prepare --ability A` records the task's ability in the run directory, and under review the guard refuses an edit outside the run's output directory and a Bash command that writes into the clone (a redirection, a file command, a git command that changes the work tree or history).
- The coordinator's procedure for verifying and applying returned patches is the skill `qargi-verify`.
- `qargi migrate roles [--member-names build=NAME,...] [--apply --plan TOKEN --asked "..."]`: existing installations made with the earlier names (roles `dev` and `docs`, the agents `qargi-dev`, `qargi-docs`, `qargi-review`, `qargi-test`, cloud agents `<project>-agent-<role>`) move to the current ones: registry, tracker, answers, pack links and saved definitions; the notes of both memory stores; the cloud agents and deployments (renamed by update, nothing archived) and their prompts; the old agent symlinks, replaced by members. It prints a plan with every cloud call and a token, applies exactly that plan, stops at the first failure and is re-runnable. `qargi import` maps an archive made with the earlier role names to the current ones.
