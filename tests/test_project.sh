#!/usr/bin/env bash
# Table tests for `qargi project validate|set` (no API). Run: tests/test_project.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); mkdir -p "$T/h"; export HOME=$T/h QARGI_CONF=$T/c QARGI_STATE=$T/s
DA=./bin/qargi; fail=0; HANDSEAL=$PWD/tests/handseal.py
base=$($DA project template demo | jq '.repo.url="https://github.com/example/demo"')
chk() { # name expected(0|1) jq-filter
  local f=$T/a.json; jq "$3" <<<"$base" > "$f"
  $DA project validate "$f" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1 (exit $rc, wanted $2)"; fail=1; fi
}
chk "valid template"                0 '.'
chk "placeholder repo url"          1 '.repo.url="https://github.com/OWNER/REPO"'
chk "no long-lived branches"        1 '.repo.long_lived=[]'
chk "repo.detached: a branch name"  0 '.repo.detached=["docs-site","site/pages"]'
chk "repo.detached: not a list"     1 '.repo.detached="docs-site"'
chk "repo.detached: a git-flow name" 1 '.repo.detached=["develop"]'
chk "repo.detached: a feature name" 1 '.repo.detached=["feature/docs"]'
chk "repo.detached: a duplicate"    1 '.repo.detached=["docs","docs"]'
chk "repo.detached: a bad name"     1 '.repo.detached=["a b"]'
chk "repo.parking_branch: a name"   0 '.repo.parking_branch="rest"'
chk "repo.parking_branch: develop"  1 '.repo.parking_branch="develop"'
chk "repo.parking_branch: not a string" 1 '.repo.parking_branch=3'
chk "repo.parking_branch: long-lived" 1 '.repo.long_lived=["master","develop","rest"] | .repo.parking_branch="rest"'
chk "repo.parking_branch: detached" 1 '.repo.detached=["rest"] | .repo.parking_branch="rest"'
chk "branches: both keys"           0 '.branches={delete_merged:"local+remote",push_features:"when-shared"}'
chk "branches.delete_merged: bad"   1 '.branches={delete_merged:"remote"}'
chk "branches.push_features: bad"   1 '.branches={push_features:"yes"}'
chk "branches: unknown key"         1 '.branches={keep:true}'
chk "branches: not an object"       1 '.branches="local"'
chk "worktrees.root: absolute"      0 '.worktrees={root:"/tmp/worktrees"}'
chk "worktrees.root: relative"      1 '.worktrees={root:"worktrees"}'
chk "worktrees.root: empty"         1 '.worktrees={root:""}'
chk "worktrees.root: unknown key"   1 '.worktrees={path:"/tmp/x"}'
chk "worktrees.root: in the repo"   1 '.repo.path="/tmp/qrepo" | .worktrees={root:"/tmp/qrepo/wt"}'
chk "packs.none: true"              0 '.packs={none:true}'
chk "packs.none: false"             0 '.packs={none:false}'
chk "packs.none: not a boolean"     1 '.packs={none:"yes"}'
chk "packs: unknown key"            1 '.packs={off:true}'
chk "packs: not an object"          1 '.packs=true'
chk "unknown role"                  1 '.roles.fresh=.roles.build'
chk "a base as a role entry"        0 '.roles.worker=.roles.build | .roles.reviewer=.roles.build'
chk "no roles"                      1 '.roles={}'
chk "push by coordinator refused"   1 '.roles.build.push={mode:"coordinator",branch_pattern:"agent/<slug>"}'
chk "push by agent refused"         1 '.roles.write.push={mode:"agent",branch_pattern:"docs/<slug>",credential:"vault:vlt_x"}'
chk "bad push mode"                 1 '.roles.build.push.mode="always"'
chk "bad effort"                    1 '.roles.build.effort="turbo"'
chk "bad model"                     1 '.models.provider={local:"claude-code",cloud:"claude-platform"} | .roles.build.model="gpt"'
chk "bad skill"                     1 '.roles.write.skills=["bash"]'
chk "zero budget"                   1 '.budget_cents=0'
chk "bad store id"                  1 '.memory.memory_store="x"'
chk "empty store ids allowed"       0 '.memory={memory_store:"",reference_store:""}'
SIGN='{key:"~/.ssh/relkey",namespace:"relsign",files:["dist/release/SHA256SUMS"],verify_command:["make","release-verify"]}'
chk "release signing answers"       0 ".release={sign:$SIGN, assets:[\"dist/release/a.tar.gz\"], notes_file:\"dist/NOTES-{version}.md\"}"
chk "release: unknown key"          1 '.release={sing:{}}'
chk "release.sign: a public key"    1 ".release={sign:($SIGN|.key=\"~/.ssh/relkey.pub\")}"
chk "release.sign: a relative key"  1 ".release={sign:($SIGN|.key=\"relkey\")}"
chk "release.sign: no namespace"    1 ".release={sign:($SIGN|del(.namespace))}"
chk "release.sign: a file outside"  1 ".release={sign:($SIGN|.files=[\"../SHA256SUMS\"])}"
chk "release.sign: absolute file"   1 ".release={sign:($SIGN|.files=[\"/etc/passwd\"])}"
chk "release.sign: verify is text"  1 ".release={sign:($SIGN|.verify_command=\"make release-verify\")}"
chk "release.assets: a label (#)"   1 '.release={assets:["a.tar.gz#label"]}'
chk "release.notes_file: absolute"  1 '.release={notes_file:"/tmp/notes.md"}'
chk "release layout answers"        0 '.release={version_file:"none", changelog:{unreleased:"## {version} (unreleased)", released:"## {version} ({date})"}, man_pages:["docs/acme.1"], test_command:["make","check"], preflight:["make","check-release","{version}"]}'
chk "release.version_file: a path"  0 '.release={version_file:"conf/version.txt"}'
chk "release.version_file: outside" 1 '.release={version_file:"../VERSION"}'
chk "release.changelog: unknown"    1 '.release={changelog:{head:"## x"}}'
chk "release.changelog: not object" 1 '.release={changelog:"## [Unreleased]"}'
chk "changelog.unreleased: no head" 1 '.release={changelog:{unreleased:"Unreleased"}}'
chk "changelog.unreleased: {date}"  1 '.release={changelog:{unreleased:"## Next {date}"}}'
chk "changelog.released: no version" 1 '.release={changelog:{released:"## Released {date}"}}'
chk "changelog.released: other {x}" 1 '.release={changelog:{released:"## {version} {when}"}}'
chk "release.man_pages: not a list" 1 '.release={man_pages:"man/acme.1"}'
chk "release.man_pages: outside"    1 '.release={man_pages:["../acme.1"]}'
chk "release.test_command: a line"  0 '.release={test_command:"make check"}'
chk "release.test_command: empty"   1 '.release={test_command:[]}'
chk "release.test_command: number"  1 '.release={test_command:5}'
chk "release.preflight: text"       1 '.release={preflight:"make check"}'
chk "release.preflight: empty list" 1 '.release={preflight:[]}'
chk "bad memory.tiers key"        1 '.memory.tiers={bogus:{path:"/x"}}'
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
chkm "bad model alias"              '.models.provider={local:"claude-code",cloud:"claude-platform"} | .profiles.tiny={base:"worker",model:"gpt"}' 'profiles.tiny.model: '
chkm "bad effort (profile)"         '.profiles.tiny={base:"worker",effort:"turbo"}' 'profiles.tiny.effort: '
chkm "purpose not a string"         '.profiles.tiny={base:"worker",purpose:5}' 'profiles.tiny.purpose: '
chkm "purpose too long"             '.profiles.tiny={base:"worker",purpose:("x"*301)}' 'profiles.tiny.purpose: '
chkm "abilities not a list"         '.profiles.tiny={base:"worker",abilities:"build"}' 'profiles.tiny.abilities: '
chkm "abilities unknown role"       '.profiles.tiny={base:"worker",abilities:["nosuch"]}' 'profiles.tiny.abilities: '
chkm "abilities class conflict"     '.profiles.tiny={base:"worker",abilities:["review"]}' 'profiles.tiny.abilities: review is read-only, but base worker is write'
chkm "unknown profile key"          '.profiles.tiny={base:"worker",colour:"red"}' 'profiles.tiny.colour: '
# env: the overrides of the detected environment commands (lib/env.py)
chk  "env overrides"                 0 '.env={doctor_command:"make doctor",bootstrap_command:"make bootstrap",dry_run_command:"make -n bootstrap",known_failures:["expected: x"]}'
chkm "env not an object"            '.env="make"' 'env: '
chkm "env unknown key"              '.env={colour:"red"}' 'env.colour: unknown key'
chkm "env command not a string"     '.env={doctor_command:["make"]}' 'env.doctor_command: '
chkm "env command with a newline"   '.env={bootstrap_command:"a\nb"}' 'env.bootstrap_command: '
chkm "env known_failures not a list" '.env={known_failures:"x"}' 'env.known_failures: '
# models.accept_no_barrier: what `qargi provider accept` records, exactly {by, at, reason} per surface
ACC='{by:"rett",at:"2026-10-31T12:00:00Z",reason:"review on cloud, no barrier, my call"}'
chk  "accept_no_barrier recorded"   0 ".models.accept_no_barrier.cloud=$ACC"
chk  "accept_no_barrier, both"      0 ".models.accept_no_barrier={cloud:$ACC,local:$ACC}"
chk  "models.provider alone is fine" 0 '.models.provider={local:"claude-code",cloud:"claude-platform"}'
chkm "accept_no_barrier not an object" '.models.accept_no_barrier="yes"' 'models.accept_no_barrier: '
chkm "accept_no_barrier unknown surface" ".models.accept_no_barrier.moon=$ACC" 'models.accept_no_barrier.moon: '
chkm "accept_no_barrier record is a string" '.models.accept_no_barrier.cloud="yes"' 'models.accept_no_barrier.cloud: '
chkm "accept_no_barrier missing reason" '.models.accept_no_barrier.cloud={by:"rett",at:"2026-10-31T12:00:00Z"}' 'models.accept_no_barrier.cloud: '
chkm "accept_no_barrier extra field" ".models.accept_no_barrier.cloud=($ACC + {extra:1})" 'models.accept_no_barrier.cloud: '
chkm "accept_no_barrier empty by"   ".models.accept_no_barrier.cloud=($ACC | .by=\"\")" 'models.accept_no_barrier.cloud.by: '
chkm "accept_no_barrier bad time"   ".models.accept_no_barrier.cloud=($ACC | .at=\"yesterday\")" 'models.accept_no_barrier.cloud.at: '
chkm "accept_no_barrier empty reason" ".models.accept_no_barrier.cloud=($ACC | .reason=\"\")" 'models.accept_no_barrier.cloud.reason: '
# models.provider: the template has it, empty (there is no default provider); validate reports an empty or missing one as a finding
# line and still exits 0, so storing and every flow after it work as before
jq -e '.models.provider == ""' <<<"$base" >/dev/null && echo "ok   the template has models.provider as an empty string" || { echo "FAIL template models.provider"; fail=1; }
jq -e '.roles | all(.[]; has("model") and .model == null)' <<<"$base" >/dev/null && echo "ok   the template names no model for a role (the provider's tier applies once one is set)" || { echo "FAIL template role models"; fail=1; }
$DA project template demo | grep -qi claude && { echo "FAIL the template names a vendor"; fail=1; } || echo "ok   the template names no vendor"
fnd() { # name jq-filter wanted(yes|no): does validate print the models.provider finding, with exit 0?
  local f=$T/a.json out rc; jq "$2" <<<"$base" > "$f"
  out=$($DA project validate "$f" 2>&1); rc=$?
  local has=no; grep -qx 'finding: models.provider is not set and there is no default provider: qargi project set demo models.provider PROVIDER (qargi provider list)' <<<"$out" && has=yes
  if [ "$rc" = 0 ] && [ "$has" = "$3" ] && { [ "$3" = yes ] || ! grep -q '^finding:' <<<"$out"; }; then echo "ok   $1"
  else echo "FAIL $1 (exit $rc, finding wanted: $3; got: $out)"; fail=1; fi
}
fnd "validate: the template's empty provider is a finding"   '.'                         yes
fnd "validate: no models at all is a finding"                'del(.models)'              yes
fnd "validate: models without a provider is a finding"       '.models={}'                yes
fnd "validate: a blank provider is a finding"                '.models.provider="  "'     yes
fnd "validate: a provider that is not a string is a finding" '.models.provider=3'        yes
fnd "validate: a provider named is no finding"               '.models.provider={local:"claude-code",cloud:"claude-platform"}' no
# a pack linked to a role of the project that the library does not hold is a WARN line; validate still exits 0
mkdir -p "$T/c/packs/skills/present" "$T/c/packs/tools"
jq -n '{links:[{pack:"skill:present",scope:"user"},{pack:"skill:gone",scope:"project",project:"demo"},{pack:"tool:lost",scope:"project-role",project:"demo",role:"write"},
  {pack:"skill:other",scope:"project",project:"elsewhere"},{pack:"skill:norole",scope:"user-role",role:"fresh"},{pack:"skill:gone-all",scope:"user"}]}' > "$T/c/packs/links.json"
