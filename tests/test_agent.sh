#!/usr/bin/env bash
# Members: qargi agent add | list | for | rename | remove, in a throwaway home. Run: tests/test_agent.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
mkdir -p "$HOME" "$T/c/projects"
# there is no default provider: the provider is a project's models.provider, and a member belongs to a project (no user-level members).
# pbase is the project most members below belong to and the one in effect (QARGI_PROJECT)
git init -q "$T/repop"
jq -n --arg p "$T/repop" '{schema:1,project:"pbase",repo:{url:"https://github.com/example/pbase",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/pbase.json"
export QARGI_PROJECT=pbase
A=$T/repop/.claude/agents
fm() { $DA agent for "$@" --json 2>/dev/null | jq -r .member; }   # the member name only
has_member() { jq -e --arg n "$1" '[(.projects // {})[] | keys[]] | index($n) != null' "$T/c/agents.json" >/dev/null; }

out=$($DA agent add forge --project pbase --roles build,test 2>&1) && [ -f "$A/forge.md" ] && ok "add renders the member definition" || no "add: $out"
# the file is what the runtime's renderers.agent data makes of the neutral definition (agents/member.json and member.body.md): the front matter
# is pinned here byte for byte, the body is the neutral body with the runtime's skills directory in it
{ cat <<'EOS'
---
name: forge
description: "A qargi member for one task at a time (roles: build, test). Works in its own clone and returns patches or a report. Dispatched only by /qargi-task or /qargi-team; never pushes."
model: claude-sonnet-5-5
effort: high
tools: Bash, Read, Edit, Write, Grep, Glob, Monitor, TaskStop, ToolSearch, Skill
hooks:
  PreToolUse:
    - matcher: "Bash|Monitor|Edit|Write|NotebookEdit|Read|Grep|mcp__.*"
      hooks:
        - type: command
          command: qargi __guard
          timeout: 20
          onFailure: block
---

EOS
sed 's|{skills_dir}|.claude/skills|' agents/member.body.md; } > "$T/forge.golden"
cmp -s "$T/forge.golden" "$A/forge.md" && ok "the member file is the golden text, byte for byte" || no "golden: $(diff "$T/forge.golden" "$A/forge.md" | head -5)"
# the canonical copy of the render lives in the configuration directory (agents/PROJECT/PATH, beside agents.json), outside every repository
C=$T/c/agents/pbase
cmp -s "$T/forge.golden" "$C/forge.md" && ok "the copy in config is the same text" || no "copy: $(ls -R "$T/c/agents" 2>&1)"
! grep -qi 'claude' agents/member.json agents/member.body.md && ok "the neutral definition names no runtime" || no "the neutral definition names a runtime"
# the same member as the adapter's template renders it (the form before renderers): equal once the optional quotes of a value are set aside
norm() { sed -E 's/^( *(- )?[A-Za-z]+: )"(.*)"$/\1\3/'; }
old=$(jq -nc '{member:"forge",abilities:["build","test"],class:"write",model:"claude-sonnet-5-5",effort:"high"}' | "$PWD/lib/providers/claude-code/adapter" dispatch-local | jq -j .definition.text)
cmp -s <(norm <<<"$old") <(norm < "$A/forge.md") && ok "and it says what the file of the earlier form said (only the quoting of values differs)" || no "old vs new: $(diff <(norm <<<"$old") <(norm < "$A/forge.md") | head -5)"
h=$(sha256sum < "$A/forge.md" | cut -d' ' -f1)
jq -e --arg h "$h" --arg f "$A/forge.md" '.projects.pbase.forge | .provider == "claude-code" and .surface == "local" and .file == $f and .render.path == "forge.md" and .render.hash == $h and (.render.inputs_hash | test("^[0-9a-f]{64}$"))' "$T/c/agents.json" >/dev/null \
  && ok "the record keeps the runtime, the surface, the path, the hash of the file and the hash of what it was made from" || no "record: $(jq -c .projects.pbase.forge "$T/c/agents.json")"
$DA agent list | grep -q "forge .*forge.md$" && ok "list shows no state for a current member" || no "list current: $($DA agent list | head -2)"
grep -q '^name: forge$' "$A/forge.md" && grep -q 'build, test' "$A/forge.md" && grep -q '^model: claude-sonnet-5-5$' "$A/forge.md" && grep -q '^effort: high$' "$A/forge.md" && ok "it carries the name, abilities and model" || no "rendered: $(head -5 "$A/forge.md")"
grep -q 'matcher: "Bash|Monitor|Edit|Write|NotebookEdit|Read|Grep|mcp__.\*"' "$A/forge.md" && grep -q 'command: qargi __guard$' "$A/forge.md" && ok "the guard covers Bash, Monitor, the edit tools and every MCP tool" || no "hook"
! grep -q 'mcp__[a-z]' "$A/forge.md" && ok "a member whose roles have no tool pack has no MCP tool" || no "an MCP tool with no tool pack: $(grep -n mcp__ "$A/forge.md")"
grep -q 'onFailure: block$' "$A/forge.md" && grep -q '^ *timeout: [0-9]' "$A/forge.md" && ok "the guard hook blocks when it fails or times out" || no "hook failure setting"
! grep -q '{{' "$A/forge.md" && ok "no placeholder is left" || no "placeholder left"
$DA agent add scribe --project pbase --roles write --model opus --effort medium >/dev/null 2>&1 && grep -q '^model: opus$' "$A/scribe.md" && ok "model is the one given" || no "model"
$DA agent add omni --project pbase >/dev/null 2>&1 && jq -e '.projects.pbase.omni.roles == ["build","write","review","test"]' "$T/c/agents.json" >/dev/null && ok "a member serves all four abilities by default" || no "default abilities"
for bad in Forge "two--dashes" "-x" general-purpose Explore statusline-setup review lead forge; do
  $DA agent add "$bad" --project pbase >/dev/null 2>&1 && no "the name '$bad' was accepted" || ok "the name '$bad' is refused"
done
$DA agent add other --project pbase --roles build,deploy >/dev/null 2>&1 && no "an unknown ability was accepted" || ok "an unknown ability is refused"
out=$($DA agent add old --project pbase --abilities build 2>&1); rc=$?
[ $rc != 0 ] && grep -q "unknown option --abilities" <<<"$out" && [ ! -e "$A/old.md" ] && ok "--abilities is gone: an unknown option" || no "--abilities still accepted: $out"
touch "$A/taken.md"; $DA agent add taken --project pbase >/dev/null 2>&1 && no "an existing file was replaced" || ok "a definition that exists is never replaced"

[ -z "$(fm build)$(fm test)$(fm write)" ] && ok "for: members named forge, scribe or omni serve nobody; only the bases (worker, reviewer) are dispatched" || no "for named members: $(fm build) $(fm write)"
$DA agent for review >/dev/null 2>&1 && no "a member that can write was returned for review: $($DA agent for review)" || ok "for: a member serving build and review (write class) never serves review"
$DA agent list | grep -q "^pbase  *scribe  *write  *opus/medium" && ok "list shows abilities, project, model and effort" || no "list: $($DA agent list)"
$DA agent add judge --project pbase --roles review >/dev/null 2>&1 && grep -q 'command: qargi __guard --class read-only$' "$A/judge.md" && ok "a member that only reviews is read-only by class in its hook" || no "review class"
! grep -q -- '--class' "$A/forge.md" && ! grep -q -- '--class' "$A/scribe.md" 2>/dev/null && ok "a member with other abilities names no class" || no "class on a writer"
$DA agent remove judge >/dev/null 2>&1

# a project's own member comes first inside its repository
git init -q "$T/repo"
jq -n --arg p "$T/repo" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high"}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/alpha.json"
$DA agent add smith --roles build --project alpha >/dev/null 2>&1 && [ -f "$T/repo/.claude/agents/smith.md" ] && ok "--project puts it in the repository" || no "project add"
grep -qx '/.claude/agents/smith.md' "$T/repo/.git/info/exclude" && [ -z "$(git -C "$T/repo" status --porcelain)" ] && ok "and hides it from git" || no "exclude"
$DA agent add worker --project alpha >/dev/null 2>&1
[ "$(cd "$T/repo" && QARGI_PROJECT='' fm build)" = worker ] && [ -z "$(fm build)" ] && [ "$(fm build --project alpha)" = worker ] && ok "for resolves the members of the project in effect, and of no other" || no "project for"
$DA agent remove worker --project alpha >/dev/null 2>&1

