#!/usr/bin/env bash
# A run option of a runtime (dispatch.run_config.options of its definition): an opt-in change to the run's configuration file that the project's owner
# enables per runtime (`qargi provider enable PROJECT --runtime NAME --option OPT`: a plan, a token and words that carry the phrase of the option) and a profile
# of the project selects (profiles.NAME.options); a run of that profile then gets the baseline with the option's settings applied, and nothing else changed.
# Default off: a project and a profile with no option get the run file, the prepare and run output and the plans they always had.
# Hermetic and offline: a copy of the tool holds fake command runtimes derived from the shipped codex definition (tests/fakeprov.sh), whose stub commits a file;
# no live runtime is started and nothing is spent. Run: tests/test_run_options.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
umask 077
unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_AUTHOR_DATE GIT_COMMITTER_DATE
SRC=$PWD
T=$(mktemp -d); fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T TMPDIR=$T/tmp
unset QARGI_PROJECT QARGI_LEAD_RUNTIME
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/tmp" "$T/scr"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
LC="git -c user.name=t -c user.email=t@example.net"
HID=$T/hidden-by-the-sandbox
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
NOHIDE='.dispatch.hidden_paths.prefixes = ["'"$HID"'"]'
export PATH=$TOOL/stubs:$PATH          # a runtime's command is found by name on PATH
mkfake() { # NAME FILTER: a fake command runtime (the shipped codex definition under another name, with its option), its command a stub by name
  fake_command_runtime "$SRC" "$TOOL" "$1" ".dispatch.argv[0] = \"$1\" | $NOHIDE | ${2:-.}"
  mkdir -p "$HOME/.$1-members"; echo '{}' > "$HOME/.$1-members/auth.json"
}
OPT=image_generation
PHRASE='hosted image generation runs outside the sandbox'
mkfake fakeimg
mkfake fakeother
mkfake fakeplain 'del(.dispatch.run_config.options)'
python3 -I "$TOOL/lib/provider.py" check fakeimg >/dev/null 2>&1 && python3 -I "$TOOL/lib/provider.py" check fakeplain >/dev/null 2>&1 \
  && ok "the fake runtimes are valid, the first with the option the shipped definition declares and the second with none" || no "the fake runtimes"
jq -e --arg o "$OPT" '.dispatch.run_config.options[$o].verified_on == null and .dispatch.run_config.baseline.features[$o] == false' "$SRC/lib/providers/codex.json" >/dev/null \
  && ok "the shipped codex definition declares the option unverified and keeps its baseline off" || no "codex.json: the option"

mkproj() { # NAME PROVIDER-JSON [EXTRAS-JSON [PROFILES-JSON]]: stored answers with a repository of their own
  local repo=$T/repo-$1
  git init -q -b main "$repo" && $LC -C "$repo" commit -q --allow-empty -m one
  jq -n --arg n "$1" --arg p "$repo" --argjson prov "$2" --argjson ex "${3:-null}" --argjson pr "${4:-null}" \
    '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
      roles:{build:{base:"main",push:{mode:"none"},effort:"medium"},review:{base:"main",push:{mode:"none"},effort:"medium"}}, profiles:($pr // {}),
      models:({provider:$prov} + (if $ex == null then {} else {extra_runtimes:{local:$ex}} end)),
      memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
}
EN() { "$DA" provider enable "$@"; }
DIS() { "$DA" provider disable "$@"; }
tokof_() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$1"; }
opts_of() { jq -c '(.models.run_options // null) | if . == null then "none" else {local: .local} end' "$T/c/projects/$1.json"; }
digs_of() { jq -c '.models.run_options.declared // "none"' "$T/c/projects/$1.json"; }
ro_store() { python3 -I "$TOOL/lib/gated_answers.py" store "$1" "$2" "$3" --conf "$T/c" >/dev/null 2>&1; }
ro_dig() { # PROJECT RUNTIME: record the digest of each enabled option's declaration as the definition declares it now, as the approval of an enable does
  local d
  d=$(python3 -I - "$TOOL/lib" "$T/c/projects/$1.json" "$2" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
import provider as P
declared = P.declared_options(P.composed(sys.argv[3], "local"))
names = P.run_options_of(json.load(open(sys.argv[2]))).get(sys.argv[3], [])
print(json.dumps({n: P.option_digest(declared[n]) for n in names if n in declared}))
PY
  ) && ro_store "$1" "models.run_options.declared.$2" "$d"
}
ro_set() { ro_store "$1" "models.run_options.local.$2" "$3" && ro_dig "$1" "$2"; }       # PROJECT RUNTIME LIST: as the enable verb stores them
nlines() { local n; n=$(grep -c "provider:$1" "$T/s/audit.log" 2>/dev/null); echo "${n:-0}"; }
refusal_code() { sed -n 's/^qargi-refusal\/1 .*"code":"\([a-z-]*\)".*/\1/p' <<<"$1"; }
own='{"local":"fakeimg"}'
PROFILES='{"imgs":{"base":"worker","tier":"balanced","effort":"high","options":["image_generation"]},"plain":{"base":"worker","tier":"balanced","effort":"high"}}'

# --- the plan: what the option adds to the run's file, what it opens, what the owner must say; it changes nothing
mkproj g1 "$own" '["fakeother"]'
out=$(EN g1 --runtime fakeimg --option "$OPT" 2>&1); rc=$?
tok=$(tokof_ "$out")
{ [ "$rc" = 0 ] && [ -n "$tok" ] && [ "$(opts_of g1)" = '"none"' ] && [ "$(nlines enable-option)" = 0 ]; } && ok "plan: without --plan and --approved it prints the plan and a token and changes nothing" || no "plan: rc=$rc $out"
{ grep -q '^enable run option image_generation of runtime fakeimg for project g1 (models.run_options.local.fakeimg)$' <<<"$out" \
  && grep -qx '    \[features\]' <<<"$out" && grep -qx '    image_generation = true' <<<"$out" && ! grep -q 'approval_policy' <<<"$out"; } \
  && ok "plan: the settings the option adds to the run's config.toml, as the TOML lines, and nothing of the baseline" || no "plan settings: $out"
{ grep -q '^for write runs only: write; a read-only run never gets it' <<<"$out" && grep -q '^outside the sandbox: the tool this opens runs outside the sandbox of fakeimg' <<<"$out" \
  && grep -q "^spend: it may spend on the members' sign-in; qargi does not measure that" <<<"$out" && grep -q '^writes: the image files the member saves' <<<"$out"; } \
  && ok "plan: the barrier note: write runs only, outside the sandbox, may spend and is not measured, where it writes" || no "plan barrier: $out"
{ grep -q '^reads: members on fakeimg can read the real ~/.codex' <<<"$out" && grep -q '^verified: no (verified_on is null): codex-cli 0.171.0' <<<"$out" \
  && grep -q '^profiles that could select it now: none yet; a profile of base worker selects it with profiles.NAME.options' <<<"$out" \
  && grep -q "^the owner.s approval words must contain: \"$PHRASE\"$" <<<"$out"; } \
  && ok "plan: the reads warning of the runtime, that the option is unverified, the profiles that could select it and the phrase" || no "plan tail: $out"

# --- the approval: words that carry the phrase; a wrong token is plan-stale; the token stays good after a refused approval
EN g1 --runtime fakeimg --option "$OPT" --plan wrong --approved "go ahead, $PHRASE" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 1 ] && grep -q '"code":"plan-stale"' "$T/e" && [ "$(opts_of g1)" = '"none"' ]; } && ok "a wrong token is plan-stale and stores nothing" || no "wrong token: rc=$rc $(cat "$T/e")"
EN g1 --runtime fakeimg --option "$OPT" --plan "$tok" --approved "go ahead" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 1 ] && grep -q '"code":"runtime-option-unacknowledged"' "$T/e" && grep -q 'refused \[runtime-option-unacknowledged\] the approval of the option image_generation of the runtime fakeimg does not carry the phrase' "$T/e" \
  && [ "$(opts_of g1)" = '"none"' ] && [ "$(nlines enable-option)" = 0 ]; } \
  && ok "unacknowledged: an approval without the phrase is runtime-option-unacknowledged (exit 1), stores nothing and writes no audit line" || no "no phrase: rc=$rc $(cat "$T/e")"
