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

# --- what the sandbox does not hold: the reads claim of a definition (dispatch.reads)
CX=$SRC/lib/providers/codex.json
[ "$(jq -r '.. | .reads? // empty | .confined' "$CX")" = false ] && jq -e '.dispatch.reads.exposes == ["~/.codex"] and (.dispatch.reads.note | test("sessions"))' "$CX" >/dev/null \
  && ok "the shipped codex definition says that reads are not confined, and names ~/.codex" || no "codex.json: dispatch.reads"
jq -e '.capabilities.read_only_barrier.note | test("sessions") and test("history") and test("~/.codex") and test("not its reads")' "$CX" >/dev/null \
  && ok "the barrier note of the shipped codex definition names the reads: ~/.codex, its sessions and history" || no "codex.json: the barrier note"
out=$(rb codex local --project two 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'sessions' <<<"$out"; } && ok "the note is printed wherever the barrier is: require-barrier prints the whole of it" || no "codex note: rc=$rc $out"
out=$("$DA" provider reads-warning fakecx 2>&1)
[ "$out" = "members on fakecx can read the real ~/.codex (sessions, history, sign-in) and whatever else this account can read: reads are not confined" ] \
  && ok "reads-warning: the words of the plan, with the exposed paths and what they hold" || no "reads-warning fakecx: $out"
out=$("$DA" provider reads-warning fakeconf 2>&1); [ -z "$out" ] && ok "reads-warning: a runtime whose definition says reads are confined has none" || no "reads-warning fakeconf: $out"
out=$("$DA" provider reads-warning claude-code 2>&1); [ -z "$out" ] && ok "reads-warning: a runtime that works in the session has none" || no "reads-warning claude-code: $out"
fake_command_runtime "$SRC" "$TOOL" fakenoreads 'del(.dispatch.reads)'
out=$("$DA" provider reads-warning fakenoreads 2>&1)
[ "$out" = "members on fakenoreads can read whatever this account can read: reads are not confined" ] \
  && ok "reads-warning: a command runtime with no dispatch.reads counts as not confined, with no path named" || no "reads-warning fakenoreads: $out"
fake_command_runtime "$SRC" "$TOOL" fakebadreads '.dispatch.reads = {"confined": "no", "paths": []}'
mkdir -p "$HOME/.fakenoreads-members" "$HOME/.fakebadreads-members"
python3 -I "$TOOL/lib/provider.py" check fakebadreads >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 1 ] && grep -q 'dispatch.reads.confined' "$T/o" && grep -q 'dispatch.reads.paths: unknown key' "$T/o"; } \
  && ok "a malformed dispatch.reads fails provider check" || no "bad reads: rc=$rc $(cat "$T/o")"
out=$("$DA" provider reads-warning fakebadreads 2>&1)
[ "$out" = "members on fakebadreads can read whatever this account can read: reads are not confined" ] && ok "a malformed claim is no claim: reads are not confined, nothing named" || no "reads-warning fakebadreads: $out"
out=$("$DA" provider reads-warning nosuch 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -z "$out" ]; } && ok "reads-warning of an unknown runtime says nothing" || no "reads-warning nosuch: rc=$rc $out"

# --- provider enable|disable PROJECT --runtime NAME: the plan, the token, the approval
ok() { echo "ok $1"; }            # the named cases below print `ok NAME`
EN() { "$DA" provider enable "$@"; }
tokof_() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$1"; }
answers_of() { jq -c '.models.extra_runtimes // "none"' "$T/c/projects/$1.json"; }
nlines() { local n; n=$(grep -c "provider:$1" "$T/s/audit.log" 2>/dev/null); echo "${n:-0}"; }
mkproj en1 "$CC"
out=$(EN en1 --runtime fakecx 2>&1); rc=$?
etok=$(tokof_ "$out")
{ [ "$rc" = 0 ] && [ -n "$etok" ] && [ "$(answers_of en1)" = '"none"' ] && [ "$(nlines enable)" = 0 ]; } && ok "enable-plan: without --plan and --approved it prints the plan and a token and changes nothing" || no "plan: rc=$rc $out"
grep -q '^runtime: fakecx (shipped), mode command, serves the local surface' <<<"$out" && grep -q "^executable: $TOOL/stubs/fakecx -> $TOOL/stubs/fakecx" <<<"$out" \
  && ok "the plan names the runtime, its origin, its mode and the executable it would resolve" || no "plan head: $out"
