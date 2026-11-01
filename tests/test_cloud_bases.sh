#!/usr/bin/env bash
# The two cloud bases (worker: write class, reviewer: read-only class) and the safety rules around them: the class of an
# instance name comes from the bases in lib/model-defaults.json and fails closed (an unknown class is read-only, never write);
# a read-only or coordinator class has the edit and write tools off in the cloud; worker and reviewer are reserved names no
# role may take; the read-only barrier guard fires for <project>-reviewer. Hermetic, offline. Run: tests/test_cloud_bases.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$FAKE"

# the ant fake: logs its calls, logged in, answers a deployment run with a session id, everything else with nothing
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
case $1 in
  beta:deployments) if [ "${2:-}" = run ]; then echo '{"session_id":"sesn_1"}'; else echo '{}'; fi;;
  beta:sessions) echo '{"status":"idle","budget":{"max_list_cost":{"amount":"500"}}}';;
esac
exit 0
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

# roles of yours: one read-only, one write, one with a class the guard does not know
mkdir -p "$T/c/roles/audit" "$T/c/roles/probe" "$T/c/roles/odd"
printf '{"class":"read-only"}\n' > "$T/c/roles/audit/role.json"; printf '# Role: audit\n\nList the dependencies.\n' > "$T/c/roles/audit/ROLE.md"
printf '{"class":"write"}\n' > "$T/c/roles/probe/role.json"; printf '# Role: probe\n\nTry things.\n' > "$T/c/roles/probe/ROLE.md"
printf '{"class":"sudo"}\n' > "$T/c/roles/odd/role.json"; printf '# Role: odd\n\nUnknown class.\n' > "$T/c/roles/odd/ROLE.md"

. lib/lib.sh

# --- the class of an instance name
cls() { instance_class "$1" 2>/dev/null; }
[ "$(cls worker)" = write ] && ok "the worker base is write" || no "worker: $(cls worker)"
[ "$(cls reviewer)" = read-only ] && ok "the reviewer base is read-only" || no "reviewer: $(cls reviewer)"
[ "$(cls build)" = write ] && [ "$(cls write)" = write ] && [ "$(cls test)" = write ] && ok "legacy build, write and test stay write" || no "legacy write roles"
[ "$(cls review)" = read-only ] && ok "legacy review stays read-only" || no "review: $(cls review)"
[ "$(cls lead)" = coordinator ] && ok "lead is the coordinator class" || no "lead: $(cls lead)"
[ "$(cls audit)" = read-only ] && [ "$(cls probe)" = write ] && ok "roles of yours keep their class" || no "own roles: $(cls audit) $(cls probe)"
[ "$(cls nosuch)" = read-only ] && ok "an unknown name fails closed: read-only" || no "nosuch: '$(cls nosuch)'"
[ "$(cls odd)" = read-only ] && ok "a role with an unknown class fails closed: read-only" || no "odd: '$(cls odd)'"
[ "$(cls '')" = read-only ] && ok "an empty name fails closed: read-only" || no "empty: '$(cls '')'"
# a defaults table that cannot be read must not turn a base into write
( _QARGI_DEFAULTS=$T/missing.json; [ "$(instance_class reviewer 2>/dev/null)" = read-only ] ) && ok "a base class that cannot be read is read-only" || no "unreadable defaults"
# the old helper is unchanged: it fails for a name it does not know
role_class worker >/dev/null 2>&1 && no "role_class answered for a base name" || ok "role_class itself still fails for a base name (callers use instance_class)"