EN g1 --runtime fakeimg --option "$OPT" --plan "$tok" --approved "hosted image generation runs outside the sandboxes" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 1 ] && grep -q '"code":"runtime-option-unacknowledged"' "$T/e" && [ "$(opts_of g1)" = '"none"' ]; } && ok "unacknowledged-as-words: a word that only starts like the phrase's last one does not carry it" || no "as words: rc=$rc $(cat "$T/e")"
EN g1 --runtime fakeimg --option "$OPT" --plan "$tok" --approved "unhosted image generation runs outside the sandbox" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 1 ] && grep -q '"code":"runtime-option-unacknowledged"' "$T/e" && [ "$(opts_of g1)" = '"none"' ]; } && ok "unacknowledged-as-words: a word that only ends like the phrase's first one does not carry it either" || no "as words, prefix: rc=$rc $(cat "$T/e")"
# a hyphen is part of a word: the phrase inside a longer hyphenated word (xphrase, phrase-x, x-phrase) is not carried; the exact phrase in a sentence is
for words in "xhosted image generation runs outside the sandbox" "hosted image generation runs outside the sandbox-x" "x-hosted image generation runs outside the sandbox" \
             "hosted image generation runs outside the x-sandbox" "hosted image generation runs outside the sandbox_x" "hosted-image generation runs outside the sandbox"; do
  EN g1 --runtime fakeimg --option "$OPT" --plan "$tok" --approved "$words" >"$T/o" 2>"$T/e"; rc=$?
  { [ "$rc" = 1 ] && grep -q '"code":"runtime-option-unacknowledged"' "$T/e" && [ "$(opts_of g1)" = '"none"' ] && [ "$(nlines enable-option)" = 0 ]; } \
    && ok "unacknowledged-as-words: '$words' does not carry the phrase" || no "hyphen ($words): rc=$rc $(cat "$T/e")"
done
EN g1 --runtime fakeimg --option "$OPT" --plan "$tok" --approved "yes: Hosted  IMAGE
generation runs outside the sandbox, and it may spend" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 0 ] && [ "$(opts_of g1)" = '{"local":{"fakeimg":["image_generation"]}}' ]; } \
  && ok "acknowledged: the same token is still good, and words that carry the phrase (other letter case, runs of blanks) store the option at models.run_options.local.fakeimg" || no "phrase: rc=$rc $(cat "$T/e" "$T/o")"
{ [ "$(nlines enable-option)" = 1 ] && tail -1 "$T/s/audit.log" | jq -e '.verb == "provider:enable-option" and (.approved | test("IMAGE")) and (.detail | test("^g1 runtime fakeimg option image_generation "))' >/dev/null; } \
  && ok "one audit line, provider:enable-option, keeps the words of the approval" || no "audit: $(tail -2 "$T/s/audit.log")"
"$DA" project validate g1 >/dev/null 2>&1 && ok "the stored answers stay valid for project validate" || no "validate g1: $("$DA" project validate g1 2>&1)"
out=$(EN g1 --runtime fakeimg --option "$OPT" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'nothing to do: the option image_generation of fakeimg is enabled for g1 already' <<<"$out" && [ "$(nlines enable-option)" = 1 ]; } && ok "enabling again says so and records nothing more" || no "again: $out"

