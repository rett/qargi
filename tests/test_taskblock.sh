#!/usr/bin/env bash
# The task block `qargi local prepare` writes (RUN/task.md) for every runtime: golden files for a build and a review run, the refusals (a DONE
# that is not a command, an empty or linked task file), and SCOPE as the limit `qargi review check` applies. Run: tests/test_taskblock.sh
# UPDATE_GOLDEN=1 bash tests/test_taskblock.sh rewrites tests/golden/taskblock-*.md (read the diff before committing it).
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
Q=$PWD/bin/qargi; GOLD=$PWD/tests/golden
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
R=$T/fixrepo
git init -q -b main "$R" && mkdir -p "$R/tests" && printf '#!/bin/sh\nexit 0\n' > "$R/tests/check.sh" && chmod +x "$R/tests/check.sh"
git -C "$R" add -A && git -C "$R" -c user.name=t -c user.email=t@example.net commit -q -m one
# a read-only role is looked up through the repository's project (its local provider)
mkdir -p "$T/c/projects" "$T/c/profiles"
jq -n --arg p "$R" '{schema:1,project:"fixproj",repo:{url:"https://github.com/example/fixproj",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/fixproj.json"
printf '# Profile of fixrepo\n\nGates: `make test`.\nRule: no private names.\n' > "$T/c/profiles/fixrepo.md"
printf 'Add the flag --quiet to the tool.\n\nIt prints nothing on success.\n' > "$T/task.txt"
runs() { find "$T" -maxdepth 1 -name 'qargi.??????' | wc -l; }
# prep ARGS...: prepare in the fixture repository; sets RUN, TMPD and BSHA from its output
prep() { local out; out=$($Q local prepare --repo "$R" --base main --scratch "$T" "$@" 2>&1) || { echo "$out"; return 1; }
  PREP=$out; RUN=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); TMPD=$(sed -n '1,/^$/s/^TMP=//p' <<<"$out"); BSHA=$(sed -n '1,/^$/s/^BASE_SHA=//p' <<<"$out"); }
# norm FILE: the paths and the SHA of a run replaced, so the golden file holds nothing of this machine
norm() { sed -e "s|$RUN|<RUN>|g" -e "s|$TMPD|<TMP>|g" -e "s|$BSHA|<BASE_SHA>|g" "$1"; }
golden() { # NAME FILE: compare the normalised task block with tests/golden/NAME
  if [ -n "${UPDATE_GOLDEN:-}" ]; then mkdir -p "$GOLD"; norm "$2" > "$GOLD/$1"; fi
  if norm "$2" | diff -u "$GOLD/$1" - > "$T/golden.diff" 2>&1; then ok "task.md matches tests/golden/$1"; else no "task.md differs from tests/golden/$1"; head -30 "$T/golden.diff"; fi
}

# --- the golden files: a build run (task file, DONE, two scope paths, the repository's profile) and a review run (no scope)
prep --slug gold --role build --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope lib/ --scope ./docs/guide.md || no "prepare with a task block failed"
[ -f "$RUN/task.md" ] && ok "prepare writes RUN/task.md when given --task-file" || no "no RUN/task.md"
golden taskblock-build.md "$RUN/task.md"
grep -qx "TASK_FILE=$RUN/task.md" <<<"$PREP" && ok "prepare prints TASK_FILE=RUN/task.md, the path the lead hands the member" || no "no TASK_FILE line"
grep -q "^BASE_SHA: $(git -C "$R" rev-parse main)$" "$RUN/task.md" && ok "the block names the base SHA" || no "base sha"
grep -q '^SCOPE: lib/, docs/guide.md$' "$RUN/task.md" && ok "SCOPE is one line, the paths comma separated" || no "scope line: $(grep SCOPE: "$RUN/task.md")"
prep --slug goldrev --role review --task-file "$T/task.txt" --done 'bash tests/check.sh' || no "prepare of a review run with a task block failed"
golden taskblock-review.md "$RUN/task.md"
grep -q '^SCOPE: none$' "$RUN/task.md" && ok "without --scope the block says SCOPE: none" || no "scope none"

# --- a run without the flags is as before: no task.md
prep --slug plain || no "plain prepare failed"
[ ! -e "$RUN/task.md" ] && ok "without --task-file there is no task.md (as before)" || no "task.md without the flag"

