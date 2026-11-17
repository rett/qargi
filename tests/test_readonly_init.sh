#!/usr/bin/env bash
# The first-load setup of lib/lib.sh changes nothing that is already right: an observational verb run after one initializing run leaves every path,
# byte and mode under qargi's root, config and state as it was and calls no chmod; with those directories read-only (owner write removed, or a
# read-only mount when the system lets an unprivileged user make one) the verbs print no chmod or mkdir diagnostic and keep their exit status. A fresh
# home still gets its directories at mode 700 and its files at 600, a directory open to group or others is closed to 700, DA_NOSETUP creates nothing,
# and a write that is really needed and fails still says so (with no chmod after it). A root, config or state that is a link to a directory counts as
# the directory (a target made 500 on purpose is left alone), and a mode that cannot be read gets the chmod to 700. The directories made read-only
# are made writable again by a trap, also when the step is killed.
# The three runs of the verbs (as initialized, owner write removed, read-only mount) each work on their own copy of the initialized root and run side
# by side, so the step stays within its budget.
# Run: tests/test_readonly_init.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; LIB=$PWD/lib/lib.sh
# a timeout or a kill must not leave directories without write permission that the hermetic cleanup cannot remove: give the owner write back, then
# clean up as the hermetic trap does
trap 'kill_bg; chmod -R u+w "$T" 2>/dev/null; rm -rf "$HERMETIC"' EXIT
trap 'exit 143' TERM INT HUP
# shellcheck source=fixtures.sh
. tests/fixtures.sh

# qargi's data under one root (QARGI_HOME), so the setup also handles the root directory; the hermetic QARGI_CONF and QARGI_STATE would skip it
unset QARGI_CONF QARGI_STATE
# a chmod first on PATH for the verbs: it logs each call to the file CHLOG names, then runs the real one
CHMOD=$(command -v chmod)
mkdir -p "$T/shim"
printf '#!/bin/sh\necho "$*" >> "${CHLOG:?}"\nexec %s "$@"\n' "'$CHMOD'" > "$T/shim/chmod"
"$CHMOD" 755 "$T/shim/chmod"
SPATH=$T/shim:$PATH

# a scratch repository with a backlog and a small valid graph, and the stored answers of its project
R=$T/app; Q=$T/q; mkdir -p "$R/.git" "$Q/config/projects"
printf '# Backlog\n\n## Now\n\n- [aa] the first item\n- [bb] the second item\n' > "$T/backlog.md"
printf '{"format":"backlog-graph","version":1,"nodes":["backlog:aa","backlog:bb"],"relations":[],"evidence":[]}\n' > "$T/graph.json"
jq -n --arg r "$R" --arg b "$T/backlog.md" '{project: "app", repo: {path: $r}, backlog: {file: $b, section: "Now"}}' > "$Q/config/projects/app.json"

# the observational verbs. run_verb N ROOT OUT: runs verb N in the repository with qargi's data under ROOT and the shim first on PATH (its calls in
# OUT.chmod), its output in OUT; sets rc
VERBS=("version" "backlog list --json" "backlog graph check" "doctor")
run_verb() {
  local -a args
  case $1 in
    0) args=(version);;
    1) args=(backlog list --json --project app);;
    2) args=(backlog graph check --graph "$T/graph.json" --project app);;
    3) args=(doctor);;
  esac
  rc=0; (cd "$R" && QARGI_HOME=$2 CHLOG=$3.chmod PATH=$SPATH "$DA" "${args[@]}") > "$3" 2>&1 || rc=$?
}
# snap ROOT: every path under ROOT with its type, mode, size and mtime, and the checksum of every file
snap() { { find "$1" -printf '%y %m %s %T@ %p\n'; find "$1" -type f -exec sha256sum {} +; } | LC_ALL=C sort; }
# phase NAME ROOT: runs each verb N once on ROOT and leaves in $T/NAME.N.rc its exit status, in $T/NAME.N.out its output, in $T/NAME.N.out.chmod
# its chmod calls and in $T/NAME.N.diff the change of ROOT it made
phase() {
  local i
  for i in "${!VERBS[@]}"; do
    snap "$2" > "$T/$1.$i.before"; : > "$T/$1.$i.out.chmod"
    run_verb "$i" "$2" "$T/$1.$i.out"; echo "$rc" > "$T/$1.$i.rc"
    snap "$2" | diff "$T/$1.$i.before" - > "$T/$1.$i.diff"
  done
}
# the owner-write phase: root, config and state without write permission for anyone
phase_ro() { "$CHMOD" a-w "$2/config" "$2/state" "$2"; phase "$@"; }
# the mount phase: ROOT mounted read-only over itself in a user and mount namespace of its own
phase_mount() {
  # shellcheck disable=SC2016  # expanded by the inner shell
  unshare -rm bash -c 'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" || exit 99; eval "$2"' _ "$2" \
    "$(declare -f run_verb snap phase); $(declare -p T R DA SPATH VERBS); phase $(printf '%q %q' "$1" "$2")"
}

