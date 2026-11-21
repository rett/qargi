#!/usr/bin/env bash
# The enabled set of runtimes of a project and its gate (the first task of the runtime-per-profile design): a project runs its members on its
# own runtime and on the extra runtimes of models.extra_runtimes.local, each approved with `qargi provider enable PROJECT --runtime NAME` (a plan,
# a token and the owner's words); a read-only role needs the barrier of its own runtime, and the acceptance of the project's runtime does not count
# for an extra one; a profile may name one of them. Hermetic and offline: a copy of the tool holds the fake runtimes (tests/fakeprov.sh), so the
# shipped definitions are never changed, and the sign-in of a fake runtime is a file of the test's own home. Run: tests/test_runtime_enable.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
unset QARGI_PROJECT QARGI_LEAD_RUNTIME
mkdir -p "$HOME" "$T/c/projects" "$T/s"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
# fakecx: the codex definition under another name (partial barrier, reads not confined); fakeyes: a barrier that holds; fakeno: none; fakeconf: its
# reads are confined (the claim of the definition); each has its sign-in under the test's home, outside any directory of a user's own sessions
BARRIER() { printf '.capabilities.read_only_barrier |= (.value = "%s" | .verified_on = "2026-11-11")' "$1"; }
fake_command_runtime "$SRC" "$TOOL" fakecx
fake_command_runtime "$SRC" "$TOOL" fakeyes "$(BARRIER yes)"
fake_command_runtime "$SRC" "$TOOL" fakeno "$(BARRIER no)"
fake_command_runtime "$SRC" "$TOOL" fakeconf '.dispatch.reads = {"confined": true, "exposes": [], "note": "nothing"}'
for r in fakecx fakeyes fakeno fakeconf; do mkdir -p "$HOME/.$r-members"; echo '{}' > "$HOME/.$r-members/auth.json"; done
for r in fakecx fakeyes fakeno fakeconf; do python3 -I "$TOOL/lib/provider.py" check "$r" >/dev/null 2>&1 || bad=$r; done
[ -z "${bad:-}" ] && ok "the fake command runtimes are valid" || no "fake command runtime $bad"

mkproj() { # NAME PROVIDER-JSON [EXTRAS-JSON]: stored answers with a repository of their own; EXTRAS is the list of models.extra_runtimes.local
  local repo=$T/repo-$1
  mkdir -p "$repo"
  jq -n --arg n "$1" --arg p "$repo" --argjson prov "$2" --argjson ex "${3:-null}" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
    roles:{build:{base:"main",push:{mode:"none"},effort:"medium"},review:{base:"main",push:{mode:"none"},effort:"medium"}},
    models:({provider:$prov} + (if $ex == null then {} else {extra_runtimes:{local:$ex}} end)),memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
}
CC='{"local":"claude-code","cloud":"claude-platform"}'
ACC='{"by":"me","at":"2026-11-11T12:00:00Z","reason":"the owner said so"}'

# --- no extras: project validate of a project without them is what it was before the design (the fixture was recorded from the head before it)
for f in project project-command; do
  out=$({ "$DA" project validate "$SRC/tests/fixtures/runtime-no-extras/$f.json" 2>&1; echo "exit $?"; })
  [ "$out" = "$(cat "$SRC/tests/fixtures/runtime-no-extras/validate-$f.golden")" ] && ok "no extras: project validate of $f.json is as recorded" || no "no extras: validate of $f.json changed: $out"
done