# --- the refusals of the plan
out=$(EN g1 --runtime fakeplain --option "$OPT" 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ] && grep -q 'name=fakeplain' <<<"$out" && ! grep -q '^plan token' <<<"$out"; } \
  && ok "a runtime that is not enabled for the project has no option to enable (runtime-not-enabled)" || no "not enabled: rc=$rc $out"
out=$(EN g1 --runtime fakeother --option "$OPT" 2>&1); tok2=$(tokof_ "$out")
EN g1 --runtime fakeother --option "$OPT" --plan "$tok2" --approved "$PHRASE" >/dev/null 2>&1
[ "$(opts_of g1)" = '{"local":{"fakeimg":["image_generation"],"fakeother":["image_generation"]}}' ] && ok "an extra runtime has its own list" || no "extra: $(opts_of g1)"
mkfake fakeno_opts 'del(.dispatch.run_config.options)'
out=$(EN g1 --runtime fakeimg --option nosuchopt 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'declares no option named nosuchopt' <<<"$out" && grep -q 'image_generation' <<<"$out" && ! grep -q '^plan token' <<<"$out"; } \
  && ok "an option the definition does not declare does not exist (exit 2, no token)" || no "undeclared: rc=$rc $out"
# a definition that provider check refuses has no plan: an empty phrase (grep -w "" matches anything), a missing phrase or set, a set outside the rule
for bad in '.phrase = ""' 'del(.phrase)' 'del(.set)' '.set = {"features": {"newkey": true}}' '.set = {"approval_policy": "on-request"}' '.set = {"web_search": "live"}' '.set = {"sandbox_workspace_write": {"exclude_slash_tmp": false}}'; do
  mkfake fakebad ".dispatch.run_config.options.image_generation |= ($bad)"
  mkproj g6 '{"local":"fakebad"}'
  out=$(EN g6 --runtime fakebad --option "$OPT" 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -q 'the definition of fakebad is not valid, so no plan is made for its option image_generation' <<<"$out" && ! grep -q '^plan token' <<<"$out" \
    && ! grep -q 'Traceback' <<<"$out" && [ "$(opts_of g6)" = '"none"' ]; } && ok "an option of a malformed definition has no plan, no token and no traceback ($bad)" || no "malformed ($bad): rc=$rc $out"
  EN g6 --runtime fakebad --option "$OPT" --plan 0000 --approved "anything at all" >"$T/o" 2>&1; rc=$?
  { [ "$rc" = 2 ] && [ "$(opts_of g6)" = '"none"' ]; } && ok "nor an approval, whatever the words ($bad)" || no "malformed approve ($bad): rc=$rc $(cat "$T/o")"
done
out=$(EN g1 --runtime fakeimg --option 'Bad Name' 2>&1); rc=$?
[ "$rc" = 2 ] && ok "a bad option name is a usage error (exit 2)" || no "bad name: rc=$rc $out"
mkproj g2 "$own"
out=$(EN g2 --runtime claude-code --option "$OPT" 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ]; } && ok "nor has a runtime the project never enabled" || no "claude-code: rc=$rc $out"

# the runtime itself cannot be disabled while an option of it is enabled (a runtime that is not enabled has none: the answers would be invalid)
out=$(DIS g1 --runtime fakeother 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'project g1 has run options enabled for the runtime fakeother (image_generation): disable them first (qargi provider disable g1 --runtime fakeother --option image_generation)' <<<"$out" \
  && ! grep -q '^plan token' <<<"$out" && [ "$(jq -c '.models.extra_runtimes' "$T/c/projects/g1.json")" = '{"local":["fakeother"]}' ]; } \
  && ok "disabling a runtime is refused, with no token, while an option of it is enabled" || no "disable runtime with options: rc=$rc $out"

# --- a profile selects among the enabled options; the disable is refused while one does
"$DA" project set g1 profiles.imgs '{"base":"worker","tier":"balanced","options":["image_generation"]}' >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -c .profiles.imgs.options "$T/c/projects/g1.json")" = '["image_generation"]' ]; } && ok "project set: a profile selects an option the project enabled (a plain set)" || no "set profile: rc=$rc $(cat "$T/o")"
out=$(DIS g1 --runtime fakeimg --option "$OPT" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'profile imgs of project g1 selects the option image_generation: take it out of profiles.NAME.options first' <<<"$out" && ! grep -q '^plan token' <<<"$out" \
  && [ "$(opts_of g1)" = '{"local":{"fakeimg":["image_generation"],"fakeother":["image_generation"]}}' ]; } \
  && ok "disable is refused while a profile selects the option, and stores nothing" || no "disable while selected: rc=$rc $out"
"$DA" project set g1 profiles.imgs.options '[]' >/dev/null 2>&1
out=$(DIS g1 --runtime fakeimg --option "$OPT" 2>&1); rc=$?; tok=$(tokof_ "$out")
{ [ "$rc" = 0 ] && [ -n "$tok" ] && grep -q '^disable run option image_generation of runtime fakeimg for project g1 (models.run_options.local.fakeimg)$' <<<"$out" \
  && grep -q 'becomes \[\]' <<<"$out" && ! grep -q 'approval words must contain' <<<"$out"; } && ok "the disable plan shows what the list becomes and names no phrase" || no "disable plan: rc=$rc $out"
DIS g1 --runtime fakeimg --option "$OPT" --plan "$tok" --approved "stop it" >"$T/o" 2>"$T/e"; rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -c '.models.run_options.local.fakeimg' "$T/c/projects/g1.json")" = '[]' ] && [ "$(nlines disable-option)" = 1 ]; } \
  && ok "disable applies with no phrase and leaves one audit line, provider:disable-option" || no "disable: rc=$rc $(cat "$T/e")"