# one initializing run, then three copies of the initialized root
run_verb 1 "$Q" "$T/init.out"
[ "$rc" = 0 ] || no "the initializing run failed (exit $rc): $(cat "$T/init.out")"
cp -a "$Q" "$T/q.ro"; cp -a "$Q" "$T/q.mount"
PHASES=(plain)
spawn_bg phase plain "$Q"
if [ "$(id -u)" = 0 ]; then echo "skip (b) with owner write removed: running as root, which writes whatever the mode"
else spawn_bg phase_ro ro "$T/q.ro"; PHASES+=(ro); fi
if unshare -rm true 2>/dev/null; then spawn_bg phase_mount mount "$T/q.mount"; PHASES+=(mount)
else echo "skip (b) on a read-only mount: this system lets no unprivileged user namespace mount one"; fi
wait

# --- (a) as initialized, (b) owner write removed and on a read-only mount: each verb changes nothing, calls no chmod, prints no chmod or mkdir
# diagnostic and has the exit status it has as initialized
declare -A LABEL=([plain]="after an initializing run" [ro]="read-only directories" [mount]="read-only mount")
for p in "${PHASES[@]}"; do
  for i in "${!VERBS[@]}"; do
    rc=$(cat "$T/$p.$i.rc" 2>/dev/null); ref=$(cat "$T/plain.$i.rc" 2>/dev/null)
    if [ -n "$rc" ] && [ "$rc" = "$ref" ] && [ ! -s "$T/$p.$i.diff" ] && [ ! -s "$T/$p.$i.out.chmod" ] && ! grep -Eq 'chmod: |mkdir: ' "$T/$p.$i.out"; then
      ok "${LABEL[$p]}: qargi ${VERBS[$i]} keeps exit $rc, changes no path, byte or mode, calls no chmod and prints no chmod or mkdir diagnostic"
    else
      no "${LABEL[$p]}: qargi ${VERBS[$i]} rc=$rc (as initialized: $ref): $(cat "$T/$p.$i.out" 2>&1) changes: $(head -20 "$T/$p.$i.diff" 2>&1) chmod calls: $(cat "$T/$p.$i.out.chmod" 2>&1)"
    fi
  done
done
[ "$(cat "$T/plain.0.rc")" = 0 ] && [ "$(cat "$T/plain.1.rc")" = 0 ] && grep -q '"aa"' "$T/plain.1.out" && [ "$(cat "$T/plain.2.rc")" = 0 ] \
  && ok "version, backlog list --json and backlog graph check succeed" || no "a verb failed: $(cat "$T/plain.0.out" "$T/plain.1.out" "$T/plain.2.out")"

# setup [ENV...]: loads lib/lib.sh once with the environment given (the shim first on PATH, its calls in $T/chmod.log), its output in
# $T/setup.out, and sets rc
setup() { rc=0; env PATH="$SPATH" CHLOG="$T/chmod.log" "$@" bash -c '. "$1"' _ "$LIB" > "$T/setup.out" 2>&1 || rc=$?; }
chmods() { [ -s "$T/chmod.log" ] && cat "$T/chmod.log"; }
mode() { stat -c %a "$1"; }

# --- (c) a fresh home gets its directories at 700 and its files at 600, with the same contents as before
F=$T/fresh
setup QARGI_HOME="$F"
[ $rc = 0 ] && [ ! -s "$T/setup.out" ] && [ "$(mode "$F")" = 700 ] && [ "$(mode "$F/config")" = 700 ] && [ "$(mode "$F/state")" = 700 ] \
  && [ "$(mode "$F/config/instances.json")" = 600 ] && [ "$(mode "$F/state/sessions.json")" = 600 ] && [ "$(mode "$F/config/agents.json")" = 600 ] \
  && [ "$(cat "$F/config/instances.json")" = '{}' ] && [ "$(cat "$F/state/sessions.json")" = '{}' ] \
  && [ "$(cat "$F/config/agents.json")" = '{"schema":2,"projects":{}}' ] && ok "a fresh home: root, config and state 700, the three files 600 with their first contents" \
  || no "fresh home rc=$rc: $(cat "$T/setup.out"); $(find "$F" -printf '%m %p\n')"
