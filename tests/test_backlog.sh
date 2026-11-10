#!/usr/bin/env bash
# The backlog (qargi backlog, the answer backlog.file): the answer is checked when it is set, list shows the items with their ids (an item without an
# id as unnumbered, a duplicated id flagged, --json), done is a plan and a token and then moves the item with the evidence and the date to the dated
# archive beside the file and removes it, and feature finish and release finish name the open items whose id the merged commits mention.
# Run: tests/test_backlog.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app QARGI_LEAD=lead-one
mkdir -p "$HOME" "$T/c/projects" "$T/bin" "$T/mem"
cat > "$T/bin/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://example.net/acme/app/pull/1;; esac
G
chmod +x "$T/bin/gh"; export PATH=$T/bin:$PATH
R=$T/app; git init -q -b master "$R"; git init -q --bare "$T/origin.git"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" push -q origin master develop
git -C "$R" checkout -q -b parked
P=$T/c/projects/app.json
$DA project template app | jq --arg p "$R" '.repo.url = "https://github.com/acme/app" | .repo.path = $p | .test_command = "true"' > "$P"
F="$DA feature"; REL="$DA release"
bl() { "$DA" backlog "$@"; }
bldone() { bl 'done' "$@"; }   # quoted: shellcheck takes a bare done after a word for the keyword
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
sum() { sha256sum "$@" 2>/dev/null | cut -d' ' -f1 | tr '\n' ' '; }
MEM=$T/mem/backlog.md
write_backlog() { cat > "$MEM" <<'EOF'
# Backlog

## Now

- [fix-names] Rename the two helpers that share a name
  second line of the item
  - a nested bullet that belongs to it

- [add-cache] Cache the lookups
- plain item without an id
- [x] a task-list box, not an id
* [star-item] a starred item

## Later

```text
- [in-fence] not an item, it is inside a code block
```

- [fix-names] a second item that uses a taken id
- [late-one] The last one
EOF
}

