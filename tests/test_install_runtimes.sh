#!/usr/bin/env bash
# install.sh with several runtimes: the lead skills of Claude Code and Codex installed side by side from one tool, each removable on its own,
# the command, man page and completions shared and removed with the last runtime; an install of one runtime leaves the links of the other
# as they are (same inodes); --uninstall alone removes every runtime and lists them; a record that fails its check stops the run with nothing
# changed; a link no install recorded is not replaced without --force and one already pointing at the tool is adopted; the lock keeps a second
# run out; entries of yours in a skills directory stay byte- and inode-identical throughout. Scratch homes only. Run: tests/test_install_runtimes.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
unset XDG_DATA_HOME
ROOT=$PWD; T=$(mktemp -d); fail=0
trap 'kill_bg; rm -rf "$T"; rm -rf "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh
INSTALL="$ROOT/install.sh"
NSKILLS=$(sed -n 's/^skills="\(.*\)"$/\1/p' "$INSTALL" | wc -w)

# a fresh scratch home: H, its records C, the skills directories of the two runtimes
fresh() {
  H=$(mktemp -d "$T/h.XXXXXX"); C=$H/.qargi/config
  CS=$H/.claude/skills; XS=$H/.codex/skills
}
inst() { env -u QARGI_CONF -u QARGI_HOME HOME="$H" XDG_CONFIG_HOME="$H/.config" bash "$INSTALL" "$@"; }
nlinks() { find "$1" -maxdepth 1 -name 'qargi-*' -type l 2>/dev/null | wc -l; }
# the inventory of a tree: path, type, inode, link target, and the checksum of a file
inventory() { find "$@" -printf '%p %y %i %l\n' 2>/dev/null | sort; find "$@" -type f -exec md5sum {} + 2>/dev/null | sort; }
# what of yours a Codex skills directory holds: a link to another tree, a real directory and the runtime's own system skills
mine() {
  mkdir -p "$XS/.system/sys-skill" "$XS/synced" "$T/other/skill"
  echo sys > "$XS/.system/sys-skill/SKILL.md"; echo synced > "$XS/synced/SKILL.md"
  ln -s "$T/other/skill" "$XS/other-skill"
}
yours() { inventory "$XS/.system" "$XS/synced" "$XS/other-skill"; }

# --- side by side
fresh; mine; y0=$(yours)
out=$(inst --user 2>&1); rc=$?
[ "$rc" = 0 ] && ok "install --user (claude-code)" || no "install --user: rc=$rc $out"
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 0 ] && echo "$out" | grep -q "installed runtimes: claude-code, codex"; } && ok "install --user --runtime codex beside it, and says which runtimes are installed" || no "install codex: rc=$rc $out"
shared=0; for p in "$H/.local/bin/qargi" "$H/.local/share/man/man1/qargi.1" "$H/.local/share/bash-completion/completions/qargi" "$H/.local/share/zsh/site-functions/_qargi" "$H/.config/fish/completions/qargi.fish"; do
  [ -L "$p" ] && shared=$((shared + 1))
done
{ [ "$(nlinks "$CS")" = "$NSKILLS" ] && [ "$(nlinks "$XS")" = "$NSKILLS" ] && [ "$shared" = 5 ]; } && ok "both runtimes have their $NSKILLS skill links and the 5 shared links are there" || no "links: claude $(nlinks "$CS"), codex $(nlinks "$XS"), shared $shared"
[ "$(cd "$C/install.d" && ls | tr '\n' ' ')" = "runtime-claude-code.manifest runtime-codex.manifest shared.manifest " ] && ok "three records: one per runtime and the shared one" || no "records: $(ls "$C/install.d")"
[ "$(readlink "$XS/qargi-task")" = "$ROOT/skills/qargi-task" ] && ok "the Codex links point into the one tool" || no "codex link: $(readlink "$XS/qargi-task")"
[ "$(yours)" = "$y0" ] && ok "your entries in the Codex skills directory are untouched" || no "your entries changed: $(diff <(echo "$y0") <(yours))"