jq '.models.provider={local:"claude-code",cloud:"claude-platform"}' <<<"$base" > "$T/a.json"
out=$($DA project validate "$T/a.json" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -qE '^WARN: skill:gone is linked to .*build.* of demo but is not in the pack library' <<<"$out" && grep -qE '^WARN: tool:lost is linked to write of demo ' <<<"$out" \
  && grep -qE '^WARN: skill:gone-all is linked to ' <<<"$out" && [ "$(grep -c '^WARN:' <<<"$out")" = 3 ] && grep -qx ok <<<"$out"; } \
  && echo "ok   validate warns of a linked pack the library does not hold (once per pack, with its roles) and still exits 0" || { echo "FAIL pack WARN (exit $rc): $out"; fail=1; }
mkdir -p "$T/c/packs/skills/gone" "$T/c/packs/skills/gone-all"; echo '{}' > "$T/c/packs/tools/lost.json"
out=$($DA project validate "$T/a.json" 2>&1); [ "$?" = 0 ] && ! grep -q '^WARN:' <<<"$out" && echo "ok   with the packs in the library the warnings are gone" || { echo "FAIL pack WARN gone: $out"; fail=1; }
rm -rf "$T/c/packs"
echo "$base" > $T/ok.json; $DA project init demo --answers $T/ok.json >/dev/null 2>&1 || { echo "FAIL init"; fail=1; }
out=$($DA project init demo --answers $T/ok.json --force 2>&1); grep -q '^finding: models.provider is not set' <<<"$out" && echo "ok   init tells that no provider is set" || { echo "FAIL init finding: $out"; fail=1; }
grep -q 'role build: .*, provider tier/high' <<<"$out" && echo "ok   init says a role without a model takes its provider's tier" || { echo "FAIL init role line: $out"; fail=1; }
out=$($DA project validate demo 2>&1); [ "$?" = 0 ] && grep -q '^finding: models.provider is not set' <<<"$out" && echo "ok   validate NAME reads the stored answers and reports the finding" || { echo "FAIL validate NAME: $out"; fail=1; }
$DA project set demo models.provider.local claude-code >/dev/null 2>&1 && $DA project set demo models.provider.cloud claude-platform >/dev/null 2>&1 && out=$($DA project validate demo 2>&1) && ! grep -q '^finding:' <<<"$out" && echo "ok   project set models.provider clears the finding" || { echo "FAIL set provider: $out"; fail=1; }
$DA project set demo budget_cents 2500 >/dev/null 2>&1 && [ "$(jq .budget_cents $T/c/projects/demo.json)" = 2500 ] && echo "ok   set budget" || { echo "FAIL set budget"; fail=1; }
# the message follows the key: the provision note belongs to answers a provision reads; a deployment option of the methodology
# (github-release, none) is not one, so only what was set is said; a deployment value that is no option keeps the note
msg=$($DA project set demo budget_cents 2600 2>&1); grep -q "applies to the next provision" <<<"$msg" && echo "ok   set budget_cents keeps the provision note" || { echo "FAIL set budget note: $msg"; fail=1; }
for v in github-release none; do
  msg=$($DA project set demo deployment "$v" 2>&1); [ "$msg" = "demo: deployment = \"$v\"" ] && echo "ok   set deployment $v says only what was set" || { echo "FAIL set deployment $v: $msg"; fail=1; }