# --- 1. the answer is checked when it is set
out=$($DA project set app backlog.file 5 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'backlog.file: the path of a markdown file' <<<"$out" && ! jq -e 'has("backlog")' "$P" >/dev/null && ok "set refuses a file that is no path string, and changes nothing" || no "number rc=$rc: $out"
out=$($DA project set app backlog '{"file":"x.md","dir":"y"}' 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'backlog: an object like' <<<"$out" && ok "set refuses an unknown key under backlog" || no "unknown key rc=$rc: $out"
out=$($DA project set app backlog.file "$MEM" 2>&1) && [ "$(jq -r .backlog.file "$P")" = "$MEM" ] && $DA project validate app >/dev/null 2>&1 && ok "set stores the path and validate accepts it" || no "set path: $out"

# --- 2. list: nothing to read yet
out=$(bl list 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the backlog file $MEM (backlog.file) does not exist" <<<"$out" && ok "list says when the file is missing (exit 1)" || no "missing file rc=$rc: $out"
jq 'del(.backlog)' "$P" > "$P.new" && mv "$P.new" "$P"
out=$(bl list 2>&1); rc=$?
[ $rc = 1 ] && grep -q 'qargi project set app backlog.file PATH' <<<"$out" && ok "list with the answer unset names it (exit 1)" || no "unset rc=$rc: $out"
$DA project set app backlog.file "$MEM" >/dev/null 2>&1

# --- 3. list
write_backlog
out=$(bl list 2>&1); rc=$?
[ $rc = 0 ] && grep -q ": 7 open items\$" <<<"$out" && ok "list counts the items (fenced and heading lines are none)" || no "count rc=$rc: $out"
grep -q '^  fix-names  Rename the two helpers that share a name   (duplicate id: lines 5, 20)$' <<<"$out" && grep -q '^  fix-names  a second item that uses a taken id   (duplicate id: lines 5, 20)$' <<<"$out" \
  && grep -q '^duplicate ids: fix-names' <<<"$out" && ok "a duplicated id is flagged on both items and said again" || no "duplicates: $out"
grep -q '^  star-item  a starred item$' <<<"$out" && grep -q '^  -  *plain item without an id$' <<<"$out" && grep -q '^  -  *\[x\] a task-list box, not an id$' <<<"$out" && grep -q '^(2 without an id' <<<"$out" \
  && ! grep -q 'in-fence\|nested bullet' <<<"$out" && ok "items without an id are shown as '-', the continuation belongs to its item, a fence is no item" || no "unnumbered: $out"
out=$(bl list --json 2>&1); rc=$?
jq -e '.file == "'"$MEM"'" and (.items | length) == 7 and .duplicates == ["fix-names"] and .items[0].id == "fix-names" and .items[0].duplicate == true and .items[0].line == 5
       and (.items[0].full | contains("a nested bullet that belongs to it")) and .items[2].id == null and .items[2].text == "plain item without an id"' <<<"$out" >/dev/null \
  && ok "list --json gives the file, each item and the duplicated ids" || no "json rc=$rc: $out"
bl list extra >/dev/null 2>&1; r1=$?; bl list --evidence x >/dev/null 2>&1; r2=$?
[ "$r1" = 2 ] && [ "$r2" = 2 ] && ok "list takes no id and no evidence (exit 2)" || no "list usage $r1 $r2"

# --- 4. done: the plan changes nothing, and it needs the evidence
export QARGI_NOW=2026-11-08
before=$(sum "$MEM"); ARCH=$T/mem/backlog-archive-2026-11.md
out=$(bldone add-cache 2>&1); rc=$?
[ $rc = 2 ] && grep -q 'done needs --evidence' <<<"$out" && ok "done without evidence is a usage error" || no "no evidence rc=$rc: $out"
out=$(bldone add-cache --evidence "  " 2>&1); rc=$?
[ $rc = 1 ] && grep -q -- '--evidence needs the words' <<<"$out" && ok "blank evidence is refused" || no "blank evidence rc=$rc: $out"
out=$(bldone add-cache --evidence "merged in feature/cache, suite green" 2>&1); rc=$?; t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "move this item out of $MEM into $ARCH" <<<"$out" && grep -q '^  | - \[add-cache\] Cache the lookups$' <<<"$out" && grep -q '^  evidence: merged in feature/cache, suite green$' <<<"$out" \
  && grep -q '^  dated 2026-11-08$' <<<"$out" && ok "the plan shows the item, the evidence and the target, with a token" || no "plan rc=$rc: $out"
[ "$(sum "$MEM")" = "$before" ] && [ ! -e "$ARCH" ] && ! grep -q 'backlog:done' "$T/s/audit.log" 2>/dev/null && ok "the plan deletes and writes nothing" || no "plan changed something"
out=$(bldone add-cache --evidence "merged in feature/cache, suite green" --json 2>&1)
jq -e '.verb == "backlog done" and (.token | test("^[0-9a-f]+$")) and (.plan | contains("[add-cache]")) and (.apply | contains("--evidence"))' <<<"$out" >/dev/null && ok "done --json gives the plan and its token" || no "done json: $out"
out=$(bldone add-cache --evidence "merged in feature/cache, suite green" --plan "$t" 2>&1); [ -n "$(tok <<<"$out")" ] && [ "$(sum "$MEM")" = "$before" ] && ok "a token without the approval is the plan again" || no "token alone: $out"
out=$(bldone add-cache --evidence "merged in feature/cache, suite green" --plan 000000000000 --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'the plan changed or --plan is missing' <<<"$out" && [ "$(sum "$MEM")" = "$before" ] && [ ! -e "$ARCH" ] && ok "a wrong token is refused and nothing changes" || no "wrong token rc=$rc: $out"
out=$(QARGI_NESTED=1 bldone add-cache --evidence "merged in feature/cache, suite green" --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'the plan changed or --plan is missing' <<<"$out" && [ "$(sum "$MEM")" = "$before" ] && [ ! -e "$ARCH" ] && ok "done with no token under the nested variable is refused, the backlog and archive did not change" || no "nested done, no token rc=$rc: $out"
out=$(QARGI_NESTED=1 bldone add-cache --evidence "merged in feature/cache, suite green" --plan 000000000000 --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'the plan changed or --plan is missing' <<<"$out" && [ "$(sum "$MEM")" = "$before" ] && [ ! -e "$ARCH" ] && ok "and a wrong token is refused under the nested variable too" || no "nested done, wrong token rc=$rc: $out"
out=$(bldone add-cache --evidence "another set of words" --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && [ "$(sum "$MEM")" = "$before" ] && ok "the token is of the evidence too" || no "other evidence rc=$rc: $out"
out=$(bldone nope-x --evidence e 2>&1); rc=$?
[ $rc = 1 ] && grep -q 'no open item \[nope-x\]' <<<"$out" && ok "an id that is not there is refused" || no "unknown id rc=$rc: $out"
out=$(bldone fix-names --evidence e 2>&1); rc=$?
[ $rc = 1 ] && grep -q 'the id \[fix-names\] is used by 2 items (lines 5, 20)' <<<"$out" && ok "an id used twice is refused, naming the lines" || no "duplicate id rc=$rc: $out"
out=$(bldone 'Bad Id' --evidence e 2>&1); rc=$?
[ $rc = 1 ] && grep -q 'a lowercase slug' <<<"$out" && ok "an id that is no slug is refused" || no "bad id rc=$rc: $out"

# --- 5. done: the apply
out=$(bldone add-cache --evidence "merged in feature/cache, suite green" --plan "$t" --approved "yes, archive add-cache" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "done \[add-cache\]: moved to $ARCH and removed from $MEM" <<<"$out" && ok "the apply says where the item went" || no "apply rc=$rc: $out"
! grep -q 'add-cache' "$MEM" && grep -q '^- plain item without an id$' "$MEM" && grep -q '^\* \[star-item\]' "$MEM" && grep -q '^  - a nested bullet' "$MEM" \
  && ok "the item is gone from the backlog and the rest is as it was" || no "backlog after: $(cat "$MEM")"
[ "$(cat "$ARCH")" = "$(printf '# backlog archive 2026-11\n\n### 2026-11-08: add-cache\n\n- [add-cache] Cache the lookups\n\nEvidence: merged in feature/cache, suite green')" ] && ok "the archive is created with a heading, the date, the item as written and the evidence" || no "archive: $(cat "$ARCH")"
[ "$(jq -rs '[.[] | select(.verb == "backlog:done")] | map(.detail + "|" + .approved) | join(",")' "$T/s/audit.log")" = "app add-cache|yes, archive add-cache" ] && ok "the apply leaves an audit line" || no "audit: $(cat "$T/s/audit.log")"
bldone add-cache --evidence x >/dev/null 2>&1 && no "a done item is still there" || ok "the same id is not found again"
# an item with continuation lines and nested bullets goes with all of them; a second done in the month appends to the same archive; another month is another file
write_backlog
sed -i 's/^- \[fix-names\] a second item.*/- [fix-names-2] a second item that uses a taken id/' "$MEM"
out=$(bldone fix-names --evidence "renamed" 2>&1); t=$(tok <<<"$out")
bldone fix-names --evidence "renamed" --plan "$t" --approved go >/dev/null 2>&1
exp=$(printf '# Backlog\n\n## Now\n\n- [add-cache] Cache the lookups\n- plain item without an id\n- [x] a task-list box, not an id\n* [star-item] a starred item\n\n## Later\n\n```text\n- [in-fence] not an item, it is inside a code block\n```\n\n- [fix-names-2] a second item that uses a taken id\n- [late-one] The last one\n_')
[ "$(cat "$MEM"; echo _)" = "$exp" ] && ok "the item goes with its continuation and nested bullet, and one blank line is left where it stood" || no "after fix-names: $(cat "$MEM")"
grep -q '^### 2026-11-08: fix-names$' "$ARCH" && grep -q '^  second line of the item$' "$ARCH" && grep -q '^  - a nested bullet that belongs to it$' "$ARCH" && [ "$(grep -c '^### ' "$ARCH")" = 2 ] \
  && [ "$(grep -c '^# backlog archive' "$ARCH")" = 1 ] && ok "a second done appends to the archive of the month" || no "archive 2: $(cat "$ARCH")"
export QARGI_NOW=2026-12-02
out=$(bldone star-item --evidence "line one
line two" 2>&1); t=$(tok <<<"$out")
bldone star-item --evidence "line one
line two" --plan "$t" --approved go >/dev/null 2>&1
[ "$(cat "$T/mem/backlog-archive-2026-12.md")" = "$(printf '# backlog archive 2026-12\n\n### 2026-12-02: star-item\n\n* [star-item] a starred item\n\nEvidence: line one\n  line two')" ] && ok "another month is another archive file (a multi-line evidence is indented)" || no "december: $(cat "$T/mem/backlog-archive-2026-12.md")"
! grep -q 'star-item' "$MEM" && [ -e "$T/mem/backlog-archive-2026-11.md" ] && [ "$(grep -c '^### ' "$ARCH")" = 2 ] && ok "the November archive was not touched by it" || no "november"
unset QARGI_NOW
[ -z "$(find "$T/mem" -mindepth 1 ! -name 'backlog*')" ] && ok "no temporary file is left beside the backlog" || no "left over: $(find "$T/mem" -mindepth 1)"
# a relative path is taken from the repository; ~/ from the home directory
mkdir -p "$R/docs"; printf -- '- [rel-item] in the repository\n' > "$R/docs/backlog.md"; $DA project set app backlog.file docs/backlog.md >/dev/null 2>&1
bl list 2>&1 | grep -q '^  rel-item  in the repository$' && ok "a relative path is taken from the repository" || no "relative"
printf -- '- [home-item] under home\n' > "$HOME/bl.md"
# shellcheck disable=SC2088  # the answer holds the tilde as typed; qargi expands it
$DA project set app backlog.file '~/bl.md' >/dev/null 2>&1
bl list 2>&1 | grep -q '^  home-item  under home$' && ok "a path under the home directory (tilde slash) is taken from it" || no "home"
rm -rf "$R/docs"

# --- 5b. backlog.section: only the list under the heading holds items; backlog.archive: where the archive goes
SF=$T/mem/sect.md; AD=$T/mem/arch
cat > "$SF" <<'EOF'
# Backlog

- [top-one] above every section

## Now

- [now-one] first of now
### Detail

- [now-deep] under a deeper heading, still in Now

## Later

- [later-one] in Later
EOF
$DA project set app backlog.file "$SF" >/dev/null 2>&1
out=$($DA project set app backlog.section '## Now' 2>&1); rc=$?
[ $rc = 0 ] && [ "$(jq -r .backlog.section "$P")" = "## Now" ] && ok "backlog.section is stored" || no "set section rc=$rc: $out"
out=$(bl list 2>&1)
grep -q ': 2 open items$' <<<"$out" && grep -q '^  now-one  *first of now$' <<<"$out" && grep -q '^  now-deep  *under a deeper heading' <<<"$out" && ! grep -q 'top-one\|later-one' <<<"$out" \
  && ok "list shows only the items under the section (a deeper heading belongs to it, the next heading of its level ends it)" || no "section list: $out"
out=$(bl list --json 2>&1); jq -e '.section == "## Now" and (.items | map(.id)) == ["now-one","now-deep"]' <<<"$out" >/dev/null && ok "list --json names the section" || no "section json: $out"
out=$(bldone later-one --evidence e 2>&1); rc=$?
[ $rc = 1 ] && grep -q 'no open item \[later-one\]' <<<"$out" && ok "done refuses an item outside the section" || no "outside the section rc=$rc: $out"
$DA project set app backlog.section Missing >/dev/null 2>&1
out=$(bl list 2>&1); rc=$?
[ $rc = 1 ] && grep -q "no heading 'Missing' in the backlog file (backlog.section)" <<<"$out" && ok "a heading that is not in the file is an error" || no "missing heading rc=$rc: $out"
$DA project set app backlog.section Now >/dev/null 2>&1
export QARGI_NOW=2026-11-08
out=$(bldone now-one --evidence "finished" 2>&1); t=$(tok <<<"$out")
bldone now-one --evidence "finished" --plan "$t" --approved go >/dev/null 2>&1
{ ! grep -q now-one "$SF" && grep -q 'top-one' "$SF" && grep -q 'later-one' "$SF" && [ -f "$T/mem/sect-archive-2026-11.md" ]; } && ok "done removes the item of the section and archives it beside the file" || no "section done: $(cat "$SF")"
# the archive in a directory of its own (created), named as before; a relative path is taken from the repository; a name ending in .md is the one archive file
$DA project set app backlog.archive "$AD" >/dev/null 2>&1
out=$(bldone now-deep --evidence "second" 2>&1); t=$(tok <<<"$out")
grep -q "into $AD/sect-archive-2026-11.md" <<<"$out" && ok "the plan names the archive in backlog.archive" || no "archive plan: $out"
bldone now-deep --evidence "second" --plan "$t" --approved go >/dev/null 2>&1
{ [ -f "$AD/sect-archive-2026-11.md" ] && grep -q '^### 2026-11-08: now-deep$' "$AD/sect-archive-2026-11.md" && grep -q '^# sect archive 2026-11$' "$AD/sect-archive-2026-11.md"; } && ok "the archive directory is created and holds the monthly file" || no "archive dir: $(ls -R "$AD")"
cat > "$SF" <<'EOF'
## Now

- [one-aa] first
- [one-bb] second
EOF
$DA project set app backlog.archive "$T/mem/all.md" >/dev/null 2>&1
for i in one-aa one-bb; do
  out=$(bldone "$i" --evidence "ev $i" 2>&1); t=$(tok <<<"$out"); bldone "$i" --evidence "ev $i" --plan "$t" --approved go >/dev/null 2>&1
done
[ "$(grep -c '^### ' "$T/mem/all.md")" = 2 ] && grep -q '^# all$' "$T/mem/all.md" && ok "a backlog.archive ending in .md is the one archive file, whatever the month" || no "one archive file: $(cat "$T/mem/all.md")"
$DA project set app backlog.archive "$(printf 'a\nb')" >/dev/null 2>&1 && no "a control character in backlog.archive accepted" || ok "backlog.archive refuses a control character"
$DA project set app backlog.section '##' >/dev/null 2>&1 && no "an empty heading accepted" || ok "backlog.section refuses a heading with no text"
unset QARGI_NOW
jq 'del(.backlog.archive, .backlog.section)' "$P" > "$P.new" && mv "$P.new" "$P"

# --- 5c. add: one item, validated; done: a batch with one plan and one token
AF=$T/mem/add.md; printf -- '# Backlog\n\n- [aa-one] first\n' > "$AF"
$DA project set app backlog.file "$AF" >/dev/null 2>&1
out=$(bl add bb-two "second item" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "added \[bb-two\] to $AF" <<<"$out" && [ "$(cat "$AF")" = "$(printf '# Backlog\n\n- [aa-one] first\n- [bb-two] second item')" ] && ok "add appends the item to the list" || no "add rc=$rc: $out; $(cat "$AF")"
[ "$(jq -rs '[.[] | select(.verb == "backlog:add")] | map(.detail) | join(",")' "$T/s/audit.log")" = "app bb-two" ] && ok "add leaves an audit line" || no "add audit: $(cat "$T/s/audit.log")"
out=$(bl add cc-three "third" --detail "why it matters
and how" 2>&1); rc=$?
[ $rc = 0 ] && tail -3 "$AF" | head -1 | grep -qx -- '- \[cc-three\] third' && tail -2 "$AF" | head -1 | grep -qx '  why it matters' && tail -1 "$AF" | grep -qx '  and how' && ok "add --detail writes indented lines that belong to the item" || no "add detail rc=$rc: $out; $(cat "$AF")"
bl list 2>&1 | grep -q ': 3 open items$' && ok "and list shows the three items" || no "list after add: $(bl list 2>&1)"
cp "$AF" "$T/add.before"
out=$(bl add aa-one "again" 2>&1); rc=$?
[ $rc = 1 ] && grep -q 'the id \[aa-one\] is already an item (line 3)' <<<"$out" && cmp -s "$AF" "$T/add.before" && ok "add refuses an id that is taken and changes nothing" || no "dup add rc=$rc: $out"
for bad in 'Bad Id' a 'UPPER'; do
  out=$(bl add "$bad" "x" 2>&1); rc=$?
  [ $rc = 1 ] && grep -q 'a lowercase slug' <<<"$out" && cmp -s "$AF" "$T/add.before" && ok "add refuses the id '$bad' (no slug)" || no "bad slug '$bad' rc=$rc: $out"
done
out=$(bl add dd-four 2>&1); rc=$?; [ $rc = 2 ] && grep -q 'usage: qargi backlog' <<<"$out" && ok "add without a text is a usage error" || no "add usage rc=$rc: $out"
out=$(bl add dd-four "x" --evidence e 2>&1); rc=$?; [ $rc = 2 ] && ok "add takes no evidence" || no "add evidence rc=$rc: $out"
out=$(bl add dd-four "  " 2>&1); rc=$?; [ $rc = 1 ] && grep -q 'the text needs words' <<<"$out" && ok "add refuses a blank text" || no "blank text rc=$rc: $out"
# the section: the item goes to the end of the list under the heading
printf -- '# Backlog\n\n## Now\n\n- [aa-one] first\n\n## Later\n\n- [zz-last] last\n' > "$AF"
$DA project set app backlog.section Now >/dev/null 2>&1
bl add bb-two "second" >/dev/null 2>&1
[ "$(cat "$AF")" = "$(printf '# Backlog\n\n## Now\n\n- [aa-one] first\n- [bb-two] second\n\n## Later\n\n- [zz-last] last')" ] && ok "with backlog.section the item goes to the end of that section's list" || no "add in section: $(cat "$AF")"
out=$(bl add zz-last "taken in Later" 2>&1); rc=$?
[ $rc = 1 ] && grep -q 'the id \[zz-last\] is already an item' <<<"$out" && ok "an id taken outside the section is refused too" || no "dup outside section rc=$rc: $out"
jq 'del(.backlog.section)' "$P" > "$P.new" && mv "$P.new" "$P"
# done with several ids: one plan, one token, the same evidence for each, one apply
printf -- '- [aa-one] first\n- [bb-two] second\n  more\n- [cc-three] third\n- [dd-four] fourth\n' > "$AF"
export QARGI_NOW=2026-11-08; AARCH=$T/mem/add-archive-2026-11.md; rm -f "$AARCH"
out=$(bldone aa-one cc-three --evidence "shipped together" 2>&1); rc=$?; t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && [ "$(grep -c '^plan token:' <<<"$out")" = 1 ] && grep -q '^done 2 items (\[aa-one\], \[cc-three\]): move them out of' <<<"$out" && grep -q '^  | - \[aa-one\] first$' <<<"$out" \
  && grep -q '^  | - \[cc-three\] third$' <<<"$out" && grep -q 'qargi backlog done aa-one cc-three --evidence' <<<"$out" && ok "a batch has one plan listing every item, and one token" || no "batch plan rc=$rc: $out"
cp "$AF" "$T/add.before"
out=$(bldone aa-one cc-three --evidence "shipped together" --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(printf '%s\n' "$out" | grep -c '^done \[')" = 2 ] && [ "$(cat "$AF")" = "$(printf -- '- [bb-two] second\n  more\n- [dd-four] fourth')" ] && ok "the apply removes every item of the batch and no other" || no "batch apply rc=$rc: $out; $(cat "$AF")"
[ "$(grep -c '^### ' "$AARCH")" = 2 ] && [ "$(grep -c '^Evidence: shipped together$' "$AARCH")" = 2 ] && grep -q '^### 2026-11-08: aa-one$' "$AARCH" && grep -q '^### 2026-11-08: cc-three$' "$AARCH" && ok "the same evidence is archived with each id" || no "batch archive: $(cat "$AARCH")"
[ "$(jq -rs '[.[] | select(.verb == "backlog:done")] | last | .detail' "$T/s/audit.log")" = "app aa-one cc-three" ] && ok "one audit line names the batch" || no "batch audit: $(tail -1 "$T/s/audit.log")"
# a token for one id does not apply the batch; a missing, repeated or comma-joined id refuses all and changes nothing
printf -- '- [aa-one] first\n- [bb-two] second\n' > "$AF"; cp "$AF" "$T/add.before"; rm -f "$AARCH"
t1=$(tok <<<"$(bldone aa-one --evidence e 2>&1)")
out=$(bldone aa-one bb-two --evidence e --plan "$t1" --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'the plan changed or --plan is missing' <<<"$out" && cmp -s "$AF" "$T/add.before" && [ ! -e "$AARCH" ] && ok "the token of one id does not apply a batch" || no "token of one rc=$rc: $out"
for ids in 'aa-one nope-x' 'aa-one aa-one' 'aa-one,bb-two'; do
  # shellcheck disable=SC2086  # the ids are split on purpose
  out=$(bldone $ids --evidence e 2>&1); rc=$?
  [ $rc != 0 ] && [ -z "$(tok <<<"$out")" ] && cmp -s "$AF" "$T/add.before" && ok "the batch '$ids' is refused with no plan, nothing changed" || no "batch '$ids' rc=$rc: $out"
done
unset QARGI_NOW

# --- 6. feature finish names the open items the commits mention (information only)
$DA project set app backlog.file "$MEM" >/dev/null 2>&1
printf -- '# Backlog\n\n- [add-cache] Cache the lookups\n- [late-one] The last one\n- [never-named] Nobody mentions it\n- [ci] a short id\n- plain\n' > "$MEM"
task() { # name SUBJECT [BODY]: a task branch with one commit, cut from develop
  git -C "$R" branch "agent/$1" develop; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "$2" ${3:+-m "$3"}; git -C "$R" worktree remove --force "$w"
}
$F start bl >/dev/null 2>&1
task b1 "Cache the lookups, closes add-cache"; task b2 "Touches xadd-cache, add-cache-more and late-one2" "and a body that says late-one."; task b3 "Not a word: specific"
for b in b1 b2 b3; do $F merge bl agent/$b >/dev/null 2>&1; done
$F verify bl >/dev/null 2>&1
d0=$(git -C "$R" rev-parse develop)
out=$($F finish bl 2>&1); rc=$?; t1=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t1" ] && grep -qx '  backlog items named in these commits: add-cache, late-one' <<<"$out" && ok "feature finish names the open items whose id a commit message holds (subject or body), in backlog order" || no "feature plan rc=$rc: $out"
! grep -q 'never-named\|backlog items named.*ci' <<<"$out" && ok "an id inside a longer word or slug, and an id nobody mentions, is not named" || no "false hit: $out"
[ "$(git -C "$R" rev-parse develop)" = "$d0" ] && grep -q 'add-cache' "$MEM" && ok "the plan acts on neither the repository nor the backlog" || no "plan acted"
jq 'del(.backlog)' "$P" > "$P.new" && mv "$P.new" "$P"
out=$($F finish bl 2>&1); t2=$(tok <<<"$out")
! grep -q 'backlog' <<<"$out" && [ "$t1" = "$t2" ] && ok "answer unset: no line, and the token is the same (the line is information only)" || no "unset: $out"
$DA project set app backlog.file "$T/mem/gone.md" >/dev/null 2>&1
out=$($F finish bl 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q 'backlog' <<<"$out" && [ "$(tok <<<"$out")" = "$t1" ] && ok "file missing: no line and no failure" || no "missing: rc=$rc $out"
$DA project set app backlog.file "$MEM" >/dev/null 2>&1
# backlog.section: only the list under the heading holds items, so the plan names only the commits' ids that are in it
cp "$MEM" "$T/mem/plain.md"
printf -- '# Backlog\n\n## Now\n\n- [add-cache] Cache the lookups\n\n## Later\n\n- [late-one] The last one\n- [never-named] Nobody mentions it\n' > "$MEM"
$DA project set app backlog.section Now >/dev/null 2>&1
out=$($F finish bl 2>&1); grep -qx '  backlog items named in these commits: add-cache' <<<"$out" && ok "backlog.section: the finish plan names only the items under the heading" || no "section Now: $out"
$DA project set app backlog.section '## Later' >/dev/null 2>&1
out=$($F finish bl 2>&1); grep -qx '  backlog items named in these commits: late-one' <<<"$out" && ok "backlog.section may be written with its #s" || no "section Later: $out"
$DA project set app backlog.section Missing >/dev/null 2>&1
out=$($F finish bl 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q 'backlog items' <<<"$out" && [ -n "$(tok <<<"$out")" ] && ok "a heading that is not in the file names nothing and fails nothing" || no "section Missing: rc=$rc $out"
jq 'del(.backlog.section)' "$P" > "$P.new" && mv "$P.new" "$P"
out=$($F finish bl 2>&1); grep -qx '  backlog items named in these commits: add-cache, late-one' <<<"$out" && ok "without the section both lists are read" || no "section unset: $out"
cp "$T/mem/plain.md" "$MEM"
bldone add-cache --evidence "finished" --plan "$(bldone add-cache --evidence finished | tok)" --approved go >/dev/null 2>&1
out=$($F finish bl 2>&1); grep -qx '  backlog items named in these commits: late-one' <<<"$out" && ok "an item that was done is open no longer" || no "after done: $out"
t=$(tok <<<"$out"); $F finish bl --plan "$t" --approved go >/dev/null 2>&1 && [ "$(git -C "$R" rev-list --count "$d0..develop")" -gt 0 ] && ok "the finish itself goes on as before" || no "finish apply"

# --- 7. release finish names them too
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q --detach "$w" develop; echo r > "$w/r.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "A release change for never-named"
git -C "$R" update-ref refs/heads/develop "$(git -C "$w" rev-parse HEAD)"; git -C "$R" worktree remove --force "$w"
$REL verify 0.2.0 >/dev/null 2>&1
p=$($REL start 0.2.0 --date 2026-01-02 2>&1); $REL start 0.2.0 --date 2026-01-02 --plan "$(tok <<<"$p")" --approved go >/dev/null 2>&1
p=$($REL push 0.2.0 2>&1); $REL push 0.2.0 --plan "$(tok <<<"$p")" --approved go >/dev/null 2>&1
out=$($REL finish 0.2.0 2>&1); rc=$?; r1=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$r1" ] && grep -qx '  backlog items named in these commits: late-one, never-named' <<<"$out" && ok "release finish names the open items of the commits it merges" || no "release plan rc=$rc: $out"
jq 'del(.backlog)' "$P" > "$P.new" && mv "$P.new" "$P"
out=$($REL finish 0.2.0 2>&1); [ "$(tok <<<"$out")" = "$r1" ] && ! grep -q 'backlog' <<<"$out" && ok "release finish: answer unset, no line, same token" || no "release unset: $out"

exit "$fail"
