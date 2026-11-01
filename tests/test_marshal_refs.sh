#!/usr/bin/env bash
# qargi marshal, slice 2: the shared refs backend (refs/qargi/features/NAME on the project's origin). Written from the SPEC of the
# feature, not from its code. Everything is local: a scratch bare origin in a temp dir, several "machines" (each with its own
# HOME, QARGI_CONF, QARGI_STATE and clone of that origin), and a git shim first on PATH that logs every push and fetch qargi runs
# (and can delay them, or run a command right after a fetch, to make a race deterministic). Time is injected: the taker's own
# monotonic clock with QARGI_MARSHAL_MONO (seconds), the wall clock with QARGI_MARSHAL_NOW. Nothing leaves the temp dir.
# Run: tests/test_marshal_refs.sh
#
# Interfaces beyond the spec's wording that this test ASSUMES (the commit message of this file lists them as well):
#   - `qargi marshal enable` with neither --plan nor --approved prints a line `plan token: TOK` (like `project new`); applying
#     is `enable --plan TOK --approved WORDS`; either of the two missing, or a wrong token, is refused (exit nonzero).
#   - `qargi marshal disable` takes no option, exits 0 and audits `marshal:disable`.
#   - a refused enable/disable or mutating verb inside a member run exits 2 and says "member" on stderr; a member run is the
#     current directory at or below a directory holding the files `ability` and `refs.before`.
#   - the local record of a claim not yet pushed has `.state == "provisional"`; it is not provisional afterwards.
#   - the cache of the remote refs is the repository's own refs/refs/qargi/* (the fetch refspec +refs/qargi/*:refs/qargi/*).
#   - a remote record or ref that is ignored is named in a stderr warning (the word "warning" and the ref's last name).
#   - `qargi marshal status ... --no-fetch` exists (the session hook uses it).
#   - `python3 -I lib/marshal_refs.py push-check REF` exits 0 for a ref marshal_push may push and 2 for any other, running no git.
#   - the "remote not checked" notice is printed on stdout or stderr; offline, a claim exits whatever it likes but stays
#     provisional, and the next mutating verb (renew) completes it or drops it.
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; TOOL=$PWD
trap 'jobs -p | xargs -r kill 2>/dev/null; rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
unset GIT_TERMINAL_PROMPT
REALGIT=$(command -v git)
git() { "$REALGIT" "$@"; }                 # the test's own git is never logged or delayed by the shim
ORIGIN=$T/origin.git; LOG=$T/shim.log; : > "$LOG"
mkdir -p "$T/m" "$T/shimbin" "$T/slow" "$T/hooks"
WORDS="the shared refs are fine for this project"

# --- the git shim: logs push, fetch, pull, ls-remote and clone as `SUB<TAB>prompt=<GIT_TERMINAL_PROMPT><TAB>cwd<TAB>args after SUB`
cat > "$T/shimbin/git" <<SHIM
#!/usr/bin/env bash
key=\$(printf '%s' "\$HOME" | tr / _)
sub=''; i=0; skip=0
for a in "\$@"; do
  i=\$((i + 1))
  if [ \$skip = 1 ]; then skip=0; continue; fi
  case \$a in -C|-c) skip=1;; -*) ;; *) sub=\$a; break;; esac
done
case \$sub in
  push|fetch|pull|ls-remote|clone)
    printf '%s\t%s\t%s\t%s\n' "\$sub" "prompt=\${GIT_TERMINAL_PROMPT-unset}" "\$PWD" "\${*:\$((i + 1))}" >> "$LOG"
    if [ -f "$T/slow/\$key" ] && grep -qw "\$sub" "$T/slow/\$key"; then exec sleep 30; fi;;
esac
"$REALGIT" "\$@"; rc=\$?
if [ "\$sub" = fetch ] && [ -f "$T/hooks/\$key" ]; then   # a command to run right after this machine's next fetch (once)
  mv "$T/hooks/\$key" "$T/hooks/\$key.run"; bash "$T/hooks/\$key.run" >/dev/null 2>&1
fi
exit \$rc
SHIM
chmod +x "$T/shimbin/git"; export PATH=$T/shimbin:$PATH
nsub() { local n; n=$(grep -c "^$1	" "$LOG" 2>/dev/null); echo "${n:-0}"; }   # count of logged pushes / fetches
nall() { wc -l < "$LOG"; }

