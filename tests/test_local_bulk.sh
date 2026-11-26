#!/usr/bin/env bash
# local list and local clean over many runs: the work done once for all the runs (one process for the merged test, one refs question for the repository), the one-line reason
# of a legacy run clean --applied keeps, and clean --applied --legacy (a plan, a token, the archive of each run's out/ read back before the run is removed). Synthetic runs:
# a few real prepares, turned into legacy runs (no lifecycle marker, no attempt state) by hand, as runs of an older qargi are. Run: tests/test_local_bulk.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
umask 077
unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_AUTHOR_DATE GIT_COMMITTER_DATE
T=$(mktemp -d); trap 'kill_bg; rm -rf "$T" "$HERMETIC"' EXIT; fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm
S=$T/s; DA=./bin/qargi; REPO=$T/r; SCR=$T/scr
mkdir -p "$T/c/projects" "$T/shm" "$SCR" "$T/log"
LC="git -c user.name=t -c user.email=t@example.net"
git init -q -b main "$REPO" && $LC -C "$REPO" commit -q --allow-empty -m one
git init -q --bare "$T/remote.git" && git -C "$REPO" remote add origin "$T/remote.git" && git -C "$REPO" push -q origin main
jq -n --arg p "$REPO" '{schema:1,project:"bulkproj",repo:{url:"https://github.com/example/bulkproj",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/bulkproj.json"