# --- the refusals: each makes no run
refuse() { # LABEL EXPECTED-TEXT ARGS...
  local label=$1 want=$2 before out rc; shift 2; before=$(runs)
  out=$($Q local prepare --repo "$R" --base main --scratch "$T" "$@" 2>&1); rc=$?
  if [ "$rc" != 0 ] && grep -q -- "$want" <<<"$out" && [ "$(runs)" = "$before" ]; then ok "$label is refused, and no run is made"; else no "$label: rc=$rc runs $before -> $(runs): $out"; fi
}
refuse "a prose DONE" "reads as prose" --slug r1 --task-file "$T/task.txt" --done 'the output looks right'
refuse "an empty DONE" "needs --done" --slug r2 --task-file "$T/task.txt" --done ''
refuse "no DONE" "needs --done" --slug r3 --task-file "$T/task.txt"
refuse "a DONE with several lines" "one command line" --slug r4 --task-file "$T/task.txt" --done $'make test\nmake lint'
refuse "a DONE script that does not exist" "not an existing script" --slug r5 --task-file "$T/task.txt" --done './tests/nope.sh'
: > "$T/empty.txt"; printf ' \n\t\n' > "$T/blank.txt"
refuse "an empty task file" "is empty" --slug r6 --task-file "$T/empty.txt" --done 'bash tests/check.sh'
refuse "a blank task file" "is empty" --slug r7 --task-file "$T/blank.txt" --done 'bash tests/check.sh'
ln -s "$T/task.txt" "$T/link.txt"
refuse "a task file that is a link" "is a link" --slug r8 --task-file "$T/link.txt" --done 'bash tests/check.sh'
refuse "a task file that is not there" "no such file" --slug r9 --task-file "$T/missing.txt" --done 'bash tests/check.sh'
printf 'Do it.\nSCOPE: everything\n' > "$T/scoped.txt"
refuse "a task file with its own SCOPE: line" "starts SCOPE:" --slug r10 --task-file "$T/scoped.txt" --done 'bash tests/check.sh'
refuse "an absolute --scope" "relative" --slug r11 --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope /etc
refuse "a --scope with .." "relative" --slug r12 --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope ../x
refuse "a --scope with a comma" "relative" --slug r13 --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope 'a,b'
refuse "--done without --task-file" "go with --task-file" --slug r14 --done 'bash tests/check.sh'
refuse "--scope without --task-file" "go with --task-file" --slug r15 --scope lib/
# what a DONE may be: an executable, a builtin, a script of the repository, with leading NAME=value words
n=0; for d in 'make test' 'true' 'FOO=1 bash tests/check.sh' './tests/check.sh' 'cd tests && ./check.sh'; do
  n=$((n+1)); prep --slug "d$n" --task-file "$T/task.txt" --done "$d" >/dev/null 2>&1 && grep -qxF "DONE: $d" "$RUN/task.md" && ok "DONE '$d' is accepted" || no "DONE '$d' refused"
done

# --- P3: a run prepared with --scope; review check fails a patch outside it and passes one inside
sc() { # NAME FILES...: a run with --scope lib/, a member series that changes the given files, its OUT
  local name=$1 f; shift
  prep --slug "$name" --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope lib/ || { no "prepare $name"; return; }
  G=$RUN/git; C=$RUN/clone
  for f in "$@"; do mkdir -p "$C/$(dirname "$f")"; echo x > "$C/$f"; done
  "$G" -C "$C" add -A; "$G" -C "$C" commit -q -m "change the files" -m "The files change because the task says so."
  mkdir -p "$RUN/out/patches"; "$G" -C "$C" format-patch -q -o "$RUN/out/patches" "$BSHA..HEAD"
  "$G" -C "$C" log --format='%H%x09%s' "$BSHA..HEAD" | jq -R -s -c '[split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
    | {status:"DONE", commits:$c, commit_advice:($c|map(. + {why_separate:"x", depends_on:[], builds_alone:true})), patch_groups:[{name:"g", why:"one change", commits:($c|map(.sha))}]}' > "$RUN/out/manifest.json"
  echo "# series" > "$RUN/out/series.md"
}
sc inside lib/a.sh lib/sub/b.sh
out=$($Q review check "$RUN/out" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a patch inside the prepared SCOPE passes review check" || no "inside: rc=$rc $out"
sc outside lib/a.sh docs/other.md
out=$($Q review check "$RUN/out" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q 'outside SCOPE (lib/): docs/other.md' <<<"$out" && ok "a patch that touches another path fails review check, the path named" || no "outside: rc=$rc $out"
jq '.scope = ["lib/", "docs/"]' "$RUN/out/manifest.json" > "$RUN/out/m.json" && mv "$RUN/out/m.json" "$RUN/out/manifest.json"
$Q review check "$RUN/out" 2>&1 | grep -q 'outside SCOPE' && ok "the member's own scope[] does not widen the prepared SCOPE" || no "scope[] widened the limit"

exit $fail