# --- the origin, seeded from a scratch repository, and the machines
git init -q --bare "$ORIGIN"
git init -q -b master "$T/seed"; echo 0.1.0 > "$T/seed/VERSION"
git -C "$T/seed" add -A && git -C "$T/seed" commit -q -m one && git -C "$T/seed" branch develop
git -C "$T/seed" remote add origin "$ORIGIN" && git -C "$T/seed" push -q origin master develop
mk() { # NAME: a machine with its own home, conf, state and a clone of the origin
  local d=$T/m/$1
  mkdir -p "$d/home" "$d/c/projects" "$d/s"
  git clone -q "$ORIGIN" "$d/app" && git -C "$d/app" branch develop origin/develop >/dev/null 2>&1
  # a valid project (the template has a role, the models and a budget), pointed at this machine's clone
  env HOME="$d/home" QARGI_CONF="$d/c" QARGI_STATE="$d/s" "$DA" project template app \
    | jq --arg p "$d/app" '.repo.path = $p | .repo.url = "https://github.com/acme/app" | .methodology = "gitflow" | .test_command = "true"' > "$d/c/projects/app.json"
}
# XE MACHINE [VAR=val...] ARGS...: qargi as that machine, output in $T/o and $T/e, the exit status returned
XE() {
  local m=$1; shift; local -a ev=()
  while [[ ${1:-} =~ ^[A-Z_]+= ]]; do ev+=("$1"); shift; done
  env HOME="$T/m/$m/home" QARGI_CONF="$T/m/$m/c" QARGI_STATE="$T/m/$m/s" "${ev[@]}" "$DA" "$@" >"$T/o" 2>"$T/e"
}
out() { cat "$T/o" "$T/e"; }
S() { echo "$T/m/$1/s"; }                  # the state directory of a machine
fb() { local n d; for n in "$@"; do for d in "$T"/m/*; do git -C "$d/app" branch "feature/$n" develop; done; done; }   # the branch on every machine
en() { # MACHINE: switch the machine to the refs backend the way an owner does (plan, then apply with the token and words)
  local tk; XE "$1" marshal enable; tk=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' "$T/o")
  XE "$1" marshal enable --plan "$tk" --approved "$WORDS"
}
OG() { git --git-dir="$ORIGIN" "$@"; }
oref() { OG rev-parse -q --verify "$1" 2>/dev/null || echo none; }          # an origin ref's oid, or none
ocount() { OG rev-list --count "$1" 2>/dev/null || echo 0; }
orec() { OG cat-file -p "$1:record.json" 2>/dev/null; }                    # the record at a ref of the origin
lref() { git -C "$T/m/$1/app" for-each-ref "$2"; }                          # a machine's local refs
hook_after_fetch() { # TARGET SRC ARGS...: right after TARGET's next fetch, run qargi as SRC with ARGS
  local t=$1 s=$2; shift 2
  { printf 'env HOME=%q QARGI_CONF=%q QARGI_STATE=%q QARGI_PROJECT=app %q' "$T/m/$s/home" "$T/m/$s/c" "$T/m/$s/s" "$DA"; printf ' %q' "$@"; echo; } > "$T/hooks/$(printf '%s' "$T/m/$t/home" | tr / _)"
}
slow() { printf '%s\n' "$2" > "$T/slow/$(printf '%s' "$T/m/$1/home" | tr / _)"; }       # SLOW MACHINE "fetch push": those git verbs hang
unslow() { rm -f "$T/slow/$(printf '%s' "$T/m/$1/home" | tr / _)"; }

mk a; mk b
fb off0 f1 f2 f3 f4 f5 r6 r8 r8u tk tw1 tw2 tb fin fa off1 off2 off3 gh1 loc1 mr1 pc1
TTL=900

# ============================================================ (1) off by default
XE a marshal claim off0 --as alice --goal local; rc=$?
[ $rc = 0 ] && ok "default: a claim works in the local mode" || no "SPEC default claim must work locally (rc=$rc): $(out)"
[ -z "$(OG for-each-ref refs/qargi)" ] && [ -z "$(lref a refs/qargi)" ] && [ "$(nsub push)" = 0 ] \
  && ok "default: no refs/qargi on the origin or locally and the git shim logged no push" \
  || no "SPEC default: marshal is local until enabled; origin: $(OG for-each-ref refs/qargi); local: $(lref a refs/qargi); pushes: $(nsub push)"

# ============================================================ (2) enable
XE a marshal enable; tk=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' "$T/o")
[ -n "$tk" ] && ok "enable: without options it prints the plan and a plan token" || no "SPEC enable: a plan token line 'plan token: TOK' is expected without --plan/--approved: $(out)"
EN=$(S a)/marshal/app.enabled
XE a marshal enable --approved "$WORDS"; r1=$?; e1=$([ -e "$EN" ] && echo yes || echo no)
XE a marshal enable --plan "${tk:-none}"; r2=$?; e2=$([ -e "$EN" ] && echo yes || echo no)
XE a marshal enable --plan 000000000000 --approved "$WORDS"; r3=$?; e3=$([ -e "$EN" ] && echo yes || echo no)
XE a marshal enable --plan "${tk:-none}" --approved "$WORDS"; rc=$?
if [ $rc = 0 ]; then
  ok "enable: ok with the plan token and the words"
  for c in "1:without the plan token:$r1:$e1" "2:without words (--approved):$r2:$e2" "3:with a wrong plan token:$r3:$e3"; do
    IFS=: read -r _ what r e <<<"$c"
    [ "$r" != 0 ] && [ "$e" = no ] && ok "enable: refused $what (exit $r), nothing enabled" || no "SPEC enable must be refused $what (rc=$r, enabled file: $e)"
  done
else
  no "SPEC enable --plan TOK --approved W must exit 0 (rc=$rc): $(out)"
  no "SPEC enable refusals (no token / no words / wrong token: rc $r1 $r2 $r3) cannot be judged while enable itself is unknown or fails"
fi
jq -e --arg w "$WORDS" '.backend == "refs" and (.remote | type == "string" and length > 0) and (.enabled_at | length > 0) and .words == $w' "$EN" >/dev/null 2>&1 \
  && ok "enable: \$STATE/marshal/app.enabled holds backend, remote, enabled_at and the words" || no "SPEC enable state file $EN: $(cat "$EN" 2>&1)"
jq -e --arg w "$WORDS" 'select(.verb == "marshal:enable" and .approved == $w)' "$(S a)/audit.log" >/dev/null 2>&1 \
  && ok "enable: an audit line marshal:enable with the words" || no "SPEC enable audit line: $(cat "$(S a)/audit.log" 2>&1)"
cp "$T/m/a/c/projects/app.json" "$T/app.before"
XE a project set app marshal.backend refs; rc=$?
[ $rc != 0 ] && cmp -s "$T/m/a/c/projects/app.json" "$T/app.before" && ok "project set: marshal.backend is not a project answer (refused, file unchanged)" || no "SPEC project set app marshal.backend refs must be refused (rc=$rc): $(out)"
XE a project set app marshal.ttl 15; rc=$?
[ $rc = 0 ] && ok "project set: marshal.ttl is still allowed" || no "SPEC project set marshal.ttl must stay allowed (rc=$rc): $(out)"
en b

# ============================================================ (3) the claim is one commit with record.json only
XE a marshal claim f1 --as alice --goal "ship the thing"; rc=$?
[ $rc = 0 ] && ok "claim: exit 0 with the refs backend" || no "claim f1 (rc=$rc): $(out)"
F1=refs/qargi/features/f1
[ "$(ocount $F1)" = 1 ] && [ "$(OG ls-tree -r --name-only $F1 2>/dev/null)" = record.json ] \
  && ok "claim: refs/qargi/features/f1 is ONE commit whose tree holds only record.json" || no "SPEC claim: one commit, tree = record.json only (count: $(ocount $F1), tree: $(OG ls-tree -r --name-only $F1 2>&1))"
orec $F1 | jq -e '.feature == "f1" and .lead.id == "alice" and .goal == "ship the thing" and ((.state // "") != "provisional")' >/dev/null 2>&1 \
  && ok "claim: the pushed record is led by alice and is not provisional" || no "SPEC claim record: $(orec $F1)"
F1_A=$(oref $F1)

# ============================================================ (4) a plain fetch does not bring refs/qargi, marshal status does
git -C "$T/m/b/app" fetch -q origin
[ -z "$(lref b refs/qargi)" ] && ok "fetch: a plain git fetch on machine B does not bring refs/qargi" || no "plain fetch brought refs/qargi: $(lref b refs/qargi)"
XE b marshal status f1 --as bob; rc=$?
[ $rc = 0 ] && grep -q alice <(out) && ok "status on B shows the record of f1 (lead alice)" || no "SPEC status on B must fetch refs/qargi and show f1 led by alice (rc=$rc): $(out)"
[ "$(git -C "$T/m/b/app" rev-parse -q --verify "$F1" 2>/dev/null)" = "$F1_A" ] && ok "status: B's cache is the repository's own refs/qargi/features/f1" || no "SPEC status: refs/qargi/features/f1 in B's repository should equal the origin's"

# ============================================================ (5) one commit per update, linear
prev=$(oref $F1); okc=1
for step in "set f1 --as alice --goal g2" "set f1 --as alice --note n1" "renew f1 --as alice" "set f1 --as alice --status blocked" "set f1 --as alice --plan p1"; do
  cnt=$(ocount $F1)
  # shellcheck disable=SC2086  # the words of a step
  XE a marshal $step; rc=$?
  now_=$(oref $F1)
  if [ $rc != 0 ] || [ "$(ocount $F1)" != $((cnt + 1)) ] || [ "$(OG rev-parse -q --verify "$F1^" 2>/dev/null)" != "$prev" ]; then
    okc=0; no "SPEC one commit per update: '$step' rc=$rc count $cnt -> $(ocount $F1), parent $(OG rev-parse -q --verify "$F1^" 2>&1) vs $prev: $(out)"
  fi
  prev=$now_
done
[ $okc = 1 ] && [ -z "$(OG rev-list --merges $F1)" ] && ok "updates: five updates are five commits, each the child of the last (linear)" || no "SPEC updates linear (merges: $(OG rev-list --merges $F1 2>&1))"

# ============================================================ (6) deterministic race: stale cache
XE b marshal status --all --brief >/dev/null
XE a marshal claim r6 --as alice; rc=$?; [ $rc = 0 ] || no "setup r6 claim by alice (rc=$rc): $(out)"
R6=$(oref refs/qargi/features/r6)
XE b marshal claim r6 --as bob; rc=$?
[ $rc = 1 ] && grep -q "led by" <(out) && grep -q alice <(out) && [ "$(oref refs/qargi/features/r6)" = "$R6" ] && [ "$R6" != none ] \
  && ok "race: B (stale cache) claims after A: exit 1, 'led by alice', the origin keeps A's oid" || no "SPEC race: rc=$rc, origin $(oref refs/qargi/features/r6) vs $R6: $(out)"

# ============================================================ (7) parallel race: 8 claims released together
RACERS="z1 z2 z3 z4 z5 z6 z7 z8"
for m in $RACERS; do mk "$m"; en "$m" || true; done
fb race
mkfifo "$T/go"; exec 9<>"$T/go"
i=0; pids=''
for m in $RACERS; do
  i=$((i + 1))
  ( read -r -u 9 _; env HOME="$T/m/$m/home" QARGI_CONF="$T/m/$m/c" QARGI_STATE="$T/m/$m/s" "$DA" marshal claim race --as "u$i" >"$T/m/$m.o" 2>"$T/m/$m.e"; echo $? > "$T/m/$m.rc" ) &
  pids="$pids $!"
done
sleep 1; for _ in $RACERS; do echo go >&9; done
# shellcheck disable=SC2086  # the pids
wait $pids
exec 9>&-
wins=0; losers=0
for m in $RACERS; do
  rc=$(cat "$T/m/$m.rc" 2>/dev/null || echo none)
  if [ "$rc" = 0 ]; then wins=$((wins + 1)); elif [ "$rc" = 1 ] && grep -q "led by" "$T/m/$m.o" "$T/m/$m.e"; then losers=$((losers + 1)); fi
done
[ $wins = 1 ] && [ $losers = 7 ] && [ "$(ocount refs/qargi/features/race)" = 1 ] \
  && ok "parallel race: of 8 simultaneous claims exactly one wins (exit 0), 7 exit 1 'led by'; the ref is one commit" \
  || no "SPEC parallel race: wins=$wins losers=$losers count=$(ocount refs/qargi/features/race): $(for m in $RACERS; do echo "$m rc=$(cat "$T/m/$m.rc" 2>&1) $(head -c 150 "$T/m/$m.e" 2>&1)"; done)"
winner=$(orec refs/qargi/features/race | jq -r '.lead.id // "none"')
case $winner in u[1-8]) ok "parallel race: the record's lead is one of the claimants ($winner)";; *) no "SPEC parallel race: the record's lead is $winner";; esac

# ============================================================ (8) CAS: someone pushes between the fetch and the push
XE b marshal status --all --brief >/dev/null
hook_after_fetch b a marshal claim r8 --as alice
XE b marshal claim r8 --as bob; rc=$?
R8=$(oref refs/qargi/features/r8)
[ ! -e "$T/hooks/$(printf '%s' "$T/m/b/home" | tr / _)" ] && [ "$R8" != none ] && [ "$(orec refs/qargi/features/r8 | jq -r .lead.id)" = alice ] && [ "$(ocount refs/qargi/features/r8)" = 1 ] \
  && [ $rc = 1 ] && grep -q "led by" <(out) \
  && ok "CAS (create): A creates the ref between B's fetch and B's push; B refuses (exit 1, 'led by'), origin unchanged by B" || no "SPEC CAS create: rc=$rc, origin $(orec refs/qargi/features/r8), count $(ocount refs/qargi/features/r8): $(out)"
XE b marshal check r8 --as bob; [ $? = 1 ] && ok "CAS (create): B holds no provisional lead afterwards" || no "SPEC CAS: B's check of r8 must refuse (led by alice): $(out)"
# the update: B takes over a stale lead, A renews between B's fetch and push
XE a marshal claim r8u --as alice >/dev/null 2>&1
XE b QARGI_MARSHAL_MONO=0 marshal status r8u --as bob >/dev/null
hook_after_fetch b a marshal renew r8u --as alice
XE b QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover r8u --as bob --approved "$WORDS"; rc=$?
if [ $rc = 1 ] && [ "$(ocount refs/qargi/features/r8u)" = 2 ] && [ "$(orec refs/qargi/features/r8u | jq -r .lead.id)" = alice ]; then
  ok "CAS (update): A renews between B's fetch and B's push; the takeover is refused and the origin keeps A's two commits"
else no "SPEC CAS update: rc=$rc, count $(ocount refs/qargi/features/r8u), lead $(orec refs/qargi/features/r8u | jq -r .lead.id): $(out)"; fi

# ============================================================ (9) takeover on the taker's monotonic clock
XE a marshal claim tk --as alice --goal t >/dev/null 2>&1
TK0=$(oref refs/qargi/features/tk)
XE b QARGI_MARSHAL_MONO=0 marshal status tk --as bob >/dev/null
jq -e --arg o "$TK0" '.tk[0] == $o and .tk[1] == 0 and (.tk[2] | type == "string" and length > 0)' "$(S b)/features/.observed-app.json" >/dev/null 2>&1 \
  && ok "takeover: first seen at mono 0 is cached as [oid, 0, boot id]" || no "SPEC observed cache \$STATE/features/.observed-app.json {name: [oid, first_seen_mono, boot_id]}: $(cat "$(S b)/features/.observed-app.json" 2>&1)"
XE b QARGI_MARSHAL_MONO=$((TTL - 1)) marshal takeover tk --as bob --approved "$WORDS"; rc=$?
[ $rc = 1 ] && [ "$(oref refs/qargi/features/tk)" = "$TK0" ] && ok "takeover: refused one second before the ttl (exit 1), origin unchanged" || no "SPEC takeover at ttl-1 must be refused (rc=$rc): $(out)"
XE a marshal renew tk --as alice; rc=$?
TK1=$(oref refs/qargi/features/tk)
[ $rc = 0 ] && [ "$TK1" != "$TK0" ] || no "setup: A's renew of tk (rc=$rc): $(out)"
XE b QARGI_MARSHAL_MONO=$TTL marshal status tk --as bob >/dev/null
XE b QARGI_MARSHAL_MONO=$((TTL + TTL - 1)) marshal takeover tk --as bob --approved "$WORDS"; rc=$?
[ $rc = 1 ] && [ "$(oref refs/qargi/features/tk)" = "$TK1" ] && ok "takeover: A's renew restarted the timer (refused ttl-1 after the new oid was first seen)" || no "SPEC renew restarts the timer: rc=$rc: $(out)"
XE b QARGI_MARSHAL_MONO=$((TTL + TTL + 1)) marshal takeover tk --as bob; rc=$?
[ $rc != 0 ] && [ "$(oref refs/qargi/features/tk)" = "$TK1" ] && ok "takeover: after the ttl but without words it is refused" || no "SPEC takeover without --approved (rc=$rc): $(out)"
XE b QARGI_MARSHAL_MONO=$((TTL + TTL + 1)) marshal takeover tk --as bob --approved "$WORDS"; rc=$?; rc_to=$rc
[ $rc = 0 ] && [ "$(orec refs/qargi/features/tk | jq -r .lead.id)" = bob ] && [ "$(OG rev-parse -q --verify refs/qargi/features/tk^)" = "$TK1" ] \
  && ok "takeover: after the ttl with words it succeeds as a new commit on A's" || no "SPEC takeover after ttl with words (rc=$rc): $(out)"
[ "$rc_to" = 0 ] && jq -e --arg w "$WORDS" 'select(.verb == "marshal:takeover" and .approved == $w)' "$(S b)/audit.log" >/dev/null 2>&1 \
  && ok "takeover: an audit line marshal:takeover with the words" || no "SPEC takeover audit line: $(cat "$(S b)/audit.log" 2>&1)"
TK2=$(oref refs/qargi/features/tk)
# a lead's wall clock is never compared with another machine's
XE a QARGI_MARSHAL_NOW=$(( $(date +%s) - 86400 )) marshal claim tw1 --as alice >/dev/null 2>&1
TW1=$(oref refs/qargi/features/tw1)
XE b QARGI_MARSHAL_MONO=0 marshal status tw1 --as bob >/dev/null
XE b QARGI_MARSHAL_MONO=$((TTL - 1)) marshal takeover tw1 --as bob --approved "$WORDS"; rc=$?
[ $rc = 1 ] && [ "$(oref refs/qargi/features/tw1)" = "$TW1" ] && [ "$TW1" != none ] && ok "wall clock: A's clock a day in the PAST does not make the lease stale for B" || no "SPEC wall clock must not matter (rc=$rc): $(out)"
XE a QARGI_MARSHAL_NOW=$(( $(date +%s) + 86400 )) marshal claim tw2 --as alice >/dev/null 2>&1
XE b QARGI_MARSHAL_MONO=0 marshal status tw2 --as bob >/dev/null
XE b QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover tw2 --as bob --approved "$WORDS"; rc=$?
[ $rc = 0 ] && [ "$(orec refs/qargi/features/tw2 | jq -r .lead.id)" = bob ] && ok "wall clock: A's clock a day in the FUTURE does not keep the lease alive for B" || no "SPEC wall clock must not matter (rc=$rc): $(out)"
# a changed boot id resets the timer
XE a marshal claim tb --as alice >/dev/null 2>&1
TB=$(oref refs/qargi/features/tb)
XE b QARGI_MARSHAL_MONO=0 marshal status tb --as bob >/dev/null
CACHE=$(S b)/features/.observed-app.json
jq '.tb[2] = "another-boot"' "$CACHE" > "$T/cache.tmp" 2>/dev/null && cp "$T/cache.tmp" "$CACHE"
XE b QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover tb --as bob --approved "$WORDS"; rc=$?
[ $rc = 1 ] && [ "$(oref refs/qargi/features/tb)" = "$TB" ] && ok "boot id: a changed boot id resets the timer (refused though mono is past the ttl)" || no "SPEC boot id change must reset the timer (rc=$rc): $(out)"
XE b QARGI_MARSHAL_MONO=$((TTL + 1 + TTL - 1)) marshal takeover tb --as bob --approved "$WORDS"; rc=$?
[ $rc = 1 ] && ok "boot id: and it counts from the reset (still refused ttl-1 later)" || no "SPEC boot id reset counts afresh (rc=$rc): $(out)"
XE b QARGI_MARSHAL_MONO=$((TTL + 1 + TTL + 1)) marshal takeover tb --as bob --approved "$WORDS"; rc=$?
[ $rc = 0 ] && ok "boot id: and succeeds after the ttl from the reset" || no "SPEC takeover after the reset ttl (rc=$rc): $(out)"

# ============================================================ (10) lost lease: A, after B's takeover of tk
for v in "set tk --as alice --note mine" "renew tk --as alice" "finish tk --as alice"; do
  # shellcheck disable=SC2086  # the words of a verb
  XE a marshal $v; rc=$?
  [ $rc = 1 ] && [ "$(oref refs/qargi/features/tk)" = "$TK2" ] && [ "$(oref refs/qargi/done/tk)" = none ] \
    && ok "lost lease: A's '$v' exits 1 and leaves the origin untouched" || no "SPEC lost lease '$v': rc=$rc, origin $(oref refs/qargi/features/tk) vs $TK2, done: $(oref refs/qargi/done/tk): $(out)"
done

# ============================================================ (11) finish
XE a marshal claim fin --as alice >/dev/null 2>&1; XE a marshal set fin --as alice --note two >/dev/null 2>&1
XE b marshal status --all --brief >/dev/null
LASTFIN=$(oref refs/qargi/features/fin)
XE a marshal finish fin --as alice; rc=$?
[ $rc = 0 ] && [ "$(oref refs/qargi/features/fin)" = none ] && [ "$(OG rev-parse -q --verify refs/qargi/done/fin^ 2>/dev/null)" = "$LASTFIN" ] && [ "$LASTFIN" != none ] \
  && ok "finish: features/fin is gone and done/fin is a child of the last feature commit" || no "SPEC finish (rc=$rc): features $(oref refs/qargi/features/fin), done parent $(OG rev-parse -q --verify refs/qargi/done/fin^ 2>&1) vs $LASTFIN: $(out)"
XE b marshal status --all --brief >/dev/null
[ -z "$(lref b refs/qargi/features/fin)" ] && [ -n "$(lref b refs/qargi/done/fin)" ] && ok "finish: B's next fetch prunes features/fin and brings done/fin" || no "SPEC fetch +refs/qargi/*:refs/qargi/* --prune; B has: $(lref b refs/qargi/ | grep fin)"
# atomic: a pre-receive hook that rejects done/* leaves both refs as they were
XE a marshal claim fa --as alice >/dev/null 2>&1
FA=$(oref refs/qargi/features/fa)
cat > "$ORIGIN/hooks/pre-receive" <<'HOOK'
#!/bin/sh
while read -r old new ref; do case $ref in refs/qargi/done/*) echo "done/* refused by the test hook" >&2; exit 1;; esac; done
exit 0
HOOK
chmod +x "$ORIGIN/hooks/pre-receive"
XE a marshal finish fa --as alice; rc=$?
[ $rc != 0 ] && [ "$(oref refs/qargi/features/fa)" = "$FA" ] && [ "$FA" != none ] && [ "$(oref refs/qargi/done/fa)" = none ] \
  && ok "finish: atomic: when done/fa is rejected, features/fa stays (exit $rc)" || no "SPEC finish is ONE push --atomic (rc=$rc): features $(oref refs/qargi/features/fa), done $(oref refs/qargi/done/fa): $(out)"
rm -f "$ORIGIN/hooks/pre-receive"

# ============================================================ (12) offline
XE b marshal status --all --brief >/dev/null            # B's cache is warm
slow a fetch; slow b fetch
cat > "$ORIGIN/hooks/pre-receive" <<'HOOK'
#!/bin/sh
sleep 5
exit 1
HOOK
chmod +x "$ORIGIN/hooks/pre-receive"
t0=$(date +%s)
XE b QARGI_REMOTE_TIMEOUT=1 marshal status --all --brief; rc=$?
[ $rc = 0 ] && grep -q "remote not checked" <(out) && grep -q "^f1 " "$T/o" && [ $(( $(date +%s) - t0 )) -lt 20 ] \
  && ok "offline: status shows the cache with 'remote not checked' and exits 0" || no "SPEC offline status (rc=$rc): $(out)"
XE a QARGI_REMOTE_TIMEOUT=1 marshal claim off1 --as alice
grep -q "remote not checked" <(out) && ok "offline: the claim says 'remote not checked'" || no "SPEC offline claim must say 'remote not checked': $(out)"
[ "$(jq -r '.state // ""' "$(S a)/features/app-off1.json" 2>/dev/null)" = provisional ] && [ "$(oref refs/qargi/features/off1)" = none ] \
  && ok "offline: the claim stays provisional locally and nothing reached the origin" || no "SPEC offline claim is provisional: $(cat "$(S a)/features/app-off1.json" 2>&1), origin $(oref refs/qargi/features/off1)"
unslow a; unslow b; rm -f "$ORIGIN/hooks/pre-receive"
sleep 6   # the hook of the killed push ends (and rejects) before the origin is used again
XE a marshal renew off1 --as alice; rc=$?
[ $rc = 0 ] && [ "$(orec refs/qargi/features/off1 | jq -r .lead.id)" = alice ] && [ "$(jq -r '.state // ""' "$(S a)/features/app-off1.json" 2>/dev/null)" != provisional ] \
  && ok "offline: the next verb completes the provisional claim" || no "SPEC provisional claim completes on the next verb (rc=$rc), origin $(oref refs/qargi/features/off1): $(out)"
slow a "fetch push"
XE a QARGI_REMOTE_TIMEOUT=1 marshal claim off2 --as alice >/dev/null 2>&1
XE b marshal claim off2 --as bob; rc=$?
[ $rc = 0 ] || no "setup: B claims off2 while A is offline (rc=$rc): $(out)"
unslow a
XE a marshal renew off2 --as alice; rc=$?
[ $rc = 1 ] && grep -q bob <(out) && [ "$(orec refs/qargi/features/off2 | jq -r .lead.id)" = bob ] && [ "$(jq -r '.lead.id // "none"' "$(S a)/features/app-off2.json" 2>/dev/null || echo none)" != alice ] \
  && ok "offline: a provisional claim that B won meanwhile is dropped on A's next verb" || no "SPEC provisional claim dropped when B claimed (rc=$rc): $(out); local: $(cat "$(S a)/features/app-off2.json" 2>&1)"

# ============================================================ (14) member refusal
mkdir -p "$T/run/work"; echo build > "$T/run/ability"; : > "$T/run/refs.before"
n_all=$(nall); good=1
for v in "claim mr1 --as alice" "set mr1 --as alice --note x" "renew f1 --as alice" "release f1 --as alice --note n" "take f1 --as alice" "takeover f1 --as alice --approved w" "finish f1 --as alice" "enable --approved w" "disable"; do
  # shellcheck disable=SC2086  # the words of a verb
  ( cd "$T/run/work" && XE a marshal $v ); rc=$?
  if [ $rc != 2 ] || ! grep -qi member "$T/e"; then good=0; no "SPEC member run: 'marshal $v' must exit 2 and say 'member' on stderr (rc=$rc): $(out)"; fi
done
[ $good = 1 ] && [ "$(nall)" = "$n_all" ] && ok "member: mutating verbs, enable and disable exit 2 and run no git push or fetch" || { [ $good = 1 ] && no "SPEC member run: the shim logged $(( $(nall) - n_all )) git calls"; }
[ -f "$EN" ] && [ "$(oref refs/qargi/features/mr1)" = none ] && ok "member: still enabled, nothing created" || no "member run changed something"
n_all=$(nall); good=1
for v in "status f1" "status --all" "status --all --brief" "status f1 --json" "check" "check f1"; do
  # shellcheck disable=SC2086  # the words of a verb
  ( cd "$T/run/work" && XE a marshal $v ); rc=$?
  [ $rc = 0 ] || { good=0; no "SPEC member run: read verb 'marshal $v' must exit 0 from the cache (rc=$rc): $(out)"; }
done
[ $good = 1 ] && [ "$(nall)" = "$n_all" ] && ok "member: read verbs exit 0 on the cache, without fetch or push" || { [ $good = 1 ] && no "SPEC member run read verbs ran git ($(( $(nall) - n_all )) calls)"; }

# ============================================================ (15) the push ref check
PC=(python3 -I "$TOOL/lib/marshal_refs.py" push-check)
n_all=$(nall)
"${PC[@]}" refs/qargi/features/f1 >"$T/o" 2>"$T/e"; rcv=$?
"${PC[@]}" refs/qargi/done/f1-x2 >/dev/null 2>&1; rcv2=$?
if [ $rcv = 0 ] && [ $rcv2 = 0 ]; then
  ok "push-check: refs/qargi/features/NAME and done/NAME pass"
  for ref in refs/heads/develop refs/qargi/../heads/x "refs/qargi/features/f1:refs/heads/x" "+refs/qargi/features/f1" refs/qargi/x/y/z refs/qargi/features/Bad refs/qargi/features/a--b refs/qargi/features/ "" refs/tags/v1 refs/qargi/features/f1/extra; do
    "${PC[@]}" "$ref" >"$T/o" 2>"$T/e"; rc=$?
    [ $rc = 2 ] && ok "push-check: refused (exit 2): '$ref'" || no "SPEC push-check '$ref' must exit 2 (rc=$rc): $(out)"
  done
  [ "$(nall)" = "$n_all" ] && ok "push-check: runs no git" || no "SPEC push-check ran git"
else
  no "SPEC marshal_push prefix check: 'python3 -I lib/marshal_refs.py push-check REF' must exit 0 for refs/qargi/features/f1 (rc=$rcv) and done/f1-x2 (rc=$rcv2): $(cat "$T/e")"
  no "SPEC push-check cannot judge the hostile names until the valid ones pass (module lib/marshal_refs.py: $(ls "$TOOL/lib/marshal_refs.py" 2>&1))"
fi

# ============================================================ (16) hostile remote records
VALID() { jq -nc --arg f "$1" '{feature:$f, project:"app", status:"active", goal:"hostile", rev:1, lead:{id:"mallory", user:"m", host:"h", since:"2026-01-01T00:00:00Z"}, renewed_at:"2026-01-01T00:00:00Z", updated_at:"2026-01-01T00:00:00Z"}'; }
blob() { printf '%s' "$1" | OG hash-object -w --stdin; }
tree() { while [ $# -gt 0 ]; do printf '%s %s %s\t%s\n' "$1" "$2" "$3" "$4"; shift 4; done | OG mktree; }
plant() { local c; c=$(OG commit-tree -m hostile "$2") && OG update-ref "$1" "$c"; }   # plant REF TREE
good_blob() { blob "$(VALID "$1")"; }
HOSTILE=''
plant refs/qargi/features/hgood "$(tree 100644 blob "$(blob "$(VALID hgood | jq -c '.lead.id = "carol"')")" record.json)"   # the one valid record among them
for bad in Bad_Name a--b -dash x/y; do   # bad names, valid records
  plant "refs/qargi/features/$bad" "$(tree 100644 blob "$(good_blob "$bad")" record.json)"; HOSTILE="$HOSTILE refs/qargi/features/$bad"
done
plant refs/qargi/features/hnorec "$(tree 100644 blob "$(blob x)" other.txt)"
plant refs/qargi/features/hlink "$(tree 120000 blob "$(blob /etc/passwd)" record.json)"
plant refs/qargi/features/hdir "$(tree 040000 tree "$(tree 100644 blob "$(good_blob hdir)" record.json)" record.json)"
plant refs/qargi/features/hbig "$(tree 100644 blob "$(blob "$(jq -nc --argjson r "$(VALID hbig)" --arg pad "$(head -c 70000 /dev/zero | tr '\0' a)" '$r + {pad:$pad}')")" record.json)"
plant refs/qargi/features/hjson "$(tree 100644 blob "$(blob 'this is not json {')" record.json)"
plant refs/qargi/features/harr "$(tree 100644 blob "$(blob '[1,2,3]')" record.json)"
plant refs/qargi/features/hctl "$(tree 100644 blob "$(blob "$(VALID hctl | jq -c '.goal = "x\u001b[31mred\u0007"')")" record.json)"
plant refs/qargi/features/hmis "$(tree 100644 blob "$(blob "$(VALID other)")" record.json)"
plant refs/qargi/features/hextra "$(tree 100644 blob "$(good_blob hextra)" extra.txt 100644 blob "$(good_blob hextra)" record.json)"
HOSTILE="$HOSTILE refs/qargi/features/hnorec refs/qargi/features/hlink refs/qargi/features/hdir refs/qargi/features/hbig refs/qargi/features/hjson refs/qargi/features/harr refs/qargi/features/hctl refs/qargi/features/hmis refs/qargi/features/hextra"
XE b marshal status --all --json; rc=$?
if [ $rc = 0 ] && jq -e . "$T/o" >/dev/null 2>&1 && ! grep -q Traceback "$T/e" && ! grep -q mallory "$T/o" && grep -q carol "$T/o"; then
  ok "hostile: status --all --json is valid JSON, exit 0, no hostile record shown, the valid remote one (carol) is"
else no "SPEC hostile records: rc=$rc json=$(jq -e . "$T/o" >/dev/null 2>&1 && echo valid || echo INVALID) (mallory shown: $(grep -c mallory "$T/o")): $(head -c 600 "$T/e")"; fi
XE b marshal status --all --brief; rc=$?
[ $rc = 0 ] && grep -q '^hgood ' "$T/o" && ! grep -q mallory "$T/o" && ! grep -qE '^(hnorec|hlink|hdir|hbig|hjson|harr|hctl|hmis|hextra|Bad|a--b|-dash|x/y)' "$T/o" && ! LC_ALL=C grep -q '[[:cntrl:]]' <(tr -d '\n\t' < "$T/o") \
  && ok "hostile: --brief lists none of them and prints no control character" || no "SPEC hostile --brief (rc=$rc): $(out)"
miss=''
for r in $HOSTILE; do grep -qi "warn" "$T/e" && grep -q "${r##*/}" "$T/e" || miss="$miss ${r##*/}"; done
[ -z "$miss" ] && ok "hostile: every ignored ref is named in a stderr warning" || no "SPEC hostile: ignored with a warning; no warning names:$miss (stderr: $(head -c 800 "$T/e"))"
XE b marshal status hnorec; [ $? != 0 ] && ! grep -q Traceback "$T/e" && ok "hostile: asking for an ignored feature by name is a plain refusal, no crash" || no "SPEC hostile status NAME: $(out)"
XE b marshal check hjson --as bob; [ $? != 70 ] && ! grep -q Traceback "$T/e" && ok "hostile: check on an ignored feature does not crash" || no "SPEC hostile check: $(out)"
hk=$(printf '{"session_id":"s1"}' | env HOME="$T/m/b/home" QARGI_CONF="$T/m/b/c" QARGI_STATE="$T/m/b/s" bash "$TOOL/lib/hook.sh" session-start --project app 2>/dev/null)
printf '%s' "$hk" | jq -e '.hookSpecificOutput.additionalContext | strings' >/dev/null 2>&1 && ! printf '%s' "$hk" | grep -q mallory \
  && ok "hostile: the session hook still prints valid JSON, without the hostile records" || no "SPEC hostile: hook JSON: ${hk:0:300}"
for r in $HOSTILE refs/qargi/features/hgood; do OG update-ref -d "$r"; done

# ============================================================ (17) read verbs never push
XE a marshal claim gh1 --as alice >/dev/null 2>&1
GH=$(oref refs/qargi/features/gh1)
git -C "$T/m/a/app" branch -q -D feature/gh1                        # the branch is gone: a ghost, which the local mode fixes on a read
slow a "fetch push"; XE a QARGI_REMOTE_TIMEOUT=1 marshal claim off3 --as alice >/dev/null 2>&1; unslow a   # a provisional claim waits
np=$(nsub push); good=1
for who in a b; do
  for v in "status gh1" "status --all" "status --all --brief" "status --all --json" "status off3" "check" "check gh1" "status --all --history --no-fetch" "status --all --brief --no-fetch"; do
    # shellcheck disable=SC2086  # the words of a verb
    XE $who marshal $v >/dev/null 2>&1 || true
    [ "$(nsub push)" = "$np" ] || { good=0; no "SPEC read verbs never push: '$who marshal $v' pushed"; np=$(nsub push); }
  done
done
[ $good = 1 ] && [ "$(oref refs/qargi/features/gh1)" = "$GH" ] && [ "$(oref refs/qargi/features/off3)" = none ] \
  && ok "read verbs: status/check (ghost, provisional claim, --no-fetch included) never push; the origin is as it was" || no "SPEC read verbs: origin gh1 $(oref refs/qargi/features/gh1) vs $GH, off3 $(oref refs/qargi/features/off3)"
nf=$(nsub fetch)
XE a marshal status --all --brief --no-fetch; rc=$?
[ $rc = 0 ] && [ "$(nsub fetch)" = "$nf" ] && ok "read verbs: --no-fetch runs no fetch (the session hook's mode)" || no "SPEC status --no-fetch (rc=$rc, fetches +$(( $(nsub fetch) - nf ))): $(out)"
hk=$(printf '{"session_id":"s2"}' | env HOME="$T/m/a/home" QARGI_CONF="$T/m/a/c" QARGI_STATE="$T/m/a/s" bash "$TOOL/lib/hook.sh" session-start --project app 2>/dev/null)
printf '%s' "$hk" | jq -e . >/dev/null 2>&1 && [ "$(nsub fetch)" = "$nf" ] && [ "$(nsub push)" = "$np" ] \
  && ok "read verbs: the session hook runs no fetch or push and prints valid JSON" || no "SPEC hook uses status --no-fetch: fetches +$(( $(nsub fetch) - nf )), pushes +$(( $(nsub push) - np )), json: ${hk:0:120}"

# ============================================================ (18) disable
F1_NOW=$(oref $F1)
XE a marshal disable; rc=$?; drc=$rc
FOC=$(OG for-each-ref refs/qargi/features | wc -l)
[ $rc = 0 ] && [ ! -e "$EN" ] && jq -e 'select(.verb == "marshal:disable")' "$(S a)/audit.log" >/dev/null 2>&1 \
  && ok "disable: exit 0, the enabled file is gone, an audit line marshal:disable" || no "SPEC disable (rc=$rc, file $(ls "$EN" 2>&1)): $(out); audit: $(tail -2 "$(S a)/audit.log" 2>&1)"
np=$(nsub push)
XE a marshal claim loc1 --as alice; rc=$?
[ $drc = 0 ] && [ $rc = 0 ] && [ "$(nsub push)" = "$np" ] && [ "$(oref refs/qargi/features/loc1)" = none ] && [ "$(OG for-each-ref refs/qargi/features | wc -l)" = "$FOC" ] && [ "$(oref $F1)" = "$F1_NOW" ] \
  && ok "disable: back to the local mode: a claim pushes nothing; the refs on the origin stay" || no "SPEC disable returns to local (rc=$rc): $(out)"
[ -f "$(S a)/features/app-loc1.json" ] && ok "disable: the new claim is a local record" || no "SPEC disable: no local record for loc1"

# ============================================================ (13) every push and fetch qargi made
npu=$(nsub push); nfe=$(nsub fetch)
{ [ "$npu" -gt 0 ] && [ "$nfe" -gt 0 ]; } && ok "audit of the shim log: qargi pushed $npu times and fetched $nfe times" || no "SPEC the refs backend pushes and fetches through git (pushes $npu, fetches $nfe)"
bad=''; set -f
while IFS=$'\t' read -r sub prompt _ args; do
  [ "$prompt" = "prompt=0" ] || bad="$bad [GIT_TERMINAL_PROMPT=${prompt#prompt=}: $sub $args]"
  first=1; lease=0
  for t in $args; do
    case $t in
      --force-with-lease=refs/qargi/*:*) lease=1;;
      --force-with-lease|--force-with-lease=*|--force|-f|--mirror|--all|--tags|--follow-tags) bad="$bad [option $t: $sub $args]";;
      -*) ;;
      *) if [ $first = 1 ]; then first=0; continue; fi
         case $sub in
           push) [[ $t =~ ^[^:+]*:refs/qargi/(features|done)/[a-z0-9]+(-[a-z0-9]+)*$ ]] || bad="$bad [refspec $t: push $args]";;
           fetch) [[ $t =~ ^\+?refs/qargi/[^:]+:refs/qargi/[^:]+$ ]] || bad="$bad [refspec $t: fetch $args]";;
           *) bad="$bad [unexpected git $sub $args]";;
         esac;;
    esac
  done
  [ "$sub" != push ] || [ $lease = 1 ] || bad="$bad [push without --force-with-lease=refs/qargi/...: $args]"
done < "$LOG"
set +f
[ -z "$bad" ] && ok "shim log: every push and fetch has GIT_TERMINAL_PROMPT=0, pushes carry a refs/qargi lease, and all touch only refs/qargi/" || no "SPEC shim log: ${bad:0:1500}"
grep -q "^push.*--atomic" "$LOG" && ok "shim log: finish pushed with --atomic" || no "SPEC shim log: no push --atomic (finish)"
grep -q "^push.*=refs/qargi/features/[a-z0-9-]*:0000000000000000000000000000000000000000" "$LOG" \
  && ok "shim log: a claim leases the zero oid (create-only)" || no "SPEC shim log: no --force-with-lease=REF:<40 zeros> in any push"

echo
[ $fail = 0 ] && echo "marshal refs: all ok" || echo "marshal refs: FAILURES"
exit $fail
