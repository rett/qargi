#!/usr/bin/env bash
# `qargi packs seed`: the baseline packs shipped with qargi are added to the library, updated only while the user has not
# changed them, and never overwrite an edited copy. The tool is copied to a temporary directory with fixture packs, so the
# shipped text is under the test's control (case 13 checks the real packs/ directory). Offline, hermetic.
# Run: tests/test_packs_seed.sh
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }

# The tool under test: a copy of bin, lib and VERSION, with fixture packs and their manifest.
mkdir -p "$T/tool/packs/skills"
cp -r bin lib VERSION "$T/tool/"
VER=$(cat "$T/tool/VERSION")
DA=$T/tool/bin/qargi
SK=$T/tool/packs/skills
NAMES="alpha-pack beta-pack gamma-pack"
mkpack() { mkdir -p "$SK/$1"; printf -- '---\nname: %s\ndescription: Use when testing %s.\n---\n# %s\n%s\n' "$1" "$1" "$1" "$2" > "$SK/$1/SKILL.md"; }
manifest() { # names of the shipped packs
  local n; for n in "$@"; do jq -n --arg n "$n" '{kind:"skill",name:$n,propose:"tracked *.sh"}'; done | jq -s '{schema:1,packs:.}' > "$T/tool/packs/baseline.json"; }