setup QARGI_CONF="$T/fc/config" QARGI_STATE="$T/fc/state"
[ $rc = 0 ] && [ "$(mode "$T/fc/config")" = 700 ] && [ "$(mode "$T/fc/state")" = 700 ] && [ "$(mode "$T/fc/config/agents.json")" = 600 ] \
  && [ "$(mode "$T/fc")" != 700 ] && [ ! -e "$HOME/.qargi" ] && ok "QARGI_CONF and QARGI_STATE: the two directories 700, the parent and the default root left alone" \
  || no "conf/state rc=$rc: $(find "$T/fc" -printf '%m %p\n'); $(ls -ld "$HOME/.qargi" 2>&1)"

# --- (d) a directory open to group or others is closed to 700; nothing else is touched
"$CHMOD" 755 "$F/config"; "$CHMOD" 644 "$F/state/sessions.json"; echo '{"kept": 1}' > "$F/config/instances.json"
: > "$T/chmod.log"; setup QARGI_HOME="$F"
[ $rc = 0 ] && [ "$(mode "$F/config")" = 700 ] && [ "$(chmods)" = "700 $F/config" ] && [ "$(mode "$F/state/sessions.json")" = 644 ] \
  && [ "$(cat "$F/config/instances.json")" = '{"kept": 1}' ] && ok "a directory at 755 is set to 700 by the one chmod; existing files are left alone" \
  || no "755 rc=$rc: $(cat "$T/setup.out") chmod calls: $(chmods); $(find "$F" -printf '%m %p\n')"

# --- (e) DA_NOSETUP creates nothing
: > "$T/chmod.log"; setup QARGI_HOME="$T/none" DA_NOSETUP=1
[ $rc = 0 ] && [ ! -e "$T/none" ] && ! chmods >/dev/null && ok "DA_NOSETUP=1: nothing is created and no chmod runs" || no "DA_NOSETUP rc=$rc: $(cat "$T/setup.out") $(ls -la "$T/none" 2>&1)"

# --- (f) a write that is really needed and fails still says so
if [ "$(id -u)" = 0 ]; then
  echo "skip (f): running as root, which writes whatever the mode"
else
  rm "$F/config/agents.json"; "$CHMOD" 500 "$F/config"
  setup QARGI_HOME="$F"
  grep -q 'agents.json: Permission denied' "$T/setup.out" && [ ! -e "$F/config/agents.json" ] && ! grep -q 'chmod: ' "$T/setup.out" && ! chmods >/dev/null \
    && ok "a missing file in a read-only directory: the failed write is reported, and no chmod follows it" \
    || no "needed write rc=$rc: $(cat "$T/setup.out") chmod calls: $(chmods)"
fi

# --- (g) a link to a directory counts as the directory: with the root a link to an initialized root, and the config a link to a directory made 500
# on purpose, an observational verb makes no chmod call, changes nothing under the targets and leaves the 500
cp -a "$Q" "$T/q.real"; mv "$T/q.real/config" "$T/q.cfg"; ln -s "$T/q.cfg" "$T/q.real/config"; ln -s "$T/q.real" "$T/q.lnk"; "$CHMOD" 500 "$T/q.cfg"
{ snap "$T/q.real"; snap "$T/q.cfg"; } > "$T/lnk.before"; : > "$T/lnk.out.chmod"
run_verb 1 "$T/q.lnk" "$T/lnk.out"
{ snap "$T/q.real"; snap "$T/q.cfg"; } | diff "$T/lnk.before" - > "$T/lnk.diff"
[ $rc = 0 ] && [ ! -s "$T/lnk.diff" ] && [ ! -s "$T/lnk.out.chmod" ] && [ "$(mode "$T/q.cfg")" = 500 ] && ! grep -Eq 'chmod: |mkdir: ' "$T/lnk.out" \
  && ok "root and config as links to directories: no chmod call, nothing changed, the 500 target kept" \
  || no "links rc=$rc: $(cat "$T/lnk.out") changes: $(head -20 "$T/lnk.diff") chmod calls: $(cat "$T/lnk.out.chmod"); $(mode "$T/q.cfg")"

# --- (h) a mode that cannot be read is not left to chance: root, config and state each get the chmod to 700
mkdir -p "$T/shim2"; printf '#!/bin/sh\nexit 1\n' > "$T/shim2/stat"; "$CHMOD" 755 "$T/shim2/stat"
cp -a "$Q" "$T/q.nostat"; : > "$T/chmod.log"
setup QARGI_HOME="$T/q.nostat" PATH="$T/shim2:$SPATH"
[ $rc = 0 ] && [ "$(chmods | LC_ALL=C sort)" = "$(printf '700 %s\n' "$T/q.nostat" "$T/q.nostat/config" "$T/q.nostat/state" | LC_ALL=C sort)" ] \
  && ok "stat fails: root, config and state each get the chmod to 700" || no "stat failure rc=$rc: $(cat "$T/setup.out") chmod calls: $(chmods)"

exit "$fail"
