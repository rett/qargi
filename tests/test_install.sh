#!/usr/bin/env bash
# install.sh: the skills it installs agree with skills/, their front matter is YAML a strict parser reads, an install links them,
# a second run changes nothing, an existing real directory is kept unless --force, an uninstall removes the links, and a project install hides them through the local
# exclude file without touching the owner's lines. Hermetic home; nothing touches the real ~/.claude. Run: tests/test_install.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
unset XDG_DATA_HOME
ROOT=$PWD; T=$(mktemp -d); fail=0
trap 'rm -rf "$T"; rm -rf "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh
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

# --- the front matter of every shipped skill is YAML a strict parser reads: a runtime that parses it strictly drops a skill it cannot read, without a
# word. Each line is `key: value`; an unquoted value starts with no YAML indicator (- ? : followed by a space, or , [ ] { } # & * ! | > ' " % @ `)
# and holds no ': ' and no ' #' (a strict parser fails on the first and reads a comment from the second); a quoted value is one quoted
# scalar with nothing after it. The rule is tried on samples first, so a check that accepts everything fails. EXPECTED names the skills whose front
# matter fails it today and is fixed outside this test; an entry that passes fails, so the list only shrinks.
EXPECTED=""
fm_check() { # FILE... -> one line per file: FILE<TAB>ok or FILE<TAB>line N: why
  python3 -I - "$@" <<'PY'
import sys

INDICATORS = ",[]{}#&*!|>'\"%@`"


def quoted_end(v, q):
    """The index after the closing quote of the scalar quoted with q at the start of v, or None when it is not closed."""
    i = 1
    while i < len(v):
        if q == '"' and v[i] == "\\":
            i += 2
            continue
        if v[i] == q:
            if q == "'" and v[i + 1:i + 2] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return None


def problem(v):
    if v == "":
        return "no value (a strict parser reads null or a nested block)"
    if v[0] in "\"'":
        end = quoted_end(v, v[0])
        if end is None:
            return "a quoted value that is not closed"
        return None if v[end:].strip() == "" else "text after the closing quote of a quoted value"
    if v[0] in "-?:" and (len(v) == 1 or v[1] == " "):
        return "an unquoted value that starts with '%s '" % v[0]
    if v[0] in INDICATORS:
        return "an unquoted value that starts with '%s'" % v[0]
    if ": " in v or v.endswith(":"):
        return "an unquoted value with ': ' in it"
    if " #" in v or "\t" in v:
        return "an unquoted value with ' #' or a tab in it"
    return None


def check(text):
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return "no front matter between two --- lines"
    for n, line in enumerate(lines[1:lines.index("---", 1)], 2):
        key, sep, value = line.partition(": ")
        if not sep and line.endswith(":"):
            key, sep, value = line[:-1], ":", ""
        if not sep or not key or not key.replace("-", "").replace("_", "").isalnum():
            return "line %d: not a `key: value` line" % n
        why = problem(value)
        if why:
            return "line %d: %s" % (n, why)
    return None


samples = {"plain words, a/b|c (d) and NAME.md": None, "'single ''quoted'' text'": None, '"double \\"quoted\\" text"': None, "-x is plain": None,
           "a: b": "': '", "ends with:": "': '", "[NAME]": "'['", "{a}": "'{'", "- item": "'- '", "* star": "'*'", "@at": "'@'", "`tick`": "'`'",
           '"<task>" --done "<check>"': "after the closing quote", "'open": "not closed", "a #comment": "' #'", "": "no value"}
for v, want in samples.items():
    got = problem(v)
    if (got is None) != (want is None) or (want and want not in got):
        print("SELFTEST\tthe rule gives %r for %r, not %r" % (got, v, want))
for f in sys.argv[1:]:
    with open(f, encoding="utf-8") as fh:
        why = check(fh.read())
    print("%s\t%s" % (f, why or "ok"))
PY
}
while IFS=$'\t' read -r f res; do
  s=${f#skills/}; s=${s%/SKILL.md}
  if [ "$f" = SELFTEST ]; then no "the front matter rule fails its own samples: $res"
  elif [[ " $EXPECTED " == *" $s "* ]]; then
    if [ "$res" = ok ]; then no "skill $s: its front matter now parses; remove it from EXPECTED in this test"
    else echo "expected  skill $s: front matter a strict YAML parser fails ($res), fixed outside this test"; fi
  elif [ "$res" = ok ]; then ok "skill $s: its front matter is YAML a strict parser reads"
  else no "skill $s: its front matter is not YAML a strict parser reads ($res)"; fi
done < <(cd "$ROOT" && fm_check skills/*/SKILL.md)

mkdir -p "$T/elsewhere"

# --- --user ---
out=$(bash "$INSTALL" --user 2>&1); rc=$?
[ "$rc" = 0 ] && ok "install --user succeeds" || no "install --user: rc=$rc $out"
miss=''; for s in $CURRENT; do [ "$(readlink "$S/$s")" = "$ROOT/skills/$s" ] && [ -d "$S/$s" ] || miss="$miss $s"; done
[ -z "$miss" ] && ok "the skills are installed as links into the checkout" || no "skills missing:$miss"

before=$(find "$S" -maxdepth 1 -type l -printf "%f -> %l\n" | sort)
bash "$INSTALL" --user >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$before" = "$(find "$S" -maxdepth 1 -type l -printf "%f -> %l\n" | sort)" ] && ok "a second run changes nothing" || no "second run: rc=$rc"

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
# no manifest: nothing is recorded, so uninstall removes nothing and fails, with --force too (no guessing at fixed paths)
mkdir "$S/qargi-flow"; echo mine > "$S/qargi-flow/notes.md"; ln -s "$T/elsewhere" "$S/qargi-team"; echo mine > "$S/other-skill"
out=$(bash "$INSTALL" --user --uninstall 2>&1); rc=$?
{ [ "$rc" != 0 ] && [ -f "$S/qargi-flow/notes.md" ] && [ -L "$S/qargi-team" ] && echo "$out" | grep -q "no install manifest" && echo "$out" | grep -q "nothing was removed"; } && ok "without a manifest uninstall says so and removes nothing" || no "uninstall without a manifest: rc=$rc $out"
out=$(bash "$INSTALL" --user --uninstall --force 2>&1); rc=$?
{ [ "$rc" != 0 ] && [ -f "$S/qargi-flow/notes.md" ] && [ -L "$S/qargi-team" ] && [ -d "$T/elsewhere" ] && [ -f "$S/other-skill" ]; } && ok "uninstall --force without a manifest removes nothing either" || no "uninstall --force without a manifest: rc=$rc $out"
rm -rf "$S/qargi-flow" "$S/other-skill"; rm -f "$S/qargi-team"

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
# the copied tool is complete: every directory a modified copy needs (TOOL_DIRS) is there, and the installed command runs from it
D=$HOME/.local/share/qargi; miss=''
for d in $TOOL_DIRS; do [ ! -e "$ROOT/$d" ] || [ -e "$D/$d" ] || miss="$miss $d"; done
[ -z "$miss" ] && ok "install --user --copy copies every entry of TOOL_DIRS (missing:${miss:- none})" || no "the copy lacks:$miss"
[ -f "$D/canon/CANON.md" ] && [ -f "$D/canon/layout.json" ] && [ -f "$D/catalog/tools.json" ] && ok "the copy has canon/ and catalog/" || no "canon/ or catalog/ is not in $D"
out=$("$HOME/.local/bin/qargi" help 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'discover' <<<"$out"; } && ok "the installed command runs from the copy: qargi help" || no "installed qargi help (rc=$rc): $out"
out=$("$HOME/.local/bin/qargi" discover search pdf 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'skill-pdf' <<<"$out"; } && ok "and discover finds the catalog entries of catalog/tools.json" || no "installed discover (rc=$rc): $out"
P2=$T/proj2; mkdir -p "$P2"; git init -q "$P2"
bash "$INSTALL" --project "$P2" --copy >/dev/null 2>&1; rc=$?
miss=''; for r in $refs; do cmp -s "$ROOT/skills/$r" "$P2/.claude/skills/$r" || miss="$miss $r"; done
[ "$rc" = 0 ] && [ -z "$miss" ] && ok "install --project --copy copies the reference files too" || no "project copy: rc=$rc missing or different:$miss"
bash "$INSTALL" --user --uninstall --force >/dev/null 2>&1; bash "$INSTALL" --project "$P2" --uninstall --force >/dev/null 2>&1

# --- the install manifest: --copy then --uninstall leaves nothing of qargi's under a fresh home, and only what the install wrote is removed ---
H2=$T/h2; mkdir -p "$H2"
inst2() { HOME=$H2 XDG_CONFIG_HOME=$H2/.config bash "$INSTALL" "$@"; }
out=$(inst2 --user --copy 2>&1); rc=$?
M=$QARGI_CONF/install.manifest
{ [ "$rc" = 0 ] && [ -s "$M" ] && grep -q "^C	$H2/.local/share/qargi$" "$M" && grep -q "^C	$H2/.claude/skills/qargi-task$" "$M" && grep -q "^C	$H2/.local/share/man/man1/qargi.1$" "$M"; } && ok "a copy install records what it wrote in the manifest" || no "copy install manifest (rc=$rc): $out"
echo mine > "$H2/.local/share/qargi/keep-me.txt"; mkdir -p "$H2/.claude/skills/mine"; echo mine > "$H2/.claude/skills/mine/SKILL.md"
echo stray > "$H2/.local/share/man/man1/other.1"
"$H2/.local/bin/qargi" help >/dev/null 2>&1   # runs the copy, which leaves bytecode in it
out=$(inst2 --user --uninstall 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$M" ] && [ ! -e "$H2/.local/bin/qargi" ] && [ ! -e "$H2/.local/share/man/man1/qargi.1" ] && [ ! -e "$H2/.local/share/bash-completion" ] \
  && [ ! -e "$H2/.local/share/zsh" ] && [ ! -e "$H2/.config" ] && [ ! -e "$H2/.claude/skills/qargi-task" ] && [ ! -e "$H2/.local/share/qargi/lib" ]; } && ok "uninstall after --copy removes the skills, command, man page, completions and the copied tool" || no "uninstall after --copy (rc=$rc): $out"
{ [ -f "$H2/.local/share/qargi/keep-me.txt" ] && [ -f "$H2/.claude/skills/mine/SKILL.md" ] && [ -f "$H2/.local/share/man/man1/other.1" ] && echo "$out" | grep -q "kept $H2/.local/share/qargi"; } && ok "files the install did not write are kept (and a directory holding one is said to be kept)" || no "uninstall removed or hid a file that was not in the manifest: $out"
files=$(cd "$H2" && find . -type f | sort | tr '\n' ' ')
[ "$files" = "./.claude/skills/mine/SKILL.md ./.local/share/man/man1/other.1 ./.local/share/qargi/keep-me.txt " ] && ok "nothing else of qargi's is left under the home" || no "files left under the home: $files"
rm -rf "$H2"; mkdir -p "$H2"
[ -d "$QARGI_CONF/packs" ] && ok "uninstall leaves the user's data (the pack library under the config) alone" || no "uninstall removed the pack library"

# a second --copy install over the first needs no --force (it is the install's own), a link install over a copy leaves no copy behind
inst2 --user --copy >/dev/null 2>&1; rc=$?
inst2 --user --copy >/dev/null 2>&1; rc2=$?
[ "$rc" = 0 ] && [ "$rc2" = 0 ] && ok "a copy install repeated over its own copy needs no --force" || no "repeated copy install: rc=$rc rc2=$rc2"
echo mine > "$H2/.claude/skills/qargi-task/notes.md"
out=$(inst2 --user --copy 2>&1); rc=$?
{ [ "$rc" != 0 ] && echo "$out" | grep -q "refusing to replace existing $H2/.claude/skills/qargi-task"; } && ok "a copied skill with a file of yours inside is not replaced without --force" || no "copy with a stray file: rc=$rc $out"
rm -f "$H2/.claude/skills/qargi-task/notes.md"
inst2 --user >/dev/null 2>&1
{ [ ! -e "$H2/.local/share/qargi" ] && [ -L "$H2/.claude/skills/qargi-task" ]; } && ok "a link install over a copy install removes the copied tool" || no "link over copy left the data directory"
inst2 --user --uninstall >/dev/null 2>&1
[ -z "$(find "$H2" -mindepth 1 | head -1)" ] && ok "and its uninstall leaves nothing either" || no "left after the link install: $(find "$H2" -mindepth 1 | head -5)"

# --- the skills directories come from the runtime's definition ---
TL=$T/tool; copy_tool "$ROOT" "$TL"; cp "$ROOT/install.sh" "$TL/"; mkdir -p "$TL/completions" "$TL/man"; cp "$ROOT"/completions/* "$TL/completions/"; cp "$ROOT/man/qargi.1" "$TL/man/"
find "$TL" -name __pycache__ -prune -exec rm -rf {} +   # a copy of a checkout that ran has bytecode: the install below must be what makes it
sed -i 's#"user_dir": "~/.claude/skills"#"user_dir": "~/.alt/skills"#; s#"project_dir": ".claude/skills"#"project_dir": ".alt/skills"#' "$TL/lib/providers/claude-code.json"
H3=$T/h3; P3=$T/proj3; mkdir -p "$H3" "$P3"; git init -q "$P3"
out=$(HOME=$H3 XDG_CONFIG_HOME=$H3/.config bash "$TL/install.sh" --user 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -L "$H3/.alt/skills/qargi-task" ] && [ ! -e "$H3/.claude" ]; } && ok "--user takes the user skills directory from the runtime's definition" || no "user layout (rc=$rc): $out"
out=$(HOME=$H3 bash "$TL/install.sh" --project "$P3" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -L "$P3/.alt/skills/qargi-task" ] && [ ! -e "$P3/.claude" ] && grep -qx "/.alt/skills/qargi-task" "$P3/.git/info/exclude"; } && ok "--project takes the project skills directory from it, and hides that one" || no "project layout (rc=$rc): $out"
ls "$TL"/lib/__pycache__/guard.*.pyc >/dev/null 2>&1 && ok "--user compiles the tool's lib/ (bin/qargi imports the guard from it on every tool call, and python caches only an imported module)" || no "--user left no bytecode of the guard in $TL/lib"
HOME=$H3 bash "$TL/install.sh" --project "$P3" --uninstall >/dev/null 2>&1
HOME=$H3 XDG_CONFIG_HOME=$H3/.config bash "$TL/install.sh" --user --uninstall >/dev/null 2>&1
{ [ ! -e "$P3/.alt" ] && [ ! -e "$H3/.alt" ] && ! grep -q "alt/skills" "$P3/.git/info/exclude"; } && ok "and the uninstalls follow it" || no "uninstall with a changed layout left: $(find "$H3" "$P3" -path "$P3/.git" -prune -o -name '*alt*' -print)"

# --- a tool the user cannot write to (a checkout installed with sudo): the install still works, says the bytecode was not compiled, and writes nothing into the tool ---
if [ "$(id -u)" != 0 ]; then
  RO=$T/ro; H6=$T/h6; mkdir -p "$H6"; copy_tool "$ROOT" "$RO"; cp "$ROOT/install.sh" "$RO/"; mkdir -p "$RO/completions" "$RO/man"; cp "$ROOT"/completions/* "$RO/completions/"; cp "$ROOT/man/qargi.1" "$RO/man/"
  find "$RO" -name __pycache__ -prune -exec rm -rf {} +
  chmod -R a-w "$RO"
  out=$(HOME=$H6 XDG_CONFIG_HOME=$H6/.config QARGI_CONF=$H6/qconf bash "$RO/install.sh" --user 2>&1); rc=$?
  nopyc=$(find "$RO" -name __pycache__ | head -1)
  { [ "$rc" = 0 ] && [ -z "$nopyc" ] && echo "$out" | grep -q "bytecode of $RO/lib was not compiled" && echo "$out" | grep -q "sudo python3 -I -m compileall -q $RO/lib"; } && ok "a read-only tool is installed, with a note on how to compile it, and nothing is written into it" || no "read-only tool (rc=$rc, pycache: $nopyc): $out"
  guard_rc=0; printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git push origin HEAD"},"cwd":"/"}' | HOME=$H6 QARGI_CONF=$H6/qconf "$RO/bin/qargi" __guard >/dev/null 2>&1 || guard_rc=$?
  [ "$guard_rc" = 2 ] && ok "and the guard of a read-only tool still answers (without cached bytecode)" || no "guard of a read-only tool: exit $guard_rc"
  HOME=$H6 XDG_CONFIG_HOME=$H6/.config QARGI_CONF=$H6/qconf bash "$RO/install.sh" --user --uninstall >/dev/null 2>&1
  chmod -R u+w "$RO" "$H6"   # the packs seeded from the tool keep its mode
fi

# --- the config directory (~/.qargi/config) a project install made goes with its uninstall once it is empty, and only then ---
H4=$T/h4; P4=$T/proj4; mkdir -p "$H4" "$P4"; git init -q "$P4"
inst4() { env -u QARGI_CONF -u QARGI_HOME HOME="$H4" bash "$INSTALL" "$@"; }
out=$(inst4 --project "$P4" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -d "$H4/.qargi/config" ] && grep -q "^c	$H4/.qargi/config$" "$H4"/.qargi/config/project-*.manifest; } && ok "a project install records the config directory it made" || no "project install config record (rc=$rc): $out"
inst4 --project "$P4" >/dev/null 2>&1   # a reinstall keeps the record of the directory the first one made
out=$(inst4 --project "$P4" --uninstall 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$H4/.qargi" ] && [ ! -e "$P4/.claude/skills/qargi-task" ]; } && ok "its uninstall removes the empty config directory it made, and ~/.qargi with it" || no "project uninstall left (rc=$rc): $(find "$H4" -mindepth 1) $out"
inst4 --project "$P4" >/dev/null 2>&1; echo '{}' > "$H4/.qargi/config/answers.json"
inst4 --project "$P4" --uninstall >/dev/null 2>&1
{ [ -f "$H4/.qargi/config/answers.json" ] && [ -z "$(find "$H4/.qargi/config" -name 'project-*.manifest')" ]; } && ok "a config directory that holds anything else is kept" || no "config with a file of yours: $(find "$H4" -mindepth 1)"
rm -rf "$H4/.qargi"; mkdir -p "$H4/.qargi/config"
inst4 --project "$P4" >/dev/null 2>&1; inst4 --project "$P4" --uninstall >/dev/null 2>&1
[ -d "$H4/.qargi/config" ] && ok "an empty config directory the install did not make is kept" || no "uninstall removed a config directory it did not make"
out=$(HOME=$H3 bash "$INSTALL" --user --runtime claude-platform 2>&1); rc=$?
{ [ "$rc" != 0 ] && echo "$out" | grep -q "no user skills directory" && echo "$out" | grep -q "cannot take user_skills_dir"; } && ok "a runtime with no skills directory is refused, with the reason" || no "runtime without a skills directory: rc=$rc $out"
out=$(HOME=$H3 bash "$INSTALL" --user --runtime nosuch 2>&1); rc=$?
{ [ "$rc" != 0 ] && echo "$out" | grep -q "unknown provider 'nosuch'"; } && ok "an unknown runtime is refused" || no "unknown runtime: rc=$rc $out"
[ ! -e "$H3/.claude" ] && ok "a refused install writes nothing" || no "a refused install wrote $H3/.claude"

[ "$fail" = 0 ] && echo "test_install: all passed" || { echo "test_install: FAILED"; exit 1; }
