#!/usr/bin/env bash
# The guided lead flow: qargi lead grant | status | revoke; and the lead's context: usage, compact-check and the stage lines.
# Offline (fake curl, git, ant with state; fixture transcripts).
# Run: tests/test_lead.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
mkdir -p "$T/c/projects" "$T/s" "$T/bin" "$FAKE"
TOK=github_pat_11AAAAAA0abcdefghijklmnopqrstuvwxyz0123456789SECRETVALUE
cat > "$T/bin/curl" <<'EOS'
#!/usr/bin/env bash
for a in "$@"; do url=$a; done
case $url in
  *"/branches/"*"/protection") printf '{"message":"Resource not accessible by personal access token"}\n403';;
  *"/repos/example/x") printf '{"full_name":"example/x","default_branch":"main"}\n200';;
  *"/user/repos"*) printf '[{"full_name":"example/other"}]\n200';;
  *) printf '{"message":"Not Found"}\n404';;
esac
EOS
cat > "$T/bin/git" <<'EOS'
#!/usr/bin/env bash
if printf '%s\n' "$@" | grep -qx push; then case "$*" in *github.com/example/x.git*) exit 0;; *) exit 1;; esac; fi
exec /usr/bin/git "$@"
EOS
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
has() { local k=$1; shift; for a in "$@"; do [ "$a" = "$k" ] && return 0; done; return 1; }
arg() { local k=$1; shift; while [ $# -gt 0 ]; do [ "$1" = "$k" ] && { echo "$2"; return; }; shift; done; }
case $1 in
  auth) exit 0;;
  beta:agents)
    case $2 in
      retrieve) if [ "$(arg --agent-id "$@")" = agent_D ]; then jq -nc --argjson v "$(cat "$FAKE/dver" 2>/dev/null || echo 1)" '{id:"agent_D",version:$v}'; exit 0; fi
        jq -nc --argjson t "$([ -f "$FAKE/agent_tool" ] && echo true || echo false)" --argjson p "$([ -f "$FAKE/agent_push" ] && echo true || echo false)" \
        '{id:"agent_L",version:1,system:("Lead contract"+(if $p then "\n# Push\nYou may create branches named agent/*" else "" end)),mcp_servers:(if $t then [{name:"github",url:"u"}] else [] end),tools:[{type:"agent_toolset_20260401"}],multiagent:{type:"coordinator",agents:[{id:"agent_D",version:1}]}}';;
      update) if has --mcp-server "$@"; then touch "$FAKE/agent_tool"; else touch "$FAKE/agent_push"; fi; has --multiagent "$@" && arg --multiagent "$@" > "$FAKE/multiagent"; echo '{}';;
    esac;;
  beta:deployments)
    case $2 in
      retrieve) jq -nc --slurpfile v <(cat "$FAKE/dep_vaults" 2>/dev/null || echo '[]') '{id:"depl_L",vault_ids:$v[0],agent:{id:"agent_L",version:1}}';;
      update) if has --vault-id "$@"; then arg --vault-id "$@" > "$FAKE/dep_vaults"; fi; echo "$*" >> "$FAKE/dep-update"; echo '{}';;
    esac;;
  beta:vaults) case $2 in list) [ -f "$FAKE/vault" ] && echo '{"id":"vlt_NEW","display_name":"alpha-vault-lead"}';; create) touch "$FAKE/vault"; echo '{"id":"vlt_NEW"}';; esac;;
  beta:vaults:credentials) case $2 in list) [ -f "$FAKE/cred" ] && echo '{"id":"vcrd_1"}';; create) cat > /dev/null; touch "$FAKE/cred";; archive) rm -f "$FAKE/cred";; esac;;
  *) echo "{}";;
esac
EOS
chmod 755 "$T/bin/"*; export PATH=$T/bin:$PATH
jq -n '{schema:1,project:"alpha",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]},
         write:{base:"gh-pages",push:{mode:"none"},model:"claude-opus-5-5",effort:"medium",apt:[],skills:[]}},
  lead:{model:"claude-opus-5-5",effort:"high",push:{local:true}},
  teams:{t:{members:["build","write"]}},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/alpha.json"
jq -n '{"alpha-lead":{location:"cloud",deployment_id:"depl_L",environment_id:"env_1",agent:{id:"agent_L",version:1,version_pinned:1}}}' > "$T/c/instances.json"
printf '%s' "$TOK" > "$T/tokfile"; echo y > "$T/yes"; : > "$T/out"
export QARGI_TTY_IN=$T/yes QARGI_TTY_OUT=$T/out