# --- the tools off in the cloud
off() { tools_off "$1" "${2:-}"; }
has() { case " $1 " in *" $2 "*) return 0;; esac; return 1; }
o=$(off reviewer); has "$o" edit && has "$o" write && has "$o" web_search && has "$o" web_fetch && ok "reviewer: web_search web_fetch edit write off" || no "reviewer off: $o"
o=$(off worker); has "$o" edit || has "$o" write && no "worker lost edit or write: $o" || ok "worker keeps edit and write"
has "$o" web_search && has "$o" web_fetch && ok "worker keeps the web tools off, as before" || no "worker off: $o"
o=$(off review); has "$o" edit && has "$o" write && ok "legacy review: edit and now write off" || no "review off: $o"
[ "$(off build)" = "web_search web_fetch" ] && ok "legacy build is unchanged" || no "build off: $(off build)"
o=$(off lead); has "$o" edit && has "$o" write && ok "lead (coordinator): edit and write off" || no "lead off: $o"
o=$(off nosuch); has "$o" edit && has "$o" write && ok "an unknown class: edit and write off (fail closed)" || no "nosuch off: $o"
o=$(off odd); has "$o" edit && has "$o" write && ok "a role with an unknown class: edit and write off" || no "odd off: $o"
P=$T/proj.json
jq -n '{roles: {reviewer: {tools_off: ["web_search"]}, worker: {tools_off: ["bash"]}, review: {tools_off: []}}}' > "$P"
[ "$(off reviewer "$P")" = web_search ] && [ "$(off worker "$P")" = bash ] && [ "$(off review "$P")" = "" ] && ok "an explicit roles.<role>.tools_off still overrides the default" || no "override: $(off reviewer "$P")|$(off worker "$P")|$(off review "$P")"

# --- the barrier guard fires for <project>-reviewer (claude has no read-only barrier on cloud)
refused() { # name rc output project
  [ "$2" = 2 ] && grep -q "qargi provider accept claude --surface cloud --no-barrier --project $4 --asked" <<<"$3" && ok "$1" || no "$1 (rc=$2: $3)"
}
out=$($DA provision plan --project delta --role reviewer 2>&1); rc=$?
refused "provision plan: the reviewer base is refused where cloud has no barrier" "$rc" "$out" delta
out=$($DA provision apply --project delta --role reviewer --asked x --approved y --plan z 2>&1); rc=$?
refused "provision apply: the reviewer base is refused too" "$rc" "$out" delta
$DA provision plan --project delta --role worker >/dev/null 2>&1 && ok "the worker base passes the guard" || no "worker plan: $($DA provision plan --project delta --role worker 2>&1 | tail -3)"
$DA provision plan --project delta --role review >/dev/null 2>&1; [ $? = 2 ] && ok "legacy review is still refused" || no "legacy review plan"

git init -q -b main "$T/repo" && git -C "$T/repo" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
$DA project template gamma | jq --arg r "$T/repo" '.repo.url = "https://github.com/example/\(.project)" | .repo.path = $r | .models.provider = "claude"' > "$T/gamma.json"
$DA project init gamma --answers "$T/gamma.json" --force >/dev/null 2>&1 || no "init gamma"
jq -n '{"gamma-reviewer":{location:"cloud",deployment_id:"depl_R",environment_id:"env_1",agent:{id:"agent_R",version_pinned:1}},
  "gamma-worker":{location:"cloud",deployment_id:"depl_W",environment_id:"env_1",agent:{id:"agent_W",version_pinned:1}}}' > "$T/c/instances.json"
: > "$FAKE/ant.log"
out=$($DA start gamma-reviewer --asked "start the review" 2>&1); rc=$?
refused "start: the reviewer base is refused until the project accepts" "$rc" "$out" gamma
out=$($DA send gamma-reviewer "review it" --label rv --new --asked "review it" 2>&1); rc=$?
refused "send --new: the reviewer base is refused too" "$rc" "$out" gamma
grep -q 'deployments run' "$FAKE/ant.log" && no "a session was created" || ok "and no session was created"
$DA start gamma-worker --asked "build" >/dev/null 2>&1; grep -q 'deployments run --deployment-id depl_W' "$FAKE/ant.log" && ok "the worker base starts as before" || no "worker start"
tok=$($DA provider accept claude --surface cloud --no-barrier --project gamma --asked "I accept it" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
$DA provider accept claude --surface cloud --no-barrier --project gamma --asked "I accept it" --plan "$tok" --approved go >/dev/null 2>&1 || no "accept"
: > "$FAKE/ant.log"
$DA start gamma-reviewer --asked "start the review" >/dev/null 2>&1; grep -q 'deployments run --deployment-id depl_R' "$FAKE/ant.log" && ok "after the project accepts, the reviewer base starts" || no "reviewer start after accept"

[ $fail = 0 ] && echo "cloud bases tests passed" || { echo "cloud bases tests FAILED"; exit 1; }
