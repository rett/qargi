#!/usr/bin/env bash
# Table tests for `qargi project validate|set` (no API). Run: tests/test_project.sh
set -u
cd "$(dirname "$0")/.." || exit 1
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
chk "unknown role"                  1 '.roles.fresh=.roles.dev'
chk "no roles"                      1 '.roles={}'
chk "push by coordinator refused"   1 '.roles.dev.push={mode:"coordinator",branch_pattern:"agent/<slug>"}'
chk "push by agent refused"         1 '.roles.docs.push={mode:"agent",branch_pattern:"docs/<slug>",credential:"vault:vlt_x"}'
chk "bad push mode"                 1 '.roles.dev.push.mode="always"'
chk "bad effort"                    1 '.roles.dev.effort="turbo"'
chk "bad model"                     1 '.roles.dev.model="gpt"'
chk "bad skill"                     1 '.roles.docs.skills=["bash"]'
chk "zero budget"                   1 '.budget_cents=0'
chk "bad store id"                  1 '.memory.memory_store="x"'
chk "empty store ids allowed"       0 '.memory={memory_store:"",reference_store:""}'
echo "$base" > $T/ok.json; $DA project init demo --answers $T/ok.json >/dev/null 2>&1 || { echo "FAIL init"; fail=1; }
$DA project set demo budget_cents 2500 >/dev/null 2>&1 && [ "$(jq .budget_cents $T/c/projects/demo.json)" = 2500 ] && echo "ok   set budget" || { echo "FAIL set budget"; fail=1; }
$DA project set demo roles.dev.effort turbo >/dev/null 2>&1 && { echo "FAIL set invalid accepted"; fail=1; } || echo "ok   set refuses an invalid value"
[ "$(jq -r .roles.dev.effort $T/c/projects/demo.json)" = high ] && echo "ok   refused set changed nothing" || { echo "FAIL set changed the file"; fail=1; }
exit $fail
