#!/usr/bin/env bash
# Table tests for `qargi project validate|set` (no API). Run: tests/test_project.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); export QARGI_CONF=$T/c QARGI_STATE=$T/s
DA=./bin/qargi; fail=0
base=$($DA project template demo | jq '.repo.url="https://github.com/example/demo"')
chk() { # name expected(0|1) jq-filter
  local f=$T/a.json; jq "$3" <<<"$base" > "$f"
  $DA project validate "$f" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1 (exit $rc, wanted $2)"; fail=1; fi
}
chk "valid template"                0 '.'
chk "placeholder repo url"          1 '.repo.url="https://github.com/OWNER/REPO"'
chk "no long-lived branches"        1 '.repo.long_lived=[]'
chk "unknown role"                  1 '.roles.fresh=.roles.build'
chk "a base as a role entry"        0 '.roles.worker=.roles.build | .roles.reviewer=.roles.build'
chk "no roles"                      1 '.roles={}'
chk "push by coordinator refused"   1 '.roles.build.push={mode:"coordinator",branch_pattern:"agent/<slug>"}'
chk "push by agent refused"         1 '.roles.write.push={mode:"agent",branch_pattern:"docs/<slug>",credential:"vault:vlt_x"}'
chk "bad push mode"                 1 '.roles.build.push.mode="always"'
chk "bad effort"                    1 '.roles.build.effort="turbo"'
chk "bad model"                     1 '.roles.build.model="gpt"'
chk "bad skill"                     1 '.roles.write.skills=["bash"]'
chk "zero budget"                   1 '.budget_cents=0'
chk "bad store id"                  1 '.memory.memory_store="x"'
chk "empty store ids allowed"       0 '.memory={memory_store:"",reference_store:""}'
chk "bad memory.tiers key"          1 '.memory.tiers={bogus:{path:"/x"}}'
chk "absolute repo tier path"       1 '.memory.tiers={repo:{path:"/abs/mem"}}'
# profiles: each bad shape is refused with its own message
chkm() { # name jq-filter expected-message-prefix
  local f=$T/a.json out; jq "$2" <<<"$base" > "$f"
  out=$($DA project validate "$f" 2>&1); local rc=$?
  if [ "$rc" != 0 ] && grep -qF -- "$3" <<<"$out"; then echo "ok   $1"; else echo "FAIL $1 (exit $rc, wanted message $3; got: $out)"; fail=1; fi
}
chk  "valid project profile"        0 '.profiles.tiny={base:"reviewer",tier:"fast",model:"haiku",effort:"low",purpose:"small checks",abilities:["review"]}'
chk  "shipped profile, only tier"   0 '.profiles.build={tier:"deep"}'
chk  "profiles absent is fine"      0 'del(.profiles)'
chk  "full model id accepted"       0 '.profiles.tiny={base:"worker",model:"claude-sonnet-5-5"}'
chkm "profile name"                 '.profiles.Bad_Name={base:"worker"}' 'profiles.Bad_Name: '
chkm "profile not an object"        '.profiles.tiny="x"' 'profiles.tiny: '
chkm "project-only needs base"      '.profiles.tiny={tier:"fast"}' 'profiles.tiny.base: '
chkm "unknown base"                 '.profiles.tiny={base:"boss"}' 'profiles.tiny.base: '
chkm "bad tier"                     '.profiles.tiny={base:"worker",tier:"huge"}' 'profiles.tiny.tier: '
chkm "bad model alias"              '.profiles.tiny={base:"worker",model:"gpt"}' 'profiles.tiny.model: '
chkm "bad effort (profile)"         '.profiles.tiny={base:"worker",effort:"turbo"}' 'profiles.tiny.effort: '
chkm "purpose not a string"         '.profiles.tiny={base:"worker",purpose:5}' 'profiles.tiny.purpose: '
chkm "purpose too long"             '.profiles.tiny={base:"worker",purpose:("x"*301)}' 'profiles.tiny.purpose: '
chkm "abilities not a list"         '.profiles.tiny={base:"worker",abilities:"build"}' 'profiles.tiny.abilities: '
chkm "abilities unknown role"       '.profiles.tiny={base:"worker",abilities:["nosuch"]}' 'profiles.tiny.abilities: '
chkm "abilities class conflict"     '.profiles.tiny={base:"worker",abilities:["review"]}' 'profiles.tiny.abilities: review is read-only, but base worker is write'
chkm "unknown profile key"          '.profiles.tiny={base:"worker",colour:"red"}' 'profiles.tiny.colour: '
# models.accept_no_barrier: what `qargi provider accept` records, exactly {by, at, reason} per surface
ACC='{by:"rett",at:"2026-10-31T12:00:00Z",reason:"review on cloud, no barrier, my call"}'
chk  "accept_no_barrier recorded"   0 ".models.accept_no_barrier.cloud=$ACC"
chk  "accept_no_barrier, both"      0 ".models.accept_no_barrier={cloud:$ACC,local:$ACC}"
chk  "models.provider alone is fine" 0 '.models.provider="claude"'
chkm "accept_no_barrier not an object" '.models.accept_no_barrier="yes"' 'models.accept_no_barrier: '
chkm "accept_no_barrier unknown surface" ".models.accept_no_barrier.moon=$ACC" 'models.accept_no_barrier.moon: '
chkm "accept_no_barrier record is a string" '.models.accept_no_barrier.cloud="yes"' 'models.accept_no_barrier.cloud: '
chkm "accept_no_barrier missing reason" '.models.accept_no_barrier.cloud={by:"rett",at:"2026-10-31T12:00:00Z"}' 'models.accept_no_barrier.cloud: '
chkm "accept_no_barrier extra field" ".models.accept_no_barrier.cloud=($ACC + {extra:1})" 'models.accept_no_barrier.cloud: '
chkm "accept_no_barrier empty by"   ".models.accept_no_barrier.cloud=($ACC | .by=\"\")" 'models.accept_no_barrier.cloud.by: '
chkm "accept_no_barrier bad time"   ".models.accept_no_barrier.cloud=($ACC | .at=\"yesterday\")" 'models.accept_no_barrier.cloud.at: '
chkm "accept_no_barrier empty reason" ".models.accept_no_barrier.cloud=($ACC | .reason=\"\")" 'models.accept_no_barrier.cloud.reason: '
echo "$base" > $T/ok.json; $DA project init demo --answers $T/ok.json >/dev/null 2>&1 || { echo "FAIL init"; fail=1; }
$DA project set demo budget_cents 2500 >/dev/null 2>&1 && [ "$(jq .budget_cents $T/c/projects/demo.json)" = 2500 ] && echo "ok   set budget" || { echo "FAIL set budget"; fail=1; }
$DA project set demo roles.build.effort turbo >/dev/null 2>&1 && { echo "FAIL set invalid accepted"; fail=1; } || echo "ok   set refuses an invalid value"
[ "$(jq -r .roles.build.effort $T/c/projects/demo.json)" = high ] && echo "ok   refused set changed nothing" || { echo "FAIL set changed the file"; fail=1; }
exit $fail
