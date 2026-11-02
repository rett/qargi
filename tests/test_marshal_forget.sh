#!/usr/bin/env bash
# qargi marshal forget NAME: the owner drops this machine's accepted high-water mark of a feature, so that a stale mark (left after the
# feature was deleted or re-created on the remote) stops reporting "rollback detected". Hermetic: a scratch bare origin in a temp dir and
# machines with their own HOME, QARGI_CONF, QARGI_STATE and clone of it; nothing leaves the temp dir. Run: tests/test_marshal_forget.sh
#
# Interface this test fixes:
#   - `marshal forget NAME [--project P]` without options prints a plan (the rev and the oid of the mark it would drop) and `plan token: TOK`
#     and changes nothing; it applies with `--plan TOK --approved WORDS` (any of the two missing, a wrong token, or a mark that changed
#     since the plan is refused); audit line `marshal:forget` with the words.
#   - exit 2 with a message when integrity is off (also when the project is not enabled), when there is no mark for NAME, when the mark
#     file is unusable, and in a member run. Only the mark of NAME goes; the others stay.
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
unset GIT_TERMINAL_PROMPT
ORIGIN=$T/origin.git
WORDS="the stale mark is safe to drop"
mkdir -p "$T/m"

git init -q --bare "$ORIGIN"
git init -q -b master "$T/seed"; echo 0.1.0 > "$T/seed/VERSION"
git -C "$T/seed" add -A && git -C "$T/seed" commit -q -m one && git -C "$T/seed" branch develop
git -C "$T/seed" remote add origin "$ORIGIN" && git -C "$T/seed" push -q origin master develop
mk() { # NAME: a machine with its own home, conf, state and a clone of the origin
  local d=$T/m/$1
  mkdir -p "$d/home" "$d/c/projects" "$d/s"
  git clone -q "$ORIGIN" "$d/app" && git -C "$d/app" branch develop origin/develop >/dev/null 2>&1
  env HOME="$d/home" QARGI_CONF="$d/c" QARGI_STATE="$d/s" "$DA" project template app \
    | jq --arg p "$d/app" '.repo.path = $p | .repo.url = "https://github.com/acme/app" | .methodology = "gitflow" | .test_command = "true"' > "$d/c/projects/app.json"
}
# the machines run from their own directory, never from the checkout this test sits in (which may itself be a member's run directory)
XE() { local m=$1; shift; cd "${XD:-$T/m/$m}" && env HOME="$T/m/$m/home" QARGI_CONF="$T/m/$m/c" QARGI_STATE="$T/m/$m/s" "$DA" "$@" >"$T/o" 2>"$T/e"; }
out() { cat "$T/o" "$T/e"; }
S() { echo "$T/m/$1/s"; }
MK() { echo "$(S "$1")/features/.accepted-app.json"; }
tokof() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' "$T/o"; }
OWN() { local m=$1 tk; shift; XE "$m" marshal "$@"; tk=$(tokof); [ -n "$tk" ] || return 97; XE "$m" marshal "$@" --plan "$tk" --approved "$WORDS"; }
OG() { git --git-dir="$ORIGIN" "$@"; }
oref() { OG rev-parse -q --verify "$1" 2>/dev/null || echo none; }
fb() { local n d; for n in "$@"; do for d in "$T"/m/*; do git -C "$d/app" branch "feature/$n" develop; done; done; }
mark() { jq -c --arg n "$2" '.[$n] // empty' "$(MK "$1")" 2>/dev/null; }   # MACHINE NAME: [rev,"oid"]

mk a; mk b; mk c
mkdir -p "$(S a)/features" "$(S b)/features" "$(S c)/features"
fb f1 f2
# a: shared refs, a key, itself trusted, integrity advisory (its own writes are signed and become its accepted marks)
OWN a key init --principal alice@ms >/dev/null 2>&1; LA=$(grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/o" | sed 's/^[[:space:]]*//')
XE a marshal enable; tk=$(tokof); XE a marshal enable --plan "$tk" --approved "$WORDS"
OWN a signers add --line "$LA" >/dev/null 2>&1
OWN a enable --integrity advisory >/dev/null 2>&1
XE a marshal claim f1 --as alice --goal one >/dev/null 2>&1; R1=$(oref refs/qargi/features/f1)
XE a marshal set f1 --as alice --goal two >/dev/null 2>&1
XE a marshal set f1 --as alice --goal three >/dev/null 2>&1; R3=$(oref refs/qargi/features/f1)
XE a marshal claim f2 --as alice --goal other >/dev/null 2>&1; R2=$(oref refs/qargi/features/f2)
[ "$(mark a f1)" = "[3,\"$R3\"]" ] && [ -n "$(mark a f2)" ] && ok "setup: the machine holds marks for f1 (rev 3) and f2" || no "setup: marks $(cat "$(MK a)" 2>&1)"

# the remote has f1 rewound to its first record: the stale-mark situation
OG update-ref refs/qargi/features/f1 "$R1"
XE a marshal status f1
grep -q 'rollback detected' <(out) && ok "before: a status of f1 reports rollback detected" || no "setup: expected a rollback: $(out)"

# plan: prints the mark, a token, changes nothing
cp "$(MK a)" "$T/mk.before"
XE a marshal forget f1; r0=$?; tk=$(tokof)
{ [ $r0 = 0 ] && [ -n "$tk" ] && grep -q 'rev 3' <(out) && grep -q "$R3" <(out) && cmp -s "$(MK a)" "$T/mk.before"; } \
  && ok "plan: forget f1 prints the mark (rev 3 and its oid) and a token and drops nothing" || no "plan (rc=$r0, token '$tk'): $(out)"

# gates
XE a marshal forget f1 --approved "$WORDS"; r1=$?
XE a marshal forget f1 --plan "$tk"; r2=$?
XE a marshal forget f1 --plan 000000000000 --approved "$WORDS"; r3=$?
{ [ $r1 != 0 ] && [ $r2 != 0 ] && [ $r3 != 0 ] && grep -q 'plan changed' "$T/e" && ! grep -qi usage "$T/e" && cmp -s "$(MK a)" "$T/mk.before"; } \
  && ok "gates: refused without the token, without the words and with a wrong token; the marks are untouched" || no "gates (rc $r1 $r2 $r3)"

# the token covers the mark: a mark that changed after the plan is another plan
jq --arg o "$R2" '.f1 = [3, $o]' "$T/mk.before" > "$(MK a)"
XE a marshal forget f1 --plan "$tk" --approved "$WORDS"; r1=$?
jq --arg o "$R3" '.f1 = [4, $o]' "$T/mk.before" > "$(MK a)"
XE a marshal forget f1 --plan "$tk" --approved "$WORDS"; r2=$?
{ [ $r1 != 0 ] && [ $r2 != 0 ] && grep -q 'plan changed' "$T/e" && [ -n "$(mark a f1)" ]; } \
  && ok "token: applying the plan of an earlier mark (another oid, another rev) is refused and nothing is dropped" || no "token covers the mark (rc $r1 $r2): $(out)"
cp "$T/mk.before" "$(MK a)"

# apply
OWN a forget f1; rc=$?
{ [ $rc = 0 ] && [ -z "$(mark a f1)" ] && [ "$(mark a f2)" = "[1,\"$R2\"]" ]; } \
  && ok "apply: with the token and the words the mark of f1 is gone and the mark of f2 stays" || no "apply (rc=$rc): $(out); $(cat "$(MK a)")"
jq -e --arg w "$WORDS" 'select(.verb == "marshal:forget" and .approved == $w)' "$(S a)/audit.log" >/dev/null 2>&1 \
  && ok "apply: audited as marshal:forget with the words" || no "audit: $(tail -3 "$(S a)/audit.log" 2>&1)"
XE a marshal status f1
{ ! grep -q 'rollback detected' <(out) && grep -q one <(out); } && ok "after: status of f1 no longer reports a rollback (it trusts what it sees again)" || no "after forget: $(out)"

# refusals
XE a marshal forget f3; r1=$?; tk=$(tokof)
XE a marshal forget f3 --plan 000000000000 --approved "$WORDS"; r2=$?
{ [ $r1 = 2 ] && [ $r2 = 2 ]; } && [ -z "$tk" ] && grep -qi 'no accepted mark' "$T/e" && ok "refuse: a name with no mark exits 2 with a message, in the plan and in the apply" || no "no mark (rc $r1 $r2, token '$tk'): $(out)"
XE a marshal forget f2 extra; r3=$?; u3=$(cat "$T/e")
XE a marshal forget; r1=$?; u1=$(cat "$T/e")
XE a marshal forget 'bad/name'; r2=$?
{ [ $r1 = 2 ] && [ $r2 = 2 ] && [ $r3 = 2 ]; } && grep -qi usage <<<"$u1" && grep -qi usage <<<"$u3" && [ -n "$(mark a f2)" ] && ok "refuse: a missing NAME, an invalid NAME and a second argument exit 2" || no "usage (rc $r1 $r2 $r3)"

# integrity off: enabled without integrity (b) and not enabled at all (c); a hand-made mark file stays
printf '{"f1": [2, "%s"]}\n' "$R3" > "$(MK b)"; cp "$(MK b)" "$(MK c)"
XE b marshal enable; tkb=$(tokof); XE b marshal enable --plan "$tkb" --approved "$WORDS"
XE b marshal forget f1; r1=$?; eb=$(cat "$T/e")
XE b marshal forget f1 --plan 000000000000 --approved "$WORDS"; r2=$?
XE c marshal forget f1; r3=$?; ec=$(cat "$T/e")
{ [ $r1 = 2 ] && [ $r2 = 2 ] && [ $r3 = 2 ] && grep -qi 'integrity advisory or strict' <<<"$eb" && grep -qi 'integrity advisory or strict' <<<"$ec" && [ -n "$(mark b f1)" ] && [ -n "$(mark c f1)" ]; } \
  && ok "refuse: with integrity off (enabled without it, or not enabled) it exits 2 naming the integrity and keeps the mark" || no "integrity off (rc $r1 $r2 $r3): $eb / $ec"

# an unusable mark file is not read as empty and not replaced
printf 'not json' > "$(MK a)"; cp "$(MK a)" "$T/mk.bad"
XE a marshal forget f2; r1=$?
{ [ $r1 = 2 ] && grep -qi 'not valid JSON' "$T/e" && cmp -s "$(MK a)" "$T/mk.bad"; } && ok "refuse: a damaged mark file exits 2 and is left as it is" || no "damaged mark file (rc $r1): $(out)"
rm -f "$(MK a)"; ln -s "$T/mk.before" "$(MK a)"
XE a marshal forget f2; r1=$?
{ [ $r1 = 2 ] && grep -qi 'symlink' "$T/e" && ! grep -qi usage "$T/e" && [ -L "$(MK a)" ] && [ -n "$(jq -c .f2 "$T/mk.before")" ]; } && ok "refuse: a symlinked mark file is neither read nor written through" || no "symlinked mark file (rc $r1): $(out)"
rm -f "$(MK a)"; cp "$T/mk.before" "$(MK a)"

# a member run
mkdir -p "$T/run/work"; echo build > "$T/run/ability"; : > "$T/run/refs.before"
cp "$(MK a)" "$T/mk.a.before"; good=1
XD=$T/run/work XE a marshal forget f1; rc=$?; { [ $rc = 2 ] && grep -qi member "$T/e"; } || { good=0; no "member: forget rc=$rc: $(out)"; }
XD=$T/run/work XE a marshal forget f1 --plan 000000000000 --approved w; [ $? = 2 ] || good=0
XD=$T/run/work XE a marshal forget f2 --approved "$WORDS"; [ $? = 2 ] || good=0
[ $good = 1 ] && cmp -s "$(MK a)" "$T/mk.a.before" && ok "member: forget, even with a token and words, exits 2 and leaves the marks alone" || no "member run (good=$good)"

echo
[ $fail = 0 ] && echo "marshal forget: all ok" || echo "marshal forget: FAILURES"
exit $fail
