#!/usr/bin/env bash
# Install or remove qargi: the qargi-* skills, the `qargi` command, its manual page and its
# bash, zsh and fish completion. It installs no agent definition: you create the members
# (the local workers) yourself, with the names you choose: qargi agent add NAME.
#
#   install.sh --user [--runtime NAME] [--copy] [--force]   the lead skills in the runtime's user skills directory, the command in
#                                                 ~/.local/bin, man page and completions (bash, zsh under ~/.local/share, fish under
#                                                 ~/.config/fish)
#   install.sh --project DIR [--runtime NAME] [--copy] [--force]   the skills in the runtime's project skills directory of DIR only
#   install.sh --user|--project DIR --uninstall [--runtime NAME]
#   --runtime NAME                                the runtime whose session loads the lead skills; without it every runtime
#                                                 already installed (at that level, in that project) is refreshed, and
#                                                 claude-code is installed when none is. Its skills directories come from its
#                                                 definition (lib/providers/NAME.json, `qargi provider layout`), none is built in
#                                                 here. A runtime with no skills directory (or an unknown one) is refused; an
#                                                 installed runtime whose definition is gone is skipped with a note.
#
# Runtimes install side by side: an install of one runtime leaves the skills of the others as they are, and the command, man page and
# completions are shared by them. --uninstall --runtime NAME removes one runtime; --uninstall alone removes every runtime installed (it
# lists them first); the shared part goes with the last one. The user runtimes come from one tool, all linked or all copied: --runtime NAME
# from another tool or in the other mode is refused while another runtime is installed (install.sh --user [--copy] without --runtime moves
# them all), and a --user --copy run copies every installed runtime again, since it rewrites the tool copy they come from.
#
# By default everything is a symlink to this checkout (updates follow `git pull`).
# --copy installs real files: for --user the whole tool is copied to
# $XDG_DATA_HOME/qargi (default ~/.local/share/qargi) and the skills and
# command come from there; for --project the skill files are copied (the command
# is user-level either way, so install --user first). An existing real file or
# directory, or a link no install recorded, is never replaced without --force; a link already pointing where the install would point it is
# left as it is (and recorded).
# A --project install never touches the repository's committed files: the paths
# are hidden through the repository's local .git/info/exclude, and the install
# is refused if any of them is already tracked. The instance registry, session
# tracker and profiles are always per user (~/.qargi). The user install and the installs in projects stand side by side, each with its
# own records, installed and removed on its own.
#
# Every path an install writes (links, copied files and the directories it had to create) is recorded in an install manifest in
# <live config>/install.d, before it is written: runtime-NAME.manifest for the skills of a runtime, shared.manifest for the command, man page,
# completions and the --copy tool, project-N-NAME.manifest for the skills of a runtime in project DIR. lib/install_record.py reads and writes
# them and checks every line it reads. --uninstall removes exactly what the manifests list and nothing else: a file you added inside a copied
# skill is kept, and so is ~/.qargi (the live config directory and its parents go only when the install made them and they are empty once
# the records are removed). Without a manifest --uninstall removes nothing and says so (exit 1), with or without --force. A run holds
# <live config>/install.lock while it reads or changes the records. An install.manifest or project-N.manifest of qargi 0.3.1 in the live
# config directory is not read and not removed (qargi doctor warns of it).
#
# --user also records the tool it installed in <live config>/install.json (~/.qargi/config, or QARGI_CONF /
# QARGI_HOME when set; the uninstall of the last runtime removes it). A checkout run from any other place is then a dev run that keeps its data
# in its own .qargi directory (see docs/install-and-upgrade/README.md, Running a branch checkout).
set -eu