done
msg=$($DA project set demo deployment dep_0123 2>&1); grep -q "applies to the next provision" <<<"$msg" && echo "ok   set deployment to a cloud deployment keeps the provision note" || { echo "FAIL set cloud deployment note: $msg"; fail=1; }
$DA project set demo roles.build.effort turbo >/dev/null 2>&1 && { echo "FAIL set invalid accepted"; fail=1; } || echo "ok   set refuses an invalid value"
[ "$(jq -r .roles.build.effort $T/c/projects/demo.json)" = high ] && echo "ok   refused set changed nothing" || { echo "FAIL set changed the file"; fail=1; }
# marshal.lease_minutes is a project answer; the backend switch is not (it is set with a plan and an audit line by the marshal verbs)
$DA project set demo marshal.lease_minutes 20 >/dev/null 2>&1 && [ "$(jq .marshal.lease_minutes $T/c/projects/demo.json)" = 20 ] && echo "ok   set marshal.lease_minutes" || { echo "FAIL set marshal.lease_minutes"; fail=1; }
for bad in 0 -3 1441 abc 2.5 '"15"'; do
  $DA project set demo marshal.lease_minutes "$bad" >/dev/null 2>&1 && { echo "FAIL set marshal.lease_minutes $bad accepted"; fail=1; } || echo "ok   set refuses marshal.lease_minutes $bad"
done
[ "$(jq .marshal.lease_minutes $T/c/projects/demo.json)" = 20 ] && echo "ok   refused lease values changed nothing" || { echo "FAIL a refused lease value changed the file"; fail=1; }
cp $T/c/projects/demo.json $T/before.json
for k in marshal.backend marshal.lease_minutes.x marshal; do
  v=refs; [ "$k" = marshal ] && v='{"backend":"refs"}'
  msg=$($DA project set demo "$k" "$v" 2>&1) && { echo "FAIL set $k accepted"; fail=1; } || { grep -q "marshal enable" <<<"$msg" && cmp -s $T/before.json $T/c/projects/demo.json && echo "ok   set refuses $k and points to the marshal verbs" || { echo "FAIL set $k: $msg"; fail=1; }; }
