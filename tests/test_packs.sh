#!/usr/bin/env bash
# Skills and tools: library, scope links, per-role disable, review and drift, provisioning render.
# Offline (fake ant). Run: tests/test_packs.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s" "$T/bin"
printf '#!/usr/bin/env bash\ncase "$1" in auth) exit 0;; *) echo "{}";; esac\n' > "$T/bin/ant"; chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH
DA=./bin/qargi
proj() { jq -n --arg p "$1" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]},
         write:{base:"gh-pages",push:{mode:"none"},model:"claude-opus-5-5",effort:"medium",apt:[],skills:["pdf"]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha; proj beta

# --- a new skill fails its review until it is real
seal() { local tok; tok=$($DA skill seal "$1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
desc() { sed -i "s/^description: .*/description: $2/" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
$DA skill new style --compatible any >/dev/null; $DA skill link style --scope user >/dev/null 2>&1 && no "a skill with a placeholder description was linked" || ok "a placeholder skill cannot be linked"
sed -i 's/^description: .*/description: Use when writing release notes in the house style./' "$T/c/packs/skills/style/SKILL.md"
$DA skill link style --scope user >/dev/null 2>&1 && no "an edited, unapproved skill was linked" || ok "an edited skill must be approved (sealed) before it links"
seal style; $DA skill link style --scope user >/dev/null 2>&1 && ok "a sealed skill links" || no "link failed"
$DA skill new style --compatible any >/dev/null 2>&1 && no "duplicate name accepted" || ok "names are unique"
$DA tool new style --compatible any >/dev/null 2>&1 && no "a tool took a skill's name" || ok "skills and tools share one namespace"

# --- scopes: user, user-role, project, project-role
$DA skill new build-only --compatible any >/dev/null; desc build-only "Use for build tasks."; $DA skill link build-only --scope user-role --role build >/dev/null
$DA skill new alpha-all --compatible any >/dev/null; desc alpha-all "Use on alpha."; $DA skill link alpha-all --scope project --project alpha >/dev/null
$DA skill new alpha-write --compatible any >/dev/null; desc alpha-write "Use for alpha write."; $DA skill link alpha-write --scope project-role --project alpha --role write >/dev/null
eff() { $DA skill effective "$1" "$2" | sort | paste -sd, -; }
[ "$(eff alpha build)" = "alpha-all,build-only,style" ] && ok "alpha/build gets user, user-role and project packs" || no "alpha/build: $(eff alpha build)"
[ "$(eff alpha write)" = "alpha-all,alpha-write,style" ] && ok "alpha/write gets user, project and project-role packs" || no "alpha/write: $(eff alpha write)"
[ "$(eff beta build)" = "build-only,style" ] && ok "beta/build gets only what reaches it (no alpha packs)" || no "beta/build: $(eff beta build)"
[ "$(eff beta write)" = "style" ] && ok "beta/write gets only the user pack" || no "beta/write: $(eff beta write)"

# --- opt out per role
$DA skill disable alpha build style >/dev/null && [ "$(eff alpha build)" = "alpha-all,build-only" ] && ok "a role can disable an inherited pack" || no "disable"
[ "$(eff alpha write)" = "alpha-all,alpha-write,style" ] && ok "the opt-out is for that role only" || no "opt-out leaked"
$DA skill enable alpha build style >/dev/null && [ "$(eff alpha build)" = "alpha-all,build-only,style" ] && ok "enable undoes the opt-out" || no "enable"

# --- drift and removal
echo "extra" >> "$T/c/packs/skills/style/SKILL.md"
$DA skill check alpha build >/dev/null 2>&1 && no "drift not detected" || ok "a changed pack fails check (drift)"
$DA packs render alpha build "$T/o" >/dev/null 2>&1 && no "render attached a drifted pack" || ok "provisioning refuses a drifted pack"
$DA skill remove style >/dev/null 2>&1 && no "removed a linked pack" || ok "a linked pack cannot be removed"
sed -i '$d' "$T/c/packs/skills/style/SKILL.md"   # undo the edit: the hash matches again
$DA skill check alpha build >/dev/null 2>&1 && ok "reverting the change clears the drift" || no "drift not cleared"

# --- tools: allowlist and write-like tools
printf '%s' '{"name":"issues","url":"https://mcp.example.net/","tools":{"list_issues":"always_allow","create_issue":"always_allow"}}' > "$T/t.json"
$DA tool import "$T/t.json" --compatible any 2>&1 | grep -q "create_issue.*write-like" && ok "a write-like tool cannot run unattended" || no "write-like tool accepted"
printf '%s' '{"name":"issues","url":"https://mcp.example.net/","tools":{"list_issues":"always_allow","create_issue":"always_ask"}}' > "$T/t.json"
tok=$($DA tool import "$T/t.json" --compatible any | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
$DA tool import "$T/t.json" --compatible any --plan wrong --approved x >/dev/null 2>&1 && no "wrong plan token accepted" || ok "an import needs the token of the review"
$DA tool import "$T/t.json" --compatible any --plan "$tok" --approved "test" >/dev/null 2>&1 && ok "a reviewed tool is stored" || no "tool import"
$DA tool link issues --scope project-role --project beta --role build >/dev/null
$DA packs render beta build "$T/o2" >/dev/null 2>&1 && jq -e '.[0].name=="issues"' "$T/o2/mcp.json" >/dev/null && ok "render carries the tool" || no "render"

# --- a skill from a directory, with a secret, is refused at import
mkdir -p "$T/src/leaky"; printf -- '---\nname: leaky\ndescription: Use when testing.\n---\nkey ghp_%s\n' "abcdefghijklmnopqrstuvwxyz0123456789" > "$T/src/leaky/SKILL.md"
$DA skill import "$T/src/leaky" --compatible any 2>&1 | grep -q "looks like a secret" && ok "a skill with a secret is refused at import" || no "secret skill accepted"

# --- provisioning picks up attached skills and tools
$DA provision plan --project alpha --role write >/dev/null 2>&1
grep -q "./skills/alpha-all" "$T/s/provision/alpha-write/agents/alpha-write/agent.md" && [ -f "$T/s/provision/alpha-write/agents/alpha-write/skills/alpha-write/SKILL.md" ] && ok "provisioning attaches custom skills" || no "skills not in the rendered agent"
$DA provision plan --project beta --role build >/dev/null 2>&1
f=$T/s/provision/beta-build/agents/beta-build; grep -q "mcp_toolset" "$f/agent.md" && grep -q "create_issue" "$f/agent.md" && grep -q "permission_policy: {type: always_ask}" "$f/agent.md" && ok "provisioning attaches the tool with its policies" || no "tool not rendered"

# --- updating an existing cloud agent (fake ant records the calls)
cat > "$T/bin/ant" <<FAKE
#!/usr/bin/env bash
echo "\$*" >> "$T/calls.log"
case "\$1" in
  auth) exit 0;;
  apply) lock=""; names=(); a=("\$@"); for ((i=0;i<\${#a[@]};i++)); do [ "\${a[i]}" = --lock-file ] && lock=\${a[i+1]}; case "\${a[i]}" in skills/*) names+=("\${a[i]}");; esac; done
         { echo '{"resources":{'; sep=""; for n in "\${names[@]}"; do printf '%s"./%s":{"id":"skill_%s"}' "\$sep" "\$n" "\${n#skills/}"; sep=","; done; echo '}}'; } > "\$lock";;
  beta:agents) if [ "\$2" = retrieve ]; then echo '{"version":4,"tools":[{"type":"agent_toolset_20260401","default_config":{"enabled":true}}]}'; else echo "\$*" > "$T/update.args"; echo '{}'; fi;;
  beta:deployments) if [ "\$2" = retrieve ]; then echo '{"agent":{"version":5}}'; else echo '{}'; fi;;
  *) echo '{}';;
esac
FAKE
chmod 755 "$T/bin/ant"
$DA tool link issues --scope project-role --project alpha --role write >/dev/null
echo '{"alpha-write":{"location":"cloud","deployment_id":"depl_x","agent":{"id":"agent_x","version_pinned":4},"environment_id":"env_x","resources":[]}}' > "$T/c/instances.json"
out=$($DA packs apply alpha-write --asked "test"); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
echo "$out" | grep -q "custom skills:.*alpha-write" && ok "the apply plan lists the custom skills" || no "plan listing"
$DA packs apply alpha-write --asked "test" --approved x >/dev/null 2>&1 && no "applied without the plan token" || ok "apply refuses without the plan token"
$DA packs apply alpha-write --asked "test" --plan "$tok" --approved "test" >/dev/null 2>&1 && ok "apply runs with the token" || no "apply failed"
u=$(cat "$T/update.args" 2>/dev/null)
grep -q -- '--skill' <<<"$u" && grep -q '"type":"custom"' <<<"$u" && grep -q 'skill_alpha-write' <<<"$u" && grep -q '"skill_id":"pdf"' <<<"$u" && ok "the agent gets its anthropic and custom skills" || no "skills in the update: $u"

# --- QARGI_NESTED does not stand in for the plan token of a skill-changing verb
mkdir -p "$T/src/good"; printf -- '---\nname: good\ndescription: Use when testing the nested rule.\n---\nbody\n' > "$T/src/good/SKILL.md"
good_tok=$($DA skill import "$T/src/good" --compatible any | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
[ -n "$good_tok" ] || no "no token for the nested test import"
QARGI_NESTED=1 $DA skill import "$T/src/good" --compatible any --approved "an agent says so" >/dev/null 2>&1 && no "a nested import skipped the token" || ok "a nested import without the token is refused"
QARGI_NESTED=1 $DA skill import "$T/src/good" --compatible any --plan 000000000000 --approved x >/dev/null 2>&1 && no "a nested import took a wrong token" || ok "a nested import with a wrong token is refused"
[ ! -e "$T/c/packs/skills/good" ] && ok "nothing was stored by the refused nested imports" || no "a refused import stored the skill"
QARGI_NESTED=1 $DA skill import "$T/src/good" --compatible any --plan "$good_tok" --approved "a person read the review" >/dev/null 2>&1 && [ -d "$T/c/packs/skills/good" ] && ok "a nested import with the right token works (the token is what counts)" || no "nested import with the token"
tail -1 "$T/s/audit.log" | jq -e '.verb=="skill-import" and .nested==false' >/dev/null && ok "the audit line does not claim the call was nested" || no "audit nested flag: $(tail -1 "$T/s/audit.log")"
echo "more" >> "$T/c/packs/skills/good/SKILL.md"
QARGI_NESTED=1 $DA skill seal good --approved "x" >/dev/null 2>&1 && no "a nested seal skipped the token" || ok "a nested seal without the token is refused"
mkdir -p "$T/nosum"; printf '#!/usr/bin/env bash\nexit 0\n' > "$T/nosum/sha256sum"; chmod 755 "$T/nosum/sha256sum"
out=$(PATH=$T/nosum:$PATH $DA skill seal good --plan '' --approved "x" 2>&1) && no "an empty token was accepted" || { grep -q "no plan token" <<<"$out" && ok "an empty expected token is an error, not a match for an empty --plan" || no "empty token message: $out"; }
QARGI_NESTED=1 $DA tool import "$T/t.json" --compatible any --name issues2 --approved "x" >/dev/null 2>&1 && no "a nested tool import skipped the token" || ok "a nested tool import without the token is refused"
QARGI_NESTED=1 $DA packs apply alpha-write --asked "test" --approved x >/dev/null 2>&1 && no "a nested packs apply skipped the token" || ok "a nested packs apply without the token is refused"
rm -f "$T/update.args"
QARGI_NESTED=1 $DA packs apply alpha-write --asked "test" --approved x >/dev/null 2>&1; [ ! -e "$T/update.args" ] && ok "and it did not touch the agent" || no "agent updated by a nested apply"
grep -q 'mcp_toolset' <<<"$u" && grep -q 'agent_toolset_20260401' <<<"$u" && ok "the agent keeps its toolset and gains the MCP tool" || no "tools in the update"
grep -q '"name":"web_fetch","enabled":false' <<<"$u" && grep -q '"name":"web_search","enabled":false' <<<"$u" && ! grep -q '"name":"edit"' <<<"$u" && ok "apply switches the web tools off for a write role and keeps edit" || no "tool configs in the update: $u"
# --- load: what a role has enabled, read at call time
proj gamma
$DA skill new loadme --compatible any >/dev/null; desc loadme "Use for the load test."; mkdir -p "$T/c/packs/skills/loadme/refs"; echo extra > "$T/c/packs/skills/loadme/refs/x.md"; seal loadme
$DA skill link loadme --scope project-role --project gamma --role build >/dev/null
out=$($DA packs load --project gamma --role build 2>&1) && grep -q "skill loadme: Use for the load test." <<<"$out" && ok "load lists the enabled packs with their descriptions" || no "load index: $out"
out=$($DA packs load loadme --project gamma --role build 2>&1) && grep -q "^== skill loadme" <<<"$out" && grep -q "refs/x.md" <<<"$out" && ok "load prints one pack's text and lists its other files" || no "load pack: $out"
$DA packs load loadme --project gamma --role write >/dev/null 2>&1 && no "a pack not enabled for the role was loaded" || ok "load refuses a pack that is not enabled for that role"
$DA packs load '../x' --project gamma --role build >/dev/null 2>&1 && no "a path-like name was accepted" || ok "load refuses a name that is not a pack name"
$DA skill disable gamma build loadme >/dev/null; $DA packs load loadme --project gamma --role build >/dev/null 2>&1 && no "a disabled pack was loaded" || ok "disabling takes effect at once"
$DA skill enable gamma build loadme >/dev/null
echo tampered >> "$T/c/packs/skills/loadme/SKILL.md"
$DA packs load loadme --project gamma --role build >/dev/null 2>&1 && no "a drifted pack was loaded" || ok "load refuses a pack that changed since it was approved"
$DA packs load --project gamma >/dev/null 2>&1 && no "load without a role" || ok "load needs a role"
# --- compatible_providers: every pack declares which providers can use it; the declaration is approved with the content
rec() { jq -c ".$2" "$(if [ "$1" = tool ]; then echo "$T/c/packs/tools/$3.pack.json"; else echo "$T/c/packs/skills/$3/.pack.json"; fi)"; }
mkp() { # name compat: a sealed skill pack (the hash and record as `skill new` and seal write them)
  $DA skill new "$1" --compatible "$2" >/dev/null && sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md" && seal "$1"; }
$DA skill new nodecl >/dev/null 2>&1 && no "skill new without --compatible created a pack" || ok "skill new refuses a pack without compatible_providers"
[ ! -e "$T/c/packs/skills/nodecl" ] && ok "and creates nothing" || no "a refused new left a directory"
$DA tool new nodecl >/dev/null 2>&1 && no "tool new without --compatible created a pack" || ok "tool new refuses a pack without compatible_providers"
for bad in "" "any,claude" "Claude" "a b" "1x" '[]' '{"a":1}' '["any","any2",3]'; do
  $DA skill new badc --compatible "$bad" >/dev/null 2>&1 && no "compatible_providers '$bad' accepted" || ok "compatible_providers '$bad' is refused"
done
[ ! -e "$T/c/packs/skills/badc" ] && ok "a refused declaration creates nothing" || no "badc created"
$DA skill new decl --compatible "claude, fam ,claude" >/dev/null && [ "$(rec skill compatible_providers decl)" = '["claude","fam"]' ] && ok "a declaration is stored sorted, trimmed, without repeats" || no "decl record: $(rec skill compatible_providers decl)"
sed -i "s/^description: .*/description: Use for decl./" "$T/c/packs/skills/decl/SKILL.md"
$DA skill new decl2 --compatible '["fam","any-x"]' >/dev/null && [ "$(rec skill compatible_providers decl2)" = '["any-x","fam"]' ] && ok "a JSON array is accepted too" || no "decl2: $(rec skill compatible_providers decl2)"
$DA skill list | grep -q "^decl .*compatible: claude, fam" && ok "list shows the declaration" || no "list: $($DA skill list | grep decl)"
$DA skill import "$T/src/good" --name noimp >/dev/null 2>&1 && no "import without --compatible reviewed a pack" || ok "import refuses a pack without compatible_providers"
out=$($DA skill import "$T/src/good" --name impc --compatible claude); grep -q "^compatible_providers: claude" <<<"$out" && ok "the import review shows the declaration" || no "import review: $out"
itok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA skill import "$T/src/good" --name impc --compatible "claude,fam" --plan "$itok" --approved x >/dev/null 2>&1 && no "an import with another declaration took the token of the first" || ok "the token covers the declaration (another declaration needs its own approval)"
$DA skill import "$T/src/good" --name impc --compatible claude --plan "$itok" --approved x >/dev/null 2>&1 && [ "$(rec skill compatible_providers impc)" = '["claude"]' ] && ok "an import stores the approved declaration" || no "import record"

# the hash covers the field: the same files, another declaration, another hash; editing the record is drift
seal decl; h1=$($DA skill seal decl | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
$DA skill seal decl --compatible "fam" | grep -q "^compatible_providers changes: " && ok "sealing with another declaration says what changes" || no "seal change line"
h2=$($DA skill seal decl --compatible fam | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
[ -n "$h2" ] && [ "$h2" != "$h1" ] && ok "another declaration is another plan token (the same files hash differently)" || no "hash did not change: $h1 $h2"
mkp hashed any; $DA skill link hashed --scope project --project zeta >/dev/null 2>&1   # no such project: ignored
cp "$T/c/packs/skills/hashed/.pack.json" "$T/rec.keep"
jq '.compatible_providers = ["fam"]' "$T/rec.keep" > "$T/c/packs/skills/hashed/.pack.json"
proj hp; $DA skill link hashed --scope project --project hp >/dev/null 2>&1 && no "a pack whose declaration was edited was linked" || ok "an edited declaration is not the approved content (link refused)"
cp "$T/rec.keep" "$T/c/packs/skills/hashed/.pack.json"; $DA skill link hashed --scope project --project hp >/dev/null 2>&1
jq '.compatible_providers = ["fam"]' "$T/rec.keep" > "$T/c/packs/skills/hashed/.pack.json"
$DA skill check hp build 2>&1 | grep -q "drift" && ok "check reports the edited declaration as drift" || no "no drift for an edited declaration"
$DA packs render hp build "$T/oh" >/dev/null 2>&1 && no "render attached a pack whose declaration was edited" || ok "render refuses it"
cp "$T/rec.keep" "$T/c/packs/skills/hashed/.pack.json"

# a pack with no declaration (an earlier library) is refused wherever it is used, and sealed again with one
mkp legacy any; $DA skill link legacy --scope project --project hp >/dev/null
lh=$(cd "$T/c/packs/skills/legacy" && find . -type f ! -name .pack.json -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
jq --arg h "$lh" 'del(.compatible_providers) | .sha256 = $h' "$T/c/packs/skills/legacy/.pack.json" > "$T/rec.tmp" && cp "$T/rec.tmp" "$T/c/packs/skills/legacy/.pack.json"
$DA skill check hp build 2>&1 | grep -q "skill:legacy: FAIL: compatible_providers: not declared" && ok "check says a pack declares no compatible_providers" || no "check legacy: $($DA skill check hp build 2>&1)"
$DA packs render hp build "$T/ol" >/dev/null 2>&1 && no "render attached a pack with no declaration" || ok "render refuses a pack with no declaration"
$DA skill list | grep -q "^legacy .*compatible: NOT DECLARED" && ok "list marks it NOT DECLARED" || no "list legacy"
$DA skill seal legacy >/dev/null 2>&1 && no "seal accepted a pack with no declaration" || ok "seal refuses it until it is given --compatible"
out=$($DA skill seal legacy --compatible any); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA skill seal legacy --compatible any --plan "$tok" --approved test >/dev/null && [ "$(rec skill compatible_providers legacy)" = '["any"]' ] && $DA skill check hp build >/dev/null 2>&1 && ok "sealed with --compatible any, it passes check again" || no "reseal legacy"
$DA skill unlink legacy --scope project --project hp >/dev/null; $DA skill unlink hashed --scope project --project hp >/dev/null

# tool packs declare it too
printf '%s' '{"name":"ctool","url":"https://mcp.example.net/","tools":{"list_items":"always_allow"}}' > "$T/ct.json"
$DA tool import "$T/ct.json" >/dev/null 2>&1 && no "tool import without --compatible" || ok "tool import refuses a pack without compatible_providers"
tok=$($DA tool import "$T/ct.json" --compatible fam | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA tool import "$T/ct.json" --compatible fam --plan "$tok" --approved x >/dev/null 2>&1 && [ "$(rec tool compatible_providers ctool)" = '["fam"]' ] && ok "a tool pack is stored with its declaration" || no "tool record"

exit $fail
