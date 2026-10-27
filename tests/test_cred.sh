#!/usr/bin/env bash
# Private-repository credentials: validation, and that the token never reaches an argument,
# the tracker or the audit log. Uses a fake `ant` on PATH. Run: tests/test_cred.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s" "$T/bin" "$T/secrets"
TOKEN=ghp_TESTTOKEN0123456789abcdefXYZ
printf '%s\n' "$TOKEN" > "$T/secrets/tok"; chmod 600 "$T/secrets/tok"
mk() { jq -n --arg f "$1" '{schema:1,project:"demo",repo:{url:"https://github.com/example/demo",path:"",credential_file:$f,long_lived:["main"]},
  roles:{dev:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},memory:{memory_store:"",reference_store:""},budget_cents:1500}'; }

# --- validation
mk "$T/secrets/tok" > "$T/a.json"; ./bin/qargi project validate "$T/a.json" >/dev/null 2>&1 && ok "a private 600 file outside any repo is accepted" || no "valid credential file"
chmod 644 "$T/secrets/tok"; ./bin/qargi project validate "$T/a.json" >/dev/null 2>&1 && no "world-readable file accepted" || ok "a world-readable credential file is refused"; chmod 600 "$T/secrets/tok"
git init -q "$T/repo"; cp "$T/secrets/tok" "$T/repo/tok"; chmod 600 "$T/repo/tok"; mk "$T/repo/tok" > "$T/b.json"
./bin/qargi project validate "$T/b.json" >/dev/null 2>&1 && no "file inside a repo accepted" || ok "a credential file inside a git repository is refused"
mk "$T/secrets/missing" > "$T/c.json"; ./bin/qargi project validate "$T/c.json" >/dev/null 2>&1 && no "missing file accepted" || ok "a missing credential file is refused"

# --- a session with the repository mounted, with a fake ant
cat > "$T/bin/ant" <<FAKE
#!/usr/bin/env bash
echo "\$*" >> "$T/argv.log"
case "\$1" in
  auth) exit 0;;
  beta:deployments) echo '{"id":"depl_fake","agent":{"id":"agent_fake","version":3},"environment_id":"env_fake","vault_ids":[],"budget":{"type":"limit","max_list_cost":{"amount":"1500","currency":"USD"}},"resources":[{"type":"memory_store","memory_store_id":"memstore_fake","access":"read_write"}],"initial_events":[{"type":"user.message","content":[{"type":"text","text":"ready?"}]}]}';;
  beta:sessions) if [ "\$2" = create ]; then cat > "$T/body.json"; echo '{"id":"sesn_fake"}'; else echo '{"status":"idle","budget":{"max_list_cost":{"amount":"1500"}},"usage":{"list_cost":{"amount":"0"}}}'; fi;;
  *) echo '{}';;
esac
FAKE
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH
mk "$T/secrets/tok" > "$T/c/projects/demo.json"; chmod 600 "$T/c/projects/demo.json"
echo '{"demo-dev":{"location":"cloud","deployment_id":"depl_fake","agent":{"id":"agent_fake","version_pinned":3},"environment_id":"env_fake","resources":[]}}' > "$T/c/instances.json"
./bin/qargi start demo-dev --asked "test" >/dev/null 2>&1 && ok "start succeeds with a credential" || no "start failed"
jq -e '.resources[] | select(.type=="github_repository") | .url=="https://github.com/example/demo"' "$T/body.json" >/dev/null && ok "the repository is mounted as a github_repository resource" || no "no github_repository resource"
jq -e '.resources[] | select(.type=="memory_store")' "$T/body.json" >/dev/null && ok "the deployment's memory stores are kept" || no "memory stores lost"
jq -e '.budget.max_list_cost.amount=="1500"' "$T/body.json" >/dev/null && ok "the deployment's budget is kept" || no "budget lost"
grep -q "$TOKEN" "$T/body.json" && ok "the token reaches ant on stdin" || no "the token is missing from the body"
grep -q "$TOKEN" "$T/argv.log" && no "THE TOKEN IS IN AN ARGUMENT" || ok "the token is in no command-line argument"
grep -rq "$TOKEN" "$T/s" && no "THE TOKEN IS IN THE STATE DIRECTORY (tracker or audit log)" || ok "the token is in neither the tracker nor the audit log"
grep -q "credential file tok" "$T/s/audit.log" && ok "the audit log names the credential file, not its content" || no "audit entry missing"
QARGI_DRY_RUN=1 ./bin/qargi start demo-dev --asked "test" 2>/dev/null | grep -q "$TOKEN" && no "the dry run printed the token" || ok "the dry run masks the token"
exit $fail