grep -q "^link: ~/.fakecx-members/auth.json -> auth.json (real path $(realpath "$HOME")/.fakecx-members/auth.json): present, not inside ~/.codex" <<<"$out" \
  && grep -q '^runs that share a link source run one at a time' <<<"$out" && ok "link-source-present: the plan prints the link source, its real path, present, and that it is not inside ~/.codex" || no "plan link: $out"
grep -q '^read-only barrier: partial (verified 2026-11-11): .*sessions' <<<"$out" \
  && grep -q '^read-only roles (review) on fakecx run under the partial barrier: no `provider accept` is asked and none counts' <<<"$out" \
  && ok "the plan prints the whole barrier note, and that a read-only role runs under the partial barrier with no acceptance" || no "plan barrier: $out"
grep -q '^a read-only member on fakecx reads and reports and runs nothing that writes' <<<"$out" && ok "the plan says a read-only member reads and runs nothing" || no "plan reading review: $out"
grep -q '^model and effort of a run on fakecx are requested, not confirmed: the override claims are unverified' <<<"$out" && ok "the plan says the model and effort are requested, not confirmed" || no "plan model: $out"
grep -q '^reads: members on fakecx can read the real ~/.codex (sessions, history, sign-in) and whatever else this account can read: reads are not confined$' <<<"$out" \
  && grep -q '^the owner.s approval words must contain: "reads are not confined"$' <<<"$out" && ok "reads-warning: the plan warns, with the exposed paths, and names the phrase the approval must carry" || no "plan reads: $out"
grep -q '^hidden paths: /dev' <<<"$out" && grep -q '^not available to a member on fakecx: a qargi guard hook' <<<"$out" && ok "the plan names the hidden paths and what the runtime lacks" || no "plan hidden: $out"
grep -q '^tool packs of role build: none$' <<<"$out" && grep -q '^tool packs of role review: none$' <<<"$out" && grep -q '^the MCP servers of tool packs run outside the sandbox' <<<"$out" \
  && ok "the plan says tool packs: none for a role without one" || no "plan tool packs none: $out"
# a tool pack linked to one role is listed for that role only, with its scope
mkdir -p "$T/c/packs"
printf '{"links":[{"scope":"project-role","project":"en1","role":"build","pack":"tool:kb"},{"scope":"user","pack":"tool:notes"},{"scope":"user","pack":"skill:style"}]}\n' > "$T/c/packs/links.json"
out2=$(EN en1 --runtime fakecx 2>&1)
grep -q '^tool packs of role build: kb (project-role), notes (user)$' <<<"$out2" && grep -q '^tool packs of role review: notes (user)$' <<<"$out2" \
  && ok "tool-packs-listed: each role's tool packs with their scope, and none of a skill pack" || no "plan tool packs: $out2"
[ "$(tokof_ "$out2")" != "$etok" ] && ok "the token covers the packs listed: a pack linked later is another plan" || no "the token did not move with the packs"
rm -f "$T/c/packs/links.json"
out=$(EN en1 --runtime fakecx 2>&1); etok=$(tokof_ "$out")

# approvals: the phrase is the owner's words
EN en1 --runtime fakecx --plan wrong --approved "go ahead, reads are not confined" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 1 ] && grep -q 'qargi-refusal/1' "$T/e" && grep -q '"code":"plan-stale"' "$T/e" && [ "$(answers_of en1)" = '"none"' ]; } && ok "a wrong token is plan-stale and stores nothing" || no "wrong token: rc=$rc $(cat "$T/e")"
EN en1 --runtime fakecx --approved "go" >"$T/o" 2>"$T/e"; rc=$?
[ "$rc" = 2 ] && ok "--approved without --plan is a usage error (exit 2)" || no "approved without plan: rc=$rc"
EN en1 --runtime fakecx --plan "$etok" --approved "go ahead" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 1 ] && grep -q '"code":"runtime-reads-unacknowledged"' "$T/e" && grep -q 'refused \[runtime-reads-unacknowledged\] the approval of the runtime fakecx does not carry the phrase' "$T/e" \
  && [ "$(answers_of en1)" = '"none"' ] && [ "$(nlines enable)" = 0 ]; } && ok "reads-unacknowledged: an approval without the phrase is runtime-reads-unacknowledged (exit 1), stores nothing and writes no audit line" || no "no phrase: rc=$rc $(cat "$T/e")"