# status before anything
out=$($DA lead status alpha 2>&1)
echo "$out" | grep -q "this session.*may push agent branches" && echo "$out" | grep -q "cloud lead.*no grant" && ok "status before a grant shows this session's grant and no cloud grant" || no "status: $out"

# the flow needs a terminal
QARGI_TTY_IN=/nonexistent $DA lead grant alpha --from-file "$T/tokfile" >/dev/null 2>&1 && no "grant ran without a terminal" || ok "grant refuses to run without a terminal"

# grant: three steps, each approved at the terminal
out=$($DA lead grant alpha --from-file "$T/tokfile" 2>&1); rc=$?
[ $rc = 0 ] && ok "grant completes" || no "grant rc=$rc: $out"
echo "$out" | grep -q "== 1/3" && echo "$out" | grep -q "== 2/3" && echo "$out" | grep -q "== 3/3" && ok "it walks through the three steps, showing each plan" || no "steps: $out"
jq -e '.lead.push.cloud == "branches" and .lead.push.vault_id == "vlt_NEW" and .lead.push.local == true' "$T/c/projects/alpha.json" >/dev/null && ok "the cloud grant is recorded next to the local one" || no "answers"
[ "$(stat -c %a "$T/c/credentials/alpha-lead-push")" = 600 ] && ok "the token is stored mode 600" || no "token file"
grep -q "$TOK" "$FAKE/ant.log" && no "the token appeared in an ant argument" || ok "the token is in no ant argument"
[ -f "$FAKE/agent_tool" ] && [ -f "$FAKE/agent_push" ] && ok "the lead got the GitHub tool and its Push rules" || no "agent state"
grep -q '"approved":"interactive: confirmed at the terminal' "$T/s/audit.log" && ok "the audit log records approval at the terminal" || no "audit: $(tail -3 "$T/s/audit.log")"
echo "$out" | grep -q "GitHub tool.*attached" && echo "$out" | grep -q "Push rules.*in its prompt" && echo "$out" | grep -q "deployment.*vault is attached" && ok "the closing status shows everything in place" || no "closing status: $(echo "$out" | tail -12)"

# a second grant finds everything in place and changes nothing more
n1=$(grep -c "beta:agents update" "$FAKE/ant.log"); out=$($DA lead grant alpha --from-file "$T/tokfile" 2>&1); n2=$(grep -c "beta:agents update" "$FAKE/ant.log")
[ "$n1" = "$n2" ] && echo "$out" | grep -q "already attached" && echo "$out" | grep -q "already in the lead's prompt" && ok "running it again skips the steps already done" || no "idempotent: n1=$n1 n2=$n2"

# status flags a missing token file
mv "$T/c/credentials/alpha-lead-push" "$T/gone"; $DA lead status alpha 2>&1 | grep -q "token file.*MISSING" && ok "status reports a missing token file" || no "status missing file"; mv "$T/gone" "$T/c/credentials/alpha-lead-push"

# a newer member version: status says so, refresh-prompt plans it and points the lead at it
echo 2 > "$FAKE/dver"
$DA lead status alpha 2>&1 | grep -q "pinned at v1, current v2: re-point the lead" && ok "status reports a member that has a newer version" || no "status member: $($DA lead status alpha 2>&1 | tail -3)"
out=$($DA instances refresh-prompt alpha-lead --asked "t" 2>&1)
echo "$out" | grep -q "agent_D: v1 -> v2" && echo "$out" | grep -q "plan token" && ok "refresh-prompt plans the member change and changes nothing" || no "plan: $out"
[ ! -f "$FAKE/multiagent" ] && ok "the plan alone does not touch the agent" || no "plan wrote multiagent"
tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA instances refresh-prompt alpha-lead --asked "t" --plan "$tok" --approved "go ahead" >/dev/null 2>&1
jq -e '.type == "coordinator" and .agents == [{"type":"agent","id":"agent_D","version":2}]' "$FAKE/multiagent" >/dev/null 2>&1 && ok "the approved plan points the lead at the member's current version" || no "multiagent: $(cat "$FAKE/multiagent" 2>&1)"