done
# models.extensions and models.accept_no_barrier.* take a plan token and an approval through provider enable and provider accept: project set is not a way around them
cp $T/c/projects/demo.json $T/before.json
for kv in 'models.extensions|["x"]|provider enable' 'models.extensions.0|"x"|provider enable' 'models.accept_no_barrier.local|{"by":"a","at":"t","reason":"r"}|provider accept' \
          'models.accept_no_barrier|{"local":{"by":"a","at":"t","reason":"r"}}|provider accept' 'models|{"extensions":["x"]}|provider enable' 'models|{"accept_no_barrier":{}}|provider accept'; do
  IFS='|' read -r k v want <<<"$kv"
  msg=$($DA project set demo "$k" "$v" 2>&1); rc=$?
  { [ $rc = 2 ] && grep -q "qargi $want" <<<"$msg" && cmp -s $T/before.json $T/c/projects/demo.json; } && echo "ok   set refuses $k ($v) with exit 2 and points to qargi $want" || { echo "FAIL set $k $v (rc=$rc): $msg"; fail=1; }
done
$DA project set demo models.provider.local claude-code >/dev/null 2>&1 && [ "$(jq -r .models.provider.local $T/c/projects/demo.json)" = claude-code ] && echo "ok   set still takes models.provider.local" || { echo "FAIL set models.provider.local"; fail=1; }
# no environment variable opens project set to the gated keys: QARGI_GATED_STORE was one, honoured from any caller, and is gone
cp $T/c/projects/demo.json $T/before.json
for k in models.extensions models.accept_no_barrier.local; do
  v='["x"]'; [ "$k" = models.accept_no_barrier.local ] && v='{"by":"a","at":"2026-11-02T00:00:00Z","reason":"r"}'
  for how in qargi script; do
    if [ $how = qargi ]; then msg=$(QARGI_GATED_STORE=1 $DA project set demo "$k" "$v" 2>&1); else msg=$(QARGI_GATED_STORE=1 lib/project.sh set demo "$k" "$v" 2>&1); fi; rc=$?
    { [ $rc != 0 ] && cmp -s $T/before.json $T/c/projects/demo.json; } && echo "ok   QARGI_GATED_STORE=1 opens nothing: $how project set $k is refused" || { echo "FAIL QARGI_GATED_STORE=1 $how project set $k (rc=$rc): $msg"; fail=1; }
  done
done
# the store the gated verbs use (provider enable|disable|accept) takes only those two keys, and only what the answers' own validation accepts
GA="python3 -I lib/gated_answers.py"; cp $T/c/projects/demo.json $T/before.json
for kv in 'budget_cents|5' 'models.provider.local|"claude"' 'models|{}' 'roles.build.effort|"low"' 'models.accept_no_barrier.moon|{"by":"a","at":"2026-11-02T00:00:00Z","reason":"r"}' \
          'models.accept_no_barrier.local|{"by":"a"}'; do
  IFS='|' read -r k v <<<"$kv"
  msg=$($GA store demo "$k" "$v" 2>&1); rc=$?
  { [ $rc != 0 ] && cmp -s $T/before.json $T/c/projects/demo.json; } && echo "ok   gated_answers stores nothing for $k=$v" || { echo "FAIL gated_answers $k=$v (rc=$rc): $msg"; fail=1; }
done
$GA store demo models.extensions '["x"]' >/dev/null 2>&1 && [ "$(jq -c .models.extensions $T/c/projects/demo.json)" = '["x"]' ] && [ "$(stat -c %a $T/c/projects/demo.json)" = 600 ] \
  && echo "ok   gated_answers stores models.extensions" || { echo "FAIL gated_answers models.extensions"; fail=1; }
cp $T/before.json $T/c/projects/demo.json
# project init writes the whole answers file, so it is a route to the same keys: a file that carries models.extensions or models.accept_no_barrier is
# refused when it would add or change them (a fresh init: when it has them at all); the file is stored only if it leaves them as they are
GATEKEYS='.models.extensions=["x"]|.models.accept_no_barrier={local:{by:"a",at:"2026-11-02T00:00:00Z",reason:"r"}}'
for f in '.models.extensions=["x"]' '.models.accept_no_barrier={local:{by:"a",at:"2026-11-02T00:00:00Z",reason:"r"}}'; do
  jq "$f | .project=\"fresh\"" <<<"$base" > $T/g.json
  msg=$($DA project init fresh --answers $T/g.json 2>&1); rc=$?
  { [ $rc != 0 ] && [ ! -e $T/c/projects/fresh.json ] && grep -q "qargi provider" <<<"$msg"; } && echo "ok   init of a new project refuses $f and names the verbs" || { echo "FAIL fresh init $f (rc=$rc): $msg"; fail=1; }
done
jq '.models.extensions=[] | .models.accept_no_barrier={} | .project="fresh"' <<<"$base" > $T/g.json
$DA project init fresh --answers $T/g.json >/dev/null 2>&1 && echo "ok   init takes empty gated keys (a project whose extensions were all disabled)" || { echo "FAIL init refused empty gated keys"; fail=1; }
rm -f $T/c/projects/fresh.json
cp $T/c/projects/demo.json $T/before.json
for f in '.models.extensions=["x"]' '.models.accept_no_barrier={local:{by:"a",at:"2026-11-02T00:00:00Z",reason:"r"}}'; do
  jq "$f | .project=\"demo\"" <<<"$base" > $T/g.json
  msg=$($DA project init demo --answers $T/g.json --force 2>&1); rc=$?
  { [ $rc != 0 ] && cmp -s $T/before.json $T/c/projects/demo.json && grep -q "qargi provider" <<<"$msg"; } && echo "ok   init --force refuses to add $f" || { echo "FAIL init --force $f (rc=$rc): $msg"; fail=1; }