here=$(cd "$(dirname "$0")" && pwd -P)
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null || { echo "qargi: install.sh needs python3 3.11 or newer" >&2; exit 1; }
# what --copy puts in the data directory: the tool's directories and files (tests/test_tool_copy.sh keeps this list covering TOOL_DIRS of
# tests/hermetic.sh, the directories a modified copy of the tool needs to run, and the end of tests/test_install.sh runs the copy)
tool_dirs="bin lib provision contract canon catalog roles methodologies packs skills agents examples man completions VERSION"
skills="qargi-task qargi-project qargi-instances qargi-provision qargi-memory qargi-packs qargi-providers qargi-verify qargi-flow qargi-team qargi-session"
proj='' mode='' copy='' force='' uninstall='' runtime=''
while [ $# -gt 0 ]; do
  case $1 in
    --user) mode=user; shift;;
    --project) [ $# -ge 2 ] || { echo "--project needs DIR" >&2; exit 2; }
               mode=project; proj=$2; shift 2;;
    --runtime) [ $# -ge 2 ] || { echo "--runtime needs NAME" >&2; exit 2; }
               runtime=$2; shift 2
               case $runtime in ''|*[!a-z0-9-]*) echo "qargi: install.sh: bad runtime name '$runtime'" >&2; exit 2;; esac;;
    --copy) copy=1; shift;;
    --force) force=1; shift;;
    --uninstall) uninstall=1; shift;;
    *) echo "usage: install.sh --user|--project DIR [--runtime NAME] [--copy] [--force] [--uninstall]" >&2; exit 2;;
  esac
done
[ -n "$mode" ] || { echo "choose --user or --project DIR" >&2; exit 2; }

records() { python3 -I "$here/lib/install_record.py" "$@"; }
# where a runtime keeps its skills: the layout of its definition, never a path written here
layout_of() {   # layout_of NAME FIELD: the field, or a clear refusal (no such runtime, or the runtime has no such directory) and status 1
  python3 "$here/lib/provider.py" layout "$1" "$2" --would "install the skills" || { echo "qargi: install.sh: cannot take $2 from the definition of runtime '$1' (--runtime NAME chooses another)" >&2; return 1; }
}
commas() { local out='' x; for x in "$@"; do out="${out:+$out, }$x"; done; printf '%s' "$out"; }

