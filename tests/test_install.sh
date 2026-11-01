#!/usr/bin/env bash
# install.sh and the four retired ability skills (qargi-build, qargi-write, qargi-review, qargi-test): an install and an
# uninstall remove the links an earlier version made, keep everything that is not such a link, and clean the local
# exclude file. Hermetic home; nothing touches the real ~/.claude. Run: tests/test_install.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
unset XDG_DATA_HOME
ROOT=$PWD; T=$(mktemp -d); fail=0
trap 'rm -rf "$T"; rm -rf "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
RETIRED="qargi-build qargi-write qargi-review qargi-test"
CURRENT="qargi-task qargi-project qargi-instances qargi-provision qargi-memory qargi-packs qargi-verify qargi-flow qargi-team"
INSTALL="$ROOT/install.sh"
S=$HOME/.claude/skills
DATA=$HOME/.local/share/qargi

# the state an upgrade meets: links into the checkout and into the copy, a link elsewhere, a real directory
old_state() {
  mkdir -p "$S" "$T/elsewhere" "$T/realdir"
  echo mine > "$T/realdir/notes.md"
  ln -sfn "$ROOT/skills/qargi-build" "$S/qargi-build"
  ln -sfn "$DATA/skills/qargi-write" "$S/qargi-write"
  ln -sfn "$T/elsewhere" "$S/qargi-review"
  rm -rf "${S:?}/qargi-test"; cp -r "$T/realdir" "$S/qargi-test"
}

# --- --user ---
old_state
out=$(bash "$INSTALL" --user 2>&1); rc=$?
[ "$rc" = 0 ] && ok "install --user succeeds over the old state" || no "install --user: rc=$rc $out"
{ [ ! -L "$S/qargi-build" ] && [ ! -e "$S/qargi-build" ]; } && ok "a retired link into the checkout is removed" || no "link into the checkout kept"
{ [ ! -L "$S/qargi-write" ] && [ ! -e "$S/qargi-write" ]; } && ok "a retired link into the copy is removed" || no "link into the copy kept"
[ -L "$S/qargi-review" ] && [ "$(readlink "$S/qargi-review")" = "$T/elsewhere" ] && ok "a link that points elsewhere is kept" || no "foreign link touched"
[ -f "$S/qargi-test/notes.md" ] && [ ! -L "$S/qargi-test" ] && ok "a real directory is kept" || no "real directory touched"
echo "$out" | grep -q "kept $S/qargi-review" && echo "$out" | grep -q "kept $S/qargi-test" && ok "the output says what was kept" || no "no 'kept' lines: $out"
echo "$out" | grep -q "removed .*$S/qargi-build" && ok "the output says what was removed" || no "no 'removed' line: $out"
miss=''; for s in $CURRENT; do [ "$(readlink "$S/$s")" = "$ROOT/skills/$s" ] && [ -d "$S/$s" ] || miss="$miss $s"; done
[ -z "$miss" ] && ok "the current skills are installed" || no "current skills missing:$miss"

before=$(ls -l "$S" | sed 1d)
out2=$(bash "$INSTALL" --user 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$before" = "$(ls -l "$S" | sed 1d)" ] && ok "a second run changes nothing" || no "second run: rc=$rc"
echo "$out2" | grep -q "removed .*qargi-build" && no "the second run removed a link again" || ok "the second run has nothing left to remove"

out=$(bash "$INSTALL" --user --force 2>&1)
[ ! -e "$S/qargi-test" ] && ok "--force removes a retired real directory" || no "--force kept the real directory: $out"
[ -L "$S/qargi-review" ] && ok "--force keeps a link that points elsewhere" || no "--force removed a foreign link"

# --- --user --uninstall ---
old_state
out=$(bash "$INSTALL" --user --uninstall 2>&1); rc=$?
[ "$rc" = 0 ] && ok "uninstall succeeds" || no "uninstall: rc=$rc $out"
{ [ ! -L "$S/qargi-build" ] && [ ! -L "$S/qargi-write" ]; } && ok "uninstall removes the retired links into the install" || no "uninstall kept retired links"
[ -L "$S/qargi-review" ] && [ -f "$S/qargi-test/notes.md" ] && ok "uninstall keeps a foreign link and a real directory" || no "uninstall touched them"
echo "$out" | grep -q "kept $S/qargi-test" && ok "uninstall says what it kept" || no "uninstall output: $out"
left=''; for s in $CURRENT; do [ ! -e "$S/$s" ] && [ ! -L "$S/$s" ] || left="$left $s"; done
[ -z "$left" ] && ok "uninstall removes the current skills" || no "current skills left:$left"
bash "$INSTALL" --user --uninstall --force >/dev/null 2>&1
[ ! -e "$S/qargi-test" ] && [ -L "$S/qargi-review" ] && ok "uninstall --force removes the real directory, still not a foreign link" || no "uninstall --force"

# --- --project ---
P=$T/proj; mkdir -p "$P"; git init -q "$P"
X=$P/.git/info/exclude; mkdir -p "$P/.git/info"
{ echo "# mine"; echo "build/"; for s in $RETIRED; do echo "/.claude/skills/$s"; done; echo "/.claude/skills/qargi-task"; } > "$X"
mkdir -p "$P/.claude/skills"
ln -s "$ROOT/skills/qargi-build" "$P/.claude/skills/qargi-build"
ln -s "$T/elsewhere" "$P/.claude/skills/qargi-write"
out=$(bash "$INSTALL" --project "$P" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "install --project succeeds" || no "install --project: rc=$rc $out"
{ [ ! -L "$P/.claude/skills/qargi-build" ] && [ -L "$P/.claude/skills/qargi-write" ]; } && ok "project: the retired link is removed, the foreign one kept" || no "project links"
bad=''; for s in $RETIRED; do ! grep -qx -F "/.claude/skills/$s" "$X" || bad="$bad $s"; done
[ -z "$bad" ] && ok "the stale exclude lines are removed" || no "exclude lines left:$bad"
grep -qx "build/" "$X" && grep -qx "# mine" "$X" && ok "the owner's own exclude lines stay" || no "own lines lost: $(cat "$X")"
miss=''; for s in $CURRENT; do grep -qx -F "/.claude/skills/$s" "$X" && [ -L "$P/.claude/skills/$s" ] || miss="$miss $s"; done
[ -z "$miss" ] && ok "the current skills are linked and hidden" || no "project current skills:$miss"
n=$(grep -c -x -F "/.claude/skills/qargi-task" "$X")
cp "$X" "$T/x1"; bash "$INSTALL" --project "$P" >/dev/null 2>&1
{ cmp -s "$X" "$T/x1" && [ "$n" = 1 ]; } && ok "project: a second run leaves the exclude file as it was" || no "project second run: $(cat "$X")"

echo "# stale again" >> "$X"; echo "/.claude/skills/qargi-test" >> "$X"
bash "$INSTALL" --project "$P" --uninstall >/dev/null 2>&1
bad=''; for s in $RETIRED $CURRENT; do ! grep -qx -F "/.claude/skills/$s" "$X" || bad="$bad $s"; done
[ -z "$bad" ] && grep -qx "build/" "$X" && ok "project uninstall removes the skill lines and keeps the owner's" || no "uninstall exclude: $(cat "$X")"
[ -L "$P/.claude/skills/qargi-write" ] && [ ! -e "$P/.claude/skills/qargi-task" ] && ok "project uninstall keeps the foreign link and removes the current skills" || no "project uninstall links"

[ "$fail" = 0 ] && echo "test_install: all passed" || { echo "test_install: FAILED"; exit 1; }
