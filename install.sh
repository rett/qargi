#!/usr/bin/env bash
# Install or remove qargi: the qargi-* skills, the `qargi` command, its manual page and its
# bash, zsh and fish completion. It installs no agent definition: you create the members
# (the local workers) yourself, with the names you choose: qargi agent add NAME.
#
#   install.sh --user [--copy] [--force]          skills in the runtime's user skills directory, command in
#                                                 ~/.local/bin, man page and completions (bash, zsh under
#                                                 ~/.local/share, fish under ~/.config/fish)
#   install.sh --project DIR [--copy] [--force]   skills in the runtime's project skills directory of DIR only
#   install.sh --user|--project DIR --uninstall
#   --runtime NAME                                the runtime whose session loads the lead skills (default claude-code);
#                                                 its skills directories come from its definition (lib/providers/NAME.json,
#                                                 `qargi provider layout`), none is built in here. A runtime with no
#                                                 skills directory (or an unknown one) is refused.
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
# tracker and profiles are always per user (~/.qargi). Install at one level only.
#
# Every path an install writes (links, copied files and the directories it had to create) is recorded in an install manifest
# next to install.json (<live config>/install.manifest for --user, project-N.manifest for --project DIR). --uninstall removes
# exactly what the manifest lists and nothing else: a file you added inside a copied skill is kept, and so is ~/.qargi. An
# install without a manifest (made by an older install.sh) cannot be told apart from your own files, so --uninstall says so and
# removes only the fixed paths this script writes, and only with --force.
#
# --user also records the tool it installed in <live config>/install.json (~/.qargi/config, or QARGI_CONF /
# QARGI_HOME when set; --uninstall removes it). A checkout run from any other place is then a dev run that keeps its data
# in its own .qargi directory (see README, Running a branch checkout).
set -eu

here=$(cd "$(dirname "$0")" && pwd -P)
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null || { echo "qargi: install.sh needs python3 3.11 or newer" >&2; exit 1; }
# what --copy puts in the data directory: the tool's directories and files (tests/test_tool_copy.sh keeps this list covering TOOL_DIRS of
# tests/hermetic.sh, the directories a modified copy of the tool needs to run, and the end of tests/test_install.sh runs the copy)
tool_dirs="bin lib provision contract canon catalog roles methodologies packs skills agents examples man completions VERSION"
skills="qargi-task qargi-project qargi-instances qargi-provision qargi-memory qargi-packs qargi-providers qargi-verify qargi-flow qargi-team qargi-session"
proj='' mode='' copy='' force='' uninstall='' runtime=claude-code
while [ $# -gt 0 ]; do
  case $1 in
    --user) mode=user; shift;;
    --project) [ $# -ge 2 ] || { echo "--project needs DIR" >&2; exit 2; }
               mode=project; proj=$2; shift 2;;
    --runtime) [ $# -ge 2 ] || { echo "--runtime needs NAME" >&2; exit 2; }
               runtime=$2; shift 2;;
    --copy) copy=1; shift;;
    --force) force=1; shift;;
    --uninstall) uninstall=1; shift;;
    *) echo "usage: install.sh --user|--project DIR [--copy] [--force] [--uninstall] [--runtime NAME]" >&2; exit 2;;
  esac
done
[ -n "$mode" ] || { echo "choose --user or --project DIR" >&2; exit 2; }
case $runtime in ''|*[!a-z0-9-]*) echo "qargi: install.sh: bad runtime name '$runtime'" >&2; exit 2;; esac

# where this runtime keeps its skills: the layout of its definition, never a path written here
layout_field() {   # layout_field FIELD WOULD: the field, or a clear refusal (no such runtime, or the runtime has no such directory)
  python3 "$here/lib/provider.py" layout "$runtime" "$1" --would "$2" || { echo "qargi: install.sh: cannot take $1 from the definition of runtime '$runtime' (--runtime NAME chooses another)" >&2; exit 1; }
}

