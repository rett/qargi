#!/usr/bin/env bash
# Skills and tools: library, scope links, per-role disable, review and drift, provisioning render.
# Offline (fake ant). Run: tests/test_packs.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s; mkdir -p "$T/c/projects" "$T/s" "$T/bin"
printf '#!/usr/bin/env bash\ncase "$1" in auth) exit 0;; *) echo "{}";; esac\n' > "$T/bin/ant"; chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH
DA=./bin/qargi
proj() { jq -n --arg p "$1" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]},
         write:{base:"gh-pages",push:{mode:"none"},model:"claude-opus-5-5",effort:"medium",apt:[],skills:["pdf"]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha; proj beta

# --- a new skill fails its review until it is real
seal() { local tok; tok=$($DA skill seal "$1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA skill seal "$1" --plan "$tok" --approved test >/dev/null; }
desc() { sed -i "s/^description: .*/description: $2/" "$T/c/packs/skills/$1/SKILL.md"; seal "$1"; }
$DA skill new style --compatible any >/dev/null; $DA skill link style --scope user >/dev/null 2>&1 && no "a skill with a placeholder description was linked" || ok "a placeholder skill cannot be linked"
sed -i 's/^description: .*/description: Use when writing release notes in the house style./' "$T/c/packs/skills/style/SKILL.md"
$DA skill link style --scope user >/dev/null 2>&1 && no "an edited, unapproved skill was linked" || ok "an edited skill must be approved (sealed) before it links"
seal style; $DA skill link style --scope user >/dev/null 2>&1 && ok "a sealed skill links" || no "link failed"
$DA skill new style --compatible any >/dev/null 2>&1 && no "duplicate name accepted" || ok "names are unique"
$DA tool new style --compatible any >/dev/null 2>&1 && no "a tool took a skill's name" || ok "skills and tools share one namespace"

# --- scopes: user, user-role, project, project-role
$DA skill new build-only --compatible any >/dev/null; desc build-only "Use for build tasks."; $DA skill link build-only --scope user-role --role build >/dev/null
$DA skill new alpha-all --compatible any >/dev/null; desc alpha-all "Use on alpha."; $DA skill link alpha-all --scope project --project alpha >/dev/null
$DA skill new alpha-write --compatible any >/dev/null; desc alpha-write "Use for alpha write."; $DA skill link alpha-write --scope project-role --project alpha --role write >/dev/null
eff() { $DA skill effective "$1" "$2" | sort | paste -sd, -; }
[ "$(eff alpha build)" = "alpha-all,build-only,style" ] && ok "alpha/build gets user, user-role and project packs" || no "alpha/build: $(eff alpha build)"
[ "$(eff alpha write)" = "alpha-all,alpha-write,style" ] && ok "alpha/write gets user, project and project-role packs" || no "alpha/write: $(eff alpha write)"
[ "$(eff beta build)" = "build-only,style" ] && ok "beta/build gets only what reaches it (no alpha packs)" || no "beta/build: $(eff beta build)"
[ "$(eff beta write)" = "style" ] && ok "beta/write gets only the user pack" || no "beta/write: $(eff beta write)"

# --- opt out per role
$DA skill disable alpha build style >/dev/null && [ "$(eff alpha build)" = "alpha-all,build-only" ] && ok "a role can disable an inherited pack" || no "disable"
[ "$(eff alpha write)" = "alpha-all,alpha-write,style" ] && ok "the opt-out is for that role only" || no "opt-out leaked"
$DA skill enable alpha build style >/dev/null && [ "$(eff alpha build)" = "alpha-all,build-only,style" ] && ok "enable undoes the opt-out" || no "enable"

# --- drift and removal
echo "extra" >> "$T/c/packs/skills/style/SKILL.md"
$DA skill check alpha build >/dev/null 2>&1 && no "drift not detected" || ok "a changed pack fails check (drift)"
$DA packs render alpha build "$T/o" >/dev/null 2>&1 && no "render attached a drifted pack" || ok "provisioning refuses a drifted pack"
$DA skill remove style >/dev/null 2>&1 && no "removed a linked pack" || ok "a linked pack cannot be removed"
sed -i '$d' "$T/c/packs/skills/style/SKILL.md"   # undo the edit: the hash matches again
$DA skill check alpha build >/dev/null 2>&1 && ok "reverting the change clears the drift" || no "drift not cleared"

# what is not a regular file of one name is part of the content hash: a link, a pipe, an empty directory or a second name added to an approved pack is drift
# (find -type f saw none of them; `packs load` compares the hash alone, without the review)
for kind in link fifo emptydir hardlink; do
  sd=$T/c/packs/skills/style
  case $kind in link) ln -s /etc/hostname "$sd/added";; fifo) mkfifo "$sd/added";; emptydir) mkdir "$sd/added";; hardlink) ln "$sd/SKILL.md" "$sd/added";; esac
  $DA packs load style --project alpha --role build >/dev/null 2>&1 && no "a $kind added to an approved pack was not drift" || ok "a $kind added to an approved pack is drift (its content hash changed)"
  rm -rf "$sd/added"
