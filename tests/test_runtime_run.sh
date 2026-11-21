#!/usr/bin/env bash
# A run on one of several runtimes (the third task of the runtime-per-profile design): `qargi local prepare` resolves the runtime of a run (the task's
# --runtime, the runtime a profile names, the project's own) before anything else, asks the read-only barrier of THAT runtime, binds the run to it, and
# records it in the lead's registry; `qargi local run` starts the run on the runtime it was prepared for or refuses (runtime-drift); `local list` and
# `review check` show it; verify, review, apply, close and clean never ask for a runtime. A project without extra runtimes (models.extra_runtimes.local
# empty) sees nothing new: its prepare output, registry line and run list are the ones recorded in tests/fixtures/runtime-no-extras before the change.
# Hermetic and offline: a copy of the tool holds the fake command runtimes (tests/fakeprov.sh), the scratch directories are under the test's own
# directory (TMPDIR on disk: the shipped codex definition hides /dev, so a test under /dev/shm would refuse its own runs).
# Run: tests/test_runtime_run.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
umask 077
unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_AUTHOR_DATE GIT_COMMITTER_DATE
SRC=$PWD
T=$(mktemp -d); fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T TMPDIR=$T/tmp
unset QARGI_PROJECT QARGI_LEAD_RUNTIME
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/tmp" "$T/scr" "$HOME/.codex-members"
echo '{}' > "$HOME/.codex-members/auth.json"   # the members' sign-in of the shipped codex: a file of the test's own home
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
NX=$SRC/tests/fixtures/runtime-no-extras
LC="git -c user.name=t -c user.email=t@example.net"
# the shipped codex definition hides /dev, and a TMPDIR under /dev/shm would refuse every run of a codex-derived runtime: the copy of the tool
# hides HID, a path no run lies under, in its place (the suite may run under /dev/shm; the hidden-path refusal is tested with a prefix of its own)
HID=$T/hidden-by-the-sandbox
jq --arg h "$HID" '.dispatch.hidden_paths.prefixes = [$h]' "$SRC/lib/providers/codex.json" > "$TOOL/lib/providers/codex.json"
ok() { echo "ok $1"; }
no() { echo "FAIL $1"; fail=1; }

# --- a project without extras: what prepare printed, what the registry recorded and what the list showed are on record (tests/fixtures/
# runtime-no-extras, recorded from the head before the change). Paths, run names, times and commit ids are masked; everything else must not move.
mkrepo() { # DIR: a repository with develop and master at one commit
  git init -q -b master "$1" && $LC -C "$1" commit -q --allow-empty -m one && git -C "$1" branch develop
}
mask() { sed -e "s#$T#T#g" -e 's/qargi\.[A-Za-z0-9]\{6\}/qargi.XXXXXX/g' -e 's/qargi-run\.[A-Za-z0-9]\{6\}/qargi-run.XXXXXX/g' -e 's/[0-9a-f]\{40\}/SHA/g'; }
nx_project() { # NAME FIXTURE: the stored answers of a fixture project, with a repository of its own
  mkrepo "$T/repo-$1"
  jq --arg p "$T/repo-$1" --arg n "$1" '.repo.path = $p | .project = $n' "$NX/$2.json" > "$T/c/projects/$1.json"
}
nx_prep() { # PROJECT ARGS...: a prepare in the project's repository, its output (standard error too) masked; the run is left in RUN
  local p=$1; shift
  PREP=$("$DA" local prepare --repo "$T/repo-$p" --base develop --scratch "$T/scr" "$@" 2>&1); PREP_RC=$?
  RUN=$(sed -n 's/^RUN=//p' <<<"$PREP")
  echo "--- prepare $p $*"; mask <<<"$PREP"; echo "exit $PREP_RC"
}
nx_registry() { # RUN: the registry line of the run, with what changes from one run to the next masked
  jq -S --arg r "$1" 'select(.run == $r) | .run = "RUN" | .tmpdir = "TMP" | del(.started) | if has("repo") then .repo = "REPO" else . end' "$QARGI_STATE/local-runs.jsonl"
}
nx_scene() { # PROJECT: two prepares (a build with a profile, a review), their registry lines and the run list
  nx_prep "$1" --slug nxa --profile worker-fast; nx_registry "$RUN"
  nx_prep "$1" --slug nxb --role review; nx_registry "$RUN"
  echo "--- local list --json"
  "$DA" local list --json | jq -S . | mask | sed 's/[0-9][0-9]*[mhd] /AGE /g'
}
nx_project nxsession project
nx_project nxcommand project-command
"$DA" agent add worker --roles build,write,test --project nxsession >/dev/null 2>&1
"$DA" agent add reviewer --roles review --project nxsession >/dev/null 2>&1
if [ -n "${NX_RECORD:-}" ]; then    # the head before the change is run once with NX_RECORD=DIR, and the fixture is what it printed
  nx_scene nxsession > "$NX_RECORD/prepare-session.golden" 2>&1
  nx_scene nxcommand > "$NX_RECORD/prepare-command.golden" 2>&1
  exit 0
fi
nxbad=''
for pair in session:nxsession command:nxcommand; do
  out=$(nx_scene "${pair##*:}" 2>&1)
  [ "$out" = "$(cat "$NX/prepare-${pair%%:*}.golden")" ] \
    || { nxbad=1; no "no extras: prepare, the registry line and the run list of the ${pair%%:*} fixture project changed:"; diff <(echo "$out") "$NX/prepare-${pair%%:*}.golden" | head -20; }
done
[ -n "$nxbad" ] || ok no-extras-identical

exit $fail