EN en1 --runtime fakecx --plan "$etok" --approved "go ahead, reads  ARE
not Confined" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 0 ] && [ "$(answers_of en1)" = '{"local":["fakecx"]}' ]; } && ok "reads-acknowledged: the same token is still good, and words that carry the phrase (other letter case, runs of blanks) store it" || no "phrase: rc=$rc $(cat "$T/e" "$T/o")"
{ [ "$(nlines enable)" = 1 ] && tail -1 "$T/s/audit.log" | jq -e '.verb == "provider:enable" and (.approved | test("ARE")) and (.detail | test("^en1 runtime fakecx "))' >/dev/null; } \
  && ok "one audit line keeps the words of the approval" || no "audit: $(tail -2 "$T/s/audit.log")"
[ "$("$DA" provider runtimes en1)" = "primary claude-code
extra fakecx" ] && "$DA" project validate en1 >/dev/null 2>&1 && ok "the enabled set has the runtime and the answers stay valid for project validate" || no "after enable: $("$DA" project validate en1 2>&1)"
out=$(EN en1 --runtime fakecx 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'nothing to do: fakecx is enabled for en1 already' <<<"$out" && [ "$(nlines enable)" = 1 ]; } && ok "enabling again says so and records nothing more" || no "again: $out"

# a runtime whose definition says reads are confined: no warning, no phrase
mkproj en2 "$CC"
out=$(EN en2 --runtime fakeconf 2>&1); etok=$(tokof_ "$out")
{ grep -q '^reads: confined, as the definition of fakeconf claims' <<<"$out" && ! grep -q 'reads are not confined' <<<"$out"; } && ok "a runtime that confines reads prints no warning and names no phrase" || no "confined plan: $out"
EN en2 --runtime fakeconf --plan "$etok" --approved "go" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 0 ] && [ "$(answers_of en2)" = '{"local":["fakeconf"]}' ]; } && ok "and its approval asks for no phrase" || no "confined apply: rc=$rc $(cat "$T/e")"

# disable: a plan, a token, no phrase; two runtimes enabled, one stopped
out=$(EN en2 --runtime fakecx 2>&1); etok=$(tokof_ "$out")
EN en2 --runtime fakecx --plan "$etok" --approved "yes, reads are not confined" >/dev/null 2>&1
[ "$(answers_of en2)" = '{"local":["fakeconf","fakecx"]}' ] && ok "a second runtime is added to the list" || no "second: $(answers_of en2)"
out=$("$DA" provider disable en2 --runtime fakeconf 2>&1); etok=$(tokof_ "$out")
{ grep -q '^disable runtime fakeconf for project en2' <<<"$out" && grep -q 'becomes \["fakecx"\]' <<<"$out" && [ "$(answers_of en2)" = '{"local":["fakeconf","fakecx"]}' ]; } && ok "the disable plan shows what the list becomes and changes nothing" || no "disable plan: $out"
"$DA" provider disable en2 --runtime fakeconf --plan "$etok" --approved "stop it" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 0 ] && [ "$(answers_of en2)" = '{"local":["fakecx"]}' ] && [ "$(nlines disable)" = 1 ]; } && ok "disable applies with no phrase, and leaves one audit line" || no "disable: rc=$rc $(cat "$T/e")"
out=$("$DA" provider disable en2 --runtime fakeconf 2>&1)
grep -q 'nothing to do: fakeconf is not enabled for en2' <<<"$out" && ok "disabling what is not enabled says so" || no "disable twice: $out"
out=$("$DA" provider disable en2 --runtime fakecx 2>&1); etok=$(tokof_ "$out")
"$DA" provider disable en2 --runtime fakecx --plan "$etok" --approved "last one" >/dev/null 2>&1
[ "$(answers_of en2)" = '{"local":[]}' ] && [ "$("$DA" provider runtimes en2)" = "primary claude-code" ] && ok "an empty list is no extra runtime" || no "empty list: $(answers_of en2)"

