#!/usr/bin/env bash
# The link engine (lib/linker.py) on its own: a resource kind that is not skills (agents), a file as the source, the worktree a link is
# made in, what the plan token covers, and the states the files are left in when a step fails. The skills wrapper (packs link|unlink) is
# tested by tests/test_packs_link.sh. Offline, hermetic. Run: tests/test_linker.sh
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
# the engine refuses inside a member run (a directory `qargi local prepare` made, at or above the working directory), and this test may
# itself run in one: work from the temporary directory
# shellcheck source=fixtures.sh
. tests/fixtures.sh
cd "$T" || exit 1
STATE=$T/s; mkdir -p "$STATE"
G="git -c user.name=t -c user.email=t@example.net"
R=$T/repo
git init -q -b main "$R"; echo x > "$R/README"; $G -C "$R" add -A; $G -C "$R" commit -q -m one

# the engine has no command line of its own (the verbs are packs link and, later, the project verbs): this driver calls it as they do
cat > "$T/drv.py" <<'EOF'
import json, os, sys
sys.path.insert(0, sys.argv[1])
import linker
phase, verb, specfile = sys.argv[2:5]
spec = json.load(open(specfile))
if phase == "checkout":
    print(linker.resolve_checkout(spec["repo"], spec["cwd"]))
    sys.exit(0)
lk = linker.Link(spec["kind"], spec["project"], spec["checkout"], spec["dest"], spec["source"], spec["mode"], spec["state"], spec.get("words"))
if phase == "plan":
    tf = specfile + ".token"
    if os.path.exists(tf):
        os.unlink(tf)
    linker.cmd_plan(verb, lk, tf)
    if os.path.exists(tf):
        print("plan token: " + open(tf).read())
elif phase == "apply":
    linker.cmd_apply(verb, lk, sys.argv[5])
EOF
K=agents M=dir-symlink CO=$R DEST=.rt/agents SRC=$STATE/render/alpha/rt/agents
spec() { jq -n --arg kind "$K" --arg mode "$M" --arg dest "$DEST" --arg src "$SRC" --arg co "$CO" --arg st "$STATE" \
           '{kind:$kind,project:"alpha",checkout:$co,dest:$dest,source:$src,mode:$mode,state:$st}' > "$T/spec.json"; }
drv() { python3 -I "$T/drv.py" "$ROOT/lib" "$@"; }
pl() { spec; drv plan "$1" "$T/spec.json"; }                          # plan
ap() { spec; drv apply "$1" "$T/spec.json" "$2"; }                    # apply with a token
ptok() { pl "$1" 2>&1 | tok_of; }
go() { local tok; tok=$(ptok "$1"); [ -n "$tok" ] && ap "$1" "$tok"; }  # plan, then apply that plan
# a hash of everything under the given paths (names, link targets, contents), for "nothing changed"
snap() { find "$@" \( -type l -printf 'L %p -> %l\n' \) -o \( -type f -printf 'F %p\n' \) -o \( -type d -printf 'D %p\n' \) 2>/dev/null | sort | sha256sum
         find "$@" -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum | sha256sum; }
mkdir -p "$SRC"; printf 'a\n' > "$SRC/a.md"; printf 'b\n' > "$SRC/b.md"
L=$R/$DEST bk=$R/$DEST.qargi-backup

# --- a second resource kind, dir-symlink: the same plan, token, apply and undo as the skills directory
before=$(snap "$STATE")
out=$(pl link 2>&1); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && grep -q "^link plan for alpha: the checkout $R loads the project's agents from the source" <<<"$out" && grep -q "link:   $L" <<<"$out" && grep -q "target: $SRC" <<<"$out" && [ ! -e "$R/.rt" ] \
  && ok "agents: the plan names the link and its target, prints a token and writes nothing" || no "absent plan: $out"
