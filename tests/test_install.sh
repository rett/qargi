#!/usr/bin/env bash
# install.sh: the skills it installs agree with skills/, an install links them, a second run changes nothing, an existing
# real directory is kept unless --force, an uninstall removes the links, and a project install hides them through the local
# exclude file without touching the owner's lines. Hermetic home; nothing touches the real ~/.claude. Run: tests/test_install.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
unset XDG_DATA_HOME
ROOT=$PWD; T=$(mktemp -d); fail=0
trap 'rm -rf "$T"; rm -rf "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
CURRENT="qargi-task qargi-project qargi-instances qargi-provision qargi-memory qargi-packs qargi-providers qargi-verify qargi-flow qargi-team qargi-session"
INSTALL="$ROOT/install.sh"
S=$HOME/.claude/skills

# --- the shipped skills: the list in install.sh, the directories under skills/ and this test agree, and each has valid front matter
listed=$(sed -n 's/^skills="\(.*\)"$/\1/p' "$INSTALL" | tr ' ' '\n' | sort)
shipped=$(cd "$ROOT/skills" && ls -d -- */ | tr -d / | sort)
[ "$listed" = "$shipped" ] && ok "install.sh installs exactly the skills under skills/" || no "install.sh skills= and skills/ differ: $(diff <(echo "$listed") <(echo "$shipped"))"
[ "$(echo "$CURRENT" | tr ' ' '\n' | sort)" = "$listed" ] && ok "this test lists the skills install.sh installs" || no "CURRENT in this test differs from install.sh skills="
for s in $listed; do
  f=$ROOT/skills/$s/SKILL.md
  if [ -f "$f" ] && [ "$(sed -n '1p' "$f")" = "---" ] && [ "$(sed -n '2,/^---$/{/^name: /p}' "$f" | head -1)" = "name: $s" ] \
     && [ -n "$(sed -n '2,/^---$/{s/^description: *//p}' "$f" | head -1)" ]; then ok "skill $s: SKILL.md with name $s and a description"
  else no "skill $s: SKILL.md missing or its front matter has no name: $s / description"; fi
done

mkdir -p "$T/elsewhere"

# --- --user ---
out=$(bash "$INSTALL" --user 2>&1); rc=$?
[ "$rc" = 0 ] && ok "install --user succeeds" || no "install --user: rc=$rc $out"
miss=''; for s in $CURRENT; do [ "$(readlink "$S/$s")" = "$ROOT/skills/$s" ] && [ -d "$S/$s" ] || miss="$miss $s"; done
[ -z "$miss" ] && ok "the skills are installed as links into the checkout" || no "skills missing:$miss"

before=$(ls -l "$S" | sed 1d)
bash "$INSTALL" --user >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$before" = "$(ls -l "$S" | sed 1d)" ] && ok "a second run changes nothing" || no "second run: rc=$rc"

# a real directory in the way is kept without --force and replaced with it
rm -f "$S/qargi-task"; mkdir "$S/qargi-task"; echo mine > "$S/qargi-task/notes.md"
out=$(bash "$INSTALL" --user 2>&1); rc=$?
{ [ "$rc" != 0 ] && [ -f "$S/qargi-task/notes.md" ] && echo "$out" | grep -q "refusing to replace existing $S/qargi-task"; } && ok "a real directory is not replaced without --force" || no "real directory: rc=$rc $out"
bash "$INSTALL" --user --force >/dev/null 2>&1
[ "$(readlink "$S/qargi-task")" = "$ROOT/skills/qargi-task" ] && ok "--force replaces it with the link" || no "--force left the directory"

# --- --user --uninstall ---
out=$(bash "$INSTALL" --user --uninstall 2>&1); rc=$?
[ "$rc" = 0 ] && ok "uninstall succeeds" || no "uninstall: rc=$rc $out"
left=''; for s in $CURRENT; do [ ! -e "$S/$s" ] && [ ! -L "$S/$s" ] || left="$left $s"; done
[ -z "$left" ] && ok "uninstall removes the skills" || no "skills left:$left"
mkdir "$S/qargi-flow"; echo mine > "$S/qargi-flow/notes.md"; ln -s "$T/elsewhere" "$S/qargi-team"
out=$(bash "$INSTALL" --user --uninstall 2>&1)
{ [ -f "$S/qargi-flow/notes.md" ] && echo "$out" | grep -q "kept $S/qargi-flow"; } && ok "uninstall keeps a real directory and says so" || no "uninstall touched the real directory: $out"
bash "$INSTALL" --user --uninstall --force >/dev/null 2>&1
{ [ ! -e "$S/qargi-flow" ] && [ ! -e "$S/qargi-team" ] && [ -d "$T/elsewhere" ]; } && ok "uninstall --force removes them, and leaves what a link pointed to" || no "uninstall --force"