done
# once the stored answers hold them (a gated verb put them there), a file that keeps them as they are is fine, one that adds or changes an entry is not, and one that drops an entry is (that only narrows trust)
jq "$GATEKEYS" $T/c/projects/demo.json > $T/g.json && mv $T/g.json $T/c/projects/demo.json; cp $T/c/projects/demo.json $T/before.json
jq '.budget_cents = 777' $T/before.json > $T/g.json
$DA project init demo --answers $T/g.json --force >/dev/null 2>&1 && [ "$(jq .budget_cents $T/c/projects/demo.json)" = 777 ] && [ "$(jq -c .models.extensions $T/c/projects/demo.json)" = '["x"]' ] \
  && echo "ok   init --force with the gated keys unchanged stores the rest" || { echo "FAIL init --force with the gated keys unchanged"; fail=1; }
cp $T/c/projects/demo.json $T/before.json
for f in '.models.extensions=["x","y"]' '.models.accept_no_barrier.local.reason="other"'; do
  jq "$f" $T/before.json > $T/g.json
  msg=$($DA project init demo --answers $T/g.json --force 2>&1); rc=$?
  { [ $rc != 0 ] && cmp -s $T/before.json $T/c/projects/demo.json; } && echo "ok   init --force refuses to change the stored keys ($f)" || { echo "FAIL init --force $f (rc=$rc): $msg"; fail=1; }
done
# dropping a stored entry only narrows trust, so a file may do it
for f in 'del(.models.extensions)' 'del(.models.accept_no_barrier)'; do
  jq "$f" $T/before.json > $T/g.json
  $DA project init demo --answers $T/g.json --force >/dev/null 2>&1 && [ "$(jq -c "$(sed 's/^del(\(.*\))$/\1/' <<<"$f")" $T/c/projects/demo.json)" = null ] \
    && echo "ok   init --force may drop a stored gated key ($f)" || { echo "FAIL init --force $f was not stored"; fail=1; }
  cp $T/before.json $T/c/projects/demo.json
