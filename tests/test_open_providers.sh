#!/usr/bin/env bash
# The acceptance test of open providers: two runtimes that exist only as data files (tests/open-providers/fakecli and fakemd, outside
# lib/) are taken through the whole path with nothing added to lib/, bin/ or agents/: import (plan, token, approval), check, the
# project's answer, packs rendered and skipped by compatible_providers, the project link into a work tree, a member rendered into the
# runtime's own file format, DRIFT and STALE, the audit's `excluded`, the command line of a local run, the hook of a read-only
# barrier, the refusals, an extension and its conflict. The last line is `git diff --exit-code -- lib bin agents`.
#   fakecli  agents TOML (file per item, one link per entry), skills dir-symlink, exclusion a config list in TOML, dispatch a command
#            with class arguments and resume, no barrier
#   fakemd   agents markdown with front matter, skills dir-symlink, exclusion a settings key, dispatch in the lead's session, a hook
#            barrier that denies with a JSON document and exit 0
# Hermetic and offline. Run: tests/test_open_providers.sh
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T TMPDIR=$T/tmp
mkdir -p "$T/tmp" "$T/bin" "$T/c/projects" "$T/s"
# shellcheck source=fixtures.sh
. tests/fixtures.sh
skip() { echo "skip $1"; }
DA=$ROOT/bin/qargi
FIX=$ROOT/tests/open-providers
LC="git -c user.name=t -c user.email=t@example.net"
LIB=$T/c/packs/providers
# a member run (a directory `qargi local prepare` made) may hold this test; the verbs that change a checkout refuse inside one
cd "$T" || exit 1

toml() { python3 -I -c 'import tomllib,sys,json; print(json.dumps(tomllib.load(open(sys.argv[1],"rb"))))' "$1" 2>&1; }
mdfm() { # front matter of a markdown member as JSON: top-level keys, one level of nesting, the body
  python3 -I - "$1" <<'PY' 2>&1
import json, sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\n")
assert lines[0] == "---", "no front matter"
end = lines.index("---", 1)
doc, cur = {}, None
for ln in lines[1:end]:
    if ln.startswith("  "):
        k, _, v = ln.strip().partition(": ")
        doc[cur][k] = v
    else:
        k, _, v = ln.partition(":")
        v = v.strip()
        if v == "":
            cur = k
            doc[k] = {}
        else:
            doc[k] = json.loads(v) if v.startswith('"') else v
doc["body"] = "\n".join(lines[end + 1:]).strip("\n")
print(json.dumps(doc))
PY
}
imp() { # DIR [more args]: import a pack through its plan, a token and an approval
  local d=$1 t; shift
  t=$("$DA" provider import "$d" "$@" | tokp)
  [ -n "$t" ] && "$DA" provider import "$d" "$@" --plan "$t" --approved "test" >/dev/null 2>&1
}
seal() { local t; t=$("$DA" provider seal "$1" | tokp); "$DA" provider seal "$1" --plan "$t" --approved test >/dev/null 2>&1; }
mkproj() { # NAME REPO: stored answers; the runtime is set afterwards with `project set`
  jq -n --arg n "$1" --arg p "$2" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
    roles:{build:{base:"main",push:{mode:"none"},effort:"medium"},review:{base:"main",push:{mode:"none"},effort:"medium"}},memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
  git init -q -b main "$2" && $LC -C "$2" commit -q --allow-empty -m one
}
mkskill() { # NAME COMPATIBLE PROJECT: a sealed skill pack linked to the project
  "$DA" skill new "$1" --compatible "$2" >/dev/null
  sed -i "s/^description: .*/description: Use for $1./" "$T/c/packs/skills/$1/SKILL.md"
  local t; t=$("$DA" skill seal "$1" | tokp); "$DA" skill seal "$1" --plan "$t" --approved test >/dev/null
  "$DA" skill link "$1" --scope project --project "$3" >/dev/null
}

# a stand-in for the command of fakecli; nothing here runs it
printf '#!/bin/sh\necho "fakecli-bin is not run by this test"\n' > "$T/bin/fakecli-bin"; chmod 755 "$T/bin/fakecli-bin"; export PATH=$T/bin:$PATH

# --- a name that the shipped runtimes have is refused at the plan, and a library name cannot be taken twice ----------------------------
CL=$T/clash; mkdir -p "$CL"
for n in claude-code claude-platform claude; do
  jq --arg n "$n" '.provider = $n' "$FIX/fakecli/definition.json" > "$CL/definition.json"
  out=$("$DA" provider import "$CL" 2>&1); rc=$?
  { [ $rc != 0 ] && [ -z "$(tokp <<<"$out")" ] && grep -q "$n" <<<"$out"; } && ok "import of the shipped name $n is refused at the plan, with no token" || no "shipped name $n: rc=$rc $out"
done
[ ! -e "$LIB/claude-code" ] && [ ! -e "$LIB/claude" ] && ok "and nothing is stored under a shipped name" || no "stored under a shipped name"

