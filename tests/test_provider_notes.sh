#!/usr/bin/env bash
# The notes of a runtime's definition and the verb that reads them: `provider notes [TOPIC] [--project P]` prints the text of TOPIC from the
# definition of the project's local runtime (composed with its extensions; the project is --project, else the one in effect), or lists the
# topics when it is given none. A topic or a runtime with no notes is exit 1 and names both; a project with no local runtime has no
# provider to ask, and a runtime that cannot be used as it stands (a library pack never sealed or changed since, a definition that is not
# readable) is refused: both are exit 2 (there is no default); the verb changes nothing. A definition lists the topics that are about the
# lead's own session (lead_notes); with a lead runtime named (--lead-runtime NAME, else QARGI_LEAD_RUNTIME; the option wins) those come from
# that runtime and the others from the project's, a name that is no usable local runtime or a note about the lead that it lacks is
# unsupported (exit 3, never answered by the project's runtime), and with neither the output is what it was. Hermetic and offline: a copy
# of the tool holds the fake runtimes (tests/fakeprov.sh), so the shipped definitions are never changed. Run: tests/test_provider_notes.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
# notey: a local runtime with two notes of its own; plain: one with none; every other note of the shipped runtime is dropped, and with
# the notes the list that says which of them are about the lead (lead_notes names topics of notes only)
fake_runtime "$SRC" "$TOOL" notey local '.notes = {"alpha": "The alpha text.", "beta-2": "The beta text, with a comma."} | del(.lead_notes)'
fake_runtime "$SRC" "$TOOL" plain local 'del(.notes, .lead_notes)'

mkproj() { # NAME PROVIDER-JSON: stored answers with a repository of their own
  local repo=$T/repo-$1
  mkdir -p "$repo"
  jq -n --arg n "$1" --arg p "$repo" --argjson prov "$2" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
    roles:{build:{base:"main",push:{mode:"none"},effort:"medium"}},models:{provider:$prov},memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
}
mkproj withnotes '"notey"'
mkproj nonotes '"plain"'
mkproj cloudonly '{"cloud":"claude-platform"}'
mkproj noprov 'null'
jq 'del(.models.provider)' "$T/c/projects/noprov.json" > "$T/np" && mv "$T/np" "$T/c/projects/noprov.json"

# run NAME... : stdout, stderr and status of `qargi provider notes ...` from outside every project
run() { out=$("$DA" provider notes "$@" 2>"$T/err"); rc=$?; err=$(cat "$T/err"); }

run alpha --project withnotes
{ [ $rc = 0 ] && [ "$out" = "The alpha text." ] && [ -z "$err" ]; } && ok "a topic prints its text and nothing else" || no "alpha: rc=$rc out=$out err=$err"
run --project withnotes beta-2
{ [ $rc = 0 ] && [ "$out" = "The beta text, with a comma." ]; } && ok "--project may come first" || no "beta-2: rc=$rc out=$out err=$err"
run --project withnotes
{ [ $rc = 0 ] && [ "$out" = "alpha
beta-2" ]; } && ok "no topic lists the topic names, one per line" || no "list: rc=$rc out=$out err=$err"

# the project in effect: inside its repository, or QARGI_PROJECT
out=$(cd "$T/repo-withnotes" && "$DA" provider notes alpha 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$out" = "The alpha text." ]; } && ok "inside a project's repository the project is the one in effect" || no "in effect: rc=$rc $out"
out=$(QARGI_PROJECT=withnotes "$DA" provider notes beta-2 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$out" = "The beta text, with a comma." ]; } && ok "QARGI_PROJECT names the project" || no "QARGI_PROJECT: rc=$rc $out"
run alpha
{ [ $rc = 2 ] && grep -q "no project" <<<"$err" && [ -z "$out" ]; } && ok "with no project in effect it is exit 2 and says so" || no "no project: rc=$rc out=$out err=$err"
run alpha --project nosuch
{ [ $rc = 2 ] && grep -q "no such project 'nosuch'" <<<"$err"; } && ok "an unknown project is exit 2" || no "unknown project: rc=$rc err=$err"

# a topic that does not exist: exit 1, the message names the topic and the runtime and lists the topics there are
run gamma --project withnotes
{ [ $rc = 1 ] && [ -z "$out" ] && grep -q "notey" <<<"$err" && grep -q "gamma" <<<"$err" && grep -q "alpha, beta-2" <<<"$err"; } \
  && ok "an unknown topic is exit 1 naming the topic and the runtime and listing the topics" || no "unknown topic: rc=$rc out=$out err=$err"
run 'Not A Topic' --project withnotes
{ [ $rc = 1 ] && grep -q "Not A Topic" <<<"$err"; } && ok "a topic that cannot be a name is an unknown topic too" || no "bad topic: rc=$rc err=$err"

# a runtime with no notes
run alpha --project nonotes
{ [ $rc = 1 ] && [ -z "$out" ] && grep -q "plain" <<<"$err" && grep -q "alpha" <<<"$err" && grep -q "no notes" <<<"$err"; } \
  && ok "a runtime with no notes is exit 1 naming the topic and the runtime" || no "no notes: rc=$rc out=$out err=$err"
run --project nonotes
{ [ $rc = 1 ] && grep -q "plain" <<<"$err" && grep -q "no notes" <<<"$err"; } && ok "listing the topics of a runtime with none is exit 1" || no "list no notes: rc=$rc out=$out err=$err"

# no default provider: a project with none, or with none for the local surface, is exit 2 and falls back to nothing
run alpha --project noprov
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "has no provider" <<<"$err" && ! grep -qi "claude" <<<"$err"; } && ok "a project with no provider is exit 2 (no default)" || no "no provider: rc=$rc out=$out err=$err"
run alpha --project cloudonly
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "no local provider" <<<"$err"; } && ok "a project with no local runtime is exit 2 (the verb asks for the local surface)" || no "cloud only: rc=$rc out=$out err=$err"

# a runtime that cannot be used as it stands is a refusal (exit 2), not "no such topic" (exit 1)
mkdir -p "$T/c/packs/providers/unsealed"
jq '.provider = "unsealed" | .family = null | .notes = {"alpha": "x"} | del(.adapter, .adapter_verbs, .lead_notes)' "$SRC/lib/providers/claude-code.json" > "$T/c/packs/providers/unsealed/definition.json"
mkproj unsealedp '"unsealed"'
run alpha --project unsealedp
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "never reviewed" <<<"$err"; } && ok "a library runtime that was never sealed is exit 2" || no "unsealed: rc=$rc out=$out err=$err"
printf '{ not json' > "$TOOL/lib/providers/garbled.json"
mkproj garbledp '"garbled"'
run alpha --project garbledp
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "garbled" <<<"$err"; } && ok "a definition that is not readable is exit 2" || no "garbled: rc=$rc out=$out err=$err"
run --project garbledp
[ $rc = 2 ] && ok "listing the topics of such a runtime is exit 2 too" || no "garbled list: rc=$rc out=$out err=$err"