# --- the enabled set: one function answers it
mkproj plain "$CC"
mkproj two "$CC" '["fakecx"]'
mkproj dup "$CC" '["fakecx","fakecx","claude-code"]'
mkproj nolocal '{"cloud":"claude-platform"}' '["fakecx"]'
out=$("$DA" provider runtimes plain 2>&1)
[ "$out" = "primary claude-code" ] && ok "runtimes: a project without extras has its own runtime and no extra" || no "runtimes of plain: $out"
out=$("$DA" provider runtimes two 2>&1)
[ "$out" = "primary claude-code
extra fakecx" ] && ok "runtimes: the primary, then each extra" || no "runtimes of two: $out"
out=$("$DA" provider runtimes dup 2>&1)
[ "$out" = "primary claude-code
extra fakecx" ] && ok "runtimes: an extra is listed once and the primary is never one" || no "runtimes of dup: $out"
"$DA" provider runtimes nolocal >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && ok "runtimes: a project with no local runtime is refused (exit 2)" || no "runtimes of nolocal: rc=$rc"
"$DA" provider runtimes nosuch >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && ok "runtimes: no such project is refused (exit 2)" || no "runtimes of nosuch: rc=$rc"

# --- the read-only barrier belongs to the runtime
rb() { python3 -I "$TOOL/lib/provider.py" require-barrier "$@"; }
mkproj bar "$CC" '["fakecx","fakeyes","fakeno"]'
jq --argjson a "$ACC" '.models.accept_no_barrier = {local: $a}' "$T/c/projects/bar.json" > "$T/bar.json" && mv "$T/bar.json" "$T/c/projects/bar.json"
out=$(rb fakeyes local --project bar 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -z "$out" ]; } && ok "an extra runtime whose barrier holds passes silently" || no "fakeyes: rc=$rc $out"
out=$(rb fakecx local --project bar 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'partial read-only barrier' <<<"$out"; } && ok "an extra runtime with a partial barrier passes and prints its note" || no "fakecx: rc=$rc $out"
out=$(rb fakeno local --project bar 2>&1); rc=$?
{ [ "$rc" = 4 ] && grep -q 'has no read-only barrier' <<<"$out" && ! grep -q 'qargi provider accept' <<<"$out"; } \
  && ok "an extra runtime with no barrier is refused (exit 4) even though the project accepted none for its own runtime, and no accept command is offered" || no "fakeno: rc=$rc $out"
mkproj bar2 '{"local":"fakeno","cloud":"claude-platform"}' '["fakecx"]'
jq --argjson a "$ACC" '.models.accept_no_barrier = {local: $a}' "$T/c/projects/bar2.json" > "$T/bar.json" && mv "$T/bar.json" "$T/c/projects/bar2.json"
out=$(rb fakeno local --project bar2 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -z "$out" ]; } && ok "the project's own runtime with no barrier still passes on the acceptance recorded for it" || no "own runtime with acceptance: rc=$rc $out"
mkproj bar3 '{"local":"fakeno","cloud":"claude-platform"}' '["fakecx"]'
out=$(rb fakeno local --project bar3 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider accept fakeno --surface local --no-barrier --project bar3' <<<"$out"; } && ok "the project's own runtime with no barrier is refused with the accept command (exit 2), as before" || no "own runtime: rc=$rc $out"
out=$(rb fakeno local --project plain 2>&1); rc=$?
[ "$rc" = 2 ] && ok "a runtime that is not an extra of the project is judged as before (exit 2)" || no "not an extra: rc=$rc $out"

# barrier_guard SURFACE PROJECT [RUNTIME]: the shell gate the verbs call
guard() { ( . "$TOOL/lib/lib.sh"; barrier_guard "$@" ) 2>&1; }
out=$(guard local bar fakeno); rc=$?
{ [ "$rc" = 1 ] && grep -q 'qargi-refusal/1' <<<"$out" && grep -q '"code":"runtime-barrier-missing"' <<<"$out" && grep -q 'refused \[runtime-barrier-missing\] the runtime fakeno has no read-only barrier' <<<"$out"; } \
  && ok "barrier-guard-extra-missing: barrier_guard with an extra runtime that has no barrier raises runtime-barrier-missing (exit 1)" || no "guard fakeno: rc=$rc $out"
out=$(guard local bar fakecx); rc=$?
{ [ "$rc" = 0 ] && grep -q 'partial read-only barrier' <<<"$out"; } && ok "barrier_guard with an extra runtime that has a partial barrier passes with its note" || no "guard fakecx: rc=$rc $out"
out=$(guard local bar); rc=$?
{ [ "$rc" = 0 ] && grep -q 'partial read-only barrier' <<<"$out"; } && ok "barrier_guard with no runtime asks the project's own runtime, as before" || no "guard own: rc=$rc $out"
out=$(guard local bar3); rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider accept fakeno' <<<"$out"; } && ok "barrier_guard of a project whose own runtime has none is refused with the accept command (exit 2), as before" || no "guard bar3: rc=$rc $out"

exit $fail
