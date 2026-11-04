#!/usr/bin/env bash
# The render of packs for the local runtime (Claude Code here): render a project's enabled skills and tools into a state directory, with a
# manifest and a drift check. Offline, hermetic. Run: tests/test_packs_render.sh
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
  models:{provider:"claude-code"},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha
D=$T/s/render/alpha/claude-code

tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
seal() { local tok; tok=$($DA skill seal "$1" | tok_of); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
mkskill() { $DA skill new "$1" --compatible any >/dev/null; sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
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
[ ! -e "$T/s/render/alpha/.claude-code.new" ] && [ -z "$(find "$T/s/render" -mindepth 1 -maxdepth 2 -name '.*')" ] && ok "a plan leaves no staging directory" || no "staging left behind"
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
out=$(go); grep -q "no change in packs" <<<"$(apply)" && [ "$(jq -r .generated "$D/MANIFEST.json")" = "$gen" ] && [ -z "$(find "$T/s/render" -mindepth 1 -maxdepth 2 -name '.*')" ] && [ "$(find "$T/s/render" -mindepth 1 -maxdepth 1 | wc -l)" = 1 ] && [ "$(find "$T/s/render/alpha" -mindepth 1 -maxdepth 1 | wc -l)" = 1 ] && ok "re-apply is idempotent and leaves no sibling directory" || no "re-apply: $out"

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
itok=$($DA tool import "$T/t.json" --compatible any | tok_of); $DA tool import "$T/t.json" --compatible any --plan "$itok" --approved test >/dev/null
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
mkdir -p "$T/elsewhere"; rm -rf "$T/s/render"; ln -s "$T/elsewhere" "$T/s/render"
apply >/dev/null 2>&1 && no "rendered through a symlinked output root" || ok "an output root that resolves outside the state directory is refused"
[ -z "$(ls -A "$T/elsewhere")" ] && ok "nothing was written outside the state directory" || no "wrote outside"
rm "$T/s/render"
mkdir -p "$T/s/render"; ln -s "$T/elsewhere" "$T/s/render/alpha"
apply >/dev/null 2>&1 && no "rendered through a symlinked project directory" || ok "a project render directory that is a symlink is refused"
[ -z "$(ls -A "$T/elsewhere")" ] && ok "nothing was written through it" || no "wrote through the project link"
rm -rf "$T/s/render"
$DA packs apply --target nope alpha >/dev/null 2>&1 && no "unknown target accepted" || ok "an unknown target is refused"
$DA packs check alpha >/dev/null 2>&1 && no "check without a target" || ok "check needs a target"

# --- compatible_providers: a pack the project's provider cannot use is left out of the render, with a note, never rendered silently
mkp() { $DA skill new "$1" --compatible "$2" >/dev/null; sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; $DA skill link "$1" --scope project --project alpha >/dev/null; }
mkp s-other elsewhere; mkp s-rt claude; mkp s-mix "elsewhere,claude"
out=$(apply)
grep -q "skipped skill s-other: not compatible with claude-code (it declares elsewhere)" <<<"$out" && ok "the plan says which pack was skipped and why" || no "skip line in the plan: $out"
grep -q "added .*skill s-rt" <<<"$out" && grep -q "added .*skill s-mix" <<<"$out" && ! grep -q "added .*skill s-other" <<<"$out" && ok "a pack that names the project's runtime is rendered, one that does not is not" || no "plan packs: $out"
go >/dev/null
[ -f "$D/.claude/skills/s-rt/SKILL.md" ] && [ -f "$D/.claude/skills/s-mix/SKILL.md" ] && [ ! -e "$D/.claude/skills/s-other" ] && ! jq -e '[.packs[].name]|index("s-other")' "$D/MANIFEST.json" >/dev/null && ok "the skipped pack is not in the render or its manifest" || no "render has s-other"
out=$(check 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^note: skipped skill s-other: not compatible with claude-code" <<<"$out" && ok "check passes and notes the skip (a skip is not a finding)" || no "check (rc=$rc): $out"
$DA skill effective alpha build | grep -q "^skipped skill s-other: not compatible with claude-code" && ok "effective shows the skipped pack" || no "effective: $($DA skill effective alpha build)"
# the pack's declaration changes: the render is then stale and says so
jq '.compatible_providers = ["claude"]' "$T/c/packs/skills/s-other/.pack.json" > "$T/rec.tmp" && cp "$T/rec.tmp" "$T/c/packs/skills/s-other/.pack.json"
out=$(check 2>&1) && no "check passed after a declaration was edited by hand" || { grep -q "skill:s-other: library drift\|skill s-other" <<<"$out" && ok "a declaration edited by hand is drift, not a quiet skip or a quiet render" || no "edited declaration: $out"; }
jq '.compatible_providers = ["elsewhere"]' "$T/c/packs/skills/s-other/.pack.json" > "$T/rec.tmp" && cp "$T/rec.tmp" "$T/c/packs/skills/s-other/.pack.json"
check >/dev/null 2>&1 && ok "put back, check passes" || no "check after putting the declaration back"
$DA skill unlink s-other --scope project --project alpha >/dev/null; $DA skill unlink s-rt --scope project --project alpha >/dev/null; $DA skill unlink s-mix --scope project --project alpha >/dev/null; go >/dev/null
rm -rf "$T/s/render"   # the next case needs no render of alpha

# --- the cloud path does not take the new route
$DA packs apply nobody --asked x --target managed-agents >/dev/null 2>&1; [ ! -e "$T/s/render/alpha" ] && ok "managed-agents still means the cloud path" || no "cloud route"
# --- a project that names a runtime per surface (models.provider is an object): the render is the local surface's, and the cloud
# runtime is not asked about (the verbs used to refuse an object that names two different runtimes)
proj gamma; jq '.models.provider = {local: "claude-code", cloud: "claude-platform"}' "$T/c/projects/gamma.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/gamma.json"
gtok=$($DA packs apply --target claude-code gamma 2>&1 | tok_of)
[ -n "$gtok" ] && ok "an object-form models.provider with different runtimes: apply plans the local surface's render" || no "object-form plan: $($DA packs apply --target claude-code gamma 2>&1)"
out=$($DA packs apply --target claude-code gamma --plan "$gtok" --approved test 2>&1); gd=$(sed -n 's/^applied: //p' <<<"$out")
[ -n "$gd" ] && [ -f "$gd/MANIFEST.json" ] && grep -q "^launch: claude --add-dir $gd\$" <<<"$out" && ok "the render is made and the launch line is the local runtime's" || no "object-form apply: $out"
out=$($DA packs check --target claude-code gamma 2>&1); rc=$?
[ "$rc" = 0 ] && ok "check passes for it" || no "object-form check (rc=$rc): $out"
jq '.models.provider = {cloud: "claude-platform"}' "$T/c/projects/gamma.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/gamma.json"
out=$($DA packs check --target claude-code gamma 2>&1); rc=$?
[ "$rc" = 2 ] && [ "$out" = "qargi: project gamma has no local provider: set one with qargi project set gamma models.provider.local NAME" ] && ok "an object that names only a cloud runtime has no local provider: exit 2 and the fix" || no "cloud-only object (rc=$rc): $out"
# --- the renderer is neutral: the skills directory, the MCP file and entry, the permission rule and the settings file come from the
# runtime's definition. fakert is a definition in a copy of the tool with its own names for all of them (a schema 2 file made from
# claude-code's); it has no agent hooks, no adapter and a launch line of its own.
ROOT=$PWD; TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$ROOT" "$TOOL"
FX=$TOOL/bin/qargi
mkfake() { # name jq-filter: a runtime made from claude-code's definition
  jq --arg n "$1" '.provider = $n | .family = null | .adapter = null | .adapter_verbs = [] | .resources.skills.project_dir = ".fk/skills" | .resources.skills.user_dir = "~/.fk/skills"
    | .resources.skills.exclusion = null | .resources.settings.files = [{scope:"user",path:"~/.fk/settings.json",format:"json"}] | .session.render_target = "fk-render"
    | .session.launch = "fk run --render {render}[ --servers {render}/conf/servers.json]" | '"$2" "$ROOT/lib/providers/claude-code.json" > "$TOOL/lib/providers/$1.json"
}
mkfake fakert '.resources.mcp = {file:"conf/servers.json",format:"json",root_pointer:"/servers/remote",entry:{transport:"http",address:"{url}",label:"{name}"},permission_rule:"{server}.{tool}"}
  | .resources.settings.allow_pointer = "/rules/yes" | .renderers.packs = {label:"FakeRT",settings:{file:"rules.json",ask_pointer:"/rules/prompt"}}'
mkfake nomcp 'del(.resources.mcp) | del(.renderers) | .resources.settings.allow_pointer = null'
proj delta; jq '.models = {provider: "fakert"}' "$T/c/projects/delta.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/delta.json"
$DA skill link s-all --scope project --project delta >/dev/null; $DA tool link issues --scope project --project delta >/dev/null
FD=$T/s/render/delta/fakert
fapply() { $FX packs apply --target fk-render delta "$@"; }
out=$(fapply); ftok=$(tok_of <<<"$out")
[ -n "$ftok" ] && grep -q "^fk-render target for delta -> $FD\$" <<<"$out" && grep -q "role scoping is advisory: FakeRT cannot enforce" <<<"$out" && grep -q "^  tool entry: issues.\*  (see conf/servers.json and rules.json)\$" <<<"$out" \
  && ok "another runtime: the plan names its target and label, and the tool entry in its own rule form and files" || no "fakert plan: $out"
out=$(fapply --plan "$ftok" --approved test 2>&1)
[ -f "$FD/.fk/skills/s-all/SKILL.md" ] && [ ! -e "$FD/.claude" ] && cmp -s "$FD/.fk/skills/s-all/refs/r.md" "$T/c/packs/skills/s-all/refs/r.md" && ok "another runtime: the skills go to its skills directory and nothing is made of Claude Code's" || no "fakert skills: $out; $(find "$FD" | head -20)"
jq -e '.servers.remote.issues == {transport:"http",address:"https://mcp.example.net/",label:"issues"} and (keys == ["servers"])' "$FD/conf/servers.json" >/dev/null && ok "another runtime: the tool pack is an entry built from its template, under its root pointer, in its file" || no "fakert servers: $(cat "$FD/conf/servers.json" 2>&1)"
jq -e '.rules.yes == ["issues.list_issues"] and .rules.prompt == ["issues.create_issue"] and (.rules | keys == ["prompt","yes"]) and (keys == ["rules"])' "$FD/rules.json" >/dev/null && ok "another runtime: the permission rules use its rule form and its pointers (no deny pointer, no deny list)" || no "fakert rules: $(cat "$FD/rules.json" 2>&1)"
grep -q "^launch: fk run --render $FD --servers $FD/conf/servers.json\$" <<<"$out" && ok "another runtime: the launch line is its own" || no "fakert launch: $out"
out=$($FX packs check --target fk-render delta 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^ok   delta: 2 packs, rendered tree matches the manifest, nothing shadowed" <<<"$out" && ok "another runtime: check passes on its render" || no "fakert check (rc=$rc): $out"
echo '{}' > "$FD/rules.json"; $FX packs check --target fk-render delta 2>&1 | grep -q "differs from the manifest: rules.json" && ok "another runtime: a tampered settings file is reported by the name its definition gives" || no "fakert tamper"
mkdir -p "$HOME/.fk/skills/s-all"; $FX packs check --target fk-render delta 2>&1 | grep -q "shadowing: skill s-all is also in ~/.fk/skills" && ok "another runtime: shadowing is looked for in its own user skills directory" || no "fakert shadow"
rmdir "$HOME/.fk/skills/s-all" "$HOME/.fk/skills" "$HOME/.fk"
$FX packs apply --target claude-code delta >/dev/null 2>&1; [ $? != 0 ] && ok "another runtime: its project is not rendered under the target of another" || no "fakert wrong target"

# a runtime with no usable mcp resource gets its skills only; its tool packs are said to be skipped, and a check does not call them missing
jq '.models = {provider: "nomcp"}' "$T/c/projects/delta.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/delta.json"
out=$(fapply); ntok=$(tok_of <<<"$out")
[ -n "$ntok" ] && grep -q "^  skipped tool issues: provider nomcp has no usable mcp resource in its definition, so it cannot be given MCP servers\$" <<<"$out" && ! grep -q "tool entry" <<<"$out" && ok "a runtime with no mcp resource: the plan skips the tool packs and says why" || no "nomcp plan: $out"
out=$(fapply --plan "$ntok" --approved test 2>&1)
[ -f "$T/s/render/delta/nomcp/.fk/skills/s-all/SKILL.md" ] && [ ! -e "$T/s/render/delta/nomcp/conf" ] && [ ! -e "$T/s/render/delta/nomcp/rules.json" ] && ok "a runtime with no mcp resource: only the skills are rendered" || no "nomcp apply: $out"
out=$($FX packs check --target fk-render delta 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^note: skipped tool issues: provider nomcp has no usable mcp resource" <<<"$out" && ok "a runtime with no mcp resource: check passes and notes the skip" || no "nomcp check (rc=$rc): $out"
# --- an extension the project enabled is part of the definition the render reads: a runtime like nomcp that also claims no mcp, given an mcp
# resource and a label by an extension pack of the library, renders the tool pack; without the extension it still skips it. The extension is a
# library pack, imported through its plan; the render reads the composed definition (provider compose), not the runtime's own file.
mkfake bare 'del(.resources.mcp) | del(.renderers) | del(.capabilities.mcp) | .resources.settings.allow_pointer = null'
EXT=$T/ext/mcpext; mkdir -p "$EXT"
jq -n '{schema:2,kind:"extension",extension:"mcpext",description:"gives bare an mcp resource",extends:"bare",provides:["mcp"],
  adds:{capabilities:{mcp:{value:"yes",note:"servers file"}},
        resources:{mcp:{file:"conf/servers.json",format:"json",root_pointer:"/servers/remote",entry:{transport:"http",address:"{url}",label:"{name}"},permission_rule:null}},
        renderers:{packs:{label:"ExtRT"}}}}' > "$EXT/definition.json"
etok=$($FX provider import "$EXT" | tok_of); $FX provider import "$EXT" --plan "$etok" --approved test >/dev/null 2>&1 || no "could not import the extension pack"
jq '.models = {provider: "bare"}' "$T/c/projects/delta.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/delta.json"
out=$(fapply); grep -q "^  skipped tool issues: provider bare has no usable mcp resource" <<<"$out" && ok "an extension not enabled by the project changes nothing: the tool pack is still skipped" || no "extension not enabled: $out"
jq '.models.extensions = ["mcpext"]' "$T/c/projects/delta.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/delta.json"
out=$(fapply); xtok=$(tok_of <<<"$out")
{ [ -n "$xtok" ] && grep -q "^  tool entry: issues  (see conf/servers.json)$" <<<"$out" && ! grep -q "skipped tool issues" <<<"$out" && grep -q "role scoping is advisory: ExtRT cannot enforce" <<<"$out"; } \
  && ok "an extension the project enabled: the plan has the tool entry its mcp resource gives, and its label" || no "extension plan: $out"
out=$(fapply --plan "$xtok" --approved test 2>&1)
jq -e '.servers.remote.issues == {transport:"http",address:"https://mcp.example.net/",label:"issues"}' "$T/s/render/delta/bare/conf/servers.json" >/dev/null 2>&1 && ok "and the render has the server entry built from the extension's template" || no "extension apply: $out; $(find "$T/s/render/delta/bare" | head)"
out=$($FX packs check --target fk-render delta 2>&1); rc=$?
[ "$rc" = 0 ] && ok "and check reads the same composed definition and passes" || no "extension check (rc=$rc): $out"
jq '.models = {provider: "nomcp"}' "$T/c/projects/delta.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/delta.json"
# --- the render directory of an earlier version (<state>/claude) is not handled any more: no migrate-render verb, and a leftover directory
# there is neither read nor changed by apply and check. The render of the runtime (<state>/render/PROJECT/RUNTIME) applies and checks as before.
case $QARGI_STATE in "$T"/*) ok "the tests run in the test's own state directory, never the real one";; *) no "state is not temporary: $QARGI_STATE"; exit 1;; esac
cd "$T" || exit 1; DA=$ROOT/bin/qargi
out=$("$DA" packs migrate-render 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'usage: packs.sh packs' <<<"$out" && ! grep -q 'migrate-render' <<<"${out#*usage}" && ! grep -q 'plan token' <<<"$out"; } && ok "packs migrate-render is an unknown verb: it fails with the usage, which does not name it" || no "migrate-render (rc=$rc): $out"
{ "$DA" packs --help; "$DA" help guard; } 2>&1 | grep -q 'migrate-render' && no "migrate-render is still in the packs help or the guard topic" || ok "the packs help and the guard topic do not name migrate-render"
mkdir -p "$T/s/claude/old1/.claude/skills"; echo x > "$T/s/claude/old1/MANIFEST.json"
proj fin1; "$DA" skill link s-all --scope project --project fin1 >/dev/null; D=$T/s/render/fin1/claude-code
legacy_sig=$(find "$T/s/claude" -printf '%p %y\n' | sort)
out=$(cd "$T" && "$FX" packs apply --target claude-code fin1 2>&1); atok=$(tok_of <<<"$out")
[ -n "$atok" ] && ! grep -q 'claude/old1' <<<"$out" && ok "a render still plans with a leftover state/claude directory beside it, which the plan does not name" || no "plan with a leftover: $out"
out=$("$FX" packs apply --target claude-code fin1 --plan "$atok" --approved test 2>&1); arc=$?
[ "$arc" = 0 ] && [ -f "$D/MANIFEST.json" ] && [ -f "$D/.claude/skills/s-all/SKILL.md" ] && ok "and the render applies into state/render/PROJECT/RUNTIME" || no "apply (rc=$arc): $out"
out=$("$FX" packs check --target claude-code fin1 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^ok   fin1: " <<<"$out" && ok "packs check --target claude-code still passes on that render" || no "check (rc=$rc): $out"
[ "$legacy_sig" = "$(find "$T/s/claude" -printf '%p %y\n' | sort)" ] && ok "the leftover directory is untouched by apply and check" || no "the leftover directory changed"
exit $fail