data=${XDG_DATA_HOME:-$HOME/.local/share}/qargi
cmd=$HOME/.local/bin/qargi
xdg=${XDG_DATA_HOME:-$HOME/.local/share}
manpage=$xdg/man/man1/qargi.1
completion=$xdg/bash-completion/completions/qargi
zshcomp=$xdg/zsh/site-functions/_qargi
fishcomp=${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions/qargi.fish
src=$here
liveconf=${QARGI_CONF:-${QARGI_HOME:-$HOME/.qargi}/config}   # where the install record goes: the live location, never a dev sandbox
[ -z "$copy" ] || [ "$mode" != user ] || src=$data   # where links/copies come from

psk=
if [ "$mode" = user ]; then
  skdir=$(layout_field user_skills_dir "install the skills") || exit 1
  mf=$liveconf/install.manifest
else
  psk=$(layout_field project_skills_dir "install the skills") || exit 1
  skdir=$proj/$psk
  [ -n "$uninstall" ] || mkdir -p "$proj"
  mf=$liveconf/project-$( (cd "$proj" 2>/dev/null && pwd -P || printf %s "$proj") | cksum | cut -d' ' -f1).manifest
fi

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

paths=()
for s in $skills; do paths+=("$skdir/$s"); done
[ "$mode" != user ] || paths+=("$cmd" "$manpage" "$completion" "$zshcomp" "$fishcomp")

exclude_file=
if [ "$mode" = project ] && git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
  exclude_file=$(git -C "$proj" rev-parse --git-path info/exclude)
  case $exclude_file in /*) ;; *) exclude_file=$proj/$exclude_file;; esac
  pat=$(printf '%s|' $skills); pat=${pat%|}
  pagents=$(python3 "$here/lib/provider.py" layout "$runtime" project_agents_dir 2>/dev/null || true)
  tracked=$(git -C "$proj" ls-files -- "$psk" ${pagents:+"$pagents"} | grep -E "(^|/)($pat)(/|\\.md\$)" || true)
  if [ -n "$tracked" ]; then
    echo "refusing: qargi paths are tracked in $proj; remove them from the repository first" >&2; exit 1
  fi
fi
entries=
if [ "$mode" = project ]; then
  for s in $skills; do entries="$entries/$psk/$s
"; done
fi

# ---- the install manifest: one line per path an install wrote, "KIND<TAB>PATH"
#   L a link we made         C a file or directory we copied (the root of a copy)
#   f a file inside a copy   d a directory inside a copy      P a parent directory we had to create
rec() { printf '%s\t%s\n' "$1" "$2" >> "$mf"; }
rec_contents() {   # rec_contents DIR: what a copy put inside DIR
  local x
  while IFS= read -r x; do rec d "$x"; done < <(find "$1" -mindepth 1 -type d)
  while IFS= read -r x; do rec f "$x"; done < <(find "$1" -mindepth 1 ! -type d)
}
mk() {   # mk DIR: mkdir -p, recording each directory it created
  local d=$1 x; local -a made=()
  while [ ! -d "$d" ] && [ "$d" != / ] && [ "$d" != . ]; do made=("$d" ${made[@]+"${made[@]}"}); d=$(dirname "$d"); done
  mkdir -p "$1"
  for x in ${made[@]+"${made[@]}"}; do rec P "$x"; done
}
# ours PATH: PATH and everything under it is in the manifest of the earlier install (so it is not something of yours)
ours() {
  [ -f "$mf" ] || return 1
  cut -f2 "$mf" | LC_ALL=C sort > "$tmp/paths"
  [ -z "$(find "$1" 2>/dev/null | LC_ALL=C sort | LC_ALL=C comm -23 - "$tmp/paths")" ]
}
# remove_recorded FILE say|quiet: remove exactly the paths FILE lists; a path no longer what was installed is kept and said
remove_recorded() {
  local f=$1 mode_say=$2 k p d dk
  say() { [ "$mode_say" = say ] || return 0; echo "$1"; }
  : > "$tmp/dirs"
  while IFS=$'\t' read -r k p; do
    [ -n "$p" ] || continue
    case $k in
      L) if [ -L "$p" ]; then rm -f "$p"; say "removed $p"; elif [ -e "$p" ]; then say "kept $p (no longer the link the install made)"; fi;;
      f) if [ -f "$p" ] || [ -L "$p" ]; then rm -f "$p"; fi;;
      C) if [ -d "$p" ] && [ ! -L "$p" ]; then printf '%s\t%s\n' "$p" "$k" >> "$tmp/dirs"
         elif [ -f "$p" ] || [ -L "$p" ]; then rm -f "$p"; say "removed $p"; fi;;
      d|P) printf '%s\t%s\n' "$p" "$k" >> "$tmp/dirs";;
    esac
  done < "$f"
  # the directories, the deepest first; the bytecode Python wrote inside a copied directory is not in the manifest and goes with it
  while IFS=$'\t' read -r d dk; do
    [ -d "$d" ] && [ ! -L "$d" ] || continue
    [ "$dk" = P ] || rm -rf "${d:?}/__pycache__"
    if rmdir "$d" 2>/dev/null; then [ "$dk" != C ] || say "removed $d"
    elif [ "$dk" = C ]; then say "kept $d (it holds files the install did not write)"; fi
  done < <(LC_ALL=C sort -r "$tmp/dirs")
}

if [ -n "$uninstall" ]; then
  if [ -f "$mf" ]; then
    remove_recorded "$mf" say
    rm -f "$mf"
  else
    echo "qargi: no install manifest at $mf, so I cannot tell what an earlier install wrote (it predates the manifest, or was removed)"
    legacy=("${paths[@]}")
    if [ "$mode" = user ] && [ -f "$liveconf/install.json" ]; then
      root=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("tool_root",""))' "$liveconf/install.json" 2>/dev/null || true)
      [ -z "$root" ] || [ "$root" != "$data" ] || [ "$data" = "$here" ] || legacy+=("$data")
    fi
    found=()
    for p in "${legacy[@]}"; do if [ -e "$p" ] || [ -L "$p" ]; then found+=("$p"); fi; done
    if [ ${#found[@]} -eq 0 ]; then echo "nothing of the fixed paths is there"
    elif [ -z "$force" ]; then
      echo "nothing removed; these fixed paths exist and may be yours:"; printf '  %s\n' "${found[@]}"
      echo "--uninstall --force removes exactly them (the skills, the command, the man page, the completions and, when install.json says it was installed there, $data)"
      exit 1
    else
      for p in "${found[@]}"; do rm -rf "$p"; echo "removed $p"; done
    fi
  fi
  if [ -n "$exclude_file" ] && [ -f "$exclude_file" ]; then
    grep -v -x -F "$entries" "$exclude_file" > "$exclude_file.tmp" || true
    mv "$exclude_file.tmp" "$exclude_file"
  fi
  [ "$mode" != user ] || [ ! -f "$liveconf/install.json" ] || { rm -f "$liveconf/install.json"; echo "removed $liveconf/install.json"; }
  exit 0
fi

# an existing real file or directory is yours unless the earlier install recorded it (and you added nothing inside it)
for p in "${paths[@]}"; do
  if [ -e "$p" ] && [ ! -L "$p" ] && [ -z "$force" ] && ! ours "$p"; then
    echo "refusing to replace existing $p (use --force)" >&2; exit 1
  fi
done

# a reinstall starts from a clean slate: what the earlier install wrote is removed first (a copy install made over a link install leaves nothing behind)
mkdir -p "$liveconf"; chmod 700 "$liveconf"
if [ -f "$mf" ]; then remove_recorded "$mf" quiet; fi
: > "$mf"; chmod 600 "$mf"

if [ -n "$copy" ] && [ "$mode" = user ]; then
  rm -rf "$data"; mk "$(dirname "$data")"; mkdir "$data"; rec C "$data"
  for d in $tool_dirs; do cp -r "$here/$d" "$data/"; done
  rec_contents "$data"
  echo "copied the tool to $data"
fi

mk "$skdir"
for s in $skills; do
  rm -rf "${skdir:?}/$s"
  if [ -n "$copy" ]; then rec C "$skdir/$s"; cp -r "$src/skills/$s" "$skdir/$s"; rec_contents "$skdir/$s"
  else ln -s "$src/skills/$s" "$skdir/$s"; rec L "$skdir/$s"; fi
done
kind="symlinks to $here"; [ -z "$copy" ] || kind=copy
if [ "$mode" = user ]; then
  for d in "$(dirname "$cmd")" "$(dirname "$manpage")" "$(dirname "$completion")" "$(dirname "$zshcomp")" "$(dirname "$fishcomp")"; do mk "$d"; done
  rm -f "$cmd" "$manpage" "$completion" "$zshcomp" "$fishcomp"
  ln -s "$src/bin/qargi" "$cmd"; rec L "$cmd"
  if [ -n "$copy" ]; then
    cp "$src/man/qargi.1" "$manpage"; cp "$src/completions/qargi.bash" "$completion"; cp "$src/completions/_qargi" "$zshcomp"; cp "$src/completions/qargi.fish" "$fishcomp"
    for p in "$manpage" "$completion" "$zshcomp" "$fishcomp"; do rec C "$p"; done
  else
    ln -s "$src/man/qargi.1" "$manpage"; ln -s "$src/completions/qargi.bash" "$completion"; ln -s "$src/completions/_qargi" "$zshcomp"; ln -s "$src/completions/qargi.fish" "$fishcomp"
    for p in "$manpage" "$completion" "$zshcomp" "$fishcomp"; do rec L "$p"; done
  fi
  echo "installed skills in $skdir, command at $cmd, man page at $manpage ($kind)"
  echo "completion: bash $completion, zsh $zshcomp, fish $fishcomp"
  echo "recorded what was written in $mf (--uninstall removes exactly that)"
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg r "$(cd "$src" && pwd -P)" --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg v "$(cat "$src/VERSION")" '{tool_root:$r, installed_at:$t, version:$v}' > "$liveconf/install.json"
    chmod 600 "$liveconf/install.json"
    echo "recorded the install in $liveconf/install.json (a checkout run from elsewhere keeps its data in its own .qargi)"
    # the baseline packs go into the library (only the missing ones, unlinked: an unlinked pack reaches nobody)
    "$src/bin/qargi" packs seed --install || echo "note: the baseline packs were not seeded; run: qargi packs seed" >&2
  else
    echo "note: jq is not installed, so the install was not recorded in $liveconf/install.json" >&2
  fi
  ! command -v zsh >/dev/null 2>&1 || echo "note: for zsh add this to ~/.zshrc before compinit: fpath=($(dirname "$zshcomp") \$fpath)" >&2
  command -v man >/dev/null 2>&1 && ! man -w qargi >/dev/null 2>&1 && echo "note: man does not find it yet; add $xdg/man to MANPATH (or: man -l $manpage)" >&2 || true
  echo "note: bash loads the completion in new shells when bash-completion is installed; otherwise add to ~/.bashrc: source $completion" >&2
else
  command -v qargi >/dev/null 2>&1 || echo "note: the qargi command is not on PATH; run: install.sh --user" >&2
  echo "installed skills in $skdir ($kind)"
fi

echo "next: create the members that do the work, with names you choose, for example:"
echo "  qargi agent add worker --project NAME    (and reviewer: qargi agent add reviewer --project NAME)"

if [ -n "$exclude_file" ]; then
  mkdir -p "$(dirname "$exclude_file")"; touch "$exclude_file"
  printf '%s\n' "$entries" | while IFS= read -r line; do
    [ -n "$line" ] || continue
    grep -qx -F "$line" "$exclude_file" || printf '%s\n' "$line" >> "$exclude_file"
  done
  echo "hidden from git via $exclude_file (local only, nothing committed)"
fi