done
# attach --force keeps the stored keys as they are (it replaces only what it detects)
AF=$T/afrepo; git init -q -b main "$AF"; echo x > "$AF/README"; git -C "$AF" -c user.name=t -c user.email=t@example.net add -A; git -C "$AF" -c user.name=t -c user.email=t@example.net commit -q -m one
out=$($DA project attach "$AF" --name afp --url https://github.com/example/afp 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA project attach "$AF" --name afp --url https://github.com/example/afp --plan "$tok" --approved go >/dev/null 2>&1
jq "$GATEKEYS" $T/c/projects/afp.json > $T/g.json && mv $T/g.json $T/c/projects/afp.json; cp $T/c/projects/afp.json $T/before.json
out=$($DA project attach "$AF" --name afp --url https://github.com/example/afp --force 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA project attach "$AF" --name afp --url https://github.com/example/afp --force --plan "$tok" --approved go >/dev/null 2>&1
{ [ "$(jq -c .models.extensions $T/c/projects/afp.json)" = '["x"]' ] && [ "$(jq -c .models.accept_no_barrier $T/c/projects/afp.json)" = "$(jq -c .models.accept_no_barrier $T/before.json)" ]; } \
  && echo "ok   attach --force keeps the stored gated keys as they are" || { echo "FAIL attach --force changed the gated keys"; fail=1; }
# attach does not guess a provider and stores none; it says so, in the plan and after storing, and the stored answers still validate
AR=$T/arepo; git init -q -b main "$AR"; echo x > "$AR/README"; git -C "$AR" -c user.name=t -c user.email=t@example.net add -A
git -C "$AR" -c user.name=t -c user.email=t@example.net commit -q -m one
out=$($DA project attach "$AR" --name provless --url https://github.com/example/provless 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
grep -q '^finding: models.provider is not set and there is no default provider: qargi project set provless models.provider PROVIDER' <<<"$out" && echo "ok   the attach plan says no provider is set" || { echo "FAIL attach plan finding: $out"; fail=1; }
out=$($DA project attach "$AR" --name provless --url https://github.com/example/provless --plan "$tok" --approved go 2>&1)
grep -q '^finding: models.provider is not set' <<<"$out" && [ "$(jq -r '.models.provider // "none"' $T/c/projects/provless.json)" = none ] && echo "ok   attach stores no models.provider and says so" || { echo "FAIL attach stores a provider: $out"; fail=1; }
$DA project validate provless >/dev/null 2>&1 && echo "ok   the stored answers of an attached project validate" || { echo "FAIL attached project does not validate"; fail=1; }
# the hint about a repository's own skills names the provider's directory, and every provider's while the project has none
TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$PWD" "$TOOL"
# shellcheck source=fakeprov.sh
. "$PWD/tests/fakeprov.sh"
fake_runtime "$PWD" "$TOOL" agentx local '.adapter = null | .resources.skills.project_dir = ".agent/skills" | .session.render_target = "agentx-render"'
FX=$TOOL/bin/qargi
HR=$T/hrepo; git init -q -b main "$HR"; echo x > "$HR/README"; git -C "$HR" -c user.name=t -c user.email=t@example.net add -A; git -C "$HR" -c user.name=t -c user.email=t@example.net commit -q -m one
mkdir -p "$HR/.agent/skills/one" "$HR/.claude/skills/two"; echo x > "$HR/.agent/skills/one/SKILL.md"; echo x > "$HR/.claude/skills/two/SKILL.md"
out=$($FX project attach "$HR" --name hintp --url https://github.com/example/hintp 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
grep -qx "repo has its own .agent/skills (1 skill): qargi packs link hintp offers to use the library's instead and shows which are new" <<<"$out" && grep -qx "repo has its own .claude/skills (1 skill): qargi packs link hintp offers to use the library's instead and shows which are new" <<<"$out" \
  && echo "ok   no provider yet: the hint is given for the skills directory of every provider" || { echo "FAIL hint for every provider: $out"; fail=1; }
$FX project attach "$HR" --name hintp --url https://github.com/example/hintp --plan "$tok" --approved go >/dev/null 2>&1; $FX project set hintp models.provider agentx >/dev/null 2>&1
out=$($FX project attach "$HR" --name hintp 2>&1)
grep -qx "repo has its own .agent/skills (1 skill): qargi packs link hintp offers to use the library's instead and shows which are new" <<<"$out" && ! grep -q "repo has its own .claude/skills" <<<"$out" \
  && echo "ok   a project with a provider: the hint names that provider's skills directory only" || { echo "FAIL hint for the provider: $out"; fail=1; }

# --- project link | unlink: skills, agents and memory, linked from ~/.qargi into the checkout and the runtime's memory directory
# One plan and one token for the lot; a worktree gets its links by running the verb inside it; nothing records the worktrees. A member's run
# never applies, so work from the temporary directory (this test may itself run in one).
DA=$PWD/bin/qargi
cd "$T" || exit 1
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
G="git -c user.name=t -c user.email=t@example.net"
tokp() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
snap() { find "$@" \( -type l -printf 'L %p -> %l\n' \) -o \( -type f -printf 'F %p\n' \) -o \( -type d -printf 'D %p\n' \) 2>/dev/null | sort | sha256sum
         find "$@" -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum | sha256sum; }
# a runtime defined by data alone: agents as TOML files linked one by one (entry-symlinks), memory in a directory named by a hash of the checkout
LIB=$T/c/packs/providers/fakelink; mkdir -p "$LIB"
jq -n '{schema:2, kind:"provider", provider:"fakelink", family:null, surface:"local",
  models:{pattern:"^fake-[a-z0-9.-]+$", tiers:{"*":{model:"fake-m", alias:null, verified_on:null, source:"test"}}, effort:{low:"l", medium:"m", high:"h", xhigh:null, max:null}},
  resources:{agents:{project_dir:".fake/agents", user_dir:"~/.fake/agents", items:"file-per-item", ext:".toml", link:{project:"entry-symlinks", user:"none"}},
             memory:{user_dir:"~/.fake/mem/{checkout_key}", checkout_key:"sha256-16", link:{user:"dir-symlink"}}},
  agents:{reserved_names:["fake-builtin"]},
  renderers:{agent:{engine:"map", format:"toml", path:"{name}.toml", fields:[
    {from:"name", to:"name", refuse_if_missing:true}, {from:"description", to:"description"},
    {from:"model", to:"model", refuse_if_missing:true}, {from:"effort", to:"effort", resolve:"effort"},
    {from:"tools", to:"tools", tool_map:{shell:"sh", read:"cat", edit:"ed", write:"tee"}}, {from:"class", to:"mode"},
    {from:"body", to:"prompt"}]}},
  dispatch:{mode:"in-session"}, barrier:{kind:"none"}}' > "$LIB/definition.json"
python3 -I "$HANDSEAL" "$LIB"                             # a library pack counts only once sealed
LR=$T/lrepo; git init -q -b main "$LR"; echo x > "$LR/README"; $G -C "$LR" add -A; $G -C "$LR" commit -q -m one
lproj() { jq -n --arg p "$1" --arg r "$2" --arg v "$3" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:$r,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:$v},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
lproj lp "$LR" fakelink
LM=$HOME/.qargi/memory/projects/lp; mkdir -p "$LM"; echo note > "$LM/a.md"
key() { python3 -c 'import hashlib,sys;print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])' "$1"; }
LD=$HOME/.fake/mem/$(key "$LR")                                 # where the runtime reads the memory of the checkout
MD=$T/s/render/lp/fakelink.agents                               # the member render: beside the runtime's render, which a packs render replaces whole
lgo() { local v=$1 p=$2 tok; shift 2; tok=$($DA project "$v" "$p" "$@" | tokp); [ -n "$tok" ] && $DA project "$v" "$p" "$@" --plan "$tok" --approved test; }

# the plan names every link, prints one token and writes nothing; no member is rendered yet, so agents is skipped and says why
before=$(snap "$T/s" "$HOME/.qargi" "$LR/.fake" "$HOME/.fake")
out=$($DA project link lp 2>&1); tok=$(tokp <<<"$out")
{ [ -n "$tok" ] && grep -q "== memory (dir-symlink)" <<<"$out" && grep -q "link:   $LD" <<<"$out" && grep -q "target: $LM" <<<"$out" && grep -q "^agents: not linked, no member of lp is rendered" <<<"$out" \
  && [ "$before" = "$(snap "$T/s" "$HOME/.qargi" "$LR/.fake" "$HOME/.fake")" ]; } && ok "project link: the plan names the link, prints a token and writes nothing; agents with no member yet is skipped with the reason" || no "plan: $out"
$DA project link lp --resource agents >/dev/null 2>&1; [ $? = 1 ] && ok "project link: a resource named whose source does not exist is refused" || no "named agents without members"
$DA project link lp --resource skills >/dev/null 2>&1; [ $? = 3 ] && ok "project link: a resource the runtime does not link is exit 3 when named" || no "named skills: $?"
$DA project link lp --resource bogus >/dev/null 2>&1 && no "a bogus resource was accepted" || ok "project link: --resource takes skills, agents, memory only"
$DA project link lp --approved x >/dev/null 2>&1 && no "applied without the plan token" || ok "project link: apply refuses without the plan token"
$DA project link lp --plan 000000000000 --approved x >/dev/null 2>&1 && no "applied with a wrong token" || ok "project link: apply refuses a wrong token"
[ ! -e "$LD" ] && ok "project link: a refused apply changes nothing" || no "refused apply linked"

# agents: a member of the project is rendered into the member render, and linking puts one link per member in the checkout
out=$($DA agent add smith --roles build --project lp 2>&1)
{ [ -f "$MD/smith.toml" ] && [ ! -e "$LR/.fake" ] && grep -q "project link lp --resource agents" <<<"$out"; } && ok "agent add --project: the file goes to the member render, not the checkout, and the note names the link verb" || no "agent add: $out $(ls -A "$LR")"
jq -e --arg f "$MD/smith.toml" '.projects.lp.smith | .file == $f and has("project") == false' "$T/c/agents.json" >/dev/null && ok "and the record says so" || no "record"
mkdir -p "$LR/.fake/agents"; echo mine > "$LR/.fake/agents/own.toml"                  # the user's own agent beside it
out=$(lgo link lp 2>&1)
{ [ -L "$LR/.fake/agents/smith.toml" ] && [ "$(readlink "$LR/.fake/agents/smith.toml")" = "$MD/smith.toml" ] && [ -f "$LR/.fake/agents/own.toml" ] && [ ! -L "$LR/.fake/agents/own.toml" ] \
  && [ -L "$LD" ] && [ "$(readlink "$LD")" = "$LM" ] && [ "$(cat "$LD/a.md")" = note ]; } && ok "project link: agents (entry-symlinks) beside the user's own file, and memory, in one apply" || no "link: $out"
tail -1 "$T/s/audit.log" | jq -e '.verb=="project:link" and .approved=="test"' >/dev/null && ok "project link is audit-logged" || no "audit: $(tail -1 "$T/s/audit.log")"
out=$($DA project link lp 2>&1); { grep -q "already linked: $LD" <<<"$out" && grep -q "already linked: $LR/.fake/agents -> $MD" <<<"$out" && [ -z "$(tokp <<<"$out")" ]; } && ok "project link: when everything is linked there is no plan to approve" || no "relink: $out"
# a member added later is picked up by the next link, and one removed is dropped
$DA agent add anvil --roles test --project lp >/dev/null 2>&1; lgo link lp >/dev/null 2>&1
[ -L "$LR/.fake/agents/anvil.toml" ] && ok "project link: a member added later is linked by the next run" || no "second member"
$DA agent remove anvil >/dev/null 2>&1; lgo link lp >/dev/null 2>&1
[ ! -e "$LR/.fake/agents/anvil.toml" ] && [ ! -L "$LR/.fake/agents/anvil.toml" ] && [ -L "$LR/.fake/agents/smith.toml" ] && ok "project link: a removed member's link is dropped, the others stay" || no "stale link: $(ls -la "$LR/.fake/agents")"
# unlink: only what was linked, and the checkout is as it was
out=$(lgo unlink lp 2>&1)
{ [ ! -e "$LD" ] && [ ! -L "$LD" ] && [ ! -L "$LR/.fake/agents/smith.toml" ] && [ -f "$LR/.fake/agents/own.toml" ] && [ -f "$MD/smith.toml" ] && [ -f "$LM/a.md" ]; } && ok "project unlink: the links go, the user's own file, the member render and the memory stay" || no "unlink: $out"
$DA project unlink lp >/dev/null 2>&1 && no "unlink with nothing linked succeeded" || ok "project unlink: nothing linked is refused"

# a real directory where the memory link goes is moved to a backup, and unlink puts it back
mkdir -p "$LD"; echo mine > "$LD/MEMORY.md"
out=$($DA project link lp --resource memory 2>&1)
grep -q "apply moves the directory to $LD.qargi-backup" <<<"$out" && ok "backup: the plan says a real memory directory is moved, not deleted" || no "backup plan: $out"
lgo link lp --resource memory >/dev/null 2>&1
{ [ -L "$LD" ] && [ "$(cat "$LD.qargi-backup/MEMORY.md")" = mine ]; } && ok "backup: the real directory is now $LD.qargi-backup, whole" || no "backup apply"
lgo unlink lp --resource memory >/dev/null 2>&1
{ [ -d "$LD" ] && [ ! -L "$LD" ] && [ "$(cat "$LD/MEMORY.md")" = mine ] && [ ! -e "$LD.qargi-backup" ]; } && ok "backup: unlink restores it" || no "backup restore"
rm -rf "$LD"

# a link that is not ours is refused, in every resource, and nothing is changed
mkdir -p "$T/elsewhere" "$(dirname "$LD")"; ln -s "$T/elsewhere" "$LD"
before=$(snap "$LR/.fake" "$(dirname "$LD")")
out=$($DA project link lp --resource memory 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "is a symbolic link to $T/elsewhere, not to this project's memory; refusing to replace it" <<<"$out" && [ "$(readlink "$LD")" = "$T/elsewhere" ]; } && ok "foreign link: a memory directory that links elsewhere is refused" || no "foreign memory: rc=$rc $out"
rm -f "$LD"
ln -s "$T/elsewhere" "$LR/.fake/agents/smith.toml"
out=$($DA project link lp --resource agents 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "is a symbolic link to $T/elsewhere, not into" <<<"$out" && [ "$(readlink "$LR/.fake/agents/smith.toml")" = "$T/elsewhere" ]; } && ok "foreign link: an agent entry that links elsewhere is refused" || no "foreign agent: rc=$rc $out"
$DA project unlink lp --resource agents >/dev/null 2>&1 && no "unlinked what is not ours" || ok "foreign link: unlink does not touch it either"
rm -f "$LR/.fake/agents/smith.toml"
# a symbolic link in the parents of the memory link is refused (the link would land somewhere else)
rm -rf "$HOME/.fake"; mkdir -p "$T/real-fake"; ln -s "$T/real-fake" "$HOME/.fake"
out=$($DA project link lp --resource memory 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "$HOME/.fake is a symbolic link; refusing" <<<"$out" && [ -z "$(ls -A "$T/real-fake")" ]; } && ok "a symbolic link above the memory link is refused and nothing is written through it" || no "parent link: rc=$rc $out"
rm -f "$HOME/.fake"

# the project memory must lie in the memory root by its real path: a link below the root that leads outside it is outside
mkdir -p "$T/mem-outside"; echo n > "$T/mem-outside/n.md"; ln -s "$T/mem-outside" "$HOME/.qargi/memory/vialink"
jq --arg p "$HOME/.qargi/memory/vialink" '.memory.tiers = {project:{path:$p}}' "$T/c/projects/lp.json" > "$T/lp.tmp" && cp "$T/lp.tmp" "$T/c/projects/lp.json"
out=$($DA project link lp --resource memory 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "is placed at" <<<"$out" && grep -q "outside" <<<"$out" && [ ! -e "$LD" ] && [ ! -L "$LD" ]; } && ok "a project memory path that is a link out of the memory root is refused as outside it" || no "memory via link: rc=$rc $out"
rm -f "$HOME/.qargi/memory/vialink" "$T/lp.tmp"; rm -rf "$T/mem-outside"; lproj lp "$LR" fakelink

# a worktree gets its links by running the verb inside it; nothing lists worktrees
$DA project link lp --resource memory,agents --plan "$($DA project link lp --resource memory,agents | tokp)" --approved test >/dev/null 2>&1
WT=$T/lwt; $G -C "$LR" worktree add -q "$WT" -b side
WD=$HOME/.fake/mem/$(key "$(realpath "$WT")")
before_main=$(snap "$LR/.fake" "$LD")
out=$(cd "$WT" && lgo link lp 2>&1)
{ [ -L "$WD" ] && [ "$(readlink "$WD")" = "$LM" ] && [ -L "$WT/.fake/agents/smith.toml" ] && [ "$before_main" = "$(snap "$LR/.fake" "$LD")" ]; } && ok "worktree: run inside it, the links land in that worktree (and its memory key) and the main checkout is untouched" || no "worktree link: $out"
! grep -rIl "$WT" "$T/s" "$T/c" 2>/dev/null | grep -q . && ok "worktree: no stored file names the worktree (the links are the record)" || no "a stored file names the worktree: $(grep -rIl "$WT" "$T/s" "$T/c" | head -3)"
out=$(cd "$WT" && $DA project link lp 2>&1); grep -q "already linked: $WD" <<<"$out" && ok "worktree: its own status is its own links" || no "worktree status: $out"
(cd "$WT" && lgo unlink lp >/dev/null 2>&1)
{ [ ! -e "$WD" ] && [ ! -L "$WT/.fake/agents/smith.toml" ] && [ -L "$LD" ] && [ -L "$LR/.fake/agents/smith.toml" ]; } && ok "worktree: unlink inside it removes only its links" || no "worktree unlink"
lgo unlink lp >/dev/null 2>&1
$G -C "$LR" worktree remove --force "$WT" 2>/dev/null

# a member's run never applies
RUN=$T/memberrun; mkdir -p "$RUN/clone"; : > "$RUN/ability"; : > "$RUN/refs.before"
tok=$($DA project link lp --resource memory | tokp)
out=$(cd "$RUN/clone" && $DA project link lp --resource memory --plan "$tok" --approved test 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "not available in a member run" <<<"$out" && [ ! -e "$LD" ] && [ ! -L "$LD" ]; } && ok "a member's run never applies project link" || no "member run: rc=$rc $out"

# an extension the project enabled is part of the definition project link reads: fakelink has no skills; an extension pack of the library gives
# it the skills resource, which is linked once the project enabled it and the extension has been checked (its skills capability is verified)
SX=$T/ext/skext; mkdir -p "$SX"
jq -n '{schema:2,kind:"extension",extension:"skext",description:"gives fakelink skills",extends:"fakelink",provides:["skills"],
  adds:{capabilities:{skills:{value:"yes",note:"n"}},resources:{skills:{project_dir:".fake/skills",items:"dir-per-item",entry:"SKILL.md",format:"skill-md",link:{project:"dir-symlink",user:"none"}}}}}' > "$SX/definition.json"
xt=$($DA provider import "$SX" | tokp); $DA provider import "$SX" --plan "$xt" --approved test >/dev/null 2>&1 || no "could not import the skills extension"
SRD=$T/s/render/lp/fakelink/.fake/skills; mkdir -p "$SRD/s1"; echo s > "$SRD/s1/SKILL.md"; SLD=$LR/.fake/skills
$DA project link lp --resource skills >/dev/null 2>&1; [ $? = 3 ] && ok "extension: a project that did not enable it still has no skills link (exit 3)" || no "skills before enabling: $?"
jq '.models.extensions = ["skext"]' "$T/c/projects/lp.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/lp.json"
$DA project link lp --resource skills >/dev/null 2>&1; [ $? = 3 ] && ok "extension: enabled but not checked, its skills capability is unverified and counts as no (exit 3)" || no "skills unverified: $?"
$DA provider check skext --project lp >/dev/null 2>&1 || no "check of the skills extension"
out=$($DA project link lp --resource skills 2>&1); xtok=$(tokp <<<"$out")
{ [ -n "$xtok" ] && grep -q "link:   $SLD" <<<"$out" && grep -q "target: $SRD" <<<"$out" && [ ! -e "$SLD" ]; } && ok "extension: verified, the plan links the checkout's skills directory to the render (from the composed resources)" || no "skills plan: $out"
out=$($DA project link lp --resource skills --plan "$xtok" --approved test 2>&1)
{ [ -L "$SLD" ] && [ "$(readlink "$SLD")" = "$SRD" ] && [ -f "$SLD/s1/SKILL.md" ]; } && ok "extension: and apply makes the link" || no "skills apply: $out"
lgo unlink lp --resource skills >/dev/null 2>&1; [ ! -e "$SLD" ] && [ -f "$SRD/s1/SKILL.md" ] && ok "extension: unlink drops the link and keeps the render" || no "skills unlink"
jq 'del(.models.extensions)' "$T/c/projects/lp.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/lp.json"

# the real runtime: skills (dir-symlink) and memory in one plan; agents are not linked by Claude Code's definition, so they are skipped
CR=$T/crepo; git init -q -b main "$CR"; echo x > "$CR/README"; $G -C "$CR" add -A; $G -C "$CR" commit -q -m one
lproj lc "$CR" claude-code
CM=$HOME/.qargi/memory/projects/lc; mkdir -p "$CM"; echo n > "$CM/b.md"
CRD=$T/s/render/lc/claude-code/.claude/skills; mkdir -p "$CRD/s1"; echo s > "$CRD/s1/SKILL.md"       # what packs apply makes
CD=$HOME/.claude/projects/$(sed 's/[^A-Za-z0-9]/-/g' <<<"$CR")/memory
out=$(lgo link lc 2>&1)
{ [ -L "$CR/.claude/skills" ] && [ "$(readlink "$CR/.claude/skills")" = "$CRD" ] && [ -L "$CD" ] && [ "$(readlink "$CD")" = "$CM" ] && grep -q "^agents: not linked, the runtime links no agents at project level" <<<"$out"; } && ok "claude: skills and memory linked in one apply, agents skipped with the reason" || no "claude link: $out"
$DA agent add jones --roles build --project lc >/dev/null 2>&1
{ [ -f "$CR/.claude/agents/jones.md" ] || [ -f "$CR/.claude/skills/../agents/jones.md" ]; } && ok "claude: a project member is still written into the checkout's agents directory, as before (its definition does not link agents)" || no "claude member location"
lgo unlink lc >/dev/null 2>&1
{ [ ! -e "$CR/.claude/skills" ] && [ ! -e "$CD" ] && [ -d "$CRD/s1" ] && [ -f "$CM/b.md" ]; } && ok "claude: unlink with no resource named undoes every one that is linked" || no "claude unlink"
exit $fail
