#!/usr/bin/env bash
# A caller that is itself approved (QARGI_NESTED set) has not approved this plan: need_plan skips its check when QARGI_NESTED is set, so every
# call site of it is written `QARGI_NESTED='' need_plan ...`, and a nested environment never skips a plan token. One verb that needs a plan
# for each file that calls it (branch, marshal, project, provider, registry, provision, cred), each run with QARGI_NESTED=1 and no token, then a wrong one:
# refused (exit not 0, "the plan changed or --plan is missing") and nothing changed. The sites of release, local, feature, upstream and backlog
# are tested in their own tests; canon apply is the one verb that honours QARGI_NESTED (provisioning runs it that way) and is not tested here.
# Offline (fake ant, curl, git). Run: tests/test_nested_plan.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0; DA=$SRC/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T FAKE=$T/fake GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$FAKE"
trap 'rm -rf "$T" "$HERMETIC"' EXIT
cd "$T" || exit 1   # a verb that changes the marshal refuses to run inside a member run, which is where this checkout may be
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }

# --- static: every call of need_plan in lib/ and bin/ is written QARGI_NESTED='' need_plan, or is one of the few sites below, so a future call
# that forgets the prefix is found here and not by a user. The sites that are not prefixed (the file, how many, why):
#   canon.sh      1  canon apply honours the variable: provisioning runs it nested after its own plan check, and the guard refuses an agent that sets it
#   memory.sh     1  the verb unsets QARGI_NESTED first
#   tierwrite.sh  1  the script unsets QARGI_NESTED first
#   packs.sh      1  the write verbs unset QARGI_NESTED first
#   project.sh    1  project link unsets QARGI_NESTED first
ALLOW="canon.sh:1 memory.sh:1 tierwrite.sh:1 packs.sh:1 project.sh:1"
UNSETS="memory.sh tierwrite.sh packs.sh project.sh"
bare=$(grep -nE '(^|[^_A-Za-z])need_plan "' "$SRC"/lib/*.sh "$SRC"/bin/* 2>/dev/null | grep -vE "^[^:]*:[0-9]+:[[:space:]]*#" | grep -v "QARGI_NESTED='' need_plan" | grep -v "lib/lib.sh:")
n_all=$(grep -hE '(^|[^_A-Za-z])need_plan "' "$SRC"/lib/*.sh "$SRC"/bin/* 2>/dev/null | grep -cvE "^[[:space:]]*#")
msg=''
for f in $(sed -E 's#^.*/([^/:]*):[0-9]+:.*#\1#' <<<"$bare" | sort -u); do
  case " $ALLOW " in *" $f:"*) ;; *) msg="$msg $f (not on the list)";; esac
