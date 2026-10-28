#!/usr/bin/env bash
# The cloud lead's write token: `credential setup lead-push` checks the token against GitHub, stores it,
# creates the vault credential, records the grant, and the lead's GitHub tool is rendered from it.
# Offline (fake curl and ant). Run: tests/test_leadcred.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
mkdir -p "$T/c/projects" "$T/s" "$T/bin" "$FAKE"
TOK=github_pat_11AAAAAA0abcdefghijklmnopqrstuvwxyz0123456789SECRETVALUE
# fake curl: GitHub answers by path; FAKE_ADMIN / FAKE_PUSH / FAKE_REPOS vary them
cat > "$T/bin/curl" <<'EOS'
#!/usr/bin/env bash
for a in "$@"; do url=$a; done
case $url in
  *"/repos/example/x") jq -nc --argjson p "${FAKE_PUSH:-true}" --argjson a "${FAKE_ADMIN:-false}" '{full_name:"example/x",permissions:{push:$p,admin:$a}}';;
  *"/user/repos"*) n=${FAKE_REPOS:-1}; jq -nc --argjson n "$n" '[range($n) | {name:"r\(.)"}]';;
  *) echo '{"message":"Not Found"}';;
esac
EOS
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
case $1 in
  auth) exit 0;;
  beta:vaults) case $2 in list) :;; create) echo '{"id":"vlt_NEW"}';; esac;;
  beta:vaults:credentials) case $2 in create) cat > "$FAKE/cred-body";; *) :;; esac;;
  beta:deployments) case $2 in retrieve) echo '{"vault_ids":[]}';; update) echo "$*" >> "$FAKE/dep-update";; *) echo '{}';; esac;;
  *) echo "{}";;
esac
EOS
chmod 755 "$T/bin/curl" "$T/bin/ant"; export PATH=$T/bin:$PATH
jq -n '{schema:1,project:"alpha",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{dev:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]},
         docs:{base:"gh-pages",push:{mode:"none"},model:"claude-opus-5-5",effort:"medium",apt:[],skills:[]}},
  lead:{model:"claude-opus-5-5",effort:"high"},
  teams:{t:{members:["dev","docs"]}},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/alpha.json"
printf '%s' "$TOK" > "$T/tokfile"
S="$DA credential setup lead-push alpha"

printf 'ghp_classic' | $S >/dev/null 2>&1 && no "a classic token was accepted" || ok "a classic token is refused"
FAKE_ADMIN=true $S --from-file "$T/tokfile" >/dev/null 2>&1 && no "a token that can administer was accepted" || ok "a token that can administer the repository is refused"
FAKE_PUSH=false $S --from-file "$T/tokfile" >/dev/null 2>&1 && no "a read-only token was accepted" || ok "a token that cannot push is refused"
FAKE_REPOS=3 $S --from-file "$T/tokfile" >/dev/null 2>&1 && no "a token for 3 repositories was accepted" || ok "a token that reaches several repositories is refused"
FAKE_REPOS=3 $S --from-file "$T/tokfile" --allow-more-repos >/dev/null 2>&1 && ok "…unless that is accepted knowingly" || no "allow-more-repos refused"

out=$($S --from-file "$T/tokfile" 2>&1); tok=$(echo "$out" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
[ -n "$tok" ] && [ ! -e "$T/c/credentials/alpha-lead-push" ] && ! grep -q vault "$FAKE/ant.log" 2>/dev/null && ok "without --approved it checks and prints a plan, and changes nothing" || no "plan: $out"
$S --from-file "$T/tokfile" --asked "user: yes" --approved "user: yes" --plan 000000000000 >/dev/null 2>&1 && no "a wrong plan token was accepted" || ok "a wrong plan token is refused"
$S --from-file "$T/tokfile" --approved "user: yes" --plan "$tok" >/dev/null 2>&1 && no "applied without --asked" || ok "applying needs --asked"
out=$($S --from-file "$T/tokfile" --asked "user: yes" --approved "user: yes" --plan "$tok" 2>&1); [ $? = 0 ] && ok "apply succeeds" || no "apply: $out"
f=$T/c/credentials/alpha-lead-push
[ "$(cat "$f")" = "$TOK" ] && [ "$(stat -c %a "$f")" = 600 ] && [ "$(stat -c %a "$(dirname "$f")")" = 700 ] && ok "the token is stored mode 600 in a directory only you can enter" || no "token file"
jq -e '.auth.type == "static_bearer" and .auth.token == "'"$TOK"'" and .auth.mcp_server_url == "https://api.githubcopilot.com/mcp/"' "$FAKE/cred-body" >/dev/null && ok "the vault credential is a bearer credential for the GitHub tool" || no "credential body"
grep -q "$TOK" "$FAKE/ant.log" && no "the token appeared in an ant argument" || ok "the token is in no ant argument (it went on stdin)"
grep -rq "$TOK" "$T/s" 2>/dev/null && no "the token is in the state directory" || ok "the token is in no log or tracker"
jq -e '.lead.push.cloud == "branches" and .lead.push.vault_id == "vlt_NEW" and .lead.push.merge == "ask" and .lead.push.release == "ask" and .lead.push.branch_pattern == "agent/*"' "$T/c/projects/alpha.json" >/dev/null && ok "the grant is recorded in the project answers with merges and releases asked" || no "answers"
$DA project validate alpha >/dev/null 2>&1 && ok "the project still validates" || no "validate: $($DA project validate alpha 2>&1)"

# the lead's GitHub tool
$DA packs render alpha lead "$T/o" >/dev/null 2>&1
jq -e '.[] | select(.name=="github") | .vault_ids == ["vlt_NEW"] and .tools.merge_pull_request == "always_ask" and .tools.create_pull_request == "always_allow" and (.tools | has("delete_file") | not) and (.tools | has("create_release") | not)' "$T/o/mcp.json" >/dev/null \
  && ok "the lead gets a fixed GitHub allowlist: merges asked, nothing destructive, no release tool" || no "mcp: $(cat "$T/o/mcp.json" 2>&1 | head -c 400)"
$DA packs render alpha dev "$T/o2" >/dev/null 2>&1; jq -e 'length == 0' "$T/o2/mcp.json" >/dev/null && ok "a worker gets no GitHub tool" || no "worker mcp"
jq '.lead.push.merge="never"' "$T/c/projects/alpha.json" > "$T/x" && mv "$T/x" "$T/c/projects/alpha.json"
$DA packs render alpha lead "$T/o3" >/dev/null 2>&1; jq -e '.[] | select(.name=="github") | .tools | has("merge_pull_request") | not' "$T/o3/mcp.json" >/dev/null && ok "with merge: never the merge tool is not offered at all" || no "merge never"
jq '.lead.push.merge="ask"' "$T/c/projects/alpha.json" > "$T/x" && mv "$T/x" "$T/c/projects/alpha.json"
jq -n '{"alpha-dev":{location:"cloud",agent:{id:"agent_D",version:1}},"alpha-docs":{location:"cloud",agent:{id:"agent_O",version:1}}}' > "$T/c/instances.json"
$DA provision plan --project alpha --role lead >/dev/null 2>&1
A=$T/s/provision/alpha-lead/agents/alpha-lead
grep -q "mcp_toolset" "$A/agent.md" && grep -q "merge_pull_request" "$A/agent.md" && grep -q "always_ask" "$A/agent.md" && grep -q "vault_ids: \[vlt_NEW\]" "$A/deployment-standby.yaml" && ok "a newly provisioned lead carries the tool, the merge policy and the vault" || no "lead render: $(grep -c . "$A/agent.md")"
exit $fail