$DA agent rename forge anvil >/dev/null 2>&1 && [ -f "$A/anvil.md" ] && [ ! -e "$A/forge.md" ] && grep -q '^name: anvil$' "$A/anvil.md" && jq -e '.projects.pbase | has("anvil") and (has("forge") | not)' "$T/c/agents.json" >/dev/null && ok "rename moves the definition and the record" || no "rename"
{ [ -f "$C/anvil.md" ] && [ ! -e "$C/forge.md" ] && cmp -s "$C/anvil.md" "$A/anvil.md"; } && ok "and the copy in config" || no "rename copy: $(ls "$C")"
$DA agent rename anvil scribe >/dev/null 2>&1 && no "rename onto a member" || ok "rename refuses a name in use"
sed -i '/onFailure/d;/timeout: 20/d' "$A/anvil.md"; cp "$A/anvil.md" "$T/old.md"
$DA agent refresh anvil >/dev/null 2>&1 && grep -q 'onFailure: block$' "$A/anvil.md" && grep -q '^name: anvil$' "$A/anvil.md" && grep -q 'build, test' "$A/anvil.md" && jq -e '.projects.pbase.anvil.roles == ["build","test"]' "$T/c/agents.json" >/dev/null && ok "refresh re-renders from the current definition, keeping name and abilities" || no "refresh"
$DA agent refresh anvil 2>&1 | grep -q "is current" && ok "refresh of a current member says so" || no "refresh idempotent"
$DA agent refresh nobody >/dev/null 2>&1 && no "refresh of an unknown member" || ok "refresh refuses an unknown member"
$DA agent remove anvil >/dev/null 2>&1 && [ ! -e "$A/anvil.md" ] && [ ! -e "$C/anvil.md" ] && jq -e '.projects.pbase | has("anvil") | not' "$T/c/agents.json" >/dev/null && ok "remove deletes the definition, its copy in config and the record" || no "remove"
$DA agent remove omni >/dev/null 2>&1; $DA agent for review >/dev/null 2>&1 && no "for found a removed member" || ok "for fails, with a hint, when no member serves the ability"
$DA agent for review 2>&1 | grep -q "qargi agent add reviewer --project pbase" && ok "the hint names the command" || no "hint"

# DRIFT: the file was edited by hand; STALE: it is not what the definition renders today (or nothing is on record)
$DA agent add drifty --project pbase --roles build >/dev/null 2>&1; cp "$A/drifty.md" "$T/drifty.keep"
printf '\nA line added by hand.\n' >> "$A/drifty.md"
$DA agent list | grep -q "drifty .*drifty.md (DRIFT: qargi agent refresh drifty --project pbase)$" && ok "list: an edited file is DRIFT, with the fix" || no "list drift: $($DA agent list | grep drifty)"
$DA agent models --json | jq -e '.members[] | select(.name == "drifty") | .state == ["DRIFT"] and (.flags | any(startswith("DRIFT")))' >/dev/null && $DA agent models --json | jq -e '.warnings | any(.name == "drifty" and (.message | startswith("DRIFT")))' >/dev/null \
  && ok "models: the member has state DRIFT, a flag and a warning" || no "models drift: $($DA agent models --json | jq -c '.members[] | select(.name == "drifty")')"
$DA agent models | grep drifty | grep -q 'DRIFT' && ok "and the text view shows it" || no "models text drift"
out=$($DA agent refresh drifty 2>&1); grep -q 'edits made to the file by hand are gone' <<<"$out" && cmp -s "$A/drifty.md" "$T/drifty.keep" && ok "refresh replaces an edited file and says so" || no "refresh drift: $out"
$DA agent list | grep drifty | grep -qw 'DRIFT\|STALE' && no "still flagged after refresh" || ok "and the flag is gone"
jq 'del(.projects.pbase.drifty.render) | del(.projects.pbase.drifty.provider)' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
$DA agent list | grep -q "drifty .*drifty.md (STALE: qargi agent refresh drifty --project pbase)$" && ok "list: a member with no render on record (made before) is STALE, with the fix" || no "list stale: $($DA agent list | grep drifty)"
$DA agent models --json | jq -e '.members[] | select(.name == "drifty") | .state == ["STALE"] and (.flags | any(startswith("STALE") and contains("agent refresh drifty")))' >/dev/null && ok "models: STALE with the fix in the flag" || no "models stale"
out=$($DA agent refresh drifty 2>&1); grep -q 'is current' <<<"$out" && jq -e '.projects.pbase.drifty.render.hash != null and .projects.pbase.drifty.provider == "claude-code"' "$T/c/agents.json" >/dev/null && ! $DA agent list | grep drifty | grep -qw 'STALE' && ok "refresh of an identical file only records the render" || no "refresh stale: $out"
jq '.projects.pbase.drifty.render.inputs_hash = "0000000000000000000000000000000000000000000000000000000000000000"' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
$DA agent list | grep -q "drifty .*(STALE: qargi agent refresh drifty --project pbase)$" && ok "an inputs hash that is not today's is STALE" || no "stale hash"
$DA agent refresh drifty >/dev/null 2>&1
# MISSING: the runtime's file is gone (a cleaned checkout, a fresh clone); the copy in config is what refresh writes it from
cmp -s "$C/drifty.md" "$A/drifty.md" && ok "the copy in config is the render, byte for byte" || no "copy: $(ls -R "$T/c/agents" 2>&1)"
rm -rf "$A" "$T/repop/.git/info/exclude"   # a cleaned checkout: no agents directory, no exclude file
$DA agent list | grep -q "drifty .*drifty.md (MISSING: qargi agent refresh drifty --project pbase)$" && ok "list: a file that is gone is MISSING, with the fix" || no "list missing: $($DA agent list | grep drifty)"
$DA agent models --json | jq -e '.members[] | select(.name == "drifty") | .state == ["MISSING"] and (.flags | any(startswith("MISSING") and contains("agent refresh drifty --project pbase")))' >/dev/null && ok "models: MISSING with the fix in the flag" || no "models missing: $($DA agent models --json | jq -c '.members[] | select(.name == "drifty")')"
out=$($DA agent refresh drifty 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'refreshed member drifty' <<<"$out" && cmp -s "$C/drifty.md" "$A/drifty.md"; } && ok "refresh writes the file again, the same bytes as the copy" || no "refresh missing: rc=$rc $out"
grep -qx '/.claude/agents/drifty.md' "$T/repop/.git/info/exclude" && [ -z "$(git -C "$T/repop" status --porcelain)" ] && ok "and hides it from git again" || no "refresh exclude: $(cat "$T/repop/.git/info/exclude" 2>&1)"
$DA agent list | grep drifty | grep -q '(' && no "still flagged after the file came back: $($DA agent list | grep drifty)" || ok "and the member is current"
$DA agent refresh scribe >/dev/null 2>&1
# the copy in config is qargi's render: gone or edited, the member is STALE and refresh writes it again
rm -f "$C/drifty.md"
$DA agent list | grep -q "drifty .*drifty.md (STALE: qargi agent refresh drifty --project pbase)$" && ok "list: a copy gone from config is STALE, with the fix" || no "list no copy: $($DA agent list | grep drifty)"
out=$($DA agent refresh drifty 2>&1); { grep -q 'is current' <<<"$out" && cmp -s "$C/drifty.md" "$A/drifty.md"; } && ok "refresh of a current file writes the copy again and says the member is current" || no "refresh copy: $out"
echo "edited" >> "$C/drifty.md"
$DA agent list | grep -q "drifty .*(STALE: " && ok "a copy edited by hand is STALE" || no "edited copy: $($DA agent list | grep drifty)"
$DA agent refresh drifty >/dev/null 2>&1; cmp -s "$C/drifty.md" "$A/drifty.md" && ! $DA agent list | grep drifty | grep -q '(' && ok "and refresh replaces it" || no "refresh edited copy: $($DA agent list | grep drifty)"
$DA agent remove drifty >/dev/null 2>&1