# --- --project ---
P=$T/proj; mkdir -p "$P"; git init -q "$P"
X=$P/.git/info/exclude; mkdir -p "$P/.git/info"
{ echo "# mine"; echo "build/"; echo "/.claude/skills/qargi-task"; } > "$X"
out=$(bash "$INSTALL" --project "$P" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "install --project succeeds" || no "install --project: rc=$rc $out"
miss=''; for s in $CURRENT; do grep -qx -F "/.claude/skills/$s" "$X" && [ -L "$P/.claude/skills/$s" ] || miss="$miss $s"; done
[ -z "$miss" ] && ok "the skills are linked and hidden" || no "project skills:$miss"
grep -qx "build/" "$X" && grep -qx "# mine" "$X" && ok "the owner's own exclude lines stay" || no "own lines lost: $(cat "$X")"
n=$(grep -c -x -F "/.claude/skills/qargi-task" "$X")
cp "$X" "$T/x1"; bash "$INSTALL" --project "$P" >/dev/null 2>&1
{ cmp -s "$X" "$T/x1" && [ "$n" = 1 ]; } && ok "project: a second run leaves the exclude file as it was" || no "project second run: $(cat "$X")"

bash "$INSTALL" --project "$P" --uninstall >/dev/null 2>&1
bad=''; for s in $CURRENT; do ! grep -qx -F "/.claude/skills/$s" "$X" || bad="$bad $s"; done
[ -z "$bad" ] && grep -qx "build/" "$X" && ok "project uninstall removes the skill lines and keeps the owner's" || no "uninstall exclude: $(cat "$X")"
left=''; for s in $CURRENT; do [ ! -e "$P/.claude/skills/$s" ] && [ ! -L "$P/.claude/skills/$s" ] || left="$left $s"; done
[ -z "$left" ] && ok "project uninstall removes the skills" || no "project skills left:$left"

# --- --copy: a skill is copied as a whole directory, so its reference files come with SKILL.md ---
# (a skill loads its reference files only when its SKILL.md tells it to, so a copy without them would break that skill)
refs=$(cd "$ROOT/skills" && find . -type f ! -name SKILL.md | sed 's#^\./##' | sort)
[ -n "$refs" ] && ok "some skills have reference files beside SKILL.md ($(echo "$refs" | tr '\n' ' '))" || no "no skill has a reference file: the copy checks below prove nothing"
bash "$INSTALL" --user --copy --force >/dev/null 2>&1; rc=$?
miss=''; for s in $CURRENT; do
  [ ! -L "$S/$s" ] && [ -d "$S/$s" ] || { miss="$miss $s(not a copy)"; continue; }
  while IFS= read -r f; do cmp -s "$ROOT/skills/$f" "$S/$f" || miss="$miss $f"; done < <(cd "$ROOT/skills" && find "$s" -type f)
done
[ "$rc" = 0 ] && [ -z "$miss" ] && ok "install --user --copy copies every file of every skill, reference files included" || no "user copy: rc=$rc missing or different:$miss"
P2=$T/proj2; mkdir -p "$P2"; git init -q "$P2"
bash "$INSTALL" --project "$P2" --copy >/dev/null 2>&1; rc=$?
miss=''; for r in $refs; do cmp -s "$ROOT/skills/$r" "$P2/.claude/skills/$r" || miss="$miss $r"; done
[ "$rc" = 0 ] && [ -z "$miss" ] && ok "install --project --copy copies the reference files too" || no "project copy: rc=$rc missing or different:$miss"
bash "$INSTALL" --user --uninstall --force >/dev/null 2>&1; bash "$INSTALL" --project "$P2" --uninstall --force >/dev/null 2>&1

[ "$fail" = 0 ] && echo "test_install: all passed" || { echo "test_install: FAILED"; exit 1; }