# revoke
echo n > "$T/no"; QARGI_TTY_IN=$T/no $DA lead revoke alpha >/dev/null 2>&1; jq -e '.lead.push.cloud == "branches"' "$T/c/projects/alpha.json" >/dev/null && ok "answering no to revoke changes nothing" || no "revoke no"
out=$($DA lead revoke alpha 2>&1)
jq -e '.lead.push.cloud == "none" and (.lead.push | has("vault_id") | not) and .lead.push.local == true' "$T/c/projects/alpha.json" >/dev/null && ok "revoke sets the cloud grant to none and keeps the local one" || no "revoke answers: $out"
[ ! -e "$T/c/credentials/alpha-lead-push" ] && [ ! -f "$FAKE/cred" ] && ok "revoke deletes the token file and archives the credential" || no "revoke cleanup"
grep -q -- "--vault-id \[\]" "$FAKE/dep-update" && ok "revoke detaches the vault from the deployment" || no "detach: $(tail -2 "$FAKE/dep-update")"
echo "$out" | grep -q "revoke the token on GitHub" && ok "revoke reminds you to revoke the token on GitHub itself" || no "reminder"

# --- the lead's context: qargi lead usage | compact-check, the stage lines, the markers the verbs keep (fixture transcripts under the fresh HOME)
RB=$T/beta; S=$QARGI_STATE; export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
git init -q -b master "$RB"; echo 0.1.0 > "$RB/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$RB/CHANGELOG.md"
git -C "$RB" add -A && git -C "$RB" commit -q -m one && git -C "$RB" branch develop && git -C "$RB" checkout -q -b parked
DURING=$T/during.out
jq -n --arg p "$RB" --arg tc "test -f \"$S/busy/beta.verify.lc.pid\" && (cd \"$RB\" && \"$DA\" lead compact-check --project beta > \"$DURING\" 2>&1; true)" \
  '{schema:1, project:"beta", methodology:"gitflow", repo:{url:"https://github.com/acme/beta", path:$p, long_lived:["master","develop"]},
    models:{provider:{local:"claude-code",cloud:"claude-platform"}}, test_command:$tc}' > "$T/c/projects/beta.json"
TD=$HOME/.claude/projects/$(printf '%s' "$(readlink -f "$RB")" | sed 's/[^A-Za-z0-9]/-/g'); mkdir -p "$TD"
printf '%s\n' '{"type":"assistant","isSidechain":false,"message":{"model":"m","usage":{"input_tokens":1,"cache_read_input_tokens":99999,"cache_creation_input_tokens":0}}}' > "$TD/sess1.jsonl"
B() { ( cd "$RB" && "$DA" "$@" ); }
AS=' (window assumed 200,000; set lead.context_window)'   # the fixture's model is not in the runtime's table, so its window is a guess
B lead usage --project beta | grep -qF "context: 100,000 of 200,000 tokens in use (50%)$AS" && ok "lead usage reads the fixture transcript of the checkout" || no "usage: $(B lead usage --project beta 2>&1)"
B lead compact-check --project beta >/dev/null 2>&1 && ok "compact-check: nothing open is safe (exit 0)" || no "compact-check clean"
B feature start lc --project beta >/dev/null 2>&1
task() { git -C "$RB" branch "agent/$1" develop; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$RB" worktree add -q "$w" "agent/$1"; echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$RB" worktree remove --force "$w"; }
run_of() { local d=$T/run-$1; mkdir -p "$d"; printf 'agent/%s %s\n' "$1" "$(git -C "$RB" rev-parse "agent/$1")" > "$d/applied"; : > "$d/verified"
  jq -nc --arg r "$d" --arg s "$1" --arg p "$RB" '{run:$r, slug:$s, ability:"build", base:"feature/lc", started:"1", repo:$p}' >> "$S/local-runs.jsonl"; }
