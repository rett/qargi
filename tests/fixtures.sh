# shellcheck shell=bash
# Sourced by a shell test, from the repository root (`. tests/fixtures.sh`) after hermetic.sh. Sourcing only defines functions: it sets no
# option and no variable, changes no directory and runs nothing, so the line may stand wherever the test used to define ok and no. A helper
# reads T (its temporary directory), fail=0 and DA (the qargi under test) when it runs, not when the file is sourced.
# The helpers the tests re-implemented one by one: the report lines, a scratch repository, a bare origin, the machines (a clone of the
# origin with its own home, conf and state), the git and ssh-keygen shims, and a poll that replaces a fixed sleep. A test that needs the
# helper under another name or another body keeps its own; nothing here reads anything but the arguments and the variables named below.
#
# Variables a helper reads: T (a writable directory the test owns), fail (set to 1 by no), DA (the qargi to run), ORIGIN (the bare origin
# make_origin made). Every helper takes its directories as arguments or from T, so a test may run a second world with T set to another directory.

# --- the report: `ok TEXT` prints an ok line, `no TEXT` a FAIL line and fails the test
ok() { echo "ok   $1"; }
# shellcheck disable=SC2034  # the test reads fail
no() { echo "FAIL $1"; fail=1; }
# out: what the last XE printed, output then error (the test keeps them in $T/o and $T/e)
out() { cat "$T/o" "$T/e"; }
# tokof [TEXT]: the plan token of a plan printed by an owner verb, from TEXT or else from the last output ($T/o)
tokof() { if [ $# -gt 0 ]; then sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$1"; else sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' "$T/o"; fi; }
# tok: the plan token of the plan printed on its standard input (`$DA verb | tok`). tok_of and tokp are the names older tests use for the
# same filter. A test that wants another body for tokof (a pipe filter, say) defines it after sourcing this file.
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
tok_of() { tok; }
tokp() { tok; }

# --- polling instead of sleeping
# wait_until CMD [SECONDS]: runs CMD (a command line, evaluated; use a function for a loop, `return` and `exit` end the helper or the test)
# every 50 ms until it succeeds; returns 1 when SECONDS (whole seconds, default 10) pass first.
wait_until() {
  local cmd=$1 limit=${2:-10} end
  end=$(( ${EPOCHREALTIME/./} / 1000 + ${limit%.*} * 1000 ))
  until eval "$cmd"; do
    [ $(( ${EPOCHREALTIME/./} / 1000 )) -lt "$end" ] || return 1
    sleep 0.05
  done
}

# --- repositories
# make_repo DIR: a repository with one commit on master (VERSION 0.1.0) and a develop branch at it.
make_repo() {
  git init -q -b master "$1" && echo 0.1.0 > "$1/VERSION" \
    && git -C "$1" add -A && git -C "$1" commit -q -m one && git -C "$1" branch develop
}
# make_origin DIR: a bare repository holding master and develop (the seed repository is made beside it and removed again).
make_origin() {
  git init -q --bare "$1" && make_repo "$1.seed" \
    && git -C "$1.seed" remote add origin "$1" && git -C "$1.seed" push -q origin master develop
  rm -rf "$1.seed"
}
# make_machine NAME: $T/m/NAME with home/, c/ (QARGI_CONF, with a valid project "app" pointing at the machine's clone), s/ (QARGI_STATE) and
# app/ (a clone of $ORIGIN with a local develop). The first call builds the clone and the project record in $T/.fx; every later one copies
# them with `cp -a` and points the record at its own clone, so each machine is as independent as one cloned from scratch.
make_machine() {
  local d=$T/m/$1 fx=$T/.fx
  mkdir -p "$d/home" "$d/c/projects" "$d/s"
  if [ ! -d "$fx/app" ]; then
    mkdir -p "$fx/home" "$fx/c" "$fx/s"
    git clone -q "$ORIGIN" "$fx/app" && git -C "$fx/app" branch develop origin/develop >/dev/null 2>&1
    env HOME="$fx/home" QARGI_CONF="$fx/c" QARGI_STATE="$fx/s" "$DA" project template app \
      | jq '.repo.url = "https://github.com/acme/app" | .methodology = "gitflow" | .test_command = "true"' > "$fx/app.json"
  fi
  cp -a "$fx/app" "$d/app"
  jq --arg p "$d/app" '.repo.path = $p' "$fx/app.json" > "$d/c/projects/app.json"
}
# clone_machine SRC NAME: $T/m/NAME as a copy (`cp -a`) of the machine SRC as it is now (enabled, keyed, with its records), with the
# machine's own paths written in place of SRC's in its text files. For a setup that every machine of a group repeats the same way.
clone_machine() {
  cp -a "$T/m/$1" "$T/m/$2" \
    && { grep -rIlF --exclude-dir=objects -e "$T/m/$1" "$T/m/$2" || true; } | while IFS= read -r f; do sed -i "s|$T/m/$1|$T/m/$2|g" "$f"; done
}

# --- shims first on PATH
# git_shim BINDIR LOG REALGIT [CTL]: BINDIR/git logs every push, fetch, pull, ls-remote and clone as `SUB<TAB>prompt=<GIT_TERMINAL_PROMPT>
# <TAB>cwd<TAB>args after SUB` in LOG and runs REALGIT. With CTL (a directory) it also obeys, per machine (the key is $HOME with / as _):
# CTL/slow/KEY lists the verbs that hang (30 s) and CTL/hooks/KEY is a script run once right after that machine's next fetch.
git_shim() {
  mkdir -p "$1"
  {
    printf '#!/usr/bin/env bash\nLOG=%q REALGIT=%q CTL=%q\n' "$2" "$3" "${4:-}"
    cat <<'SHIM'
key=$(printf '%s' "$HOME" | tr / _)
sub=''; i=0; skip=0
for a in "$@"; do
  i=$((i + 1))
  if [ $skip = 1 ]; then skip=0; continue; fi
  case $a in -C|-c) skip=1;; -*) ;; *) sub=$a; break;; esac
done
case $sub in
  push|fetch|pull|ls-remote|clone)
    printf '%s\t%s\t%s\t%s\n' "$sub" "prompt=${GIT_TERMINAL_PROMPT-unset}" "$PWD" "${*:$((i + 1))}" >> "$LOG"
    if [ -n "$CTL" ] && [ -f "$CTL/slow/$key" ] && grep -qw "$sub" "$CTL/slow/$key"; then exec sleep 30; fi;;
