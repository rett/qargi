#!/usr/bin/env bash
# The Claude Code target of packs: render a project's enabled skills and tools into a state directory, with a
# manifest and a drift check. Offline, hermetic. Run: tests/test_packs_claude.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s"
DA=./bin/qargi
proj() { jq -n --arg p "$1" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]},
         write:{base:"gh-pages",push:{mode:"none"},model:"claude-opus-5-5",effort:"medium",apt:[],skills:[]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha
D=$T/s/claude/alpha

tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
seal() { local tok; tok=$($DA skill seal "$1" | tok_of); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
mkskill() { $DA skill new "$1" >/dev/null; sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
apply() { $DA packs apply --target claude-code alpha "$@"; }
plan() { apply | tok_of; }
go() { apply --plan "$(plan)" --approved test; }
check() { $DA packs check --target claude-code alpha; }

mkskill s-all; mkskill s-build; mkskill s-write
mkdir -p "$T/c/packs/skills/s-all/refs"; echo ref > "$T/c/packs/skills/s-all/refs/r.md"
printf '#!/bin/sh\necho hi\n' > "$T/c/packs/skills/s-all/run.sh"; chmod 755 "$T/c/packs/skills/s-all/run.sh"; seal s-all
$DA skill link s-all --scope project --project alpha >/dev/null
$DA skill link s-build --scope project-role --project alpha --role build >/dev/null
$DA skill link s-write --scope project-role --project alpha --role write >/dev/null

# --- plan changes nothing; apply needs the token
out=$(apply); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && [ ! -e "$D" ] && grep -q "added .*skill s-all" <<<"$out" && grep -q "advisory" <<<"$out" && ok "the plan lists the packs and says role scoping is advisory, and writes nothing" || no "plan: $out"
[ ! -e "$T/s/claude/.alpha.new" ] && ok "a plan leaves no staging directory" || no "staging left behind"
apply --approved x >/dev/null 2>&1 && no "applied without the plan token" || ok "apply refuses without the plan token"
apply --plan 000000000000 --approved x >/dev/null 2>&1 && no "applied with a wrong token" || ok "apply refuses a wrong token"
[ ! -e "$D" ] && ok "apply without approval changes nothing" || no "apply without approval wrote $D"
out=$(apply --plan "$tok" --approved "test")
grep -q "^launch: claude --add-dir $D\$" <<<"$out" && ok "apply ends with the launch command (no mcp/settings flags without tools)" || no "launch line: $out"
tail -1 "$T/s/audit.log" | jq -e '.verb=="packs-apply-claude-code"' >/dev/null && ok "apply is audit-logged" || no "audit: $(tail -1 "$T/s/audit.log")"

# --- union across roles, roles recorded, exact copy
for s in s-all s-build s-write; do [ -f "$D/.claude/skills/$s/SKILL.md" ] || no "$s not rendered"; done
[ ! -e "$D/.claude/skills/s-all/.pack.json" ] && cmp -s "$D/.claude/skills/s-all/refs/r.md" "$T/c/packs/skills/s-all/refs/r.md" && ok "skills are copied without .pack.json" || no "copy"
[ "$(jq -c '[.packs[]|{n:.name,r:.roles}]|sort_by(.n)' "$D/MANIFEST.json")" = '[{"n":"s-all","r":["build","write"]},{"n":"s-build","r":["build"]},{"n":"s-write","r":["write"]}]' ] && ok "the union is rendered and the roles are recorded" || no "manifest roles: $(jq -c .packs "$D/MANIFEST.json")"
jq -e '.schema==1 and .project=="alpha" and .role_scoping=="advisory" and (.packs[0].sha256|length)==16 and (.packs[0].files|length)>0' "$D/MANIFEST.json" >/dev/null && ok "the manifest has schema, project, advisory scoping, hashes and files" || no "manifest shape"
[ -x "$D/.claude/skills/s-all/run.sh" ] && [ "$(stat -c %a "$D/.claude/skills/s-all/refs/r.md")" = 644 ] && ok "modes are 0644, executables stay executable" || no "modes"
check >/dev/null && ok "check passes on a fresh render" || no "check on fresh render: $(check)"

# --- idempotent re-apply, atomic swap
gen=$(jq -r .generated "$D/MANIFEST.json"); sleep 1
out=$(go); grep -q "no change in packs" <<<"$(apply)" && [ "$(jq -r .generated "$D/MANIFEST.json")" = "$gen" ] && [ ! -e "$T/s/claude/.alpha.new" ] && [ "$(find "$T/s/claude" -mindepth 1 -maxdepth 1 | wc -l)" = 1 ] && ok "re-apply is idempotent and leaves no sibling directory" || no "re-apply: $out"

# --- packs_off respected, enablement drift, removal
$DA skill disable alpha write s-write >/dev/null
check >/dev/null 2>&1 && no "enablement drift not reported after disabling" || ok "check reports a pack disabled since the render"
check 2>&1 | grep -q "enablement: skill s-write" && ok "the enablement finding names the pack" || no "enablement text"
apply | grep -q "removed .*skill s-write" && ok "the plan shows the removal" || no "removal not planned"
go >/dev/null; [ ! -e "$D/.claude/skills/s-write" ] && jq -e '[.packs[].name]|index("s-write")|not' "$D/MANIFEST.json" >/dev/null && ok "packs_off is respected" || no "s-write still rendered"
check >/dev/null && ok "check passes again after re-apply" || no "check after re-apply"
$DA skill unlink s-build --scope project-role --project alpha --role build >/dev/null
check 2>&1 | grep -q "no longer enabled" && ok "a stale manifest after unlinking is reported" || no "stale manifest not reported"
go >/dev/null; $DA skill enable alpha write s-write >/dev/null; go >/dev/null

# --- tool pack -> mcp.json, settings.json
printf '%s' '{"name":"issues","url":"https://mcp.example.net/","vault_ids":["vlt_abc123"],"tools":{"list_issues":"always_allow","create_issue":"always_ask","other":"auto"}}' > "$T/t.json"
itok=$($DA tool import "$T/t.json" | tok_of); $DA tool import "$T/t.json" --plan "$itok" --approved test >/dev/null
$DA tool link issues --scope project-role --project alpha --role build >/dev/null
out=$(apply); grep -q "needs credentials you configure yourself.*issues" <<<"$out" && ok "the plan lists tools that need credentials" || no "credentials note: $out"
out=$(go)
jq -e '.mcpServers.issues.url=="https://mcp.example.net/"' "$D/mcp.json" >/dev/null && ok "a tool pack becomes an mcp.json server entry" || no "mcp.json: $(cat "$D/mcp.json" 2>&1)"
jq -e '.permissions.allow==["mcp__issues__list_issues"] and .permissions.ask==["mcp__issues__create_issue"]' "$D/settings.json" >/dev/null && ok "always_allow -> allow, always_ask -> ask" || no "settings.json: $(cat "$D/settings.json" 2>&1)"
grep -q "^launch: claude --add-dir $D --mcp-config $D/mcp.json --settings $D/settings.json\$" <<<"$out" && ok "the launch command carries the mcp and settings flags" || no "launch: $out"
check >/dev/null && ok "check passes with a tool pack" || no "check with tool: $(check)"
echo '{}' > "$D/mcp.json"; check 2>&1 | grep -q "differs from the manifest: mcp.json" && ok "a tampered mcp.json is reported" || no "mcp.json tamper"
go >/dev/null

# --- rendered drift: tampered and extra files
echo tamper >> "$D/.claude/skills/s-all/SKILL.md"
check 2>&1 | grep -q "differs from the manifest: .claude/skills/s-all/SKILL.md" && ok "a tampered rendered file is reported" || no "tamper not reported"
go >/dev/null; check >/dev/null && ok "re-apply repairs it" || no "not repaired"
echo x > "$D/.claude/skills/s-all/extra.md"
check 2>&1 | grep -q "extra file .claude/skills/s-all/extra.md" && ok "an extra file is reported" || no "extra not reported"
go >/dev/null; rm "$D/.claude/skills/s-all/refs/r.md"
check 2>&1 | grep -q "missing file .claude/skills/s-all/refs/r.md" && ok "a missing file is reported" || no "missing not reported"
go >/dev/null

# --- shadowing
mkdir -p "$HOME/.claude/skills/s-all"
check 2>&1 | grep -q "shadowing: skill s-all is also in ~/.claude/skills" && ok "a skill of the same name in ~/.claude/skills is reported" || no "home shadow"
apply | grep -q "WARNING: skill s-all is also in ~/.claude/skills" && ok "the plan warns about shadowing" || no "plan shadow warning"
rmdir "$HOME/.claude/skills/s-all"
mkdir -p "$T/repo/.claude/skills/s-build"; jq --arg p "$T/repo" '.repo.path=$p' "$T/c/projects/alpha.json" > "$T/p.json" && mv "$T/p.json" "$T/c/projects/alpha.json"
$DA skill link s-build --scope project-role --project alpha --role build >/dev/null; go >/dev/null
check 2>&1 | grep -q "shadowing: skill s-build is also in the project checkout" && ok "a skill in the project checkout's .claude/skills is reported" || no "checkout shadow"
rmdir "$T/repo/.claude/skills/s-build"; check >/dev/null && ok "no shadowing, no finding" || no "check after removing shadow"

# --- a manifest that is missing
rm "$D/MANIFEST.json"; check 2>&1 | grep -q "manifest missing" && ok "a missing manifest is reported" || no "manifest missing"
go >/dev/null

# --- a drifted library pack is refused by apply and reported by check
echo more >> "$T/c/packs/skills/s-build/SKILL.md"
out=$(apply 2>&1) && no "apply planned a drifted pack" || { grep -q "library drift" <<<"$out" && ok "apply refuses a library pack changed since approved" || no "drift message: $out"; }
check 2>&1 | grep -q "library: skill:s-build: library drift" && ok "check reports library drift" || no "check library drift"
cmp -s "$D/.claude/skills/s-build/SKILL.md" "$T/c/packs/skills/s-build/SKILL.md" && no "the drifted file was rendered" || ok "the live render is untouched by the refusal"
sed -i '$d' "$T/c/packs/skills/s-build/SKILL.md"

# --- the output root stays under the state directory
mkdir -p "$T/elsewhere"; rm -rf "$T/s/claude"; ln -s "$T/elsewhere" "$T/s/claude"
apply >/dev/null 2>&1 && no "rendered through a symlinked output root" || ok "an output root that resolves outside the state directory is refused"
[ -z "$(ls -A "$T/elsewhere")" ] && ok "nothing was written outside the state directory" || no "wrote outside"
rm "$T/s/claude"
$DA packs apply --target nope alpha >/dev/null 2>&1 && no "unknown target accepted" || ok "an unknown target is refused"
$DA packs check alpha >/dev/null 2>&1 && no "check without a target" || ok "check needs a target"

# --- the cloud path does not take the new route
$DA packs apply nobody --asked x --target managed-agents >/dev/null 2>&1; [ ! -e "$T/s/claude/alpha" ] && ok "managed-agents still means the cloud path" || no "cloud route"
exit $fail