shipped() { rm -rf "${SK:?}"/*; local n; for n in $NAMES; do mkpack "$n" "first text of $n"; done; manifest $NAMES; }
hash_of() { (cd "$1" && find . -type f ! -name .pack.json -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16); }
tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
fresh() { rm -rf "$T/c" "$T/s"; export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s"; LIB=$T/c/packs; shipped; }
proj() { jq -n --arg p "$1" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
seal() { local tok; tok=$($DA skill seal "$1" | tok_of); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
# plan, then apply with the token it printed; OUT holds the output of the last seed call, RC its exit status
plan() { OUT=$($DA packs seed 2>&1); RC=$?; TOK=$(tok_of <<<"$OUT"); }
apply() { plan; [ -n "$TOK" ] || return 1; OUT=$($DA packs seed --plan "$TOK" --approved "test go-ahead" 2>&1); RC=$?; }
has() { grep -Eq -- "$1" <<<"$OUT"; }
rec() { jq -r "$2" "$LIB/skills/$1/.pack.json"; }
shown() { echo "$OUT" | head -5 | sed 's/^/       | /'; }
empty_lib() { [ -z "$(ls -A "$LIB/skills" 2>/dev/null)" ]; }

# --- 1. a plan on an empty library: every pack is an add, a token is printed, nothing is stored
fresh
plan
H_A=$(hash_of "$SK/alpha-pack"); H_B=$(hash_of "$SK/beta-pack"); H_G=$(hash_of "$SK/gamma-pack")
if [ "$RC" = 0 ] && has "add +skill alpha-pack \(content $H_A\)" && has "add +skill beta-pack \(content $H_B\)" && has "add +skill gamma-pack \(content $H_G\)"; then
  ok "the plan adds every shipped pack, with its content hash"; else no "plan lines (rc=$RC)"; shown; fi
[ -n "$TOK" ] && ok "the plan prints a token" || no "no plan token"
empty_lib && ok "planning stores nothing" || no "planning stored: $(ls -A "$LIB/skills")"
[ "$fail" = 0 ] || { echo "stopping: the cases that follow need a working plan"; exit 1; }

# --- 2. a wrong token is refused and nothing is stored
OUT=$($DA packs seed --plan 000000000000 --approved x 2>&1); RC=$?
{ [ "$RC" != 0 ] && empty_lib; } && ok "a wrong token is refused and stores nothing" || no "wrong token (rc=$RC)"
OUT=$($DA packs seed --plan "$TOK" 2>&1); RC=$?
{ [ "$RC" != 0 ] && empty_lib; } && ok "the right token without --approved is refused" || no "token without approval (rc=$RC)"

# --- 3. apply: the library copy is the shipped one and records where it came from
apply
if [ "$RC" = 0 ] && has "seeded skill alpha-pack \(content $H_A\)" && has "seeded skill beta-pack \(content $H_B\)" && has "seeded skill gamma-pack \(content $H_G\)"; then
  ok "apply prints a seeded line per pack"; else no "apply output (rc=$RC)"; shown; fi
good=1
for n in $NAMES; do
  cmp -s "$SK/$n/SKILL.md" "$LIB/skills/$n/SKILL.md" || good=0
  [ "$(rec "$n" .source)" = "qargi-baseline $VER" ] || good=0
  [ "$(rec "$n" .kind)" = skill ] || good=0
  [ "$(rec "$n" .shipped)" = "$(hash_of "$LIB/skills/$n")" ] || good=0
  [ "$(rec "$n" .sha256)" = "$(hash_of "$LIB/skills/$n")" ] || good=0
done
[ "$good" = 1 ] && ok "the copies equal the shipped text; records say source qargi-baseline $VER and carry shipped" || no "library copies or records"
[ -z "$(find "$LIB/skills" -maxdepth 1 -name '.seed-*')" ] && ok "no staging directory is left behind" || no "staging left: $(ls -A "$LIB/skills")"
tail -1 "$T/s/audit.log" 2>/dev/null | jq -e '.verb=="packs-seed"' >/dev/null && ok "the apply is in the audit log" || no "audit line: $(tail -1 "$T/s/audit.log" 2>/dev/null)"

# --- 4. a rerun has nothing to do
plan
{ [ "$RC" = 0 ] && has "current +skill alpha-pack" && has "nothing to seed" && [ -z "$TOK" ]; } && ok "a second run says nothing to seed, with no token" || { no "rerun (rc=$RC)"; shown; }

# --- 5. a changed shipped text is an update, applied while the copy was never edited
mkpack alpha-pack "second text of alpha-pack"
H_A2=$(hash_of "$SK/alpha-pack")
plan
{ has "update +skill alpha-pack \(content $H_A -> $H_A2; links: none\)" && has "current +skill beta-pack" && [ -n "$TOK" ]; } && ok "a changed shipped pack is an update (links: none)" || { no "update plan"; shown; }
apply
{ [ "$RC" = 0 ] && has "seeded skill alpha-pack \(content $H_A2\)" && cmp -s "$SK/alpha-pack/SKILL.md" "$LIB/skills/alpha-pack/SKILL.md" \
  && [ "$(rec alpha-pack .shipped)" = "$H_A2" ] && [ "$(rec alpha-pack .sha256)" = "$H_A2" ]; } && ok "the update replaces the copy and moves shipped" || no "update apply (rc=$RC)"

# --- 6. an edited copy that was sealed is the user's: kept, never overwritten (also when other packs are updated)
fresh; apply
echo "my own rule" >> "$LIB/skills/beta-pack/SKILL.md"; seal beta-pack
H_BE=$(hash_of "$LIB/skills/beta-pack")
mkpack beta-pack "second text of beta-pack"; H_B2=$(hash_of "$SK/beta-pack")
plan
{ [ "$RC" = 0 ] && has "kept +skill beta-pack: edited in your library \(content $H_BE; shipped $H_B2\)" && [ -z "$TOK" ] && has "nothing to seed"; } \
  && ok "a sealed edit is kept, and with nothing else to do there is no token" || { no "kept (sealed) plan (rc=$RC)"; shown; }
mkpack gamma-pack "second text of gamma-pack"
apply
{ [ "$RC" = 0 ] && has "seeded skill gamma-pack" && [ "$(hash_of "$LIB/skills/beta-pack")" = "$H_BE" ] && grep -q "my own rule" "$LIB/skills/beta-pack/SKILL.md"; } \
  && ok "applying another update leaves the sealed edit alone" || no "sealed edit touched (rc=$RC)"

# --- 7. an edit not yet sealed is kept as well
fresh; apply
echo "unsealed edit" >> "$LIB/skills/beta-pack/SKILL.md"
H_BE=$(hash_of "$LIB/skills/beta-pack")
mkpack beta-pack "second text of beta-pack"; H_B2=$(hash_of "$SK/beta-pack")
mkpack gamma-pack "second text of gamma-pack"
apply
{ [ "$RC" = 0 ] && has "kept +skill beta-pack: edited in your library \(content $H_BE; shipped $H_B2\)" && [ "$(hash_of "$LIB/skills/beta-pack")" = "$H_BE" ]; } \
  && ok "an unsealed edit is kept and not overwritten" || { no "kept (unsealed) (rc=$RC)"; shown; }

# --- 8. a pack the user created or imported under a baseline name belongs to the user
fresh
$DA skill new alpha-pack >/dev/null
mine=$(hash_of "$LIB/skills/alpha-pack")
plan
{ has "kept +skill alpha-pack: the name belongs to a pack you created or imported" && has "add +skill beta-pack" && [ "$(hash_of "$LIB/skills/alpha-pack")" = "$mine" ]; } \
  && ok "a created pack under a baseline name is kept" || { no "created-pack plan (rc=$RC)"; shown; }
apply
{ [ "$(hash_of "$LIB/skills/alpha-pack")" = "$mine" ] && [ "$(rec alpha-pack .source)" != "qargi-baseline $VER" ]; } && ok "and it stays the user's after the apply" || no "created pack overwritten"
fresh; mkdir -p "$T/imp/beta-pack"; printf -- '---\nname: beta-pack\ndescription: Use when importing.\n---\nbody\n' > "$T/imp/beta-pack/SKILL.md"
itok=$($DA skill import "$T/imp/beta-pack" | tok_of); $DA skill import "$T/imp/beta-pack" --plan "$itok" --approved test >/dev/null 2>&1
plan
has "kept +skill beta-pack: the name belongs to a pack you created or imported" && ok "an imported pack under a baseline name is kept" || { no "imported-pack plan"; shown; }

# --- 9. a tool under a baseline name is not replaced either
fresh
printf '%s' '{"name":"gamma-pack","url":"https://mcp.example.net/","tools":{"list_things":"always_allow"}}' > "$T/tool.json"
ttok=$($DA tool import "$T/tool.json" | tok_of); $DA tool import "$T/tool.json" --plan "$ttok" --approved test >/dev/null 2>&1
[ -f "$LIB/tools/gamma-pack.json" ] || no "setup: the fixture tool was not stored"
plan
{ has "kept +skill gamma-pack: the name belongs to a pack you created or imported" && has "add +skill alpha-pack"; } && ok "a tool with a baseline name keeps the name" || { no "tool-name plan (rc=$RC)"; shown; }
apply
{ [ ! -e "$LIB/skills/gamma-pack" ] && [ -f "$LIB/tools/gamma-pack.json" ]; } && ok "no skill is stored over the tool's name" || no "skill stored beside the tool"

# --- 10. --install only adds, without a token, and says when newer versions ship
fresh
OUT=$($DA packs seed --install 2>&1); RC=$?
{ [ "$RC" = 0 ] && has "add +skill alpha-pack" && has "seeded skill alpha-pack" && ! has "plan token" && cmp -s "$SK/alpha-pack/SKILL.md" "$LIB/skills/alpha-pack/SKILL.md"; } \
  && ok "--install adds every missing pack with no token" || { no "install on an empty library (rc=$RC)"; shown; }
! has "newer shipped versions" && ok "no note when nothing newer ships" || no "unexpected note"
old=$(hash_of "$LIB/skills/alpha-pack")
mkpack alpha-pack "second text of alpha-pack"; rm -rf "${LIB:?}/skills/gamma-pack"
OUT=$($DA packs seed --install 2>&1); RC=$?
{ [ "$RC" = 0 ] && has "note: newer shipped versions: run qargi packs seed" && has "seeded skill gamma-pack" && ! has "plan token" && [ "$(hash_of "$LIB/skills/alpha-pack")" = "$old" ]; } \
  && ok "--install adds a missing pack, never updates, and points at the full seed" || { no "install with a newer pack (rc=$RC)"; shown; }
OUT=$($DA packs seed --install 2>&1); RC=$?; [ "$RC" = 0 ] && ok "--install is repeatable" || no "second --install (rc=$RC)"

# --- 11. seeding creates no links
fresh
before=$(cat "$LIB/links.json"); apply
{ [ "$(cat "$LIB/links.json")" = "$before" ] && [ "$(jq '.links|length' "$LIB/links.json")" = 0 ]; } && ok "seed leaves the links alone" || no "links changed: $(cat "$LIB/links.json")"
$DA packs seed --install >/dev/null 2>&1; [ "$(jq '.links|length' "$LIB/links.json")" = 0 ] && ok "and so does --install" || no "install made links"

# --- 12. an updated pack that is linked prints what to run next
fresh; proj apple; apply
$DA skill link alpha-pack --scope project --project apple >/dev/null 2>&1 || no "setup: linking the seeded pack failed"
links=$(cat "$LIB/links.json")
mkpack alpha-pack "second text of alpha-pack"
plan
{ has "update +skill alpha-pack" && ! has "alpha-pack \(content [0-9a-f]+ -> [0-9a-f]+; links: none\)"; } && ok "the update line names the links it reaches" || { no "linked update plan"; shown; }
apply
{ [ "$RC" = 0 ] && has "seeded skill alpha-pack" && has "qargi packs apply --target claude-code apple" && [ "$(cat "$LIB/links.json")" = "$links" ]; } \
  && ok "the apply prints the follow-up for the project and keeps the link" || { no "follow-up (rc=$RC)"; echo "$OUT" | sed 's/^/       | /'; }

# --- 13. the packs shipped in this repository
PK=$ROOT/packs
if [ -d "$PK/skills" ] && [ -f "$PK/baseline.json" ]; then
  jq -e '.schema==1 and (.packs|length)>0 and all(.packs[]; .kind=="skill" and (.name|test("^[a-z0-9-]+$")) and (.propose|length>0))' "$PK/baseline.json" >/dev/null \
    && ok "baseline.json is well formed" || no "baseline.json shape"
  listed=$(jq -r '.packs[].name' "$PK/baseline.json" | sort); present=$(ls "$PK/skills" | sort)
  [ "$listed" = "$present" ] && ok "every packs/skills directory is listed in baseline.json and the reverse" || no "listed [$listed] vs present [$present]"
  for d in "$PK"/skills/*/; do
    n=$(basename "$d"); f=${d}SKILL.md; bad=""
    [ -f "$f" ] || { no "$n: no SKILL.md"; continue; }
    [ "$(sed -n 1p "$f")" = --- ] || bad="$bad no-front-matter"
    fm=$(awk 'NR==1{next} /^---$/{exit} {print}' "$f")
    [ "$(sed -n 's/^name: *//p' <<<"$fm")" = "$n" ] || bad="$bad name!=dir"
    { [ "$(wc -l <<<"$fm")" = 2 ] && grep -q '^description: ' <<<"$fm"; } || bad="$bad front-matter-not-name+description"
    awk 'NR>1 && /^---$/{f=1} END{exit !f}' "$f" || bad="$bad unclosed-front-matter"
    grep -Eiqw 'curl|wget|ssh|scp|nc|ncat' "$f" && bad="$bad network-word"
    grep -Eq 'qargi (skill|tool|packs|project|local|memory|discover|review|feature)' "$f" && bad="$bad names-a-qargi-verb"
    [ -z "$(find "$d" -type l)" ] || bad="$bad symlink"
    [ -z "$bad" ] && ok "shipped pack $n: front matter, name and wording" || no "shipped pack $n:$bad"
    fresh; out=$($DA skill import "$d" 2>&1); rc=$?
    { [ "$rc" = 0 ] && ! grep -q FAIL <<<"$out" && ! grep -q "network commands mentioned" <<<"$out"; } && ok "shipped pack $n passes the library review" || { no "shipped pack $n review (rc=$rc)"; echo "$out" | grep -E 'FAIL|network' | sed 's/^/       | /'; }
  done
else
  no "this repository ships no packs/ directory with baseline.json and skills/"
fi

# --- 14. a missing packs directory is an error that names the place
fresh; mv "$T/tool/packs" "$T/tool/packs.away"
OUT=$($DA packs seed 2>&1); RC=$?
{ [ "$RC" != 0 ] && has "no baseline packs shipped at $T/tool/packs"; } && ok "without packs/ the seed dies naming the directory" || { no "missing packs (rc=$RC)"; shown; }
mv "$T/tool/packs.away" "$T/tool/packs"

exit "$fail"