# the shipped runtime of Claude Code has the topics the skills point at, and the text of a topic is what the verb prints
mkproj onclaude '{"local":"claude-code","cloud":"claude-platform"}'
run --project onclaude
{ [ $rc = 0 ] && [ "$out" = "commands
exploration
identity
member-out
session-model
skills-dir
spawn" ]; } && ok "the shipped claude-code lists its topics" || no "claude-code topics: rc=$rc out=$out err=$err"
run spawn --project onclaude
{ [ $rc = 0 ] && grep -q 'subagent_type' <<<"$out"; } && ok "claude-code says how a lead spawns a member" || no "claude-code spawn: rc=$rc out=$out err=$err"
topics=$(grep -rhoE 'qargi provider notes [a-z][a-z0-9-]*' skills packs contract roles agents 2>/dev/null | awk '{print $4}' | sort -u)
missing=
for t in $topics; do run "$t" --project onclaude; [ $rc = 0 ] || missing="$missing $t"; done
[ -z "$missing" ] && ok "every topic a skill points at exists in claude-code${topics:+ ($(tr '\n' ' ' <<<"$topics" | sed 's/ $//'))}" || no "skills point at topics claude-code lacks:$missing"
# the shipped runtime of Codex: a command runtime, so its spawn note sends the lead to `qargi local run`, not to an in-session tool
mkproj oncodex '{"local":"codex"}'
run --project oncodex
{ [ $rc = 0 ] && [ "$out" = "commands
exploration
identity
message
session-model
skills-dir
spawn" ]; } && ok "the shipped codex lists its topics" || no "codex topics: rc=$rc out=$out err=$err"
run message --project oncodex
{ [ $rc = 0 ] && grep -q 'codex queue --thread ID_OR_NAME --message TEXT' <<<"$out" && grep -q 'never an approval' <<<"$out"; } \
  && ok "codex says how to send a session a message without attaching, and that a message is no approval" || no "codex message: rc=$rc out=$out err=$err"
run spawn --project oncodex
{ [ $rc = 0 ] && grep -q 'qargi local run RUN' <<<"$out" && grep -q 'qargi local prepare' <<<"$out" && ! grep -q 'subagent_type' <<<"$out"; } \
  && ok "codex says a member is started with qargi local run" || no "codex spawn: rc=$rc out=$out err=$err"
# the lead identity on codex: no hook records it, and the verbs outside the marshal take no --as, so the note says to start the session
# with QARGI_LEAD set and never sends a lead to an --as those verbs do not have
run identity --project oncodex
{ [ $rc = 0 ] && grep -qF 'start the session with `QARGI_LEAD=ID` set' <<<"$out" && grep -qF '`feature`, `local`, `review` and `release` read it' <<<"$out" \
  && grep -qF 'only marshal verbs take `--as ID`' <<<"$out" && ! grep -q 'commands that take it' <<<"$out"; } \
  && ok "codex says the lead identity is QARGI_LEAD, set when the session starts, and that only the marshal verbs take --as" || no "codex identity: rc=$rc out=$out err=$err"
bad=
for v in feature local review release; do   # the claim, against the scripts: each of the four reads the identity through the marshal and has no --as of its own
  grep -q 'marshal' "$SRC/lib/$v.sh" || bad="$bad $v:no-marshal"
  grep -qE -- '(^|[^-[:alnum:]])--as([^-[:alnum:]]|$)' "$SRC/lib/$v.sh" && bad="$bad $v:--as"
done
grep -qE -- '--as\) as=' "$SRC/lib/marshal.sh" || bad="$bad marshal:no---as"
[ -z "$bad" ] && ok "and that holds: feature, local, review and release ask the marshal and take no --as; the marshal verbs take it" || no "the identity note and the scripts disagree:$bad"
# the same on claude-code, whose hook records the identity when it runs: without it the note says the same as codex's, and never sends a lead to an --as the verbs outside the marshal do not have
run identity --project onclaude
{ [ $rc = 0 ] && grep -qF 'The SessionStart hook (`qargi hook session-start`) appends `export QARGI_LEAD='"'ID'"'`' <<<"$out" \
  && grep -qF 'Without it start the session with `QARGI_LEAD=ID` set' <<<"$out" && grep -qF '`feature`, `local`, `review` and `release` read it' <<<"$out" \
  && grep -qF 'only marshal verbs take `--as ID`' <<<"$out" && ! grep -qF 'pass `--as ID`' <<<"$out" && ! grep -q 'commands that take it' <<<"$out"; } \
  && ok "claude-code says the hook records the lead identity and that without it the session starts with QARGI_LEAD set, and only the marshal verbs take --as" || no "claude-code identity: rc=$rc out=$out err=$err"
# commands is about the lead's own session (a command the person must run); what a member's commands may do is about the members, so
# it stands in spawn, which a lead on another runtime reads, and not in commands, which such a lead reads from its own runtime
run commands --project oncodex
{ [ $rc = 0 ] && grep -q 'in their own terminal' <<<"$out" && ! grep -qi 'member' <<<"$out"; } && ok "codex's commands note is about the lead's session only" || no "codex commands: rc=$rc out=$out err=$err"
run spawn --project oncodex --lead-runtime claude-code
{ [ $rc = 0 ] && grep -q 'A Codex member runs commands only inside its sandbox\.' <<<"$out"; } && ok "that a codex member runs commands only inside its sandbox is in spawn: a lead on another runtime reads it" || no "codex spawn, the member's commands: rc=$rc out=$out err=$err"
run skills-dir --project oncodex
{ [ $rc = 0 ] && grep -q '\.agents/skills' <<<"$out"; } && ok "codex names its skills directory" || no "codex skills-dir: rc=$rc out=$out err=$err"
run exploration --project oncodex
{ [ $rc = 0 ] && grep -q 'qargi provider model codex local fast' <<<"$out" && grep -q 'git grep' <<<"$out"; } && ok "codex says how a lead explores a repository (the skills point at that topic)" || no "codex exploration: rc=$rc out=$out err=$err"
run spawn --project cloudonly
[ $rc = 2 ] && ok "claude-platform is a cloud runtime: a project with only it has no local notes" || no "cloud only spawn: rc=$rc"

# the cloud surface: the notes of the runtime a project uses there (where a hosted session keeps its outputs and clones)
run output-dir --project onclaude --surface cloud
[ "$rc $out" = "0 /mnt/session/outputs" ] && ok "--surface cloud reads the notes of the cloud runtime (output-dir)" || no "cloud output-dir: rc=$rc out=$out err=$err"
run clone-dir --surface cloud --project onclaude
[ "$rc $out" = "0 /workspace" ] && ok "and clone-dir, the option before or after the project" || no "cloud clone-dir: rc=$rc out=$out err=$err"
run --project onclaude --surface cloud
[ "$out" = "clone-dir
output-dir" ] && ok "listing the cloud topics" || no "cloud list: rc=$rc out=$out"
run output-dir --project onclaude
[ $rc = 1 ] && grep -q "no notes topic 'output-dir'" <<<"$err" && ok "the local runtime has no such topic: the surface is local unless told" || no "local output-dir: rc=$rc out=$out err=$err"
run output-dir --project withnotes --surface cloud
[ $rc = 2 ] && ok "a project with no cloud runtime is exit 2 for --surface cloud" || no "no cloud runtime: rc=$rc out=$out err=$err"
fake_runtime "$SRC" "$TOOL" otherplat cloud '.notes = {"output-dir": "/srv/out", "clone-dir": "/srv/clones"}'
mkproj otherp '{"local":"claude-code","cloud":"otherplat"}'
run output-dir --project otherp --surface cloud
[ "$rc $out" = "0 /srv/out" ] && ok "another cloud runtime names its own directory" || no "other platform: rc=$rc out=$out err=$err"
run output-dir --project onclaude --surface sky
[ $rc = 2 ] && ok "an unknown surface is a usage error" || no "bad surface: rc=$rc out=$out"

# lead_notes: the topics of a definition's notes that are about the lead's own session on that runtime; the others are about its members.
# marks NAME: the lead topics of the runtime NAME of the tool copy as the library reads them (one line, sorted), then every failure the
# validation of its definition reports, one per line
marks() {
  python3 -I -c 'import sys
sys.path.insert(0, sys.argv[1])
import provider as P
d = P.definition(sys.argv[2])
try:
    print("lead: " + " ".join(sorted(P.lead_topics(d))))
except P.ProviderError as e:
    print("unreadable: %s" % e)
for level, m in P.validate2(d, sys.argv[2]):
    if level == "fail":
        print("fail: " + m)' "$TOOL/lib" "$1" 2>&1
}
[ "$(marks claude-code)" = "lead: commands exploration identity session-model skills-dir" ] \
  && ok "the shipped claude-code marks the notes about the lead's session; spawn and member-out are about its members" || no "claude-code marks: $(marks claude-code)"
[ "$(marks codex)" = "lead: commands exploration identity session-model skills-dir" ] \
  && ok "the shipped codex marks the notes about the lead's session; spawn is about its members and message about its sessions, whoever writes to one" || no "codex marks: $(marks codex)"
[ "$(marks claude-platform)" = "lead: " ] && ok "the shipped claude-platform marks none: its two notes are about the hosted members" || no "claude-platform marks: $(marks claude-platform)"
[ "$(marks notey)" = "lead: " ] && ok "a definition with no lead_notes is valid and marks none" || no "notey marks: $(marks notey)"
fake_runtime "$SRC" "$TOOL" marked local '.notes = {"alpha": "a", "beta-2": "b"} | .lead_notes = ["beta-2"]'
[ "$(marks marked)" = "lead: beta-2" ] && ok "lead_notes lists topics of the definition's own notes" || no "marked: $(marks marked)"
fake_runtime "$SRC" "$TOOL" marked local '.notes = {"alpha": "a"} | .lead_notes = []'
[ "$(marks marked)" = "lead: " ] && ok "an empty list is valid" || no "empty marks: $(marks marked)"
fake_runtime "$SRC" "$TOOL" marked local '.notes = {"alpha": "a", "beta-2": "b"} | .lead_notes = ["alpha", "gamma"]'
m=$(marks marked)
{ grep -q "^unreadable: .*lead_notes: 'gamma' is not a topic of notes" <<<"$m" && grep -q "^fail: lead_notes: 'gamma' is not a topic of notes (alpha, beta-2)$" <<<"$m" && [ "$(grep -c '^fail' <<<"$m")" = 1 ]; } \
  && ok "a marked topic the notes do not have fails the validation and is never read as marking the rest" || no "dangling mark: $m"
fake_runtime "$SRC" "$TOOL" marked local 'del(.notes) | .lead_notes = ["alpha"]'
grep -q "^fail: lead_notes: 'alpha' is not a topic of notes (the definition has none)$" <<<"$(marks marked)" && ok "so does a mark in a definition with no notes" || no "mark without notes: $(marks marked)"
fake_runtime "$SRC" "$TOOL" marked local '.notes = {"alpha": "a"} | .lead_notes = "alpha"'
m=$(marks marked)
{ grep -q "^unreadable: " <<<"$m" && grep -q "^fail: lead_notes: 'alpha' is not of type array$" <<<"$m"; } && ok "lead_notes that is not a list fails" || no "mark not a list: $m"
fake_runtime "$SRC" "$TOOL" marked local '.notes = {"alpha": "a"} | .lead_notes = ["alpha", 7]'
m=$(marks marked)
{ grep -q "^unreadable: " <<<"$m" && grep -q "^fail: lead_notes\[1\]: 7 is not of type string$" <<<"$m"; } && ok "an item that is not a string fails" || no "mark not a string: $m"
fake_runtime "$SRC" "$TOOL" marked local '.notes = {"alpha": "a"} | .lead_notes = ["alpha", "alpha"]'
grep -q "^fail: lead_notes: has a duplicate item$" <<<"$(marks marked)" && ok "a topic listed twice fails" || no "mark twice: $(marks marked)"
rm -f "$TOOL/lib/providers/marked.json"; rm -rf "$TOOL/lib/providers/marked"
m=$(python3 -I -c 'import sys
sys.path.insert(0, sys.argv[1])
import provider as P
ext = {"schema": 2, "kind": "extension", "extension": "addon", "extends": "notey", "provides": [], "adds": {"lead_notes": ["alpha"]}}
print("\n".join(m for level, m in P.validate2(ext, "addon") if level == "fail"))' "$TOOL/lib" 2>&1)
[ "$m" = "adds.lead_notes: additional property is not allowed" ] && ok "an extension cannot mark notes (it has none)" || no "extension marks: $m"
# with no lead runtime named the marks change nothing: every topic is the project's runtime's (the lists of the shipped runtimes above)
run identity --project onclaude
{ [ $rc = 0 ] && [ "$out" = "$(jq -r '.notes.identity' "$SRC/lib/providers/claude-code.json")" ] && [ -z "$err" ]; } \
  && ok "a marked topic is still the project's runtime's when no lead runtime is named" || no "marked topic, no lead runtime: rc=$rc out=$out err=$err"

# a lead runtime: --lead-runtime NAME, else QARGI_LEAD_RUNTIME. The notes about the lead's own session come from it and the notes about
# members from the project's runtime, so a lead on one runtime gets its own guidance in a project whose members run on another.
# Two lead runtimes and two member runtimes with the same four topics, the same two of them marked as about the lead; every text names
# its runtime, so an answer shows which definition it came from. Besides: lead-one and member-one have a marked `message`, lead-two an
# unmarked `extra`, member-two a marked `handoff` that lead-one has unmarked. The two member runtimes start a member with a command
# (dispatch.mode command), which any lead can run; a runtime that starts one inside the lead's session comes further down (member-ins).
four='.notes = {"identity": ("identity of " + $n), "session-model": ("session-model of " + $n), "spawn": ("spawn of " + $n), "member-out": ("member-out of " + $n)}
  | .lead_notes = ["identity", "session-model"]'
fake_runtime "$SRC" "$TOOL" lead-one local "$four | .notes.message = \"message of lead-one\" | .lead_notes += [\"message\"] | .notes.handoff = \"handoff of lead-one\""
fake_runtime "$SRC" "$TOOL" lead-two local "$four | .notes.extra = \"extra of lead-two\""
fake_runtime "$SRC" "$TOOL" member-one local "$four | .dispatch.mode = \"command\" | .notes.message = \"message of member-one\" | .lead_notes += [\"message\"]"
fake_runtime "$SRC" "$TOOL" member-two local "$four | .dispatch.mode = \"command\" | .notes.handoff = \"handoff of member-two\" | .lead_notes += [\"handoff\"]"
mkproj on-one '{"local":"member-one"}'
mkproj on-two '"member-two"'
# all PROJECT [OPTION...]: the status, output and error of the four topics and of the list, one line each
all() {
  local p=$1 t; shift
  for t in identity session-model spawn member-out; do run "$t" --project "$p" "$@"; echo "$t: $rc|$out|$err"; done
  run --project "$p" "$@"; echo "list: $rc|$(tr '\n' ' ' <<<"$out")|$err"
}
for L in lead-one lead-two; do
  for M in member-one member-two; do
    topics="identity member-out session-model spawn "
    [ "$L" = lead-one ] && topics="identity member-out message session-model spawn "
    want="identity: 0|identity of $L|
session-model: 0|session-model of $L|
spawn: 0|spawn of $M|
member-out: 0|member-out of $M|
list: 0|$topics|"
    got=$(all "on-${M#member-}" --lead-runtime "$L")
    [ "$got" = "$want" ] && ok "lead $L, members on $M: identity and session-model are $L's, spawn and member-out are $M's, the list is both" || no "lead $L, members $M: $got"
  done
done
got=$(QARGI_LEAD_RUNTIME=lead-two all on-one)
[ "$got" = "identity: 0|identity of lead-two|
session-model: 0|session-model of lead-two|
spawn: 0|spawn of member-one|
member-out: 0|member-out of member-one|
list: 0|identity member-out session-model spawn |" ] && ok "QARGI_LEAD_RUNTIME names the lead runtime when the option is not given" || no "the variable: $got"
out=$(QARGI_LEAD_RUNTIME=lead-one "$DA" provider notes identity --project on-two --lead-runtime lead-two 2>&1); rc=$?
[ "$rc $out" = "0 identity of lead-two" ] && ok "the option wins over the variable" || no "option over variable: rc=$rc $out"
out=$(QARGI_LEAD_RUNTIME=nosuch "$DA" provider notes identity --project on-two --lead-runtime lead-two 2>&1); rc=$?
[ "$rc $out" = "0 identity of lead-two" ] && ok "with the option the variable is not read at all (an unusable name in it changes nothing)" || no "option, bad variable: rc=$rc $out"
run message --project on-two --lead-runtime lead-one
[ "$rc|$out|$err" = "0|message of lead-one|" ] && ok "a note only the lead runtime has, marked, is the lead's (the project's runtime has no such topic)" || no "lead-only topic: rc=$rc out=$out err=$err"
run identity --project on-one --lead-runtime member-one
[ "$rc|$out|$err" = "0|identity of member-one|" ] && ok "the project's own runtime may be named as the lead runtime" || no "lead is the member runtime: rc=$rc out=$out err=$err"

# with no lead runtime the answer is today's, byte for byte: every topic and the list are the project's runtime's, marked or not, and
# the errors are worded as they were; an empty variable is no lead runtime
got=$(all on-one)
[ "$got" = "identity: 0|identity of member-one|
session-model: 0|session-model of member-one|
spawn: 0|spawn of member-one|
member-out: 0|member-out of member-one|
list: 0|identity member-out message session-model spawn |" ] && ok "unset: every note and the whole list are the project's runtime's, marked or not" || no "unset on-one: $got"
[ "$(QARGI_LEAD_RUNTIME='' all on-one)" = "$got" ] && ok "an empty QARGI_LEAD_RUNTIME is the same as none" || no "empty variable: $(QARGI_LEAD_RUNTIME='' all on-one)"
bad=
for pr in onclaude:claude-code oncodex:codex; do
  def=$SRC/lib/providers/${pr#*:}.json
  run --project "${pr%%:*}"
  [ "$rc|$out|$err" = "0|$(jq -r '.notes | keys[]' "$def")|" ] || bad="$bad ${pr#*:}:list"
  for t in $(jq -r '.notes | keys[]' "$def"); do
    run "$t" --project "${pr%%:*}"
    [ "$rc|$out|$err" = "0|$(jq -r --arg t "$t" '.notes[$t]' "$def")|" ] || bad="$bad ${pr#*:}:$t"
  done
done
[ -z "$bad" ] && ok "unset: each topic of the shipped claude-code and codex prints the text of its definition and nothing else, and the list is all of them" || no "unset, shipped:$bad"
run gamma --project withnotes
[ "$rc|$out|$err" = "1||qargi: the runtime notey has no notes topic 'gamma'; its topics: alpha, beta-2" ] && ok "unset: an unknown topic is worded as it was" || no "unset unknown topic: rc=$rc out=$out err=$err"
run alpha --project nonotes
[ "$rc|$out|$err" = "1||qargi: the runtime plain has no notes topic 'alpha' (it has no notes)" ] && ok "unset: a runtime with no notes is worded as it was" || no "unset no notes: rc=$rc out=$out err=$err"
run --project nonotes
[ "$rc|$out|$err" = "1||qargi: the runtime plain has no notes" ] && ok "unset: so is the list of a runtime with none" || no "unset list none: rc=$rc out=$out err=$err"
run alpha --project cloudonly
[ "$rc|$out|$err" = "2||qargi: project cloudonly has no local provider: set one with qargi project set cloudonly models.provider.local NAME" ] \
  && ok "unset: a project with no local runtime is refused as it was" || no "unset no local runtime: rc=$rc out=$out err=$err"

# refusals: a lead runtime that is not a usable local runtime is unsupported (exit 3), whatever is asked; nothing is printed and the
# project's runtime never answers in its place
refused() { # WHAT NEEDLE: the last run was exit 3 with nothing on stdout, said unsupported and NEEDLE, and printed no note of any runtime
  { [ $rc = 3 ] && [ -z "$out" ] && grep -q "^qargi: unsupported" <<<"$err" && grep -qF -- "$2" <<<"$err" && ! grep -q " of member-\| of lead-" <<<"$err"; } \
    && ok "$1" || no "$1: rc=$rc out=$out err=$err"
}
run identity --project on-one --lead-runtime nosuch
refused "an unknown lead runtime is unsupported (exit 3): a note about the lead is not taken from the project's runtime" "unsupported lead runtime 'nosuch': no runtime has that name"
grep -q "the local runtimes: .*lead-one, lead-two, .*member-one, member-two" <<<"$err" && ok "the refusal lists the local runtimes there are" || no "the runtimes listed: $err"
run spawn --project on-one --lead-runtime nosuch
refused "and so is a note about members: the name is refused, not ignored" "unsupported lead runtime 'nosuch'"
run --project on-one --lead-runtime nosuch
refused "and the list of topics" "unsupported lead runtime 'nosuch'"
grep -q "; the lead runtime is named by --lead-runtime$" <<<"$err" && ok "the refusal ends with what named the lead runtime: the option" || no "named by the option: $err"
out=$(QARGI_LEAD_RUNTIME=nosuch "$DA" provider notes identity --project on-one 2>"$T/err"); rc=$?; err=$(cat "$T/err")
refused "an unknown runtime in QARGI_LEAD_RUNTIME is refused the same way" "unsupported lead runtime 'nosuch'"
grep -q "; the lead runtime is named by QARGI_LEAD_RUNTIME$" <<<"$err" && ok "and then it ends with the variable, which is not on the command line that was refused" || no "named by the variable: $err"
out=$(QARGI_LEAD_RUNTIME=lead-one "$DA" provider notes identity --project on-one --lead-runtime nosuch 2>"$T/err"); rc=$?; err=$(cat "$T/err")
refused "an unknown runtime in the option is not replaced by the one in the variable" "unsupported lead runtime 'nosuch'"
grep -q "; the lead runtime is named by --lead-runtime$" <<<"$err" && ok "with both, the refusal names the option: the variable was not read" || no "named by the option, both set: $err"
run identity --project onclaude --lead-runtime claude
refused "a family name does not name a lead runtime" "unsupported lead runtime 'claude': no runtime has that name (a family name does not name a lead runtime)"
run identity --project onclaude --lead-runtime claude-platform
refused "a runtime of the cloud surface is not a lead runtime" "unsupported lead runtime 'claude-platform': it serves the cloud surface only"
run identity --project on-one --lead-runtime 'No Such'
refused "a name that cannot be a runtime's is unsupported" "unsupported lead runtime 'No Such': it is not a runtime name"
out=$(QARGI_LEAD_RUNTIME=lead-one "$DA" provider notes identity --project on-one --lead-runtime '' 2>"$T/err"); rc=$?; err=$(cat "$T/err")
refused "an empty name in the option is unsupported too, not a way back to the variable" "unsupported lead runtime '': it is not a runtime name"
run identity --project on-one --lead-runtime unsealed
refused "a library runtime that was never sealed is not a lead runtime" "unsupported lead runtime 'unsealed': it cannot be used as it stands"
run identity --project on-one --lead-runtime garbled
refused "nor is a definition that is not readable" "unsupported lead runtime 'garbled': it cannot be used as it stands"
fake_runtime "$SRC" "$TOOL" lead-bad local "$four | .lead_notes = [\"identity\", \"gone\"]"
run identity --project on-one --lead-runtime lead-bad
refused "nor one whose lead_notes cannot be read (its marks are never guessed)" "unsupported lead runtime 'lead-bad': it cannot be used as it stands"
rm -f "$TOOL/lib/providers/lead-bad.json"; rm -rf "$TOOL/lib/providers/lead-bad"

# a note about the lead's session that the lead runtime does not have is unsupported (exit 3); the project's runtime's is for a lead on
# that runtime and is never printed
run message --project on-one --lead-runtime lead-two
refused "a note about the lead that the lead runtime lacks is unsupported: the project's runtime's is not printed" "the lead runtime lead-two has no note 'message' about the lead's session (its topics: identity, session-model)"
grep -qF "the 'message' note of the project's runtime member-one is about a lead session on member-one and is not used in its place" <<<"$err" \
  && ok "the refusal says whose note it did not use, and why" || no "missing lead note wording: $err"
out=$(QARGI_LEAD_RUNTIME=lead-two "$DA" provider notes message --project on-one 2>"$T/err"); rc=$?; err=$(cat "$T/err")
refused "the same refusal when the variable names the lead runtime" "the lead runtime lead-two has no note 'message' about the lead's session"
grep -q "is not used in its place; the lead runtime is named by QARGI_LEAD_RUNTIME$" <<<"$err" && ok "and it ends with the variable that named it" || no "missing lead note, named by the variable: $err"
run handoff --project on-two --lead-runtime lead-one
refused "a topic the lead runtime has only as a note about its members does not answer for a note about the lead either" "the lead runtime lead-one has no note 'handoff' about the lead's session"
run message --project on-two --lead-runtime lead-two
{ [ $rc = 1 ] && [ -z "$out" ] && [ "$err" = "qargi: the runtime member-two has no notes topic 'message' about its members (its topics: member-out, spawn) and the lead runtime lead-two has none about the lead's session (its topics: identity, session-model)" ]; } \
  && ok "a topic neither runtime has is exit 1, naming both and what each has" || no "unknown topic with a lead runtime: rc=$rc out=$out err=$err"
run extra --project on-one --lead-runtime lead-two
{ [ $rc = 1 ] && [ -z "$out" ] && ! grep -q "extra of lead-two" <<<"$err"; } && ok "a note about the lead runtime's own members is not the project's: exit 1, not printed" || no "lead runtime's member note: rc=$rc out=$out err=$err"

# a runtime that works in the session (dispatch.mode in-session) starts a member with a tool of the lead's own session, so only a lead on
# that runtime can start one. For a lead on another runtime its spawn and member-out are unsupported (exit 3) and never printed: the text
# would send that lead to a tool it does not have. The runtime's other notes about its members still answer, and the list leaves the two
# out. member-ins has the four topics and an unmarked `message`, and works in the session as the shipped runtime it is built from does.
fake_runtime "$SRC" "$TOOL" member-ins local "$four | .notes.message = \"message of member-ins\""
mkproj on-ins '"member-ins"'
[ "$(jq -r .dispatch.mode "$TOOL/lib/providers/member-ins.json") $(jq -r .dispatch.mode "$TOOL/lib/providers/member-one.json")" = "in-session command" ] \
  && ok "the fixtures: member-ins works in the session, member-one is started by a command" || no "the dispatch modes of member-ins and member-one are not in-session and command"
for t in spawn member-out; do
  run "$t" --project on-ins --lead-runtime lead-two
  refused "a lead on another runtime than a project's in-session runtime: $t is unsupported, and its text is not printed" "members of this project cannot be started from this lead"
done
[ "$err" = "qargi: unsupported: members of this project cannot be started from this lead: the project's runtime member-ins starts a member inside a lead session on member-ins (dispatch.mode in-session) and the lead runtime is lead-two; its 'member-out' note is for a lead on member-ins and is not printed; the lead runtime is named by --lead-runtime" ] \
  && ok "the refusal names the two runtimes, the mode, the note and what named the lead runtime" || no "the in-session refusal is worded: $err"
out=$(QARGI_LEAD_RUNTIME=lead-two "$DA" provider notes spawn --project on-ins 2>"$T/err"); rc=$?; err=$(cat "$T/err")
refused "the same refusal when the variable names the lead runtime" "members of this project cannot be started from this lead"
grep -q "is not printed; the lead runtime is named by QARGI_LEAD_RUNTIME$" <<<"$err" && ok "and it ends with the variable that named it" || no "in-session refusal, named by the variable: $err"
run --project on-ins --lead-runtime lead-two
[ "$rc|$(tr '\n' ' ' <<<"$out")|$err" = "0|identity message session-model |" ] && ok "the list leaves spawn and member-out out: it names what this lead can read" || no "in-session list: rc=$rc out=$out err=$err"
run message --project on-ins --lead-runtime lead-two
[ "$rc|$out|$err" = "0|message of member-ins|" ] && ok "a note of that runtime that is not about starting a member is still answered" || no "in-session, another member note: rc=$rc out=$out err=$err"
run identity --project on-ins --lead-runtime lead-two
[ "$rc|$out|$err" = "0|identity of lead-two|" ] && ok "and the lead's own notes are the lead runtime's" || no "in-session, lead note: rc=$rc out=$out err=$err"
run gamma --project on-ins --lead-runtime lead-two
[ "$rc|$out|$err" = "1||qargi: the runtime member-ins has no notes topic 'gamma' about its members (its topics: message) and the lead runtime lead-two has none about the lead's session (its topics: identity, session-model)" ] \
  && ok "an unknown topic is exit 1 and lists the topics this lead can read" || no "in-session, unknown topic: rc=$rc out=$out err=$err"
bad=
for t in spawn member-out; do
  run "$t" --project on-ins --lead-runtime member-ins; [ "$rc|$out|$err" = "0|$t of member-ins|" ] || bad="$bad lead-is-member-ins:$t"
  run "$t" --project on-ins; [ "$rc|$out|$err" = "0|$t of member-ins|" ] || bad="$bad no-lead-runtime:$t"
done
run --project on-ins --lead-runtime member-ins
[ "$(tr '\n' ' ' <<<"$out")" = "identity member-out message session-model spawn " ] || bad="$bad list"
[ -z "$bad" ] && ok "a lead on the in-session runtime itself, and a lead that names no runtime, read spawn and member-out as before" || no "in-session, the same runtime or none:$bad"
# a runtime whose only note is how to start a member, and a lead runtime with no note about the lead: there is nothing to list
fake_runtime "$SRC" "$TOOL" member-bare local '.notes = {"spawn": "spawn of member-bare"} | del(.lead_notes)'
mkproj on-bare '"member-bare"'
run --project on-bare --lead-runtime notey
[ "$rc|$out|$err" = "1||qargi: the lead runtime notey has no notes about the lead's session and the runtime member-bare has none about its members that a lead on another runtime can use (it starts a member inside a lead session on member-bare)" ] \
  && ok "a list with nothing this lead can read is exit 1 and says why" || no "in-session, empty list: rc=$rc out=$out err=$err"
rm -f "$TOOL/lib/providers/member-ins.json" "$TOOL/lib/providers/member-bare.json"; rm -rf "$TOOL/lib/providers/member-ins" "$TOOL/lib/providers/member-bare"

# the lead's own guidance does not depend on the project's runtime: it needs a project, not a runtime that can be read
run identity --project cloudonly --lead-runtime lead-one
[ "$rc|$out|$err" = "0|identity of lead-one|" ] && ok "a project with no local runtime still gets the lead's notes from the lead runtime" || no "lead note, no member runtime: rc=$rc out=$out err=$err"
run spawn --project cloudonly --lead-runtime lead-one
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "no local provider" <<<"$err"; } && ok "and a note about members is refused as without a lead runtime (exit 2)" || no "member note, no member runtime: rc=$rc out=$out err=$err"
run --project cloudonly --lead-runtime lead-one
[ $rc = 2 ] && ok "so is the list, which needs both" || no "list, no member runtime: rc=$rc out=$out err=$err"
run identity --project garbledp --lead-runtime lead-one
[ "$rc|$out" = "0|identity of lead-one" ] && ok "a project whose runtime cannot be read still gets the lead's notes" || no "lead note, garbled member runtime: rc=$rc out=$out err=$err"
run spawn --project garbledp --lead-runtime lead-one
{ [ $rc = 2 ] && [ -z "$out" ]; } && ok "and its notes about members are refused as they were (exit 2)" || no "member note, garbled member runtime: rc=$rc out=$out err=$err"
run identity --lead-runtime lead-one
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "no project" <<<"$err"; } && ok "with no project in effect it is exit 2, lead runtime or not" || no "lead runtime, no project: rc=$rc out=$out err=$err"
run identity --project nosuch --lead-runtime lead-one
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "no such project 'nosuch'" <<<"$err"; } && ok "an unknown project is exit 2, lead runtime or not" || no "lead runtime, unknown project: rc=$rc out=$out err=$err"

# the lead runtime is a local one whatever surface the members are asked about
run output-dir --project onclaude --surface cloud --lead-runtime lead-one
[ "$rc|$out|$err" = "0|/mnt/session/outputs|" ] && ok "--surface cloud with a lead runtime: a note about the hosted members is the cloud runtime's" || no "cloud member note with a lead runtime: rc=$rc out=$out err=$err"
run identity --project onclaude --surface cloud --lead-runtime lead-one
[ "$rc|$out|$err" = "0|identity of lead-one|" ] && ok "and a note about the lead is the lead runtime's" || no "cloud, lead note: rc=$rc out=$out err=$err"

# qargi's own questions about a hosted directory (cloud_note of lib/lib.sh, which the team brief and collect ask) do not depend on the
# lead's variable: the question is put with it cleared, so a name in it neither refuses the question nor answers it from the lead's
# runtime, and the caller's own variable is what it was. lead-out lists output-dir as a note about the lead, so it would answer.
fake_runtime "$SRC" "$TOOL" lead-out local "$four | .notes[\"output-dir\"] = \"output-dir of lead-out\" | .lead_notes += [\"output-dir\"]"
out=$(QARGI_LEAD_RUNTIME=lead-out "$DA" provider notes output-dir --project onclaude --surface cloud 2>&1); rc=$?
[ "$rc $out" = "0 output-dir of lead-out" ] && ok "the verb itself reads the variable for a cloud topic too: a lead runtime that lists output-dir answers it" || no "the variable, cloud topic: rc=$rc $out"
# note LEAD-RUNTIME PROJECT TOPIC: the status and output of cloud_note with the variable set, then the variable as the caller has it afterwards
note() { QARGI_LEAD_RUNTIME=$1 bash -c '. "$1/lib/lib.sh"; out=$(cloud_note "$2" "$3" 2>&1); echo "$? $out|$QARGI_LEAD_RUNTIME"' _ "$TOOL" "$2" "$3"; }
got=$(note lead-out onclaude output-dir)
[ "$got" = "0 /mnt/session/outputs|lead-out" ] && ok "cloud_note is answered by the cloud runtime when the variable names a lead runtime that lists the topic, and the caller keeps its variable" || no "cloud_note, a lead runtime with the topic: $got"
got=$(note nosuch onclaude clone-dir)
[ "$got" = "0 /workspace|nosuch" ] && ok "and when the variable names no runtime: the question is not refused" || no "cloud_note, an unusable lead runtime: $got"
got=$(note nosuch withnotes output-dir)
[[ $got == "2 "*"|nosuch" ]] && ok "its own refusal keeps its status: a project with no cloud runtime is exit 2" || no "cloud_note, no cloud runtime: $got"
rm -f "$TOOL/lib/providers/lead-out.json"; rm -rf "$TOOL/lib/providers/lead-out"

# the shipped runtimes, crossed: a lead on one with members on the other
jqn() { jq -r --arg t "$2" '.notes[$t]' "$SRC/lib/providers/$1.json"; }
bad=
for t in commands exploration identity session-model skills-dir; do
  run "$t" --project onclaude --lead-runtime codex; [ "$rc|$out|$err" = "0|$(jqn codex "$t")|" ] || bad="$bad $t"
done
run --project onclaude --lead-runtime codex
[ "$rc|$(tr '\n' ' ' <<<"$out")|$err" = "0|commands exploration identity session-model skills-dir |" ] || bad="$bad list"
[ -z "$bad" ] && ok "a codex lead of a project on claude-code: its own notes are codex's, and the list is those" || no "codex lead, claude-code members:$bad"
# codex's message note says how a message reaches a session on codex: it is about the sessions of that runtime, not about its lead, so
# it is no answer in a project whose sessions run on claude-code, which has no such note
run message --project onclaude --lead-runtime codex
{ [ $rc = 1 ] && [ -z "$out" ] && grep -q "has no notes topic 'message'" <<<"$err" && ! grep -q 'codex queue' <<<"$err"; } \
  && ok "codex's message is not a note about the lead: in a project on claude-code, which has none, the topic is unknown (exit 1) and not printed" || no "message, codex lead of claude-code: rc=$rc out=$out err=$err"
# claude-code starts a member inside a claude-code session, which a codex lead is not in: its spawn and member-out would name a tool
# that lead does not have, so they are unsupported and the lead is told it cannot start the project's members
for t in spawn member-out; do
  run "$t" --project onclaude --lead-runtime codex
  refused "a codex lead of a project on claude-code: $t is unsupported, claude-code's text is not printed" \
    "members of this project cannot be started from this lead: the project's runtime claude-code starts a member inside a lead session on claude-code (dispatch.mode in-session) and the lead runtime is codex"
  grep -q 'subagent_type\|final message' <<<"$out$err" && no "the refusal of $t carries the text of claude-code's note: $err"
done
bad=
for t in spawn member-out; do
  run "$t" --project onclaude --lead-runtime claude-code; [ "$rc|$out|$err" = "0|$(jqn claude-code "$t")|" ] || bad="$bad $t"
done
[ -z "$bad" ] && ok "a claude-code lead of that project reads spawn and member-out from claude-code" || no "claude-code lead, claude-code members:$bad"
bad=
for t in commands exploration identity session-model skills-dir; do
  run "$t" --project oncodex --lead-runtime claude-code; [ "$rc|$out|$err" = "0|$(jqn claude-code "$t")|" ] || bad="$bad $t"
done
for t in spawn message; do
  run "$t" --project oncodex --lead-runtime claude-code; [ "$rc|$out|$err" = "0|$(jqn codex "$t")|" ] || bad="$bad $t"
done
run --project oncodex --lead-runtime claude-code
[ "$(tr '\n' ' ' <<<"$out")" = "commands exploration identity message session-model skills-dir spawn " ] || bad="$bad list"
[ -z "$bad" ] && ok "a claude-code lead of a project on codex: its own notes are claude-code's; spawn (qargi local run) and message (how to write to a session there) are codex's" || no "claude-code lead, codex members:$bad"
run member-out --project oncodex --lead-runtime claude-code
{ [ $rc = 1 ] && [ -z "$out" ]; } && ok "claude-code's note about its own members is not codex's members': exit 1" || no "member-out, codex members: rc=$rc out=$out err=$err"

# the name selects which definition is read and nothing else: no other code of qargi reads it (the schema and the texts only describe it),
# so no approval, identity or authority can depend on it. lib/lib.sh names the variable once, to unset it for cloud_note's question.
readers=$(grep -rlE --exclude='*.pyc' --exclude='*.json' --exclude='*.md' 'QARGI_LEAD_RUNTIME|LEAD_RUNTIME_ENV|lead-runtime|lead_notes_of' lib bin install.sh | LC_ALL=C sort | tr '\n' ' ')
[ "$readers" = "lib/commands.py lib/lib.sh lib/provider.py " ] && ok "only the notes verb (lib/provider.py), its help (lib/commands.py) and cloud_note (lib/lib.sh) know the lead runtime" || no "the lead runtime is known to: $readers"
uses=$(grep -nE 'QARGI_LEAD_RUNTIME|LEAD_RUNTIME_ENV|lead-runtime|lead_notes_of' lib/lib.sh | grep -vE '^[0-9]+:[[:space:]]*#')
{ [ "$(grep -c . <<<"$uses")" = 1 ] && grep -qE '^[0-9]+:  \( unset QARGI_LEAD_RUNTIME; pymod provider notes ' <<<"$uses"; } \
  && ok "and lib/lib.sh only unsets it, in the one line that asks cloud_note's question: nothing there reads it" || no "lib/lib.sh uses the lead runtime: $uses"

# usage
run a b --project withnotes
[ $rc = 2 ] && ok "two topics are a usage error" || no "two topics: rc=$rc"
run alpha --project
[ $rc = 2 ] && ok "--project with no name is a usage error" || no "--project alone: rc=$rc"
run identity --project on-one --lead-runtime
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "^usage: qargi provider notes \[TOPIC\] \[--project P\] \[--surface local|cloud\] \[--lead-runtime NAME\] \[--runtime NAME | --run RUN\]$" <<<"$err"; } \
  && ok "--lead-runtime with no name is a usage error, and the usage names the option" || no "--lead-runtime alone: rc=$rc out=$out err=$err"
run identity --project on-one --lead-runtime lead-one --lead-runtime lead-two
{ [ $rc = 2 ] && [ -z "$out" ]; } && ok "--lead-runtime twice is a usage error" || no "--lead-runtime twice: rc=$rc out=$out err=$err"

# read-only: the definitions and the answers are what they were
before=$(cd "$T" && find tool/lib/providers c -type f -exec sha256sum {} + | sort | sha256sum)
run alpha --project withnotes; run --project withnotes; run gamma --project withnotes
after=$(cd "$T" && find tool/lib/providers c -type f -exec sha256sum {} + | sort | sha256sum)
[ "$before" = "$after" ] && ok "the verb changes nothing" || no "the verb changed a file"
# nor with a lead runtime: the answers, the definitions, the state and the home are what they were, whether it answers or refuses
tree() { (cd "$T" && find tool/lib/providers c s home -exec stat -c '%n %F %s %Y' {} + | LC_ALL=C sort | sha256sum; find tool/lib/providers c s home -type f -exec sha256sum {} + | LC_ALL=C sort | sha256sum); }
before=$(tree)
run identity --project on-one --lead-runtime lead-two; run spawn --project on-one --lead-runtime lead-two; run --project on-two --lead-runtime lead-one
run message --project on-one --lead-runtime lead-two; run identity --project on-one --lead-runtime nosuch
out=$(QARGI_LEAD_RUNTIME=lead-one "$DA" provider notes identity --project on-two 2>&1)
[ "$before" = "$(tree)" ] && ok "naming a lead runtime stores and rewrites nothing (answers, definitions, state, home), answered or refused" || no "a lead runtime changed a file"


# a project without extra runtimes: every topic answers as it did before runtime-per-profile (the fixtures of tests/fixtures/runtime-no-extras,
# recorded from the head before it, are the two projects of the design; NOTES_RECORD=1 writes them again when a shipped note changes)
FIX=$SRC/tests/fixtures/runtime-no-extras
notes_dump() { # NAME: for the stored project NAME, each topic its runtime and the two lead runtimes answer, as the verb printed it
  local p=$1 v t vs topics
  vs=("" "--lead-runtime claude-code" "--lead-runtime codex" "env")
  topics=$(for v in "${vs[@]}"; do
    case $v in env) QARGI_LEAD_RUNTIME=codex "$DA" provider notes --project "$p" 2>/dev/null;; *) "$DA" provider notes --project "$p" $v 2>/dev/null;; esac
  done | sort -u)
  for v in "${vs[@]}"; do
    for t in "" $topics nosuch; do
      printf '>>> notes %s --project %s %s\n' "$t" "$p" "$v"
      case $v in
        env) QARGI_LEAD_RUNTIME=codex "$DA" provider notes $t --project "$p" 2>&1; printf 'exit %s\n' "$?";;
        *) "$DA" provider notes $t --project "$p" $v 2>&1; printf 'exit %s\n' "$?";;
      esac
    done
  done
}
for f in project project-command; do
  jq '.project = "demo"' "$FIX/$f.json" > "$T/c/projects/demo.json"
  if [ -n "${NOTES_RECORD:-}" ]; then notes_dump demo > "$FIX/notes-$f.golden"; ok "recorded notes-$f.golden"; continue; fi
  notes_dump demo > "$T/notes-$f.out"
  cmp -s "$T/notes-$f.out" "$FIX/notes-$f.golden" && ok "no extras: provider notes of $f.json answers every topic as recorded" || no "no extras: notes of $f.json changed: $(diff "$FIX/notes-$f.golden" "$T/notes-$f.out" | head -5)"
done
rm -f "$T/c/projects/demo.json"

# a project with extra runtimes: --runtime NAME and --run RUN name the runtime whose notes about its members are asked for. The runtime must be
# enabled (its own, or one of models.extra_runtimes.local); the topics about the lead's own session stay with the lead runtime, or with the
# project's own runtime when none is named. cx1 and cx2 are command runtimes (the shipped codex under other names) whose every note names its runtime.
for r in cx1 cx2; do
  fake_command_runtime "$SRC" "$TOOL" $r ".notes |= with_entries(.value = (.key + \" of $r\"))"
  mkdir -p "$HOME/.$r-members"; echo '{}' > "$HOME/.$r-members/auth.json"
done
mkx() { # NAME PROVIDER-JSON EXTRAS-JSON: a stored project whose models.extra_runtimes.local is EXTRAS
  mkproj "$1" "$2"
  jq --argjson ex "$3" '.models.extra_runtimes = {local: $ex}' "$T/c/projects/$1.json" > "$T/x" && mv "$T/x" "$T/c/projects/$1.json"
}
CCP='{"local":"claude-code","cloud":"claude-platform"}'
mkx withx "$CCP" '["cx1"]'
mkx withxx "$CCP" '["cx1","cx2"]'
mkx cmdx '{"local":"cx1"}' '["cx2"]'
mkproj plainx "$CCP"
mkx cloudx '{"cloud":"claude-platform"}' '["cx1"]'
CCT="commands exploration identity session-model skills-dir"             # the notes of claude-code about the lead's own session
CXM="message spawn"                                                         # and of the shipped codex (and so of cx1) about its members

# no option, or the project's own runtime named: the answer is the one a project without extras gives
same=1
for a in "" "spawn" "identity" "nosuch"; do
  run $a --project plainx; want="$rc|$out|$err"
  for opt in "--project withx" "--project withx --runtime claude-code" "--project withxx --runtime claude-code"; do
    run $a $opt; [ "$rc|$out|$err" = "$want" ] || { same=0; no "project with extras, '$a' $opt: rc=$rc out=$out err=$err"; }
  done
done
[ $same = 1 ] && ok "notes-own-runtime: with no option, or the project's own runtime named, a project with extras answers as one without" || no "notes-own-runtime"

# --runtime NAME: the notes about its members from that runtime, those about the lead's own session from the project's own runtime
run --project withx --runtime cx1
{ [ $rc = 0 ] && [ "$out" = "$(tr ' ' '\n' <<<"$CCT $CXM" | sort)" ] && [ -z "$err" ]; } && ok "notes-runtime-list: the topics are the lead's (claude-code) and the members' (cx1)" || no "runtime list: rc=$rc out=$out err=$err"
run spawn --project withx --runtime cx1
{ [ $rc = 0 ] && [ "$out" = "spawn of cx1" ] && [ -z "$err" ]; } && ok "notes-runtime-spawn: a member of cx1 is started as cx1's note says (not the session's tool)" || no "runtime spawn: rc=$rc out=$out err=$err"
run message --project withx --runtime cx1
{ [ $rc = 0 ] && [ "$out" = "message of cx1" ]; } && ok "a note about the members' sessions is cx1's" || no "runtime message: rc=$rc out=$out err=$err"
run identity --project withx --runtime cx1
want=$("$DA" provider notes identity --project plainx 2>&1)
{ [ $rc = 0 ] && [ "$out" = "$want" ] && ! grep -q 'of cx1' <<<"$out"; } && ok "notes-runtime-lead-topics: identity is the lead's, from the project's own runtime, not cx1's" || no "runtime identity: rc=$rc out=$out err=$err"
run spawn --project withxx --runtime cx2
{ [ $rc = 0 ] && [ "$out" = "spawn of cx2" ]; } && ok "each enabled extra answers for itself" || no "cx2 spawn: rc=$rc out=$out err=$err"
run spawn --project withxx --runtime claude-code
want=$("$DA" provider notes spawn --project plainx 2>&1)
{ [ $rc = 0 ] && [ "$out" = "$want" ] && grep -q 'subagent_type' <<<"$out"; } && ok "the project's own runtime keeps the session's tool" || no "own spawn: rc=$rc out=$out err=$err"
run gamma --project withx --runtime cx1
{ [ $rc = 1 ] && [ -z "$out" ] && grep -q "the runtime cx1 has no notes topic 'gamma' about its members (its topics: message, spawn) and the lead runtime claude-code has none about the lead's session" <<<"$err"; } \
  && ok "an unknown topic is exit 1 naming both runtimes" || no "runtime unknown topic: rc=$rc out=$out err=$err"
run spawn --runtime cx1 --project cmdx
{ [ $rc = 0 ] && [ "$out" = "spawn of cx1" ]; } && ok "the project's own runtime named" || no "cmdx own: rc=$rc out=$out err=$err"
run spawn --runtime cx2 --project cmdx
{ [ $rc = 0 ] && [ "$out" = "spawn of cx2" ]; } && ok "a project on a command runtime asks an extra the same way" || no "cmdx extra: rc=$rc out=$out err=$err"
run identity --runtime cx2 --project cmdx
want=$("$DA" provider notes identity --project cmdx 2>&1)
{ [ $rc = 0 ] && [ "$out" = "$want" ] && [ "$out" = "identity of cx1" ]; } && ok "and the lead's topics are the project's own runtime's" || no "cmdx identity: rc=$rc out=$out err=$err"
run --project withx --runtime cx1 --lead-runtime nosuch
{ [ $rc = 3 ] && [ -z "$out" ] && grep -q "unsupported lead runtime 'nosuch'" <<<"$err"; } && ok "a lead runtime that is no runtime is exit 3 whatever runtime is asked" || no "nosuch lead: rc=$rc out=$out err=$err"
run identity --project withx --runtime cx1 --lead-runtime cx2
{ [ $rc = 0 ] && [ "$out" = "identity of cx2" ]; } && ok "with a lead runtime named, the lead's topics are its" || no "lead cx2: rc=$rc out=$out err=$err"
run spawn --project withx --runtime cx1 --lead-runtime cx2
{ [ $rc = 0 ] && [ "$out" = "spawn of cx1" ]; } && ok "and the members' are the asked runtime's, not the lead's" || no "lead cx2 spawn: rc=$rc out=$out err=$err"
out=$(QARGI_LEAD_RUNTIME=cx2 "$DA" provider notes identity --project withx --runtime cx1 2>&1)
[ "$out" = "identity of cx2" ] && ok "QARGI_LEAD_RUNTIME names the lead runtime as it does without --runtime" || no "env lead: $out"
out=$(QARGI_LEAD_RUNTIME=cx2 "$DA" provider notes identity --project withx --runtime cx1 --lead-runtime cx1 2>&1)
[ "$out" = "identity of cx1" ] && ok "and the option wins" || no "env and option: $out"
# the rule of 0.3.4 holds for the runtime named: one that starts a member inside the lead's session is answered only to a lead on it
run spawn --project withx --runtime claude-code --lead-runtime cx1
{ [ $rc = 3 ] && [ -z "$out" ] && grep -q "members of this project cannot be started from this lead" <<<"$err"; } \
  && ok "notes-in-session-rule: the in-session own runtime named is refused to a lead on another runtime, as without --runtime" || no "in-session rule: rc=$rc out=$out err=$err"

# a runtime the project has not enabled, or that is no runtime: exit 2, nothing answered
for bad in cx2 codex nosuch 'Not A Name' schema-2; do
  run spawn --project withx --runtime "$bad"
  { [ $rc = 2 ] && [ -z "$out" ] && grep -q "enabled\|not a runtime name" <<<"$err"; } && ok "notes-not-enabled: --runtime '$bad' is refused" || no "runtime '$bad': rc=$rc out=$out err=$err"
done
run spawn --project withx --runtime cx2
{ [ $rc = 2 ] && grep -q "the runtime cx2 is not enabled for project withx: its runtimes are claude-code, cx1 (qargi provider enable withx --runtime cx2)" <<<"$err"; } \
  && ok "the refusal lists the runtimes the project has and the way to enable one" || no "enabled list: $err"
run spawn --project plainx --runtime cx1
{ [ $rc = 2 ] && grep -q "its runtimes are claude-code (" <<<"$err"; } && ok "a project without extras refuses every other runtime" || no "plainx cx1: rc=$rc err=$err"
run spawn --project cloudx --runtime cx1
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "no local provider" <<<"$err"; } && ok "a project with no local runtime has none to ask" || no "cloudx: rc=$rc out=$out err=$err"
run spawn --project nosuch --runtime cx1
{ [ $rc = 2 ] && grep -q "no such project 'nosuch'" <<<"$err"; } && ok "an unknown project is exit 2" || no "no project: rc=$rc err=$err"
run spawn --runtime cx1
{ [ $rc = 2 ] && grep -q "no project" <<<"$err"; } && ok "with no project in effect it is exit 2 and says so" || no "no project in effect: rc=$rc err=$err"
out=$(cd "$T/repo-withx" && "$DA" provider notes spawn --runtime cx1 2>&1)
[ "$out" = "spawn of cx1" ] && ok "inside the project's repository the project is the one in effect" || no "in effect: $out"
run spawn --project withx --runtime cx1 --surface cloud
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "local surface" <<<"$err"; } && ok "the cloud surface has no extra runtimes: --runtime with it is refused" || no "cloud surface: rc=$rc out=$out err=$err"
run spawn --project withx --runtime cx1 --surface local
[ "$out" = "spawn of cx1" ] && ok "the local surface may be named" || no "local surface: rc=$rc out=$out err=$err"

