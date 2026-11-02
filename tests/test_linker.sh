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
cd "$T" || exit 1
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
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
tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
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

rm -rf "$T"
exit $fail
