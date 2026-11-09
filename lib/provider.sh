#!/usr/bin/env bash
# qargi provider accept: record that you accept a provider surface that has no read-only barrier (lib/provider.py runs this
# for the verb; the other provider verbs are Python).
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
[ -n "$NOBAR" ] || die "say what you accept: --no-barrier (running a read-only role on $SURFACE without a read-only barrier). $usage"
[ -n "$ASKED" ] || die "--asked \"<your words>\" is required: they are recorded as the reason. $usage"
[ -z "$APPROVED" ] || [ -n "$PLAN_ARG" ] || usage_die "--approved needs --plan TOKEN, the token the plan printed"

[ -n "$PROJ" ] || PROJ=$(python3 -I "$here/help.py" infer)
# the barrier of the project's runtime as composed with the extensions the project enabled: one an extension provides and has verified counts
state=$(python3 -I "$here/provider.py" effective "$NAME" "$SURFACE" read_only_barrier ${PROJ:+--project "$PROJ"}) || exit 1
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

token=$(printf '%s\n%s\n%s\n%s\n' "$NAME" "$SURFACE" "$PROJ" "$ASKED" | plan_token)
if [ -z "$APPROVED" ] || [ -z "$PLAN_ARG" ]; then
  echo "accept: $NAME has no read-only barrier on $SURFACE"
  echo "record in the answers of project $PROJ: models.accept_no_barrier.$SURFACE = {by: $(id -un), at: <now>, reason: \"$ASKED\"}"
  echo "effect: the review role and every other read-only role may then run on $NAME $SURFACE with nothing that stops it from writing; the audit log gets a line"
  echo "plan token: $token   (apply with: --plan $token --approved \"...\")"
  exit 0
fi

QARGI_NESTED='' need_plan "$token"
rec=$(jq -nc --arg b "$(id -un)" --arg t "$(now)" --arg r "$ASKED" '{by: $b, at: $t, reason: $r}')
audit_log provider:accept "$NAME $SURFACE $PROJ"
python3 -I "$here/gated_answers.py" store "$PROJ" "models.accept_no_barrier.$SURFACE" "$rec" --conf "$DA_CONF" >/dev/null || die "could not record it in the answers of $PROJ; nothing changed"
echo "project $PROJ accepts $NAME on $SURFACE without a read-only barrier (approved: $APPROVED)"
