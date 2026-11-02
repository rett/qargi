#!/usr/bin/env bash
# qargi packs link|unlink: the checkout's .claude/skills as a symbolic link to the Claude Code render of the project's packs.
# Offline, hermetic. Run: tests/test_packs_link.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s"
DA=./bin/qargi
R=$T/repo
proj() { jq -n --arg p "$1" --arg r "$2" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:$r,long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  models:{provider:"claude"},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha "$R"
D=$T/s/claude/alpha

tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
seal() { local tok; tok=$($DA skill seal "$1" | tok_of); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
mkskill() { $DA skill new "$1" >/dev/null; sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
lk() { $DA packs link alpha "$@"; }
ul() { $DA packs unlink alpha "$@"; }
lplan() { lk | tok_of; }
ulplan() { ul | tok_of; }
lgo() { lk --plan "$(lplan)" --approved test; }
ulgo() { ul --plan "$(ulplan)" --approved test; }
G="git -c user.name=t -c user.email=t@example.net"
# a hash of everything under the given paths (names, link targets, contents), for "nothing changed"
snap() { find "$@" \( -type l -printf 'L %p -> %l\n' \) -o \( -type f -printf 'F %p\n' \) -o \( -type d -printf 'D %p\n' \) 2>/dev/null | sort | sha256sum
         find "$@" -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum | sha256sum; }

mkskill s-all; mkskill s-build
mkdir -p "$T/c/packs/skills/s-all/refs"; echo ref > "$T/c/packs/skills/s-all/refs/r.md"; seal s-all
$DA skill link s-all --scope project --project alpha >/dev/null
$DA skill link s-build --scope project --project alpha >/dev/null
git init -q -b main "$R"; echo x > "$R/README"; $G -C "$R" add -A; $G -C "$R" commit -q -m one

# --- refusals before anything exists
out=$(lk 2>&1) && no "linked without a render" || { grep -q "packs apply --target claude-code alpha first" <<<"$out" && ok "a missing render is refused and the message names the fix" || no "no-render message: $out"; }
[ ! -e "$R/.claude" ] && ok "a refused link writes nothing" || no "wrote .claude"
proj alpha ""; out=$(lk 2>&1) && no "linked with no checkout" || ok "a project with no checkout is refused"
proj alpha "$T/nodir"; lk >/dev/null 2>&1 && no "linked a missing checkout" || ok "a checkout that does not exist is refused"
mkdir -p "$T/plain"; proj alpha "$T/plain"; out=$(lk 2>&1) && no "linked a directory that is not a git work tree" || { grep -q "not the top of a git work tree" <<<"$out" && ok "a checkout that is not a git work tree is refused" || no "work tree message: $out"; }
mkdir -p "$R/sub"; proj alpha "$R/sub"; lk >/dev/null 2>&1 && no "linked a subdirectory of a work tree" || ok "a subdirectory of a work tree is not a checkout"
proj alpha "$R"
$DA packs link >/dev/null 2>&1 && no "link without PROJECT" || ok "link needs a PROJECT"

# --- the render exists; link into a checkout without .claude
$DA packs apply --target claude-code alpha --plan "$($DA packs apply --target claude-code alpha | tok_of)" --approved test >/dev/null
[ -d "$D/.claude/skills/s-all" ] || no "the render was not made"
before=$(snap "$T/c" "$D")
out=$(lk); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && grep -q "$R/.claude/skills" <<<"$out" && grep -q "$D/.claude/skills" <<<"$out" && [ ! -e "$R/.claude" ] && ok "the plan names the link and its target, prints a token and writes nothing" || no "absent plan: $out"
lk --approved x >/dev/null 2>&1 && no "applied without the plan token" || ok "apply refuses without the plan token"
lk --plan 000000000000 --approved x >/dev/null 2>&1 && no "applied with a wrong token" || ok "apply refuses a wrong token"
[ ! -e "$R/.claude" ] && ok "a refused apply changes nothing" || no "refused apply wrote .claude"
out=$(lk --plan "$tok" --approved "go ahead")
[ -L "$R/.claude/skills" ] && [ "$(readlink "$R/.claude/skills")" = "$D/.claude/skills" ] && [ -f "$R/.claude/skills/s-all/SKILL.md" ] && cmp -s "$R/.claude/skills/s-all/refs/r.md" "$T/c/packs/skills/s-all/refs/r.md" && ok "apply creates a symbolic link to the render, and it resolves" || no "apply: $out; $(ls -la "$R/.claude" 2>&1)"
tail -1 "$T/s/audit.log" | jq -e '.verb=="packs-link" and .approved=="go ahead"' >/dev/null && ok "link is audit-logged" || no "audit: $(tail -1 "$T/s/audit.log")"
grep -q "git does not ignore .claude/skills" <<<"$out" && grep -q "^    .claude/skills$" <<<"$out" && grep -q "info/exclude" <<<"$out" && ok "an unignored link prints the line to add to .git/info/exclude" || no "exclude hint: $out"
[ ! -s "$R/.git/info/exclude" ] || ! grep -q "^.claude/skills" "$R/.git/info/exclude" && ok "the exclude file is not edited" || no "exclude edited"
[ "$before" = "$(snap "$T/c" "$D")" ] && ok "neither the library nor the render changed" || no "library or render changed"
out=$(lk); rc=$?
[ "$rc" = 0 ] && grep -q "^already linked" <<<"$out" && [ -z "$(tok_of <<<"$out")" ] && ok "linking again says already linked, with no token, exit 0" || no "second link: rc=$rc $out"
n=$(wc -l < "$T/s/audit.log"); lk --plan x --approved y >/dev/null; [ "$n" = "$(wc -l < "$T/s/audit.log")" ] && ok "already linked is not audited" || no "audit on no-op"

# the check note
$DA packs check --target claude-code alpha 2>&1 | grep -q "^note: repo .claude/skills is not linked" && no "check notes a linked checkout" || ok "check says nothing when the checkout is linked"

# --- unlink: only the symlink goes
out=$(ul); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && [ -L "$R/.claude/skills" ] && ok "the unlink plan prints a token and changes nothing" || no "unlink plan: $out"
ul --plan 000000000000 --approved x >/dev/null 2>&1 && no "unlinked with a wrong token" || ok "unlink refuses a wrong token"
[ -L "$R/.claude/skills" ] && ok "a refused unlink changes nothing" || no "refused unlink removed the link"
ul --plan "$tok" --approved test >/dev/null
[ ! -e "$R/.claude/skills" ] && [ ! -L "$R/.claude/skills" ] && [ -d "$D/.claude/skills/s-all" ] && [ -d "$R/.claude" ] && ok "unlink removes only the symlink; the render stays" || no "unlink result"
tail -1 "$T/s/audit.log" | jq -e '.verb=="packs-unlink"' >/dev/null && ok "unlink is audit-logged" || no "unlink audit"
ul >/dev/null 2>&1 && no "unlinked something that is not linked" || ok "unlink with nothing linked is refused"
$DA packs check --target claude-code alpha 2>&1 | grep -qx "note: repo .claude/skills is not linked to the render (qargi packs link alpha)" && ok "check notes a checkout that is not linked, without failing" || no "check note"
$DA packs check --target claude-code alpha >/dev/null 2>&1 && ok "the note does not change the exit status" || no "check status"
echo ".claude/skills" >> "$R/.git/info/exclude"
out=$(lk); [ -n "$(tok_of <<<"$out")" ] && ! grep -q "git does not ignore" <<<"$out" && ok "no hint once git ignores the path" || no "hint despite ignore: $out"

# --- a symlink somewhere else is never replaced
mkdir -p "$T/other/skills"; echo keep > "$T/other/skills/f"; ln -s "$T/other/skills" "$R/.claude/skills"
out=$(lk 2>&1) && no "replaced a foreign symlink" || { grep -q "not to this project's render" <<<"$out" && ok "a symlink to somewhere else is refused" || no "foreign message: $out"; }
lk --plan 000000000000 --approved x >/dev/null 2>&1 && no "foreign symlink accepted with a token" || ok "a foreign symlink is refused at apply too"
out=$(ul 2>&1) && no "unlink removed a foreign symlink" || { grep -q "not to this project's render" <<<"$out" && ok "unlink refuses a foreign symlink" || no "unlink foreign: $out"; }
[ "$(readlink "$R/.claude/skills")" = "$T/other/skills" ] && [ "$(cat "$T/other/skills/f")" = keep ] && ok "the foreign symlink and its target are untouched" || no "foreign changed"
rm "$R/.claude/skills"; ln -s "$T/nowhere" "$R/.claude/skills"; lk >/dev/null 2>&1 && no "replaced a dangling symlink" || ok "a dangling foreign symlink is refused too"
rm "$R/.claude/skills"

# --- a real directory: same / differs / new
S=$R/.claude/skills
mkdir -p "$S"; cp -r "$T/c/packs/skills/s-all" "$S/s-all"; rm -f "$S/s-all/.pack.json"
cp -r "$T/c/packs/skills/s-build" "$S/s-build"; rm -f "$S/s-build/.pack.json"; echo "local edit" >> "$S/s-build/SKILL.md"
mkdir -p "$S/mine/data"; printf -- '---\nname: mine\ndescription: Use for mine.\n---\n' > "$S/mine/SKILL.md"; echo d > "$S/mine/data/x.txt"
echo note > "$S/NOTES.txt"; ln -s "$R/README" "$S/mine/rl"
cp -a "$S" "$T/snapshot"
out=$(lk); tok=$(tok_of <<<"$out")
grep -qE "^ +same +s-all" <<<"$out" && grep -qE "^ +differs +s-build" <<<"$out" && grep -qE "^ +new +mine" <<<"$out" && ok "a real directory's skills are classified same, differs and new" || no "classify: $out"
grep -q "qargi skill import $S/mine" <<<"$out" && grep -q "qargi skill link mine --scope project --project alpha" <<<"$out" && ok "a new skill gets the import and link offer" || no "offer: $out"
! grep -q "skill import $S/s-all" <<<"$out" && ! grep -q "skill import $S/s-build" <<<"$out" && ok "same and differs get no import offer" || no "offer for known skills"
grep -q "$S.qargi-backup" <<<"$out" && grep -q "stop loading" <<<"$out" && grep -q "NOTES.txt" <<<"$out" && ok "the plan says where the backup goes, that unimported skills stop loading and what else moves" || no "plan text: $out"
bk=$R/.claude/skills.qargi-backup
[ -n "$tok" ] && [ -d "$S" ] && [ ! -L "$S" ] && [ ! -e "$bk" ] && ok "the plan changed nothing" || no "dir plan wrote"
# the plan token covers the classification
echo extra > "$R/.claude/skills/NEW.txt"; mkdir -p "$S/late"; printf -- '---\nname: late\ndescription: Use for late.\n---\n' > "$S/late/SKILL.md"
lk --plan "$tok" --approved x >/dev/null 2>&1 && no "applied a plan that changed" || ok "a changed plan is refused at apply"
[ -d "$S" ] && [ ! -L "$S" ] && [ ! -e "$bk" ] && ok "the refused apply changed nothing" || no "changed plan wrote"
rm -rf "$S/late" "$S/NEW.txt"
mkdir -p "$bk"; out=$(lk 2>&1) && no "planned over an existing backup" || { grep -q "already exists" <<<"$out" && ok "an existing backup is refused" || no "backup message: $out"; }
rmdir "$bk"
out=$(lk --plan "$tok" --approved x 2>&1) && [ -L "$S" ] && [ "$(readlink "$S")" = "$D/.claude/skills" ] && [ -f "$S/s-all/SKILL.md" ] && ok "apply moves the directory away and links" || no "apply real dir: $out"
grep -q "backup: $bk" <<<"$out" && diff -r "$T/snapshot" "$bk" >/dev/null && [ -L "$bk/mine/rl" ] && ok "the backup holds everything, byte for byte" || no "backup differs"
[ ! -e "$S/mine" ] && ok "unimported skills no longer load" || no "mine still visible"
ul --plan "$(ulplan)" --approved x 2>&1 | grep -q "restored from" && [ -d "$S" ] && [ ! -L "$S" ] && [ ! -e "$bk" ] && diff -r "$T/snapshot" "$S" >/dev/null && [ -L "$S/mine/rl" ] && ok "unlink restores the directory byte for byte" || no "restore differs"
out=$(ul 2>&1) && no "unlink touched a real directory" || { grep -q "is not a symbolic link" <<<"$out" && ok "unlink refuses a real .claude/skills" || no "unlink real dir: $out"; }
[ -d "$S" ] && diff -r "$T/snapshot" "$S" >/dev/null && ok "the real directory is untouched by the refusal" || no "real dir changed"

# --- link, then something real takes the link's place
lgo >/dev/null; rm "$S"; mkdir "$S"; echo mine > "$S/x"
out=$(ul 2>&1) && no "unlink with a real directory in place and a backup" || ok "unlink refuses when a real .claude/skills took the symlink's place"
[ -f "$S/x" ] && [ -d "$bk" ] && ok "nothing moved" || no "moved"
rm -r "$S"; out=$(ul 2>&1) && no "unlink with a backup but no link" || { grep -q "is not a symbolic link of this project's render" <<<"$out" && ok "unlink refuses a backup whose symlink is gone" || no "backup-only message: $out"; }
[ -d "$bk" ] && ok "the backup stays" || no "backup gone"
out=$(lk 2>&1) && no "link over an existing backup with no directory" || ok "link refuses while a backup exists, even with nothing at .claude/skills"
mv "$bk" "$S"; diff -r "$T/snapshot" "$S" >/dev/null && ok "(the backup is the original directory)" || no "backup content"

# --- tracked files: the repository's owner decides
git -C "$R" add -f .claude/skills; $G -C "$R" commit -q -m "track skills"
out=$(lk 2>&1) && no "planned over tracked skills" || { grep -q "tracked by git" <<<"$out" && grep -q "owner decides" <<<"$out" && ok "a directory with tracked files is refused and the owner decides" || no "tracked message: $out"; }
lk --plan 000000000000 --approved x >/dev/null 2>&1 && no "applied over tracked skills" || ok "tracked skills are refused at apply too"
[ -d "$S" ] && [ ! -L "$S" ] && diff -r "$T/snapshot" "$S" >/dev/null && ok "tracked files are untouched" || no "tracked changed"
rm -r "$S"; out=$(lk 2>&1) && no "planned over tracked, deleted skills" || ok "tracked files that were deleted from the work tree are still refused"
git -C "$R" checkout -q -- .claude/skills; git -C "$R" rm -q -r --cached .claude/skills; $G -C "$R" commit -q -m untrack
rm -rf "$S"

# --- a symlinked .claude
rm -rf "$R/.claude"; mkdir -p "$T/elsewhere"; ln -s "$T/elsewhere" "$R/.claude"
out=$(lk 2>&1) && no "linked through a symlinked .claude" || { grep -q "is a symbolic link" <<<"$out" && ok "a symlinked .claude is refused" || no ".claude message: $out"; }
ul >/dev/null 2>&1 && no "unlinked through a symlinked .claude" || ok "unlink refuses a symlinked .claude too"
lk --plan 000000000000 --approved x >/dev/null 2>&1; [ -z "$(ls -A "$T/elsewhere")" ] && ok "nothing is written outside the checkout" || no "wrote outside"
rm "$R/.claude"; printf 'file\n' > "$R/.claude"; lk >/dev/null 2>&1 && no ".claude that is a file was accepted" || ok "a .claude that is a file is refused"
rm "$R/.claude"

# --- the whole round trip writes nothing outside the checkout's .claude
before=$(snap "$T/c" "$D" "$R/README" "$R/.git/info" "$T/other")
lgo >/dev/null; ulgo >/dev/null; lgo >/dev/null
[ "$before" = "$(snap "$T/c" "$D" "$R/README" "$R/.git/info" "$T/other")" ] && ok "link and unlink leave the library, the render and the repository's own files alone" || no "outside changed"
[ "$(git -C "$R" status --porcelain | grep -v '^?? .claude/' | wc -l)" = 0 ] && ok "git sees nothing tracked change" || no "git status: $(git -C "$R" status --porcelain)"

# --- the project's render is gone: a dangling link can still be removed
mv "$D" "$T/render.gone"; out=$(lk 2>&1) && no "link with the render gone" || ok "link refuses when the render is gone"
ulgo >/dev/null 2>&1; [ ! -L "$R/.claude/skills" ] && ok "a dangling link of ours can be unlinked" || no "dangling unlink"
mv "$T/render.gone" "$D"

# --- a project name that is not one
$DA packs link '../x' >/dev/null 2>&1 && no "a bad project name was accepted" || ok "a bad project name is refused"
# --- a provider whose layout differs: every path comes from its descriptor, and a missing facility is a refusal (exit 3)
# A copy of the tool holds the fake providers, so the shipped descriptors are never changed. agentx keeps its skills in .agent/skills,
# has its own render target, and no renderer: the render is made by hand.
TOOL=$T/tool; mkdir -p "$TOOL"
for d in agents bin lib roles skills provision canon methodologies VERSION; do [ ! -e "$PWD/$d" ] || cp -r "$PWD/$d" "$TOOL/"; done
FX=$TOOL/bin/qargi
mkprov() { jq --arg n "$1" ".provider = \$n | .adapter = null | $2" lib/providers/claude.json > "$TOOL/lib/providers/$1.json"; }
mkprov agentx '.layout.project_skills_dir = ".agent/skills" | .layout.render_target = "agentx-render" | .layout.user_skills_dir = "~/.agent/skills"'
mkprov noskills '.layout.project_skills_dir = null'
mkprov unverified '.capabilities.skills.local.verified_on = null'
mkprov notarget '.layout.render_target = null'
R2=$T/repo2; git init -q -b main "$R2"; echo x > "$R2/README"; $G -C "$R2" add -A; $G -C "$R2" commit -q -m one
projp() { proj "$1" "$R2"; jq --arg v "$2" '.models = {provider: $v}' "$T/c/projects/$1.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/$1.json"; }
projp beta agentx
fl() { $FX packs link beta "$@"; }
fu() { $FX packs unlink beta "$@"; }
D2=$T/s/agentx/beta
out=$(fl 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "there is no render of beta yet" <<<"$out" && grep -q "packs apply --target agentx-render beta first" <<<"$out" && ! grep -q "claude" <<<"$out" && ok "another provider: the missing render is refused and the message names its render target" || no "agentx no-render: rc=$rc $out"
mkdir -p "$D2/.agent/skills"; cp -r "$T/c/packs/skills/s-all" "$D2/.agent/skills/s-all"
out=$(fl); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && grep -q "link:   $R2/.agent/skills" <<<"$out" && grep -q "target: $D2/.agent/skills" <<<"$out" && ! grep -q "\.claude" <<<"$out" && ok "another provider: the plan names the link and the render under the provider's own directories" || no "agentx plan: $out"
grep -q "git does not ignore .agent/skills" <<<"$out" && grep -q "^    .agent/skills$" <<<"$out" && ok "another provider: the exclude hint names its skills directory" || no "agentx hint: $out"
out=$(fl --plan "$tok" --approved go)
[ -L "$R2/.agent/skills" ] && [ "$(readlink "$R2/.agent/skills")" = "$D2/.agent/skills" ] && [ ! -e "$R2/.claude" ] && ok "another provider: apply links .agent/skills and creates no .claude" || no "agentx apply: $out; $(ls -a "$R2")"
out=$(fl); grep -q "^already linked: $R2/.agent/skills" <<<"$out" && ok "another provider: linking again says already linked" || no "agentx again: $out"
fu --plan "$(fu | tok_of)" --approved go >/dev/null; [ ! -e "$R2/.agent/skills" ] && [ -d "$D2/.agent/skills/s-all" ] && ok "another provider: unlink removes only the link" || no "agentx unlink"
mkdir -p "$R2/.agent/skills/own"; printf -- '---\nname: own\ndescription: Use for own.\n---\n' > "$R2/.agent/skills/own/SKILL.md"
out=$(fl); grep -qE "^ +new +own" <<<"$out" && grep -q "moves the directory to $R2/.agent/skills.qargi-backup" <<<"$out" && ok "another provider: a real skills directory is classified and backed up beside itself" || no "agentx real dir: $out"
rm -rf "$R2/.agent"

projp gamma noskills; out=$($FX packs link gamma 2>&1); rc=$?
[ "$rc" = 3 ] && [ "$out" = "qargi: provider noskills has no project skills directory: link the checkout's skills directory to the render" ] && ok "a provider with no project skills directory: link is refused with exit 3 and the degrade text" || no "noskills link: rc=$rc $out"
out=$($FX packs unlink gamma 2>&1); rc=$?
[ "$rc" = 3 ] && grep -q "^qargi: provider noskills has no project skills directory: " <<<"$out" && ok "unlink is refused the same way" || no "noskills unlink: rc=$rc $out"
[ ! -e "$R2/.claude" ] && [ ! -e "$R2/.agent" ] && ok "a refused verb writes nothing" || no "noskills wrote"
projp delta unverified; out=$($FX packs link delta 2>&1); rc=$?
[ "$rc" = 3 ] && grep -q "^qargi: provider unverified has no skills support on the local surface: " <<<"$out" && ok "a provider whose skills capability is not verified: link is refused with exit 3" || no "unverified: rc=$rc $out"
projp eps notarget; out=$($FX packs check --target claude-code eps 2>&1); rc=$?
[ "$rc" = 3 ] && [ "$out" = "qargi: provider notarget has no packs render target: render the project's packs for a local session" ] && ok "a provider with no render target: packs check --target is refused with exit 3" || no "notarget check: rc=$rc $out"
out=$($FX packs apply --target claude-code beta 2>&1); rc=$?
[ "$rc" != 0 ] && [ "$rc" != 3 ] && grep -q "^qargi: --target is agentx-render for provider agentx" <<<"$out" && ok "another provider's render target is the one --target accepts" || no "wrong target: rc=$rc $out"
out=$($FX packs apply --target agentx-render beta 2>&1); rc=$?
[ "$rc" = 3 ] && grep -q "^qargi: provider agentx has no packs renderer for target agentx-render: " <<<"$out" && ok "a render target nothing renders is refused with exit 3" || no "no renderer: rc=$rc $out"
out=$($DA packs check --target claude-code alpha 2>&1); [ -n "$out" ] && ok "claude keeps answering to --target claude-code" || no "claude target"
# there is no default provider: answers without models.provider are refused with exit 2 and the fix, by every verb that needs one
jq 'del(.models)' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"
for v in "packs link alpha" "packs unlink alpha" "packs check --target claude-code alpha" "packs apply --target claude-code alpha"; do
  out=$($DA $v 2>&1); rc=$?
  [ "$rc" = 2 ] && [ "$out" = "qargi: project alpha has no provider: set one with qargi project set alpha models.provider NAME" ] && ok "no models.provider: $v is refused with exit 2" || no "no provider ($v): rc=$rc $out"
done
jq '.models = {provider: "nosuch"}' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"
out=$($DA packs link alpha 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "unknown provider 'nosuch'" <<<"$out" && ok "a provider with no descriptor is refused like any unknown provider" || no "unknown provider: rc=$rc $out"

rm -rf "$T"
exit $fail