# --- the synthetic runs
newrun() { # SLUG -> the run directory: prepared, one commit in its clone, a manifest and a report, verified (a lifecycle run, as prepare makes them today)
  local o r g c
  o=$($DA local prepare --repo "$REPO" --base main --slug "$1" --scratch "$SCR" 2>/dev/null) || return 1
  r=$(sed -n '1,/^$/s/^RUN=//p' <<<"$o"); g=$(sed -n '1,/^$/s/^GIT=//p' <<<"$o"); c=$(sed -n '1,/^$/s/^CLONE=//p' <<<"$o")
  echo "$1" > "$c/f-$1"; "$g" -C "$c" add "f-$1"; "$g" -C "$c" commit -q -m "work $1"
  echo '{}' > "$r/out/manifest.json"; echo r > "$r/out/report.md"
  $DA local verify "$r" >/dev/null 2>&1 || return 1
  echo "$r"
}
legacy() { # RUN -> turns a lifecycle run into the run an older qargi made: no marker in its registry line, no attempt state, no attempt in the saved copy
  local id=${1##*/}
  jq -c --arg r "$1" 'if .run == $r then del(.lifecycle) else . end' "$S/local-runs.jsonl" > "$S/lr.new" && mv "$S/lr.new" "$S/local-runs.jsonl" && chmod 600 "$S/local-runs.jsonl"
  rm -rf "$S/attempts/$id" "$S/runs/$id/attempt"
  [ ! -f "$S/runs/$id/record.json" ] || { jq -c 'del(.lifecycle)' "$S/runs/$id/record.json" > "$S/runs/$id/record.new" && mv "$S/runs/$id/record.new" "$S/runs/$id/record.json"; }
}
stale() { # RUN -> the run's baseline names a branch that is gone now: the refs differ from what it recorded, as they do for a run made long ago
  local f; for f in refs.before verified; do printf 'local refs/heads/oldgone 1111111111111111111111111111111111111111\n' >> "$1/$f"; done
}
chain=$(git -C "$REPO" rev-parse main)
applied() { # RUN [merged|unmerged] -> RUN/applied and the lead's apply record, the commit on feature/all (merged) or on no branch (unmerged)
  local sha
  sha=$($LC -C "$REPO" commit-tree -p "$chain" -m "applied ${1##*/}" "$(git -C "$REPO" rev-parse 'main^{tree}')")
  printf 'agent/x %s now\n' "$sha" > "$1/applied"
  mkdir -p "$S/apply"; chmod 700 "$S/apply"
  jq -nc --arg run "$1" --arg tip "$sha" '{schema:1,run:$run,branch:"agent/x",tip:$tip,status:"done"}' > "$S/apply/${1##*/}.json"
  if [ "${2:-merged}" = merged ]; then chain=$sha; git -C "$REPO" update-ref refs/heads/feature/all "$sha"; fi
}
LM1=$(newrun lm1); LM2=$(newrun lm2); LU1=$(newrun lu1); LO1=$(newrun lo1); LN1=$(newrun ln1); LX1=$(newrun lx1); LV1=$(newrun lv1); LK1=$(newrun lk1)
[ -n "$LM1" ] && [ -n "$LK1" ] && ok "(setup) eight runs prepared and verified" || { no "setup: runs not made"; exit 1; }
# LM1, LM2: legacy, applied and merged, refs changed since   LU1: legacy, applied, not merged, refs changed   LO1: legacy, open (never applied)
# LN1: legacy, applied and merged, refs unchanged           LX1: legacy, applied and merged, refs changed, a member alive   LV1: a lifecycle run, applied and merged
# LK1: legacy by its registry line, applied and merged, refs changed, but the lead's state still holds attempt state for it (a marker that was stripped)
for r in "$LM1" "$LM2" "$LU1" "$LO1" "$LN1" "$LX1" "$LK1"; do legacy "$r"; done
for r in "$LM1" "$LM2" "$LU1" "$LO1" "$LX1" "$LK1"; do stale "$r"; done
applied "$LM1"; applied "$LM2"; applied "$LU1" unmerged; applied "$LN1"; applied "$LX1"; applied "$LV1"; applied "$LK1"
mkdir -p "$S/attempts/$(basename "$LK1")"; chmod 700 "$S/attempts/$(basename "$LK1")"

# --- list: one process for the merged test of every applied run
python3_real=$(command -v python3)
mkdir -p "$T/shim"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/log/python3"\nexec "%s" "$@"\n' "$T" "$python3_real" > "$T/shim/python3"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/log/git"\nexec "%s" "$@"\n' "$T" "$(command -v git)" > "$T/shim/git"
chmod 755 "$T/shim/python3" "$T/shim/git"
: > "$T/log/python3"
out=$(PATH="$T/shim:$PATH" $DA local list --scratch "$SCR" 2>&1); rcl=$?
nm=$(grep -c 'merged[.]py' "$T/log/python3" || true)
{ [ $rcl = 0 ] && [ "$nm" = 1 ] && grep -q -- 'merged[.]py --batch' "$T/log/python3"; } \
  && ok "list asks lib/merged.py once for all the applied runs (one process, not one for each of them)" || no "list: rc=$rcl merged.py started $nm times: $(cat "$T/log/python3")"
{ [ "$(awk '$2=="lm1"{print $4,$5}' <<<"$out")" = "yes yes" ] && [ "$(awk '$2=="lu1"{print $4,$5}' <<<"$out")" = "yes no" ] && [ "$(awk '$2=="lo1"{print $4,$5}' <<<"$out")" = "no no" ] \
  && [ "$(awk '$2=="lv1"{print $4,$5}' <<<"$out")" = "yes yes" ] && [ "$(wc -l <<<"$out")" = 9 ]; } \
  && ok "and its rows say what they said: applied and merged of each run" || no "list rows: $out"
# merged.py --batch answers as the single call does, for the same runs: merged, not merged, no tip, an option-like word, an unknown repository
sha_m=$(cut -d' ' -f2 "$LM1/applied"); sha_u=$(cut -d' ' -f2 "$LU1/applied")
for pair in "$sha_m" "$sha_u" "--merged=HEAD" "abc1234" ""; do
  one=0; python3 -I lib/merged.py "$REPO" "$pair" --state "$S" >/dev/null 2>&1 || one=$?
  bat=$(printf '%s\0%s\0%s\0%s\0' "$REPO" "$pair" "" "" | python3 -I lib/merged.py --batch --state "$S" 2>/dev/null)
  [ "$one" = "$bat" ] && ok "merged.py --batch answers $one for '$pair', as the call for one run does" || no "batch '$pair': single $one, batch $bat"
done
bat=$(printf '%s\0%s\0%s\0%s\0' "$REPO" "$sha_m" "" '{"runs":{"owned_refs":["refs/heads/feature/*"]}}' | python3 -I lib/merged.py --batch --state "$S" 2>/dev/null)
one=0; python3 -I lib/merged.py "$REPO" "$sha_m" --state "$S" --answers '{"runs":{"owned_refs":["refs/heads/feature/*"]}}' >/dev/null 2>&1 || one=$?
[ "$one" = "$bat" ] && ok "and with the answers of the run (a ref the runtime owns settles nothing) the batch and the single call agree ($one)" || no "batch with answers: single $one, batch $bat"

# --- the registry: a field of a line is what jq says, whatever is in it
RT=$T/regt; mkdir -p "$RT/s"
printf '%s\n' '{"run":"/x/qargi.AAAAAA","slug":"a\tb","base":"main","answers":{"k":"v\\w"},"lifecycle":1}' 'not json' '{"run":"/x/qargi.BBBBBB","slug":"plain","tmpdir":"/t/d e","closed":"2026-01-01T00:00:00Z"}' \
  '{"run":"/x/qargi.AAAAAA","slug":"again","base":"dev"}' '{"run":5}' '{"run":"/x/qargi.CCCCCC","slug":7,"cleaned":"yes"}' '{"run":"/x/qargi.DDDDDD","slug":"d","lifecycle":1}' > "$RT/s/local-runs.jsonl"
chmod 600 "$RT/s/local-runs.jsonl"
cat > "$T/regtest.sh" <<'EOF'
. lib/lib.sh
DA_STATE=$1
reg_load
printf 'rows %s\n' "${#LRUNS_ORDER[@]}"
for d in /x/qargi.AAAAAA /x/qargi.BBBBBB /x/qargi.CCCCCC /x/qargi.DDDDDD; do
  for k in slug base tmpdir closed cleaned lifecycle nosuch; do
    new=$(reg_get "$d" "$k"); old=$(jq -Rnr --arg r "$d" --arg k "$k" '[inputs | fromjson? | select(type == "object" and .run == $r)] | last // {} | if (.[$k] | type) == "string" then .[$k] else "" end' "$DA_STATE/local-runs.jsonl")
    [ "$new" = "$old" ] || echo "DIFF $d $k [$new] [$old]"
  done
done
reg_legacy /x/qargi.DDDDDD && echo "DDDDDD legacy" || echo "DDDDDD marked"
reg_legacy /x/qargi.AAAAAA && echo "AAAAAA legacy" || echo "AAAAAA marked"
reg_legacy /x/qargi.BBBBBB && echo "BBBBBB legacy" || echo "BBBBBB marked"
REG_BULK=1 reg_load
for d in /x/qargi.AAAAAA /x/qargi.BBBBBB; do for k in slug base tmpdir closed; do echo "$d $k $(reg_get "$d" "$k")"; done; done
a=''; reg_ans a /x/qargi.BBBBBB; printf 'answers of B [%s]\n' "$a"
EOF
out=$(QARGI_TOOL=$PWD bash "$T/regtest.sh" "$RT/s" 2>&1)
{  grep -q '^rows 4$' <<<"$out" && ! grep -q '^DIFF' <<<"$out" && grep -q '^DDDDDD marked$' <<<"$out" && grep -q '^AAAAAA legacy$' <<<"$out" && grep -q '^BBBBBB legacy$' <<<"$out" && grep -q '^/x/qargi.AAAAAA slug again$' <<<"$out" \
  && grep -q '^/x/qargi.BBBBBB tmpdir /t/d e$' <<<"$out" && grep -q '^answers of B \[\]$' <<<"$out"; } \
  && ok "reg_get answers from one read of the registry as jq does for each field (a later line replaces an earlier, a bad line and a non-string are passed over, a value with a space is whole)" || no "registry: $out"

# --- clean --applied: the refs of the repository are asked once, a legacy run kept for its refs gets one line, the rest is as it was
: > "$T/log/git"
out=$(PATH="$T/shim:$PATH" $DA local clean --applied --scratch "$SCR" 2>&1); rca=$?
nls=$(grep -c 'ls-remote' "$T/log/git" || true)
{ [ "$nls" -le 2 ]; } && ok "clean --applied asks the repository's origin for its refs once for all the runs (ls-remote ran $nls times for eight runs)" || no "ls-remote ran $nls times"
[ ! -e "$LN1" ] && grep -q "^cleaned $LN1" <<<"$out" && ok "a legacy run whose refs are as it recorded and whose work is merged is cleaned, as before" || no "the clean legacy run: $out"
[ ! -e "$LV1" ] && grep -q "^cleaned $LV1" <<<"$out" && ok "so is a lifecycle run, as before" || no "the lifecycle run: $out"
one() { grep -c "^kept $1:" <<<"$out"; }
{ [ -d "$LM1" ] && [ "$(one "$LM1")" = 1 ] && grep -q "^kept $LM1: legacy run, refs changed or could not be compared since it was prepared; its work is merged: after its out/ is archived, qargi local clean $LM1 --discard\$" <<<"$out"; } \
  && ok "a legacy run kept for its refs gets one line: what is the matter, and the one command to run (clean RUN --discard once the out/ is archived)" || no "legacy reason: $out"
{ [ "$(one "$LU1")" = 1 ] && grep -q "^kept $LU1: legacy run, refs changed or could not be compared, and its work is not merged: qargi feature merge NAME agent/x, then archive its out/ and qargi local clean $LU1 --discard\$" <<<"$out"; } \
  && ok "one that is not merged says that first" || no "unmerged legacy reason: $out"
{ [ "$(one "$LO1")" = 1 ] && grep -q "^kept $LO1: its work is not recorded applied\$" <<<"$out"; } && ok "a run never applied is kept as it was (open work)" || no "open run: $out"
{ grep -q "^kept $LK1: " <<<"$out" && ! grep -q "^kept $LK1: legacy run, refs changed" <<<"$out" && grep -q "private lifecycle evidence exists for an unmarked run" <<<"$out" && [ -d "$LK1" ]; } \
  && ok "a legacy run with private lifecycle evidence is left to clean, which names the evidence (it is not decided here)" || no "remnants run: $out"
grep -q "^kept $LX1: legacy run, refs changed" <<<"$out" && ok "a legacy run with a member alive is kept for its refs like the others (the bulk form is where liveness is asked)" || no "x run: $out"
{ ! grep "^kept $LM1" <<<"$out" | grep -q -e 'unmarked legacy run' -e 'writable snapshots' && [ "$(grep -c "$LM1" <<<"$out")" = 1 ] && [ "$(grep -c "$LU1" <<<"$out")" = 1 ]; } \
  && ok "no paragraph of warnings for a kept legacy run: one line each" || no "legacy warnings in the output: $out"
{ [ $rca = 1 ] && grep -q "^cleaned 2 run(s), kept 6\$" <<<"$out" && grep -q "^4 legacy run(s) kept for their refs: qargi local clean --applied --legacy --scratch $SCR plans archiving" <<<"$out"; } \
  && ok "the summary counts them and names the bulk form; the exit status is 1 as before" || no "summary (rc=$rca): $out"

# --- clean --applied --legacy: the usage errors, the plan, the approval
for bad in "--legacy" "--legacy --scratch $SCR" "--applied --legacy" "--applied --legacy --scratch $SCR $LM1" "--applied --legacy --discard --scratch $SCR" "--stale 5 --legacy --scratch $SCR" "--orphans --legacy" "--plan abc --scratch $SCR" "--approved go --applied --scratch $SCR --discard"; do
  # shellcheck disable=SC2086
  $DA local clean $bad >/dev/null 2>&1; rcb=$?
  { [ $rcb = 2 ] && [ -d "$LM1" ]; } && ok "clean $bad is a usage error and removes nothing" || no "clean $bad (rc=$rcb)"
done
QARGI_MEMBER_RUN=$LX1 spawn_bg sleep 600   # a member of LX1: a process that carries the run's mark in its environment
before=$(find "$SCR" "$S" -type f -printf '%p %T@ %s\n' | grep -v '/plans/' | sort | sha256sum)
out=$($DA local clean --applied --legacy --scratch "$SCR" 2>&1); rcp=$?; tok=$(sed -n 's/^plan token: \([0-9a-f]*\) .*/\1/p' <<<"$out")
{ [ $rcp = 0 ] && [ -n "$tok" ] && grep -q "^  $LM1  [0-9]* bytes\$" <<<"$out" && grep -q "^  $LM2  [0-9]* bytes\$" <<<"$out" && ! grep -q "^  $LU1 " <<<"$out" && ! grep -q "^  $LO1 " <<<"$out" \
  && ! grep -q "^  $LX1 " <<<"$out" && ! grep -q "$LV1" <<<"$out" && ! grep -q "$LK1" <<<"$out" && grep -q 'not in the plan: 1 applied and not merged' <<<"$out" && grep -q 'not in the plan: 1 with a runner or a member alive' <<<"$out" \
  && grep -q 'not in the plan: 1 with a lifecycle or private lifecycle evidence' <<<"$out" \
  && grep -q "archive its out/ .* to $S/runs-archive/NAME.tar.gz, read the archive back and check its size and its list of files, and only then remove the run" <<<"$out"; } \
  && ok "the plan names the applied and merged legacy runs with their sizes and says what is done to each; the unmerged, the open and the one with a member alive are not in it" || no "plan (rc=$rcp): $out"
{ [ "$before" = "$(find "$SCR" "$S" -type f -printf '%p %T@ %s\n' | grep -v '/plans/' | sort | sha256sum)" ] && [ ! -e "$S/runs-archive/$(basename "$LM1").tar.gz" ]; } \
  && ok "and the plan changes nothing (no archive, no run touched)" || no "the plan changed a file"
# a legacy_runs.py that fails to say who is alive, or how big the runs are, is no "nobody is alive": the plan stops (exit 3) and plans nothing (a copy of the tool whose helper fails)
mkdir -p "$T/tool"; tar --exclude=./.git -C "$PWD" -cf - . | tar -C "$T/tool" -xf -
printf 'import sys\nsys.exit(1 if sys.argv[1:2] == ["live"] else 0)\n' > "$T/tool/lib/legacy_runs.py"
out=$("$T/tool/bin/qargi" local clean --applied --legacy --scratch "$SCR" 2>&1); rcb=$?
{ [ $rcb = 3 ] && grep -q 'could not tell which legacy runs have a runner or a member alive' <<<"$out" && ! grep -q 'plan token' <<<"$out" && [ -d "$LM1" ]; } \
  && ok "a liveness check that fails stops the plan (exit 3), with no plan and no token" || no "live fails (rc=$rcb): $out"
printf 'import sys\nsys.exit(1 if sys.argv[1:2] == ["size"] else 0)\n' > "$T/tool/lib/legacy_runs.py"
out=$("$T/tool/bin/qargi" local clean --applied --legacy --scratch "$SCR" 2>&1); rcb=$?
{ [ $rcb = 3 ] && grep -q 'could not measure the legacy runs' <<<"$out" && ! grep -q 'plan token' <<<"$out"; } && ok "so does a size that fails" || no "size fails (rc=$rcb): $out"
rm -rf "$T/tool"
$DA plan show "$tok" 2>&1 | grep -q 'local clean' && ok "the plan is kept as a record (qargi plan show TOKEN) for the verb local clean" || no "plan show: $($DA plan show "$tok" 2>&1 | head -3)"
$DA plan show "$tok" 2>&1 | grep -q 'bulkproj' && ok "its target names the project" || no "plan target: $($DA plan show "$tok" 2>&1 | head -5)"
out=$($DA local clean --applied --legacy --scratch "$SCR" --approved "go" 2>&1); rcs=$?
{ [ $rcs != 0 ] && [ -d "$LM1" ] && [ -d "$LM2" ]; } && ok "--approved without --plan removes nothing" || no "approved without plan (rc=$rcs): $out"
out=$($DA local clean --applied --legacy --scratch "$SCR" --plan 000000000000 --approved "go" 2>&1); rcs=$?
{ [ $rcs != 0 ] && [ -d "$LM1" ] && [ ! -e "$S/runs-archive" ]; } && ok "a wrong token removes nothing and archives nothing" || no "wrong token (rc=$rcs): $out"
out=$(QARGI_NESTED=1 $DA local clean --applied --legacy --scratch "$SCR" --approved "go" 2>&1); rcs=$?
{ [ $rcs != 0 ] && [ -d "$LM1" ]; } && ok "QARGI_NESTED does not stand in for the token" || no "nested (rc=$rcs): $out"
# a changed fixture changes the token
touch "$LM2/out/another-file"
out=$($DA local clean --applied --legacy --scratch "$SCR" 2>&1); tok2=$(sed -n 's/^plan token: \([0-9a-f]*\) .*/\1/p' <<<"$out")
{ [ -n "$tok2" ] && [ "$tok2" != "$tok" ]; } && ok "a run that changed since the plan (a file added to its out/) makes a new token" || no "the token did not move: $tok $tok2"
out=$($DA local clean --applied --legacy --scratch "$SCR" --plan "$tok" --approved "go" 2>&1); rcs=$?
{ [ $rcs != 0 ] && [ -d "$LM1" ] && [ -d "$LM2" ]; } && ok "so the old token is stale: nothing is removed" || no "stale token (rc=$rcs): $out"
tok=$tok2
# an archive that is there already and is not this run's is never replaced: that run is kept, the other goes
mkdir -p "$S/runs-archive"; chmod 700 "$S/runs-archive"; echo garbage > "$S/runs-archive/$(basename "$LM2").tar.gz"
out=$($DA local clean --applied --legacy --scratch "$SCR" --plan "$tok" --approved "the owner said archive and remove them" 2>&1); rcs=$?
{ [ $rcs = 1 ] && [ ! -e "$LM1" ] && [ -d "$LM2" ] && grep -q "^kept $LM2: not archived, so not removed: qargi: an archive .* is there already and .*it is kept" <<<"$out" && grep -q '^removed 1 legacy run(s), kept 1$' <<<"$out"; } \
  && ok "an archive of the same name that does not match is never replaced: that run is kept, with its reason, and the other one is archived and removed (exit 1)" || no "apply (rc=$rcs): $out"
A1=$S/runs-archive/$(basename "$LM1").tar.gz
{ [ -f "$A1" ] && [ "$(stat -c %a "$A1")" = 600 ] && [ "$(stat -c %a "$S/runs-archive")" = 700 ]; } && ok "the archive is there, private" || no "archive mode: $(ls -l "$A1")"
lst=$(tar tzf "$A1" 2>&1)
{ grep -q "^$(basename "$LM1")/out/manifest.json\$" <<<"$lst" && grep -q "^$(basename "$LM1")/out/report.md\$" <<<"$lst" && grep -q "^$(basename "$LM1")/verified\$" <<<"$lst" && grep -q "^$(basename "$LM1")/applied\$" <<<"$lst" \
  && grep -q "^$(basename "$LM1")/saved/out/manifest.json\$" <<<"$lst" && grep -q "^$(basename "$LM1")/record.json\$" <<<"$lst" && ! grep -q '/clone/' <<<"$lst"; } \
  && ok "it holds the run's out/, its records, the lead's saved copy and its registry line, and not its clone" || no "archive list: $lst"
[ "$(tar xzOf "$A1" "$(basename "$LM1")/out/report.md")" = r ] && ok "and what it holds reads back" || no "archive content"
{ [ ! -e "$LM1" ] && [ -d "$LU1" ] && [ -d "$LO1" ] && [ -d "$LX1" ] && [ -f "$LX1/out/manifest.json" ]; } && ok "the runs that were not in the plan are untouched" || no "a run outside the plan changed"
[ ! -e "$S/runs/$(basename "$LM1")" ] && jq -e --arg r "$LM1" 'select(.run == $r and (.cleaned | type) == "string")' "$S/local-runs.jsonl" >/dev/null && ok "the removed run is marked cleaned in the registry and its saved copy is gone (it is in the archive)" || no "registry/saved copy of the removed run"
jq -e 'select(.verb == "local:clean-legacy" and .approved == "the owner said archive and remove them")' "$S/audit.log" >/dev/null 2>&1 && ok "the removal is in the audit log with the words" || no "audit: $(tail -2 "$S/audit.log")"
jq -s -e --arg r "$LM1" '[.[] | select(.verb == "local:clean-legacy")] | (map(.detail | startswith($r + " archived to")) | index(true)) as $i | ($i != null) and ($i < (length - 1)) and .[$i].approved == "the owner said archive and remove them"' "$S/audit.log" >/dev/null 2>&1 \
  && ok "each run has its own audit line (its archive, with the words) before the summary line, written before its removal" || no "audit per run: $(grep clean-legacy "$S/audit.log" | cut -c1-200)"
# the archive is read back before the run goes: a run whose archive cannot be made is not removed
rm -f "$S/runs-archive/$(basename "$LM2").tar.gz"; mv "$S/runs-archive" "$S/ra.keep"; ln -s "$T/log" "$S/runs-archive"   # the archive directory is a link, not a directory
out=$($DA local clean --applied --legacy --scratch "$SCR" 2>&1); tok3=$(sed -n 's/^plan token: \([0-9a-f]*\) .*/\1/p' <<<"$out")
out=$($DA local clean --applied --legacy --scratch "$SCR" --plan "$tok3" --approved "go on" 2>&1); rcs=$?
rm -f "$S/runs-archive"; mv "$S/ra.keep" "$S/runs-archive"
{ [ $rcs = 1 ] && [ -d "$LM2" ] && grep -q "^kept $LM2: not archived, so not removed" <<<"$out"; } && ok "when the archive cannot be written (its directory is a link) the run is kept: nothing is removed before its archive exists" || no "no archive (rc=$rcs): $out"
# the unit: legacy_runs.py archive checks the list it wrote against the files, and an existing archive that matches is reused
out=$(sed -n 1p "$S/local-runs.jsonl" | python3 -I lib/legacy_runs.py archive "$S" "$LM2" 2>&1); rca=$?
{ [ $rca = 0 ] && grep -q "^archive $S/runs-archive/$(basename "$LM2").tar.gz [0-9]* [0-9]*\$" <<<"$out"; } && ok "legacy_runs.py archive writes and checks an archive" || no "archive unit (rc=$rca): $out"
out2=$(sed -n 1p "$S/local-runs.jsonl" | python3 -I lib/legacy_runs.py archive "$S" "$LM2" 2>&1); [ "$out" = "$out2" ] && ok "and an archive there already that matches is reused as it is" || no "reuse: $out | $out2"
echo more > "$LM2/out/changed-after"
out=$(sed -n 1p "$S/local-runs.jsonl" | python3 -I lib/legacy_runs.py archive "$S" "$LM2" 2>&1); rca=$?
{ [ $rca = 1 ] && grep -q 'is there already and its list does not match the files' <<<"$out"; } && ok "one that no longer matches the run's files is kept and refused, never replaced" || no "mismatch (rc=$rca): $out"
out=$(python3 -I lib/legacy_runs.py live "$LX1" "$LM2" 2>&1)
{ grep -q "^$LX1	a process carries QARGI_MEMBER_RUN for it\$" <<<"$out" && ! grep -q "$LM2" <<<"$out"; } && ok "legacy_runs.py live names a run whose member carries QARGI_MEMBER_RUN, and no other" || no "live: $out"

# --- the archive, checked harder: what a member can leave in out/, a damaged file, a rewrite of the same length, and the flush to disk
U=$T/u; UR=$U/r/qargi.UNIT01; mkdir -p "$U/s/runs" "$UR/out"; printf 'aaaa' > "$UR/out/a"; ln "$UR/out/a" "$UR/out/b"; ln -s a "$UR/out/l"; printf 'x\n' > "$UR/refs.before"
UA=$U/s/runs-archive/qargi.UNIT01.tar.gz
arch() { printf '{"run":"x"}\n' | python3 -I lib/legacy_runs.py archive "$U/s" "$UR" 2>&1; }
out=$(arch); rca=$?
{ [ $rca = 0 ] && ! grep -q Traceback <<<"$out" && [ "$(tar tzvf "$UA" | grep -c '^-')" -ge 3 ] && ! tar tzvf "$UA" | grep -q '^h' && tar tzf "$UA" | grep -q 'out/a$' && tar tzf "$UA" | grep -q 'out/b$'; } \
  && ok "a hard link in out/ is archived as a file of its own (each name has its content), and the archive checks" || no "hard link (rc=$rca): $out"
cp "$UA" "$U/good.tar.gz"
python3 -I -c '
import sys
p = sys.argv[1]
d = bytearray(open(p, "rb").read())
d[-8] ^= 1                      # the CRC32 of the gzip trailer
open(p, "wb").write(d)' "$UA"
out=$(arch); rca=$?
{ [ $rca = 1 ] && grep -q 'is there already and the archive cannot be read back' <<<"$out"; } && ok "an archive whose gzip checksum is wrong fails the read-back (it was passed before: the tar ends before the trailer)" || no "crc (rc=$rca): $out"
cp "$U/good.tar.gz" "$UA"; printf 'bbbb' > "$UR/out/a"
out=$(arch); rca=$?
{ [ $rca = 1 ] && grep -q 'is there already and its list does not match the files' <<<"$out"; } && ok "a file rewritten with the same length is not the archived one: its sha256 differs, the archive is kept and refused" || no "same length (rc=$rca): $out"
printf 'aaaa' > "$UR/out/a"; out=$(arch); rca=$?
[ $rca = 0 ] && ok "and with the content back the archive matches again" || no "content back (rc=$rca): $out"
python3 -I -c '
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.bind(sys.argv[1])' "$UR/out/sock"
rm -f "$UA"; out=$(arch); rca=$?
{ [ $rca = 1 ] && grep -q 'sock is a socket: a socket cannot be archived' <<<"$out" && ! grep -q Traceback <<<"$out" && [ ! -e "$UA" ]; } && ok "a socket in out/ is refused with its name as the reason, no traceback and no archive" || no "socket (rc=$rca): $out"
rm -f "$UR/out/sock"
python3 -I - lib "$U/s" "$UR" <<'PYEOF' && ok "the archive file is flushed (fsync) before it is renamed into place, and the directory after" || no "fsync order"
import os, stat, sys
sys.path.insert(0, sys.argv[1])
import legacy_runs as LR
state, run = sys.argv[2], sys.argv[3]
dest = os.path.join(state, "runs-archive", "qargi.UNIT01.tar.gz")
if os.path.exists(dest):
    os.unlink(dest)
calls = []
real = os.fsync
def spy(fd):
    calls.append(("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file", os.path.exists(dest)))
    return real(fd)
LR.os.fsync = spy
LR.archive(state, run, "{}")
assert calls == [("file", False), ("dir", True)], calls
PYEOF

# --- the cached snapshot of a remote is the answer to one question: the same URL asked with another credential is another question
sed -n '/^snap_cached() {/,/^}/p; /^snapshot_url() {/p' lib/local.sh > "$T/snap.sh"
cat > "$T/snaptest.sh" <<'EOF'
. "$1"
DA_STATE=$2; QARGI_SNAP_CACHE=$DA_STATE/verify.t; mkdir -p "$QARGI_SNAP_CACHE"
snapshot_url_raw() { echo "asked ${2:-none}" >> "$DA_STATE/asks"; echo "refs-for-${2:-none}"; }
a=$(snapshot_url https://example.net/r.git /c/one); b=$(snapshot_url https://example.net/r.git /c/two); c=$(snapshot_url https://example.net/r.git /c/one); n=$(snapshot_url https://example.net/r.git)
echo "$a|$b|$c|$n|$(wc -l < "$DA_STATE/asks")"
EOF
mkdir -p "$T/sn"; out=$(bash "$T/snaptest.sh" "$T/snap.sh" "$T/sn" 2>&1)
[ "$out" = "refs-for-/c/one|refs-for-/c/two|refs-for-/c/one|refs-for-none|3" ] && ok "a cached snapshot of a URL is keyed with the credential too (two credentials, two answers; the same one asked once)" || no "snapshot cache key: $out"

# --- the warning of merged.py reaches the lead (a line of the ref journal that is not JSON)
cp "$S/ref-journal.jsonl" "$T/journal.keep" 2>/dev/null || : > "$T/journal.keep"
printf 'this line is not json\n' >> "$S/ref-journal.jsonl"
out=$($DA local list --scratch "$SCR" 2>&1)
cp "$T/journal.keep" "$S/ref-journal.jsonl"; [ -s "$T/journal.keep" ] || rm -f "$S/ref-journal.jsonl"
{ [ "$(grep -c 'line of the ref journal' <<<"$out")" = 1 ]; } && ok "local list says once that the ref journal has a line that is not JSON (the warning of merged.py is not dropped)" || no "journal warning: $out"

# --- a legacy run closed by hand with changed refs: its line does not send it to a plan that excludes it
LC1=$(newrun lc1); $DA local close "$LC1" --applied-by-am >/dev/null 2>&1 || no "setup: local close of the run"
legacy "$LC1"; stale "$LC1"
out=$($DA local clean --applied --scratch "$SCR" 2>&1)
{ grep -q "^kept $LC1: legacy run closed by hand (local close --applied-by-am), refs changed" <<<"$out" && grep -q 'clean --applied --legacy does not plan it' <<<"$out" && [ -d "$LC1" ]; } \
  && ok "a run closed by hand and kept for its refs says so, and names the clean RUN --discard that works (the bulk form does not plan it)" || no "closed run line: $(grep "$LC1" <<<"$out")"
kill_bg
exit $fail
