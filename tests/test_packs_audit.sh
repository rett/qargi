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

# --- the audit reads: nothing it reports on changed
before=$(snap "$T/c" "$T/s/claude" "$R" "$HOME")
chk >/dev/null; [ "$before" = "$(snap "$T/c" "$T/s/claude" "$R" "$HOME")" ] && ok "plain check is read only" || no "check wrote something"

rm -rf "$T"
exit $fail