task t1; task t2; run_of t1; run_of t2
out=$(B lead compact-check --project beta 2>&1); rc=$?
[ $rc = 1 ] && grep -q "applied and not merged" <<<"$out" && ok "compact-check: runs applied and not merged are not safe" || no "applied runs: rc=$rc $out"
out=$(B feature merge lc agent/t1 --project beta 2>&1)
grep -q "^lead:" <<<"$out" && no "a stage line after a merge while another run of the feature is open: $out" || ok "feature merge of a run that is not the last prints no stage line"
out=$(B feature merge lc agent/t2 --project beta 2>&1)
grep -qxF "lead: 50%, 100k tokens of context$AS; compact is safe now: run /compact" <<<"$out" && ok "feature merge of the last open run prints the stage line" || no "merge line: $out"
jq '.lead = {compact_advice_pct: 60}' "$T/c/projects/beta.json" > "$T/c/p.tmp" && mv "$T/c/p.tmp" "$T/c/projects/beta.json"
task t3; run_of t3; B feature merge lc agent/t3 --project beta 2>&1 | grep -q "^lead:" && no "the stage line ignored lead.compact_advice_pct" || ok "lead.compact_advice_pct above the usage silences the stage line"
jq 'del(.lead)' "$T/c/projects/beta.json" > "$T/c/p.tmp" && mv "$T/c/p.tmp" "$T/c/projects/beta.json"
B feature verify lc --project beta >/dev/null 2>&1
grep -q "do not compact now" "$DURING" && grep -q "the whole suite is running (verify.lc" "$DURING" && ok "compact-check while feature verify runs: not safe, the busy marker names it" || no "during verify: $(cat "$DURING" 2>&1)"
[ -z "$(ls "$S/busy" 2>/dev/null)" ] && ok "the busy marker is removed when the verify ends" || no "busy left: $(ls "$S/busy")"
tk=$(B feature finish lc --project beta | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
out=$(B feature finish lc --project beta --plan "$tk" --approved go 2>&1)
grep -qxF "lead: 50%, 100k tokens of context$AS; compact is safe now: run /compact" <<<"$out" && ok "feature finish prints the stage line" || no "finish line: $out"
note=$T/note.md
out=$(B marshal handoff --project beta --write "$note" 2>&1)
[ "$(tail -1 <<<"$out")" = "lead: 50%, 100k tokens of context$AS; compact is safe now: run /compact" ] && [ -s "$note" ] && ok "marshal handoff --write ends with the stage line" || no "handoff line: $out"
jq -e --arg f "$note" '.file == $f and (.epoch | type == "number")' "$S/handoff/beta.json" >/dev/null && ok "handoff --write records when and where the note was written" || no "handoff record: $(cat "$S/handoff/beta.json" 2>&1)"
B marshal handoff --project beta 2>"$T/err" | grep -q "^lead:" && no "the stage line is in the note on stdout" || { grep -q "^lead:" "$T/err" && ok "marshal handoff without --write keeps the stage line out of the note (stderr)" || no "no stderr line"; }
B marshal handoff --project beta --json 2>&1 | jq -e . >/dev/null && ok "marshal handoff --json stays pure JSON" || no "handoff json"
jq -nc '{epoch: 1, verb: "feature:merge", project: "beta"}' >> "$S/ref-journal.jsonl"
jq '.epoch = 0' "$S/handoff/beta.json" > "$T/h.tmp" && mv "$T/h.tmp" "$S/handoff/beta.json"
out=$(B lead compact-check --project beta 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the handoff note (written 1970-01-01 00:00:00Z) is older than the last merge" <<<"$out" && ok "compact-check: a handoff note older than the last merge is not safe" || no "stale note: rc=$rc $out"
B lead compact-check --project beta --advise 2>&1 | grep -q "compact advised (50%, 100k tokens of the context), but not safe yet" && ok "compact-check --advise at 50% says advised, not safe yet" || no "advise"
# a release in progress, and its finish
jq 'del(.test_command)' "$T/c/projects/beta.json" > "$T/c/p.tmp" && jq '.test_command = "true"' "$T/c/p.tmp" > "$T/c/projects/beta.json"
git -C "$RB" checkout -q parked 2>/dev/null; rm -f "$S/ref-journal.jsonl"; rm -rf "$S/handoff"
B release verify 0.2.0 --project beta >/dev/null 2>&1; B release start 0.2.0 --project beta --date 2026-01-02 >/dev/null 2>&1
out=$(B lead compact-check --project beta 2>&1); rc=$?
[ $rc = 1 ] && grep -q "a release is in progress (release/0.2.0)" <<<"$out" && ok "compact-check: an open release branch is not safe" || no "release open: rc=$rc $out"
B release verify 0.2.0 --project beta >/dev/null 2>&1
tk=$(B release finish 0.2.0 --project beta | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
out=$(B release finish 0.2.0 --project beta --plan "$tk" --approved go 2>&1)
grep -qxF "lead: 50%, 100k tokens of context$AS; compact is safe now: run /compact" <<<"$out" && ok "release finish prints the stage line" || no "release line: $out"
exit $fail