# the refusals of the plan
check_unusable() { # NAME WHY: the code, its field, exit 1, no token, nothing stored
  local out rc
  out=$(EN en3 --runtime "$1" 2>&1); rc=$?
  { [ "$rc" = 1 ] && grep -q '"code":"runtime-unusable"' <<<"$out" && grep -q "name=$1 why=$2" <<<"$out" && ! grep -q '^plan token' <<<"$out" && [ "$(answers_of en3)" = '"none"' ]; } \
    && ok "runtime-unusable $2: $1" || no "unusable $1: rc=$rc $out"
}
mkproj en3 "$CC"
fake_runtime "$SRC" "$TOOL" fakeinsession local
check_unusable claude-code is-primary
check_unusable fakeinsession not-command
check_unusable claude-platform not-local
mkdir -p "$T/c/packs/providers"
out=$(python3 -I "$TOOL/lib/provider.py" new draftcx --kind provider --from command 2>&1)
python3 -I "$TOOL/lib/provider.py" new draftcx --kind provider --from command --plan "$(tokof_ "$out")" --approved "a draft for the test" >/dev/null 2>&1 || no "the draft pack was not made"
check_unusable draftcx not-sealed
out=$(EN en3 --runtime nosuchcx 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q "no runtime 'nosuchcx'" <<<"$out"; } && ok "an unknown runtime is refused naming the list" || no "unknown: rc=$rc $out"
out=$(EN en3 --runtime 'a b' 2>&1); rc=$?
[ "$rc" = 2 ] && ok "a bad runtime name is a usage error (exit 2)" || no "bad name: rc=$rc $out"
out=$(EN nosuch --runtime fakecx 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "no stored answers for project 'nosuch'" <<<"$out" && ok "no such project is refused" || no "no project: rc=$rc $out"
mkproj en4 '{"cloud":"claude-platform"}'
out=$(EN en4 --runtime fakecx 2>&1); rc=$?
[ "$rc" = 2 ] && ok "a project with no local runtime is refused (exit 2)" || no "no local runtime: rc=$rc $out"

# link sources: missing, inside ~/.codex, none; the plan prints the verdict and no token
mkproj en5 "$CC"
mv "$HOME/.fakecx-members/auth.json" "$HOME/.fakecx-members/auth.gone"
out=$(EN en5 --runtime fakecx 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q ': missing, not inside ~/.codex' <<<"$out" && grep -q 'does not exist' <<<"$out" && ! grep -q '^plan token' <<<"$out"; } \
  && ok "link-source-missing: the plan says missing, the refusal is the one prepare gives, and no token is printed" || no "missing: rc=$rc $out"
mv "$HOME/.fakecx-members/auth.gone" "$HOME/.fakecx-members/auth.json"
mkdir -p "$HOME/.codex"; echo '{}' > "$HOME/.codex/auth.json"
mkdir -p "$HOME/.fakeln-members"; ln -s "$HOME/.codex/auth.json" "$HOME/.fakeln-members/auth.json"
fake_command_runtime "$SRC" "$TOOL" fakeln
out=$(EN en5 --runtime fakeln 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'refused: the sign-in ~/.fakeln-members/auth.json for fakeln member runs resolves inside ~/.codex' <<<"$out" && ! grep -q '^plan token' <<<"$out" && [ "$(answers_of en5)" = '"none"' ]; } \
  && ok "link-source-refused-in-plan: a link source that resolves into ~/.codex (through a link) is refused by the plan, with no token" || no "inside .codex: rc=$rc $out"
mkdir -p "$HOME/.fakedir-members"; ln -s "$HOME/.codex" "$HOME/.fakedir-members/real"
fake_command_runtime "$SRC" "$TOOL" fakedir '.dispatch.home.link = [{from: "~/.fakedir-members/real/auth.json", to: "auth.json"}]'
out=$(EN en5 --runtime fakedir 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'resolves inside ~/.codex' <<<"$out" && ! grep -q '^plan token' <<<"$out"; } && ok "link-source-symlink-into: a source below a link to ~/.codex is refused too" || no "symlink dir: rc=$rc $out"
fake_command_runtime "$SRC" "$TOOL" fakenolink '.dispatch.home.link = []'
out=$(EN en5 --runtime fakenolink 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^links: none$' <<<"$out" && ! grep -q 'run one at a time' <<<"$out" && grep -q '^plan token' <<<"$out"; } && ok "a runtime with no link prints links: none" || no "links none: rc=$rc $out"

# the answer is gated: no project verb stores it
mkproj en6 "$CC"
cp "$T/c/projects/en6.json" "$T/before.json"
"$DA" project set en6 models.extra_runtimes.local '["fakecx"]' >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider enable PROJECT --runtime NAME' "$T/o" && cmp -s "$T/before.json" "$T/c/projects/en6.json"; } && ok "project set refuses models.extra_runtimes and names the verb" || no "project set: rc=$rc $(cat "$T/o")"
"$DA" project set en6 models '{"provider":{"local":"claude-code"},"extra_runtimes":{"local":["fakecx"]}}' >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 2 ] && cmp -s "$T/before.json" "$T/c/projects/en6.json"; } && ok "nor as a key of a whole models object" || no "project set models: rc=$rc $(cat "$T/o")"
jq '.models.extra_runtimes = {local: ["fakecx"]}' "$T/before.json" > "$T/new.json"
"$DA" project init en6 --answers "$T/new.json" --force >"$T/o" 2>&1; rc=$?
{ [ "$rc" != 0 ] && cmp -s "$T/before.json" "$T/c/projects/en6.json"; } && ok "project init --answers does not add it either" || no "project init: rc=$rc $(cat "$T/o")"
"$DA" project unset en6 models.extra_runtimes >"$T/o" 2>&1; rc=$?
[ "$rc" -le 2 ] && ok "unset of an answer that is not there changes nothing" || no "unset: rc=$rc"
python3 -I "$TOOL/lib/gated_answers.py" store en6 models.extra_runtimes '["fakecx"]' --conf "$T/c" >/dev/null 2>&1 && no "gated_answers stored a path it was not given" || ok "gated_answers stores models.extra_runtimes.local and no other path of it"