ap link 000000000000 >/dev/null 2>&1 && no "applied with a wrong token" || ok "agents: apply refuses a wrong token"
[ ! -e "$R/.rt" ] && ok "agents: a refused apply writes nothing" || no "refused apply wrote"
out=$(ap link "$tok" 2>&1)
[ -L "$L" ] && [ "$(readlink "$L")" = "$SRC" ] && [ -f "$L/a.md" ] && grep -q "^linked: $L -> $SRC" <<<"$out" && ok "agents: apply creates the link, and it resolves" || no "apply: $out"
grep -q "git does not ignore .rt/agents" <<<"$out" && grep -q "^    .rt/agents$" <<<"$out" && ok "agents: an unignored link prints the line for .git/info/exclude" || no "hint: $out"
[ "$before" = "$(snap "$STATE")" ] && ok "agents: the source is not changed by linking" || no "source changed"
out=$(pl link 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^already linked: $L -> $SRC" <<<"$out" && [ -z "$(tok_of <<<"$out")" ] && ok "agents: linking again says already linked, with no token" || no "again: rc=$rc $out"
out=$(pl unlink 2>&1); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && grep -q "remove the symbolic link $L" <<<"$out" && grep -q "there is no backup, so .rt/agents will not exist afterwards" <<<"$out" && [ -L "$L" ] && ok "agents: the unlink plan prints a token and changes nothing" || no "unlink plan: $out"
ap unlink "$tok" >/dev/null 2>&1
[ ! -e "$L" ] && [ ! -L "$L" ] && [ -f "$SRC/a.md" ] && [ -d "$R/.rt" ] && ok "agents: unlink removes only the symbolic link" || no "unlink result"
out=$(pl unlink 2>&1) && no "unlinked what is not linked" || { grep -q "is not linked to the agents source of alpha; nothing to unlink" <<<"$out" && ok "agents: unlink with nothing linked is refused and says so" || no "unlink nothing: $out"; }

# --- a real directory: the user's own entries are moved to the backup beside it, and unlink puts them back
mkdir -p "$L"; echo mine > "$L/mine.md"; echo more > "$L/more.md"; cp -a "$L" "$T/real.snap"
out=$(pl link 2>&1); tok=$(tok_of <<<"$out")
grep -q "^  .rt/agents is a real directory; nothing in it is tracked by git" <<<"$out" && grep -q "entries moved with it: mine.md, more.md" <<<"$out" && grep -q "apply moves the directory to $bk (nothing is deleted)" <<<"$out" && ok "agents: a real directory is described and its backup named" || no "real plan: $out"
out=$(ap link "$tok" 2>&1)
[ -L "$L" ] && diff -r "$T/real.snap" "$bk" >/dev/null && grep -q "^backup: $bk (the former .rt/agents; qargi packs unlink alpha moves it back)" <<<"$out" && ok "agents: the directory is moved aside byte for byte and linked" || no "real apply: $out"
tok=$(ptok unlink); out=$(ap unlink "$tok" 2>&1)
[ -d "$L" ] && [ ! -L "$L" ] && [ ! -e "$bk" ] && diff -r "$T/real.snap" "$L" >/dev/null && grep -q "restored from $bk" <<<"$out" && ok "agents: unlink restores the directory byte for byte" || no "real unlink: $out"
out=$(pl unlink 2>&1) && no "unlink touched a real directory" || { grep -q "is not a symbolic link (a real .rt/agents has taken its place)" <<<"$out" && ok "agents: unlink refuses a real directory" || no "unlink real: $out"; }
rm -rf "$L"

# --- refusals: foreign link, backup in the way, tracked files, symbolic link in the parents
mkdir -p "$T/other"; ln -s "$T/other" "$L"
out=$(pl link 2>&1) && no "replaced a foreign link" || { grep -q "not to this project's agents source" <<<"$out" && ok "agents: a link to somewhere else is refused" || no "foreign: $out"; }
out=$(pl unlink 2>&1) && no "removed a foreign link" || { grep -q "not to this project's agents source" <<<"$out" && ok "agents: unlink refuses a foreign link" || no "unlink foreign: $out"; }
[ "$(readlink "$L")" = "$T/other" ] && ok "agents: the foreign link is untouched" || no "foreign changed"
rm "$L"; mkdir "$bk"; out=$(pl link 2>&1) && no "planned over a backup" || { grep -q "already exists; qargi packs unlink alpha moves it back" <<<"$out" || grep -q "already exists; move it away first" <<<"$out" && ok "agents: an existing backup is refused" || no "backup: $out"; }
rmdir "$bk"
mkdir -p "$L"; echo t > "$L/t.md"; git -C "$R" add -f .rt/agents; $G -C "$R" commit -q -m track
out=$(pl link 2>&1) && no "planned over tracked files" || { grep -q "tracked by git" <<<"$out" && grep -q "owner decides how its agents are loaded" <<<"$out" && ok "agents: tracked files are refused and the owner decides" || no "tracked: $out"; }
git -C "$R" rm -q -r --cached .rt/agents; $G -C "$R" commit -q -m untrack; rm -rf "$L"
tok=$(ptok link); [ -n "$tok" ] || no "setup: a plan before .rt becomes a link"
rm -rf "$R/.rt"; mkdir -p "$T/outside"; ln -s "$T/outside" "$R/.rt"
out=$(pl link 2>&1) && no "linked through a symlinked parent" || { grep -q "is a symbolic link; refusing" <<<"$out" && ok "agents: a symlinked parent is refused" || no "parent: $out"; }
out=$(ap link "$tok" 2>&1) && no "applied through a symlinked parent" || ok "agents: a plan made before the parent became a link is refused at apply"
[ -z "$(ls -A "$T/outside")" ] && ok "agents: nothing is written outside the checkout" || no "wrote outside"
rm "$R/.rt"

# --- the plan token covers the kind, the destination's state and the source
tok=$(ptok link)
K=skills; out=$(ap link "$tok" 2>&1) && no "a plan of another kind was applied" || { grep -q "the plan changed since it was approved" <<<"$out" && ok "token: a plan made for one resource kind is not valid for another" || no "kind token: $out"; }
tk=$(ptok link); [ -n "$tk" ] && [ "$tk" != "$tok" ] && ok "token: the same paths planned as another kind give another token" || no "same token for two kinds"
K=agents; [ ! -e "$R/.rt" ] && ok "token: the refused apply wrote nothing" || no "kind mismatch wrote"
[ "$(ptok link)" = "$tok" ] && ok "token: planning the same state twice gives the same token" || no "token not stable"

# --- a file as the source, a file as the link
K=notes DEST=docs/NOTES.md SRC=$STATE/render/alpha/NOTES.md
mkdir -p "$STATE/render/alpha"; echo "# notes" > "$SRC"
L=$R/$DEST bk=$R/$DEST.qargi-backup
out=$(go link 2>&1)
[ -L "$L" ] && [ "$(readlink "$L")" = "$SRC" ] && [ "$(cat "$L")" = "# notes" ] && ok "file: a file source is linked" || no "file link: $out"
ap unlink "$(ptok unlink)" >/dev/null 2>&1; [ ! -e "$L" ] && ok "file: unlink removes the link" || no "file unlink"
echo mine > "$L"
out=$(pl link 2>&1); grep -q "^  docs/NOTES.md is a real file; nothing in it is tracked by git" <<<"$out" && grep -q "apply moves the file to $bk" <<<"$out" && ok "file: a real file is described and its backup named" || no "file plan: $out"
out=$(go link 2>&1)
[ -L "$L" ] && [ "$(cat "$bk")" = mine ] && ok "file: the real file is moved aside and linked" || no "file apply: $out"
ap unlink "$(ptok unlink)" >/dev/null 2>&1
[ ! -L "$L" ] && [ "$(cat "$L")" = mine ] && [ ! -e "$bk" ] && ok "file: unlink puts the file back" || no "file restore"
rm -rf "$R/docs"
mkdir -p "$R/docs/NOTES.md"; out=$(pl link 2>&1) && no "a directory was taken for the file" || { grep -q "is not a file or a symbolic link" <<<"$out" && ok "file: a directory where a file was expected is refused" || no "file vs dir: $out"; }
rm -rf "$R/docs"
K=agents DEST=.rt/agents SRC=$STATE/render/alpha/rt/agents; L=$R/$DEST bk=$R/$DEST.qargi-backup

# --- the worktree a link is made in: the cwd's own checkout, and nothing is recorded anywhere else
$G -C "$R" worktree add -q "$T/wt" -b side
$G -C "$R" worktree add -q "$T/wt 2" -b side2
mkdir -p "$T/sub"; git init -q -b main "$T/unrelated"; mkdir -p "$T/wt/deep/er"
rc_of() { jq -n --arg r "$1" --arg c "$2" '{repo:$r,cwd:$c}' > "$T/rc.json"; drv checkout x "$T/rc.json"; }
[ "$(rc_of "$R" "$T/wt")" = "$(realpath "$T/wt")" ] && [ "$(rc_of "$R" "$T/wt/deep/er")" = "$(realpath "$T/wt")" ] && ok "worktree: the checkout is the top of the worktree the cwd is in" || no "checkout of a worktree: $(rc_of "$R" "$T/wt")"
[ "$(rc_of "$R" "$R")" = "$(realpath "$R")" ] && [ "$(rc_of "$R" "$T/sub")" = "$R" ] && [ "$(rc_of "$R" "$T/unrelated")" = "$R" ] && ok "worktree: outside any worktree of the project, or in another repository, it is the project's own checkout" || no "checkout fallback"
state_before=$(snap "$STATE"); main_before=$(snap "$R/.git" "$R/README"); wl=$(git -C "$R" worktree list)
CO=$T/wt; out=$(go link 2>&1)
[ -L "$T/wt/$DEST" ] && [ ! -e "$R/.rt" ] && [ ! -e "$T/wt 2/.rt" ] && ok "worktree: the link lands in that worktree only" || no "worktree link: $out"
[ "$state_before" = "$(snap "$STATE")" ] && [ "$main_before" = "$(snap "$R/.git" "$R/README")" ] && [ "$wl" = "$(git -C "$R" worktree list)" ] && ok "worktree: nothing is recorded in the state directory or the repository, and no worktree list is kept" || no "recorded something"
! grep -rIl "$T/wt" "$STATE" "$R/.git" 2>/dev/null | grep -v "^$R/.git/worktrees/" | grep -q . && ok "worktree: no stored file names the worktree" || no "a file names the worktree: $(grep -rIl "$T/wt" "$STATE" "$R/.git" 2>/dev/null | head -3)"
out=$(go link 2>&1)
CO=$R; out=$(pl link 2>&1); [ -n "$(tok_of <<<"$out")" ] && ok "worktree: the main checkout still has nothing linked" || no "main checkout: $out"
CO=$T/wt; ap unlink "$(ptok unlink)" >/dev/null 2>&1; [ ! -e "$T/wt/$DEST" ] && ok "worktree: unlink in the worktree removes its link" || no "worktree unlink"
CO="$T/wt 2"; out=$(go link 2>&1); [ -L "$T/wt 2/$DEST" ] && ok "worktree: a path with a space works" || no "worktree with space: $out"
ap unlink "$(ptok unlink)" >/dev/null 2>&1
CO=$T/sub; out=$(pl link 2>&1) && no "a directory that is not a work tree was accepted" || { grep -q "is not a directory\|not the top of a git work tree" <<<"$out" && ok "worktree: a path that is not the top of a work tree is refused" || no "not a work tree: $out"; }
CO=$T/wt/deep; out=$(pl link 2>&1) && no "a subdirectory of a work tree was accepted" || ok "worktree: a subdirectory of a work tree is not a checkout"
CO=$R

# --- the engine refuses inside a member run, whoever calls it
mkdir -p "$T/run/out"; : > "$T/run/ability"; : > "$T/run/refs.before"
tok=$(ptok link); spec
out=$(cd "$T/run/out" && python3 -I "$T/drv.py" "$ROOT/lib" apply link "$T/spec.json" "$tok" 2>&1) && no "applied in a member run" || { grep -q "packs link is not available in a member run" <<<"$out" && [ ! -e "$L" ] && ok "a member run never applies, and nothing is changed" || no "member run: $out"; }

# --- a step fails: where the files are (faults are injected with QARGI_TEST_FAULT)
mkreal() { rm -rf "$R/.rt"; mkdir -p "$L"; cp -a "$T/real.snap/." "$L/"; }
same_real() { [ -d "$L" ] && [ ! -L "$L" ] && diff -r "$T/real.snap" "$L" >/dev/null; }
strays() { local f; for f in "$R"/.rt/.qargi-*; do [ -e "$f" ] || [ -L "$f" ] && echo "$f"; done; }
mkreal; tok=$(ptok link)
out=$(QARGI_TEST_FAULT=after-tmp-link ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "The agents directory was not moved; nothing was changed" <<<"$out" && same_real && [ ! -e "$bk" ] && [ -z "$(strays)" ] && ok "fault: a stop before the move changes nothing and leaves no temporary link" || no "after-tmp-link: rc=$rc $out"
out=$(QARGI_TEST_FAULT=after-backup ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "The agents directory was moved and put back; nothing was changed" <<<"$out" && same_real && [ ! -e "$bk" ] && [ -z "$(strays)" ] && ok "fault: a stop after the move puts the directory back" || no "after-backup: rc=$rc $out"
out=$(QARGI_TEST_FAULT=after-backup,rollback ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "your agents are in $bk and $L does not exist" <<<"$out" && grep -q "mv $bk $L" <<<"$out" && ! grep -q "nothing was changed" <<<"$out" && [ ! -e "$L" ] && diff -r "$T/real.snap" "$bk" >/dev/null \
  && ok "fault: when the directory cannot be put back, the message says where the entries are and how to recover" || no "rollback: rc=$rc $out"
out=$(pl unlink 2>&1); tok2=$(tok_of <<<"$out")
[ -n "$tok2" ] && grep -q "is not linked, but the backup $bk exists" <<<"$out" && ap unlink "$tok2" >/dev/null 2>&1 && same_real && [ ! -e "$bk" ] && ok "fault: the recovery named works: unlink moves the backup back" || no "recovery: $out"
mkreal; go link >/dev/null 2>&1; tok=$(ptok unlink)
out=$(QARGI_TEST_FAULT=after-aside ap unlink "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "The link is in place and nothing was changed" <<<"$out" && [ "$(readlink "$L")" = "$SRC" ] && [ -z "$(strays)" ] && ok "fault: unlink stopped after the link was moved aside puts it back" || no "after-aside: rc=$rc $out"
out=$(QARGI_TEST_FAULT=after-aside,rollback ap unlink "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "it is at $R/.rt/.qargi-unlink\.[0-9]* and $L does not exist; your agents are in $bk" <<<"$out" && [ ! -e "$L" ] && [ -n "$(strays)" ] && diff -r "$T/real.snap" "$bk" >/dev/null \
  && ok "fault: when the link cannot be put back, the message names where it is and where the entries are" || no "unlink rollback: $out"
rm -f "$R"/.rt/.qargi-unlink.*; rm -rf "$bk" "$L"

# --- a checkout path with a space and a quote: what the message tells the owner to paste is quoted
QR="$T/it's a repo"; git init -q -b main "$QR"; echo x > "$QR/README"; $G -C "$QR" add -A; $G -C "$QR" commit -q -m one
CO=$QR L=$QR/$DEST bk=$QR/$DEST.qargi-backup; mkdir -p "$L"; echo mine > "$L/m.md"
tok=$(ptok link); out=$(QARGI_TEST_FAULT=after-backup,rollback ap link "$tok" 2>&1)
line=$(sed -n 's/.* or mv \(.*\)\. Nothing was deleted\./\1/p' <<<"$out")
eval "set -- $line"; [ "$#" = 2 ] && [ "$1" = "$bk" ] && [ "$2" = "$L" ] && ok "the recovery command in a message is shell-quoted" || no "recovery quoting: $line / $out"
CO=$R L=$R/$DEST bk=$R/$DEST.qargi-backup

# --- entry-symlinks: the directory stays real, one link per entry, only qargi's own links are ever touched
M=entry-symlinks DEST=.rt2/agents SRC=$STATE/render/alpha/ent CO=$R; L=$R/$DEST
mkdir -p "$SRC/sub" "$L"; printf 'a\n' > "$SRC/a.md"; printf 'b\n' > "$SRC/b.md"; echo s > "$SRC/sub/f"; echo h > "$SRC/.hidden"
echo mine > "$L/mine.md"; ln -s "$T/other" "$L/ext.md"
before=$(snap "$STATE" "$L")
out=$(pl link 2>&1); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && grep -q "^link plan for alpha: the checkout $R loads the project's agents from the source, one link per entry" <<<"$out" && grep -qE "^ +create +a.md" <<<"$out" && grep -qE "^ +create +sub" <<<"$out" \
  && grep -qE "^ +skipped +.hidden" <<<"$out" && grep -q "entries that are not qargi's are left alone" <<<"$out" && [ "$before" = "$(snap "$STATE" "$L")" ] && ok "entries: the plan lists each entry, skips what is hidden, prints a token and writes nothing" || no "entries plan: $out"
out=$(ap link "$tok" 2>&1)
[ -d "$L" ] && [ ! -L "$L" ] && [ -L "$L/a.md" ] && [ "$(readlink "$L/a.md")" = "$SRC/a.md" ] && [ -L "$L/sub" ] && [ -f "$L/sub/f" ] && [ ! -e "$L/.hidden" ] && [ ! -e "$L.qargi-backup" ] && ok "entries: the directory stays real and each entry is a link into the source, with no backup" || no "entries apply: $out"
[ "$(cat "$L/mine.md")" = mine ] && [ ! -L "$L/mine.md" ] && [ "$(readlink "$L/ext.md")" = "$T/other" ] && ok "entries: the user's own file and a foreign link are untouched" || no "own entries changed"
grep -q "^linked: $L: 3 entries from $SRC" <<<"$out" && grep -q "^  created a.md" <<<"$out" && grep -q "git does not ignore" <<<"$out" && grep -q "^    .rt2/agents/a.md$" <<<"$out" && ok "entries: the result is listed and the links git does not ignore are named" || no "entries output: $out"
out=$(pl link 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^already linked: $L -> $SRC" <<<"$out" && [ -z "$(tok_of <<<"$out")" ] && ok "entries: running link again says already linked, with no token" || no "entries again: rc=$rc $out"
out=$(ap link "$tok" 2>&1) && no "an old token was applied to a linked directory" || { grep -q "the plan changed since it was approved" <<<"$out" && ok "entries: the old token is refused once everything is linked" || no "old token: $out"; }
# a stale link of ours goes, a source entry that is new is linked, a link of ours that points at the wrong entry is changed
rm "$SRC/b.md"; printf 'c\n' > "$SRC/c.md"; rm "$L/a.md"; ln -s "$SRC/b.md" "$L/a.md"
out=$(pl link 2>&1); tok=$(tok_of <<<"$out")
grep -qE "^ +remove +b.md +\(a link of ours; the source has no entry" <<<"$out" && grep -qE "^ +create +c.md" <<<"$out" && grep -qE "^ +relink +a.md" <<<"$out" && grep -qE "^ +keep +sub" <<<"$out" && ok "entries: the plan says what is created, kept, relinked and removed" || no "mixed plan: $out"
ap link "$tok" >/dev/null 2>&1
[ ! -e "$L/b.md" ] && [ ! -L "$L/b.md" ] && [ "$(readlink "$L/a.md")" = "$SRC/a.md" ] && [ "$(readlink "$L/c.md")" = "$SRC/c.md" ] && [ "$(cat "$L/mine.md")" = mine ] && [ "$(readlink "$L/ext.md")" = "$T/other" ] && ok "entries: the stale link is removed, the wrong one changed, the new one made, the foreign ones kept" || no "mixed apply: $(ls -la "$L")"
# collisions: a real entry (file or directory) or a foreign link where an entry is to go
printf 'd\n' > "$SRC/d.md"; echo real > "$L/d.md"
out=$(pl link 2>&1) && no "planned over a real file" || { grep -q "$L/d.md exists and is a real file that qargi did not make; refusing to replace it" <<<"$out" && ok "entries: a name collision with a real file is refused" || no "collision file: $out"; }
rm "$L/d.md"; mkdir "$L/d.md"; out=$(pl link 2>&1) && no "planned over a real directory" || { grep -q "d.md exists and is a real directory" <<<"$out" && ok "entries: a name collision with a real directory is refused" || no "collision dir: $out"; }
rmdir "$L/d.md"; ln -s "$T/other" "$L/d.md"; out=$(pl link 2>&1) && no "planned over a foreign link" || { grep -q "d.md is a symbolic link to $T/other, not into this project's agents source" <<<"$out" && ok "entries: a name collision with a foreign link is refused" || no "collision link: $out"; }
[ "$(readlink "$L/d.md")" = "$T/other" ] && [ ! -e "$L/d.md.new" ] && ok "entries: a refused plan creates nothing, not even the entries that were free" || no "collision wrote"
rm "$L/d.md"; rm "$SRC/d.md"
# tracked
printf 'e\n' > "$SRC/e.md"; ln -s "$SRC/e.md" "$L/e.md"; git -C "$R" add -f .rt2/agents/e.md; $G -C "$R" commit -q -m trk; rm "$L/e.md"; ln -s "$T/other" "$L/e.md"
out=$(pl link 2>&1) && no "planned over a tracked path" || ok "entries: an entry that git tracks is refused"
git -C "$R" rm -q --cached .rt2/agents/e.md; $G -C "$R" commit -q -m untrk; rm -f "$L/e.md" "$SRC/e.md"
# unlink
out=$(pl unlink 2>&1); tok=$(tok_of <<<"$out")
grep -q "^unlink plan for alpha: remove the 3 links in $L that point into $SRC" <<<"$out" && ! grep -q "mine.md\|ext.md" <<<"$out" && ok "entries: the unlink plan names only the links of ours" || no "unlink plan: $out"
ap unlink "$tok" >/dev/null 2>&1
[ ! -L "$L/a.md" ] && [ ! -L "$L/c.md" ] && [ ! -L "$L/sub" ] && [ -d "$L" ] && [ "$(cat "$L/mine.md")" = mine ] && [ "$(readlink "$L/ext.md")" = "$T/other" ] && ok "entries: unlink removes our links and keeps the directory and everything else" || no "unlink apply: $(ls -la "$L")"
out=$(pl unlink 2>&1) && no "unlinked with nothing of ours" || { grep -q "has no entry linked to the agents source of alpha; nothing to unlink" <<<"$out" && ok "entries: unlink with nothing of ours is refused" || no "unlink nothing: $out"; }
# the directory does not exist yet: it is made; and a stop afterwards removes it again
rm -rf "$R/.rt2"; tok=$(ptok link)
out=$(QARGI_TEST_FAULT=after-entry-1 ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "injected fault after-entry-1" <<<"$out" && grep -q "2 changes were made and put back; nothing was changed (a missing directory above it may have been created, empty)" <<<"$out" && [ ! -e "$L" ] && [ -z "$(ls -A "$R/.rt2")" ] && ok "entries fault: a stop after the first link undoes it and the directory made for it" || no "fault absent: rc=$rc $out; $(ls -A "$R")"
# a stop with the undo failing: where the links are is told
mkdir -p "$L"; echo mine > "$L/mine.md"; printf "x\n" > "$SRC/it's me.md"; tok=$(ptok link)
out=$(QARGI_TEST_FAULT=after-entry-2,rollback ap link "$tok" 2>&1); rc=$?
n=$(find "$L" -maxdepth 1 -type l | wc -l)
[ "$rc" != 0 ] && grep -q "2 of 2 changes could not be put back: created the link c.md; created the link a.md" <<<"$out" && grep -q "Run the same command again to finish it" <<<"$out" && ! grep -q "nothing was changed" <<<"$out" && [ "$n" = 2 ] && [ "$(cat "$L/mine.md")" = mine ] && ok "entries fault: when the undo fails, the message says what stays and how to finish" || no "fault rollback: rc=$rc n=$n $out"
out=$(go link 2>&1); n=$(find "$L" -maxdepth 1 -type l | wc -l)
[ "$n" = 4 ] && [ "$(readlink "$L/a.md")" = "$SRC/a.md" ] && ok "entries fault: running link again finishes the job from there" || no "finish: n=$n $out"
# a stop during unlink puts the links back
tok=$(ptok unlink)
out=$(QARGI_TEST_FAULT=after-entry-2 ap unlink "$tok" 2>&1); rc=$?
n2=$(find "$L" -maxdepth 1 -type l | wc -l)
[ "$rc" != 0 ] && grep -q "2 changes were made and put back; nothing was changed" <<<"$out" && [ "$n2" = 4 ] && [ "$(readlink "$L/sub")" = "$SRC/sub" ] && ok "entries fault: a stop during unlink puts the removed links back" || no "unlink fault: rc=$rc n=$n2 $out"
# names: quoted and without control characters in the plan; a name with a quote and a space is created
out=$(pl unlink 2>&1); line=$(sed -n "s/^ *remove  *\('it.*\)\$/\1/p" <<<"$out")
eval "set -- $line"; [ "$#" = 1 ] && [ "$1" = "it's me.md" ] && ok "entries: a name with a quote and a space is shell-quoted in the plan" || no "name quoting: $line / $out"
ap unlink "$(ptok unlink)" >/dev/null 2>&1; rm -f "$SRC/it's me.md"
esc=$(printf 'x\033[31mred.md'); ln -s "$SRC/gone.md" "$L/$esc"; mkdir -p "$SRC"; printf 'z\n' > "$SRC/$(printf 'y\033[31mred.md')"
out=$(pl link 2>&1)
! LC_ALL=C tr -d '\n' <<<"$out" | grep -q '[[:cntrl:]]' && grep -qE "^ +skipped" <<<"$out" && grep -qE "^ +remove +'?x\[31mred.md" <<<"$out" && ok "entries: a control character in a name is never printed; a source name with one is skipped" || no "control chars: $out"
ap link "$(ptok link)" >/dev/null 2>&1; [ ! -L "$L/$esc" ] && ok "entries: a stale link of ours is removed whatever its name" || no "esc link kept"
rm -f "$SRC"/y*; ap unlink "$(ptok unlink)" >/dev/null 2>&1
# the plan token covers the source listing and the classification
tok=$(ptok link)
printf 'late\n' > "$SRC/late.md"; out=$(ap link "$tok" 2>&1) && no "a plan was applied after the source gained an entry" || { grep -q "the plan changed since it was approved" <<<"$out" && ok "token: an entry added to the source after the plan makes the plan stale" || no "token source: $out"; }
tok=$(ptok link); echo real > "$L/late.md" ; ln -sf "$SRC/c.md" "$L/zz.md"; out=$(ap link "$tok" 2>&1) && no "a plan was applied after a collision appeared" || ok "token: a collision that appears after the plan is refused at apply"
rm -f "$L/late.md" "$L/zz.md"; tok=$(ptok link)
ln -s "$SRC/c.md" "$L/zz.md"; out=$(ap link "$tok" 2>&1) && no "a plan was applied after a stale link appeared" || { grep -q "the plan changed" <<<"$out" && ok "token: a stale link of ours that appears after the plan makes the plan stale" || no "token stale: $out"; }
rm -f "$L/zz.md" "$SRC/late.md"; ap unlink "$(ptok unlink)" >/dev/null 2>&1
# between the plan and the apply: an entry appears where a link was to go; nothing else is made
tok=$(ptok link); held() { rm -f "$T"/hold.*; ( QARGI_TEST_HOLD=$T/hold "$@" >"$T/held.out" 2>&1; echo $? >"$T/held.rc" ) & HELD=$!; for _ in $(seq 300); do [ -e "$T/hold.reached" ] && return 0; sleep 0.1; done; return 1; }
release() { : > "$T/hold.go"; wait "$HELD"; HRC=$(cat "$T/held.rc"); HOUT=$(cat "$T/held.out"); }
held ap link "$tok" || no "setup: the hold was not reached"
echo late > "$L/c.md"; release
[ "$HRC" != 0 ] && grep -q "c.md exists now (it did not when the plan was made)" <<<"$HOUT" && [ "$(find "$L" -maxdepth 1 -type l | wc -l)" = 0 ] && [ "$(cat "$L/c.md")" = late ] && ok "entries: an entry that appears between the plan and the apply is left alone and nothing else is made" || no "late entry: rc=$HRC $HOUT; $(ls -la "$L")"
rm -f "$L/c.md"
tok=$(ptok link); held ap link "$tok" || no "setup: the hold was not reached"
mv "$R/.rt2" "$T/rt2.moved"; mkdir -p "$T/elsewhere3"; ln -s "$T/elsewhere3" "$R/.rt2"; release
[ "$HRC" != 0 ] && grep -q "is a symbolic link or not a directory now" <<<"$HOUT" && [ -z "$(ls -A "$T/elsewhere3")" ] && ok "entries: a parent that became a link between the plan and the apply is refused and nothing is written through it" || no "swapped parent: rc=$HRC $HOUT"
rm "$R/.rt2"; mv "$T/rt2.moved" "$R/.rt2"
rm -rf "$R/.rt2"
# the destination or a parent is not what is expected
tok=$(ptok link)
mkdir -p "$R/.rt2"; ln -s "$T/outside" "$R/.rt2/agents"; out=$(pl link 2>&1) && no "linked into a destination that is a symlink" || { grep -q "$L is a symbolic link; refusing (mode entry-symlinks keeps a real directory" <<<"$out" && ok "entries: a destination that is a symbolic link is refused" || no "dest link: $out"; }
rm "$R/.rt2/agents"; echo f > "$R/.rt2/agents"; out=$(pl link 2>&1) && no "linked into a file" || { grep -q "exists and is not a directory; refusing" <<<"$out" && ok "entries: a destination that is a file is refused" || no "dest file: $out"; }
rm -rf "$R/.rt2"; ln -s "$T/outside" "$R/.rt2"
out=$(pl link 2>&1) && no "linked through a symlinked parent" || { grep -q "$R/.rt2 is a symbolic link; refusing" <<<"$out" && ok "entries: a symlinked parent is refused" || no "parent link: $out"; }
out=$(ap link "$tok" 2>&1) && no "applied through a symlinked parent" || ok "entries: a plan made before the parent became a link is refused at apply"
out=$(pl unlink 2>&1) && no "unlinked through a symlinked parent" || ok "entries: unlink through a symlinked parent is refused"
[ -z "$(ls -A "$T/outside")" ] && ok "entries: nothing is written outside the checkout" || no "entries wrote outside"
rm "$R/.rt2"
# the worktree
CO=$T/wt; out=$(go link 2>&1)
[ -L "$T/wt/$DEST/a.md" ] && [ ! -e "$R/.rt2" ] && ok "entries: in a worktree the links land in that worktree only" || no "entries worktree: $out"
ap unlink "$(ptok unlink)" >/dev/null 2>&1; CO=$R
# a member run never applies
tok=$(ptok link); spec
out=$(cd "$T/run/out" && python3 -I "$T/drv.py" "$ROOT/lib" apply link "$T/spec.json" "$tok" 2>&1) && no "applied in a member run" || { grep -q "is not available in a member run" <<<"$out" && [ ! -e "$R/.rt2" ] && ok "entries: a member run never applies" || no "entries member run: $out"; }
M=dir-symlink; rm -rf "$SRC"

# --- copy: for runtimes that do not follow links; the copies are recorded beside the directory and only an unmodified copy is replaced or removed
M=copy DEST=.rt3/agents SRC=$STATE/render/alpha/cp CO=$R; L=$R/$DEST MF=$R/$DEST.qargi-copy.json
mkdir -p "$SRC/sub" "$L"; printf 'a\n' > "$SRC/a.md"; printf 'b\n' > "$SRC/b.md"; echo s > "$SRC/sub/f"; printf '#!/bin/sh\n' > "$SRC/sub/run.sh"; chmod +x "$SRC/sub/run.sh"; echo h > "$SRC/.hidden"
echo mine > "$L/mine.md"
strays_cp() { find "$R/.rt3" -name '.qargi-*' | grep . ; }
before=$(snap "$STATE" "$L")
out=$(pl link 2>&1); tok=$(tok_of <<<"$out")
[ -n "$tok" ] && grep -q "^link plan for alpha: the checkout $R loads the project's agents from the source, as copies" <<<"$out" && grep -q "manifest:  $MF" <<<"$out" && grep -qE "^ +create +a.md" <<<"$out" && grep -qE "^ +create +sub" <<<"$out" \
  && grep -qE "^ +skipped +.hidden" <<<"$out" && [ "$before" = "$(snap "$STATE" "$L")" ] && [ ! -e "$MF" ] && ok "copy: the plan lists each entry and the manifest, prints a token and writes nothing" || no "copy plan: $out"
out=$(ap link "$tok" 2>&1)
[ -d "$L" ] && [ ! -L "$L" ] && [ -f "$L/a.md" ] && [ ! -L "$L/a.md" ] && cmp -s "$L/a.md" "$SRC/a.md" && cmp -s "$L/sub/f" "$SRC/sub/f" && [ -x "$L/sub/run.sh" ] && [ ! -x "$L/sub/f" ] && [ ! -e "$L/.hidden" ] \
  && ok "copy: the entries are real copies (files and directories, the executable bit kept)" || no "copy apply: $out; $(ls -laR "$L")"
[ "$(jq -r '.schema, .kind, .source' "$MF" | tr '\n' ' ')" = "1 agents $SRC " ] && [ "$(jq -r '.entries | keys | join(",")' "$MF")" = "a.md,b.md,sub" ] && [ "$(jq -r '.entries | to_entries[] | .value.hash | length' "$MF" | sort -u)" = 32 ] && ok "copy: the manifest beside the directory records the kind, the source and a hash for each copy" || no "manifest: $(cat "$MF")"
[ "$(cat "$L/mine.md")" = mine ] && ! strays_cp >/dev/null && grep -q "^linked: $L: 3 copies from $SRC" <<<"$out" && ok "copy: the user's own file is untouched and no temporary file is left" || no "copy own/strays: $out"
out=$(pl link 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^already linked: $L -> $SRC" <<<"$out" && [ -z "$(tok_of <<<"$out")" ] && ok "copy: running link again says already linked, with no token" || no "copy again: rc=$rc $out"
# the source changed: an unmodified copy is updated; one the source dropped is removed
printf 'a2\n' > "$SRC/a.md"; rm "$SRC/b.md"; printf 'c\n' > "$SRC/c.md"
out=$(pl link 2>&1); tok=$(tok_of <<<"$out")
grep -qE "^ +update +a.md" <<<"$out" && grep -qE "^ +remove +b.md" <<<"$out" && grep -qE "^ +create +c.md" <<<"$out" && grep -qE "^ +keep +sub" <<<"$out" && ok "copy: the plan says what is updated, removed, created and kept" || no "copy update plan: $out"
ap link "$tok" >/dev/null 2>&1
[ "$(cat "$L/a.md")" = a2 ] && [ ! -e "$L/b.md" ] && [ "$(cat "$L/c.md")" = c ] && [ "$(jq -r '.entries | keys | join(",")' "$MF")" = "a.md,c.md,sub" ] && ! strays_cp >/dev/null && [ "$(cat "$L/mine.md")" = mine ] && ok "copy: update, removal and creation are done, the manifest follows, no old copy is left" || no "copy update apply: $(ls -la "$L"; cat "$MF")"
# a modified copy is never touched
cp -a "$L" "$T/cp.snap"; echo edited >> "$L/a.md"
out=$(pl link 2>&1) && no "planned over a modified copy" || { grep -q "$L/a.md was changed since qargi copied it" <<<"$out" && ok "copy: a modified copy makes link refuse, and the message names it" || no "modified link: $out"; }
out=$(pl unlink 2>&1) && no "unlink planned over a modified copy" || { grep -q "$L/a.md was changed since qargi copied it" <<<"$out" && ok "copy: a modified copy makes unlink refuse" || no "modified unlink: $out"; }
echo more >> "$SRC/a.md"; out=$(pl link 2>&1) && no "planned an update over a modified copy" || ok "copy: a modified copy is not overwritten even when the source changed"
sed -i '$d' "$SRC/a.md"; sed -i '$d' "$L/a.md"; [ "$(cat "$L/a.md")" = a2 ] || no "setup: a.md back to a2"
echo x >> "$L/sub/f"; out=$(pl link 2>&1) && no "planned over a copy modified deep inside" || ok "copy: a change deep inside a copied directory counts"
cp "$SRC/sub/f" "$L/sub/f"; chmod +x "$L/sub/f"; out=$(pl link 2>&1) && no "planned over a copy whose executable bit changed" || ok "copy: so does an executable bit"
chmod -x "$L/sub/f"; echo n > "$L/sub/new"; out=$(pl link 2>&1) && no "planned over a copy with an added file" || ok "copy: so does an added file"
rm "$L/sub/new"; ln -s a "$L/sub/lnk"; out=$(pl link 2>&1) && no "planned over a copy with a symlink" || ok "copy: so does a symbolic link"
rm "$L/sub/lnk"; echo stale > "$SRC/gone.md"; ap link "$(ptok link)" >/dev/null 2>&1; rm "$SRC/gone.md"; echo edit >> "$L/gone.md"
out=$(pl link 2>&1) && no "planned to remove a modified stale copy" || ok "copy: a modified copy the source dropped is not removed either"
rm "$L/gone.md"; out=$(pl link 2>&1); tok=$(tok_of <<<"$out"); grep -qE "^ +forget +gone.md" <<<"$out" && ok "copy: a recorded copy that is gone is forgotten" || no "forget: $out"
ap link "$tok" >/dev/null 2>&1; [ "$(jq -r '.entries | keys | join(",")' "$MF")" = "a.md,c.md,sub" ] && ok "copy: forgetting drops it from the manifest" || no "forget apply: $(cat "$MF")"
diff -r "$T/cp.snap" "$L" >/dev/null && ok "copy: after all of that the copies are as they were" || no "copies changed: $(diff -r "$T/cp.snap" "$L")"
# a deleted copy is made again
rm "$L/c.md"; out=$(pl link 2>&1); grep -qE "^ +create +c.md" <<<"$out" && ok "copy: a copy the user deleted is made again" || no "recreate: $out"
ap link "$(ptok link)" >/dev/null 2>&1
# collisions: something qargi did not make where a copy goes
printf 'd\n' > "$SRC/d.md"; echo real > "$L/d.md"
out=$(pl link 2>&1) && no "planned over a real file" || { grep -q "$L/d.md exists and qargi did not make it; refusing to replace it" <<<"$out" && ok "copy: a name collision with a real entry is refused" || no "copy collision: $out"; }
rm "$L/d.md"; ln -s "$T/other" "$L/d.md"; out=$(pl link 2>&1) && no "planned over a foreign link" || ok "copy: a name collision with a foreign link is refused"
rm "$L/d.md"; rm "$SRC/d.md"
ln -s "$T/other" "$SRC/lnk"; printf 'zz\n' > "$SRC/zz.md"; out=$(pl link 2>&1); [ -n "$(tok_of <<<"$out")" ] && grep -qE "^ +skipped +lnk" <<<"$out" && ok "copy: a symbolic link in the source's top level is skipped" || no "source link top: $out"
rm "$SRC/lnk" "$SRC/zz.md"; ln -s "$T/other" "$SRC/sub/inner"; out=$(pl link 2>&1) && no "copied a directory holding a symlink" || { grep -q "neither a regular file nor a directory" <<<"$out" && ok "copy: a symbolic link inside a source entry is refused (copy never follows)" || no "source link inside: $out"; }
rm "$SRC/sub/inner"
# the manifest must be ours
cp -a "$MF" "$T/mf.snap"
echo '{"schema":1}' > "$MF"; out=$(pl link 2>&1) && no "used a manifest without entries" || { grep -q "is not a manifest qargi wrote" <<<"$out" && ok "copy: a manifest that is not ours is refused" || no "bad manifest: $out"; }
jq '.source = "/elsewhere"' "$T/mf.snap" > "$MF"; out=$(pl unlink 2>&1) && no "used a manifest of another source" || { grep -q "belongs to another link" <<<"$out" && ok "copy: a manifest of another source is refused" || no "other manifest: $out"; }
rm "$MF"; ln -s "$T/mf.snap" "$MF"; out=$(pl link 2>&1) && no "used a manifest that is a symbolic link" || ok "copy: a manifest that is a symbolic link is refused"
rm "$MF"; cp -a "$T/mf.snap" "$MF"
out=$(pl link 2>&1); [ -z "$(tok_of <<<"$out")" ] && ok "copy: the manifest restored, the plan is back to already linked" || no "restored manifest: $out"
# tracked
git -C "$R" add -f .rt3/agents.qargi-copy.json; $G -C "$R" commit -q -m trk; printf 'c2\n' > "$SRC/c.md"
out=$(pl link 2>&1) && no "planned over a tracked manifest" || { grep -q "tracked by git" <<<"$out" && ok "copy: a tracked manifest is refused" || no "tracked manifest: $out"; }
git -C "$R" rm -q --cached .rt3/agents.qargi-copy.json; $G -C "$R" commit -q -m untrk; printf 'c\n' > "$SRC/c.md"
git -C "$R" add -f .rt3/agents/a.md; $G -C "$R" commit -q -m trk; printf 'a3\n' > "$SRC/a.md"
out=$(pl link 2>&1) && no "planned to update a tracked copy" || { grep -q "tracked by git" <<<"$out" && ok "copy: a tracked copy is refused" || no "tracked copy: $out"; }
git -C "$R" rm -q --cached .rt3/agents/a.md; $G -C "$R" commit -q -m untrk; printf 'a2\n' > "$SRC/a.md"
# the plan token covers the mode and the content, not only the names
tok=$(ptok link); printf 'a4\n' > "$SRC/a.md"; out=$(ap link "$tok" 2>&1) && no "applied after the source content changed" || { grep -q "the plan changed since it was approved" <<<"$out" && ok "token: a changed source file with the same listing makes the plan stale" || no "token content: $out"; }
printf 'a2\n' > "$SRC/a.md"
tok=$(ptok link); printf 'c3\n' > "$SRC/c.md"; tk=$(ptok link); printf 'c\n' > "$SRC/c.md"
[ -n "$tk" ] && [ "$tk" != "$tok" ] && ok "token: the copy's plan token depends on the content of the source" || no "content not in token"
DEST=.rt4/agents; tk=$(ptok link); M=entry-symlinks; tl=$(ptok link); M=copy; DEST=.rt3/agents
[ -n "$tk" ] && [ -n "$tl" ] && [ "$tk" != "$tl" ] && ok "token: the same paths planned in another mode give another token" || no "mode not in token"
# a change of the source between the plan and the apply
printf 'u\n' > "$SRC/a.md"; tok=$(ptok link); held ap link "$tok" || no "setup: the hold was not reached"
printf 'v\n' > "$SRC/a.md"; release
[ "$HRC" != 0 ] && grep -q "$SRC/a.md changed in the source since the plan was made" <<<"$HOUT" && [ "$(cat "$L/a.md")" = a2 ] && ok "copy: a source that changes between the plan and the apply changes nothing" || no "late source: rc=$HRC $HOUT"
printf 'a2\n' > "$SRC/a.md"
printf 'a8\n' > "$SRC/a.md"; tok=$(ptok link); held ap link "$tok" || no "setup: the hold was not reached"
echo late > "$L/a.md"; release
[ "$HRC" != 0 ] && grep -q "$L/a.md is not the copy the plan saw" <<<"$HOUT" && [ "$(cat "$L/a.md")" = late ] && ok "copy: a copy edited between the plan and the apply is left alone" || no "late edit: rc=$HRC $HOUT"
printf 'a2\n' > "$SRC/a.md"; printf 'a2\n' > "$L/a.md"
# faults: where the files are
snapcp=$(snap "$L" "$MF"); printf 'a9\n' > "$SRC/a.md"; printf 'n1\n' > "$SRC/n1.md"; tok=$(ptok link)
out=$(QARGI_TEST_FAULT=after-copy ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "injected fault after-copy" <<<"$out" && grep -q "made and put back; nothing was changed" <<<"$out" && [ "$snapcp" = "$(snap "$L" "$MF")" ] && ! strays_cp >/dev/null && ok "copy fault: a stop with a copy half placed changes nothing, and removes the temporary copy" || no "after-copy: rc=$rc $out"
out=$(QARGI_TEST_FAULT=after-entry-1 ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "changes were made and put back; nothing was changed\|change was made and put back; nothing was changed" <<<"$out" && [ "$snapcp" = "$(snap "$L" "$MF")" ] && [ "$(cat "$L/a.md")" = a2 ] && ! strays_cp >/dev/null && ok "copy fault: a stop after the first change puts the old copy and the manifest back" || no "after-entry-1: rc=$rc $out"
out=$(QARGI_TEST_FAULT=after-entry-1,rollback ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "3 of 3 changes could not be put back" <<<"$out" && grep -q "Run the same command again to finish it" <<<"$out" && ! grep -q "nothing was changed" <<<"$out" && [ "$(cat "$L/a.md")" = a9 ] && [ ! -e "$L/n1.md" ] \
  && ok "copy fault: when the undo fails the message says so and how to finish" || no "copy rollback: rc=$rc $out"
a_old=$(find "$L" -name '.qargi-old.*' | head -1); [ -n "$a_old" ] && [ "$(cat "$a_old")" = a2 ] && ok "copy fault: the replaced copy is kept under its temporary name, with its content" || no "aside: $(ls -la "$L")"
out=$(pl link 2>&1) ; tok=$(tok_of <<<"$out"); grep -qE "^ +keep +a.md" <<<"$out" && grep -qE "^ +create +n1.md" <<<"$out" && ok "copy fault: after the failed undo the next plan keeps what was done and creates what is left" || no "replan after fault: $out"
rm -rf "$L"/.qargi-old.*; ap link "$tok" >/dev/null 2>&1; out=$(pl link 2>&1); grep -q "^already linked" <<<"$out" && [ "$(cat "$L/a.md")" = a9 ] && ok "copy fault: running link again finishes the job" || no "finish copy: $out"
tok=$(ptok unlink); out=$(QARGI_TEST_FAULT=after-entry-1 ap unlink "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && [ -f "$L/a.md" ] && [ -f "$L/n1.md" ] && [ -f "$L/sub/f" ] && [ -f "$MF" ] && ! strays_cp >/dev/null && ok "copy fault: a stop during unlink puts the removed copy back" || no "copy unlink fault: rc=$rc $out; $(ls -la "$L")"
# unlink
out=$(pl unlink 2>&1); tok=$(tok_of <<<"$out")
grep -q "^unlink plan for alpha: remove the 4 copies qargi made in $L (all unmodified), and the manifest" <<<"$out" && ! grep -q "mine.md" <<<"$out" && ok "copy: the unlink plan names only the copies of ours" || no "copy unlink plan: $out"
ap unlink "$tok" >/dev/null 2>&1
[ "$(ls -A "$L")" = mine.md ] && [ ! -e "$MF" ] && ! strays_cp >/dev/null && ok "copy: unlink removes the copies and the manifest and keeps everything else" || no "copy unlink apply: $(ls -la "$L" "$R/.rt3")"
out=$(pl unlink 2>&1) && no "unlinked with nothing recorded" || { grep -q "has no copy recorded in $MF; nothing to unlink" <<<"$out" && ok "copy: unlink with nothing recorded is refused" || no "copy unlink nothing: $out"; }
# the directory does not exist yet
rm -rf "$R/.rt3"; tok=$(ptok link)
out=$(QARGI_TEST_FAULT=after-entry-2 ap link "$tok" 2>&1); rc=$?
[ "$rc" != 0 ] && [ ! -e "$L" ] && [ ! -e "$MF" ] && ok "copy fault: the directory and manifest made by a failed link are removed again" || no "copy absent fault: rc=$rc $out; $(ls -la "$R/.rt3")"
out=$(go link 2>&1); [ -f "$L/sub/run.sh" ] && [ -f "$MF" ] && ok "copy: the directory and manifest are made when missing" || no "copy absent: $out"
# names: shell-quoted, no control characters; a name with a quote and a space is copied
printf 'q\n' > "$SRC/it's me.md"; printf 'z\n' > "$SRC/$(printf 'y\033[31mred.md')"
out=$(pl link 2>&1); line=$(sed -n "s/^ *create  *\('it.*\)\$/\1/p" <<<"$out")
eval "set -- $line"; [ "$#" = 1 ] && [ "$1" = "it's me.md" ] && ! LC_ALL=C tr -d '\n' <<<"$out" | grep -q '[[:cntrl:]]' && grep -qE "^ +skipped" <<<"$out" && ok "copy: names are shell-quoted, control characters are never printed and such a source name is skipped" || no "copy names: $line / $out"
rm -f "$SRC"/y* "$SRC/it's me.md"
# parents and the destination
ap unlink "$(ptok unlink)" >/dev/null 2>&1
tok=$(ptok link); rm -rf "$R/.rt3"; ln -s "$T/outside" "$R/.rt3"
out=$(pl link 2>&1) && no "copied through a symlinked parent" || { grep -q "$R/.rt3 is a symbolic link; refusing" <<<"$out" && ok "copy: a symlinked parent is refused" || no "copy parent: $out"; }
out=$(ap link "$tok" 2>&1) && no "applied through a symlinked parent" || ok "copy: a plan made before the parent became a link is refused at apply"
out=$(pl unlink 2>&1) && no "unlinked through a symlinked parent" || ok "copy: unlink through a symlinked parent is refused"
[ -z "$(ls -A "$T/outside")" ] && ok "copy: nothing is written outside the checkout" || no "copy wrote outside"
rm "$R/.rt3"; mkdir -p "$R/.rt3"; ln -s "$T/outside" "$R/.rt3/agents"
out=$(pl link 2>&1) && no "copied into a destination that is a symlink" || { grep -q "is a symbolic link; refusing (mode copy keeps a real directory" <<<"$out" && ok "copy: a destination that is a symbolic link is refused" || no "copy dest link: $out"; }
rm "$R/.rt3/agents"; echo f > "$R/.rt3/agents"; out=$(pl link 2>&1) && no "copied into a file" || ok "copy: a destination that is a file is refused"
rm -rf "$R/.rt3"; tok=$(ptok link); held ap link "$tok" || no "setup: the hold was not reached"
mkdir -p "$T/elsewhere4"; ln -s "$T/elsewhere4" "$R/.rt3"; release
[ "$HRC" != 0 ] && grep -q "is a symbolic link or not a directory now" <<<"$HOUT" && [ -z "$(ls -A "$T/elsewhere4")" ] && ok "copy: a parent that became a link between the plan and the apply is refused and nothing is written through it" || no "copy swapped parent: rc=$HRC $HOUT"
rm "$R/.rt3"
# the worktree: the copies and the manifest are in it, nothing elsewhere
state_before=$(snap "$STATE"); main_before=$(snap "$R/.git" "$R/README")
CO=$T/wt; out=$(go link 2>&1)
[ -f "$T/wt/$DEST/a.md" ] && [ -f "$T/wt/$DEST.qargi-copy.json" ] && [ ! -e "$R/.rt3" ] && [ "$state_before" = "$(snap "$STATE")" ] && [ "$main_before" = "$(snap "$R/.git" "$R/README")" ] && ok "copy: in a worktree the copies and their manifest are in that worktree only" || no "copy worktree: $out"
ap unlink "$(ptok unlink)" >/dev/null 2>&1; [ ! -e "$T/wt/$DEST.qargi-copy.json" ] && ok "copy: unlink in the worktree removes its copies and manifest" || no "copy worktree unlink"; CO=$R
# a member run never applies
tok=$(ptok link); spec
out=$(cd "$T/run/out" && python3 -I "$T/drv.py" "$ROOT/lib" apply link "$T/spec.json" "$tok" 2>&1) && no "applied in a member run" || { grep -q "is not available in a member run" <<<"$out" && [ ! -e "$R/.rt3" ] && ok "copy: a member run never applies" || no "copy member run: $out"; }

# --- scope user: a link that lives outside every checkout (a runtime's memory directory in the home directory); root is the directory the
# destination is relative to, and nothing is asked of git there: no work tree, no tracked files, no exclude hint
cat > "$T/udrv.py" <<'EOF'
import json, os, sys
sys.path.insert(0, sys.argv[1])
import linker
phase, verb, specfile = sys.argv[2:5]
spec = json.load(open(specfile))
lk = linker.Link("memory", "alpha", spec.get("checkout", ""), spec["dest"], spec["source"], spec["mode"], spec["state"], {"place": "the home directory"},
                 root=spec["root"], source_root=spec.get("source_root"))
if phase == "plan":
    tf = specfile + ".token"
    if os.path.exists(tf):
        os.unlink(tf)
    linker.cmd_plan(verb, lk, tf)
    if os.path.exists(tf):
        print("plan token: " + open(tf).read())
else:
    linker.cmd_apply(verb, lk, sys.argv[5])
EOF
UH=$T/uhome; UM=$T/umem/alpha; mkdir -p "$UH" "$UM"; echo n > "$UM/n.md"; UD=.fake/projects/k/memory
uspec() { jq -n --arg root "$UH" --arg dest "$UD" --arg src "${1:-$UM}" --arg st "$STATE" --arg sr "$T/umem" --arg m "${2:-dir-symlink}" \
            '{root:$root,dest:$dest,source:$src,mode:$m,state:$st,source_root:$sr}' > "$T/uspec.json"; }
udrv() { uspec "${USRC:-}" "${UMODE:-}"; python3 -I "$T/udrv.py" "$ROOT/lib" "$@"; }
uplan() { udrv plan "$1" "$T/uspec.json" 2>&1; }
ugo() { local tok; tok=$(uplan "$1" | tok_of); [ -n "$tok" ] && udrv apply "$1" "$T/uspec.json" "$tok" 2>&1; }
UL=$UH/$UD
before=$(snap "$UM"); out=$(uplan link); tok=$(tok_of <<<"$out")
{ [ -n "$tok" ] && grep -q "^link plan for alpha: the home directory $UH loads " <<<"$out" && grep -q "link:   $UL" <<<"$out" && ! grep -q "git does not ignore\|tracked" <<<"$out" && [ ! -e "$UH/.fake" ]; } \
  && ok "user scope: the plan names the home directory, prints a token, writes nothing and has no exclude hint" || no "user plan: $out"
out=$(ugo link)
{ [ -L "$UL" ] && [ "$(readlink "$UL")" = "$UM" ] && [ -f "$UL/n.md" ] && ! grep -q "git does not ignore" <<<"$out" && [ "$before" = "$(snap "$UM")" ]; } \
  && ok "user scope: the link is made (the missing parents too), in a directory that is not a git work tree, and the source is untouched" || no "user apply: $out"
out=$(uplan link); { grep -q "^already linked: $UL" <<<"$out" && [ -z "$(tok_of <<<"$out")" ]; } && ok "user scope: linking again says already linked" || no "user again: $out"
ugo unlink >/dev/null; [ ! -e "$UL" ] && [ ! -L "$UL" ] && [ -d "$UH/.fake/projects/k" ] && [ -f "$UM/n.md" ] && ok "user scope: unlink removes the link only" || no "user unlink"
# a real directory is moved to the backup beside it, whole, and unlink puts it back
mkdir -p "$UL"; echo mine > "$UL/MEMORY.md"
out=$(uplan link); grep -q "apply moves the directory to $UL.qargi-backup" <<<"$out" && ok "user scope: the plan says a real directory is moved to a backup" || no "user backup plan: $out"
ugo link >/dev/null; { [ -L "$UL" ] && [ "$(cat "$UL.qargi-backup/MEMORY.md")" = mine ]; } && ok "user scope: the real directory is in the backup" || no "user backup"
ugo unlink >/dev/null; { [ -d "$UL" ] && [ ! -L "$UL" ] && [ "$(cat "$UL/MEMORY.md")" = mine ] && [ ! -e "$UL.qargi-backup" ]; } && ok "user scope: unlink restores it" || no "user restore"
rm -rf "$UL"
# refusals: a link that is not ours, a symbolic link above it, a source outside source_root, a source reached through a link, tracked files do not matter here
ln -s "$T/elsewhere" "$UL"; out=$(uplan link); rc=$?
grep -q "is a symbolic link to $T/elsewhere, not to " <<<"$out" && [ "$(readlink "$UL")" = "$T/elsewhere" ] && ok "user scope: a foreign link is refused" || no "user foreign: $out"
rm -f "$UL"; mv "$UH/.fake" "$T/moved-fake"; ln -s "$T/moved-fake" "$UH/.fake"
out=$(uplan link); grep -q "$UH/.fake is a symbolic link; refusing" <<<"$out" && ok "user scope: a symbolic link in the parents is refused" || no "user parent link: $out"
rm -f "$UH/.fake"; mv "$T/moved-fake" "$UH/.fake"
mkdir -p "$T/outside"; out=$(USRC=$T/outside uplan link); grep -q "is not below the state directory $T/umem; refusing" <<<"$out" && ok "user scope: a source outside source_root is refused" || no "user source root: $out"
ln -s "$UM" "$T/umem/viaLink"; out=$(USRC=$T/umem/viaLink uplan link); grep -q "viaLink is a symbolic link; refusing" <<<"$out" && ok "user scope: a source reached through a symbolic link is refused" || no "user source link: $out"
rm -f "$T/umem/viaLink"
out=$(USRC=$T/umem/missing uplan link); grep -q "does not exist" <<<"$out" && ok "user scope: a missing source is refused" || no "user missing source: $out"
# entry-symlinks in user scope
UMODE=entry-symlinks; mkdir -p "$UL"; echo mine > "$UL/own.md"
out=$(ugo link); { [ -L "$UL/n.md" ] && [ -f "$UL/own.md" ] && [ ! -L "$UL/own.md" ]; } && ok "user scope, entry-symlinks: beside the user's own entries" || no "user entries: $out"
ugo unlink >/dev/null; { [ ! -e "$UL/n.md" ] && [ -f "$UL/own.md" ]; } && ok "user scope, entry-symlinks: unlink removes ours only" || no "user entries unlink"
UMODE=
# a member run never applies
tok=$(uplan link | tok_of); uspec
out=$(cd "$T/run/out" && python3 -I "$T/udrv.py" "$ROOT/lib" apply link "$T/uspec.json" "$tok" 2>&1) && no "applied in a member run (user scope)" || { grep -q "is not available in a member run" <<<"$out" && [ ! -L "$UL" ] && ok "user scope: a member run never applies" || no "user member run: $out"; }

M=dir-symlink

rm -rf "$T"
exit $fail
