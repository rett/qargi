#!/usr/bin/env bash
# qargi packs link|unlink: the checkout's .claude/skills as a symbolic link to the Claude Code render of the project's packs.
# Offline, hermetic. Run: tests/test_packs_link.sh
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
# the verbs that change a checkout refuse inside a member run (a directory `qargi local prepare` made, at or above the working directory), and this
# test may itself run in one: work from the temporary directory
cd "$T" || exit 1
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s"
DA=$ROOT/bin/qargi
R=$T/repo
proj() { jq -n --arg p "$1" --arg r "$2" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:$r,long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  models:{provider:"claude"},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha "$R"
D=$T/s/claude/alpha

tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
seal() { local tok; tok=$($DA skill seal "$1" | tok_of); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
mkskill() { $DA skill new "$1" --compatible any >/dev/null; sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
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
# a pack the project's provider cannot use is not in the render, so the link never reaches it; the plan says so
$DA skill new s-skip --compatible elsewhere >/dev/null; sed -i "s/^description: .*/description: Use for s-skip./" "$T/c/packs/skills/s-skip/SKILL.md"; seal s-skip
$DA skill link s-skip --scope project --project alpha >/dev/null
out=$(lk); grep -q "^skipped skill s-skip: not compatible with claude (it declares elsewhere)" <<<"$out" && ok "the link plan says which pack the provider cannot use" || no "link plan skip note: $out"
$DA skill unlink s-skip --scope project --project alpha >/dev/null
$DA skill remove s-skip >/dev/null
out=$(lk); rc=$?
[ "$rc" = 0 ] && grep -q "^already linked" <<<"$out" && [ -z "$(tok_of <<<"$out")" ] && ok "linking again says already linked, with no token, exit 0" || no "second link: rc=$rc $out"
n=$(wc -l < "$T/s/audit.log"); lk --plan x --approved y >/dev/null; [ "$n" = "$(wc -l < "$T/s/audit.log")" ] && ok "already linked is not audited" || no "audit on no-op"

# the check note
$DA packs check --target claude-code alpha 2>&1 | grep -q "^note: repo .claude/skills is not linked" && no "check notes a linked checkout" || ok "check says nothing when the checkout is linked"
out=$($DA packs check --target claude-code alpha 2>&1); rc=$?
[ "$rc" = 0 ] && ! grep -q "shadowing" <<<"$out" && ok "a linked checkout is not shadowing its own render: check exits 0 with no shadowing" || no "linked check: rc=$rc $out"

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
tok=$(lplan); [ -n "$tok" ] || no "setup: a plan before the foreign symlink appears"   # a real token, taken in this same state
mkdir -p "$T/other/skills"; echo keep > "$T/other/skills/f"; ln -s "$T/other/skills" "$R/.claude/skills"
out=$(lk 2>&1) && no "replaced a foreign symlink" || { grep -q "not to this project's render" <<<"$out" && ok "a symlink to somewhere else is refused" || no "foreign message: $out"; }
out=$(lk --plan "$tok" --approved x 2>&1) && no "foreign symlink accepted with a token" || { grep -q "not to this project's render" <<<"$out" && ok "a foreign symlink that appeared after the plan is refused at apply, with that reason" || no "foreign at apply: $out"; }
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
rm -r "$S"; out=$(ul 2>&1); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && grep -q "is not linked, but the backup $bk exists" <<<"$out" && grep -q "move $bk back to $S; there is no link to remove" <<<"$out" && [ -d "$bk" ] && [ ! -e "$S" ] \
  && ok "unlink plans moving a backup back when its link is gone, and changes nothing" || no "backup-only plan: $out"
out=$(lk 2>&1) && no "link over an existing backup with no directory" || { grep -q "qargi packs unlink alpha moves it back" <<<"$out" && ok "link refuses while a backup exists, and says unlink moves it back" || no "link over backup message: $out"; }
ul --plan 000000000000 --approved x >/dev/null 2>&1 && no "backup-only unlink with a wrong token" || ok "the backup-only unlink needs its token too"
out=$(ul --plan "$tok" --approved x 2>&1)
[ -d "$S" ] && [ ! -L "$S" ] && [ ! -e "$bk" ] && diff -r "$T/snapshot" "$S" >/dev/null && [ -L "$S/mine/rl" ] && grep -q "restored from $bk (there was no link)" <<<"$out" && ok "the backup-only unlink moves the backup back, byte for byte" || no "backup-only apply: $out"

# --- tracked files: the repository's owner decides
tok=$(lplan); [ -n "$tok" ] || no "setup: a plan before the skills are tracked"
git -C "$R" add -f .claude/skills; $G -C "$R" commit -q -m "track skills"
out=$(lk 2>&1) && no "planned over tracked skills" || { grep -q "tracked by git" <<<"$out" && grep -q "owner decides" <<<"$out" && ok "a directory with tracked files is refused and the owner decides" || no "tracked message: $out"; }
out=$(lk --plan "$tok" --approved x 2>&1) && no "applied over tracked skills" || { grep -q "tracked by git" <<<"$out" && ok "skills that were tracked after the plan are refused at apply, with that reason" || no "tracked at apply: $out"; }
[ -d "$S" ] && [ ! -L "$S" ] && diff -r "$T/snapshot" "$S" >/dev/null && ok "tracked files are untouched" || no "tracked changed"
rm -r "$S"; out=$(lk 2>&1) && no "planned over tracked, deleted skills" || ok "tracked files that were deleted from the work tree are still refused"
git -C "$R" checkout -q -- .claude/skills; git -C "$R" rm -q -r --cached .claude/skills; $G -C "$R" commit -q -m untrack
rm -rf "$S"

# --- a symlinked .claude
tok=$(lplan); [ -n "$tok" ] || no "setup: a plan before .claude becomes a symbolic link"
rm -rf "$R/.claude"; mkdir -p "$T/elsewhere"; ln -s "$T/elsewhere" "$R/.claude"
out=$(lk 2>&1) && no "linked through a symlinked .claude" || { grep -q "is a symbolic link" <<<"$out" && ok "a symlinked .claude is refused" || no ".claude message: $out"; }
ul >/dev/null 2>&1 && no "unlinked through a symlinked .claude" || ok "unlink refuses a symlinked .claude too"
out=$(lk --plan "$tok" --approved x 2>&1); [ -z "$(ls -A "$T/elsewhere")" ] && grep -q "is a symbolic link" <<<"$out" && ok "a .claude that became a symbolic link after the plan is refused at apply, and nothing is written outside the checkout" || no "wrote outside: $out"
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
# --- a stop in the middle of link or unlink says where the skills are and how to get them back (faults are injected with QARGI_TEST_FAULT)
S=$R/.claude/skills; bk=$S.qargi-backup
mkreal() { rm -rf "$S" "$bk" "$R"/.claude/.qargi-*; mkdir -p "$S"; cp -a "$T/snapshot/." "$S/"; }
strays() { local f; for f in "$R"/.claude/.qargi-*; do [ -e "$f" ] || [ -L "$f" ] && echo "$f"; done; }   # the temporary links beside the skills directory
nostray() { [ -z "$(strays)" ]; }
same_as_snapshot() { [ -d "$1" ] && [ ! -L "$1" ] && diff -r "$T/snapshot" "$1" >/dev/null && [ -L "$1/mine/rl" ]; }
mkreal; tok=$(lplan)
out=$(QARGI_TEST_FAULT=after-tmp-link lk --plan "$tok" --approved x 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "injected fault after-tmp-link" <<<"$out" && grep -q "was not moved; nothing was changed" <<<"$out" && same_as_snapshot "$S" && [ ! -e "$bk" ] && nostray \
  && ok "link: a stop before the move changes nothing, and the temporary link is gone" || no "after-tmp-link: rc=$rc $out; $(ls -A "$R/.claude")"
out=$(QARGI_TEST_FAULT=after-backup lk --plan "$tok" --approved x 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "moved and put back; nothing was changed" <<<"$out" && same_as_snapshot "$S" && [ ! -e "$bk" ] && nostray \
  && ok "link: a stop after the move puts the directory back and says so" || no "after-backup: rc=$rc $out; $(ls -A "$R/.claude")"
out=$(QARGI_TEST_FAULT=after-backup,rollback lk --plan "$tok" --approved x 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "your skills are in $bk and $S does not exist" <<<"$out" && grep -q "qargi packs unlink alpha" <<<"$out" && grep -q "mv $bk $S" <<<"$out" && ! grep -q "nothing was changed" <<<"$out" \
  && [ ! -e "$S" ] && [ ! -L "$S" ] && same_as_snapshot "$bk" && nostray \
  && ok "link: when the directory cannot be put back, the message names the backup and the recovery, never 'nothing was changed'" || no "after-backup,rollback: rc=$rc $out; $(ls -A "$R/.claude")"
out=$(ul); tok2=$(tok_of <<<"$out")
[ -n "$tok2" ] && grep -q "is not linked, but the backup $bk exists" <<<"$out" && ul --plan "$tok2" --approved x >/dev/null 2>&1 && same_as_snapshot "$S" && [ ! -e "$bk" ] \
  && ok "the recovery named in the message works: unlink moves the backup back" || no "recovery by unlink: $out; $(ls -A "$R/.claude")"
mkreal; lgo >/dev/null; [ -L "$S" ] && same_as_snapshot "$bk" || no "setup: a linked checkout with a backup"
tok=$(ulplan)
out=$(QARGI_TEST_FAULT=after-aside ul --plan "$tok" --approved x 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "The link is in place and nothing was changed" <<<"$out" && [ "$(readlink "$S")" = "$D/.claude/skills" ] && same_as_snapshot "$bk" && nostray \
  && ok "unlink: a stop after the link was moved aside puts it back" || no "unlink after-aside: rc=$rc $out; $(ls -A "$R/.claude")"
out=$(QARGI_TEST_FAULT=after-aside,rollback ul --plan "$tok" --approved x 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "your skills are in $bk" <<<"$out" && grep -q "it is at $R/.claude/.qargi-unlink\.[0-9]* and $S does not exist" <<<"$out" && ! grep -q "nothing was changed" <<<"$out" \
  && [ ! -e "$S" ] && [ ! -L "$S" ] && [ -n "$(strays)" ] && same_as_snapshot "$bk" \
  && ok "unlink: when the link cannot be put back, the message names where it is and where the skills are" || no "unlink after-aside,rollback: rc=$rc $out; $(ls -A "$R/.claude")"
out=$(ul); tok2=$(tok_of <<<"$out")
[ -n "$tok2" ] && grep -q "is not linked, but the backup" <<<"$out" && ul --plan "$tok2" --approved x >/dev/null 2>&1 && same_as_snapshot "$S" && [ ! -e "$bk" ] \
  && ok "unlink finishes the job from there: the backup goes back" || no "unlink recovery: $out"
rm -f "$R"/.claude/.qargi-unlink.*
mkreal; lgo >/dev/null; tok=$(ulplan)
out=$(QARGI_TEST_FAULT=after-restore ul --plan "$tok" --approved x 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "The skills are back at $S" <<<"$out" && grep -q "a temporary symbolic link $R/.claude/.qargi-unlink\.[0-9]* remains" <<<"$out" && same_as_snapshot "$S" && [ ! -e "$bk" ] && [ -n "$(strays)" ] \
  && ok "unlink: a stop after the move back says the skills are back and names the leftover link" || no "unlink after-restore: rc=$rc $out; $(ls -A "$R/.claude")"
rm -f "$R"/.claude/.qargi-unlink.*

# --- the checkout changed between the plan and the act: apply works through descriptors and refuses what is no longer as planned
held() { rm -f "$T"/hold.*; ( QARGI_TEST_HOLD=$T/hold "$@" >"$T/held.out" 2>&1; echo $? >"$T/held.rc" ) & HELD=$!; for _ in $(seq 300); do [ -e "$T/hold.reached" ] && return 0; sleep 0.1; done; return 1; }
release() { : > "$T/hold.go"; wait "$HELD"; HRC=$(cat "$T/held.rc"); HOUT=$(cat "$T/held.out"); }
mkreal; tok=$(lplan); mkdir -p "$T/elsewhere2"
held lk --plan "$tok" --approved x || no "setup: the hold was not reached"
mv "$R/.claude" "$T/claude.moved"; ln -s "$T/elsewhere2" "$R/.claude"; release
[ "$HRC" != 0 ] && grep -q "is a symbolic link or not a directory now" <<<"$HOUT" && grep -q "nothing was changed" <<<"$HOUT" && [ -z "$(ls -A "$T/elsewhere2")" ] && same_as_snapshot "$T/claude.moved/skills" && [ ! -e "$T/claude.moved/skills.qargi-backup" ] \
  && ok "a .claude replaced by a symbolic link between the plan and the apply is refused, and nothing is written through it" || no "swapped .claude: rc=$HRC $HOUT; $(ls -A "$T/elsewhere2")"
rm "$R/.claude"; mv "$T/claude.moved" "$R/.claude"
tok=$(lplan); held lk --plan "$tok" --approved x || no "setup: the hold was not reached"
mkdir "$bk"; release
[ "$HRC" != 0 ] && grep -q "$bk exists now" <<<"$HOUT" && same_as_snapshot "$S" && [ -z "$(ls -A "$bk")" ] && nostray \
  && ok "a backup that appears between the plan and the apply is not replaced" || no "late backup: rc=$HRC $HOUT"
rmdir "$bk"
rm -rf "$S"; tok=$(lplan); held lk --plan "$tok" --approved x || no "setup: the hold was not reached"
mkdir -p "$S"; echo mine > "$S/f"; release
[ "$HRC" != 0 ] && grep -q "exists now (it did not when the plan was made)" <<<"$HOUT" && [ "$(cat "$S/f")" = mine ] && [ ! -L "$S" ] \
  && ok "a directory that appears where a link was to be made is left alone" || no "late directory: rc=$HRC $HOUT"
mkreal; lgo >/dev/null; tok=$(ulplan); held ul --plan "$tok" --approved x || no "setup: the hold was not reached"
rm "$S"; ln -s "$T/other/skills" "$S"; release
[ "$HRC" != 0 ] && grep -q "not a symbolic link to this project's render any more" <<<"$HOUT" && [ "$(readlink "$S")" = "$T/other/skills" ] && [ "$(cat "$T/other/skills/f")" = keep ] && same_as_snapshot "$bk" \
  && ok "a link swapped for a foreign one before the unlink is not removed" || no "swapped link: rc=$HRC $HOUT"
rm "$S"; mv "$bk" "$S"; rm -rf "$R"/.claude/.qargi-*

# --- names and paths that come from the repository are not trusted in the offers: unusual names get none, the rest are quoted, nothing prints a control character
S=$R/.claude/skills; mkdir -p "$S"
mkskilldir() { mkdir -p "$S/$1"; printf -- '---\nname: x\ndescription: Use for x.\n---\n' > "$S/$1/SKILL.md"; }
mkskilldir fine; mkskilldir 'evil $(touch PWNED)'; mkskilldir 'bt `touch PWNED`'; mkskilldir 'semi;rm -rf x'; mkskilldir "$(printf 'nl\nline')"; mkskilldir "$(printf 'esc\033[31mred')"; mkskilldir "sp ace"
out=$(lk 2>&1)
[ "$(grep -c 'skipped: unusual name' <<<"$out")" = 12 ] && ok "link plan: each unusual name is marked 'skipped: unusual name' (in the plan and in the section after it)" || no "skipped count: $out"
! grep -E 'qargi skill (import|link) ' <<<"$out" | grep -qE 'evil|PWNED|semi|nl|esc|sp ace' && grep -qE "qargi skill import .*/fine\$" <<<"$out" && ok "link plan: no offer for an unusual name, the offer for a usual one stays" || no "offers: $out"
! LC_ALL=C tr -d '\n' <<<"$out" | grep -q '[[:cntrl:]]' && ok "link plan: no control character is printed" || no "control characters in the link plan"
[ ! -e PWNED ] && ok "(nothing was run)" || no "a name was executed"
rm -rf "$S"; mkdir -p "$T/it's a repo with space"; git init -q -b main "$T/it's a repo with space"; proj alpha "$T/it's a repo with space"
S2=$T/it\'s\ a\ repo\ with\ space/.claude/skills; mkdir -p "$S2/mine"; printf -- '---\nname: x\ndescription: Use for x.\n---\n' > "$S2/mine/SKILL.md"
out=$(lk 2>&1); line=$(sed -n 's/^ *to keep it: qargi skill import //p' <<<"$out")
eval "set -- $line"; [ "$#" = 1 ] && [ "$1" = "$T/it's a repo with space/.claude/skills/mine" ] && ok "link plan: a path with a quote and spaces is shell-quoted in the offer" || no "path quoting: $line / $out"
rm -rf "$T/it's a repo with space"; proj alpha "$R"

# --- same and differs are decided on the whole tree: a link, an executable bit, an empty directory or a nested .pack.json make a copy differ
S=$R/.claude/skills; mkdir -p "$S"; cp -r "$T/c/packs/skills/s-all" "$S/s-all"; rm -f "$S/s-all/.pack.json"
kind() { lk 2>&1 | sed -n 's/^ *\(same\|differs\|new\) \+s-all .*/\1/p'; }
[ "$(kind)" = same ] && ok "a copy of the pack without its record is 'same'" || no "plain copy: $(kind)"
chmod +x "$S/s-all/refs/r.md"; [ "$(kind)" = differs ] && ok "an executable bit makes it differ" || no "mode: $(kind)"
chmod -x "$S/s-all/refs/r.md"; [ "$(kind)" = same ] && ok "(and taking it away makes it the same again)" || no "mode back: $(kind)"
ln -s r.md "$S/s-all/refs/link"; [ "$(kind)" = differs ] && ok "a symbolic link inside makes it differ" || no "symlink: $(kind)"
rm "$S/s-all/refs/link"; mkdir "$S/s-all/empty"; [ "$(kind)" = differs ] && ok "an empty directory makes it differ" || no "empty dir: $(kind)"
rmdir "$S/s-all/empty"; echo '{}' > "$S/s-all/refs/.pack.json"; [ "$(kind)" = differs ] && ok "a .pack.json below the top level makes it differ" || no "nested record: $(kind)"
rm "$S/s-all/refs/.pack.json"; echo '{}' > "$S/s-all/.pack.json"; [ "$(kind)" = differs ] && ok "so does a .pack.json at the top of a copy in the checkout" || no "top record in checkout: $(kind)"
rm "$S/s-all/.pack.json"; [ "$(kind)" = same ] && ok "(the same again once it is gone)" || no "same again: $(kind)"
rm -rf "$S"

# --- the helper script run directly, as a member could: the gates still hold (a member run never applies; the state, the checkout and the
# provider are the environment's and the stored answers', not the inputs file's)
PYL="python3 -I $ROOT/lib/packs_link.py"; DAA=$ROOT/bin/qargi
mkdir -p "$T/run/out"; : > "$T/run/ability"; : > "$T/run/refs.before"
LEAD=$T/leadrepo; git init -q -b main "$LEAD"; echo x > "$LEAD/README"; $G -C "$LEAD" add -A; $G -C "$LEAD" commit -q -m one
mkin() { jq -nc --arg co "$1" --arg st "$2" --arg h "$HOME" '{project:"alpha",provider:"claude",state:$st,home:$h,checkout:$co,packs:[],kids:[]}' > "$T/in.json"; }
tok=$(lplan); [ -n "$tok" ] && [ ! -e "$R/.claude/skills" ] || no "setup: a plan in the same state"
out=$(cd "$T/run/out" && "$DAA" packs link alpha --plan "$tok" --approved x 2>&1) && no "a member run applied packs link" || { grep -q "member run" <<<"$out" && ok "packs link refuses in a member run" || no "member link message: $out"; }
[ ! -e "$R/.claude/skills" ] && [ ! -L "$R/.claude/skills" ] && ok "a refused apply in a member run changes nothing" || no "member run linked"
mkin "$R" "$T/s"; out=$(cd "$T/run/out" && $PYL apply link "$T/in.json" "$tok" 2>&1) && no "packs_link.py applied in a member run" || { grep -q "member run" <<<"$out" && [ ! -L "$R/.claude/skills" ] && ok "packs_link.py apply refuses in a member run, whatever calls it" || no "direct member apply: $out"; }
mkin "$R" "$T/evil-state"; out=$($PYL plan link "$T/in.json" "$T/tokfile" 2>&1)
grep -q "target: $D/.claude/skills" <<<"$out" && ! grep -q "evil-state" <<<"$out" && ok "the render comes from the environment's state, not the inputs file's state" || no "state from inputs: $out"
mkin "$LEAD" "$T/s"; rm -f "$T/tokfile"; out=$($PYL plan link "$T/in.json" "$T/tokfile" 2>&1) && no "planned a checkout the project does not have" || { grep -q "not the project's repo.path" <<<"$out" && ok "the checkout must be the project's own, not the inputs file's" || no "foreign checkout message: $out"; }
$PYL apply link "$T/in.json" "$(cat "$T/tokfile" 2>/dev/null || echo 000000000000)" >/dev/null 2>&1
[ ! -e "$LEAD/.claude" ] && ok "nothing is written into a checkout the inputs file invented" || no "wrote into the lead's repository"
mkin "$R" "$T/s"; jq '.provider = "agentx"' "$T/in.json" > "$T/in2.json"; out=$($PYL plan link "$T/in2.json" "$T/tokfile" 2>&1) && no "planned another provider than the project's" || { grep -q "not the project's" <<<"$out" && ok "the provider must be the project's own" || no "foreign provider message: $out"; }
$PYL plan link "$T/in.json" "$T/tokfile" >/dev/null 2>&1 && [ -s "$T/tokfile" ] && ok "(inputs that agree with the stored answers still plan)" || no "plain direct plan failed"

# a name with a trailing newline is not a project name, nor a skill name
jq '.project = "alpha\n"' "$T/in.json" > "$T/in3.json"; out=$($PYL plan link "$T/in3.json" "$T/tokfile" 2>&1) && no "a project name with a trailing newline was accepted" || { grep -q "not a project name" <<<"$out" && ok "a project name with a trailing newline is refused" || no "newline project: $out"; }
out=$($DA skill accept alpha $'mine\n' 2>&1) && no "a skill name with a trailing newline was accepted" || { grep -q "^qargi: not a skill name: mine" <<<"$out" && ok "the shell refuses a skill name with a trailing newline as 'not a skill name'" || no "newline skill (shell): $out"; }

# --- a provider whose layout differs: every path comes from its descriptor, and a missing facility is a refusal (exit 3)
# A copy of the tool holds the fake providers, so the shipped descriptors are never changed. agentx keeps its skills in .agent/skills,
# has its own render target, and no renderer: the render is made by hand.
TOOL=$T/tool; mkdir -p "$TOOL"
for d in agents bin lib roles skills provision canon methodologies VERSION; do [ ! -e "$ROOT/$d" ] || cp -r "$ROOT/$d" "$TOOL/"; done
FX=$TOOL/bin/qargi
mkprov() { jq --arg n "$1" ".provider = \$n | .adapter = null | $2" "$ROOT/lib/providers/claude.json" > "$TOOL/lib/providers/$1.json"; }
mkprov agentx '.layout.project_skills_dir = ".agent/skills" | .layout.render_target = "agentx-render" | .layout.user_skills_dir = "~/.agent/skills"
  | .layout.settings_files = [{scope:"user",path:"~/.agent/settings.json"},{scope:"project-local",path:".agent/settings.local.json"}] | .layout.exclusion = {file_key:"skills_off", off_value:"hidden"}'
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
out=$($FX packs check beta 2>&1); rc=$?
[ "$rc" = 1 ] && [ "$out" = "qargi: --target is agentx-render (or managed-agents / none for a cloud instance); check needs --target agentx-render" ] && ok "check without --target names the project's provider's render target, not claude-code" || no "no target message: rc=$rc $out"
out=$($FX packs apply --target none beta 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "^qargi: --target is agentx-render (or managed-agents" <<<"$out" && ! grep -q claude <<<"$out" && ok "--target none names the provider's render target too" || no "target none message: rc=$rc $out"
out=$($FX packs apply --target agentx-render beta 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^agentx-render target for beta -> $T/s/agentx/beta\$" <<<"$out" && grep -q "^plan token: " <<<"$out" && ok "there is one renderer for every runtime: another provider's render target plans a render under its own directories" || no "agentx apply plan: rc=$rc $out"
out=$($FX packs apply --target claude-code gamma 2>&1); rc=$?
[ "$rc" = 3 ] && [ "$out" = "qargi: provider noskills has no project skills directory: render the project's packs for a local session" ] && ok "a provider with no project skills directory: the render is refused with exit 3 and the degrade text" || no "noskills apply: rc=$rc $out"
out=$($DA packs check --target claude-code alpha 2>&1); [ -n "$out" ] && ok "claude keeps answering to --target claude-code" || no "claude target"
# there is no default provider: answers without models.provider are refused with exit 2 and the fix, by every verb that needs one
jq 'del(.models)' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"
for v in "packs link alpha" "packs unlink alpha" "packs check --target claude-code alpha" "packs apply --target claude-code alpha"; do
  out=$($DA $v 2>&1); rc=$?
  [ "$rc" = 2 ] && [ "$out" = "qargi: project alpha has no provider: set one with qargi project set alpha models.provider NAME" ] && ok "no models.provider: $v is refused with exit 2" || no "no provider ($v): rc=$rc $out"
done
# a project that does not exist is not "a project with no provider": the fix that text names would fail for it
for v in "packs link nosuchproj" "packs unlink nosuchproj" "packs check --target claude-code nosuchproj" "packs apply --target claude-code nosuchproj" "skill accept nosuchproj x"; do
  out=$($DA $v 2>&1); rc=$?
  [ "$rc" = 2 ] && [ "$out" = "qargi: no such project 'nosuchproj'" ] && ok "no such project: $v is refused with exit 2 and says so" || no "no such project ($v): rc=$rc $out"
done
jq '.models = {provider: "nosuch"}' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"
out=$($DA packs link alpha 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "^qargi: no runtime or family 'nosuch' for the local surface; available: " <<<"$out" && ok "a provider with no descriptor is refused as an unknown runtime of the local surface (exit 2)" || no "unknown provider: rc=$rc $out"

rm -rf "$T"
exit $fail
