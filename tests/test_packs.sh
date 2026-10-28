#!/usr/bin/env bash
# Skills and tools: library, scope links, per-role disable, review and drift, provisioning render.
# Offline (fake ant). Run: tests/test_packs.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s" "$T/bin"
printf '#!/usr/bin/env bash\ncase "$1" in auth) exit 0;; *) echo "{}";; esac\n' > "$T/bin/ant"; chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH
DA=./bin/qargi
proj() { jq -n --arg p "$1" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{dev:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]},
         docs:{base:"gh-pages",push:{mode:"none"},model:"claude-opus-5-5",effort:"medium",apt:[],skills:["pdf"]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha; proj beta

# --- a new skill fails its review until it is real
seal() { local tok; tok=$($DA skill seal "$1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
desc() { sed -i "s/^description: .*/description: $2/" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
$DA skill new style >/dev/null; $DA skill link style --scope user >/dev/null 2>&1 && no "a skill with a placeholder description was linked" || ok "a placeholder skill cannot be linked"
sed -i 's/^description: .*/description: Use when writing release notes in the house style./' "$T/c/packs/skills/style/SKILL.md"
$DA skill link style --scope user >/dev/null 2>&1 && no "an edited, unapproved skill was linked" || ok "an edited skill must be approved (sealed) before it links"
seal style; $DA skill link style --scope user >/dev/null 2>&1 && ok "a sealed skill links" || no "link failed"
$DA skill new style >/dev/null 2>&1 && no "duplicate name accepted" || ok "names are unique"
$DA tool new style >/dev/null 2>&1 && no "a tool took a skill's name" || ok "skills and tools share one namespace"

# --- scopes: user, user-role, project, project-role
$DA skill new dev-only >/dev/null; desc dev-only "Use for dev tasks."; $DA skill link dev-only --scope user-role --role dev >/dev/null
$DA skill new alpha-all >/dev/null; desc alpha-all "Use on alpha."; $DA skill link alpha-all --scope project --project alpha >/dev/null
$DA skill new alpha-docs >/dev/null; desc alpha-docs "Use for alpha docs."; $DA skill link alpha-docs --scope project-role --project alpha --role docs >/dev/null
eff() { $DA skill effective "$1" "$2" | sort | paste -sd, -; }
[ "$(eff alpha dev)" = "alpha-all,dev-only,style" ] && ok "alpha/dev gets user, user-role and project packs" || no "alpha/dev: $(eff alpha dev)"
[ "$(eff alpha docs)" = "alpha-all,alpha-docs,style" ] && ok "alpha/docs gets user, project and project-role packs" || no "alpha/docs: $(eff alpha docs)"
[ "$(eff beta dev)" = "dev-only,style" ] && ok "beta/dev gets only what reaches it (no alpha packs)" || no "beta/dev: $(eff beta dev)"
[ "$(eff beta docs)" = "style" ] && ok "beta/docs gets only the user pack" || no "beta/docs: $(eff beta docs)"

# --- opt out per role
$DA skill disable alpha dev style >/dev/null && [ "$(eff alpha dev)" = "alpha-all,dev-only" ] && ok "a role can disable an inherited pack" || no "disable"
[ "$(eff alpha docs)" = "alpha-all,alpha-docs,style" ] && ok "the opt-out is for that role only" || no "opt-out leaked"
$DA skill enable alpha dev style >/dev/null && [ "$(eff alpha dev)" = "alpha-all,dev-only,style" ] && ok "enable undoes the opt-out" || no "enable"

# --- drift and removal
echo "extra" >> "$T/c/packs/skills/style/SKILL.md"
$DA skill check alpha dev >/dev/null 2>&1 && no "drift not detected" || ok "a changed pack fails check (drift)"
$DA packs render alpha dev "$T/o" >/dev/null 2>&1 && no "render attached a drifted pack" || ok "provisioning refuses a drifted pack"
$DA skill remove style >/dev/null 2>&1 && no "removed a linked pack" || ok "a linked pack cannot be removed"
sed -i '$d' "$T/c/packs/skills/style/SKILL.md"   # undo the edit: the hash matches again
$DA skill check alpha dev >/dev/null 2>&1 && ok "reverting the change clears the drift" || no "drift not cleared"

# --- tools: allowlist and write-like tools
printf '%s' '{"name":"issues","url":"https://mcp.example.net/","tools":{"list_issues":"always_allow","create_issue":"always_allow"}}' > "$T/t.json"
$DA tool import "$T/t.json" 2>&1 | grep -q "create_issue.*write-like" && ok "a write-like tool cannot run unattended" || no "write-like tool accepted"
printf '%s' '{"name":"issues","url":"https://mcp.example.net/","tools":{"list_issues":"always_allow","create_issue":"always_ask"}}' > "$T/t.json"
tok=$($DA tool import "$T/t.json" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
$DA tool import "$T/t.json" --plan wrong --approved x >/dev/null 2>&1 && no "wrong plan token accepted" || ok "an import needs the token of the review"
$DA tool import "$T/t.json" --plan "$tok" --approved "test" >/dev/null 2>&1 && ok "a reviewed tool is stored" || no "tool import"
$DA tool link issues --scope project-role --project beta --role dev >/dev/null
$DA packs render beta dev "$T/o2" >/dev/null 2>&1 && jq -e '.[0].name=="issues"' "$T/o2/mcp.json" >/dev/null && ok "render carries the tool" || no "render"

# --- a skill from a directory, with a secret, is refused at import
mkdir -p "$T/src/leaky"; printf -- '---\nname: leaky\ndescription: Use when testing.\n---\nkey ghp_%s\n' "abcdefghijklmnopqrstuvwxyz0123456789" > "$T/src/leaky/SKILL.md"
$DA skill import "$T/src/leaky" 2>&1 | grep -q "looks like a secret" && ok "a skill with a secret is refused at import" || no "secret skill accepted"

# --- provisioning picks up attached skills and tools
$DA provision plan --project alpha --role docs >/dev/null 2>&1
grep -q "./skills/alpha-all" "$T/s/provision/alpha-docs/agents/alpha-docs/agent.md" && [ -f "$T/s/provision/alpha-docs/agents/alpha-docs/skills/alpha-docs/SKILL.md" ] && ok "provisioning attaches custom skills" || no "skills not in the rendered agent"
$DA provision plan --project beta --role dev >/dev/null 2>&1
f=$T/s/provision/beta-dev/agents/beta-dev; grep -q "mcp_toolset" "$f/agent.md" && grep -q "create_issue" "$f/agent.md" && grep -q "permission_policy: {type: always_ask}" "$f/agent.md" && ok "provisioning attaches the tool with its policies" || no "tool not rendered"

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
$DA tool link issues --scope project-role --project alpha --role docs >/dev/null
echo '{"alpha-docs":{"location":"cloud","deployment_id":"depl_x","agent":{"id":"agent_x","version_pinned":4},"environment_id":"env_x","resources":[]}}' > "$T/c/instances.json"
out=$($DA packs apply alpha-docs --asked "test"); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
echo "$out" | grep -q "custom skills:.*alpha-docs" && ok "the apply plan lists the custom skills" || no "plan listing"
$DA packs apply alpha-docs --asked "test" --approved x >/dev/null 2>&1 && no "applied without the plan token" || ok "apply refuses without the plan token"
$DA packs apply alpha-docs --asked "test" --plan "$tok" --approved "test" >/dev/null 2>&1 && ok "apply runs with the token" || no "apply failed"
u=$(cat "$T/update.args" 2>/dev/null)
grep -q -- '--skill' <<<"$u" && grep -q '"type":"custom"' <<<"$u" && grep -q 'skill_alpha-docs' <<<"$u" && grep -q '"skill_id":"pdf"' <<<"$u" && ok "the agent gets its anthropic and custom skills" || no "skills in the update: $u"
grep -q 'mcp_toolset' <<<"$u" && grep -q 'agent_toolset_20260401' <<<"$u" && ok "the agent keeps its toolset and gains the MCP tool" || no "tools in the update"
grep -q '"name":"web_fetch","enabled":false' <<<"$u" && grep -q '"name":"web_search","enabled":false' <<<"$u" && ! grep -q '"name":"edit"' <<<"$u" && ok "apply switches the web tools off for a docs role and keeps edit" || no "tool configs in the update: $u"
exit $fail