# a second runtime, defined by data alone in the pack library: the same neutral member, rendered as TOML by its own renderers.agent
LIB=$T/c/packs/providers/faketoml; mkdir -p "$LIB"
jq -n '{schema:2, kind:"provider", provider:"faketoml", family:null, surface:"local",
  models:{pattern:"^fake-[a-z0-9.-]+$", tiers:{"*":{model:"fake-m", alias:null, verified_on:null, source:"test"}}, effort:{low:"l", medium:"m", high:"h", xhigh:null, max:null}},
  resources:{agents:{project_dir:".fake/agents", user_dir:"~/.fake/agents", items:"file-per-item", ext:".toml"}},
  agents:{reserved_names:["fake-builtin"]},
  renderers:{agent:{engine:"map", format:"toml", path:"{name}.toml", fields:[
    {from:"name", to:"name", refuse_if_missing:true}, {from:"description", to:"description"},
    {from:"model", to:"model", refuse_if_missing:true}, {from:"effort", to:"effort", resolve:"effort"},
    {from:"tools", to:"tools", tool_map:{shell:"sh", read:"cat", edit:"ed", write:"tee"}}, {from:"class", to:"mode"},
    {from:"body", to:"prompt"}]}},
  dispatch:{mode:"in-session"}, barrier:{kind:"none"}}' > "$LIB/definition.json"
python3 -I tests/handseal.py "$LIB"                             # a library pack counts only once sealed
git init -q "$T/repo-t"
jq -n --arg p "$T/repo-t" '{schema:1,project:"tomlp",repo:{url:"https://github.com/example/tomlp",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:"faketoml"},memory:{},budget_cents:500}' > "$T/c/projects/tomlp.json"
toml() { python3 -c 'import tomllib,sys,json; print(json.dumps(tomllib.load(open(sys.argv[1],"rb"))))' "$1" 2>&1; }
out=$($DA agent add tomler --roles build,test --project tomlp 2>&1); F=$T/repo-t/.fake/agents/tomler.toml
[ -f "$F" ] && ok "faketoml: the file is where its definition says (.fake/agents, .toml)" || no "faketoml add: $out"
tj=$(toml "$F")
jq -e '.name == "tomler" and .model == "fake-m" and .effort == "h" and .mode == "write" and .tools == ["sh","cat","ed","tee"] and (.description | startswith("A qargi member")) and (.prompt | startswith("You are a qargi member")) and (.prompt | contains("`skills` directory"))' <<<"$tj" >/dev/null \
  && ok "faketoml: it parses as TOML with the fields mapped (model from the tier, effort through its table, tools renamed, the body as the prompt)" || no "faketoml fields: $tj"
grep -q "optional tool 'search_text' has no native name" <<<"$out" && ok "faketoml: a tool it cannot name is dropped with a note" || no "tool note: $out"
grep -qx '/.fake/agents/tomler.toml' "$T/repo-t/.git/info/exclude" && [ -z "$(git -C "$T/repo-t" status --porcelain)" ] && ok "faketoml: hidden from git by the path its definition gives" || no "faketoml exclude"
jq -e '.projects.tomlp.tomler | .provider == "faketoml" and .render.path == "tomler.toml" and .file == "'"$F"'"' "$T/c/agents.json" >/dev/null && $DA agent list | grep -q "tomler .*tomler.toml$" && ok "faketoml: recorded, and current" || no "faketoml record"
out=$($DA agent add tomler2 --roles build --effort xhigh --project tomlp 2>&1); tj=$(toml "$T/repo-t/.fake/agents/tomler2.toml")
{ jq -e 'has("effort") | not' <<<"$tj" >/dev/null && grep -q "effort: omitted" <<<"$out"; } && ok "faketoml: an effort the runtime has no value for is left out, with a note" || no "xhigh: $out $tj"
printf '# hand\n' >> "$F"
$DA agent list | grep -q "tomler .*tomler.toml (DRIFT: qargi agent refresh tomler --project tomlp)$" && ok "faketoml: a hand edit is DRIFT" || no "faketoml drift: $($DA agent list | grep tomler)"
$DA agent refresh tomler --project tomlp >/dev/null 2>&1; $DA agent list | grep 'tomler ' | grep -qw 'DRIFT' && no "refresh kept DRIFT" || ok "faketoml: refresh clears it"
jq '.renderers.agent.fields += [{from:"abilities", to:"serves", transform:[{join:" "}]}]' "$LIB/definition.json" > "$T/d.json" && mv "$T/d.json" "$LIB/definition.json"
python3 -I tests/handseal.py "$LIB"                             # and the edit is sealed again: a changed definition, not a changed pack
$DA agent list | grep -q "tomler .*tomler.toml (STALE: qargi agent refresh tomler --project tomlp)$" && ok "faketoml: a changed definition makes the member STALE" || no "faketoml stale: $($DA agent list | grep tomler)"
$DA agent models --project tomlp --json | jq -e '[.members[] | select(.state == ["STALE"] and (.name | startswith("tomler")))] | length == 2' >/dev/null && ok "models: and so are the other members of that runtime" || no "models stale count"
$DA agent refresh tomler --project tomlp >/dev/null 2>&1; [ "$(toml "$F" | jq -r .serves)" = "build test" ] && ok "faketoml: refresh renders the new definition" || no "faketoml refresh: $(toml "$F")"
$DA agent list | grep 'tomler ' | grep -qw 'STALE' && no "tomler still STALE" || ok "and the member is current again"
$DA agent rename tomler smithy --project tomlp >/dev/null 2>&1; S=$T/repo-t/.fake/agents/smithy.toml
{ [ -f "$S" ] && [ ! -e "$F" ] && [ "$(toml "$S" | jq -r .name)" = smithy ]; } && ok "faketoml: rename renders the file again under the new name" || no "faketoml rename: $(ls "$T/repo-t/.fake/agents")"
grep -qx '/.fake/agents/smithy.toml' "$T/repo-t/.git/info/exclude" && [ -z "$(git -C "$T/repo-t" status --porcelain)" ] && ok "and hides the new file from git" || no "rename exclude"
$DA agent list | grep 'smithy ' | grep -q '(' && no "renamed member flagged: $($DA agent list | grep smithy)" || ok "and it is current under the new name"
# a read-only member needs a barrier on a runtime that has none (the project must accept it), as ever
$DA agent add toml-judge --roles review --project tomlp >/dev/null 2>&1; [ $? = 2 ] && ok "faketoml: a reviewing member is refused where the runtime has no barrier" || no "faketoml review"
# a runtime that claims read_only_barrier, attested, with barrier kind none and no read-only arguments has no barrier either: a reviewing member is refused
LIBC=$T/c/packs/providers/claimtoml; mkdir -p "$LIBC"
jq '.provider = "claimtoml" | .capabilities = {read_only_barrier: {value:"yes", verified_on:"2026-11-02", source:"test", note:"claim"}}' "$LIB/definition.json" > "$LIBC/definition.json"
python3 -I tests/handseal.py "$LIBC"
python3 -I - <<'PY'
import sys; sys.path.insert(0, "lib")
import provider as P
P.record_verification("claimtoml", {"read_only_barrier": {"hash": P.definition_hash("claimtoml"), "by": "attest", "at": "2026-11-02", "note": "test"}})
PY
git init -q "$T/repo-c"
jq -n --arg p "$T/repo-c" '{schema:1,project:"claimp",repo:{url:"https://github.com/example/claimp",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:"claimtoml"},memory:{},budget_cents:500}' > "$T/c/projects/claimp.json"
out=$($DA agent add claim-judge --roles review --project claimp 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'claimtoml' <<<"$out" && grep -q 'barrier.kind is none' <<<"$out" && [ ! -e "$T/repo-c/.fake/agents/claim-judge.toml" ]; } \
  && ok "a reviewing member is refused where the runtime only claims a barrier (attested, kind none): it names the claim, and nothing is made" || no "claimtoml review: rc=$rc $out"
