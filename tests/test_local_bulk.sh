#!/usr/bin/env bash
# local list and local clean over many runs: the work done once for all the runs (one process for the merged test, one refs question for the repository) and the one-line
# reason of a legacy run clean --applied keeps. Synthetic runs: a few real prepares, turned into legacy runs (no lifecycle marker, no attempt state) by hand, as runs of an
# older qargi are. Run: tests/test_local_bulk.sh
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
{ [ $rca = 1 ] && grep -q "^cleaned 2 run(s), kept 6\$" <<<"$out" ; } \
  && ok "the summary counts the runs cleaned and kept; the exit status is 1 as before" || no "summary (rc=$rca): $out"

kill_bg
exit $fail