# --- one runtime through the whole path ---------------------------------------------------------------------------------------------
# flow RT TARGET SKDIR AGDIR EXT: RT's definition is a fixture directory, TARGET its render target, SKDIR and AGDIR the work tree's skills and agents
# directories, EXT the member file's extension
flow() {   # (the 6th argument is the name of the member made: member names are the whole tool's)
  local rt=$1 target=$2 skdir=$3 agdir=$4 ext=$5 mem=$6 p repo wt out rc tok f d R MD RD xf
  p=p$rt; repo=$T/r-$rt; wt=$T/wt-$rt; R=$T/s/render/$p; RD=$R/$rt; MD=$R/$rt.agents
  mkproj "$p" "$repo"
  echo "# $rt"

  # import: the plan alone changes nothing, the token is needed, the pack arrives sealed
  out=$("$DA" provider import "$FIX/$rt" 2>&1); tok=$(tokp <<<"$out")
  { [ -n "$tok" ] && [ ! -e "$LIB/$rt" ] && grep -q "^files: 1," <<<"$out"; } && ok "$rt: import prints a review and a plan token and stores nothing" || no "$rt import plan: $out"
  "$DA" provider import "$FIX/$rt" --plan 000000000000 --approved test >/dev/null 2>&1; rc=$?
  { [ $rc != 0 ] && [ ! -e "$LIB/$rt" ]; } && ok "$rt: a wrong token is refused" || no "$rt wrong token: rc=$rc"
  "$DA" provider import "$FIX/$rt" --plan "$tok" >/dev/null 2>&1
  [ ! -e "$LIB/$rt" ] && ok "$rt: and a token with no approval stores nothing either" || no "$rt no approval stored it"
  out=$("$DA" provider import "$FIX/$rt" --plan "$tok" --approved "test" 2>&1)
  { [ -f "$LIB/$rt/definition.json" ] && jq -e '.sealed == true and .kind == "provider"' "$LIB/$rt/.pack.json" >/dev/null; } && ok "$rt: approved, it is stored sealed in the library" || no "$rt import: $out"
  "$DA" provider import "$FIX/$rt" >/dev/null 2>&1; rc=$?
  [ $rc != 0 ] && ok "$rt: importing the name again is refused" || no "$rt import twice: rc=$rc"

  # check: what the hermetic cases can show is recorded, and counts
  out=$("$DA" provider check "$rt" 2>&1); rc=$?
  { [ $rc = 0 ] && grep -q "^ok   render-agent" <<<"$out" && grep -q "^ok   link-skills" <<<"$out"; } && ok "$rt: check renders a sample member twice and links skills in a temporary repository" || no "$rt check: rc=$rc $out"
  jq -e 'has("agent_definitions") and has("skills")' "$T/s/providers/$rt/verified.json" >/dev/null && ok "$rt: and records agent_definitions and skills as verified" || no "$rt verified.json: $(cat "$T/s/providers/$rt/verified.json" 2>&1)"
  [ "$("$DA" provider effective "$rt" local skills)" = yes ] && ok "$rt: skills now count" || no "$rt effective skills"

  # the project's answer
  out=$("$DA" project set "$p" models.provider.local "$rt" 2>&1)
  [ "$(jq -r .models.provider.local "$T/c/projects/$p.json")" = "$rt" ] && ok "$rt: project set models.provider.local stores it" || no "$rt project set: $out"

  # a skill pack that names the runtime is rendered, one that names another is skipped with a note
  mkskill "sk-$rt" "$rt" "$p"; mkskill "sk-other-$rt" elsewhere "$p"
  out=$("$DA" packs apply --target "$target" "$p" 2>&1); tok=$(tokp <<<"$out")
  { [ -n "$tok" ] && grep -q "added .*skill sk-$rt" <<<"$out" && grep -q "skipped skill sk-other-$rt: not compatible with $rt (it declares elsewhere)" <<<"$out"; } && ok "$rt: the packs plan renders the pack that names it and skips the one that does not" || no "$rt packs plan: $out"
  out=$("$DA" packs apply --target "$target" "$p" --plan "$tok" --approved test 2>&1)
  { [ -f "$RD/$skdir/sk-$rt/SKILL.md" ] && [ ! -e "$RD/$skdir/sk-other-$rt" ] && grep -q "^applied: $RD\$" <<<"$out"; } && ok "$rt: packs apply renders into the runtime's skills directory ($skdir), without the skipped pack" || no "$rt packs apply: $out"
  "$DA" packs check --target "$target" "$p" >/dev/null 2>&1 && ok "$rt: and packs check passes" || no "$rt packs check"

  # a member: rendered in the runtime's own format, into the member render
  out=$("$DA" agent add "$mem" --roles build,test --project "$p" 2>&1); f=$MD/$mem$ext
  [ -f "$f" ] && ok "$rt: agent add writes the member where the definition says ($rt.agents/$mem$ext)" || no "$rt agent add: $out"
  grep -q "note: tools: the optional tool 'monitor' has no native name and was dropped" <<<"$out" && ok "$rt: a tool the runtime cannot name is dropped with a note" || no "$rt tool note: $out"
  [ "$("$DA" provider model "$rt" local fast)" != "$("$DA" provider model "$rt" local deep)" ] && ok "$rt: the fast tier and the deep tier map to different models" || no "$rt tiers"

  # the project link, run in a work tree: the links land there and nowhere else
  git -C "$repo" worktree add -q "$wt" -b "wt-$rt"
  out=$(cd "$wt" && "$DA" project link "$p" 2>&1); tok=$(tokp <<<"$out")
  { [ -n "$tok" ] && [ ! -e "$wt/$skdir" ] && grep -q "link plan for $p" <<<"$out"; } && ok "$rt: project link plans first and changes nothing" || no "$rt link plan: $out"
  out=$(cd "$wt" && "$DA" project link "$p" --plan "$tok" --approved test 2>&1); rc=$?
  { [ $rc = 0 ] && [ -L "$wt/$skdir" ] && [ "$(readlink "$wt/$skdir")" = "$RD/$skdir" ] && [ -f "$wt/$skdir/sk-$rt/SKILL.md" ] && [ ! -e "$wt/$skdir/sk-other-$rt" ]; } && ok "$rt: the skills directory of the work tree is a link to the render" || no "$rt link skills (rc=$rc): $out"
  { [ -L "$wt/$agdir/$mem$ext" ] && [ "$(readlink "$wt/$agdir/$mem$ext")" = "$f" ]; } && ok "$rt: and the member is linked in, one link for the entry" || no "$rt link agent: $(ls -la "$wt/$agdir" 2>&1)"
  { [ ! -e "$repo/$skdir" ] && [ ! -e "$repo/$agdir" ]; } && ok "$rt: the main checkout was not touched" || no "$rt main checkout changed"
  out=$(cd "$wt" && "$DA" project link "$p" 2>&1)
  grep -q "^already linked" <<<"$out" && ok "$rt: a second link finds it linked" || no "$rt second link: $out"

  # the file: parsed back, the fields mapped
  case $ext in
    .toml)
      d=$(toml "$f")
      jq -e '.name == "'"$mem"'" and .model == "fc-main" and .effort == "m" and .mode == "write" and .tools == ["sh","cat","ed","tee"] and (.description | startswith("A qargi member")) and (.prompt | startswith("You are a qargi member"))' <<<"$d" >/dev/null \
        && ok "$rt: the file parses as TOML; the balanced tier is the model, effort goes through the runtime's table, tools are renamed, the body is the prompt" || no "$rt toml fields: $d"
      out=$("$DA" agent add quick --roles build --effort xhigh --project "$p" 2>&1); d=$(toml "$MD/quick$ext")
      { jq -e 'has("effort") | not' <<<"$d" >/dev/null && grep -q "effort: omitted" <<<"$out"; } && ok "$rt: an effort the runtime has no value for is left out, with a note" || no "$rt xhigh: $out $d"
      ;;
    .md)
      d=$(mdfm "$f")
      jq -e '.name == "'"$mem"'" and .model == "md-large" and (has("effort") | not) and .tools == "run_shell, open_file, patch_file, create_file, grep_tree" and (.description | startswith("A qargi member")) and (.body | startswith("You are a qargi member")) and .hooks.before_tool == "qargi __guard --provider fakemd"' <<<"$d" >/dev/null \
        && ok "$rt: the file parses as markdown with front matter; the balanced tier is the model, effort is dropped (no control), tools are renamed, the hook is the guard" || no "$rt md fields: $d"
      ;;
  esac
  "$DA" agent list | grep " $mem " | grep -q '(' && no "$rt: $mem flagged right after add: $("$DA" agent list | grep " $mem ")" || ok "$rt: and the new member is current"

  # DRIFT: edited by hand
  printf '# edited by hand\n' >> "$f"
  "$DA" agent list | grep -q "^$p  *$mem .*$mem$ext (DRIFT: qargi agent refresh $mem --project $p)\$" && ok "$rt: a hand edit of the file is DRIFT" || no "$rt drift: $("$DA" agent list | grep " $mem ")"
  "$DA" agent refresh "$mem" >/dev/null 2>&1; "$DA" agent list | grep " $mem " | grep -q '(' && no "$rt: refresh kept the flag" || ok "$rt: refresh renders it again and clears the flag"

  # STALE: the definition changed and was sealed again
  jq '.renderers.agent.fields += [{from:"abilities", to:"serves", transform:[{join:" "}]}]' "$LIB/$rt/definition.json" > "$T/d.json" && cp "$T/d.json" "$LIB/$rt/definition.json"
  seal "$rt"
  "$DA" agent list | grep -q "^$p  *$mem .*$mem$ext (STALE: qargi agent refresh $mem --project $p)\$" && ok "$rt: a definition changed and sealed again makes its members STALE" || no "$rt stale: $("$DA" agent list | grep " $mem ")"
  out=$("$DA" agent models --project "$p" --json 2>&1); rc=$?
  if [ "$rt" = fakecli ]; then
    { [ $rc = 0 ] && jq -e '.provider == "fakecli" and .mode == "command" and .members == []
      and .bases.worker.logical == true and .bases.worker.registered == false
      and .profiles.build.base == "worker" and .profiles.build.selected == "fc-main"
      and .profiles.build.requested_effort == "high" and .profiles.build.refused == null and .profiles.build.flags == []' <<<"$out" >/dev/null; } \
      && ok "$rt: agent models resolves logical command profiles with requested high effort despite stale rendered members" || no "$rt command models: rc=$rc $out"
  else
    { [ $rc = 0 ] && jq -e --arg m "$mem" '[.members[] | select(.name == $m)] | length == 1 and (.[0].state == ["STALE"])' <<<"$out" >/dev/null; } \
      && ok "$rt: in-session agent models says STALE too" || no "$rt models stale: rc=$rc $out"
  fi
  "$DA" agent refresh "$mem" >/dev/null 2>&1
  { ! "$DA" agent list | grep " $mem " | grep -q '('; } && grep -q "serves" "$f" && ok "$rt: refresh renders the new definition" || no "$rt refresh: $("$DA" agent list | grep " $mem ")"
  out=$("$DA" provider check "$rt" 2>&1); [ "$("$DA" provider effective "$rt" local skills)" = yes ] && ok "$rt: and check records the verification of the new content" || no "$rt recheck: $out"

  # the audit: a skill of the user's own in the main checkout is unmanaged until the runtime's exclusion hides it
  mkdir -p "$repo/$skdir/mine"; printf -- '---\nname: mine\ndescription: mine\n---\n' > "$repo/$skdir/mine/SKILL.md"
  out=$(cd "$repo" && "$DA" packs link "$p" 2>&1)
  grep -qE "^ +unmanaged +mine  \(checkout" <<<"$out" && ok "$rt: the audit lists a skill nobody manages as unmanaged" || no "$rt audit unmanaged: $out"
  case $rt in
    fakecli) mkdir -p "$repo/.fake"; printf '[[skills.config]]\nname = "mine"\nenabled = false\n' > "$repo/.fake/config.toml"; xf=$repo/.fake/config.toml;;
    fakemd) mkdir -p "$repo/.fakemd"; printf '{"skills_off": {"mine": "off"}}\n' > "$repo/.fakemd/settings.json"; xf=$repo/.fakemd/settings.json;;
  esac
  out=$(cd "$repo" && "$DA" packs link "$p" 2>&1)
  grep -qE "^ +excluded +mine  \(checkout, [0-9a-f]+, off in $xf\)" <<<"$out" && ok "$rt: its exclusion entry ($(basename "$xf")) makes the audit say excluded, naming the file" || no "$rt audit excluded: $out"
  rm -rf "${repo:?}/${skdir:?}"
}

