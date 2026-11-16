---
title: Install and update
description: Install qargi for your user from a checkout, check that the command and the skills are in place, update it from its origin and remove it again.
doctype: how-to
---
qargi is a command, a set of skills and a manual page, installed from a checkout of the repository. The installed command defaults to configuration and lifecycle state under `~/.qargi`. Configured overrides, development checkouts and memory tiers follow the release's [filesystem reference](/reference/files/).

## 1. Requirements

- Linux with the prerequisites listed in the release's [README](https://github.com/rett/qargi/blob/0.3.1/README.md). Python 3.11 or later is required, and the installer checks its version.
- A coding-agent runtime for the members. The project names it for each surface; there is no default. `qargi provider list` shows the runtimes qargi ships.
- `gh` and the cloud CLI are optional: the first for publishing a release, the second only if you use cloud agents.

## 2. Install for your user

```bash
git clone https://github.com/rett/qargi.git
cd qargi
./install.sh --user --runtime claude-code
```

Choose the lead runtime with `--runtime`. The example uses Claude Code. A Codex lead uses `./install.sh --user --runtime codex`, which links skills into `~/.codex/skills`; its [setup guide](https://github.com/rett/qargi/blob/0.3.1/docs/members-and-providers/codex.md#codex-as-the-lead) records qualification limits.

For Claude Code, this links the skills into `~/.claude/skills`, the command into `~/.local/bin`, the manual page and the shell completions (bash, zsh, fish) into your user directories, and adds the baseline packs to your pack library without linking any of them. It records what it installed in `~/.qargi/config/install.json`.

Linked files follow checkout updates. Rerun the installer for the selected runtime to refresh managed links and seed missing baseline packs. To install real files instead, add the copy flag; the whole tool is then copied to `~/.local/share/qargi`.

```bash
./install.sh --user --runtime RUNTIME --copy
```

Use the same selected runtime in later install commands, replacing `RUNTIME` with its name. An existing real file or directory requires an explicit force option for replacement.

## 3. Check it

Make sure `~/.local/bin` is on your `PATH`, then:

```bash
qargi version
qargi help
qargi help concepts
```

`qargi help` lists the commands and the topics. `man qargi` is the complete reference; if the manual page is not on your `MANPATH`, `qargi help --man | man -l -` prints it.

## 4. Install the skills for one repository only

```bash
./install.sh --project /path/to/repo --runtime RUNTIME
```

The selected runtime declares the checkout skill path, such as `.claude/skills` for Claude Code or `.agents/skills` for Codex. The paths are hidden from git through the repository's local exclude file. The command is always user-level, so install `--user` first. The installer refuses when any of those paths is already tracked.

## 5. Update

If you installed with links, update the checkout and run the installer again:

```bash
git pull
./install.sh --user --runtime RUNTIME
```

If the installed tool is a root-owned checkout that `install.sh` recorded, `qargi upgrade` moves it to a newer branch or tag. It prints the commits and files that would change and a plan token, and applies only that plan:

```bash
qargi upgrade --tag TAG
qargi upgrade --tag TAG --plan TOKEN --approved "upgrade to TAG"
```

The current `upgrade` command invokes the installer with its Claude Code default. A Codex installation needs a separately reviewed runtime-preserving upgrade plan. Preserve active-run authority and obtain a shared-runtime idle boundary before changing a shared installation.

For in-session runtimes, `qargi agent list` shows changed member definitions as `STALE`; inspect each before `qargi agent refresh NAME`. Codex command mode uses logical worker and reviewer profiles.

## 6. Remove it

```bash
./install.sh --user --uninstall
```

Your projects, members and audit log under `~/.qargi` stay. `QARGI_HOME` moves that whole directory, and `qargi help files` lists what is in it.

## 7. See also

- [Your first project](/first-project/)
- [Safety](/safety/): what `upgrade` and the installer will not do for a member
- [Command reference](/reference/)
- [Releases](/releases/)
