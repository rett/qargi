#!/usr/bin/env bash
# Install or remove qargi: the qargi-* skills, the local subagent, the `qargi` command,
# its manual page and its bash, zsh and fish completion.
#
#   install.sh --user [--copy] [--force]          skills in ~/.claude, command in ~/.local/bin,
#                                                 man page and completions (bash, zsh under ~/.local/share,
#                                                 fish under ~/.config/fish)
#   install.sh --project DIR [--copy] [--force]   skills and subagent in DIR/.claude only
#   install.sh --user|--project DIR --uninstall
#
# By default everything is a symlink to this checkout (updates follow `git pull`).
# --copy installs real files: for --user the whole tool is copied to
# $XDG_DATA_HOME/qargi (default ~/.local/share/qargi) and the skills and
# command come from there; for --project the skill files are copied (the command
# is user-level either way, so install --user first). An existing real file or
# directory is never replaced without --force.
# A --project install never touches the repository's committed files: the paths
# are hidden through the repository's local .git/info/exclude, and the install
# is refused if any of them is already tracked. The instance registry, session
# tracker and profiles are always per user (XDG dirs). Install at one level only.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
skills="qargi-task qargi-project qargi-instances qargi-provision qargi-memory qargi-packs qargi-review qargi-team"
target='' proj='' mode='' copy='' force='' uninstall=''
while [ $# -gt 0 ]; do
  case $1 in
    --user) mode=user; target=$HOME/.claude; shift;;
    --project) [ $# -ge 2 ] || { echo "--project needs DIR" >&2; exit 2; }
               mode=project; proj=$2; target=$2/.claude; shift 2;;
    --copy) copy=1; shift;;
    --force) force=1; shift;;
    --uninstall) uninstall=1; shift;;
    *) echo "usage: install.sh --user|--project DIR [--copy] [--force] [--uninstall]" >&2; exit 2;;
  esac
done
[ -n "$mode" ] || { echo "choose --user or --project DIR" >&2; exit 2; }

