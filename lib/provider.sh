#!/usr/bin/env bash
# qargi provider accept: record that you accept a provider surface that has no read-only barrier, and qargi provider enable|disable PROJECT
# --runtime NAME: allow or stop an extra runtime for a project (lib/provider.py runs this for the two verbs; the other provider verbs are Python).
#
#   provider.sh enable|disable PROJECT --runtime NAME [--asked "<your words>"]                      plan: what the runtime is, what it reads, what it needs, a token
#   provider.sh enable|disable PROJECT --runtime NAME [--asked W] --plan TOKEN --approved "<the owner's go-ahead>"
#
# Applied, an enable writes models.extra_runtimes.local of the project's stored answers (lib/gated_answers.py) and one line to the audit log. The plan
# comes from lib/provider.py (runtime-info). A runtime that does not confine reads (dispatch.reads of its definition) is approved only by words that
# contain "reads are not confined", as words (letter case and runs of blanks ignored; runtime-reads-unacknowledged otherwise, and the token stays good); disable asks for no phrase.
#
#   provider.sh accept NAME --surface S --no-barrier --asked "<your words>" [--project P]       plan: what would be recorded, and a token
#   provider.sh accept NAME --surface S --no-barrier --asked "<your words>" [--project P] --plan TOKEN --approved "<your go-ahead>"
#
# Applied, it writes models.accept_no_barrier.S = {by, at, reason} to the project's stored answers (lib/gated_answers.py, which
# validates them; qargi project set refuses the key) and one line to the audit log. The reason is the --asked words. The enforcement points (qargi agent add for a
# member that only reviews, provision for a read-only role, session start, local prepare) refuse a read-only role on a surface
# whose barrier is not supported until this is recorded. Members and agents cannot use it (the guard refuses the verb).
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")
usage='usage: qargi provider accept NAME --surface local|cloud --no-barrier --asked "<your words>" [--project P] [--plan TOKEN --approved "<your go-ahead>"]'
verb=${1:-}; shift || true
# option_verb: the gate of a run option of a runtime the project has enabled (provider enable|disable PROJECT --runtime NAME --option OPT), called by runtime_verb with
# its variables. The plan names what the option adds to the run's configuration file, that it runs outside the sandbox and may spend, and the words the owner's approval
# must contain (the phrase of the option's definition, as words); an approval without them is runtime-option-unacknowledged and the token stays good. A disable asks for no
# phrase and is refused while a profile selects the option. Stored at models.run_options.local.NAME through lib/gated_answers.py, with one audit line.
option_verb() {
  local path
  printf '%s' "$OPT" | grep -Eq '^[a-z][a-z0-9_]{0,40}$' || usage_die "--option needs an option name of the runtime's definition (lower-case letters, digits and _): $rusage"
  info=$(pymod provider option-info "$PROJ" "$NAME" "$OPT" "$v" </dev/null) || exit $?
  if [ "$(jq -r .not_enabled <<<"$info")" = true ]; then refuse runtime-not-enabled name="$NAME"; fi
  nothing=$(jq -r '.nothing // empty' <<<"$info")
  [ -z "$nothing" ] || { echo "$nothing"; exit 0; }
  refusal=$(jq -r '.refusal // empty' <<<"$info")
  if [ "$(jq '.lines | length' <<<"$info")" = 0 ]; then echo "qargi: $refusal; nothing was changed" >&2; exit 2; fi
  plan=$(jq -r '.lines[]' <<<"$info")
  printf '%s\n' "$plan"
  if [ -n "$refusal" ]; then echo "qargi: $refusal; nothing was changed" >&2; exit 2; fi
  new=$(jq -c .new <<<"$info")
  token=$(printf '%s\n' "$plan" | plan_token)
  if [ -z "$APPROVED" ]; then
    echo "plan token: $token   (apply with: --plan $token --approved \"<the owner's words>\")"
    exit 0
  fi
  need_plan "$token"
  if [ "$(jq -r .needs_phrase <<<"$info")" = true ]; then
    phrase=$(jq -r .phrase <<<"$info")
    norm=$(printf '%s' "$APPROVED" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ')
    if ! grep -qwF -- "$phrase" <<<"$norm"; then       # as words, as for the reads phrase
      refuse runtime-option-unacknowledged name="$NAME" option="$OPT"
    fi
  fi
  audit_log "provider:$v-option" "$PROJ runtime $NAME option $OPT $token"
  path="models.run_options.local.$NAME"
  python3 -I "$here/gated_answers.py" store "$PROJ" "$path" "$new" --conf "$DA_CONF" >/dev/null || fail "could not record it in the answers of $PROJ; nothing changed"
  echo "${v}d run option $OPT of runtime $NAME for project $PROJ (approved: $APPROVED)"
}
runtime_verb() { # enable|disable PROJECT --runtime NAME [--asked W] [--plan T --approved W]: the gate of an extra runtime
  local v=$1 PROJ='' NAME='' OPT='' ASKED='' APPROVED='' PLAN_ARG='' rusage info nothing verdict plan refusal new token norm phrase
  rusage="usage: qargi provider $v PROJECT --runtime NAME [--option OPTION] [--asked \"<your words>\"] [--plan TOKEN --approved \"<the owner's go-ahead>\"]"
  shift
  while [ $# -gt 0 ]; do
    case $1 in
      --runtime) need_val "$1" $#; NAME=$2; shift 2;;
      --option) need_val "$1" $#; OPT=$2; shift 2;;
      --asked) need_val "$1" $#; ASKED=$2; shift 2;;
      --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
      --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;;
      -*) usage_die "unknown option $1";;
      *) [ -z "$PROJ" ] || usage_die "unexpected argument $1"; PROJ=$1; shift;;
    esac
  done
  [ -n "$PROJ" ] && [ -n "$NAME" ] || usage_die "$rusage"
  [ -z "$APPROVED" ] || [ -n "$PLAN_ARG" ] || usage_die "--approved needs --plan TOKEN, the token the plan printed"
  printf '%s' "$NAME" | grep -Eq '^[a-z][a-z0-9-]*$' || usage_die "--runtime needs a runtime name (lower-case letters, digits and -): $rusage"
  valid_project "$PROJ" && [ -f "$DA_CONF/projects/$PROJ.json" ] || fail "no stored answers for project '$PROJ' (qargi project list)"
  # shellcheck disable=SC2034  # refuse (lib.sh) names the verb and the project of its contract line from these
  PROJECT=$PROJ QARGI_VERB="provider $v"
  [ -z "$OPT" ] || { option_verb; return; }
  info=$(pymod provider runtime-info "$PROJ" "$NAME" "$v" </dev/null) || exit $?
  nothing=$(jq -r '.nothing // empty' <<<"$info")
  [ -z "$nothing" ] || { echo "$nothing"; exit 0; }
  verdict=$(jq -r .verdict <<<"$info")
  if [ "$verdict" != ok ]; then refuse runtime-unusable name="$NAME" why="$verdict"; fi
  plan=$(jq -r '.lines[]' <<<"$info")
  printf '%s\n' "$plan"
  refusal=$(jq -r '.refusal // empty' <<<"$info")
  if [ -n "$refusal" ]; then echo "qargi: $refusal; nothing was changed" >&2; exit 2; fi
  new=$(jq -c .new <<<"$info")
  token=$(printf '%s\n' "$plan" | plan_token)
  if [ -z "$APPROVED" ]; then
    echo "plan token: $token   (apply with: --plan $token --approved \"<the owner's words>\")"
    exit 0
  fi
  need_plan "$token"
  if [ "$(jq -r .needs_phrase <<<"$info")" = true ]; then
    phrase=$(jq -r .phrase <<<"$info")
    norm=$(printf '%s' "$APPROVED" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ')
    if ! grep -qwF -- "$phrase" <<<"$norm"; then       # as words: "threads are not confined" does not carry "reads are not confined"
      refuse runtime-reads-unacknowledged name="$NAME"
    fi
  fi
  audit_log "provider:$v" "$PROJ runtime $NAME $token"
  python3 -I "$here/gated_answers.py" store "$PROJ" models.extra_runtimes.local "$new" --conf "$DA_CONF" >/dev/null || fail "could not record it in the answers of $PROJ; nothing changed"
  echo "${v}d runtime $NAME for project $PROJ (approved: $APPROVED)"
}
case $verb in enable|disable) runtime_verb "$verb" "$@"; exit 0;; esac
[ "$verb" = accept ] || usage_die "$usage"
NAME='' SURFACE='' NOBAR='' PROJ='' ASKED='' APPROVED='' PLAN_ARG=''
while [ $# -gt 0 ]; do
  case $1 in
    --surface) need_val "$1" $#; SURFACE=$2; shift 2;;
    --no-barrier) NOBAR=1; shift;;
    --project) need_val "$1" $#; PROJ=$2; shift 2;;
    --asked) need_val "$1" $#; ASKED=$2; shift 2;;
    --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;;
    -*) usage_die "unknown option $1";;
    *) [ -z "$NAME" ] || usage_die "unexpected argument $1"; NAME=$1; shift;;
  esac