done
for a in $ALLOW; do
  f=${a%%:*}; want=${a##*:}
  [ "$(grep -cE "/$f:" <<<"$bare")" = "$want" ] || msg="$msg $f (has $(grep -cE "/$f:" <<<"$bare") unprefixed, the list says $want)"
done
for f in $UNSETS; do grep -vE '^[[:space:]]*#' "$SRC/lib/$f" | grep -q 'unset QARGI_NESTED' || msg="$msg $f (no unset QARGI_NESTED)"; done
[ "$n_all" -ge 30 ] && [ -z "$msg" ] && ok "static: every need_plan call in lib/ is prefixed QARGI_NESTED='' or is on the short list (canon apply, and the verbs that unset it first)" || no "static need_plan check: $msg (calls found: $n_all); unprefixed: $bare"
MSG="the plan changed or --plan is missing"
# refused CMD...: run the command, with its output in $out; true when it exited not 0 and asked for the token
refused() { out=$("$@" 2>&1); rc=$?; [ $rc != 0 ] && grep -q "$MSG" <<<"$out"; }

# --- branch prune: a merged agent branch is planned; applied nested with no token or a wrong one, it stays
R=$T/app; O=$T/origin.git; git init -q -b master "$R"; git init -q --bare "$O"
echo 0.1.0 > "$R/VERSION"; git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$O" && git -C "$R" push -q origin master develop
git -C "$R" checkout -q -b agent/gone develop; echo x > "$R/x.txt"; git -C "$R" add -A; git -C "$R" commit -q -m task
git -C "$R" checkout -q develop; git -C "$R" merge -q --no-ff agent/gone -m "merge gone"; git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
B="$DA branch"
t=$(QARGI_PROJECT=app $B prune | tok)
[ -n "$t" ] && ok "(setup) branch prune plans the merged agent/gone" || no "(setup) branch prune plan"
refused env QARGI_NESTED=1 QARGI_PROJECT=app $DA branch prune --approved go && git -C "$R" rev-parse -q --verify refs/heads/agent/gone >/dev/null && ok "branch prune with no token under QARGI_NESTED is refused, the branch stays" || no "branch, no token: rc=$rc $out"
refused env QARGI_NESTED=1 QARGI_PROJECT=app $DA branch prune --plan 000000000000 --approved go && git -C "$R" rev-parse -q --verify refs/heads/agent/gone >/dev/null && ok "and a wrong token is refused under QARGI_NESTED too" || no "branch, wrong token: rc=$rc $out"

# --- marshal key init: the signing key is not made
KEY=$T/c/credentials/marshal_ed25519
refused env QARGI_NESTED=1 $DA marshal key init --approved go && [ ! -e "$KEY" ] && ok "marshal key init with no token under QARGI_NESTED is refused, no key is made" || no "marshal, no token: rc=$rc $out"
refused env QARGI_NESTED=1 $DA marshal key init --plan 000000000000 --approved go && [ ! -e "$KEY" ] && ok "and a wrong token is refused under QARGI_NESTED too" || no "marshal, wrong token: rc=$rc $out"

# --- project attach: no stored answers are written
AF=$T/afrepo; git init -q -b main "$AF"; echo x > "$AF/README"; git -C "$AF" add -A; git -C "$AF" commit -q -m one
refused env QARGI_NESTED=1 $DA project attach "$AF" --name afp --url https://github.com/example/afp --approved go && [ ! -e "$T/c/projects/afp.json" ] && ok "project attach with no token under QARGI_NESTED is refused, nothing is stored" || no "project, no token: rc=$rc $out"
refused env QARGI_NESTED=1 $DA project attach "$AF" --name afp --url https://github.com/example/afp --plan 000000000000 --approved go && [ ! -e "$T/c/projects/afp.json" ] && ok "and a wrong token is refused under QARGI_NESTED too" || no "project, wrong token: rc=$rc $out"
t=$($DA project attach "$AF" --name afp --url https://github.com/example/afp | tok)
out=$(QARGI_NESTED=1 $DA project attach "$AF" --name afp --url https://github.com/example/afp --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ -e "$T/c/projects/afp.json" ] && ok "the right token still applies under QARGI_NESTED" || no "project, right token: rc=$rc $out"

# --- provider accept: a copy of the tool holds a runtime with no read-only barrier; the acceptance is not recorded
TOOL=$T/tool; copy_tool "$SRC" "$TOOL"
# shellcheck source=fakeprov.sh
. "$SRC/tests/fakeprov.sh"
NB='.capabilities.read_only_barrier |= (.value = "no" | .note = "nothing stops a write")'
fake_family "$SRC" "$TOOL" nobarrier . "$NB" "$NB"
git init -q -b main "$T/repo-alpha"; git -C "$T/repo-alpha" commit -q --allow-empty -m one
"$DA" project template alpha | jq --arg r "$T/repo-alpha" '.repo.url = "https://github.com/example/alpha" | .repo.path = $r | .models.provider = {local: "nobarrier-local", cloud: "nobarrier-cloud"}' > "$T/alpha.json"
"$DA" project init alpha --answers "$T/alpha.json" --force >/dev/null 2>&1 || no "(setup) init alpha"
ACCEPT=("$TOOL/bin/qargi" provider accept nobarrier-cloud --surface cloud --no-barrier --project alpha --asked "review on cloud is fine here")
t=$("${ACCEPT[@]}" | tok)
[ -n "$t" ] && ok "(setup) provider accept plans" || no "(setup) provider accept plan"
refused env QARGI_NESTED=1 "${ACCEPT[@]}" --plan 000000000000 --approved go && ! jq -e '.models.accept_no_barrier' "$T/c/projects/alpha.json" >/dev/null 2>&1 && ok "provider accept with a wrong token under QARGI_NESTED is refused, nothing is recorded" || no "provider, wrong token: rc=$rc $out"

# --- instances refresh-prompt: the cloud agent is not updated
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
case $1 in
  auth) exit 0;;
  beta:agents) case $2 in retrieve) echo '{"id":"agent_B","version":1,"archived_at":null,"name":"alpha-build","system":"an old prompt"}';; *) echo '{}';; esac;;
  beta:deployments) echo '{"id":"depl_B","status":"active","archived_at":null,"agent":{"id":"agent_B","version":1}}';;
  *) echo '{}';;