# the usage: the two options exclude each other, each once, each with a value
USAGE="usage: qargi provider notes \[TOPIC\] \[--project P\] \[--surface local|cloud\] \[--lead-runtime NAME\] \[--runtime NAME | --run RUN\]"
for args in "--runtime cx1 --run /x" "--runtime cx1 --runtime cx1" "--run /x --run /x" "--runtime" "--run" "spawn another --runtime cx1"; do
  run --project withx $args
  { [ $rc = 2 ] && [ -z "$out" ] && grep -q "^$USAGE\$" <<<"$err"; } && ok "notes-usage: '$args' is a usage error" || no "usage '$args': rc=$rc out=$out err=$err"
done

# --run RUN: the runtime of the registry's line for the run directory (the project's own when the line has none)
REG=$T/s/local-runs.jsonl
line() { jq -nc --arg r "$T/runs/$1" --arg p "$2" --arg rt "${3-}" '{lifecycle:1,run:$r,slug:"a",ability:"build",base:"main",started:"2026-11-20T10:00:00Z"}
  + (if $p == "" then {} else {project:$p} end) + (if $rt == "" then {} else {runtime:$rt} end)' >> "$REG"; }
line qargi.aaaaaa withx cx1
line qargi.bbbbbb withx
line qargi.cccccc withx cx2
line qargi.dddddd withxx cx2
line qargi.eeeeee '' cx1
line qargi.ffffff withx claude-code
jq -nc --arg r "$T/runs/qargi.gggggg" '{run:$r,project:"withx",runtime:7}' >> "$REG"
jq -nc --arg r "$T/runs/qargi.hhhhhh" '{run:$r,project:"withx",runtime:"Not A Name"}' >> "$REG"
printf '{ not json\n' >> "$REG"
line qargi.iiiiii withxx cx1
line qargi.iiiiii withxx cx2
run spawn --run "$T/runs/qargi.aaaaaa"
{ [ $rc = 0 ] && [ "$out" = "spawn of cx1" ] && [ -z "$err" ]; } && ok "notes-run: a run on cx1 is started as cx1's note says, the project is the line's" || no "run aaaaaa: rc=$rc out=$out err=$err"
run spawn --run "$T/runs/qargi.aaaaaa" --project withx
[ "$out" = "spawn of cx1" ] && ok "a project that agrees with the line's is accepted" || no "run with project: rc=$rc out=$out err=$err"
run --run "$T/runs/qargi.aaaaaa"
{ [ $rc = 0 ] && [ "$out" = "$(tr ' ' '\n' <<<"$CCT $CXM" | sort)" ]; } && ok "the topic list of a run on cx1 is the lead's and cx1's" || no "run list: rc=$rc out=$out err=$err"
run spawn --run "$T/runs/qargi.bbbbbb"
want=$("$DA" provider notes spawn --project plainx 2>&1)
{ [ $rc = 0 ] && [ "$out" = "$want" ] && grep -q subagent_type <<<"$out"; } && ok "notes-run-primary: a line without a runtime is the project's own runtime" || no "run bbbbbb: rc=$rc out=$out err=$err"
run spawn --run "$T/runs/qargi.ffffff"
{ [ $rc = 0 ] && [ "$out" = "$want" ]; } && ok "a line that names the project's own runtime is too" || no "run ffffff: rc=$rc out=$out err=$err"
run spawn --run "$T/runs/qargi.dddddd"
[ "$out" = "spawn of cx2" ] && ok "the project of the line may have several extras" || no "run dddddd: rc=$rc out=$out err=$err"
run spawn --run "$T/runs/qargi.iiiiii"
[ "$out" = "spawn of cx2" ] && ok "the last line of a run holds" || no "run iiiiii: rc=$rc out=$out err=$err"
out=$(QARGI_PROJECT=withx "$DA" provider notes spawn --run "$T/runs/qargi.eeeeee" 2>&1)
[ "$out" = "spawn of cx1" ] && ok "a line with no project takes the one in effect" || no "run eeeeee: $out"
run spawn --run "$T/runs/qargi.eeeeee"
{ [ $rc = 2 ] && grep -q "no project" <<<"$err"; } && ok "and with none in effect is exit 2" || no "run eeeeee no project: rc=$rc err=$err"
out=$(cd "$T" && "$DA" provider notes spawn --run "runs/qargi.aaaaaa" 2>&1)
[ "$out" = "spawn of cx1" ] && ok "the run directory may be given relative to where the verb runs" || no "relative run: $out"
run spawn --run "$T/runs/qargi.cccccc"
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "the runtime cx2 is not enabled for project withx" <<<"$err" && grep -q "the registry records it for the run $T/runs/qargi.cccccc" <<<"$err"; } \
  && ok "notes-run-disabled: a run whose runtime the project no longer enables is refused, saying whose run it is" || no "run cccccc: rc=$rc out=$out err=$err"