data=${XDG_DATA_HOME:-$HOME/.local/share}/qargi
cmd=$HOME/.local/bin/qargi
xdg=${XDG_DATA_HOME:-$HOME/.local/share}
manpage=$xdg/man/man1/qargi.1
completion=$xdg/bash-completion/completions/qargi
zshcomp=$xdg/zsh/site-functions/_qargi
fishcomp=${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions/qargi.fish
src=$here
agents="qargi-dev qargi-docs qargi-review qargi-test"
[ -z "$copy" ] || [ "$mode" != user ] || src=$data   # where links/copies come from

paths=()
for s in $skills; do paths+=("$target/skills/$s"); done
for a in $agents; do paths+=("$target/agents/$a.md"); done
[ "$mode" != user ] || paths+=("$cmd" "$manpage" "$completion" "$zshcomp" "$fishcomp")

exclude_file=
if [ "$mode" = project ] && git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
  exclude_file=$(git -C "$proj" rev-parse --git-path info/exclude)
  case $exclude_file in /*) ;; *) exclude_file=$proj/$exclude_file;; esac
  tracked=$(git -C "$proj" ls-files -- .claude/skills .claude/agents | grep -E '(^|/)(dev|qargi|qargi-task|qargi-project|qargi-instances|qargi-provision|qargi-memory|qargi-packs|qargi-review|qargi-team)(/|\.md$)' || true)
  if [ -n "$tracked" ]; then
    echo "refusing: qargi paths are tracked in $proj; remove them from the repository first" >&2; exit 1
  fi
fi
entries=
for s in $skills; do entries="$entries/.claude/skills/$s
"; done
for a in $agents; do entries="$entries/.claude/agents/$a.md
"; done

if [ -n "$uninstall" ]; then
  if [ -n "$exclude_file" ] && [ -f "$exclude_file" ]; then
    grep -v -x -F "$entries" "$exclude_file" > "$exclude_file.tmp" || true
    mv "$exclude_file.tmp" "$exclude_file"
  fi
  for old in qargi dev; do [ ! -L "$target/skills/$old" ] || rm -f "$target/skills/$old"; done
  for p in "${paths[@]}"; do
    if [ -L "$p" ] || { [ -e "$p" ] && [ -n "$force" ]; }; then rm -rf "$p"; echo "removed $p"
    elif [ -e "$p" ]; then echo "kept $p (not a symlink; use --force to remove)"; fi
  done
  exit 0
fi

for p in "${paths[@]}"; do
  if [ -e "$p" ] && [ ! -L "$p" ] && [ -z "$force" ]; then
    echo "refusing to replace existing $p (use --force)" >&2; exit 1
  fi
done

if [ -n "$copy" ] && [ "$mode" = user ]; then
  rm -rf "$data"; mkdir -p "$data"
  cp -r "$here/bin" "$here/lib" "$here/provision" "$here/skills" "$here/agents" "$here/examples" "$here/man" "$here/completions" "$here/VERSION" "$data/"
  echo "copied the tool to $data"
fi

mkdir -p "$target/skills" "$target/agents"
# the dispatch skill had other names before: drop leftover symlinks
for old in qargi dev; do [ ! -L "$target/skills/$old" ] || rm -f "$target/skills/$old"; done
for s in $skills; do
  rm -rf "${target:?}/skills/$s"
  if [ -n "$copy" ]; then cp -r "$src/skills/$s" "$target/skills/$s"; else ln -s "$src/skills/$s" "$target/skills/$s"; fi
done
for a in $agents; do
  rm -rf "$target/agents/$a.md"
  if [ -n "$copy" ]; then cp "$src/agents/$a.md" "$target/agents/$a.md"; else ln -s "$src/agents/$a.md" "$target/agents/$a.md"; fi
done
kind="symlinks to $here"; [ -z "$copy" ] || kind=copy
if [ "$mode" = user ]; then
  mkdir -p "$(dirname "$cmd")" "$(dirname "$manpage")" "$(dirname "$completion")" "$(dirname "$zshcomp")" "$(dirname "$fishcomp")"
  rm -f "$cmd" "$manpage" "$completion" "$zshcomp" "$fishcomp"
  ln -s "$src/bin/qargi" "$cmd"
  if [ -n "$copy" ]; then
    cp "$src/man/qargi.1" "$manpage"; cp "$src/completions/qargi.bash" "$completion"; cp "$src/completions/_qargi" "$zshcomp"; cp "$src/completions/qargi.fish" "$fishcomp"
  else
    ln -s "$src/man/qargi.1" "$manpage"; ln -s "$src/completions/qargi.bash" "$completion"; ln -s "$src/completions/_qargi" "$zshcomp"; ln -s "$src/completions/qargi.fish" "$fishcomp"
  fi
  echo "installed skills and subagent in $target, command at $cmd, man page at $manpage ($kind)"
  echo "completion: bash $completion, zsh $zshcomp, fish $fishcomp"
  ! command -v zsh >/dev/null 2>&1 || echo "note: for zsh add this to ~/.zshrc before compinit: fpath=($(dirname "$zshcomp") \$fpath)" >&2
  command -v man >/dev/null 2>&1 && ! man -w qargi >/dev/null 2>&1 && echo "note: man does not find it yet; add $xdg/man to MANPATH (or: man -l $manpage)" >&2 || true
  echo "note: bash loads the completion in new shells when bash-completion is installed; otherwise add to ~/.bashrc: source $completion" >&2
else
  command -v qargi >/dev/null 2>&1 || echo "note: the qargi command is not on PATH; run: install.sh --user" >&2
  echo "installed skills and subagent in $target ($kind)"
fi

if [ -n "$exclude_file" ]; then
  mkdir -p "$(dirname "$exclude_file")"; touch "$exclude_file"
  printf '%s\n' "$entries" | while IFS= read -r line; do
    [ -n "$line" ] || continue
    grep -qx -F "$line" "$exclude_file" || printf '%s\n' "$line" >> "$exclude_file"
  done
  echo "hidden from git via $exclude_file (local only, nothing committed)"
fi
