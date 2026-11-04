---
title: Install and update
description: Install qargi for your user from a checkout, check that the command and the skills are in place, update it from its origin and remove it again.
doctype: how-to
---
qargi is a command, a set of skills and a manual page, installed from a checkout of the repository. It keeps what it knows about you and your projects under `~/.qargi`, never inside a project.

## 1. Requirements

- Linux or macOS with `bash`, `git` and `python3` 3.11 or later. The installer refuses an older Python.
- A coding-agent runtime for the members. The project names it for each surface; there is no default. `qargi provider list` shows the runtimes qargi ships.
- `gh` and the cloud CLI are optional: the first for publishing a release, the second only if you use cloud agents.

## 2. Install for your user

```bash
git clone https://github.com/rett/qargi.git
cd qargi
./install.sh --user
```

This links the skills into `~/.claude/skills`, the command into `~/.local/bin`, the manual page and the shell completions (bash, zsh, fish) into your user directories, and adds the baseline packs to your pack library without linking any of them. It records what it installed in `~/.qargi/config/install.json`.

The links point at the checkout, so a `git pull` there updates everything. To install real files instead, add the copy flag; the whole tool is then copied to `~/.local/share/qargi`.

```bash
./install.sh --user --copy
```

An existing real file or directory is never replaced unless you add the force flag. Install at one level only: the user level, or one project.

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
./install.sh --project /path/to/repo
```

The skills go into that repository's `.claude` directory and are hidden from git through the repository's local exclude file. The command is always user-level, so install `--user` first. The installer refuses when any of those paths is already tracked.

## 5. Update

If you installed with links, update the checkout and run the installer again:

```bash
git pull
./install.sh --user
```

If the installed tool is a root-owned checkout that `install.sh` recorded, `qargi upgrade` moves it to a newer branch or tag. It prints the commits and files that would change and a plan token, and applies only that plan:

```bash
qargi upgrade --tag TAG
qargi upgrade --tag TAG --plan TOKEN --approved "upgrade to TAG"
```

Afterwards `qargi agent list` shows members whose definition changed as `STALE`; refresh each with `qargi agent refresh NAME` once you have looked at it.

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