esac
if [ -z "$CTL" ]; then exec "$REALGIT" "$@"; fi
"$REALGIT" "$@"; rc=$?
if [ "$sub" = fetch ] && [ -f "$CTL/hooks/$key" ]; then
  mv "$CTL/hooks/$key" "$CTL/hooks/$key.run"; bash "$CTL/hooks/$key.run" >/dev/null 2>&1
fi
exit $rc
SHIM
  } > "$1/git"
  chmod +x "$1/git"
}
# sshk_shim BINDIR LOG REALSSHK SLOWFILE: BINDIR/ssh-keygen logs its argument list in LOG and runs REALSSHK. A verification (verify or
# find-principals) whose arguments contain a line of the file SLOWFILE hangs for 60 s (the file empty or missing: none does). The arguments
# carry the verifying process's scratch directory, so a test names the machine by giving it a TMPDIR of its own and listing that directory.
sshk_shim() {
  mkdir -p "$1"
  {
    printf '#!/usr/bin/env bash\nLOG=%q REALSSHK=%q SLOWFILE=%q\n' "$2" "$3" "$4"
    cat <<'SHIM'
printf '%s\n' "$*" >> "$LOG"
case "$*" in
  *verify*|*find-principals*)
    if [ -s "$SLOWFILE" ]; then
      while IFS= read -r pat; do case "$*" in *"$pat"*) exec sleep 60;; esac; done < "$SLOWFILE"
    fi;;
esac
exec "$REALSSHK" "$@"
SHIM
  } > "$1/ssh-keygen"
  chmod +x "$1/ssh-keygen"
}
