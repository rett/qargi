# Install and upgrade

Installing qargi, keeping it current, binding a project to a cloud profile, and moving what qargi keeps about you between machines.

- [Install](#install): the installer, where the data lives, running a branch checkout
- [Upgrading the installed tool](#upgrading-the-installed-tool)
- [Cloud (ant) profiles per project](#cloud-ant-profiles-per-project)
- [Export and import](#export-and-import)

## Install

Choose one installation level. For a Claude Code lead, install user skills in `~/.claude/skills`:

```sh
./install.sh --user
```

For a Codex lead, install user skills in `~/.codex/skills`:

```sh
./install.sh --user --runtime codex
```

Either user installation also installs the command in `~/.local/bin`. The two install side by side, from one tool: installing one runtime leaves the skills of the other as they are, and the command, the manual page and the completions are shared. `./install.sh --user` without `--runtime` refreshes every runtime already installed (and installs `claude-code` when none is), so it is the line to run after `git pull`; `--runtime NAME` narrows a run to that runtime. Alternatively, install skills for one repository only, choosing the lead's runtime (`claude-code` is the default):

```sh
./install.sh --project /path/to/repo
```

For a Codex lead, use `./install.sh --project /path/to/repo --runtime codex`. Project installation does not install the command. For a project whose runtime supports member definitions, add a worker and a read-only reviewer:

```sh
qargi agent add worker --project P
qargi agent add reviewer --project P
```

qargi needs Python 3.11 or later (the standard library reads the TOML files some runtimes keep their settings in). The `agent add` lines need a project whose `models.provider.local` is set (see [Providers and runtimes](../members-and-providers/providers.md)) and a runtime that keeps member files: a project on `codex` has none, and its members run with `qargi local run`.

For a Codex lead, install with `./install.sh --user --runtime codex`: the skills go to `~/.codex/skills`, where Codex finds a user's skills (with its default `CODEX_HOME`), and the command to `~/.local/bin` as before. The setup, what a Codex session sees of the skills and what is not verified are in [Codex as lead and as member](../members-and-providers/codex.md#codex-as-the-lead).

Both link to this checkout, so `git pull` updates them; add `--copy` for real
files (the whole tool is copied to `~/.local/share/qargi` for `--user`),
`--uninstall` to remove. The install records every path it wrote (links, copied
files, the directories it had to create) before it writes it, in manifests under
`install.d/` beside `install.json` in `~/.qargi/config`: `runtime-NAME.manifest` for the skills of a runtime,
`shared.manifest` for the command, the manual page, the completions and the `--copy` tool, and `project-N-NAME.manifest` for the skills of a
runtime in one project. `--uninstall` removes exactly what they list, copies included, and
nothing else: a file of yours inside a copied skill is kept, and so is `~/.qargi`,
unless the install made its `config` directory and nothing else is left in it.
Every line of a manifest is checked when it is read, and one bad line stops the run with nothing changed. A run holds `install.lock`
(beside `install.d/`) while it reads or changes the records, so a second run waits briefly and then refuses.
Without a manifest `--uninstall` removes nothing and says so (exit status 1),
with or without `--force`. An existing real file or directory, or a link no install recorded, is never replaced without `--force`; a link
that already points where the install would point it is left as it is. The
skills directories come from the definition of the runtime whose session loads the
skills (`--runtime NAME`, default `claude-code`: `~/.claude/skills`); a runtime
with none is refused, and one skills directory belongs to one runtime. The command is
always user-level.

`./install.sh --user --uninstall --runtime NAME` removes the skills of one runtime; the command, the manual page, the completions, `install.json` and
`install.d/` go with the last runtime. `./install.sh --user --uninstall` alone removes every installed runtime and lists them first. A runtime whose definition has gone is skipped with a note when refreshing, and can still be uninstalled.
The runtimes come from one tool, all linked or all copied: `--runtime NAME` from another tool or in the other mode is refused while another runtime is installed
(`./install.sh --user [--copy]` without `--runtime` moves them all), and a `--user --copy` run copies every installed runtime again, since it rewrites the tool copy they come from.
A project takes both runtimes too (`--project DIR --runtime NAME`), each hidden through the repository's local exclude file and removed on its own.
Installs made by qargi 0.3.1 or earlier kept one `install.manifest` (and a `project-N.manifest` per project) in `~/.qargi/config`; `install.sh` no longer reads or removes them, and installing or uninstalling with one beside `install.d/` behaves as without it. A host that has only those records runs the 0.3.2 installer once before upgrading further, or installs again with `--force`; once `install.d/` holds the records, remove the old files by hand. A link the install recorded that you replaced with a file or a directory is refused with nothing changed: move it aside and install again, or use `--force` to replace it. `install.sh` also refuses an `install.lock` that is a link or not a regular file, without opening it and with nothing changed: move it aside and run again. A member cannot run the tool's own `install.sh` or `lib/install_record.py` (the engine `install.sh` runs), in any use, and the guard protects the records; the copies in a clone or a project stay the member's. The instance
registry, session tracker and profiles are per user, under `~/.qargi/config` and
`~/.qargi/state` (`QARGI_HOME` replaces `~/.qargi`), whichever level installs the skills. Repository rules for
agents go in a profile under `~/.qargi/config/profiles/`, also
outside the repository: nothing qargi related is added to a project's
committed files. `qargi project profile check [NAME] [--profile FILE]` reads the
profile and changes nothing: it exits 1 while the profile still carries the shipped
example's title and "Copy to" line (`project validate` warns of the same), and warns
of a gate command in its Gates section that the repository's `CLAUDE.md`,
`AGENTS.md` and `Makefile` targets do not know. `--project` installs are hidden from git through the
repository's local `.git/info/exclude`.

Installing also adds the baseline packs that ship with qargi (`packs/`) to your pack library, without linking any of them (see [Baseline packs](../skills-tools-and-memory/local-session.md#baseline-packs)).

### Where the data lives

Everything qargi keeps about you is under `~/.qargi`: `config/` (projects, instances, profiles, the pack library of skills, tools and provider packs, credentials, `install.json`, the `install.d/` records) and `state/` (the session tracker, the audit log, runs, backups, the renders under `render/`, the provider verification records). `QARGI_HOME` replaces the root; `QARGI_CONF` and `QARGI_STATE` name either directory and win over it. `XDG_CONFIG_HOME` and `XDG_STATE_HOME` are not used (the `ant` CLI keeps its login there).

### Running a branch checkout

`install.sh --user` records the tool it installed in `~/.qargi/config/install.json`. A checkout run from anywhere else, for example `bin/qargi` in a worktree, is then a dev run: it keeps its data in `<checkout>/.qargi` (ignored by git), prints `qargi: dev run from ...; data in ...` on stderr once per command, and never touches your live projects, credentials or audit log. The installed copy (for example `/opt/qargi`) is for confirming committed work and managing live projects, and never writes into its own directory. Without `install.json` a checkout behaves as the installed one. To point a dev run at live data on purpose set `QARGI_HOME=~/.qargi`; any explicit `QARGI_HOME`, `QARGI_CONF` or `QARGI_STATE` overrides the sandbox. Members call `qargi __guard` and the hooks from `PATH`, which is the installed copy: put `<checkout>/bin` first on `PATH` to test a branch's guard or hooks.

## Checking the host

`qargi doctor [PROJECT]` checks the host for what makes qargi fail quietly and changes nothing (a member may run it). It prints one line per check, `ok|warn|unknown  name: detail`, and under a warning the lines that say what you can do; it never runs a fix. The exit status is 0 whatever it finds, or 1 with `--strict` when a check warns; `--json` prints the checks as one object. Five checks make the first slice:

- `remove-ipc`: logind removes a user's IPC objects, among them what lives in `/dev/shm`, when the user's last session ends, unless `RemoveIPC=no` is set or the user lingers. The check reads `RemoveIPC` with `busctl` and the linger with `loginctl` (`QARGI_BUSCTL` and `QARGI_LOGINCTL` name other programs); with `RemoveIPC` on and no linger it warns and prints the drop-in `/etc/systemd/logind.conf.d/remove-ipc.conf` (`[Login]`, `RemoveIPC=no`, then `sudo systemctl reload systemd-logind`) or `loginctl enable-linger USER`. Without systemd, logind or those tools it says `unknown`.
- `guard`: `qargi` is on `PATH` and `qargi __guard`, the hook command of a member, answers as the guard does; with a project, no member is missing, stale or edited.
- `shm`: the free space under `/dev/shm` (`QARGI_RUN_TMP` moves it) and the orphaned `qargi-run.XXXXXX` directories there, the listing that `qargi local clean --orphans` prints; it warns on an orphan or on less than 10% free (`QARGI_DOCTOR_MIN_FREE` moves the limit, in percent).
- `window-source`: where the context-window table of the project's runtime comes from (its definition, or the answer `lead.context_window`) and whether each model id the project's roles name is in it, and the model of the lead's own session (the last turn of its transcript, read only) unless the answer is set; an id that is not in the table warns, since its window is only assumed, while a lead model that cannot be determined (no transcript, no counted turn, no model id) is not a warning.
- `install`: the install records agree with the disk: it says `ok` when they do, and warns of an `install.manifest` (or `project-N.manifest`) of 0.3.1 or earlier still present (no longer read; it can be removed by hand after checking that `install.d/` holds the records), of a recorded link that is missing or points elsewhere, and of a recorded version that differs from the tool's.

## Upgrading the installed tool

`qargi upgrade --branch develop` fetches that branch of the installed checkout's origin (for example `/opt/qargi`), shows the commits and files that would change and prints a plan token; `qargi upgrade --branch develop --plan TOKEN --approved "..."` applies exactly that (fast-forward only on the current branch, `--tag T` for a tag), re-runs `install.sh --user`, which refreshes every runtime installed (the plan prints which), and lists the members to refresh. When `~/.qargi/config/agents.json` is in an earlier shape, which every `qargi agent` verb refuses, the plan and the end of the upgrade warn about it and say to move it aside and add the members again with `qargi agent add NAME --project P`; the upgrade itself does not touch it. The git commands that write into the root-owned checkout run through `sudo`.

## Cloud (ant) profiles per project

`qargi cloud set PROJECT --profile NAME --workspace-id wrkspc_...` binds a project to an `ant` profile and the workspace it must
reach; `qargi cloud login PROJECT` logs that profile in on your terminal, and `qargi cloud check` verifies it. `qargi cloud list` and `show`
print the bindings, and `qargi cloud unset PROJECT` removes one. (These are `ant` profiles; the model profiles of a base session are
described in [Choosing models](../members-and-providers/models.md).) From then on every
command about the project runs `ant` under that profile and refuses to touch another workspace. Without a binding, `ant`'s
active profile is used.

## Export and import

`qargi export` writes one archive of what you select, and `qargi import` restores it, on this machine or another:

- **config**: project answers, the instance registry, profiles, the skill and tool library.
- **definitions**: the cloud agents, deployments and environment as they are now, read from the cloud with secret values removed. Import restores them as files; rebuild with `qargi provision`.
- **memories**: every note of the memory and reference stores. Import writes them to the stores named in the project's answers.
- **state**: the session tracker and the audit log (the audit log is only ever appended to).
- **credentials**: token files. Only an encrypted archive may hold them; the tokens in the cloud vault are not exported.

Both ask what to include (or take `--only`/`--project`). Export asks for an optional password; with one the whole archive is encrypted with gpg (AES-256) and the password never appears in a command line (`--password-file` for scripts). Import asks for the password if the archive is encrypted, shows what is inside, asks which parts and projects, and for each part how to treat what exists: `merge` (add what is missing), `overwrite` (also replace what differs) or `replace` (make it match the archive, removing the rest; you must type `replace` to allow the removals). It prints the plan, writes nothing until you confirm, and saves whatever it replaces or removes under `~/.qargi/state/backups/`. The archive is treated as untrusted: names, kinds of entry and checksums are verified before anything is read. Its project answers never add or change `models.extensions`, `models.accept_no_barrier` or the lead's answers that have no plan of their own (`ci.not_gates`, `methodology_accepted`, `review.reject_trailers`, `backlog.archive`, `backlog.section`): the stored value stays, or the key is left out, and a note says so. `qargi import FILE --dry-run` prints the plan without a terminal.