done
[ -n "$NAME" ] && [ -n "$SURFACE" ] || usage_die "$usage"
[ -n "$NOBAR" ] || usage_die "say what you accept: --no-barrier (running a read-only role on $SURFACE without a read-only barrier). $usage"
[ -n "$ASKED" ] || usage_die "--asked \"<your words>\" is required: they are recorded as the reason. $usage"
[ -z "$APPROVED" ] || [ -n "$PLAN_ARG" ] || usage_die "--approved needs --plan TOKEN, the token the plan printed"

[ -n "$PROJ" ] || PROJ=$(pymod help infer)
# the barrier of the project's runtime as composed with the extensions the project enabled: one an extension provides and has verified counts
state=$(pymod provider effective "$NAME" "$SURFACE" read_only_barrier ${PROJ:+--project "$PROJ"}) || exit 1
[ -n "$PROJ" ] || usage_die "no project: give --project P (the project whose answers record the acceptance)"
valid_project "$PROJ" && [ -f "$DA_CONF/projects/$PROJ.json" ] || die "no stored answers for project '$PROJ' (qargi project list)"

if [ "$state" != no ]; then
  echo "nothing to accept: $NAME has a read-only barrier on $SURFACE ($state)"
  exit 0
fi
if rec=$(jq -ce --arg s "$SURFACE" '.models.accept_no_barrier[$s] // empty' "$DA_CONF/projects/$PROJ.json" 2>/dev/null) && [ -n "$rec" ]; then
  echo "nothing to do: project $PROJ accepted this already ($(jq -r '"by \(.by) at \(.at): \(.reason)"' <<<"$rec"))"
  exit 0