# project validate: the shape of the answer is checked, what can change outside the answers is a finding
vproj() { # NAME EXTRAS-JSON
  mkproj "$1" "$CC" "$2"
}
vproj v1 '["fakecx","fakecx"]'
vproj v2 '["claude-code"]'
vproj v3 '"fakecx"'
vproj v4 '["bad name"]'
for p in v1 v2 v3 v4; do "$DA" project validate "$p" >"$T/o" 2>&1; rc=$?; [ "$rc" = 1 ] && ok "validate refuses models.extra_runtimes.local of $p: $(head -1 "$T/o" | cut -c1-100)" || no "validate $p: rc=$rc $(cat "$T/o")"; done
jq '.models.extra_runtimes.cloud = ["x"]' "$T/c/projects/en1.json" > "$T/v5.json"
"$DA" project validate "$T/v5.json" 2>&1 | grep -q 'models.extra_runtimes.cloud: not a surface with extra runtimes' && ok "only the local surface has extra runtimes" || no "validate cloud extras"
vproj f1 '["nosuchcx","fakeinsession","claude-platform","draftcx","fakecx"]'
out=$("$DA" project validate f1 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^finding: models.extra_runtimes.local 'nosuchcx' cannot be used: no runtime 'nosuchcx'" <<<"$out" \
  && grep -q "^finding: models.extra_runtimes.local 'fakeinsession' cannot be used: not-command" <<<"$out" && grep -q "^finding: models.extra_runtimes.local 'claude-platform' cannot be used: not-local" <<<"$out" \
  && grep -q "^finding: models.extra_runtimes.local 'draftcx' cannot be used: not-sealed" <<<"$out" && ! grep -q "'fakecx'" <<<"$out"; } && ok "an extra that is unknown, in-session, not local or unsealed is a finding, and a usable one is none" || no "findings: rc=$rc $out"

exit $fail