data=${XDG_DATA_HOME:-$HOME/.local/share}/qargi
cmd=$HOME/.local/bin/qargi
xdg=${XDG_DATA_HOME:-$HOME/.local/share}
manpage=$xdg/man/man1/qargi.1
completion=$xdg/bash-completion/completions/qargi
zshcomp=$xdg/zsh/site-functions/_qargi
fishcomp=${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions/qargi.fish
src=$here
liveconf=${QARGI_CONF:-${QARGI_HOME:-$HOME/.qargi}/config}   # where the install records go: the live location, never a dev sandbox
rdir=$liveconf/install.d
[ -z "$copy" ] || [ "$mode" != user ] || src=$data   # where links/copies come from

key=
if [ "$mode" = project ]; then
  [ -n "$uninstall" ] || mkdir -p "$proj"
  key=$( (cd "$proj" 2>/dev/null && pwd -P || printf %s "$proj") | cksum | cut -d' ' -f1)   # names the records of this project directory
  if real=$(cd "$proj" 2>/dev/null && pwd -P); then proj=$real; fi
fi
mfile() { if [ "$mode" = user ]; then printf '%s' "$rdir/runtime-$1.manifest"; else printf '%s' "$rdir/project-$key-$1.manifest"; fi; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

exclude_file=
if [ "$mode" = project ] && git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
  exclude_file=$(git -C "$proj" rev-parse --git-path info/exclude)
  case $exclude_file in /*) ;; *) exclude_file=$proj/$exclude_file;; esac
fi

# hold the lock of the records for the rest of the run: another install.sh waits a few seconds for it, then gives up. The lock file is never
# opened through a link. The uninstall of the last record removes it while it is held, so a run that waited on the removed file finds, once
# it holds that one, that the path names another file, and takes the lock again at the path.
lock() {
  local f=$liveconf/install.lock n
  for n in 1 2 3; do
    if [ -L "$f" ] || { [ -e "$f" ] && [ ! -f "$f" ]; }; then
      echo "qargi: install.sh: $f is a link or not a regular file, so it is not opened; nothing was changed: move it aside and run again" >&2; exit 1
    fi
    exec 9>>"$f" || { echo "qargi: install.sh: cannot open $f (another install may have removed $liveconf); nothing was changed" >&2; exit 1; }
    chmod 600 "$f"
    flock -w 5 9 || { echo "qargi: install.sh: another install is running (it holds $f); nothing was changed, try again once it is done" >&2; exit 1; }
    [ "$f" -ef "/proc/$$/fd/9" ] && return 0
    exec 9>&-
  done
  echo "qargi: install.sh: $f was removed again each time this run took it ($n times: other installs are running); nothing was changed, try again once they are done" >&2
  exit 1
}
# the records as they are: RUNTIMES (the user runtimes recorded), SHARED (the shared manifest, or empty), PRUNTIMES (the runtimes recorded for
# this project directory) and REC_ROOT, REC_SOURCE (the tool install.json records). A record with a line that fails its check stops the run here.
read_state() {
  local st k a b
  RUNTIMES='' SHARED='' PRUNTIMES='' REC_ROOT='' REC_SOURCE=''
  st=$(records state --conf "$liveconf" --data "$data" ${key:+--project-key "$key"}) || exit 1
  while IFS=$'\t' read -r k a b; do
    case $k in
      runtime) RUNTIMES="${RUNTIMES:+$RUNTIMES }$a";;
      shared) SHARED=$a;;
      project) PRUNTIMES="${PRUNTIMES:+$PRUNTIMES }$a";;
      record) REC_ROOT=$a; REC_SOURCE=$b;;
    esac
  done <<<"$st"
}
no_record() {
  echo "qargi: no install manifest in $rdir${1:+ for $1}, so nothing is recorded to remove and nothing was removed (the manifests list every path an install wrote; without them your files cannot be told from ours)" >&2
  exit 1
}
if [ -n "$uninstall" ]; then
  [ -d "$liveconf" ] || no_record ""
  lock
  [ -d "$rdir" ] || { rm -f "$liveconf/install.lock"; no_record ""; }
  read_state
  if [ "$mode" = user ]; then have=$RUNTIMES; where=''; else have=$PRUNTIMES; where=" in $proj"; fi
  if [ -n "$runtime" ]; then
    case " $have " in
      *" $runtime "*) drop=$runtime;;
      *) echo "qargi: install.sh: runtime $runtime is not installed$where (installed: ${have:-none}); nothing was removed" >&2; exit 1;;
    esac
  else
    drop=$have
  fi
  files=() left=''
  for r in $have; do
    case " $drop " in *" $r "*) files+=("$(mfile "$r")");; *) left="${left:+$left }$r";; esac
  done
  last=''
  if [ "$mode" = user ] && [ -z "$left" ]; then last=1; [ -z "$SHARED" ] || files+=("$SHARED"); fi
  [ ${#files[@]} -gt 0 ] || no_record "$proj"
  # shellcheck disable=SC2086  # the names are words
  [ -n "$runtime" ] || [ -z "$drop" ] || echo "uninstalling the runtimes installed$where: $(commas $drop)"
  : > "$tmp/excl"
  if [ "$mode" = project ]; then
    for f in "${files[@]}"; do records excludes "$f" >> "$tmp/excl" || exit 1; done
  fi
  # the exclude file is rewritten while the lock is held: the engine removes the lock file with the last record, and a run that took the
  # lock at once could append to the file between the read and the mv here, and the mv would drop its lines. A refused uninstall puts the
  # lines back.
  if [ -n "$exclude_file" ] && [ -f "$exclude_file" ]; then
    grep -v -x -F -f "$tmp/excl" "$exclude_file" > "$exclude_file.tmp" || true
    mv "$exclude_file.tmp" "$exclude_file"
  fi
  if ! records uninstall --conf "$liveconf" ${last:+--drop-record} "${files[@]}"; then
    if [ -n "$exclude_file" ] && [ -f "$exclude_file" ]; then
      while IFS= read -r l; do grep -q -x -F -e "$l" "$exclude_file" || printf '%s\n' "$l" >> "$exclude_file"; done < "$tmp/excl"
    fi
    exit 1
  fi
  # shellcheck disable=SC2086
  [ -z "$left" ] || echo "still installed$where: $(commas $left)"
  exit 0
fi

# a runtime named on the command line that has no skills directory is refused before anything is written
field=user_skills_dir; [ "$mode" = user ] || field=project_skills_dir
declare -A skdir=()
[ -z "$runtime" ] || skdir[$runtime]=$(layout_of "$runtime" "$field") || exit 1

# the live config directory and the parents of it this run makes (c): an uninstall removes them once they are empty
cmade=''; d=$liveconf
while [ ! -d "$d" ] && [ "$d" != / ] && [ "$d" != . ]; do cmade="$cmade$d"$'\n'; d=$(dirname "$d"); done
mkdir -p "$liveconf"; chmod 700 "$liveconf"
undo_conf() {   # a run refused before it recorded anything leaves no lock and no config directory it made
  [ ! -d "$rdir" ] || return 0
  rm -f "$liveconf/install.lock"
  while IFS= read -r d; do [ -z "$d" ] || rmdir "$d" 2>/dev/null || true; done <<<"$cmade"
}
refuse() { echo "$1" >&2; undo_conf; exit 1; }
lock; read_state
recorded=$RUNTIMES; [ "$mode" = user ] || recorded=$PRUNTIMES

# the runtimes this run installs: the one named, else every runtime recorded (claude-code when none is)
runs=${runtime:-${recorded:-claude-code}}
how="link"; [ -z "$copy" ] || how="copy"
if [ "$mode" = user ]; then
  # one source: the user runtimes all come from the same tool, linked or copied alike. A run that would move the source while it leaves
  # another recorded runtime on the old one is refused; a run that refreshes every runtime moves them all.
  others=''
  if [ -n "$runtime" ]; then for r in $recorded; do [ "$r" = "$runtime" ] || others="${others:+$others }$r"; done; fi
  newroot=$(realpath -m "$src")
  if [ -n "$others" ] && [ -n "$REC_ROOT" ] && [ "$(realpath -m "$REC_ROOT") $REC_SOURCE" != "$newroot $how" ]; then
    # shellcheck disable=SC2086  # the names are words
    refuse "qargi: install.sh: the installed runtimes ($(commas $recorded)) come from $REC_ROOT ($REC_SOURCE); this run would install $runtime from $newroot ($how) and leave $(commas $others) behind. Run install.sh --user${copy:+ --copy} without --runtime to move them all; nothing was changed"
  fi
  # a copy rewrites the tool copy every runtime's skills come from: every recorded runtime is copied again with it
  if [ -n "$copy" ]; then for r in $recorded; do case " $runs " in *" $r "*) ;; *) runs="$runs $r";; esac; done; fi
fi
keep=''
for r in $runs; do
  if [ -z "${skdir[$r]+set}" ]; then
    case " $recorded " in *" $r "*) ;; *) skdir[$r]=$(layout_of "$r" "$field") || { undo_conf; exit 1; };; esac
    if [ -z "${skdir[$r]+set}" ] && ! skdir[$r]=$(layout_of "$r" "$field" 2>/dev/null); then
      echo "note: runtime $r is recorded but its definition has no $field now, so it was not refreshed (install.sh --$mode${proj:+ $proj} --uninstall --runtime $r removes it)" >&2
      continue
    fi
  fi
  keep="${keep:+$keep }$r"
done
runs=$keep

if [ -n "$exclude_file" ]; then
  pat=$(printf '%s|' $skills); pat=${pat%|}
  for r in $runs; do
    pagents=$(python3 "$here/lib/provider.py" layout "$r" project_agents_dir 2>/dev/null || true)
    tracked=$(git -C "$proj" ls-files -- "${skdir[$r]}" ${pagents:+"$pagents"} | grep -E "(^|/)($pat)(/|\\.md\$)" || true)
    [ -z "$tracked" ] || refuse "refusing: qargi paths are tracked in $proj; remove them from the repository first"
  done
fi

# the plan: every part this run installs, each path it writes and where it comes from (lib/install_record.py apply reads it)
plan=$tmp/plan; : > "$plan"
item() { local IFS=$'\t'; printf '%s\n' "$*" >> "$plan"; }
cdirs() { local d; while IFS= read -r d; do [ -z "$d" ] || item c "$d"; done <<<"$cmade"; }
if [ "$mode" = user ]; then
  item M "$rdir/shared.manifest" kind=shared "data=$data" "slot=$cmd" "slot=$manpage" "slot=$completion" "slot=$zshcomp" "slot=$fishcomp"
  for p in "$cmd" "$manpage" "$completion" "$zshcomp" "$fishcomp"; do item D "$(dirname "$p")"; done
  if [ -n "$copy" ]; then
    item D "$(dirname "$data")"
    # shellcheck disable=SC2086  # the list is words
    item C "$data" "$here" $tool_dirs
    item L "$cmd" "$data/bin/qargi"
    item C "$manpage" "$here/man/qargi.1"; item C "$completion" "$here/completions/qargi.bash"
    item C "$zshcomp" "$here/completions/_qargi"; item C "$fishcomp" "$here/completions/qargi.fish"
  else
    item L "$cmd" "$here/bin/qargi"; item L "$manpage" "$here/man/qargi.1"; item L "$completion" "$here/completions/qargi.bash"
    item L "$zshcomp" "$here/completions/_qargi"; item L "$fishcomp" "$here/completions/qargi.fish"
  fi
  cdirs
fi
for r in $runs; do
  sk=${skdir[$r]}
  if [ "$mode" = user ]; then item M "$(mfile "$r")" kind=runtime "name=$r" "root=$sk"
  else sk=$proj/$sk; item M "$(mfile "$r")" kind=project "name=$r" "project=$proj" "root=$sk"; cdirs; fi
  skdir[$r]=$sk
  item D "$sk"
  for s in $skills; do
    if [ -n "$copy" ]; then item C "$sk/$s" "$here/skills/$s"; else item L "$sk/$s" "$here/skills/$s"; fi
  done
done
records apply --conf "$liveconf" ${force:+--force} < "$plan" || { undo_conf; exit 1; }

# The bytecode of the tool, compiled now, as you, beside the source: the guard (qargi __guard, run on every tool call of a member) is imported
# from lib/ (bin/qargi), and python caches only what it imports. A tool you cannot write to (a checkout installed with sudo) is compiled by
# the one who can: qargi upgrade does it through sudo; after a first install, run the command below once. Without the bytecode the tool runs
# as before and the guard starts slower (about twice as long). Nothing is written outside the tool's own lib/ (its __pycache__ directories).
# Every install does it, --project too: with the bytecode there, a verb that imports from lib/ finds it fresh and writes nothing, so a tool that is
# read-only afterwards (a checkout under sudo, a copy made read-only) never needs to write. (PYTHONDONTWRITEBYTECODE is no help here: python3 -I,
# which every script of lib/ starts with, ignores it.)
if ! python3 -I -m compileall -q "$src/lib" >/dev/null 2>&1; then
  echo "note: the bytecode of $src/lib was not compiled (the tool is read-only for you), so qargi __guard starts slower; once, as the owner: sudo python3 -I -m compileall -q $src/lib" >&2
fi

kind="symlinks to $here"; [ -z "$copy" ] || kind=copy
for r in $runs; do echo "installed the skills of $r in ${skdir[$r]} ($kind)"; done
if [ "$mode" = user ]; then
  records record --conf "$liveconf" --tool-root "$(cd "$src" && pwd -P)" --version "$(cat "$src/VERSION")" --source "$how" || exit 1
  read_state
  echo "installed the command at $cmd, the man page at $manpage ($kind)"
  echo "completion: bash $completion, zsh $zshcomp, fish $fishcomp"
  echo "recorded what was written in $rdir (--uninstall removes exactly that)"
  # shellcheck disable=SC2086
  echo "installed runtimes: $(commas $RUNTIMES)"
  echo "recorded the install in $liveconf/install.json (a checkout run from elsewhere keeps its data in its own .qargi)"
  # the baseline packs go into the library (only the missing ones, unlinked: an unlinked pack reaches nobody)
  "$src/bin/qargi" packs seed --install || echo "note: the baseline packs were not seeded; run: qargi packs seed" >&2
  ! command -v zsh >/dev/null 2>&1 || echo "note: for zsh add this to ~/.zshrc before compinit: fpath=($(dirname "$zshcomp") \$fpath)" >&2
  command -v man >/dev/null 2>&1 && ! man -w qargi >/dev/null 2>&1 && echo "note: man does not find it yet; add $xdg/man to MANPATH (or: man -l $manpage)" >&2 || true
  echo "note: bash loads the completion in new shells when bash-completion is installed; otherwise add to ~/.bashrc: source $completion" >&2
else
  command -v qargi >/dev/null 2>&1 || echo "note: the qargi command is not on PATH; run: install.sh --user" >&2
fi

echo "next: create the members that do the work, with names you choose, for example:"
echo "  qargi agent add worker --project NAME    (and reviewer: qargi agent add reviewer --project NAME)"

if [ -n "$exclude_file" ]; then
  mkdir -p "$(dirname "$exclude_file")"; touch "$exclude_file"
  for r in $runs; do
    for s in $skills; do
      line=/${skdir[$r]#"$proj"/}/$s
      grep -qx -F "$line" "$exclude_file" || printf '%s\n' "$line" >> "$exclude_file"
    done
  done
  echo "hidden from git via $exclude_file (local only, nothing committed)"
fi
