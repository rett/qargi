#!/usr/bin/env bash
# `qargi local report RUN [--findings] [--from FILE] [--force]`: the member's own way to put its report into OUT when its file tool is refused.
# Standard input (or a file under OUT) becomes OUT/report.md (--findings: OUT/findings.md) and a minimal manifest.json when OUT has none; paths stay inside
# OUT; it is no lead-only verb (the guard lets a read-only member run it), and it refuses a build run, a run the lead's registry does not name and the
# run of another member. Run: tests/test_local_report.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects" "$T/shm" "$T/scr"
A=$T/app; git init -q -b master "$A"; git -C "$A" config user.name lead; git -C "$A" config user.email lead@example.net
echo a > "$A/a.txt"; git -C "$A" add -A; git -C "$A" commit -q -m base; git -C "$A" branch develop; git -C "$A" checkout -q -b parked
jq -n --arg p "$A" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, models:{provider:{local:"claude-code", cloud:"claude-platform"}}, test_command:"true"}' > "$T/c/projects/app.json"
prep() { $DA local prepare --repo "$A" --base develop --slug "$1" --scratch "$T/scr" --role "${2:-review}" | sed -n 's/^RUN=//p'; }
MSG=$T/message.md; printf '# Findings\n\nnone: if n > 0 the line is fine\n\ngit push is only text here\n\n# Checked\n\nread the diff\n\nverdict: accept\n' > "$MSG"

R1=$(prep rep1)
out=$($DA local report "$R1" < "$MSG" 2>&1); rc=$?
{ [ $rc = 0 ] && cmp -s "$MSG" "$R1/out/report.md" && grep -q "wrote $R1/out/report.md" <<<"$out" && grep -q "wrote $R1/out/manifest.json" <<<"$out"; } \
  && ok "local report writes standard input as OUT/report.md and says what it wrote" || no "report: rc=$rc $out"
{ [ "$(jq -r '.status' "$R1/out/manifest.json")" = DONE ] && [ "$(jq -c '.commits' "$R1/out/manifest.json")" = '[]' ] && [ "$(jq -r '.base.sha' "$R1/out/manifest.json")" = "$(git -C "$A" rev-parse develop)" ] \
  && jq -e '.artifacts == [{"path":"report.md","kind":"report"}]' "$R1/out/manifest.json" >/dev/null; } && ok "and a minimal manifest.json that names the report" || no "manifest: $(cat "$R1/out/manifest.json" 2>&1)"
out=$($DA review check "$R1/out" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q "report-only run" <<<"$out"; } && ok "review check accepts what local report wrote" || no "check: rc=$rc $out"
out=$($DA local report "$R1" < "$MSG" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "exists already" <<<"$out"; } && ok "it does not overwrite a report" || no "overwrite: rc=$rc $out"
printf '# Findings\n\nsecond\n' | $DA local report "$R1" --force >/dev/null 2>&1
{ grep -q second "$R1/out/report.md" && [ -z "$(find "$R1/out" -name '.*' -type f)" ]; } && ok "--force replaces it and leaves no temporary file" || no "force"
jq '.task = "mine"' "$R1/out/manifest.json" > "$T/m.json" && cp "$T/m.json" "$R1/out/manifest.json"; printf '# Findings\n\nthird\n' | $DA local report "$R1" --force >/dev/null 2>&1
[ "$(jq -r .task "$R1/out/manifest.json")" = mine ] && ok "a manifest the member wrote is kept" || no "manifest kept"

# --- a file under OUT as the input, and nothing outside OUT
R2=$(prep rep2); printf '# Findings\n\nfrom a draft\n' > "$R2/out/draft.txt"
out=$($DA local report "$R2" --from draft.txt 2>&1); rc=$?
{ [ $rc = 0 ] && cmp -s "$R2/out/draft.txt" "$R2/out/report.md"; } && ok "--from takes a file under OUT (a relative name is relative to OUT)" || no "from: rc=$rc $out"
R3=$(prep rep3); printf 'outside\n' > "$T/outside.md"; ln -s "$T/outside.md" "$R3/out/link.md"; printf 'x\n' > "$R3/real.md"
for f in "$T/outside.md" "../real.md" "$R3/real.md" link.md ../../../../etc/hostname missing.md .; do
  out=$($DA local report "$R3" --from "$f" 2>&1); rc=$?
  { [ $rc != 0 ] && [ ! -e "$R3/out/report.md" ]; } && ok "--from $f is refused and nothing is written" || no "from $f: rc=$rc $out"