"$DA" project validate g1 >/dev/null 2>&1 && ok "an empty list stays valid" || no "validate after disable"
out=$(DIS g1 --runtime fakeimg --option "$OPT" 2>&1)
grep -q 'nothing to do: the option image_generation of fakeimg is not enabled for g1' <<<"$out" && ok "disabling what is not enabled says so" || no "disable twice: $out"

# --- the answer is gated: no project verb stores it, an archive may drop an entry and never add one, and a member never runs the verb
mkproj g3 "$own"
cp "$T/c/projects/g3.json" "$T/before.json"
"$DA" project set g3 models.run_options.local.fakeimg '["image_generation"]' >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider enable PROJECT --runtime NAME --option OPTION' "$T/o" && cmp -s "$T/before.json" "$T/c/projects/g3.json"; } && ok "project set refuses models.run_options and names the verb" || no "project set: rc=$rc $(cat "$T/o")"
"$DA" project set g3 models '{"provider":{"local":"fakeimg"},"run_options":{"local":{"fakeimg":["image_generation"]}}}' >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 2 ] && cmp -s "$T/before.json" "$T/c/projects/g3.json"; } && ok "nor as a key of a whole models object" || no "project set models: rc=$rc $(cat "$T/o")"
jq '.models.run_options = {local: {fakeimg: ["image_generation"]}}' "$T/before.json" > "$T/new.json"
"$DA" project init g3 --answers "$T/new.json" --force >"$T/o" 2>&1; rc=$?
{ [ "$rc" != 0 ] && cmp -s "$T/before.json" "$T/c/projects/g3.json"; } && ok "project init --answers does not add it either" || no "project init: rc=$rc $(cat "$T/o")"
python3 -I "$TOOL/lib/gated_answers.py" store g3 models.run_options.local '{}' --conf "$T/c" >/dev/null 2>&1 && no "gated_answers stored a path it was not given" \
  || ok "gated_answers stores models.run_options.local.RUNTIME, models.run_options.declared.RUNTIME and no other path of it"
python3 -I "$TOOL/lib/gated_answers.py" store g3 models.run_options.declared '{}' --conf "$T/c" >/dev/null 2>&1 && no "gated_answers stored the whole declared object" || ok "(nor the whole declared object)"
python3 -I "$TOOL/lib/gated_answers.py" store g3 models.run_options.local.fakeimg '["image_generation"]' --conf "$T/c" >/dev/null 2>&1 && [ "$(opts_of g3)" = '{"local":{"fakeimg":["image_generation"]}}' ] \
  && ok "gated_answers stores it for the verb that passed the plan token" || no "gated_answers: $(opts_of g3)"
out=$(cd "$T" && "$DA" project unset g3 models.run_options 2>&1); rc=$?      # not from inside a run directory: unset is the lead's verb, and a member run is refused before the gate is asked
{ [ "$rc" = 2 ] && grep -q 'models.run_options is not removed with project unset: it changes what an agent may run on' <<<"$out" && grep -q 'qargi provider enable PROJECT --runtime NAME --option OPT' <<<"$out" \
  && [ "$(opts_of g3)" = '{"local":{"fakeimg":["image_generation"]}}' ]; } && ok "project unset refuses it too, with the gate's message" || no "unset: rc=$rc $out"

# an init file that drops an option of a runtime only narrows what is stored (it is accepted), and one that adds an option or a runtime is refused
mkproj g4 "$own" '["fakeother"]'
ro_store g4 models.run_options.local.fakeimg '["image_generation","second_opt"]' && ro_store g4 models.run_options.local.fakeother '["image_generation"]' \
  && ro_dig g4 fakeimg && ro_dig g4 fakeother || no "could not store the options of g4"
cp "$T/c/projects/g4.json" "$T/before4.json"
jq '.models.run_options.local.fakeimg = ["image_generation"]' "$T/before4.json" > "$T/new4.json"
"$DA" project init g4 --answers "$T/new4.json" --force >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 0 ] && [ "$(opts_of g4)" = '{"local":{"fakeimg":["image_generation"],"fakeother":["image_generation"]}}' ]; } \
  && ok "project init --answers that drops one option of a runtime is accepted: it only narrows" || no "init drop an option: rc=$rc $(cat "$T/o")"
cp "$T/before4.json" "$T/c/projects/g4.json"
jq '.models.run_options.local.fakeimg = ["second_opt", "image_generation"]' "$T/before4.json" > "$T/new4.json"
"$DA" project init g4 --answers "$T/new4.json" --force >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -c .models.run_options.local.fakeimg "$T/c/projects/g4.json")" = '["second_opt","image_generation"]' ]; } \
  && ok "the same options in another order are no change: the list is compared as a set" || no "init reorder: rc=$rc $(cat "$T/o")"
cp "$T/before4.json" "$T/c/projects/g4.json"
jq '.models.run_options.local.fakeimg += ["third_opt"]' "$T/before4.json" > "$T/new4.json"
"$DA" project init g4 --answers "$T/new4.json" --force >"$T/o" 2>&1; rc=$?
{ [ "$rc" != 0 ] && grep -q 'models.run_options' "$T/o" && grep -q 'qargi provider enable PROJECT --runtime NAME --option OPT' "$T/o" && cmp -s "$T/before4.json" "$T/c/projects/g4.json"; } \
  && ok "project init --answers that adds an option is refused, and the message names provider enable PROJECT --runtime NAME --option OPT" || no "init add an option: rc=$rc $(cat "$T/o")"