out=$($DA agent add claim-builder --roles build --project claimp 2>&1); rc=$?
{ [ $rc = 0 ] && [ -f "$T/repo-c/.fake/agents/claim-builder.toml" ]; } && ok "and a building member of that runtime is not affected" || no "claimtoml build: rc=$rc $out"
# a library runtime with no renderer and no adapter cannot serve members
LIB2=$T/c/packs/providers/norender; mkdir -p "$LIB2"
jq '.provider = "norender" | del(.renderers)' "$LIB/definition.json" > "$LIB2/definition.json"
python3 -I tests/handseal.py "$LIB2"
jq '.models.provider = "norender"' "$T/c/projects/tomlp.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/tomlp.json"
out=$($DA agent add nope1 --roles build --project tomlp 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "norender" <<<"$out" && grep -q "renderers.agent" <<<"$out" && [ ! -e "$T/repo-t/.fake/agents/nope1.toml" ]; } && ok "a runtime with no member renderer is refused, naming it, and nothing is made" || no "norender: rc=$rc $out"
# the providers named in a refusal come from the loader: the library's too, and none of the schema files
LIB3=$T/c/packs/providers/badcat; mkdir -p "$LIB3"
jq '.provider = "badcat" | .models = {catalog: "nocat", use: "id"}' "$LIB/definition.json" > "$LIB3/definition.json"
python3 -I tests/handseal.py "$LIB3"
jq '.models.provider = "badcat"' "$T/c/projects/tomlp.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/tomlp.json"
out=$($DA agent add nope3 --roles build --project tomlp 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "no catalog 'nocat'" <<<"$out" && grep -q 'available: badcat, claimtoml, claude-code, claude-platform, codex, faketoml, norender$' <<<"$out"; } && ok "a definition that cannot be loaded is refused with the reason and the providers there are (the library's too, no schema file)" || no "available: rc=$rc $out"

# where a member's file goes: a member belongs to a project, and its file goes where the runtime links the project's agents; there are no user-level members
while read -r p m; do $DA agent remove "$m" --project "$p" >/dev/null 2>&1; done < <($DA agent list | awk '{print $1, $2}')
rm -rf "$A"
out=$($DA agent add bare 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q -- '--project NAME' <<<"$out" && ! grep -q -- '--user' <<<"$out" && [ ! -e "$A/bare.md" ] && ! has_member bare; } && ok "add without --project is refused (exit 2), says so, and writes nothing" || no "bare add: rc=$rc $out"
out=$(QARGI_PROJECT='' $DA agent add bare --roles build 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q -- '--project NAME' <<<"$out"; } && ok "and so it is with no project in effect either" || no "bare add, no project in effect: rc=$rc $out"
out=$($DA agent add lvl --roles build --user 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'unknown option --user' <<<"$out" && [ ! -e "$A/lvl.md" ] && ! has_member lvl; } && ok "--user is an unknown option of add and writes nothing" || no "add --user: rc=$rc $out"
$DA agent add lvl --roles build --project pbase >/dev/null 2>&1 && [ -f "$A/lvl.md" ] && jq -e '.projects.pbase.lvl | has("project") | not' "$T/c/agents.json" >/dev/null && ok "add --project writes the file and records it under the project" || no "add --project"
out=$($DA agent refresh lvl --user 2>&1); rc=$?; { [ $rc != 0 ] && grep -q 'unknown option --user' <<<"$out"; } && ok "--user is an unknown option of refresh" || no "refresh --user: rc=$rc $out"
out=$($DA agent rename lvl lvl2 --user 2>&1); rc=$?; { [ $rc != 0 ] && grep -q 'unknown option --user' <<<"$out" && [ -f "$A/lvl.md" ] && [ ! -e "$A/lvl2.md" ]; } && ok "--user is an unknown option of rename and moves nothing" || no "rename --user: rc=$rc $out"
$DA agent rename lvl lvl2 >/dev/null 2>&1 && [ -f "$A/lvl2.md" ] && [ ! -e "$A/lvl.md" ] && ok "rename works without any placement option" || no "rename"
$DA agent refresh lvl2 >/dev/null 2>&1 && ok "refresh works without any placement option" || no "refresh"
# a member belongs to the project that holds it: two projects can each have one of the same name
$DA agent remove lvl2 >/dev/null 2>&1
$DA agent add worker --project pbase >/dev/null 2>&1; $DA agent add worker --project alpha >/dev/null 2>&1
{ [ -f "$A/worker.md" ] && [ -f "$T/repo/.claude/agents/worker.md" ] && jq -e '.schema == 2 and (.projects | keys == ["alpha","pbase"]) and (.projects.alpha.worker.file | endswith("/repo/.claude/agents/worker.md")) and (.projects.pbase.worker.file | endswith("/repop/.claude/agents/worker.md"))' "$T/c/agents.json" >/dev/null; } && ok "two projects each add worker: two records, two files" || no "two workers: $(cat "$T/c/agents.json")"
out=$($DA agent list); { [ "$(grep -c ' worker ' <<<"$out")" = 2 ] && grep -q '^alpha  *worker ' <<<"$out" && grep -q '^pbase  *worker ' <<<"$out"; } && ok "list shows both, each with its project" || no "list both: $out"
out=$($DA agent list --project alpha); { grep -q '^alpha  *worker ' <<<"$out" && ! grep -qw pbase <<<"$out"; } && ok "list --project shows the members of that project only" || no "list --project: $out"
out=$($DA agent list --project nowhere); { grep -q 'no members' <<<"$out" && grep -q 'nowhere' <<<"$out"; } && ok "list --project of a project with none says so" || no "list --project none: $out"
[ "$(fm build --project alpha)" = worker ] && [ "$(fm build --project pbase)" = worker ] && ok "for resolves worker in each project" || no "for in two projects"
out=$($DA agent add worker --project alpha 2>&1); rc=$?; { [ $rc != 0 ] && grep -q 'exists already' <<<"$out"; } && ok "a name is unique within its project" || no "duplicate in a project: rc=$rc $out"
out=$(QARGI_PROJECT='' $DA agent remove worker 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'alpha' <<<"$out" && grep -q 'pbase' <<<"$out" && grep -q -- '--project' <<<"$out" && has_member worker && [ -f "$A/worker.md" ] && [ -f "$T/repo/.claude/agents/worker.md" ]; } && ok "remove NAME in two projects with none in effect: exit 2, names both, removes nothing" || no "ambiguous remove: rc=$rc $out"
out=$(QARGI_PROJECT='' $DA agent refresh worker 2>&1); rc=$?; { [ $rc = 2 ] && grep -q 'alpha' <<<"$out" && grep -q 'pbase' <<<"$out"; } && ok "so does refresh" || no "ambiguous refresh: rc=$rc $out"
out=$(QARGI_PROJECT='' $DA agent rename worker carrier 2>&1); rc=$?; { [ $rc = 2 ] && grep -q 'alpha' <<<"$out" && ! has_member carrier && [ -f "$A/worker.md" ]; } && ok "and rename" || no "ambiguous rename: rc=$rc $out"
out=$($DA agent rename worker carrier --project alpha 2>&1); rc=$?
{ [ $rc = 0 ] && jq -e '(.projects.alpha | keys == ["carrier"]) and (.projects.pbase | keys == ["worker"])' "$T/c/agents.json" >/dev/null && [ -f "$T/repo/.claude/agents/carrier.md" ] && [ ! -e "$T/repo/.claude/agents/worker.md" ] && [ -f "$A/worker.md" ]; } && ok "rename --project works inside that project and leaves the other alone" || no "rename --project: rc=$rc $out"
$DA agent rename carrier worker --project alpha >/dev/null 2>&1
out=$($DA agent remove worker --project nowhere 2>&1); rc=$?; { [ $rc != 0 ] && grep -q 'nowhere' <<<"$out" && has_member worker; } && ok "remove --project of a project without the member is refused" || no "remove wrong project: rc=$rc $out"
out=$(QARGI_PROJECT='' $DA agent remove worker --project alpha 2>&1); rc=$?
{ [ $rc = 0 ] && [ ! -e "$T/repo/.claude/agents/worker.md" ] && [ -f "$A/worker.md" ] && jq -e '(.projects.pbase | keys == ["worker"]) and (.projects.alpha // {} | length == 0)' "$T/c/agents.json" >/dev/null; } && ok "remove --project removes that project's member only" || no "remove --project: rc=$rc $out"
[ "$(fm build --project pbase)" = worker ] && [ -z "$(fm build --project alpha)" ] && ok "and the other project still resolves its own" || no "for after remove"
# inside a project that lacks NAME, a verb with no --project must not fall through to the one project that has it
cp "$A/worker.md" "$T/worker.keep"; cp "$T/c/agents.json" "$T/agents.m3"
for v in "rename worker carrier" "refresh worker" "remove worker"; do
  out=$(QARGI_PROJECT=alpha $DA agent $v 2>&1); rc=$?
  { [ $rc = 2 ] && grep -q 'alpha' <<<"$out" && grep -q -- '--project' <<<"$out" && cmp -s "$A/worker.md" "$T/worker.keep" && cmp -s "$T/c/agents.json" "$T/agents.m3"; } \
    && ok "$v inside a project without worker: exit 2, asks for --project, touches nothing" || no "foreign $v: rc=$rc $out"