# --- an install of one runtime leaves the other as it is
x0=$(inventory "$XS"); c0=$(inventory "$CS"); m0=$(cat "$C/install.d/runtime-codex.manifest")
out=$(inst --user --runtime claude-code 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(inventory "$XS")" = "$x0" ] && [ "$(cat "$C/install.d/runtime-codex.manifest")" = "$m0" ]; } && ok "reinstalling claude-code leaves every Codex link (same inodes) and its record as they were" || no "codex changed: $(diff <(echo "$x0") <(inventory "$XS"))"
[ "$(inventory "$CS")" = "$c0" ] && ok "and its own links already pointing at the tool stay as they are" || no "claude links were remade"

# --- uninstall one runtime, then the last
out=$(inst --user --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(nlinks "$XS")" = 0 ] && [ "$(nlinks "$CS")" = "$NSKILLS" ] && [ -L "$H/.local/bin/qargi" ] && [ -f "$C/install.json" ] && echo "$out" | grep -q "still installed: claude-code"; } \
  && ok "uninstall --runtime codex removes the Codex links only; the shared part and install.json stay with claude-code" || no "uninstall codex (rc=$rc): $out"
[ "$(yours)" = "$y0" ] && ok "your Codex entries are untouched by its uninstall" || no "your entries changed by the uninstall"
before=$(inventory "$H")
out=$(inst --user --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "runtime codex is not installed (installed: claude-code); nothing was removed" && [ "$(inventory "$H")" = "$before" ]; } && ok "uninstalling a runtime that is not installed is refused and changes nothing" || no "uninstall codex again (rc=$rc): $out"
out=$(inst --user --uninstall --runtime claude-code 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$H/.local/bin/qargi" ] && [ ! -e "$C/install.json" ] && [ ! -e "$C/install.d" ] && [ ! -e "$C/install.lock" ] && [ ! -e "$H/.claude" ]; } && ok "uninstalling the last runtime removes the shared part, install.json, install.d and the lock" || no "last uninstall (rc=$rc): $out $(find "$H" -mindepth 1 | grep -v codex | head)"
left=$(find "$H" -mindepth 1 \( -path "$XS" -o -path "$H/.qargi" \) -prune -o -print | grep -v -x -e "$H/.codex")
[ "$(yours)" = "$y0" ] && [ -z "$left" ] && [ -z "$(find "$C" -maxdepth 1 -name 'install*')" ] && ok "only your entries (and qargi's data in ~/.qargi, no install record) are left in the home" || no "left: $left $(ls "$C")"

# --- a bare uninstall removes every runtime, listing them
fresh; mine; y0=$(yours)
inst --user >/dev/null 2>&1; inst --user --runtime codex >/dev/null 2>&1
out=$(inst --user --uninstall 2>&1); rc=$?
{ [ "$rc" = 0 ] && echo "$out" | grep -q "uninstalling the runtimes installed: claude-code, codex" && [ "$(nlinks "$XS")" = 0 ] && [ ! -e "$H/.claude" ] && [ ! -e "$C/install.d" ]; } && ok "uninstall without --runtime removes every runtime, named first" || no "bare uninstall (rc=$rc): $out"
[ "$(yours)" = "$y0" ] && ok "and keeps your entries" || no "bare uninstall changed your entries"

# --- a record that fails its check stops the run; nothing is changed
fresh
inst --user >/dev/null 2>&1; inst --user --runtime codex >/dev/null 2>&1
echo keep > "$H/precious"
printf 'f\t%s\n' "$H/precious" >> "$C/install.d/runtime-codex.manifest"
before=$(inventory "$H")
out=$(inst --user --uninstall 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "runtime-codex.manifest line .*not a place" && [ "$(inventory "$H")" = "$before" ]; } && ok "a record listing a path outside its skills directory is refused whole: the uninstall removes nothing" || no "tampered record (rc=$rc): $out"
out=$(inst --user --runtime claude-code 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(inventory "$H")" = "$before" ]; } && ok "and an install refuses too, changing nothing" || no "install over a tampered record (rc=$rc): $out"

# --- links nobody recorded; a link the user retargeted
fresh; mkdir -p "$XS" "$H/.local/bin"
ln -s "$T/elsewhere" "$XS/qargi-flow"
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "refusing to replace $XS/qargi-flow, a link to $T/elsewhere that no install recorded (use --force)" && [ ! -e "$C/install.d" ] && [ ! -e "$H/.local/bin/qargi" ]; } \
  && ok "a link no install recorded is not replaced, and the refused run records nothing" || no "foreign link (rc=$rc): $out"
[ ! -e "$C" ] && ok "a refused first install leaves no lock and no config directory it made" || no "left after the refusal: $(find "$H/.qargi" 2>&1)"
rm "$XS/qargi-flow"; ln -s "$ROOT/skills/qargi-flow" "$XS/qargi-flow"; ino=$(stat -c %i "$XS/qargi-flow")
ln -s "$T/elsewhere" "$H/.local/bin/qargi"
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "refusing to replace $H/.local/bin/qargi"; } && ok "so is a command link of another tree" || no "foreign command link (rc=$rc): $out"
out=$(inst --user --runtime codex --force 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(readlink "$H/.local/bin/qargi")" = "$ROOT/bin/qargi" ] && [ "$(stat -c %i "$XS/qargi-flow")" = "$ino" ] \
  && grep -q "^L	$XS/qargi-flow	$ROOT/skills/qargi-flow$" "$C/install.d/runtime-codex.manifest"; } && ok "--force replaces it; a link already pointing at the tool is adopted as it is and recorded" || no "force/adopt (rc=$rc): $out"
rm "$XS/qargi-task"; ln -s "$T/elsewhere" "$XS/qargi-task"
out=$(inst --user --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(readlink "$XS/qargi-task")" = "$T/elsewhere" ] && echo "$out" | grep -q "kept $XS/qargi-task (a link to $T/elsewhere, not the one the install made)"; } && ok "an uninstall keeps a link the user pointed elsewhere, and says so" || no "retargeted link (rc=$rc): $out"

# --- one skills directory holds one runtime
fresh
inst --user >/dev/null 2>&1; mkdir -p "$H/.codex"; ln -s "$CS" "$XS"
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "one skills directory holds the skills of one runtime" && [ ! -e "$C/install.d/runtime-codex.manifest" ]; } && ok "a Codex skills directory that is the Claude one (a link) is refused" || no "overlap (rc=$rc): $out"

# --- the lock keeps a second run out
fresh
inst --user >/dev/null 2>&1
hold() { exec 8>>"$C/install.lock"; flock 8; exec sleep 60; }   # holds the lock in a process kill_bg can stop
spawn_bg hold >/dev/null 2>&1
held() { ! flock -n "$C/install.lock" true; }
wait_until held 10 || no "the lock was not taken"
before=$(inventory "$H")
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "another install is running" && [ "$(inventory "$H")" = "$before" ]; } && ok "a run while another holds the lock waits briefly, then gives up with nothing changed" || no "lock (rc=$rc): $out"
kill_bg

# --- a project with two runtimes: each hidden and removed on its own
fresh; P=$T/proj; rm -rf "$P"; mkdir -p "$P"; git init -q "$P"; X=$P/.git/info/exclude
inst --project "$P" >/dev/null 2>&1; inst --project "$P" --runtime codex >/dev/null 2>&1
{ [ "$(nlinks "$P/.claude/skills")" = "$NSKILLS" ] && [ "$(nlinks "$P/.agents/skills")" = "$NSKILLS" ] && grep -qx "/.claude/skills/qargi-task" "$X" && grep -qx "/.agents/skills/qargi-task" "$X"; } \
  && ok "a project gets the skills of both runtimes, each hidden" || no "project: $(ls -A "$P"; cat "$X")"
out=$(inst --project "$P" --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$P/.agents" ] && [ "$(nlinks "$P/.claude/skills")" = "$NSKILLS" ] && ! grep -q "/.agents/" "$X" && grep -qx "/.claude/skills/qargi-task" "$X"; } \
  && ok "removing codex from it removes its links and its exclude lines only" || no "project uninstall codex (rc=$rc): $out $(cat "$X")"
out=$(inst --project "$P" --uninstall 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$P/.claude" ] && ! grep -q "qargi-" "$X" && [ ! -e "$H/.qargi" ]; } && ok "and the bare uninstall removes the rest, with the config directory it made" || no "project uninstall (rc=$rc): $out"

[ "$fail" = 0 ] && echo "test_install_runtimes: all passed" || { echo "test_install_runtimes: FAILED"; exit 1; }
