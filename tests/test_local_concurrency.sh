#!/usr/bin/env bash
# Ten local runs at once: ten `local prepare` started together, then ten `local verify` together, then one `local clean --applied`. The
# registry ($QARGI_STATE/local-runs.jsonl) is one file every run appends to (prepare) and rewrites (verify marks a run verified, clean
# marks it cleaned), each under the registry's own lock: no line may be lost or torn, each run keeps its one line, and the scratch
# directory and the QARGI_RUN_TMP parent (shared by the ten in both rounds) hold exactly the ten runs and the ten temporary directories
# until clean removes exactly those. The "own" round gives each process a TMPDIR of its own (the test keeps them apart); the "shared"
# round gives all ten the same TMPDIR on purpose, so only the product's lock and its explicit parents (the scratch, QARGI_RUN_TMP, the
# state) keep them apart. Run: tests/test_local_concurrency.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s
mkdir -p "$T/c" "$T/s"
# shellcheck source=fixtures.sh
. tests/fixtures.sh
LC="git -c user.name=t -c user.email=t@example.net"
git init -q -b main "$T/r" && $LC -C "$T/r" commit -q --allow-empty -m one
REG=$T/s/local-runs.jsonl
reg_ok() { # -> 0 when every line of the registry is one JSON object (nothing torn), and prints the count of its lines (0 before the first run)
  [ -f "$REG" ] || { echo 0; return 0; }
  jq -ec 'type == "object"' "$REG" >/dev/null 2>&1 && [ "$(jq -c . "$REG" 2>/dev/null | wc -l)" = "$(wc -l < "$REG")" ] && wc -l < "$REG"
}
concurrent_round() { # own|shared -> ten prepares at once, ten verifies at once, one clean --applied, with the checks of each phase
  local mode=$1 n=10 i rc scr=$T/cc-$1 rt=$T/cc-$1/rt td o r t g c sha t0=$SECONDS bad='' nb na
  local -a pids=() runs=() tmps=() rcs=()
  mkdir -p "$scr" "$rt" "$scr/log"
  nb=$(reg_ok) || { no "concurrent $mode: the registry is not whole before the round"; return; }
  for i in $(seq $n); do
    case $mode in own) td=$scr/td$i;; *) td=$scr/td;; esac; mkdir -p "$td"
    spawn_bg env TMPDIR="$td" QARGI_RUN_TMP="$rt" ./bin/qargi local prepare --repo "$T/r" --base main --slug "$mode-$i" --scratch "$scr" > "$scr/log/p$i" 2> "$scr/log/p$i.err"
    pids+=("$SPAWNED_PID")
  done
  for i in $(seq $n); do wait "${pids[i - 1]}"; rcs+=("$?"); done
  for i in $(seq $n); do
    r=$(sed -n '1,/^$/s/^RUN=//p' "$scr/log/p$i"); t=$(sed -n '1,/^$/s/^TMP=//p' "$scr/log/p$i")
    [ "${rcs[i - 1]}" = 0 ] && [ -d "$r/clone" ] && [ -f "$r/refs.before" ] && [ -d "$t" ] && [ "$(cat "$r/tmpdir")" = "$t" ] || bad="$bad p$i(rc=${rcs[i - 1]})"
    runs+=("$r"); tmps+=("$t")
  done
  [ -z "$bad" ] && [ "$(printf '%s\n' "${runs[@]}" | sort -u | wc -l)" = $n ] && [ "$(printf '%s\n' "${tmps[@]}" | sort -u | wc -l)" = $n ] \
    && [ "$(printf '%s\n' "${runs[@]}" | grep -c "^$scr/qargi\.......\$")" = $n ] && [ "$(printf '%s\n' "${tmps[@]}" | grep -c "^$rt/qargi-run\.......\$")" = $n ] \
    && ok "concurrent $mode: $n prepares at once each made a run of its own under the scratch, with a temporary directory of its own under QARGI_RUN_TMP" \
    || no "concurrent $mode prepares:$bad runs=[${runs[*]}] tmps=[${tmps[*]}] $(cat "$scr"/log/p*.err)"
  na=$(reg_ok) || na=torn
  [ "$na" = $((nb + n)) ] && [ "$(jq -r --arg m "$mode-" 'select((.slug | startswith($m)) and (.cleaned | not)) | .run' "$REG" | sort)" = "$(printf '%s\n' "${runs[@]}" | sort)" ] \
    && [ "$(jq -r --arg m "$mode-" 'select(.slug | startswith($m)) | .tmpdir' "$REG" | sort)" = "$(printf '%s\n' "${tmps[@]}" | sort)" ] \
    && ok "and the registry grew by exactly $n whole lines, one per run, each naming its run directory, slug and temporary directory" \
    || no "concurrent $mode registry after prepare: $nb -> $na lines; $(grep "$mode-" "$REG")"
  for i in $(seq $n); do   # each run has work to verify: a commit in its clone, a manifest and a report (verify fails first on an uncollected run)
    r=${runs[i - 1]}; g=$(sed -n '1,/^$/s/^GIT=//p' "$scr/log/p$i"); c=$r/clone
    echo "$i" > "$c/f-$i"; "$g" -C "$c" add "f-$i"; "$g" -C "$c" commit -q -m "work $i"; echo '{"status":"DONE"}' > "$r/out/manifest.json"; echo r > "$r/out/report.md"
  done
  pids=(); rcs=(); bad=''
  for i in $(seq $n); do
    case $mode in own) td=$scr/td$i;; *) td=$scr/td;; esac
    spawn_bg env TMPDIR="$td" QARGI_RUN_TMP="$rt" ./bin/qargi local verify "${runs[i - 1]}" > "$scr/log/v$i" 2>&1
    pids+=("$SPAWNED_PID")
  done
  for i in $(seq $n); do wait "${pids[i - 1]}"; rcs+=("$?"); done
  for i in $(seq $n); do
    r=${runs[i - 1]}
    [ "${rcs[i - 1]}" = 0 ] && grep -q '^refs unchanged' "$scr/log/v$i" && [ -f "$r/verified" ] && [ -d "$T/s/runs/$(basename "$r")/out" ] || bad="$bad v$i(rc=${rcs[i - 1]})"
  done
  na=$(reg_ok) || na=torn
  [ -z "$bad" ] && [ "$na" = $((nb + n)) ] && [ "$(jq -r --arg m "$mode-" 'select((.slug | startswith($m)) and (.verified | type) == "string") | .run' "$REG" | sort)" = "$(printf '%s\n' "${runs[@]}" | sort)" ] \
    && ok "$n verifies at once each passed, saved its copy and marked its own line verified; the registry still has $((nb + n)) whole lines" \
    || no "concurrent $mode verifies:$bad registry $na lines; $(cat "$scr"/log/v*)"
  for i in $(seq $n); do   # applied and merged: a commit on main's tree, recorded in RUN/applied and on a feature branch of the repository
    sha=$($LC -C "$T/r" commit-tree -p main -m "applied $mode-$i" "$(git -C "$T/r" rev-parse 'main^{tree}')")
    printf 'agent/%s %s now\n' "$mode-$i" "$sha" > "${runs[i - 1]}/applied"; git -C "$T/r" update-ref "refs/heads/feature/$mode-$i" "$sha"
  done
  mkdir "$scr/qargi.zzzzzz" "$rt/qargi-run.zzzzzz"   # lookalikes the registry does not name: clean must leave them
  o=$(QARGI_RUN_TMP=$rt ./bin/qargi local clean --applied --scratch "$scr" 2>&1); rc=$?
  na=$(reg_ok) || na=torn
  { [ $rc = 0 ] && grep -q "^cleaned $n run(s), kept 0\$" <<<"$o" && [ "$(grep -c '^cleaned ' <<<"$o")" = $((n + 1)) ]; } || bad=" clean rc=$rc"
  for i in $(seq $n); do
    [ ! -e "${runs[i - 1]}" ] && [ ! -e "${tmps[i - 1]}" ] && [ ! -e "$T/s/runs/$(basename "${runs[i - 1]}")" ] || bad="$bad left($i)"
  done
  [ -z "$bad" ] && [ "$(find "$scr" -mindepth 1 -maxdepth 1 ! -name 'td*' -printf '%f\n' | sort | tr '\n' ' ')" = "log qargi.zzzzzz rt " ] && [ "$(ls -A "$rt")" = qargi-run.zzzzzz ] \
    && ok "one clean --applied removed the $n runs, their $n temporary directories and their saved copies, and nothing else (the lookalikes stay)" \
    || no "concurrent $mode clean:$bad scratch=[$(ls -A "$scr" | tr '\n' ' ')] rt=[$(ls -A "$rt" | tr '\n' ' ')] $o"
  [ "$na" = $((nb + n)) ] && [ "$(jq -r --arg m "$mode-" 'select((.slug | startswith($m)) and (.cleaned | type) == "string") | .run' "$REG" | sort)" = "$(printf '%s\n' "${runs[@]}" | sort)" ] \
    && ok "and every run keeps its one line, now marked cleaned: $((nb + n)) whole lines, none lost or torn (the $mode round took $((SECONDS - t0))s)" \
    || no "concurrent $mode registry after clean: $na lines; $(grep "$mode-" "$REG")"
  rm -rf "$scr/qargi.zzzzzz" "$rt/qargi-run.zzzzzz"
}
concurrent_round own
concurrent_round shared
exit $fail
