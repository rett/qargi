#!/usr/bin/env bash
# Roles: qargi role list|show|prompt|check, your own roles, the class a role gives a member and a local run, and the
# role text in a cloud prompt. Run: tests/test_role.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects"

out=$($DA role list 2>&1)
for r in build write review test; do grep -q "^$r " <<<"$out" || no "list lacks $r: $out"; done
grep -q "^review .*read-only .*built-in" <<<"$out" && grep -q "^build .*write .*built-in" <<<"$out" && ok "list shows the four built-in roles with their class" || no "list: $out"
$DA role check >/dev/null 2>&1 && ok "the built-in roles check out" || no "check: $($DA role check 2>&1)"
$DA role show review 2>&1 | grep -q "^class: read-only" && ok "show prints the class" || no "show"
[ "$($DA role prompt build)" = "$(cat roles/build/ROLE.md)" ] && ok "prompt prints the role text as it is" || no "prompt"

# your own roles
mkdir -p "$T/c/roles/audit" "$T/c/roles/probe"
printf '{"class":"read-only","description":"Check dependencies."}\n' > "$T/c/roles/audit/role.json"; printf '# Role: audit\n\nList the dependencies.\n' > "$T/c/roles/audit/ROLE.md"
printf '{"class":"write","description":"Poke."}\n' > "$T/c/roles/probe/role.json"; printf '# Role: probe\n\nTry things.\n' > "$T/c/roles/probe/ROLE.md"
$DA role list | grep -q "^audit .*read-only .*user" && ok "a role under the config directory is listed" || no "user role not listed"
$DA role check audit >/dev/null 2>&1 && ok "a valid role of yours checks out" || no "check audit"
mkdir -p "$T/c/roles/lead" "$T/c/roles/Bad" "$T/c/roles/build2x"
for n in lead Bad; do printf '{"class":"write"}\n' > "$T/c/roles/$n/role.json"; echo x > "$T/c/roles/$n/ROLE.md"; done
$DA role list | grep -qE "^(lead|Bad) " && no "a reserved or malformed role name was listed" || ok "lead and a malformed name are not roles"
mkdir -p "$T/c/roles/build"; printf '{"class":"read-only"}\n' > "$T/c/roles/build/role.json"; echo hijack > "$T/c/roles/build/ROLE.md"
[ "$($DA role show build | sed -n 3p)" = "class: write" ] && ok "a built-in role cannot be shadowed" || no "shadowed: $($DA role show build | head -4)"
rm -rf "$T/c/roles/build" "$T/c/roles/lead" "$T/c/roles/Bad" "$T/c/roles/build2x"
printf '{"class":"sudo"}\n' > "$T/c/roles/probe/role.json"
$DA role check probe >/dev/null 2>&1 && no "an unknown class passed" || ok "an unknown class fails the check"
printf '{"class":"write","description":"Poke."}\n' > "$T/c/roles/probe/role.json"

# members serve roles of yours; the class decides the guard
$DA agent add looker --abilities audit >/dev/null 2>&1 && grep -q 'command: "qargi __guard --class read-only"' "$HOME/.claude/agents/looker.md" && ok "a member of only read-only roles is read-only by class" || no "looker"
$DA agent add mixed --abilities audit,probe >/dev/null 2>&1 && ! grep -q -- '--class' "$HOME/.claude/agents/mixed.md" && ok "a member with a write role names no class" || no "mixed"
$DA agent add audit >/dev/null 2>&1 && no "a member took a role's name" || ok "a member cannot be named after a role"
[ "$($DA agent for audit)" = looker ] && ok "agent for finds the member of a role of yours" || no "for audit: $($DA agent for audit 2>&1)"
$DA agent add forge --abilities build >/dev/null 2>&1; $DA agent add judge --abilities review >/dev/null 2>&1
mkdir -p "$T/c/roles/lint"; printf '{"class":"read-only"}\n' > "$T/c/roles/lint/role.json"; echo "# Role: lint" > "$T/c/roles/lint/ROLE.md"
[ "$($DA agent for lint)" = judge ] && ok "a read-only role with no member falls back to a review member" || no "for lint: $($DA agent for lint 2>&1)"
mkdir -p "$T/c/roles/gen"; printf '{"class":"write"}\n' > "$T/c/roles/gen/role.json"; echo "# Role: gen" > "$T/c/roles/gen/ROLE.md"
[ "$($DA agent for gen)" = forge ] && ok "a write role with no member falls back to a build member" || no "for gen: $($DA agent for gen 2>&1)"
$DA agent for lead >/dev/null 2>&1 && no "agent for lead answered" || ok "lead is not a local role"

# a local run records the role and its class; the guard follows the class
git init -q "$T/repo" && git -C "$T/repo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init && git -C "$T/repo" branch -M main
mkdir -p "$T/scr"
out=$($DA local prepare --repo "$T/repo" --base main --slug a1 --scratch "$T/scr" --role audit 2>&1); RUN=$(sed -n 's/^RUN=//p' <<<"$out")
[ "$(cat "$RUN/class" 2>/dev/null)" = read-only ] && [ "$(cat "$RUN/ability")" = audit ] && grep -q '^CLASS=read-only$' <<<"$out" && ok "prepare records the role and its class" || no "prepare: $out"
guard() { printf '{"tool_name":"Write","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$1" "$RUN/clone" | $DA __guard >/dev/null 2>&1; }
guard "$RUN/clone/x.txt"; [ $? = 2 ] && ok "under a read-only role of yours the clone is refused" || no "clone write allowed"
guard "$RUN/out/report.md"; [ $? = 0 ] && ok "and the report is allowed" || no "report refused"
guard "$RUN/class"; [ $? = 2 ] && ok "a member cannot change the run's class" || no "class file writable"
out=$($DA local prepare --repo "$T/repo" --base main --slug a2 --scratch "$T/scr" --role probe 2>&1); RUN=$(sed -n 's/^RUN=//p' <<<"$out")
guard "$RUN/clone/x.txt"; [ $? = 0 ] && ok "under a write role the clone is writable" || no "write role refused"
$DA local prepare --repo "$T/repo" --base main --slug a3 --scratch "$T/scr" --role nosuch >/dev/null 2>&1 && no "an unknown role was accepted" || ok "an unknown role is refused"
$DA local prepare --repo "$T/repo" --base main --slug a4 --scratch "$T/scr" --role lead >/dev/null 2>&1 && no "lead was accepted as a local role" || ok "lead is refused as a local role"

# a cloud agent of your role gets its text; a read-only role has no edit tool by default
. lib/lib.sh
agent_prompt audit | grep -q "List the dependencies." && ok "the cloud prompt of a role carries its text" || no "prompt text"
tools_off audit "" | grep -q edit && ! tools_off probe "" | grep -q edit && ok "a read-only class turns the edit tool off in the cloud" || no "tools_off"

rm -rf "$T"
[ $fail = 0 ] && echo "role tests passed" || { echo "role tests FAILED"; exit 1; }