done
$DA packs load style --project alpha --role build >/dev/null 2>&1 && ok "with it removed the pack loads again (a pack without such entries hashes as before)" || no "style does not load after removal"

# --- tools: allowlist and write-like tools
printf '%s' '{"name":"issues","url":"https://mcp.example.net/","tools":{"list_issues":"always_allow","create_issue":"always_allow"}}' > "$T/t.json"
$DA tool import "$T/t.json" --compatible any 2>&1 | grep -q "create_issue.*write-like" && ok "a write-like tool cannot run unattended" || no "write-like tool accepted"
printf '%s' '{"name":"issues","url":"https://mcp.example.net/","tools":{"list_issues":"always_allow","create_issue":"always_ask"}}' > "$T/t.json"
tok=$($DA tool import "$T/t.json" --compatible any | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
$DA tool import "$T/t.json" --compatible any --plan wrong --approved x >/dev/null 2>&1 && no "wrong plan token accepted" || ok "an import needs the token of the review"
$DA tool import "$T/t.json" --compatible any --plan "$tok" --approved "test" >/dev/null 2>&1 && ok "a reviewed tool is stored" || no "tool import"
$DA tool link issues --scope project-role --project beta --role build >/dev/null
$DA packs render beta build "$T/o2" >/dev/null 2>&1 && jq -e '.[0].name=="issues"' "$T/o2/mcp.json" >/dev/null && ok "render carries the tool" || no "render"

# --- a tool pack follows the same text-only and escape policy as a skill: a control or bidi character in a key or a string of the JSON (written
# as a JSON escape, so the file itself is plain ASCII) is refused at import, and nothing a tool pack holds reaches the terminal raw
printf '%s' '{"name":"esc1","url":"https://mcp.example.net/","write_ok":true,"tools":{"delete_repo":"always_allow","read\u001b[1A\u001b[2Kx":"always_ask"}}' > "$T/te.json"
! grep -q $'\x1b' "$T/te.json" && ok "the hostile tool pack is plain ASCII on disk" || no "test setup: raw escape in the file"
out=$(timeout 20 $DA tool import "$T/te.json" --compatible any 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "FAIL" <<<"$out" && grep -q "control or bidi character" <<<"$out" && ! grep -q '^plan token' <<<"$out" && [ ! -e "$T/c/packs/tools/esc1.json" ]; } && ok "a tool pack with an escape in a tool name is refused at import" || no "tool escape accepted: rc=$rc $out"
{ ! grep -q $'\x1b' <<<"$out" && grep -q 'NOTE: write_ok' <<<"$out" && grep -q 'read\\x1b\[1A\\x1b\[2Kx' <<<"$out"; } && ok "the tool review prints the name escaped, so the write_ok note stays on the terminal" || no "raw escape in the tool review: $(printf '%s' "$out" | od -c | head -8)"
printf '%s' '{"name":"esc2","url":"https://mcp.example.net/‮","tools":{"list_items":"always_allow"}}' > "$T/te2.json"
out=$(timeout 20 $DA tool import "$T/te2.json" --compatible any 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "control or bidi character" <<<"$out" && ! grep -q '^plan token' <<<"$out"; } && ok "a bidi character in a string of a tool pack is refused" || no "tool bidi accepted: rc=$rc $out"
printf '%s' '{"name":"esc3","url":"https://mcp.example.net/","tools":{"list_items":"always_ask\u001b[2K"}}' > "$T/te3.json"
out=$(timeout 20 $DA tool import "$T/te3.json" --compatible any 2>&1); rc=$?
{ [ $rc = 1 ] && ! grep -q $'\x1b' <<<"$out" && ! grep -q '^plan token' <<<"$out"; } && ok "an escape in a policy value is refused and not printed raw" || no "tool value escape: rc=$rc $out"
# a pack put into the library by hand is shown and checked escaped too
cp "$T/te.json" "$T/c/packs/tools/esc4.json"
out=$($DA tool show esc4 2>&1)
{ ! grep -q $'\x1b' <<<"$out" && grep -q 'read\\x1b\[1A\\x1b\[2Kx' <<<"$out" && grep -q 'control or bidi character' <<<"$out"; } && ok "tool show prints a hand-made pack escaped and says it fails" || no "tool show raw: $(printf '%s' "$out" | od -c | head -8)"
rm -f "$T/c/packs/tools/esc4.json"

# --- a skill from a directory, with a secret, is refused at import
mkdir -p "$T/src/leaky"; printf -- '---\nname: leaky\ndescription: Use when testing.\n---\nkey ghp_%s\n' "abcdefghijklmnopqrstuvwxyz0123456789" > "$T/src/leaky/SKILL.md"
$DA skill import "$T/src/leaky" --compatible any 2>&1 | grep -q "looks like a secret" && ok "a skill with a secret is refused at import" || no "secret skill accepted"

# --- a skill pack holds only text, like every other pack: a binary, an archive, a special file, a symlink, a NUL byte, invalid UTF-8, or a
# control or bidi character in a file or in its name is refused at import (the review says which and prints it escaped), and at seal
SKM=$'---\nname: NAME\ndescription: Use when testing the text-only policy.\n---\nbody\n'
mkskill_dir() { local d=$T/src/$1; rm -rf "$d"; mkdir -p "$d"; printf '%s' "${SKM//NAME/$1}" > "$d/SKILL.md"; }
for c in elf zip nul latin ctrl bidi crlf name fifo link big empty; do mkskill_dir pol-$c; done
printf '\x7fELF\x02\x01\x01\x00rest' > "$T/src/pol-elf/helper"
printf 'PK\x03\x04rest' > "$T/src/pol-zip/refs.dat"
printf 'a\x00b\n' > "$T/src/pol-nul/refs.md"
printf 'caf\xe9\n' > "$T/src/pol-latin/refs.md"
printf 'harmless\x1b[2K\x1b[1Aforged\n' > "$T/src/pol-ctrl/refs.md"
printf 'a \xe2\x80\xae txet\n' > "$T/src/pol-bidi/refs.md"
printf 'dos\r\nlines\r\n' > "$T/src/pol-crlf/refs.md"
printf 'x\n' > "$T/src/pol-name/$(printf 'n\x1b[8mame.md')"
mkfifo "$T/src/pol-fifo/pipe"
ln -s /etc/passwd "$T/src/pol-link/lnk"
head -c 1200000 /dev/urandom > "$T/src/pol-big/blob"   # over the 1 MB a file may hold, under the 2 MB a pack may hold in all: it used to pass unread
mkdir "$T/src/pol-empty/nothing"
for c in elf:"an ELF executable" zip:"a zip archive" nul:"NUL byte" latin:"not UTF-8" ctrl:"control or bidi character" bidi:"control or bidi character" name:"control or bidi character" fifo:"not a regular file" link:"symbolic link" big:"larger than 1000000 bytes" empty:"empty directory"; do
  n=pol-${c%%:*}; why=${c#*:}
  out=$(timeout 20 $DA skill import "$T/src/$n" --compatible any 2>&1); rc=$?
  { [ $rc = 1 ] && grep -q "FAIL" <<<"$out" && grep -q "$why" <<<"$out" && ! grep -q '^plan token' <<<"$out" && [ ! -e "$T/c/packs/skills/$n" ]; } && ok "a skill pack with $n is refused at import ($why)" || no "policy $n: rc=$rc $out"
done
out=$(timeout 20 $DA skill import "$T/src/pol-ctrl" --compatible any 2>&1); out2=$(timeout 20 $DA skill import "$T/src/pol-name" --compatible any 2>&1)
{ ! grep -q $'\x1b' <<<"$out$out2" && grep -q 'n\\x1b\[8mame.md' <<<"$out2"; } && ok "the review prints a file name with an escape in it escaped, not raw" || no "raw escape in the review: $(printf '%s' "$out$out2" | od -c | head -5)"
tok=$($DA skill import "$T/src/pol-crlf" --compatible any | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
[ -n "$tok" ] && ok "a carriage return before a newline (a DOS text file) is not a control character" || no "crlf refused"
# a stored skill that is changed afterwards is refused at seal
$DA skill new pol-late --compatible any >/dev/null; sed -i 's/^description: .*/description: Use when testing late additions./' "$T/c/packs/skills/pol-late/SKILL.md"; seal pol-late
printf '\x7fELF\x02\x01\x01\x00rest' > "$T/c/packs/skills/pol-late/helper"
out=$($DA skill seal pol-late 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "an ELF executable" <<<"$out" && ! grep -q '^plan token' <<<"$out"; } && ok "seal refuses a skill pack that gained a binary" || no "seal binary: rc=$rc $out"
rm -f "$T/c/packs/skills/pol-late/helper"
$DA skill new pol-hl --compatible any >/dev/null; sed -i 's/^description: .*/description: Use when testing hard links./' "$T/c/packs/skills/pol-hl/SKILL.md"; seal pol-hl
ln "$T/c/packs/skills/pol-hl/SKILL.md" "$T/c/packs/skills/pol-hl/again.md"
out=$($DA skill seal pol-hl 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "hard link" <<<"$out" && ! grep -q '^plan token' <<<"$out"; } && ok "seal refuses a skill pack that gained a second name for a file" || no "seal hard link: rc=$rc $out"
rm -f "$T/c/packs/skills/pol-hl/again.md"

# --- provisioning picks up attached skills and tools
$DA provision plan --project alpha --role write >/dev/null 2>&1
grep -q "./skills/alpha-all" "$T/s/provision/alpha-write/agents/alpha-write/agent.md" && [ -f "$T/s/provision/alpha-write/agents/alpha-write/skills/alpha-write/SKILL.md" ] && ok "provisioning attaches custom skills" || no "skills not in the rendered agent"
$DA provision plan --project beta --role build >/dev/null 2>&1
f=$T/s/provision/beta-build/agents/beta-build; grep -q "mcp_toolset" "$f/agent.md" && grep -q "create_issue" "$f/agent.md" && grep -q "permission_policy: {type: always_ask}" "$f/agent.md" && ok "provisioning attaches the tool with its policies" || no "tool not rendered"

# --- updating an existing cloud agent (fake ant records the calls)
cat > "$T/bin/ant" <<FAKE
#!/usr/bin/env bash
echo "\$*" >> "$T/calls.log"
case "\$1" in
  auth) exit 0;;
  apply) lock=""; names=(); a=("\$@"); for ((i=0;i<\${#a[@]};i++)); do [ "\${a[i]}" = --lock-file ] && lock=\${a[i+1]}; case "\${a[i]}" in skills/*) names+=("\${a[i]}");; esac; done
         { echo '{"resources":{'; sep=""; for n in "\${names[@]}"; do printf '%s"./%s":{"id":"skill_%s"}' "\$sep" "\$n" "\${n#skills/}"; sep=","; done; echo '}}'; } > "\$lock";;
  beta:agents) if [ "\$2" = retrieve ]; then echo '{"version":4,"tools":[{"type":"agent_toolset_20260401","default_config":{"enabled":true}}]}'; else echo "\$*" > "$T/update.args"; echo '{}'; fi;;
  beta:deployments) if [ "\$2" = retrieve ]; then echo '{"agent":{"version":5}}'; else echo '{}'; fi;;
  *) echo '{}';;
esac
FAKE
chmod 755 "$T/bin/ant"
$DA tool link issues --scope project-role --project alpha --role write >/dev/null
echo '{"alpha-write":{"location":"cloud","deployment_id":"depl_x","agent":{"id":"agent_x","version_pinned":4},"environment_id":"env_x","resources":[]}}' > "$T/c/instances.json"
out=$($DA packs apply alpha-write --asked "test"); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
echo "$out" | grep -q "custom skills:.*alpha-write" && ok "the apply plan lists the custom skills" || no "plan listing"
$DA packs apply alpha-write --asked "test" --approved x >/dev/null 2>&1 && no "applied without the plan token" || ok "apply refuses without the plan token"
$DA packs apply alpha-write --asked "test" --plan "$tok" --approved "test" >/dev/null 2>&1 && ok "apply runs with the token" || no "apply failed"
u=$(cat "$T/update.args" 2>/dev/null)
grep -q -- '--skill' <<<"$u" && grep -q '"type":"custom"' <<<"$u" && grep -q 'skill_alpha-write' <<<"$u" && grep -q '"skill_id":"pdf"' <<<"$u" && ok "the agent gets its anthropic and custom skills" || no "skills in the update: $u"

# --- QARGI_NESTED does not stand in for the plan token of a skill-changing verb
mkdir -p "$T/src/good"; printf -- '---\nname: good\ndescription: Use when testing the nested rule.\n---\nbody\n' > "$T/src/good/SKILL.md"
good_tok=$($DA skill import "$T/src/good" --compatible any | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
[ -n "$good_tok" ] || no "no token for the nested test import"
QARGI_NESTED=1 $DA skill import "$T/src/good" --compatible any --approved "an agent says so" >/dev/null 2>&1 && no "a nested import skipped the token" || ok "a nested import without the token is refused"
QARGI_NESTED=1 $DA skill import "$T/src/good" --compatible any --plan 000000000000 --approved x >/dev/null 2>&1 && no "a nested import took a wrong token" || ok "a nested import with a wrong token is refused"
[ ! -e "$T/c/packs/skills/good" ] && ok "nothing was stored by the refused nested imports" || no "a refused import stored the skill"
QARGI_NESTED=1 $DA skill import "$T/src/good" --compatible any --plan "$good_tok" --approved "a person read the review" >/dev/null 2>&1 && [ -d "$T/c/packs/skills/good" ] && ok "a nested import with the right token works (the token is what counts)" || no "nested import with the token"
tail -1 "$T/s/audit.log" | jq -e '.verb=="skill-import" and .nested==false' >/dev/null && ok "the audit line does not claim the call was nested" || no "audit nested flag: $(tail -1 "$T/s/audit.log")"
echo "more" >> "$T/c/packs/skills/good/SKILL.md"
QARGI_NESTED=1 $DA skill seal good --approved "x" >/dev/null 2>&1 && no "a nested seal skipped the token" || ok "a nested seal without the token is refused"
mkdir -p "$T/nosum"; printf '#!/usr/bin/env bash\nexit 0\n' > "$T/nosum/sha256sum"; chmod 755 "$T/nosum/sha256sum"
out=$(PATH=$T/nosum:$PATH $DA skill seal good --plan '' --approved "x" 2>&1) && no "an empty token was accepted" || { grep -q "no plan token" <<<"$out" && ok "an empty expected token is an error, not a match for an empty --plan" || no "empty token message: $out"; }
QARGI_NESTED=1 $DA tool import "$T/t.json" --compatible any --name issues2 --approved "x" >/dev/null 2>&1 && no "a nested tool import skipped the token" || ok "a nested tool import without the token is refused"
QARGI_NESTED=1 $DA packs apply alpha-write --asked "test" --approved x >/dev/null 2>&1 && no "a nested packs apply skipped the token" || ok "a nested packs apply without the token is refused"
rm -f "$T/update.args"
QARGI_NESTED=1 $DA packs apply alpha-write --asked "test" --approved x >/dev/null 2>&1; [ ! -e "$T/update.args" ] && ok "and it did not touch the agent" || no "agent updated by a nested apply"
grep -q 'mcp_toolset' <<<"$u" && grep -q 'agent_toolset_20260401' <<<"$u" && ok "the agent keeps its toolset and gains the MCP tool" || no "tools in the update"
grep -q '"name":"web_fetch","enabled":false' <<<"$u" && grep -q '"name":"web_search","enabled":false' <<<"$u" && ! grep -q '"name":"edit"' <<<"$u" && ok "apply switches the web tools off for a write role and keeps edit" || no "tool configs in the update: $u"
# --- load: what a role has enabled, read at call time
proj gamma
$DA skill new loadme --compatible any >/dev/null; desc loadme "Use for the load test."; mkdir -p "$T/c/packs/skills/loadme/refs"; echo extra > "$T/c/packs/skills/loadme/refs/x.md"; seal loadme
$DA skill link loadme --scope project-role --project gamma --role build >/dev/null
out=$($DA packs load --project gamma --role build 2>&1) && grep -q "skill loadme: Use for the load test." <<<"$out" && ok "load lists the enabled packs with their descriptions" || no "load index: $out"
out=$($DA packs load loadme --project gamma --role build 2>&1) && grep -q "^== skill loadme" <<<"$out" && grep -q "refs/x.md" <<<"$out" && ok "load prints one pack's text and lists its other files" || no "load pack: $out"
$DA packs load loadme --project gamma --role write >/dev/null 2>&1 && no "a pack not enabled for the role was loaded" || ok "load refuses a pack that is not enabled for that role"
$DA packs load '../x' --project gamma --role build >/dev/null 2>&1 && no "a path-like name was accepted" || ok "load refuses a name that is not a pack name"
$DA skill disable gamma build loadme >/dev/null; $DA packs load loadme --project gamma --role build >/dev/null 2>&1 && no "a disabled pack was loaded" || ok "disabling takes effect at once"
$DA skill enable gamma build loadme >/dev/null
echo tampered >> "$T/c/packs/skills/loadme/SKILL.md"
$DA packs load loadme --project gamma --role build >/dev/null 2>&1 && no "a drifted pack was loaded" || ok "load refuses a pack that changed since it was approved"
$DA packs load --project gamma >/dev/null 2>&1 && no "load without a role" || ok "load needs a role"
# --- compatible_providers: every pack declares which providers can use it; the declaration is approved with the content
rec() { jq -c ".$2" "$(if [ "$1" = tool ]; then echo "$T/c/packs/tools/$3.pack.json"; else echo "$T/c/packs/skills/$3/.pack.json"; fi)"; }
mkp() { # name compat: a sealed skill pack (the hash and record as `skill new` and seal write them)
  $DA skill new "$1" --compatible "$2" >/dev/null && sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md" && seal "$1"; }
$DA skill new nodecl >/dev/null 2>&1 && no "skill new without --compatible created a pack" || ok "skill new refuses a pack without compatible_providers"
[ ! -e "$T/c/packs/skills/nodecl" ] && ok "and creates nothing" || no "a refused new left a directory"
$DA tool new nodecl >/dev/null 2>&1 && no "tool new without --compatible created a pack" || ok "tool new refuses a pack without compatible_providers"
for bad in "" "any,claude" "Claude" "a b" "1x" '[]' '{"a":1}' '["any","any2",3]'; do
  $DA skill new badc --compatible "$bad" >/dev/null 2>&1 && no "compatible_providers '$bad' accepted" || ok "compatible_providers '$bad' is refused"
done
[ ! -e "$T/c/packs/skills/badc" ] && ok "a refused declaration creates nothing" || no "badc created"
# a trailing newline is not part of a name: "any\n" is not "any", and "a" and "a\n" are not one name written twice to slip past the duplicate check
for bad in '["any\n"]' '["a\n"]' '["a","a\n"]' '["a\n","a"]' '["any","any\n"]'; do
  python3 -I lib/packs_compat.py valid "$bad" >/dev/null 2>&1 && no "packs_compat valid took $bad" || ok "packs_compat valid refuses $bad"
done
for bad in $'any\n' $'a,a\n' $'a\n,b' '["any\n"]' '["a","a\n"]'; do
  $DA skill new badc --compatible "$bad" >/dev/null 2>&1 && no "compatible_providers ${bad@Q} accepted" || ok "compatible_providers ${bad@Q} is refused"
done
[ ! -e "$T/c/packs/skills/badc" ] && ok "a declaration with a newline creates nothing" || no "badc created from a newline"
$DA skill new decl --compatible "claude, fam ,claude" >/dev/null && [ "$(rec skill compatible_providers decl)" = '["claude","fam"]' ] && ok "a declaration is stored sorted, trimmed, without repeats" || no "decl record: $(rec skill compatible_providers decl)"
sed -i "s/^description: .*/description: Use for decl./" "$T/c/packs/skills/decl/SKILL.md"
$DA skill new decl2 --compatible '["fam","any-x"]' >/dev/null && [ "$(rec skill compatible_providers decl2)" = '["any-x","fam"]' ] && ok "a JSON array is accepted too" || no "decl2: $(rec skill compatible_providers decl2)"
$DA skill list | grep -q "^decl .*compatible: claude, fam" && ok "list shows the declaration" || no "list: $($DA skill list | grep decl)"
$DA skill import "$T/src/good" --name noimp >/dev/null 2>&1 && no "import without --compatible reviewed a pack" || ok "import refuses a pack without compatible_providers"
out=$($DA skill import "$T/src/good" --name impc --compatible claude); grep -q "^compatible_providers: claude" <<<"$out" && ok "the import review shows the declaration" || no "import review: $out"
itok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA skill import "$T/src/good" --name impc --compatible "claude,fam" --plan "$itok" --approved x >/dev/null 2>&1 && no "an import with another declaration took the token of the first" || ok "the token covers the declaration (another declaration needs its own approval)"
$DA skill import "$T/src/good" --name impc --compatible claude --plan "$itok" --approved x >/dev/null 2>&1 && [ "$(rec skill compatible_providers impc)" = '["claude"]' ] && ok "an import stores the approved declaration" || no "import record"

# the hash covers the field: the same files, another declaration, another hash; editing the record is drift
seal decl; h1=$($DA skill seal decl | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
$DA skill seal decl --compatible "fam" | grep -q "^compatible_providers changes: " && ok "sealing with another declaration says what changes" || no "seal change line"
h2=$($DA skill seal decl --compatible fam | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
[ -n "$h2" ] && [ "$h2" != "$h1" ] && ok "another declaration is another plan token (the same files hash differently)" || no "hash did not change: $h1 $h2"
mkp hashed any; $DA skill link hashed --scope project --project zeta >/dev/null 2>&1   # no such project: ignored
cp "$T/c/packs/skills/hashed/.pack.json" "$T/rec.keep"
jq '.compatible_providers = ["fam"]' "$T/rec.keep" > "$T/c/packs/skills/hashed/.pack.json"
proj hp; $DA skill link hashed --scope project --project hp >/dev/null 2>&1 && no "a pack whose declaration was edited was linked" || ok "an edited declaration is not the approved content (link refused)"
cp "$T/rec.keep" "$T/c/packs/skills/hashed/.pack.json"; $DA skill link hashed --scope project --project hp >/dev/null 2>&1
jq '.compatible_providers = ["fam"]' "$T/rec.keep" > "$T/c/packs/skills/hashed/.pack.json"
$DA skill check hp build 2>&1 | grep -q "drift" && ok "check reports the edited declaration as drift" || no "no drift for an edited declaration"
$DA packs render hp build "$T/oh" >/dev/null 2>&1 && no "render attached a pack whose declaration was edited" || ok "render refuses it"
cp "$T/rec.keep" "$T/c/packs/skills/hashed/.pack.json"

# a pack with no declaration (an earlier library) is refused wherever it is used, and sealed again with one
mkp legacy any; $DA skill link legacy --scope project --project hp >/dev/null
lh=$(cd "$T/c/packs/skills/legacy" && find . -type f ! -name .pack.json -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
jq --arg h "$lh" 'del(.compatible_providers) | .sha256 = $h' "$T/c/packs/skills/legacy/.pack.json" > "$T/rec.tmp" && cp "$T/rec.tmp" "$T/c/packs/skills/legacy/.pack.json"
$DA skill check hp build 2>&1 | grep -q "skill:legacy: FAIL: compatible_providers: not declared" && ok "check says a pack declares no compatible_providers" || no "check legacy: $($DA skill check hp build 2>&1)"
$DA packs render hp build "$T/ol" >/dev/null 2>&1 && no "render attached a pack with no declaration" || ok "render refuses a pack with no declaration"
$DA skill list | grep -q "^legacy .*compatible: NOT DECLARED" && ok "list marks it NOT DECLARED" || no "list legacy"
$DA skill seal legacy >/dev/null 2>&1 && no "seal accepted a pack with no declaration" || ok "seal refuses it until it is given --compatible"
out=$($DA skill seal legacy --compatible any); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA skill seal legacy --compatible any --plan "$tok" --approved test >/dev/null && [ "$(rec skill compatible_providers legacy)" = '["any"]' ] && $DA skill check hp build >/dev/null 2>&1 && ok "sealed with --compatible any, it passes check again" || no "reseal legacy"
$DA skill unlink legacy --scope project --project hp >/dev/null; $DA skill unlink hashed --scope project --project hp >/dev/null

# tool packs declare it too
printf '%s' '{"name":"ctool","url":"https://mcp.example.net/","tools":{"list_items":"always_allow"}}' > "$T/ct.json"
$DA tool import "$T/ct.json" >/dev/null 2>&1 && no "tool import without --compatible" || ok "tool import refuses a pack without compatible_providers"
tok=$($DA tool import "$T/ct.json" --compatible fam | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA tool import "$T/ct.json" --compatible fam --plan "$tok" --approved x >/dev/null 2>&1 && [ "$(rec tool compatible_providers ctool)" = '["fam"]' ] && ok "a tool pack is stored with its declaration" || no "tool record"

# matching: a runtime name or its family; a pack the provider is not on is skipped with a note, never attached silently
for rt in "famcli:local" "famhost:cloud"; do n=${rt%%:*}; s=${rt##*:}; mkdir -p "$T/c/packs/providers/$n"
  jq -n --arg n "$n" --arg s "$s" '{schema:2,kind:"provider",provider:$n,family:"fam",surface:$s,models:{pattern:"^.+$",tiers:{"*":{model:"m",alias:"m",verified_on:"2026-11-02",source:"test"}},effort:null},
    dispatch:{mode:"command",argv:[$n,"run"],prompt:{via:"stdin"},cwd:"{clone}",output:{format:"text"}},agents:null,resources:{},barrier:{kind:"none"}}' > "$T/c/packs/providers/$n/definition.json"
  python3 -I tests/handseal.py "$T/c/packs/providers/$n"; done                  # a library pack counts only once sealed
$DA skill unlink style --scope user >/dev/null; $DA skill unlink build-only --scope user-role --role build >/dev/null
mkp m-any any; mkp m-fam fam; mkp m-cli famcli; mkp m-host famhost; mkp m-other elsewhere; mkp m-two "elsewhere,fam"
jq -n '{schema:1,project:"mp",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  models:{provider:{local:"famcli",cloud:"famhost"}},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/mp.json"
for n in m-any m-fam m-cli m-host m-other m-two; do $DA skill link $n --scope project --project mp >/dev/null; done
$DA tool link ctool --scope project --project mp >/dev/null
out=$($DA skill effective mp build)
[ "$(grep -v '^skipped ' <<<"$out" | sort | paste -sd, -)" = "m-any,m-cli,m-fam,m-host,m-two" ] && ok "effective gives the packs whose declaration names the runtime of a surface, or its family, or any" || no "effective: $out"
grep -q "^skipped skill m-other: not compatible with famcli, famhost (it declares elsewhere)" <<<"$out" && ok "effective shows the skipped pack and why" || no "skipped line: $out"
grep -q "m-other" <<<"$(grep -v '^skipped ' <<<"$out")" && no "a skipped pack is in the effective list" || ok "a skipped pack is not in the list"
printf '%s' '{"name":"ctool2","url":"https://mcp.example.net/","tools":{"list_items":"always_allow"}}' > "$T/ct2.json"
tok=$($DA tool import "$T/ct2.json" --compatible elsewhere | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA tool import "$T/ct2.json" --compatible elsewhere --plan "$tok" --approved x >/dev/null 2>&1; $DA tool link ctool2 --scope project --project mp >/dev/null
[ "$($DA tool effective mp build | grep -v '^skipped ' | paste -sd, -)" = "ctool" ] && $DA tool effective mp build | grep -q "^skipped tool ctool2: not compatible with famcli, famhost" && ok "a tool pack is matched and skipped the same way" || no "tool skipped: $($DA tool effective mp build)"
$DA skill check mp build 2>&1 | grep -q "^skip skill m-other: not compatible" && ok "check says what it skipped" || no "check skip note"
$DA skill check mp build >/dev/null 2>&1 && ok "a skipped pack is not a failure" || no "check failed on a skip: $($DA skill check mp build 2>&1)"
out=$($DA packs render mp build "$T/om" 2>&1 >/dev/null); rc=$?
[ "$rc" = 0 ] && grep -q "note: skipped skill m-other: not compatible with famhost" <<<"$out" && ok "the cloud render notes the skip on stderr" || no "render note (rc=$rc): $out"
[ "$(sort "$T/om/custom_skills.txt" | paste -sd, -)" = "m-any,m-fam,m-host,m-two" ] && ok "the cloud render has the packs for the cloud runtime (a family or runtime name, or any)" || no "render skills: $(paste -sd, "$T/om/custom_skills.txt")"
[ ! -e "$T/om/skills/m-cli" ] && [ ! -e "$T/om/skills/m-other" ] && [ "$(jq -c '[.[].name]' "$T/om/mcp.json")" = '["ctool"]' ] && ok "a pack for the local runtime only, and one for another provider, are not in the cloud render (a tool for the family is)" || no "render has extra packs: $(jq -c . "$T/om/mcp.json")"
out=$($DA packs load --project mp --role build 2>&1); grep -q "skill m-fam:" <<<"$out" && grep -q "skipped skill m-other: not compatible" <<<"$out" && ok "load lists what is enabled and what was skipped" || no "load: $out"
$DA packs load m-other --project mp --role build 2>&1 | grep -q "m-other is linked but skipped for mp/build: not compatible" && ok "load names the reason for a pack it will not load" || no "load m-other"
# the same pack with the project's provider named by its runtime, then by a single family name
jq '.models.provider = "fam"' "$T/c/projects/mp.json" > "$T/mp.tmp" && cp "$T/mp.tmp" "$T/c/projects/mp.json"
[ "$($DA skill effective mp build | grep -v '^skipped ' | sort | paste -sd, -)" = "m-any,m-cli,m-fam,m-host,m-two" ] && ok "a project that names the family resolves it per surface" || no "family answer: $($DA skill effective mp build)"
# no provider at all: only "any" can be matched
jq 'del(.models)' "$T/c/projects/mp.json" > "$T/mp.tmp" && cp "$T/mp.tmp" "$T/c/projects/mp.json"
out=$($DA skill effective mp build); [ "$(grep -v '^skipped ' <<<"$out" | paste -sd, -)" = "m-any" ] && grep -q "^skipped skill m-fam: project mp names no provider to match against (it declares fam)" <<<"$out" && ok "a project with no provider gets only the packs for any, and the rest are noted" || no "no provider: $out"
$DA packs render mp build "$T/om2" >/dev/null 2>&1; [ "$(paste -sd, "$T/om2/custom_skills.txt")" = "m-any" ] && ok "the render of a project with no provider holds only the packs for any" || no "render without provider"
exit $fail