done
$DA local report "$R3" --from report.md >/dev/null 2>&1; [ $? != 0 ] && [ ! -e "$R3/out/report.md" ] && ok "--from cannot name the file it writes" || no "from itself"
head -c 1100000 /dev/zero | tr '\0' a > "$R3/out/big.txt"
out=$($DA local report "$R3" --from big.txt 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "too large" <<<"$out" && [ ! -e "$R3/out/report.md" ]; } && ok "a file over the size limit is refused" || no "big: rc=$rc $out"
out=$(head -c 1100000 /dev/zero | tr '\0' a | $DA local report "$R3" 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "too large" <<<"$out" && [ ! -e "$R3/out/report.md" ] && [ -z "$(find "$R3/out" -name '.report.*')" ]; } && ok "so is a standard input over it, and no temporary file stays" || no "big stdin: rc=$rc $out"

# --- findings.md
R4=$(prep rep4)
out=$($DA local report "$R4" --findings < "$MSG" 2>&1); rc=$?
{ [ $rc = 0 ] && cmp -s "$MSG" "$R4/out/findings.md" && [ ! -e "$R4/out/report.md" ] && jq -e '.artifacts[0].path == "findings.md"' "$R4/out/manifest.json" >/dev/null; } \
  && ok "--findings writes OUT/findings.md, not report.md, and the manifest names it" || no "findings: rc=$rc $out"

# --- what it refuses
out=$($DA local report "$R4" < /dev/null 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "empty" <<<"$out"; } && ok "an empty message is refused" || no "empty: rc=$rc $out"
RB=$(prep repbuild build); out=$($DA local report "$RB" < "$MSG" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "not a read-only run" <<<"$out" && [ ! -e "$RB/out/report.md" ]; } && ok "a build run is refused: its product is patches" || no "build: rc=$rc $out"
R5=$(prep rep5); mkdir "$T/elsewhere"; rmdir "$R5/out"; ln -s "$T/elsewhere" "$R5/out"
out=$($DA local report "$R5" < "$MSG" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "link" <<<"$out" && [ -z "$(ls -A "$T/elsewhere")" ]; } && ok "an OUT that is a link is refused and nothing is written through it" || no "out link: rc=$rc $out"
ln -s "$R1" "$T/runlink"; out=$($DA local report "$T/runlink" < "$MSG" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "not a run directory" <<<"$out"; } && ok "a link to a run directory is refused" || no "run link: rc=$rc $out"
cp -r "$R2" "$T/qargi.copy12"; rm -f "$T/qargi.copy12/out/report.md"; out=$($DA local report "$T/qargi.copy12" < "$MSG" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "registry" <<<"$out" && [ ! -e "$T/qargi.copy12/out/report.md" ]; } && ok "a directory the lead's registry does not name is refused" || no "unregistered: rc=$rc $out"
$DA local report < "$MSG" >/dev/null 2>&1; [ $? = 2 ] && ok "no RUN is a usage error" || no "usage"
$DA local report "$R1" --nope < "$MSG" >/dev/null 2>&1; [ $? = 2 ] && ok "an unknown option is a usage error" || no "unknown option"

# --- the member: its own run only
R6=$(prep rep6); R7=$(prep rep7)
out=$(QARGI_MEMBER_RUN=$R6 $DA local report "$R6" < "$MSG" 2>&1); rc=$?
{ [ $rc = 0 ] && cmp -s "$MSG" "$R6/out/report.md"; } && ok "with the member mark set it writes the report of the member's own run" || no "member own: rc=$rc $out"
out=$(QARGI_MEMBER_RUN=$R6 $DA local report "$R7" < "$MSG" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "own run" <<<"$out" && [ ! -e "$R7/out/report.md" ]; } && ok "and refuses the run of another member" || no "member other: rc=$rc $out"

# --- the guard: a read-only member may run it, the lead's report verb stays the lead's
guard() { jq -n --arg c "$1" --arg d "$R7/clone" '{tool_name:"Bash", tool_input:{command:$c}, cwd:$d}' | $DA __guard --class read-only >/dev/null 2>&1; }
for c in "qargi local report $R7 < $R7/out/draft.md" "qargi local report $R7 --from draft.md" "qargi local report $R7 --findings --force" "$DA local report $R7 --from draft.md"; do
  guard "$c"; [ $? = 0 ] && ok "the guard lets a read-only member run: $c" || no "guard refused: $c"
done
guard "qargi review save $R7 < $R7/out/draft.md"; [ $? = 2 ] && ok "and still refuses the lead's review save" || no "guard let review save through"
exit $fail
