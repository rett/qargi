# Codex as lead and as member

The local runtime `codex` (`lib/providers/codex.json`, family `openai`) is data only: a member is a `codex exec` process that `qargi local run` starts in the run's clone. Codex as the **lead** (the session you talk to, which loads qargi's skills and runs the `qargi` command) and Codex as a **member** (a headless process that reads `RUN/task.md` and returns qargi's artifacts) are different surfaces; Codex's own subagents are not members and do not replace the prepared clone and the run registry. See [Providers and runtimes](providers.md) for the table of what `codex` is and is not, and [Choosing models](models.md) for its catalog.

What this page says was established with codex-cli 0.167.1 on Linux. "Seen offline" means a check with no sign-in, no model call and no network (`codex debug prompt-input`, `codex mcp list --json`, `codex features list`, `codex debug models`, `codex sandbox`, with a scratch `CODEX_HOME`). "Live" means a check with a sign-in and a model call, on a scratch repository. Three capabilities of `codex` are verified live and dated in its definition; the others stay unverified (`verified_on` null) until a live check of `/qargi-providers` (`verify.md`) shows them ([What is verified](#what-is-verified)).

- [What is verified](#what-is-verified)
- [Platform and sandbox](#platform-and-sandbox)
- [What a member run loads](#what-a-member-run-loads)
- [What a member can reach](#what-a-member-can-reach)
- [Skills and MCP tools of a member](#skills-and-mcp-tools-of-a-member)
- [The output of a run](#the-output-of-a-run)
- [Codex as the lead](#codex-as-the-lead)
- [A complete local run](#a-complete-local-run)
- [Sending a message to a Codex session](#sending-a-message-to-a-codex-session)
- [Not supported, not verified](#not-supported-not-verified)

## What is verified

Each verified capability carries `verified_on` (the date of its checks) and `source` (the evidence and the CLI version) in `lib/providers/codex.json`; `qargi provider show codex` prints the date and the note of each, and `--json` the whole definition. All were checked with codex-cli 0.167.1 on 2026-11-11, on the fast tier (`gpt-6-luna`) at `low` effort.

- **Headless dispatch**: Verified: yes; By: `qargi local run` ran `codex exec` for a write-class build task on a scratch repository: the member created and committed a file, the series, manifest and report came back, `qargi local verify` found the refs unchanged, `qargi review check` ended with 0 failures (3 warnings about optional manifest fields), and `qargi review apply` applied the series in a disposable repository, where the DONE command passed
- **Read-only barrier**: Verified: partial; By: offline, `codex sandbox -- sh -c 'echo x > /tmp/p'` answered "Read-only file system"; live, a `codex exec --sandbox read-only --ignore-rules` member (approval policy `never`, its own `CODEX_HOME` and `HOME`) asked to create a file in its working directory reported "Read-only file system" and the directory was unchanged. It holds the member's shell writes, not its reads, and not a hosted tool or an MCP server, which run outside the sandbox: so the claim is `partial`, and a review role runs on it with that note and no `provider accept`
- **Token report**: Verified: partial (tokens only); By: the `turn.completed` events carried the usage counts the definition reads, and the runs printed them as `USAGE=` (input, cached, output and reasoning tokens)

Not verified, and so counted as not supported:

- **The model and effort overrides.** A run with `-m gpt-6-luna` and `-c model_reasoning_effort=low` succeeded, but no event of `codex exec --json` names the model or the effort used (the events are `thread.started`, `turn.started`, `item.completed` and `turn.completed`), so that they take effect is not observable.
- **Skills and MCP.** No real run has shown which skills a member loads or the MCP tool names and `enabled_tools` in a session.
- **The rest of a run.** How codex-cli writes a sign-in it refreshes during a run (through the link, or by replacing it), each baseline key holding in a real run, the hosted tools being gone, and how a trusted project's `.codex/` loads.

## Platform and sandbox

qargi runs on Linux only (see the requirements in the repository's README). On Linux the Codex sandbox is bubblewrap: `codex sandbox -- CMD` runs the command under `codex-linux-sandbox` in a bwrap namespace with a read-only root, a seccomp filter and the network restricted (seen offline). Codex has a different sandbox on macOS; it plays no part here, since qargi does not run there. A read-only member runs under `--sandbox read-only` (nothing writable), a write member under `--sandbox workspace-write` with OUT and the clone's `.git` added as writable directories. Under `workspace-write` Codex keeps the clone's `.git`, `.agents` and `.codex` read-only unless they are added (seen offline), which is why the write class adds `.git` and nothing else.

**Keep the scratch directory off `/dev`.** The sandbox mounts a `/dev` of its own, so nothing under `/dev`, `/dev/shm` included, is there for the member's commands: a read-only member run there sees no clone, no contract and no OUT, and starts in `/`; a write member sees its clone, OUT and TMP, which the sandbox binds in as writable places, but not its contract or its git wrapper beside them (seen offline with `codex sandbox`, and live: a review run under `/dev/shm` returned a useless report, and a build run there worked without ever reading its contract). The definition declares it (`dispatch.hidden_paths`: `/dev`, and the clone, OUT and TMP shown to a write run), so `qargi local prepare` and `qargi local run` refuse such a run before anything is made or started, naming the path, `/dev` and the fix. A `--scratch` under `/dev/shm`, a common place for fast throwaway work, therefore does not work for Codex runs, a read-only one least of all: use a directory on disk under your home, such as `~/.cache/qargi-runs`. A directory under `/tmp` is not verified: the baseline keeps `/tmp` from being writable to the member's commands (`exclude_slash_tmp`), and no check has shown a run there working. The run's TMP may stay on `/dev/shm`, where `prepare` puts it: a write run's TMP is bound in, and a read-only member writes none.

**Which `codex` runs.** `qargi local run` resolves `codex` on your `PATH`, entry by entry, to the first regular executable file whose real path is named `codex` (or `codex.js`, a launcher a package manager links as `codex`, or `codex-` and a suffix, a release binary such as `codex-x86_64-unknown-linux-musl` linked as `codex`) and starts that path; `--dry-run` prints it as `COMMAND=` and `RUN/dispatch.json` records it as `command`. A version manager's wrapper or shim that is a link to a program of another name is passed over with a note. With `HOME` set to the run home such a wrapper looks for Codex under the run home, or installs it there, and the sandbox's re-exec of Codex then fails, so every shell command of the member fails (seen in a live run). When only such a wrapper is on `PATH` the run is refused (exit 3), naming it: put the directory the version manager installed Codex in first on `PATH`. A shim that is a script named `codex` cannot be told from the program by its name and runs as found. The member's own `PATH` is yours, unchanged, and so are the wrappers on it for other tools: a version manager's `go`, `node` or `python`, and a script whose first line is `#!/usr/bin/env node` that reaches node through one, also run with `HOME` set to the run home, where they may look for their tools, install them or fail, and the member's command fails with them. qargi does not look for these (only the command it starts is resolved). When a member needs such a tool, start the run with a `PATH` whose first entries are the directories the version manager installed the tools in.

## What a member run loads

The run's `config.toml` in `CODEX_HOME` (`RUN/home/.codex/config.toml`) is the user-level configuration of the member's Codex, written by qargi for every run. It is not the only thing Codex reads:

- **your `~/.codex/config.toml`, rules, skills, `AGENTS.md`**: not loaded: `CODEX_HOME` is the run home, which holds only what qargi writes (the configuration file, the sign-in link) and what Codex makes there itself. Not loaded is not unreadable: the member's commands can read them by path ([What a member can reach](#what-a-member-can-reach))
- **`~/.agents/skills`**: not loaded: `HOME` is the run home too
- **the run's `config.toml`**: the baseline below, and the MCP servers of the role's tool packs
- **the clone's `.codex/` (its `config.toml` with MCP servers and settings, `rules`, hooks)**: not loaded: Codex loads a project's `.codex/` only for a trusted project, and a run clone is a fresh path that no configuration marks trusted (the run's file has no `projects` entry). Seen offline: with a trust entry in a scratch home the same repository's MCP server and settings load
- **the clone's `AGENTS.md`**: loaded, as for any Codex session: the repository's own instructions keep working
- **the clone's `.agents/skills`**: loaded (also untrusted): only what the repository commits
- **execpolicy rules files**: none: `--ignore-rules` drops the user's and the project's
- **a system-wide or administrator-managed Codex configuration**: not excluded: qargi cannot keep it out, and it applies to members as it applies to you

The baseline is `dispatch.run_config.baseline` of the definition; a run with no MCP server and a run with one get the same keys (a test compares them key by key), and `--strict-config` makes Codex refuse a key it does not know, so a key a later CLI renames stops the run instead of being ignored.

- **`approval_policy`**: Value: `never`; Why: nobody answers a member; a command the sandbox refuses fails and the member sees the failure (the prompt input says "Approval policy is currently never", seen offline)
- **`sandbox_workspace_write.network_access`**: Value: `false`; Why: no network for the member's shell commands
- **`sandbox_workspace_write.exclude_slash_tmp`**: Value: `true`; Why: `/tmp` is shared with the rest of the machine; a write member writes temporary files in `TMPDIR`
- **`sandbox_workspace_write.exclude_tmpdir_env_var`**: Value: `false`; Why: `TMPDIR`, the run's TMP, stays writable (seen with `codex sandbox`: `/tmp` refused, `TMPDIR` written, no network)
- **`web_search`**: Value: `disabled`; Why: hosted search runs at the vendor, outside the shell sandbox
- **`features.apps`, `plugins`, `remote_plugin`, `hooks`, `computer_use`, `browser_use`, `in_app_browser`, `image_generation`, `tool_suggest`, `skill_mcp_dependency_install`**: Value: `false`; Why: features that reach outside the shell sandbox, install things or run code Codex did not get from the member's commands (`codex features list` shows them off)
- **`skills.bundled.enabled`**: Value: `false`; Why: the skills Codex ships (an installer, a creator, image generation) are no part of a member's task (the prompt input lists none, seen offline)

Each key is read by this CLI (a value of the wrong type is refused, naming the key). That every key holds in a real run, and that the hosted tools are gone from a real session, is not verified: the offline prompt input shows no hosted tool either way. The multi-agent tools (`spawn_agent` and its kin) stay listed: no supported switch removed them offline.

## What a member can reach

- **Files.** A write member can write its clone, the clone's `.git`, OUT and `TMPDIR`. With the `.git` it can set what git runs in that clone (a hook, `core.fsmonitor`, an alias, a filter driver), so never run git in a write member's clone: take the work from the patches in OUT, copy files out, or make a clean copy first with `git clone --no-local` (git(1), SECURITY). `qargi local run` compares the clone's `.git/config`, `hooks/` and `info/` before and after the member and names a change in a `GITDIR=changed:` line (it restores nothing). A read-only member can write nothing, OUT and `TMPDIR` included, so a test that needs a temporary file fails in a read-only run. Both can read what your user can read: the sandbox holds writes, not reads.
- **Network.** The member's shell commands have none. That is not all the network a run uses: the Codex process itself talks to the model service, and it connects to the MCP servers of the run's file, outside the shell sandbox. Hosted search and apps are off in the baseline (not verified live).
- **Git.** The member's git has no credentials (`HOME` is the run's, no global configuration, no ssh agent, no prompts), the clone's only remote is the run's bare copy with its push URL disabled, and the sandbox gives its commands no network, so an ordinary push has nothing to reach and nothing to authenticate with. That is what qargi supports, not a proof that no push can happen: `qargi local verify` compares every ref of the real repository before and after, and you apply only the patches.
- **No guard hook.** No `qargi __guard` runs for a Codex member, so the guard's refusals (push, `gh`, `ssh`, the skill and runtime verbs, writes to protected places) do not apply as such; the sandbox's write and network denial, the credential-free git and the checks of what comes back hold instead.
- **Sign-in.** Your `~/.codex/auth.json` is linked into the run home for the length of the run, and the member's Codex loads nothing else of your Codex home. This is configuration separation, not secrecy from the member: the sandbox holds writes, not reads, so the member can read that file through the link and the rest of your `~/.codex` (sessions, history) by path.
- **A sign-in refreshed during a run.** Written through the link, it lands in your `~/.codex/auth.json` directly: qargi cannot prevent a write through the link, and the run notes that your file changed. Written by replacing the link with a new file (an atomic replace), it never reaches your file: qargi does not write your file, since another run, a Codex session or a sign-in of yours may have written it meanwhile and nothing qargi can check before a rename keeps such a writer out. The new file is kept in the run home as `auth.json.from-run` (mode 600, over one an earlier run kept there), named in a `HOME_RESIDUE=` line, in `home.residue` of `RUN/dispatch.json` (the name, never a value) and by `qargi local list` and `verify`, with a note that says whether your file is unchanged since the run started. To reconcile it: if `codex login status` in your terminal still finds you signed in, keep yours and let `qargi local clean` remove the copy; if not, and the note says your file is unchanged, move the copy over yours yourself (`mv RUN/home/.codex/auth.json.from-run ~/.codex/auth.json`), or sign in again with `codex login`. When the note says your file changed, keep yours.

## Skills and MCP tools of a member

A Codex member receives the contract and the task, and no qargi skill. Its `CODEX_HOME` and `HOME` are the run home, which has no skills directory; its clone is made from the repository's commits, so the links a session makes in a checkout (untracked) do not reach it, and only skills the repository itself commits under `.agents/skills` load; and the baseline turns the bundled skills off. A lead-management skill (`qargi-flow`, `qargi-verify`, `qargi-task` and the rest) therefore never becomes a member capability: a test links them where a Codex lead finds them (`~/.codex/skills`, `~/.agents/skills`, the lead's checkout) and checks that the member sees none.

Its MCP tools are the `[mcp_servers.PACK]` tables of the run's file for its role and class: `enabled_tools` holds the tools as the server names them (`platform.list_items`, `repo/push`, `issue-close`), and the names the model is given are the `mcp__SERVER__TOOL` form, with every character other than a letter, a digit, `_` and `-` written as `_` (`mcp__kb__platform_list_items`). Two tools whose names come out alike (`a.b` and `a_b`) are given to no one; a tool the server lists but the pack does not declare is never enabled; an `always_ask` tool is never enabled (nobody answers); a read-only role gets the declared reads only. A server runs outside the sandbox, so `enabled_tools` is what holds it. An authenticated server gets only its `url` and `enabled_tools`: a tool pack's `vault_ids` are credentials of the cloud vault, which a local run never reads, and qargi writes no bearer token, header or `bearer_token_env_var`, so a server that needs a credential fails to connect in a member run. The model-visible names were not seen offline (a server must answer); they are among the live checks.

## The output of a run

- **The report.** Codex writes the member's last message (`-o`) to a new private file of the run; when the run ends qargi checks it and publishes it as `OUT/report.md`. With `--again` the earlier report is set aside as `OUT/report.md.previous` before the member starts: a run that publishes a report replaces it, and a run that publishes none leaves it there, where no check takes it for this run's.
- **A read-only run** cannot write OUT, so the lead writes `OUT/manifest.json` beside the report: the minimal report-only manifest, with what the lead recorded of the run and no test result and no verdict; `qargi review check` still reads the Findings and the verdict line of the report.
- **A write run** commits in its clone and collects its patches into OUT; a change to a tracked file left uncommitted with no patches is a refusal (`refused`, exit 2), never a finished task. A new file the member never added is not a refusal: it is reported (`WORKTREE=untracked`, and a warning in `qargi review check`), the run can still end `ok`, and `qargi local clean` removes it with the clone, with a warning. When such files are the task's work, send the run back to commit and collect them.
- **Usage** is tokens only, added up from the `turn.completed` events into `RUN/dispatch.json` and the `USAGE=` line; a count no event reports is named as not reported, never recorded as 0. A ChatGPT sign-in reports no money per run, and a wall-clock timeout is not a token or money ceiling.

## Codex as the lead

1. Install the Codex CLI and sign in yourself (`codex login`, in your terminal); `codex login status` tells you whether you are signed in.
2. `./install.sh --user --runtime codex` links the `qargi-*` skills into `~/.codex/skills`, the user skills directory of the `codex` definition, and the `qargi` command into `~/.local/bin` (keep it on `PATH`). A `CODEX_HOME` of yours that is not `~/.codex` does not see them. Seen offline with the skills linked there in a scratch home (`codex debug prompt-input`): a Codex session lists all eleven lead skills. codex-cli 0.167.1 drops a skill whose front matter it cannot parse, without a word; `qargi-task` was dropped that way until its `argument-hint` was quoted, and the install test now checks the front matter of every skill with a strict rule.
3. Attach the project with its local runtime: `qargi project attach ~/src/myproject --name myproject --provider-local codex` (or `qargi project set myproject models.provider.local codex`). There is no `qargi agent add` for Codex: it keeps no member files, and every member runs through `qargi local run`.
4. Codex reads the repository's `AGENTS.md` itself; qargi adds nothing to a project's committed files. The project's packs (`qargi packs apply --target codex`) wait until the `skills` claim of `codex` is verified, so a lead session loads the user-level skills only.
5. A Codex session has no hook that qargi uses: pass `--as ID` (or set `QARGI_LEAD`) on the commands that take a lead identity (`qargi provider notes identity`), and run a command that asks for input or a credential in your own terminal (`qargi provider notes commands`).

Not verified: which sandbox and approval settings a Codex lead session needs for qargi's own writes. `qargi` writes `~/.qargi`, the scratch directory of the runs and their TMP under `/dev/shm`, all outside a session's workspace, so under `workspace-write` expect Codex to ask or refuse. Installing for a second runtime beside the first is not verified either.

## A complete local run

A build member runs with the project's local runtime `codex`.

Prepare prints `RUN=...`, `CLONE=...`, `OUT=...` and `TASK_FILE=RUN/task.md` (the whole task block: ROLE, TASK, DONE, SCOPE and paths). The dry run shows the argv, run configuration path, tools, baseline and prompt without running anything. The run starts codex exec in the clone and prints `OUTCOME=`, `REPORT=` and `USAGE=`. Verify checks that the repository's refs are unchanged and OUT holds patches; review check checks the patches, manifest, SCOPE and DONE. Apply puts the patches on `agent/dots` with your go-ahead; clean after the work is applied and merged.

```sh
printf 'Accept a period in a user name.\n' > ~/tasks/dots.md
qargi local prepare --repo ~/src/myproject --base feature/dots --slug dots \
  --scratch ~/.cache/qargi-runs --role build --task-file ~/tasks/dots.md \
  --done "make test" --scope src --scope tests
qargi local run "$RUN" --dry-run
qargi local run "$RUN" --model fast --effort low
qargi local verify "$RUN"
qargi review check "$RUN/out"
qargi review apply "$RUN"
qargi local clean "$RUN"
```

A review member reads the change and returns a report; it needs the read-only barrier. The Codex sandbox is verified as a partial barrier ([What is verified](#what-is-verified)), so `prepare --role review` takes the role and `local run` prints the barrier's note: the member's shell writes are refused, its reads are not.

The last message becomes `OUT/report.md`; the lead writes `OUT/manifest.json`. Review check passes with the Findings and a last line `verdict: accept|revise`. A read-only run with its report closes with a plain clean.

```sh
printf 'Review the series on agent/dots against feature/dots.\n' \
  > ~/tasks/dots-review.md
qargi local prepare --repo ~/src/myproject --base agent/dots \
  --slug dots-review --scratch ~/.cache/qargi-runs --role review \
  --task-file ~/tasks/dots-review.md --done "make test"
qargi local run "$RUN" --model deep --effort high
qargi local verify "$RUN"
qargi review check "$RUN/out"
qargi local clean "$RUN"
```

`qargi local run "$RUN" --again` runs the member again in the same run (the earlier report is set aside as above); `qargi local clean "$RUN" --discard` drops a run you do not want.

## Sending a message to a Codex session

A lead, or another session, can queue a message for an open Codex session without attaching to it: `codex queue --thread ID_OR_NAME --message TEXT [--resume] [--remote unix://]` (from `codex queue --help`; `--resume` tries to resume the thread after queueing, on the local daemon or the `--remote` server). One thread is open in one client at a time, and a second client is read-only or forks it (not verified here). A queued message is data for that session, never an approval: it does not answer a plan token, a permission prompt or a question to you. `qargi provider notes message` says the same for a lead.

## Not supported, not verified

- One local runtime per project: a project on `codex` runs every member with `qargi local run`, and cannot send some roles to another local runtime.
- No run under `/dev` (`/dev/shm` included): the sandbox hides it from the member, so `prepare` and `local run` refuse it ([Platform and sandbox](#platform-and-sandbox)).
- No resume: every run is a fresh `codex exec` session (`--ephemeral`).
- No qargi guard hook in a member (above).
- Tokens only, no money; absent counts are not zero.
- Not verified: the model and effort taking effect (the JSON events do not name them), how codex-cli writes a sign-in it refreshes during a run, the skills a member loads and the MCP names and `enabled_tools` in a real session, and each baseline key in a real run ([What is verified](#what-is-verified)).