esac
EOS
cat > "$T/bin/curl" <<'EOS'
#!/usr/bin/env bash
for a in "$@"; do url=$a; done
case $url in
  *"/branches/"*"/protection") printf '{"message":"Resource not accessible by personal access token"}\n403';;
  *"/repos/example/x") printf '{"full_name":"example/x","default_branch":"main","permissions":{"push":true,"admin":true}}\n200';;
  *"/user/repos"*) printf '[{"name":"r0"}]\n200';;
  *) printf '{"message":"Not Found"}\n404';;
esac
EOS
cat > "$T/bin/git" <<'EOS'
#!/usr/bin/env bash
if printf '%s\n' "$@" | grep -qx push; then case "$*" in *github.com/example/x.git*) exit 0;; *) exit 1;; esac; fi
exec /usr/bin/git "$@"
EOS
chmod 755 "$T/bin/ant" "$T/bin/curl" "$T/bin/git"; export PATH=$T/bin:$PATH
jq -n '{schema:1,project:"beta",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},
  models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/beta.json"
jq -n '{"beta-build":{location:"cloud",deployment_id:"depl_B",environment_id:"env_1",agent:{id:"agent_B",version_pinned:1,model:"claude-sonnet-5-5",effort:"high"}}}' > "$T/c/instances.json"
t=$($DA instances refresh-prompt beta-build --asked "t" | tok)
[ -n "$t" ] && ok "(setup) refresh-prompt plans the new prompt" || no "(setup) refresh-prompt plan: $($DA instances refresh-prompt beta-build --asked t 2>&1 | tail -3)"
refused env QARGI_NESTED=1 $DA instances refresh-prompt beta-build --asked "t" --approved go && ! grep -q "beta:agents update" "$FAKE/ant.log" && ok "refresh-prompt with no token under QARGI_NESTED is refused, the agent is not updated" || no "registry, no token: rc=$rc $out"
refused env QARGI_NESTED=1 $DA instances refresh-prompt beta-build --asked "t" --plan 000000000000 --approved go && ! grep -q "beta:agents update" "$FAKE/ant.log" && ok "and a wrong token is refused under QARGI_NESTED too" || no "registry, wrong token: rc=$rc $out"

# --- provision apply: no cloud resource is created (ant apply is not run)
t=$($DA provision plan beta-build 2>&1 | tok)
[ -n "$t" ] && ok "(setup) provision plans" || no "(setup) provision plan: $($DA provision plan beta-build 2>&1 | tail -3)"
refused env QARGI_NESTED=1 $DA provision apply beta-build --asked "t" --approved go && ! grep -q "apply --yes" "$FAKE/ant.log" && ok "provision apply with no token under QARGI_NESTED is refused, nothing is created" || no "provision, no token: rc=$rc $out"
refused env QARGI_NESTED=1 $DA provision apply beta-build --asked "t" --plan 000000000000 --approved go && ! grep -q "apply --yes" "$FAKE/ant.log" && ok "and a wrong token is refused under QARGI_NESTED too" || no "provision, wrong token: rc=$rc $out"

# --- credential setup lead-push: no vault credential is made, no token is stored
jq -n '{schema:1,project:"alpha2",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  lead:{model:"claude-opus-5-5",effort:"high"},teams:{t:{members:["build"]}},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/alpha2.json"
printf '%s' "github_pat_11AAAAAA0abcdefghijklmnopqrstuvwxyz0123456789SECRETVALUE" > "$T/tokfile"
S=("$DA" credential setup lead-push alpha2 --from-file "$T/tokfile")
t=$("${S[@]}" 2>&1 | tok)
[ -n "$t" ] && ok "(setup) credential setup plans" || no "(setup) credential plan: $("${S[@]}" 2>&1 | tail -3)"
refused env QARGI_NESTED=1 "${S[@]}" --asked "user: yes" --approved "user: yes" && [ ! -e "$T/c/credentials/alpha2-lead-push" ] && ! grep -q "vaults" "$FAKE/ant.log" && ok "credential setup with no token under QARGI_NESTED is refused, nothing is stored or created" || no "cred, no token: rc=$rc $out"
refused env QARGI_NESTED=1 "${S[@]}" --asked "user: yes" --approved "user: yes" --plan 000000000000 && [ ! -e "$T/c/credentials/alpha2-lead-push" ] && ! grep -q "vaults" "$FAKE/ant.log" && ok "and a wrong token is refused under QARGI_NESTED too" || no "cred, wrong token: rc=$rc $out"

[ $fail = 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