jq '.models.run_options.declared.fakeimg.third_opt = ("a" * 64)' "$T/before4.json" > "$T/new4.json"
"$DA" project init g4 --answers "$T/new4.json" --force >"$T/o" 2>&1; rc=$?
{ [ "$rc" != 0 ] && grep -q 'models.run_options' "$T/o" && cmp -s "$T/before4.json" "$T/c/projects/g4.json"; } \
  && ok "nor does a file that adds the digest of an approval: an approval is made by the verb" || no "init add a digest: rc=$rc $(cat "$T/o")"

# --- project validate: the shape of the answer, and what a profile may select
mkproj v1 "$own" null '{"p":{"base":"worker","options":["image_generation"]}}'
out=$("$DA" project validate v1 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'profiles.p.options: image_generation is not enabled for the runtime fakeimg of this project (qargi provider enable PROJECT --runtime fakeimg --option image_generation)' <<<"$out"; } \
  && ok "validate: a profile that selects an option the project did not enable is refused" || no "validate not enabled: rc=$rc $out"
mkproj v2 "$own" null '{"p":{"base":"reviewer","options":["image_generation"]}}'
jq '.models.run_options = {local: {fakeimg: ["image_generation"]}}' "$T/c/projects/v2.json" > "$T/v2.json" && mv "$T/v2.json" "$T/c/projects/v2.json"
out=$("$DA" project validate v2 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'profiles.p.options: the profile is on the base reviewer, a read-only run, which never gets a run option' <<<"$out"; } \
  && ok "validate: a profile whose base is reviewer is refused, though the option is enabled" || no "validate reviewer: rc=$rc $out"
mkproj v3 "$own" null '{"p":{"base":"worker","options":["image_generation","image_generation"]},"q":{"base":"worker","options":"image_generation"},"r":{"base":"worker","options":["Bad"]},"ok":{"base":"worker","options":[]}}'
jq '.models.run_options = {local: {fakeimg: ["image_generation"]}}' "$T/c/projects/v3.json" > "$T/v3.json" && mv "$T/v3.json" "$T/c/projects/v3.json"
out=$("$DA" project validate v3 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'profiles.p.options: a list of distinct option names' <<<"$out" && grep -q 'profiles.q.options: a list of distinct option names' <<<"$out" \
  && grep -q 'profiles.r.options: a list of distinct option names' <<<"$out" && ! grep -q 'profiles.ok' <<<"$out"; } \
  && ok "validate: options is a list of distinct option names (an empty one selects none)" || no "validate shape: rc=$rc $out"
mkproj v4 "$own"
jq '.models.run_options = {local: {fakecx: ["image_generation"], fakeimg: "image_generation"}, cloud: {x: []}}' "$T/c/projects/v4.json" > "$T/v4.json" && mv "$T/v4.json" "$T/c/projects/v4.json"
out=$("$DA" project validate v4 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'models.run_options.local.fakecx: fakecx is not enabled for this project' <<<"$out" && grep -q 'models.run_options.local.fakeimg: a list of option names' <<<"$out" \
  && grep -q 'models.run_options.cloud: not a surface with run options (only local)' <<<"$out"; } && ok "validate: the shape of models.run_options, and the runtime must be enabled for the project" || no "validate run_options: rc=$rc $out"
