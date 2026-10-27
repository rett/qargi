#!/usr/bin/env bash
# Install or remove dev-agent at user level or in one repository.
#
#   install.sh --user [--copy] [--force]
#   install.sh --project DIR [--copy] [--force]
#   install.sh --user|--project DIR --uninstall
#
# User level puts the skill in ~/.claude/skills and the local subagent in
# ~/.claude/agents, so every project sees it. Project level puts them in
# DIR/.claude, so only that repository does. By default both are symlinks to
# this checkout (updates follow `git pull`); --copy installs real files, which
# is what to use when the project's .claude directory is committed or shared.
# An existing real directory or file is never overwritten without --force.
# A --project install never touches the repository's committed files: the two
# paths are hidden through the repository's local .git/info/exclude (not a
# tracked file), and the install is refused if either path is already tracked.
# The instance registry and session tracker are always per user (XDG dirs),
# whichever mode installs the skill; install at only one level, not both.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
target= proj= copy= force= uninstall=
while [ $# -gt 0 ]; do
  case $1 in
    --user) target=$HOME/.claude; shift;;
    --project) [ $# -ge 2 ] || { echo "--project needs DIR" >&2; exit 2; }
               proj=$2; target=$2/.claude; shift 2;;
    --copy) copy=1; shift;;
    --force) force=1; shift;;
    --uninstall) uninstall=1; shift;;
    *) echo "usage: install.sh --user|--project DIR [--copy] [--force] [--uninstall]" >&2; exit 2;;
  esac
done
[ -n "$target" ] || { echo "choose --user or --project DIR" >&2; exit 2; }

skill=$target/skills/dev-agent
agent=$target/agents/dev-agent.md

exclude_file=
if [ -n "$proj" ] && git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
  exclude_file=$(git -C "$proj" rev-parse --git-path info/exclude)
  case $exclude_file in /*) ;; *) exclude_file=$proj/$exclude_file;; esac
  if [ -n "$(git -C "$proj" ls-files -- .claude/skills/dev-agent .claude/agents/dev-agent.md)" ]; then
    echo "refusing: dev-agent paths are tracked in $proj; remove them from the repository first" >&2; exit 1
  fi
fi
entries='/.claude/skills/dev-agent
/.claude/agents/dev-agent.md'

if [ -n "$uninstall" ]; then
  if [ -n "$exclude_file" ] && [ -f "$exclude_file" ]; then
    grep -v -x -F "$entries" "$exclude_file" > "$exclude_file.tmp" || true
    mv "$exclude_file.tmp" "$exclude_file"
  fi
  for p in "$skill" "$agent"; do
    if [ -L "$p" ] || { [ -e "$p" ] && [ -n "$force" ]; }; then rm -rf "$p"; echo "removed $p"
    elif [ -e "$p" ]; then echo "kept $p (not a symlink; use --force to remove)"; fi
  done
  exit 0
fi

for p in "$skill" "$agent"; do
  if [ -e "$p" ] && [ ! -L "$p" ] && [ -z "$force" ]; then
    echo "refusing to replace existing $p (use --force)" >&2; exit 1
  fi
done
mkdir -p "$target/skills" "$target/agents"
rm -rf "$skill" "$agent"
if [ -n "$copy" ]; then
  cp -r "$here/skill" "$skill"
  cp -r "$here/provision" "$skill/provision"   # provision.sh looks for templates here
  cp "$here/agents/dev-agent.md" "$agent"
  echo "copied into $target (skills/dev-agent, agents/dev-agent.md)"
else
  ln -s "$here/skill" "$skill"
  ln -s "$here/agents/dev-agent.md" "$agent"
  echo "linked into $target (symlinks to $here)"
fi
if [ -n "$exclude_file" ]; then
  mkdir -p "$(dirname "$exclude_file")"
  touch "$exclude_file"
  printf '%s\n' "$entries" | while IFS= read -r line; do
    grep -qx -F "$line" "$exclude_file" || printf '%s\n' "$line" >> "$exclude_file"
  done
  echo "hidden from git via $exclude_file (local only, nothing committed)"
fi
