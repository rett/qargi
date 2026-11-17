#!/usr/bin/env bash
# install.sh with several runtimes. The first run over a 0.3.1 install moves its single install.manifest into install.d (links untouched,
# a leftover install.d.new removed unread); then the lead skills of Claude Code and Codex installed side by side from one tool, each removable on its own,
# the command, man page and completions shared and removed with the last runtime; an install of one runtime leaves the links of the other
# as they are (same inodes); install --user without --runtime refreshes every runtime installed, and a runtime whose definition is gone is
# skipped with a note and still removable; a record that fails its check stops the run with nothing changed; the lock keeps a second run out,
# also one that waited on a lock file removed under it, and a lock file that is a link is not opened;
# the runtimes come from one tool (another source for one runtime is refused while another is installed, a bare --user moves them all) and a
# --copy run copies them all again; --uninstall alone removes every runtime and lists them; a link no install recorded is not replaced
# without --force and one already pointing at the tool is adopted; a recorded link you replaced with a file is yours (a run refuses with
# nothing changed, every time); one skills directory holds one runtime; a project takes both runtimes;
# entries of yours in a skills directory stay byte- and inode-identical throughout. Scratch homes only. Run: tests/test_install_runtimes.sh
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

# --- the first install over a 0.3.1 install (what the 0.3.1 qargi upgrade runs: install.sh --user): its single install.manifest, a literal
# fixture of two fields a line beside the links it lists, becomes install.d once; a leftover install.d.new is removed unread. (The migration
# and this case go in 0.3.3.)
fresh; mine; y0=$(yours)
slots=("$H/.local/bin/qargi" "$H/.local/share/man/man1/qargi.1" "$H/.local/share/bash-completion/completions/qargi" "$H/.local/share/zsh/site-functions/_qargi" "$H/.config/fish/completions/qargi.fish")
srcs=(bin/qargi man/qargi.1 completions/qargi.bash completions/_qargi completions/qargi.fish)
legacy=$C/install.manifest; mkdir -p "$C" "$CS"; : > "$legacy"
printf 'P\t%s\n' "$H/.claude" "$CS" >> "$legacy"
for s in $(sed -n 's/^skills="\(.*\)"$/\1/p' "$INSTALL"); do ln -s "$ROOT/skills/$s" "$CS/$s"; printf 'L\t%s\n' "$CS/$s" >> "$legacy"; done
for d in .local .local/bin .local/share .local/share/man .local/share/man/man1 .local/share/bash-completion .local/share/bash-completion/completions \
         .local/share/zsh .local/share/zsh/site-functions .config .config/fish .config/fish/completions; do
  mkdir "$H/$d"; printf 'P\t%s\n' "$H/$d" >> "$legacy"