done
out=$(QARGI_PROJECT=alpha $DA agent refresh worker --project pbase 2>&1); rc=$?; [ $rc = 0 ] && ok "and naming the other project with --project still works" || no "explicit other project: rc=$rc $out"
out=$(QARGI_PROJECT='' $DA agent remove worker 2>&1); rc=$?; { [ $rc = 0 ] && [ ! -e "$A/worker.md" ] && ! has_member worker; } && ok "a name held by one project needs no --project" || no "unique remove: rc=$rc $out"
# a project is the key: a member with no project cannot exist, and the old flat file is refused, never converted
cp "$T/c/agents.json" "$T/agents.keep"
for body in '{"forge":{"abilities":["build"],"file":"/x/forge.md","model":"opus","effort":null,"project":"pbase","seq":1}}' '{"schema":1,"projects":{}}' '{"schema":2,"projects":{},"forge":{}}' '{"schema":2,"projects":[]}' '[]' 'not json'; do
  printf '%s\n' "$body" > "$T/c/agents.json"; bad=''
  for v in "list" "models" "for build" "add x --project pbase" "remove forge" "refresh forge" "rename forge anvil"; do
    out=$($DA agent $v 2>&1); rc=$?
    { [ $rc = 2 ] && [ "$(wc -l <<<"$out")" = 1 ] && grep -q 'agents.json is not in the current shape' <<<"$out" && grep -q 'qargi agent add NAME --project P' <<<"$out"; } || bad="$bad [$v rc=$rc $out]"
  done
  [ "$(cat "$T/c/agents.json")" = "$body" ] || bad="$bad [rewritten]"
  [ -z "$bad" ] && ok "a file of another shape is refused by every verb (exit 2, one line) and left as it is: ${body:0:40}" || no "shape ${body:0:40}:$bad"