fi

token=$(printf '%s\n%s\n%s\n%s\n' "$NAME" "$SURFACE" "$PROJ" "$ASKED" | plan_token --basis "runtime:name surface:label project:name reason:name" --verb "provider accept" --target "$PROJ:$NAME $SURFACE")
if [ -z "$APPROVED" ] || [ -z "$PLAN_ARG" ]; then
  echo "accept: $NAME has no read-only barrier on $SURFACE"
  echo "record in the answers of project $PROJ: models.accept_no_barrier.$SURFACE = {by: $(id -un), at: <now>, reason: \"$ASKED\"}"
  echo "effect: the review role and every other read-only role may then run on $NAME $SURFACE with nothing that stops it from writing; the audit log gets a line"
  echo "plan token: $token   (apply with: --plan $token --approved \"...\")"
  exit 0
fi

need_plan "$token"
rec=$(jq -nc --arg b "$(id -un)" --arg t "$(now)" --arg r "$ASKED" '{by: $b, at: $t, reason: $r}')
audit_log provider:accept "$NAME $SURFACE $PROJ"
python3 -I "$here/gated_answers.py" store "$PROJ" "models.accept_no_barrier.$SURFACE" "$rec" --conf "$DA_CONF" >/dev/null || die "could not record it in the answers of $PROJ; nothing changed"
echo "project $PROJ accepts $NAME on $SURFACE without a read-only barrier (approved: $APPROVED)"