done
for i in 0 1 2 3 4; do ln -s "$ROOT/${srcs[$i]}" "${slots[$i]}"; printf 'L\t%s\n' "${slots[$i]}" >> "$legacy"; done
printf '{"tool_root": "%s", "installed_at": "2026-11-16T00:00:00Z", "version": "0.3.1"}\n' "$ROOT" > "$C/install.json"
echo keep > "$H/precious"; mkdir -p "$C/install.d.new"
printf '#qargi-manifest\t2\tkind=runtime\tname=codex\troot=%s\nC\t%s/qargi-x\nf\t%s/qargi-x/precious\n' "$H" "$H" "$H" > "$C/install.d.new/runtime-codex.manifest"
c0=$(inventory "$CS" "$H/.local" "$H/.config")
out=$(inst --user 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$legacy" ] && [ ! -e "$C/install.d.new" ] && [ "$(cd "$C/install.d" && ls | tr '\n' ' ')" = "runtime-claude-code.manifest shared.manifest " ] \
  && echo "$out" | grep -q "moved the install records of install.manifest"; } && ok "install --user over a 0.3.1 install moves its manifest into install.d and removes it" || no "migration (rc=$rc): $out"
[ "$(inventory "$CS" "$H/.local" "$H/.config")" = "$c0" ] && ok "the links it recorded are left as they are (same inodes)" || no "the migration changed links: $(diff <(echo "$c0") <(inventory "$CS" "$H/.local" "$H/.config"))"
{ [ -f "$H/precious" ] && echo "$out" | grep -q "install.d.new, left by an interrupted migration (not read)"; } && ok "a planted install.d.new is removed and never read" || no "install.d.new: $out"

# --- side by side
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

# --- install --user without --runtime refreshes every runtime installed; one whose definition is gone is skipped with a note
mkdir -p "$H/.gone/skills"; ln -s "$ROOT/skills/qargi-task" "$H/.gone/skills/qargi-task"
printf '#qargi-manifest\t2\tkind=runtime\tname=gone\troot=%s\nP\t%s\nP\t%s\nL\t%s\t%s\n' "$H/.gone/skills" "$H/.gone" "$H/.gone/skills" "$H/.gone/skills/qargi-task" "$ROOT/skills/qargi-task" > "$C/install.d/runtime-gone.manifest"
rm "$XS/qargi-task"
out=$(inst --user 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(readlink "$XS/qargi-task")" = "$ROOT/skills/qargi-task" ] && echo "$out" | grep -q "installed the skills of codex" && echo "$out" | grep -q "installed the skills of claude-code"; } \
  && ok "install --user without --runtime refreshes claude-code and codex" || no "bare refresh (rc=$rc): $out"
{ echo "$out" | grep -q "runtime gone is recorded but its definition has no user_skills_dir now, so it was not refreshed" && [ -L "$H/.gone/skills/qargi-task" ]; } \
  && ok "and skips a recorded runtime whose definition is gone, with a note" || no "gone runtime: $out"
out=$(inst --user --uninstall --runtime gone 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$H/.gone" ] && [ "$(nlinks "$CS")" = "$NSKILLS" ] && [ "$(nlinks "$XS")" = "$NSKILLS" ]; } && ok "whose uninstall works from its record alone" || no "uninstall gone (rc=$rc): $out"

# --- a record that fails its check stops the run; nothing is changed
cp "$C/install.d/runtime-codex.manifest" "$T/codex.manifest"
echo keep > "$H/precious"
printf 'f\t%s\n' "$H/precious" >> "$C/install.d/runtime-codex.manifest"
before=$(inventory "$H")
out=$(inst --user --uninstall 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "runtime-codex.manifest line .*not a place" && [ "$(inventory "$H")" = "$before" ]; } && ok "a record listing a path outside its skills directory is refused whole: the uninstall removes nothing" || no "tampered record (rc=$rc): $out"
out=$(inst --user --runtime claude-code 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(inventory "$H")" = "$before" ]; } && ok "and an install refuses too, changing nothing" || no "install over a tampered record (rc=$rc): $out"
cp "$T/codex.manifest" "$C/install.d/runtime-codex.manifest"; rm "$H/precious"

# --- the lock keeps a second run out
hold() { exec 8>>"$C/install.lock"; flock 8; exec sleep 60; }   # holds the lock in a process kill_bg can stop
spawn_bg hold >/dev/null 2>&1
held() { ! flock -n "$C/install.lock" true; }
wait_until held 10 || no "the lock was not taken"
before=$(inventory "$H")
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "another install is running" && [ "$(inventory "$H")" = "$before" ]; } && ok "a run while another holds the lock waits briefly, then gives up with nothing changed" || no "lock (rc=$rc): $out"
kill_bg

# --- two overlapping runs: B waits on the lock file; the run holding it removes the file (as the uninstall of the last record does) and a
# third run holds a new one at the path. B, once it holds the removed file, takes the lock at the path again, so it waits for the third run
swap() {
  exec 8>>"$C/install.lock"; flock 8; : > "$T/swap.held"
  until [ -e "$T/swap.go" ]; do sleep 0.05; done
  rm "$C/install.lock"; exec 7>>"$C/install.lock"; flock 7; exec 8>&-
  exec sleep 60    # holds the new lock (fd 7) in a process kill_bg can stop
}
spawn_bg swap >/dev/null 2>&1
wait_until '[ -e "$T/swap.held" ]' || no "the first lock was not taken"
before=$(inventory "$H" | grep -v install.lock)
env -u QARGI_CONF -u QARGI_HOME HOME="$H" XDG_CONFIG_HOME="$H/.config" bash "$INSTALL" --user --runtime codex > "$T/b.out" 2>&1 & bpid=$!
wait_until '[ "$(readlink "/proc/$bpid/fd/9" 2>/dev/null)" = "$C/install.lock" ]' || no "run B did not open the lock file"
: > "$T/swap.go"
wait "$bpid"; rc=$?; out=$(cat "$T/b.out")
{ [ "$rc" = 1 ] && echo "$out" | grep -q "another install is running" && [ "$(inventory "$H" | grep -v install.lock)" = "$before" ]; } \
  && ok "a run that waited on a lock file removed under it takes the lock at the path again and does not run beside the holder of the new one" || no "overlapping runs (rc=$rc): $out"
kill_bg

# --- the lock is never opened or chmod-ed through a link
mv "$C/install.lock" "$T/lock.saved"; echo theirs > "$T/lockdest"; chmod 644 "$T/lockdest"; ln -s "$T/lockdest" "$C/install.lock"
before=$(inventory "$H")
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "install.lock is a link or not a regular file, so it is not opened; nothing was changed" && [ "$(stat -c %a "$T/lockdest")" = 644 ] \
  && [ "$(cat "$T/lockdest")" = theirs ] && [ "$(inventory "$H")" = "$before" ]; } && ok "a lock file that is a link is refused before it is opened, with nothing changed" || no "linked lock (rc=$rc): $out"
rm "$C/install.lock"; mv "$T/lock.saved" "$C/install.lock"

# --- one source: the runtimes come from one tool, linked or copied alike
TL=$T/tool; copy_tool "$ROOT" "$TL"; cp "$ROOT/install.sh" "$TL/"; mkdir -p "$TL/completions" "$TL/man"; cp "$ROOT"/completions/* "$TL/completions/"; cp "$ROOT/man/qargi.1" "$TL/man/"
before=$(inventory "$H"); j0=$(cat "$C/install.json")
out=$(env -u QARGI_CONF -u QARGI_HOME HOME="$H" XDG_CONFIG_HOME="$H/.config" bash "$TL/install.sh" --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "the installed runtimes (claude-code, codex) come from $ROOT (link)" && echo "$out" | grep -q "without --runtime to move them all" \
  && [ "$(inventory "$H")" = "$before" ] && [ "$(cat "$C/install.json")" = "$j0" ]; } && ok "installing one runtime from another tool is refused while another runtime is installed; nothing changes" || no "source mismatch (rc=$rc): $out"
out=$(inst --user --runtime codex --copy 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "leave claude-code behind" && [ "$(inventory "$H")" = "$before" ]; } && ok "and so is a copy of one runtime over linked ones" || no "copy over links (rc=$rc): $out"
out=$(env -u QARGI_CONF -u QARGI_HOME HOME="$H" XDG_CONFIG_HOME="$H/.config" bash "$TL/install.sh" --user 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(readlink "$XS/qargi-task")" = "$TL/skills/qargi-task" ] && [ "$(readlink "$CS/qargi-task")" = "$TL/skills/qargi-task" ] && [ "$(readlink "$H/.local/bin/qargi")" = "$TL/bin/qargi" ] \
  && grep -q "\"tool_root\": \"$TL\"" "$C/install.json"; } && ok "install --user from the other tool moves every runtime and the shared part to it" || no "move all (rc=$rc): $out"

# --- uninstall one runtime; then one runtime may change its source alone
out=$(inst --user --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(nlinks "$XS")" = 0 ] && [ "$(nlinks "$CS")" = "$NSKILLS" ] && [ -L "$H/.local/bin/qargi" ] && [ -f "$C/install.json" ] && echo "$out" | grep -q "still installed: claude-code"; } \
  && ok "uninstall --runtime codex removes the Codex links only; the shared part and install.json stay with claude-code" || no "uninstall codex (rc=$rc): $out"
[ "$(yours)" = "$y0" ] && ok "your Codex entries are untouched by its uninstall" || no "your entries changed by the uninstall"
before=$(inventory "$H")
out=$(inst --user --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "runtime codex is not installed (installed: claude-code); nothing was removed" && [ "$(inventory "$H")" = "$before" ]; } && ok "uninstalling a runtime that is not installed is refused and changes nothing" || no "uninstall codex again (rc=$rc): $out"
out=$(inst --user --runtime claude-code --copy 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -d "$CS/qargi-task" ] && [ ! -L "$CS/qargi-task" ] && grep -q '"source": "copy"' "$C/install.json"; } && ok "with one runtime installed it may change its source on its own" || no "single runtime source change (rc=$rc): $out"

# --- a copy rewrites the tool copy, so every runtime is copied again with it
inst --user --runtime codex --copy >/dev/null 2>&1
i0=$(stat -c %i "$CS/qargi-task/SKILL.md")
out=$(inst --user --runtime codex --copy 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -f "$XS/qargi-task/SKILL.md" ] && [ ! -L "$XS/qargi-task" ] && [ "$(stat -c %i "$CS/qargi-task/SKILL.md")" != "$i0" ] && echo "$out" | grep -q "installed the skills of claude-code"; } \
  && ok "a --copy run for codex copies claude-code again too" || no "copy refresh (rc=$rc): $out"
[ "$(yours)" = "$y0" ] && ok "your Codex entries are untouched by the copies" || no "your entries changed by a copy install"

# --- a bare uninstall removes every runtime, listing them; then only your entries are left
out=$(inst --user --uninstall 2>&1); rc=$?
{ [ "$rc" = 0 ] && echo "$out" | grep -q "uninstalling the runtimes installed: claude-code, codex" && [ ! -e "$XS/qargi-task" ] && [ ! -e "$H/.claude" ] && [ ! -e "$H/.local" ] \
  && [ ! -e "$C/install.d" ] && [ ! -e "$C/install.json" ] && [ ! -e "$C/install.lock" ]; } && ok "uninstall without --runtime removes every runtime, named first, with the shared part, install.json, install.d and the lock" || no "bare uninstall (rc=$rc): $out"
left=$(find "$H" -mindepth 1 \( -path "$XS" -o -path "$H/.qargi" \) -prune -o -print | grep -v -x -e "$H/.codex" -e "$H/precious")
[ "$(yours)" = "$y0" ] && [ -z "$left" ] && [ -z "$(find "$C" -maxdepth 1 -name 'install*')" ] && ok "only your entries (and qargi's data in ~/.qargi, no install record) are left in the home" || no "left: $left $(ls "$C")"

# --- after the full uninstall a project-N.manifest of 0.3.1 planted in the config (no install.manifest, no install.json beside it) is removed
# unread: an install of that project does not take your own qargi-task for its own, and an uninstall removes nothing
PP=$T/pp; mkdir -p "$PP/.claude/skills/qargi-task"; echo mine > "$PP/.claude/skills/qargi-task/SKILL.md"
key=$(cd "$PP" && pwd -P | cksum | cut -d' ' -f1)
printf 'C\t%s\nf\t%s\n' "$PP/.claude/skills/qargi-task" "$PP/.claude/skills/qargi-task/SKILL.md" > "$C/project-$key.manifest"
p0=$(inventory "$PP")
out=$(inst --project "$PP" 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "removed $C/project-$key.manifest: a project record of qargi 0.3.1 with no install.manifest and no install.json beside it, so it was not read" \
  && echo "$out" | grep -q "refusing to replace existing $PP/.claude/skills/qargi-task (use --force)" && [ ! -e "$C/project-$key.manifest" ] && [ ! -e "$C/install.d" ] \
  && [ "$(inventory "$PP")" = "$p0" ]; } && ok "a planted project manifest of 0.3.1 alone is removed unread: the install refuses to replace your skill" || no "planted project manifest (rc=$rc): $out"
out=$(inst --project "$PP" --uninstall 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "no install manifest" && [ "$(inventory "$PP")" = "$p0" ]; } && ok "and the uninstall of that project removes nothing" || no "uninstall after a planted project manifest (rc=$rc): $out"

# --- links nobody recorded; one skills directory per runtime; a link the user retargeted
fresh; mkdir -p "$XS" "$H/.local/bin"
ln -s "$T/elsewhere" "$XS/qargi-flow"
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "refusing to replace $XS/qargi-flow, a link to $T/elsewhere that no install recorded (use --force)" && [ ! -e "$H/.local/bin/qargi" ]; } \
  && ok "a link no install recorded is not replaced" || no "foreign link (rc=$rc): $out"
[ ! -e "$C" ] && ok "a refused first install leaves no record, lock or config directory it made" || no "left after the refusal: $(find "$H/.qargi" 2>&1)"
rm "$XS/qargi-flow"; ln -s "$ROOT/skills/qargi-flow" "$XS/qargi-flow"; ino=$(stat -c %i "$XS/qargi-flow")
ln -s "$T/elsewhere" "$H/.local/bin/qargi"
out=$(inst --user --runtime codex 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "refusing to replace $H/.local/bin/qargi"; } && ok "so is a command link of another tree" || no "foreign command link (rc=$rc): $out"
out=$(inst --user --runtime codex --force 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(readlink "$H/.local/bin/qargi")" = "$ROOT/bin/qargi" ] && [ "$(stat -c %i "$XS/qargi-flow")" = "$ino" ] \
  && grep -q "^L	$XS/qargi-flow	$ROOT/skills/qargi-flow$" "$C/install.d/runtime-codex.manifest"; } && ok "--force replaces it; a link already pointing at the tool is adopted as it is and recorded" || no "force/adopt (rc=$rc): $out"
mkdir -p "$H/.claude"; ln -s "$XS" "$CS"
out=$(inst --user --runtime claude-code 2>&1); rc=$?
{ [ "$rc" = 1 ] && echo "$out" | grep -q "one skills directory holds the skills of one runtime" && [ ! -e "$C/install.d/runtime-claude-code.manifest" ]; } && ok "a Claude skills directory that is the Codex one (a link) is refused" || no "overlap (rc=$rc): $out"
rm "$CS"
rm "$XS/qargi-task"; ln -s "$T/elsewhere" "$XS/qargi-task"
out=$(inst --user --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(readlink "$XS/qargi-task")" = "$T/elsewhere" ] && echo "$out" | grep -q "kept $XS/qargi-task (a link to $T/elsewhere, not the one the install made)"; } && ok "an uninstall keeps a link the user pointed elsewhere, and says so" || no "retargeted link (rc=$rc): $out"

# --- a recorded link you replaced with a file of yours (a wrapper for the command): a run from a moved checkout refuses before it changes
# anything, the same way each time, and says what to do; once the file is moved aside the run goes through
fresh; inst --user >/dev/null 2>&1
rm "$H/.local/bin/qargi"; printf '#!/bin/sh\nexec %s "$@"\n' "$ROOT/bin/qargi" > "$H/.local/bin/qargi"; chmod 755 "$H/.local/bin/qargi"
before=$(inventory "$H")
for n in 1 2; do
  out=$(env -u QARGI_CONF -u QARGI_HOME HOME="$H" XDG_CONFIG_HOME="$H/.config" bash "$TL/install.sh" --user 2>&1); rc=$?
  { [ "$rc" = 1 ] && echo "$out" | grep -q "refusing to replace $H/.local/bin/qargi: the install recorded a link there and it is now a file, which is yours; nothing was changed: move it aside and install again, or install with --force" \
    && ! echo "$out" | grep -q "run the install again" && [ "$(inventory "$H")" = "$before" ]; } \
    && ok "run $n from a moved checkout over a recorded link you replaced with a file refuses with nothing changed (skills, man page, records, install.json)" || no "replaced link, run $n (rc=$rc): $out $(diff <(echo "$before") <(inventory "$H"))"
done
mv "$H/.local/bin/qargi" "$H/wrapper"
out=$(env -u QARGI_CONF -u QARGI_HOME HOME="$H" XDG_CONFIG_HOME="$H/.config" bash "$TL/install.sh" --user 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(readlink "$H/.local/bin/qargi")" = "$TL/bin/qargi" ] && [ "$(readlink "$CS/qargi-task")" = "$TL/skills/qargi-task" ]; } && ok "and with the file moved aside the run moves the install to the new checkout" || no "after moving the wrapper aside (rc=$rc): $out"

# --- a project with two runtimes: each hidden and removed on its own
fresh; P=$T/proj; mkdir -p "$P"; git init -q "$P"; X=$P/.git/info/exclude
inst --project "$P" >/dev/null 2>&1; inst --project "$P" --runtime codex >/dev/null 2>&1
{ [ "$(nlinks "$P/.claude/skills")" = "$NSKILLS" ] && [ "$(nlinks "$P/.agents/skills")" = "$NSKILLS" ] && grep -qx "/.claude/skills/qargi-task" "$X" && grep -qx "/.agents/skills/qargi-task" "$X"; } \
  && ok "a project gets the skills of both runtimes, each hidden" || no "project: $(ls -A "$P"; cat "$X")"
rm "$P/.agents/skills/qargi-task"
out=$(inst --project "$P" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -L "$P/.agents/skills/qargi-task" ]; } && ok "install --project without --runtime refreshes both" || no "project refresh (rc=$rc): $out"
out=$(inst --project "$P" --uninstall --runtime codex 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$P/.agents" ] && [ "$(nlinks "$P/.claude/skills")" = "$NSKILLS" ] && ! grep -q "/.agents/" "$X" && grep -qx "/.claude/skills/qargi-task" "$X"; } \
  && ok "removing codex from it removes its links and its exclude lines only" || no "project uninstall codex (rc=$rc): $out $(cat "$X")"
out=$(inst --project "$P" --uninstall 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$P/.claude" ] && ! grep -q "qargi-" "$X" && [ ! -e "$H/.qargi" ]; } && ok "and the bare uninstall removes the rest, with the config directory it made" || no "project uninstall (rc=$rc): $out"

[ "$fail" = 0 ] && echo "test_install_runtimes: all passed" || { echo "test_install_runtimes: FAILED"; exit 1; }