done
echo '{}' > "$T/c/agents.json"
out=$($DA agent list 2>&1); { grep -q 'no members yet' <<<"$out" && [ "$(cat "$T/c/agents.json")" = '{}' ]; } && ok "an empty object reads as no members" || no "empty object: $out"
$DA agent add fresh --roles build --project pbase >/dev/null 2>&1 && jq -e '.schema == 2 and (.projects.pbase | keys == ["fresh"])' "$T/c/agents.json" >/dev/null && ok "and the first add writes the current shape" || no "add to {}: $(cat "$T/c/agents.json")"
$DA agent remove fresh >/dev/null 2>&1; jq -e '.projects == {}' "$T/c/agents.json" >/dev/null && ok "the last member of a project leaves no empty project" || no "empty project left: $(cat "$T/c/agents.json")"
# the right shape with a record that lacks a field the verbs need is refused too, naming the member: it must not become a read-only worker on refresh,
# hide the members in list, or be written to a file called "null"
for spec in 'roles|{"file":"/x/forge.md","model":"opus","effort":null,"seq":1}' 'roles|{"roles":[],"file":"/x/forge.md","seq":1}' 'roles|{"roles":"build","file":"/x/forge.md","seq":1}' \
    'roles|{"roles":[1],"file":"/x/forge.md","seq":1}' 'file|{"roles":["build"],"model":"opus","seq":1}' 'file|{"roles":["build"],"file":"","seq":1}' 'file|{"roles":["build"],"file":7,"seq":1}'; do
  field=${spec%%|*}; rec=${spec#*|}
  body=$(jq -nc --argjson r "$rec" '{schema:2,projects:{pbase:{forge:$r}}}'); printf '%s\n' "$body" > "$T/c/agents.json"; bad=''
  for v in "list" "models" "for build" "add x --project pbase" "remove forge" "refresh forge" "rename forge anvil"; do
    out=$($DA agent $v 2>&1); rc=$?
    { [ $rc = 2 ] && [ "$(wc -l <<<"$out")" = 1 ] && grep -q 'forge' <<<"$out" && grep -q 'pbase' <<<"$out" && grep -q "no $field" <<<"$out" && grep -q 'qargi agent add NAME --project P' <<<"$out"; } || bad="$bad [$v rc=$rc $out]"
  done
  [ "$(cat "$T/c/agents.json")" = "$body" ] || bad="$bad [rewritten]"
  [ -z "$bad" ] && ok "a record with a bad $field is refused by every verb (exit 2, one line, names the member): ${rec:0:50}" || no "record ${rec:0:50}:$bad"
done
cp "$T/agents.keep" "$T/c/agents.json"
# the members of a project go to the runtime's member render when its definition links the project's agents (entry-symlinks here)
LIB4=$T/c/packs/providers/fakelink; mkdir -p "$LIB4"
jq '.provider = "fakelink" | .resources.agents.link = {project: "entry-symlinks", user: "none"}' "$LIB/definition.json" > "$LIB4/definition.json"
python3 -I tests/handseal.py "$LIB4"
git init -q "$T/repo-l"
jq -n --arg p "$T/repo-l" '{schema:1,project:"linkp",repo:{url:"https://github.com/example/linkp",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:"fakelink"},memory:{},budget_cents:500}' > "$T/c/projects/linkp.json"
MD=$T/s/render/linkp/fakelink.agents
out=$($DA agent add lk --roles build --project linkp 2>&1)
{ [ -f "$MD/lk.toml" ] && [ ! -e "$T/repo-l/.fake" ] && [ ! -e "$HOME/.fake" ] && [ ! -e "$A/lk.md" ]; } && ok "linked runtime: a project's member is rendered into the member render (not the checkout, not the user's directory)" || no "linked add: $out"
grep -q "qargi project link linkp --resource agents" <<<"$out" && ok "linked runtime: add says how the checkout gets it" || no "link note: $out"
jq -e --arg f "$MD/lk.toml" '.projects.linkp.lk | .file == $f and has("project") == false and .render.path == "lk.toml"' "$T/c/agents.json" >/dev/null && $DA agent list | grep -q "^linkp  *lk " && ok "linked runtime: recorded at the render, current" || no "linked record"
cmp -s "$T/c/agents/linkp/lk.toml" "$MD/lk.toml" && ok "linked runtime: the copy in config is kept as well" || no "linked copy: $(ls -R "$T/c/agents")"
[ -z "$(git -C "$T/repo-l" status --porcelain)" ] && ! grep -qsw fake "$T/repo-l/.git/info/exclude" && ok "linked runtime: the repository's exclude file is not touched (project link prints the hint)" || no "exclude touched"
mkdir -p "$T/repo-l/.fake/agents"; ln -s "$MD/lk.toml" "$T/repo-l/.fake/agents/lk.toml"
out=$($DA agent refresh lk --project linkp 2>&1); grep -q "is current" <<<"$out" && ! grep -q "does not see" <<<"$out" && ok "linked runtime: no note once the checkout has the link" || no "link note when linked: $out"
$DA agent rename lk lk2 --project linkp >/dev/null 2>&1; [ -f "$MD/lk2.toml" ] && [ ! -e "$MD/lk.toml" ] && jq -e '.projects.linkp.lk2.file == "'"$MD"'/lk2.toml"' "$T/c/agents.json" >/dev/null && ok "linked runtime: rename keeps the member in the render" || no "linked rename: $(ls "$MD")"
mkdir -p "$T/repo-l/.fake/agents"; rm -f "$T/repo-l/.fake/agents/lk.toml"
$DA agent add old1 --roles build --project linkp >/dev/null 2>&1
out=$($DA agent remove old1 --project linkp 2>&1); grep -q "project link linkp --resource agents" <<<"$out" && [ ! -e "$MD/old1.toml" ] && ok "remove deletes the render's file and says to run project link" || no "remove: $out"
$DA agent remove lk2 --project linkp >/dev/null 2>&1
[ ! -e "$T/c/agents/linkp" ] && ok "the last member of a project leaves no copies directory" || no "copies dir left: $(ls -A "$T/c/agents/linkp")"

# a base name takes only the abilities of its class
$DA agent add worker --project pbase --roles review >/dev/null 2>&1 && no "worker accepted review" || ok "add worker refuses an ability of the read-only class"
$DA agent add worker --project pbase --roles build,review >/dev/null 2>&1 && no "worker accepted build,review" || ok "add worker refuses a mixed list"
$DA agent add reviewer --project pbase --roles build >/dev/null 2>&1 && no "reviewer accepted build" || ok "add reviewer refuses an ability of the write class"
$DA agent add reviewer --project pbase --roles review,test >/dev/null 2>&1 && no "reviewer accepted review,test" || ok "add reviewer refuses a mixed list"
$DA agent add worker --project pbase --roles tw >/dev/null 2>&1; [ ! -e "$A/worker.md" ] && ok "a refused base leaves no definition" || no "worker.md written"
e=$($DA agent add reviewer --project pbase --roles write 2>&1); grep -q 'reviewer' <<<"$e" && grep -q 'read-only' <<<"$e" && ok "and says which class the base has" || no "base message: $e"
mkdir -p "$T/c/roles/tw"; jq -n '{class:"write"}' > "$T/c/roles/tw/role.json"; echo "the tw role" > "$T/c/roles/tw/ROLE.md"
$DA agent add worker --project pbase --roles tw,test >/dev/null 2>&1 && jq -e '.projects.pbase.worker.roles == ["tw","test"]' "$T/c/agents.json" >/dev/null && ok "a custom write role fits the worker" || no "worker tw"
$DA agent remove worker >/dev/null 2>&1
$DA agent add worker --project pbase >/dev/null 2>&1 && jq -e '.projects.pbase.worker.roles == ["build","write","test"]' "$T/c/agents.json" >/dev/null && ok "add worker with no list serves the base's abilities" || no "worker default"
$DA agent add reviewer --project pbase >/dev/null 2>&1 && jq -e '.projects.pbase.reviewer.roles == ["review"]' "$T/c/agents.json" >/dev/null && grep -q -- '--class read-only' "$A/reviewer.md" && ok "add reviewer with no list serves review, read-only by class" || no "reviewer default"
$DA agent remove worker >/dev/null 2>&1; $DA agent remove reviewer >/dev/null 2>&1

# profiles: only the base members resolve (worker for the write class, reviewer for the read-only one); a member of another name serves nobody
while read -r p m; do $DA agent remove "$m" --project "$p" >/dev/null 2>&1; done < <($DA agent list | awk '{print $1, $2}')
for pair in "tw:write" "ro:read-only"; do
  r=${pair%%:*}; c=${pair##*:}; mkdir -p "$T/c/roles/$r"
  jq -n --arg c "$c" '{class:$c}' > "$T/c/roles/$r/role.json"; echo "the $r role" > "$T/c/roles/$r/ROLE.md"
done
$DA agent add builder --project pbase --roles build,test >/dev/null 2>&1
out=$($DA agent for build 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q 'qargi agent add worker --project pbase' <<<"$out"; } && ok "for: a member of another name serves nobody, and the hint names the base to add" || no "builder served: rc=$rc $out"
$DA agent add worker --project pbase --roles build,write,test >/dev/null 2>&1
[ "$($DA agent for build)" = "worker sonnet high build" ] && [ "$($DA agent for test)" = "worker sonnet low test" ] && [ "$($DA agent for write)" = "worker sonnet medium write" ] && ok "for: one line, MEMBER MODEL EFFORT PROFILE, from the base member" || no "worker: $($DA agent for build)"
jq -e . <<<"$($DA agent for build --json)" >/dev/null && $DA agent for build --json | jq -e '.member == "worker" and (has("legacy") | not) and (has("member_scope") | not) and .role == "build" and .class == "write" and .profile == "build" and .profile_source == "shipped" and .base == "worker"
  and .tier == "balanced" and .model == "sonnet" and .model_id == "claude-sonnet-5-5" and .effort == "high" and .opt_in == false and (.purpose | length > 0)' >/dev/null && ok "for --json: the whole answer" || no "json: $($DA agent for build --json)"
$DA agent for tw --json | jq -e '.member == "worker" and .profile == "build" and .profile_source == "class-fallback" and .class == "write"' >/dev/null && ok "a custom write role with no profile uses the build row" || no "custom write: $($DA agent for tw --json 2>&1)"
$DA agent for ro >/dev/null 2>&1 && no "a read-only role resolved with no read-only member" || ok "a read-only role never resolves to a write member"
$DA agent add judge --project pbase --roles review >/dev/null 2>&1
$DA agent for review >/dev/null 2>&1 && no "a read-only member named judge served review: $($DA agent for review)" || ok "review: a read-only member that is not named reviewer serves nobody"
$DA agent for ro >/dev/null 2>&1 && no "a custom read-only role was served by judge" || ok "and neither does it serve a custom read-only role"
$DA agent add mix --project pbase --roles build,review >/dev/null 2>&1
$DA agent remove judge >/dev/null 2>&1
$DA agent for review >/dev/null 2>&1 && no "mixed member returned for review: $($DA agent for review)" || ok "a mixed member is write class and never serves review"
$DA agent for build --json | jq -e '.member == "worker"' >/dev/null && ok "a mixed member still serves its write abilities" || no "mix build"
$DA agent add reviewer --project pbase --roles review >/dev/null 2>&1
[ "$($DA agent for ro)" = "reviewer opus high review" ] && $DA agent for ro --json | jq -e '.profile_source == "class-fallback" and .profile == "review"' >/dev/null && ok "a custom read-only role uses the review row" || no "custom ro"
[ "$($DA agent for review)" = "reviewer opus high review" ] && [ "$($DA agent for review --profile auditor)" = "reviewer haiku low auditor" ] && ok "for --profile auditor: the reviewer at haiku low" || no "auditor: $($DA agent for review --profile auditor)"
[ "$($DA agent for review --profile advisor)" = "reviewer opus high advisor" ] && $DA agent for review --profile researcher --json | jq -e '.model == "fable" and .opt_in == true and .effort == "high"' >/dev/null && ok "advisor and researcher" || no "advisor/researcher"
$DA agent for ro --profile auditor | grep -q '^reviewer haiku low auditor$' && ok "a custom read-only role can take a read-only profile" || no "ro auditor"
for args in "review --profile build" "build --profile review" "build --profile auditor" "tw --profile review" "ro --profile build" "build --profile lead"; do
  e=$($DA agent for $args 2>&1 >/dev/null); rc=$?
  { [ $rc = 2 ] && [ -n "$e" ]; } && ok "for $args: refused (exit 2) with a reason" || no "for $args: rc=$rc $e"
done
$DA agent for build --profile nosuch >/dev/null 2>&1 && no "an unknown profile was accepted" || ok "an unknown profile is an error"
$DA agent for build --profile 'Bad Name' >/dev/null 2>&1 && no "a bad profile name was accepted" || ok "a bad profile name is an error"
# a member named like the base but of the wrong class is not the base member
jq '.projects.pbase.reviewer.roles = ["build","review"]' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
$DA agent for review >/dev/null 2>&1 && no "a mixed reviewer served review" || ok "a member named reviewer that can write is not used for review"
jq '.projects.pbase.reviewer.roles = ["review"]' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"

# a project's profiles
jq -n --arg p "$T/repo" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-haiku-5-5",effort:"low"}},
  profiles:{wrong:{base:"worker",abilities:["review"]}, nobase:{base:"nosuch"}, pm:{base:"worker",model:"claude-opus-5-5"},
    odd:{base:"worker",model:"claude-odd-9"}, scout:{base:"reviewer",tier:"fast",effort:"medium",purpose:"looks around"},
    auditor:{effort:"high"}, junk:7, bad:{base:[],tier:3}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/alpha.json"
# the members of alpha: `agent for` resolves the members of the project asked for, and of no other
for m in smith worker reviewer mix; do $DA agent remove "$m" >/dev/null 2>&1; done; $DA agent add worker --project alpha >/dev/null 2>&1; $DA agent add reviewer --project alpha >/dev/null 2>&1
e=$($DA agent for build --profile wrong --project alpha 2>&1); rc=$?
{ [ $rc = 2 ] && grep -qi 'abilit' <<<"$e"; } && ok "a project profile whose abilities differ in class from its base is refused at dispatch" || no "wrong abilities: rc=$rc $e"
$DA agent for review --profile wrong --project alpha >/dev/null 2>&1; [ $? = 2 ] && ok "whatever the role" || no "wrong, review"
e=$($DA agent for build --profile nobase --project alpha 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'nosuch' <<<"$e"; } && ok "a project profile with an unknown base is refused" || no "nobase: rc=$rc $e"
[ "$($DA agent for build --profile pm --project alpha)" = "worker opus medium pm" ] && $DA agent for build --profile pm --project alpha --json | jq -e '.model == "opus" and .model_id == "claude-opus-5-5" and .profile_source == "project"' >/dev/null && ok "a full model id in a project profile maps to its alias" || no "pm: $($DA agent for build --profile pm --project alpha 2>&1)"
out=$($DA agent for build --profile odd --project alpha 2>$T/err); [ "$out" = "worker - medium odd" ] && grep -q "claude-odd-9" "$T/err" && grep -qi 'definition' "$T/err" && ok "a model id with no alias prints - and warns that the member's definition applies" || no "odd: $out / $(cat "$T/err")"
$DA agent for build --profile odd --project alpha --json 2>/dev/null | jq -e '.model == null and .model_id == "claude-odd-9"' >/dev/null && ok "--json: model null, the id kept" || no "odd json"
[ "$($DA agent for review --profile scout --project alpha)" = "reviewer haiku medium scout" ] && ok "a project-only profile" || no "scout"
[ "$($DA agent for review --profile auditor --project alpha)" = "reviewer haiku high auditor" ] && ok "a project entry merges over the shipped profile of its name" || no "auditor merge: $($DA agent for review --profile auditor --project alpha)"
[ "$($DA agent for build --project alpha)" = "worker haiku low build" ] && ok "a role answer still sets the profile named after the role" || no "legacy roles: $($DA agent for build --project alpha)"
[ "$($DA agent for test --project alpha)" = "worker sonnet low test" ] && ok "and only that one" || no "test unaffected"
$DA agent for build --profile junk --project alpha >/dev/null 2>&1 && no "a malformed entry was usable" || ok "a malformed entry is ignored, not a crash"
jq '.profiles = 5' "$T/c/projects/alpha.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/alpha.json"
[ "$($DA agent for build --project alpha)" = "worker haiku low build" ] && ok "profiles of the wrong type are ignored" || no "profiles=5"

# --- extensions the project enabled: the decisions about the members and the member renderer read the runtime as composed with them
while read -r p m; do $DA agent remove "$m" --project "$p" >/dev/null 2>&1; done < <($DA agent list | awk '{print $1, $2}')
imp() { local t; t=$($DA provider import "$1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA provider import "$1" --plan "$t" --approved test >/dev/null 2>&1; }
# locov: a runtime that cannot set the model per dispatch; ovl, an extension, provides the capability and counts once it is verified for locov
LIBV=$T/c/packs/providers/locov; mkdir -p "$LIBV"
jq '.provider = "locov" | .models.tiers = {fast: {model: "fake-s", alias: null, verified_on: null, source: "test"}, "*": {model: "fake-m", alias: null, verified_on: null, source: "test"}}' "$LIB/definition.json" > "$LIBV/definition.json"
python3 -I tests/handseal.py "$LIBV"
OVL=$T/ext/ovl; mkdir -p "$OVL"
jq -n '{schema:2,kind:"extension",extension:"ovl",description:"per-dispatch model override of locov",extends:"locov",provides:["per_dispatch_model_override"],
  adds:{capabilities:{per_dispatch_model_override:{value:"yes",note:"n"}}}}' > "$OVL/definition.json"
imp "$OVL" || no "could not import ovl"
git init -q "$T/repo-v"
jq -n --arg p "$T/repo-v" '{schema:1,project:"locp",repo:{url:"https://github.com/example/locp",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},
  profiles:{quick:{base:"worker",tier:"fast"}},models:{provider:"locov",extensions:["ovl"]},memory:{},budget_cents:500}' > "$T/c/projects/locp.json"
$DA agent add worker --roles build --project locp >/dev/null 2>&1 || no "add worker: $($DA agent add worker --roles build --project locp 2>&1)"
e=$($DA agent for build --profile quick --project locp 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q "per_dispatch_model_override is not supported on local" <<<"$e"; } && ok "extension enabled but unverified: the member keeps its own model; another profile's model is refused (exit 2)" || no "ext unverified: rc=$rc $e"
python3 -I - <<'PY'
import sys; sys.path.insert(0, "lib")
import provider as P
P.record_verification("ovl", {"per_dispatch_model_override": {"hash": P.extension_hash("ovl", "locov", "local"), "by": "attest", "at": "2026-11-02", "note": "test"}})
PY
e=$($DA agent for build --profile quick --project locp 2>&1); rc=$?
{ [ $rc = 0 ] && [ "${e%% *}" = worker ]; } && ok "extension verified: the profile's model is dispatched to the member (the project's capability, not the runtime's alone)" || no "ext verified: rc=$rc $e"
jq 'del(.models.extensions)' "$T/c/projects/locp.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/locp.json"
$DA agent for build --profile quick --project locp >/dev/null 2>&1; [ $? = 2 ] && ok "and a project that did not enable it is refused again" || no "ext disabled"
$DA agent remove worker --project locp >/dev/null 2>&1
# rnl has no member renderer; rnext gives it one. The members of a project that enabled it are rendered from the composed definition
LIBR=$T/c/packs/providers/rnl; mkdir -p "$LIBR"
jq '.provider = "rnl" | del(.renderers)' "$LIB/definition.json" > "$LIBR/definition.json"
python3 -I tests/handseal.py "$LIBR"
RNX=$T/ext/rnext; mkdir -p "$RNX"
jq -n --slurpfile d "$LIB/definition.json" '{schema:2,kind:"extension",extension:"rnext",description:"a member renderer for rnl",extends:"rnl",provides:["agent_definitions"],
  adds:{capabilities:{agent_definitions:{value:"yes",note:"n"}},renderers:{agent:$d[0].renderers.agent}}}' > "$RNX/definition.json"
imp "$RNX" || no "could not import rnext"
git init -q "$T/repo-r"
jq -n --arg p "$T/repo-r" '{schema:1,project:"rnp",repo:{url:"https://github.com/example/rnp",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},
  models:{provider:"rnl"},memory:{},budget_cents:500}' > "$T/c/projects/rnp.json"
out=$($DA agent add rn1 --roles build --project rnp 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "renderers.agent" <<<"$out"; } && ok "extension not enabled: a runtime with no member renderer cannot serve members" || no "rnl without extension: rc=$rc $out"
jq '.models.extensions = ["rnext"]' "$T/c/projects/rnp.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/rnp.json"
out=$($DA agent add rn1 --roles build --project rnp 2>&1); RF=$T/s/render/rnp/rnl.agents/rn1.toml; [ -f "$RF" ] || RF=$T/repo-r/.fake/agents/rn1.toml
{ [ -f "$RF" ] && [ "$(toml "$RF" | jq -r .name)" = rn1 ]; } && ok "extension enabled: the member is rendered by the renderer the extension added" || no "rnl with extension: $out"
$DA agent list | grep 'rn1 ' | grep -q '(' && no "rn1 flagged right after add: $($DA agent list | grep rn1)" || ok "and it is current"
python3 -I - "$T/c/packs/providers/rnext" <<'PY'
import json, os, sys
p = os.path.join(sys.argv[1], "definition.json")
d = json.load(open(p)); d["adds"]["renderers"]["agent"]["fields"].append({"from": "abilities", "to": "serves", "transform": [{"join": " "}]}); json.dump(d, open(p, "w"))
PY
$DA agent list | grep 'rn1 ' | grep -q 'STALE\|unsealed\|changed' && ok "a changed extension makes its member STALE" || no "extension changed: $($DA agent list | grep rn1)"
jq 'del(.models.extensions)' "$T/c/projects/rnp.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/rnp.json"
$DA agent list | grep 'rn1 ' | grep -q 'STALE' && ok "and so does disabling it" || no "extension disabled: $($DA agent list | grep rn1)"

# --- one broken record of another project does not stop this project's work; rename keeps a hand-edited file
jq '.projects.zbroken.bad = {file: "x.md"}' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
out=$($DA agent for build --project pbase 2>&1); echo "$out" | grep -q 'agents.json:' && no "a broken record of another project blocks agent for: $out" || ok "agent for works in a project whose neighbour has a broken record"
out=$($DA agent for build --project zbroken 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'member bad of project zbroken has no roles' <<<"$out"; } && ok "and the broken project itself is refused (exit 2)" || no "broken project: rc=$rc $out"
out=$($DA agent list 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'member bad of project zbroken' <<<"$out"; } && ok "list without a project still checks every project" || no "list all: rc=$rc $out"
$DA agent list --project pbase >/dev/null 2>&1 && ok "list --project checks that project only" || no "list --project pbase"
jq 'del(.projects.zbroken)' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
$DA agent add hand1 --project pbase >/dev/null 2>&1 && echo "# my edit" >> "$A/hand1.md"
out=$($DA agent rename hand1 hand2 2>&1); rc=$?
{ [ $rc = 0 ] && [ -f "$A/hand2.md" ] && [ -f "$A/hand1.md" ] && grep -q '^# my edit' "$A/hand1.md" && grep -q 'hand1.md was edited by hand, so it was kept' <<<"$out"; } \
  && ok "rename keeps a hand-edited file and says so" || no "rename of a DRIFT member: rc=$rc $out"
$DA agent add clean1 --project pbase >/dev/null 2>&1; $DA agent rename clean1 clean2 >/dev/null 2>&1
{ [ -f "$A/clean2.md" ] && [ ! -e "$A/clean1.md" ]; } && ok "and an unedited file is removed as before" || no "rename of a current member"

# --- the MCP tools of a member are the ones the tool packs of its roles give it, under the runtime's names; the hook command then names the member's
# project and roles, so the guard can hold a call to them where it finds no run (an MCP call names no path)
tools_of() { sed -n 's/^tools: //p' "$A/$1.md"; }
hook_of() { sed -n 's/^ *command: //p' "$A/$1.md"; }
BASE_TOOLS='Bash, Read, Edit, Write, Grep, Glob, Monitor, TaskStop, ToolSearch, Skill'
printf '%s' '{"name":"kb","url":"https://mcp.example.net/kb","write_ok":true,"tools":{"platform.list_items":"always_allow","getStatus":"always_allow","platform.delete_knowledge":"always_allow","repo/push":"auto","issue-close":"always_ask"}}' > "$T/kb.json"
ktok=$($DA tool import "$T/kb.json" --compatible any | tok_of); $DA tool import "$T/kb.json" --compatible any --plan "$ktok" --approved test >/dev/null
$DA agent add mcp0 --project pbase --roles build >/dev/null 2>&1
[ "$(tools_of mcp0)" = "$BASE_TOOLS" ] && [ "$(hook_of mcp0)" = "qargi __guard" ] && ok "a tool pack nobody linked gives a member nothing" || no "unlinked pack: $(tools_of mcp0) / $(hook_of mcp0)"
$DA tool link kb --scope project --project pbase >/dev/null
$DA agent list | grep -q "mcp0 .*(STALE: qargi agent refresh mcp0 --project pbase)$" && ok "a member is STALE once a tool pack reaches its roles" || no "not stale after the link: $($DA agent list | grep mcp0)"
# the guard asked as the hook asks it (the hook command of the member's file, here with this checkout's qargi), from a directory that is in no run
gcall() { # member tool: the exit status of the member's hook for a call of the tool; the refusal goes to $T/g.err
  local args; args=$(hook_of "$1"); args=${args#qargi __guard}
  # shellcheck disable=SC2086  # the arguments of the hook command are words
  jq -nc --arg t "$2" --arg d "$T" '{tool_name:$t,tool_input:{},cwd:$d}' | $DA __guard $args >/dev/null 2>"$T/g.err"
}
gcall mcp0 mcp__kb__getStatus; [ $? = 2 ] && grep -q "does not say whose member this is" "$T/g.err" && ok "a member rendered before the pack was linked is refused the tool until it is refreshed" || no "stale member: $(cat "$T/g.err")"
$DA agent refresh mcp0 >/dev/null 2>&1
[ "$(tools_of mcp0)" = "$BASE_TOOLS, mcp__kb__getStatus, mcp__kb__platform_delete_knowledge, mcp__kb__platform_list_items, mcp__kb__repo_push" ] \
  && ok "refresh gives it the tools of the pack under the runtime's names, without the always_ask one" || no "tools of a build member: $(tools_of mcp0)"
[ "$(hook_of mcp0)" = "qargi __guard --project pbase --roles build" ] && ok "and its hook command names its project and roles" || no "hook of a build member: $(hook_of mcp0)"
$DA agent list | grep -q "mcp0 .*mcp0\.md$" && ok "and it is current again" || no "still flagged: $($DA agent list | grep mcp0)"
$DA agent add mcp1 --project pbase --roles review >/dev/null 2>&1
[ "$(tools_of mcp1)" = "$BASE_TOOLS, mcp__kb__getStatus, mcp__kb__platform_list_items" ] && [ "$(hook_of mcp1)" = "qargi __guard --project pbase --roles review --class read-only" ] \
  && ok "a member of read-only roles gets the declared reads alone, and its class stays in the hook command" || no "review member: $(tools_of mcp1) / $(hook_of mcp1)"
$DA agent add mcp2 --project pbase --roles build,review >/dev/null 2>&1
[ "$(tools_of mcp2)" = "$(tools_of mcp0)" ] && [ "$(hook_of mcp2)" = "qargi __guard --project pbase --roles build,review" ] && ok "a member of several roles gets what any of them may call; the guard narrows it to the role of the task" || no "two roles: $(tools_of mcp2) / $(hook_of mcp2)"
gcall mcp0 mcp__kb__platform_delete_knowledge && ok "the hook command of a build member lets it call a write tool the pack allows" || no "build member write tool: $(cat "$T/g.err")"
gcall mcp0 mcp__kb__issue-close; [ $? = 2 ] && grep -q "always_ask" "$T/g.err" && ok "and refuses the always_ask tool" || no "always_ask: $(cat "$T/g.err")"
gcall mcp1 mcp__kb__getStatus && ok "the hook command of a review member lets it call a declared read" || no "review member read: $(cat "$T/g.err")"
gcall mcp1 mcp__kb__platform_delete_knowledge; [ $? = 2 ] && grep -q "under the read-only class" "$T/g.err" && ok "and refuses a write tool" || no "review member write: $(cat "$T/g.err")"
gcall mcp2 mcp__kb__platform_delete_knowledge; [ $? = 2 ] && grep -q "must be allowed for each of build, review" "$T/g.err" && ok "a member of a write and a read-only role calls only what both allow where no run is found" || no "two roles write: $(cat "$T/g.err")"
$DA tool unlink kb --scope project --project pbase >/dev/null
$DA agent list | grep -q "mcp0 .*(STALE: qargi agent refresh mcp0 --project pbase)$" && ok "a member is STALE once the pack is unlinked" || no "not stale after the unlink"
$DA agent refresh mcp0 >/dev/null 2>&1
[ "$(tools_of mcp0)" = "$BASE_TOOLS" ] && [ "$(hook_of mcp0)" = "qargi __guard" ] && ok "refresh takes the MCP tools away again" || no "after the unlink: $(tools_of mcp0) / $(hook_of mcp0)"
rm -rf "$T"
exit $fail