run spawn --run "$T/runs/qargi.dddddd" --project withx
{ [ $rc = 2 ] && grep -q "was made for project withxx, not withx" <<<"$err"; } && ok "a project that is not the line's is refused" || no "run other project: rc=$rc err=$err"
for g in gggggg hhhhhh; do
  run spawn --run "$T/runs/qargi.$g"
  { [ $rc = 2 ] && [ -z "$out" ] && grep -q "is not a runtime name" <<<"$err"; } && ok "notes-run-bad-record: a recorded runtime that is no name ($g) is refused" || no "run $g: rc=$rc out=$out err=$err"
done
run spawn --run "$T/runs/qargi.zzzzzz"
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "names no run $T/runs/qargi.zzzzzz" <<<"$err"; } && ok "notes-run-unknown: a run the registry does not name is refused" || no "run zzzzzz: rc=$rc out=$out err=$err"
mkdir -p "$T/runs/qargi.jjjjjj/clone"; echo '{"runtime":"cx1","project":"withx"}' > "$T/runs/qargi.jjjjjj/record.json"
run spawn --run "$T/runs/qargi.jjjjjj"
{ [ $rc = 2 ] && [ -z "$out" ]; } && ok "a file in the run directory is no record: only the registry is believed" || no "run jjjjjj: rc=$rc out=$out err=$err"
mv "$REG" "$T/reg.saved"
run spawn --run "$T/runs/qargi.aaaaaa" --project withx
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "names no run" <<<"$err"; } && ok "a lead with no registry has no run to read" || no "no registry: rc=$rc out=$out err=$err"
mv "$T/reg.saved" "$REG"
run spawn --run "$T/runs/qargi.aaaaaa" --surface cloud
{ [ $rc = 2 ] && grep -q "local surface" <<<"$err"; } && ok "--run is for the local surface too" || no "run cloud: rc=$rc err=$err"
run identity --run "$T/runs/qargi.aaaaaa" --lead-runtime cx2
[ "$out" = "identity of cx2" ] && ok "--run takes a lead runtime as --runtime does" || no "run lead: rc=$rc out=$out err=$err"
# the run's own directory is not read for it: removing it changes nothing, and the registry is the lead's
rm -rf "$T/runs"
run spawn --run "$T/runs/qargi.aaaaaa"
[ "$out" = "spawn of cx1" ] && ok "a run directory that is gone (cleaned, or a reboot) still names its runtime" || no "gone run: rc=$rc out=$out err=$err"

# the verb still changes nothing
before=$(tree)
run spawn --project withx --runtime cx1; run --project withxx --runtime cx2; run spawn --run "$T/runs/qargi.aaaaaa"; run spawn --project withx --runtime cx2
run identity --project withx --runtime cx1 --lead-runtime cx2; run spawn --project withx --runtime claude-code --lead-runtime cx1
[ "$before" = "$(tree)" ] && ok "notes-readonly: --runtime and --run store and rewrite nothing (answers, definitions, state, home), answered or refused" || no "--runtime or --run changed a file"

exit $fail