mkproj v5 "$own"
jq '.models.run_options = {local: {fakeimg: ["image_generation", "nosuchopt"]}}' "$T/c/projects/v5.json" > "$T/v5.json" && mv "$T/v5.json" "$T/c/projects/v5.json"
out=$("$DA" project validate v5 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^finding: models.run_options.local.fakeimg 'nosuchopt' is not an option the definition of fakeimg declares" <<<"$out" \
  && grep -q "^finding: models.run_options.local.fakeimg 'image_generation': the option image_generation of the runtime fakeimg has no recorded approval of its declaration" <<<"$out"; } \
  && ok "validate: an option the definition no longer declares is a finding, and so is an enabled one with no recorded approval of its declaration" || no "validate finding: rc=$rc $out"
ro_dig v5 fakeimg
out=$("$DA" project validate v5 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "'nosuchopt' is not an option" <<<"$out" && ! grep -q "'image_generation'" <<<"$out"; } \
  && ok "validate: with the digest of the approved declaration recorded, the declared option is no finding" || no "validate finding with digest: rc=$rc $out"
jq '.models.run_options.declared = {fakeimg: {image_generation: "nothex"}}' "$T/c/projects/v5.json" > "$T/v5.json" && mv "$T/v5.json" "$T/c/projects/v5.json"
out=$("$DA" project validate v5 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'models.run_options.declared: an object like {RUNTIME: {OPTION: sha256 of the declaration the owner approved}}' <<<"$out"; } \
  && ok "validate: models.run_options.declared is an object of runtimes with the sha256 of each option" || no "validate declared shape: rc=$rc $out"

# --- prepare, dry run and run: a profile that selects the option gets it, nothing else does
mkproj r1 "$own" null "$PROFILES"
ro_set r1 fakeimg '["image_generation"]' || no "could not enable the option of r1"
prep() { # PROJECT ARGS...: local prepare in the project's repository: PREP (standard error too), PREP_RC, RUN
  local p=$1; shift
  PREP=$("$DA" local prepare --repo "$T/repo-$p" --base main --scratch "$T/scr" "$@" 2>&1); PREP_RC=$?
  PREP=$(grep -v '^qargi: warning: --scratch .* is on a tmpfs' <<<"$PREP")     # the suite may run under a tmpfs
  RUN=$(sed -n 's/^RUN=//p' <<<"$PREP")
  [ -z "$RUN" ] || printf 'TASK: write a file\nDONE: true\n' > "$RUN/task.md"
}
line() { sed -n "s/^$1=//p" <<<"$PREP" | head -1; }
toml_json() { python3 -I -c 'import json, sys, tomllib; print(json.dumps(tomllib.load(open(sys.argv[1], "rb")), sort_keys=True, separators=(",", ":")))' "$1"; }
BASE=$(jq -cS .dispatch.run_config.baseline "$SRC/lib/providers/codex.json")
WANT=$(jq -cS '.features.image_generation = true' <<<"$BASE")
prep r1 --slug o1 --profile imgs
{ [ "$PREP_RC" = 0 ] && [ "$(line RUN_OPTIONS)" = 'image_generation (hosted, outside the sandbox, may spend)' ] && [ "$(line PROFILE)" = imgs ]; } \
  && ok "prepare: RUN_OPTIONS= names the option and what it opens, only for the profile that selects it" || no "prepare with option: rc=$PREP_RC $PREP"
RUN1=$RUN
out=$("$DA" local run "$RUN1" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qx "RUN_CONFIG_OPTIONS={\"image_generation\":{\"features\":{\"image_generation\":true}}}" <<<"$out" && grep -qx "RUN_CONFIG_BASELINE=$BASE" <<<"$out"; } \
  && ok "dry run: RUN_CONFIG_OPTIONS= shows what the option applies, RUN_CONFIG_BASELINE= is the definition's baseline as it is" || no "dry run: rc=$rc $out"
{ [ ! -e "$RUN1/home/.codex/config.toml" ] && [ ! -e "$RUN1/dispatch.json" ]; } && ok "a dry run writes nothing" || no "dry run wrote"
out=$("$DA" local run "$RUN1" 2>&1); rc=$?
CFG=$RUN1/home/.codex/config.toml
{ [ "$rc" = 0 ] && grep -q '^OUTCOME=ok' <<<"$out" && grep -qx 'RUN_OPTIONS=image_generation (hosted, outside the sandbox, may spend)' <<<"$out"; } \
  && ok "run: the outcome is ok and RUN_OPTIONS= is printed" || no "run: rc=$rc $out"
{ [ "$(toml_json "$CFG")" = "$WANT" ] && [ "$(stat -c %a "$CFG")" = 600 ]; } \
  && ok "run config: the baseline with features.image_generation true and nothing else changed (mode 600)" || no "run config: $(toml_json "$CFG" 2>&1)"
jq -e --argjson b "$BASE" '.run_config.options == ["image_generation"] and .run_config.baseline == $b and .run_config.baseline.features.image_generation == false' "$RUN1/dispatch.json" >/dev/null \
  && ok "dispatch.json: run_config.options names the option, run_config.baseline stays the definition's" || no "dispatch.json: $(jq -c .run_config "$RUN1/dispatch.json")"
# the same project's other profile, and a read-only run, get the baseline alone and no line
prep r1 --slug o2 --profile plain
{ [ "$PREP_RC" = 0 ] && ! grep -q 'RUN_OPTIONS' <<<"$PREP"; } && ok "prepare: a profile that selects none prints no RUN_OPTIONS=, though the project enabled the option" || no "prepare plain: rc=$PREP_RC $PREP"
RUN2=$RUN
out=$("$DA" local run "$RUN2" --dry-run 2>&1); ! grep -q 'RUN_CONFIG_OPTIONS' <<<"$out" && ok "dry run: no RUN_CONFIG_OPTIONS= either" || no "dry plain: $out"
out=$("$DA" local run "$RUN2" 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q 'RUN_OPTIONS' <<<"$out" && [ "$(toml_json "$RUN2/home/.codex/config.toml")" = "$(jq -cS . <<<"$BASE")" ] && ! jq -e '.run_config | has("options")' "$RUN2/dispatch.json" >/dev/null; } \
  && ok "run config: the other profile gets the baseline alone, dispatch.json has no options key, and the output no line" || no "plain run: rc=$rc $out"
prep r1 --slug o3 --role review
{ [ "$PREP_RC" = 0 ] && ! grep -q 'RUN_OPTIONS' <<<"$PREP"; } && ok "prepare: a read-only run gets none" || no "prepare review: rc=$PREP_RC $PREP"
RUN3=$RUN
out=$("$DA" local run "$RUN3" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(toml_json "$RUN3/home/.codex/config.toml")" = "$(jq -cS . <<<"$BASE")" ]; } && ok "run config: a read-only run gets the baseline alone" || no "review run: rc=$rc $out"

# --- a read-only run with an option is refused at prepare, whatever the profile says, before anything is made
made() { { ls "$T/scr"; ls -d "$T"/qargi-run.* 2>/dev/null; } | wc -l; }
mkproj c1 "$own" null '{"rev":{"base":"reviewer","tier":"balanced","options":["image_generation"]},"imgs":{"base":"worker","tier":"balanced","options":["image_generation"]}}'
# project validate refuses this profile, so the answers are edited by hand: prepare holds the rule whatever the file says
jq '.models.run_options = {local: {fakeimg: ["image_generation"]}}' "$T/c/projects/c1.json" > "$T/c1.json" && mv "$T/c1.json" "$T/c/projects/c1.json"
"$DA" project validate c1 2>&1 | grep -q 'the profile is on the base reviewer' && ok "(validate does refuse that profile)" || no "validate c1"
before=$(made)
prep c1 --slug c1 --role review --profile rev
{ [ "$PREP_RC" = 1 ] && [ "$(refusal_code "$PREP")" = runtime-option-class ] && grep -q 'refused \[runtime-option-class\] the option image_generation of the runtime fakeimg is for write runs, and this run is read-only' <<<"$PREP" \
  && [ "$(made)" = "$before" ]; } && ok "runtime-option-class: a read-only run whose profile selects an option is refused at prepare (exit 1), and nothing is made" || no "read-only with option: rc=$PREP_RC made=$(made)/$before $PREP"
prep c1 --slug c2 --role review
{ [ "$PREP_RC" = 0 ] && ! grep -q 'RUN_OPTIONS' <<<"$PREP"; } && ok "the same project's review profile with no option is prepared" || no "review of c1: rc=$PREP_RC $PREP"
# a profile that selects what the project did not enable, or the definition does not declare, is refused too
mkproj c2 "$own" null "$PROFILES"
before=$(made)
prep c2 --slug c3 --profile imgs
{ [ "$PREP_RC" = 2 ] && grep -q 'the profile imgs selects the option image_generation, which project c2 has not enabled for the runtime fakeimg' <<<"$PREP" && [ "$(made)" = "$before" ]; } \
  && ok "prepare: a profile that selects an option the project did not enable is refused (exit 2), and nothing is made" || no "not enabled: rc=$PREP_RC $PREP"
mkproj c3 '{"local":"fakeplain"}' null "$PROFILES"
ro_store c3 models.run_options.local.fakeplain '["image_generation"]' || no "could not store the option of c3"
prep c3 --slug c4 --profile imgs
{ [ "$PREP_RC" = 2 ] && grep -q 'the definition of the runtime fakeplain declares no option image_generation' <<<"$PREP"; } \
  && ok "prepare: an option the definition does not declare does not exist" || no "undeclared at prepare: rc=$PREP_RC $PREP"

# --- drift: the definition's option, the project's list and the profile key each bind the request; a change after prepare is refused at run
drift() { # LABEL: the run in RUN was prepared; it must be refused with a re-prepare and leave no trace
  local out rc
  out=$("$DA" local run "$RUN" 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -q 're-prepare' <<<"$out" && [ ! -e "$RUN/dispatch.json" ] && [ ! -e "$RUN/home/.codex/config.toml" ]; } && ok "drift: $1" || no "drift $1: rc=$rc $out"
}
mkproj d1 "$own" null "$PROFILES"
prep d1 --slug d1a --profile plain
ro_set d1 fakeimg '["image_generation"]'
drift "the project enabling an option after prepare (the list changed)"
prep d1 --slug d1b --profile imgs
{ [ "$PREP_RC" = 0 ] && [ -n "$(line RUN_OPTIONS)" ]; } || no "d1b: rc=$PREP_RC $PREP"
# the verb that stores the list refuses an answers file in which a profile selects what is not enabled, so the file is edited by hand
jq '.models.run_options.local.fakeimg = []' "$T/c/projects/d1.json" > "$T/d1.json" && mv "$T/d1.json" "$T/c/projects/d1.json"
drift "the project dropping the option while the profile still selects it (the list alone changed)"
jq '.models.run_options.local.fakeimg = ["image_generation"]' "$T/c/projects/d1.json" > "$T/d1.json" && mv "$T/d1.json" "$T/c/projects/d1.json"
prep d1 --slug d1b2 --profile imgs
{ [ "$PREP_RC" = 0 ] && [ -n "$(line RUN_OPTIONS)" ]; } || no "d1b2: rc=$PREP_RC $PREP"
jq '.profiles.imgs.options = []' "$T/c/projects/d1.json" > "$T/d1.json" && mv "$T/d1.json" "$T/c/projects/d1.json"
drift "the profile dropping its key while the project keeps the option enabled (the selection alone changed)"
jq '.profiles.imgs.options = ["image_generation"]' "$T/c/projects/d1.json" > "$T/d1.json" && mv "$T/d1.json" "$T/c/projects/d1.json"
prep d1 --slug d1c --profile plain
jq '.profiles.plain.options = ["image_generation"]' "$T/c/projects/d1.json" > "$T/d1.json" && mv "$T/d1.json" "$T/c/projects/d1.json"
drift "the profile gaining the key after prepare (the selection changed)"
jq '.profiles.plain |= del(.options)' "$T/c/projects/d1.json" > "$T/d1.json" && mv "$T/d1.json" "$T/c/projects/d1.json"
prep d1 --slug d1d --profile imgs
ro_set d1 fakeimg '["image_generation"]'
jq '.dispatch.run_config.options.image_generation.phrase = "hosted image generation is edited"' "$TOOL/lib/providers/fakeimg.json" > "$T/fakeimg.json" \
  && mv "$T/fakeimg.json" "$TOOL/lib/providers/fakeimg.json"
python3 -I "$TOOL/lib/provider.py" check fakeimg >/dev/null 2>&1 || no "the edited definition is no longer valid"
drift "the definition's option edited after prepare: its phrase, which is part of the hashed definition"
out=$("$DA" local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 're-prepare' <<<"$out"; } && ok "drift: a dry run refuses as well" || no "drift dry: rc=$rc $out"

# --- the approval binds the declaration of the option: a definition that changes it after the owner approved it is refused when a run is prepared
mkfake fakebind
mkproj b1 '{"local":"fakebind"}' null "$PROFILES"
out=$(EN b1 --runtime fakebind --option "$OPT" 2>&1); tok=$(tokof_ "$out")
grep -q '^the approval binds this declaration (digest [0-9a-f]\{16\}, kept at models.run_options.declared.fakebind.image_generation)' <<<"$out" && ok "plan: it says that the approval binds the declaration, with its digest" || no "binding plan line: $out"
EN b1 --runtime fakebind --option "$OPT" --plan "$tok" --approved "$PHRASE" >/dev/null 2>&1
WANTD=$(python3 -I - "$TOOL/lib" fakebind <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import provider as P
print(P.option_digest(P.declared_options(P.composed(sys.argv[2], "local"))["image_generation"]))
PY
)
{ [ "$(jq -r '.models.run_options.declared.fakebind.image_generation' "$T/c/projects/b1.json")" = "$WANTD" ] && [ "${#WANTD}" = 64 ] && [ "$(jq -c '.models.run_options.local' "$T/c/projects/b1.json")" = '{"fakebind":["image_generation"]}' ]; } \
  && ok "binding: the enable stores the digest of the declaration it showed, with the list" || no "binding stored: $(digs_of b1) $WANTD"
"$DA" project validate b1 >/dev/null 2>&1 && ok "binding: the stored answers stay valid" || no "validate b1"
prep b1 --slug b1a --profile imgs
{ [ "$PREP_RC" = 0 ] && [ -n "$(line RUN_OPTIONS)" ]; } && ok "binding: a run of a profile that selects the approved option is prepared" || no "b1a: rc=$PREP_RC $PREP"
jq '.dispatch.run_config.options.image_generation.note = "the option now also does something else"' "$TOOL/lib/providers/fakebind.json" > "$T/fakebind.json" \
  && mv "$T/fakebind.json" "$TOOL/lib/providers/fakebind.json"
python3 -I "$TOOL/lib/provider.py" check fakebind >/dev/null 2>&1 || no "the edited fakebind is no longer valid"
prep b1 --slug b1b --profile imgs
{ [ "$PREP_RC" = 2 ] && grep -q 'the definition of the runtime fakebind changed the option image_generation since the owner approved it' <<<"$PREP" && grep -q 'approve it again' <<<"$PREP"; } \
  && ok "binding: the option's text changed after the approval (the plan kept), so prepare is refused (exit 2), naming the way to approve it again" || no "binding drift: rc=$PREP_RC $PREP"
out=$("$DA" project validate b1 2>&1)
grep -q "^finding: models.run_options.local.fakebind 'image_generation': the definition of the runtime fakebind changed the option image_generation since the owner approved it" <<<"$out" \
  && ok "binding: project validate says so as a finding" || no "binding finding: $out"
prep b1 --slug b1c --profile plain
{ [ "$PREP_RC" = 0 ] && ! grep -q RUN_OPTIONS <<<"$PREP"; } && ok "binding: a profile that selects no option is not held up by it" || no "b1c: rc=$PREP_RC $PREP"
# a disable takes the digest with the option, and approving it again records the declaration as it now is
"$DA" project set b1 profiles.imgs.options '[]' >/dev/null 2>&1
out=$(DIS b1 --runtime fakebind --option "$OPT" 2>&1); tok=$(tokof_ "$out")
DIS b1 --runtime fakebind --option "$OPT" --plan "$tok" --approved "stop it" >/dev/null 2>&1
{ [ "$(digs_of b1)" = '{"fakebind":{}}' ] && [ "$(opts_of b1)" = '{"local":{"fakebind":[]}}' ]; } && ok "binding: a disable takes the digest with the option" || no "binding disable: $(digs_of b1) $(opts_of b1)"
out=$(EN b1 --runtime fakebind --option "$OPT" 2>&1); tok=$(tokof_ "$out")
grep -q 'digest' <<<"$out" && ! grep -q "digest ${WANTD:0:16}" <<<"$out" && ok "binding: the plan of the changed definition shows another digest" || no "binding new digest: $out"
EN b1 --runtime fakebind --option "$OPT" --plan "$tok" --approved "$PHRASE" >/dev/null 2>&1
"$DA" project set b1 profiles.imgs.options '["image_generation"]' >/dev/null 2>&1
prep b1 --slug b1d --profile imgs
{ [ "$PREP_RC" = 0 ] && [ -n "$(line RUN_OPTIONS)" ]; } && ok "binding: approved again as it now is, a run is prepared" || no "b1d: rc=$PREP_RC $PREP"
mkproj b2 '{"local":"fakebind"}' null "$PROFILES"
ro_store b2 models.run_options.local.fakebind '["image_generation"]'
prep b2 --slug b2a --profile imgs
{ [ "$PREP_RC" = 2 ] && grep -q 'has no recorded approval of its declaration' <<<"$PREP"; } \
  && ok "binding: an option enabled with no recorded digest is refused at prepare (exit 2), as an approval that cannot be shown" || no "b2a: rc=$PREP_RC $PREP"
{ grep -q 'take the option out of each profile that selects it' <<<"$PREP" && grep -q 'then select it in the profile again' <<<"$PREP"; } \
  && ok "binding: the refusal names the whole way (the profile first: a disable is refused while a profile selects the option)" || no "b2a remedy: $PREP"
# and the way it names works as written: the profile lets go, disable, enable, the profile selects it again
"$DA" project set b2 profiles.imgs.options '[]' >/dev/null 2>&1
out=$(DIS b2 --runtime fakebind --option "$OPT" 2>&1); tok=$(tokof_ "$out")
DIS b2 --runtime fakebind --option "$OPT" --plan "$tok" --approved "stop it" >/dev/null 2>&1
out=$(EN b2 --runtime fakebind --option "$OPT" 2>&1); tok=$(tokof_ "$out")
EN b2 --runtime fakebind --option "$OPT" --plan "$tok" --approved "$PHRASE" >/dev/null 2>&1
"$DA" project set b2 profiles.imgs.options '["image_generation"]' >/dev/null 2>&1
prep b2 --slug b2b --profile imgs
{ [ "$PREP_RC" = 0 ] && [ -n "$(line RUN_OPTIONS)" ]; } && ok "binding: the four steps the refusal names approve it again, and a run is prepared" || no "b2b: rc=$PREP_RC $PREP"

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "FAILED"; exit 1; }