flow fakecli fakecli-render .agents/skills .fake/agents .toml forge
flow fakemd fakemd-render .fakemd/skills .fakemd/agents .md forge-md

# --- dispatch of fakecli: the command line is made from the data ----------------------------------------------------------------------
echo "# fakecli dispatch"
P=pfakecli; REPO=$T/r-fakecli
prep() { eval "$("$DA" local prepare --repo "$1" --base main --slug "$2" --scratch "$T" ${3:+--role "$3"} | sed '/^$/,$d' | sed 's/^/export /')"; printf 'TASK: change the thing\nDONE: it is changed\n' > "$RUN/task.md"; }
argv() { sed -n 's/^ARGV=//p'; }
prep "$REPO" w1
[ "$EFFORT" = high ] && [ "$MODEL" = fc-main ] && ok "fakecli: implicit build preparation requests high effort and fc-main, independently of rendered medium effort" || no "fakecli implicit request: model=$MODEL effort=$EFFORT"
out=$("$DA" local run "$RUN" --dry-run 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" '["fakecli-bin","run","--model","fc-main","--effort","h","--cd",$c]')
{ [ $rc = 0 ] && [ "$(argv <<<"$out")" = "$want" ]; } && ok "fakecli: local run --dry-run prints the argv of the data" || no "fakecli dry argv: rc=$rc [$(argv <<<"$out")] want [$want]"
grep -q '^PROMPT_VIA=stdin' <<<"$out" && grep -q '^TASK: change the thing' <<<"$out" && grep -q '^CLASS=write' <<<"$out" && ok "fakecli: the prompt goes to standard input, and is the member and the task block" || no "fakecli dry prompt: $out"
out=$("$DA" local run "$RUN" --dry-run --model balanced --effort high 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(argv <<<"$out")" = "$want" ]; } && ok "fakecli: repeating the prepared model tier and effort needs no override capability" || no "fakecli same request: rc=$rc $out"
for cap in per_dispatch_model_override per_dispatch_effort_override; do
  [ "$("$DA" provider effective fakecli local "$cap")" = no ] && ok "fakecli: $cap is unverified and counts as no" || no "fakecli $cap already supported"
  if [ "$cap" = per_dispatch_model_override ]; then opts=(--model fast); else opts=(--effort low); fi
  out=$("$DA" local run "$RUN" --dry-run "${opts[@]}" 2>&1); rc=$?
  { [ $rc = 2 ] && [ -z "$(argv <<<"$out")" ] && grep -q "$cap" <<<"$out"; } && ok "fakecli: an unsupported override refuses naming $cap without argv" || no "fakecli $cap refusal: rc=$rc $out"
done
out=$("$DA" local run "$RUN" --dry-run --effort max 2>&1); rc=$?
{ [ $rc = 0 ] && ! grep -q -- '--effort' <<<"$(argv <<<"$out")"; } && grep -q '^NOTE=effort max is dropped' <<<"$out" && ok "fakecli: an effort it has no value for is dropped with a note" || no "fakecli max: rc=$rc $out"

# Give the fixture's declared override controls verification, then prepare against that policy. A refusal-only branch would not test tier expansion.
for cap in per_dispatch_model_override per_dispatch_effort_override; do
  opts=(--asked "verify fixture override" --did "offline fixture declares per-invocation model and effort argv" --result pass --cost-cents 0 --cleanup "scratch fixture only")
  out=$("$DA" provider attest fakecli "$cap" "${opts[@]}" 2>&1); tok=$(tokp <<<"$out")
  out=$("$DA" provider attest fakecli "$cap" "${opts[@]}" --plan "$tok" --approved test 2>&1); rc=$?
  { [ $rc = 0 ] && [ "$("$DA" provider effective fakecli local "$cap")" = yes ]; } && ok "fakecli: attested $cap is supported" || no "fakecli $cap attestation: rc=$rc $out"
done
out=$("$DA" local run "$RUN" --dry-run --model fast --effort low 2>&1); rc=$?
{ [ $rc = 2 ] && [ -z "$(argv <<<"$out")" ] && grep -q 'prepared command request runtime/mode/catalog/profile/policy drift' <<<"$out"; } && ok "fakecli: changed capability policy still requires reprepare, even with explicit overrides" || no "fakecli policy drift: rc=$rc $out"
prep "$REPO" w2
out=$("$DA" local run "$RUN" --dry-run --model fast --effort high 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" '["fakecli-bin","run","--model","fc-mini","--effort","h","--cd",$c]')
{ [ $rc = 0 ] && [ "$(argv <<<"$out")" = "$want" ]; } && ok "fakecli: supported --model fast selects fc-mini and --effort high becomes h" || no "fakecli tier argv: rc=$rc $out"
out=$("$DA" local run "$RUN" --dry-run --model fast --effort low 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" '["fakecli-bin","run","--model","fc-mini","--effort","l","--cd",$c]')
{ [ $rc = 0 ] && [ "$(argv <<<"$out")" = "$want" ]; } && ok "fakecli: supported native effort override selects l with the fast tier" || no "fakecli effort argv: rc=$rc $out"

# a read-only member and run need a barrier or the project's acceptance
out=$("$DA" agent add judge --roles review --project "$P" 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q "no read-only barrier on local" <<<"$out" && grep -q "qargi provider accept fakecli --surface local --no-barrier --project $P" <<<"$out" && [ ! -e "$T/s/render/$P/fakecli.agents/judge.toml" ]; } && ok "fakecli: a read-only member is refused (exit 2) with the accept command, and nothing is written" || no "fakecli review refused: rc=$rc $out"
out=$("$DA" local prepare --repo "$REPO" --base main --slug r0 --scratch "$T" --role review 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q "no read-only barrier on local" <<<"$out"; } && ok "fakecli: and local prepare will not start a read-only run" || no "fakecli review prepare: rc=$rc $out"
ACC=(fakecli --surface local --no-barrier --asked "the fixture runtime has no barrier" --project "$P")
out=$("$DA" provider accept "${ACC[@]}" 2>&1); tok=$(tokp <<<"$out")
{ [ -n "$tok" ] && ! jq -e '.models.accept_no_barrier' "$T/c/projects/$P.json" >/dev/null 2>&1; } && ok "fakecli: provider accept plans first and records nothing" || no "fakecli accept plan: $out"
"$DA" provider accept "${ACC[@]}" --plan "$tok" --approved "my call" >/dev/null 2>&1
jq -e '.models.accept_no_barrier.local.reason == "the fixture runtime has no barrier"' "$T/c/projects/$P.json" >/dev/null && ok "fakecli: applied, the acceptance is in the project's answers" || no "fakecli accept record"
prep "$REPO" r1 review
out=$("$DA" local run "$RUN" --dry-run 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" '["fakecli-bin","run","--model","fc-main","--effort","h","--cd",$c,"--sandbox","read-only"]')
{ [ $rc = 0 ] && [ "$(argv <<<"$out")" = "$want" ] && grep -q '^CLASS=read-only' <<<"$out"; } && ok "fakecli: after the acceptance the read-only run adds the class arguments (--sandbox read-only)" || no "fakecli ro argv: rc=$rc [$(argv <<<"$out")] want [$want]"
out=$("$DA" agent add judge --roles review --project "$P" 2>&1); rc=$?
{ [ $rc = 0 ] && [ -f "$T/s/render/$P/fakecli.agents/judge.toml" ]; } && jq -e '.mode == "read-only"' <<<"$(toml "$T/s/render/$P/fakecli.agents/judge.toml")" >/dev/null && ok "fakecli: and the read-only member is made, with its class in the file" || no "fakecli review after accept: rc=$rc $out"

# --- dispatch of fakemd: in the lead's session, and the hook that holds a read-only member ---------------------------------------------
echo "# fakemd dispatch and barrier"
P=pfakemd; REPO=$T/r-fakemd
prep "$REPO" m1
out=$("$DA" local run "$RUN" --dry-run 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q "dispatches in the lead's own session" <<<"$out" && grep -q "dispatch the member with the Agent tool" <<<"$out"; } && ok "fakemd: local run refuses a runtime that works in the session, and says to use the Agent tool" || no "fakemd local run: rc=$rc $out"
"$DA" agent add worker --roles build,test --project "$P" >/dev/null 2>&1
"$DA" agent for build --project "$P" --json | jq -e '.member == "worker" and .model_id == "md-large" and .model == "large"' >/dev/null && ok "fakemd: agent for names the member and its model for the session to dispatch" || no "fakemd agent for: $("$DA" agent for build --project "$P" --json 2>&1)"
out=$("$DA" agent add judge-md --roles review --project "$P" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$("$DA" provider effective fakemd local read_only_barrier)" = yes ]; } && ok "fakemd: its hook barrier was verified by check, so a read-only member needs no acceptance" || no "fakemd review: rc=$rc $out"
jq -e '.hooks.before_tool == "qargi __guard --provider fakemd --class read-only"' <<<"$(mdfm "$T/s/render/$P/fakemd.agents/judge-md.md")" >/dev/null && ok "fakemd: and its hook line carries the class" || no "fakemd hook line: $(cat "$T/s/render/$P/fakemd.agents/judge-md.md")"
out=$("$DA" provider check fakemd 2>&1)
grep -q "^ok   barrier-hook: [0-9]* corpus calls" <<<"$out" && ok "fakemd: check ran the shipped barrier corpus through __guard --provider fakemd" || no "fakemd barrier-hook: $out"

# the guard on a corpus of calls, in the hook's own protocol: a JSON document on standard output and exit 0 for a deny, nothing for an allow
GR=$T/grun; mkdir -p "$GR/clone/src" "$GR/out" "$T/ghome"
printf 'build\n' > "$GR/ability"; printf 'write\n' > "$GR/class"; : > "$GR/refs.before"
guard() { # CLASS TOOL KEY VALUE: one call through the hook; the payload is made with fakemd's pointers
  local cls=$1 tool=$2 key=$3 val=$4
  jq -nc --arg t "$tool" --arg k "$key" --arg v "$val" --arg w "$GR/clone" '{event:{tool:$t,args:{($k):$v}},workdir:$w}' \
    | (cd "$GR/clone" && env HOME="$T/ghome" "$DA" __guard --provider fakemd ${cls:+--class "$cls"})
}
deny() { # CLASS TOOL KEY VALUE WORDS: exit 0, a JSON deny on stdout whose reason has WORDS
  local out rc; out=$(guard "$1" "$2" "$3" "$4" 2>"$T/gerr"); rc=$?
  [ $rc = 0 ] && [ ! -s "$T/gerr" ] && jq -e --arg w "$5" '.decision == "deny" and (.reason | startswith("qargi guard: ")) and (.reason | contains($w))' <<<"$out" >/dev/null
}
pass() { local out rc; out=$(guard "$1" "$2" "$3" "$4" 2>"$T/gerr"); rc=$?; [ $rc = 0 ] && [ -z "$out" ] && [ ! -s "$T/gerr" ]; }
deny '' run_shell cmd "git push origin main" "Agents never push" && ok "fakemd guard: git push is a JSON deny with exit 0" || no "guard push"
deny '' run_shell cmd "gh pr list" "gh is not available" && ok "fakemd guard: so is gh" || no "guard gh"
deny '' patch_file target "$T/c/packs/skills/x/SKILL.md" "a protected location" && ok "fakemd guard: a write into the pack library is denied (a path pointer of the definition)" || no "guard library write"
deny '' run_shell cmd "qargi skill new x" "changes a skill" && ok "fakemd guard: and a verb that changes a skill" || no "guard skill verb"
pass '' run_shell cmd "ls -la && git status" && ok "fakemd guard: an ordinary call passes with nothing printed" || no "guard pass ls"
pass '' patch_file target "$GR/clone/src/a.go" && ok "fakemd guard: a write in the clone passes for a write run" || no "guard pass write"
deny read-only patch_file target "$GR/clone/src/a.go" "under the read-only class" && ok "fakemd guard: --class read-only denies a write in the clone" || no "guard ro write"
deny read-only run_shell cmd "echo x > src/a.go" "under the read-only class" && ok "fakemd guard: and a shell redirect into it" || no "guard ro redirect"
pass read-only create_file target "$GR/out/report.md" && ok "fakemd guard: but the report in the run's out directory is allowed" || no "guard ro report"
pass read-only open_file target "$GR/clone/src/a.go" && ok "fakemd guard: and reading is allowed" || no "guard ro read"
printf '{"tool_name":"Bash","tool_input":{"command":"git push"},"cwd":"%s"}' "$GR/clone" | (cd "$GR/clone" && env HOME="$T/ghome" "$DA" __guard --provider fakemd) | grep -q . \
  && no "guard read another runtime's payload" || ok "fakemd guard: another runtime's payload shape means nothing to it (the definition's pointers are the only ones read)"

# --- an extension that gives fakecli a read-only barrier; a second one conflicts; it counts only when verified -----------------------------
echo "# extensions"
X=pext; XR=$T/r-pext
mkproj "$X" "$XR"
"$DA" project set "$X" models.provider.local fakecli >/dev/null 2>&1
imp "$FIX/hookbar" && imp "$FIX/hookbar2" && ok "extensions: two extension packs that both give fakecli read_only_barrier are imported (sealed, not enabled)" || no "extension import"
jq -e '.models.extensions == null' "$T/c/projects/$X.json" >/dev/null && ok "extensions: importing enables nothing" || no "extension enabled by import"
eff() { "$DA" provider effective fakecli local read_only_barrier --project "$X" 2>&1; }
enable() { local o t; o=$("$DA" provider enable "$X" "$1" 2>&1) || { echo "$o"; return 1; }; t=$(tokp <<<"$o"); [ -n "$t" ] && "$DA" provider enable "$X" "$1" --plan "$t" --approved test 2>&1; }
out=$(enable hookbar)
{ jq -e '.models.extensions == ["hookbar"]' "$T/c/projects/$X.json" >/dev/null && grep -q "^enabled extension hookbar for project $X" <<<"$out"; } && ok "extensions: enable (plan, token, approval) puts hookbar in the project's answers" || no "enable hookbar: $out"
[ "$(eff)" = no ] && ok "extensions: enabled but not checked, it counts as no" || no "hookbar before check: $(eff)"
out=$("$DA" agent add judge-x --roles review --project "$X" 2>&1); rc=$?
[ $rc = 2 ] && ok "extensions: and a read-only member is still refused" || no "review before check: rc=$rc $out"
out=$(enable hookbar2); rc=$?
{ [ $rc != 0 ] && grep -q "extensions hookbar and hookbar2 both add capabilities.read_only_barrier" <<<"$out" && jq -e '.models.extensions == ["hookbar"]' "$T/c/projects/$X.json" >/dev/null; } && ok "extensions: a second extension giving the same capability conflicts, naming both, and nothing is enabled" || no "conflict: rc=$rc $out"
jq '.models.extensions = ["hookbar", "hookbar2"]' "$T/c/projects/$X.json" > "$T/p.tmp" && cp "$T/p.tmp" "$T/c/projects/$X.json"
out=$("$DA" provider effective fakecli local read_only_barrier --project "$X" 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q "extensions hookbar and hookbar2 both add" <<<"$out"; } && ok "extensions: both forced into the answers, the composition is refused (exit 2) and nothing is guessed" || no "forced conflict: rc=$rc $out"
jq '.models.extensions = ["hookbar"]' "$T/c/projects/$X.json" > "$T/p.tmp" && cp "$T/p.tmp" "$T/c/projects/$X.json"
out=$("$DA" provider check hookbar --project "$X" 2>&1); rc=$?
if grep -q "^ok   barrier-hook" <<<"$out"; then
  [ "$(eff)" = yes ] && ok "extensions: the extension's check passed and the barrier counts" || no "check passed but the barrier does not count: $(eff)"
else
  # FAIL-expected (data only): the guard reads a hook by a runtime's name, not by a composition, so provider check cannot run the corpus on
  # an extension's barrier; the capability stays unverified until the owner attests it
  skip "extensions: check of hookbar cannot verify read_only_barrier with data only (the guard reads a runtime's hook by its name, not a composition): FAIL-expected, see the report"
  { [ $rc = 0 ] && grep -q "^skip barrier-hook" <<<"$out" && [ "$(eff)" = no ]; } && ok "extensions: the check skipped the hook case and the barrier still counts as no" || no "hookbar check: rc=$rc $out"
  W=(--project "$X" --asked "I fed the hook a write by hand" --did "fed the fixture hook a write and a read" --result pass --cost-cents 0 --cleanup "nothing left")
  out=$("$DA" provider attest hookbar read_only_barrier "${W[@]}" 2>&1); tok=$(tokp <<<"$out")
  [ -n "$tok" ] && [ "$(eff)" = no ] && ok "extensions: attest plans first and records nothing" || no "attest plan: $out"
  "$DA" provider attest hookbar read_only_barrier "${W[@]}" --plan "$tok" --approved "my own check" >/dev/null 2>&1
  [ "$(eff)" = yes ] && ok "extensions: attested for exactly this content, the barrier counts for this project" || no "attest apply: $(eff)"
fi
[ "$("$DA" provider effective fakecli local read_only_barrier)" = no ] && ok "extensions: for a project that did not enable it (or without a project) the runtime alone still has none" || no "barrier leaked to the runtime"
out=$("$DA" agent add judge-x --roles review --project "$X" 2>&1); rc=$?
{ [ $rc = 0 ] && [ -f "$T/s/render/$X/fakecli.agents/judge-x.toml" ]; } && ok "extensions: and now a read-only member is made without an acceptance" || no "review after verify: rc=$rc $out"
jq -e '.models.accept_no_barrier == null' "$T/c/projects/$X.json" >/dev/null && ok "extensions: the project never accepted a missing barrier" || no "accept recorded"
jq '.description = "edited after the check"' "$LIB/hookbar/definition.json" > "$T/d.json" && cp "$T/d.json" "$LIB/hookbar/definition.json"; seal hookbar
[ "$(eff)" = no ] && ok "extensions: an edit of the extension makes what was verified count as no again" || no "stale extension verification: $(eff)"

# an extension that a hermetic case can verify: skills for a runtime that has none counts as soon as its check passes
NS=$T/nosk; mkdir -p "$NS"
jq '.provider = "nosk" | del(.resources.skills) | del(.capabilities.skills) | del(.session)' "$FIX/fakecli/definition.json" > "$NS/definition.json"
SX=$T/skext; mkdir -p "$SX"
jq -n --slurpfile d "$FIX/fakecli/definition.json" '{schema:2,kind:"extension",extension:"skext",description:"gives nosk the skills resource",extends:"nosk",provides:["skills"],
  adds:{capabilities:{skills:{value:"yes",note:"a directory link"}},resources:{skills:$d[0].resources.skills}}}' > "$SX/definition.json"
imp "$NS" && imp "$SX" || no "could not import nosk and skext"
mkproj pnosk "$T/r-nosk"; "$DA" project set pnosk models.provider.local nosk >/dev/null 2>&1
o=$("$DA" provider enable pnosk skext 2>&1); t=$(tokp <<<"$o"); "$DA" provider enable pnosk skext --plan "$t" --approved test >/dev/null 2>&1
sk() { "$DA" provider effective nosk local skills --project pnosk 2>&1; }
[ "$(sk)" = no ] && ok "extensions: skext enabled, not checked: skills count as no" || no "skext before check: $(sk)"
out=$("$DA" provider check skext --project pnosk 2>&1)
{ grep -q "^ok   link-skills" <<<"$out" && [ "$(sk)" = yes ]; } && ok "extensions: its check ran the link case on the composition, and now skills count" || no "skext check: $out / $(sk)"
[ "$("$DA" provider effective nosk local skills)" = no ] && ok "extensions: for the runtime alone they still do not" || no "skext leaked"

# --- a barrier that is claimed and not there is a fail-open, and the check fails it -------------------------------------------------------
echo "# a read-only barrier claimed and not provided"
# failopen: claims read_only_barrier, barrier kind none, no read-only arguments in its dispatch. The check fails it (a directory, and the
# pack as the import would store it), naming the surface and the fix, and nothing of it is verified.
out=$("$DA" provider check "$FIX/failopen" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "^fail: .*read_only_barrier.* on local" <<<"$out" && grep -q "set barrier.kind" <<<"$out" && grep -q "declare the capability not supported" <<<"$out" && grep -q "nothing is verified while the pack fails" <<<"$out"; } && ok "failopen: check fails a claimed read_only_barrier with barrier kind none and no class arguments, naming the surface and the fix" || no "failopen check: rc=$rc $out"
out=$("$DA" provider import "$FIX/failopen" 2>&1); rc=$?
{ [ $rc != 0 ] && [ -z "$(tokp <<<"$out")" ] && [ ! -e "$LIB/failopen" ]; } && ok "failopen: and the import is refused at the plan, with no token" || no "failopen import: rc=$rc $out"
# claimext adds a claim and no barrier to plainrt (which has none and no class arguments): the composition is the same fail-open
imp "$FIX/plainrt" && imp "$FIX/claimext" && ok "claimext: the runtime and an extension that only claims a barrier are imported (an extension is judged on the composition)" || no "plainrt/claimext import"
C=pclaim; mkproj "$C" "$T/r-claim"
"$DA" project set "$C" models.provider.local plainrt >/dev/null 2>&1
X=$C; out=$(enable claimext)
out=$("$DA" provider check claimext --project "$C" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q "^fail: .*read_only_barrier.*claimext.*plainrt.* on local" <<<"$out" && grep -q "set barrier.kind" <<<"$out" && grep -q "declare the capability not supported" <<<"$out"; } && ok "claimext: check fails the composition, naming the extension, the runtime, the surface and the fix" || no "claimext check: rc=$rc $out"
[ ! -e "$T/s/providers/claimext/verified.json" ] && [ "$("$DA" provider effective plainrt local read_only_barrier --project "$C")" = no ] && ok "claimext: and nothing is verified, so the claim counts as no" || no "claimext verified: $(cat "$T/s/providers/claimext/verified.json" 2>&1)"

# --- the whole run changed nothing in the tool ----------------------------------------------------------------------------------------
cd "$ROOT" || exit 1
rm -rf "$T"
git diff --exit-code -- lib bin agents >/dev/null 2>&1 && ok "git diff --exit-code -- lib bin agents: nothing in lib/, bin/ or agents/ was needed or changed" || no "lib, bin or agents differ from the index"
exit $fail
