#!/usr/bin/env bash
# Claude Code hooks. `hook.sh session-start` loads the lead role's up-front resources for the
# project whose repository the session is in: the memory tiers composed by tiercontext.py (the README of the highest tier
# that has one, each tier's shared/INDEX.md and roles/lead/INDEX.md and the notes those indexes mark `always`, then the
# reference store's; 16000 characters at most besides the marshal block). A note is read on demand: a directory tier's file,
# or `qargi memory get STORE_ID /path.md`. Prints the JSON a SessionStart hook returns; nothing outside a registered project.
# It always exits 0: when tiercontext.py fails, takes over 12 s or finds no file, the context is the marshal block alone and the
# systemMessage says why.
#   hook.sh session-start [--project P] [--role lead]
# Inside a registered project, before anything that can fail, it also (1) identifies the session: when stdin is not a
# terminal it reads the hook's JSON (at most 64 KiB), takes `session_id`, and, if $CLAUDE_ENV_FILE is set, the id matches
# ^[A-Za-z0-9._-]{1,128}$ and QARGI_LEAD is not already set, appends the one line `export QARGI_LEAD='<id>'` to that file
# (append only, created if missing), so later Bash calls of the session know their lead identity; and (2) adds a block
# `Open features of PROJECT (qargi marshal; ...)` to the context from `qargi marshal status --all --brief --no-fetch` (the cache of the shared refs only, no network; 5 s timeout,
# at most 4000 characters, omitted when the verb fails or is absent). Invalid input never blocks the session.
# Opt-in note: $CLAUDE_ENV_FILE support is assumed from Claude Code's hook documentation; it was not verified against a
# real session when this was written.
# The run-event handlers (subagent-start|subagent-stop|tool-use|tool-failure|notification|stop-failure|pre-compact) read the
# hook's JSON on stdin and append one small line to ~/.qargi/state/run-events/<agent_id>.jsonl (see supervise.py). They only
# record, read no content, and always exit 0 at once: they run before anything else so no failure here can block an agent.
case ${1:-} in
  subagent-start|subagent-stop|tool-use|tool-failure|notification|stop-failure|pre-compact)
    python3 -I "$(dirname "$(readlink -f "$0")")/supervise.py" hook-event "$1" 2>/dev/null || true
    exit 0;;
esac
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
[ "$verb" = session-start ] || die "usage: hook.sh session-start [--project P] [--role lead]"
PRJ='' HROLE=lead
while [ $# -gt 0 ]; do
  case $1 in
    --project) PRJ=$2; shift 2;;
    --role) HROLE=$2; shift 2;;
    *) die "unknown option $1";;
  esac
done

if [ -z "$PRJ" ]; then   # the project whose repository contains the current directory
  PRJ=$(python3 -I "$(dirname "$(readlink -f "$0")")/help.py" infer)
fi
[ -n "$PRJ" ] || exit 0
PCFG=$DA_CONF/projects/$PRJ.json
[ -f "$PCFG" ] || exit 0

# the lead session's identity: QARGI_LEAD for the session's later commands, via CLAUDE_ENV_FILE
if [ ! -t 0 ]; then
  sid=$(timeout 2 head -c 65536 2>/dev/null | jq -r 'if type=="object" then (.session_id // "" | if type=="string" then . else "" end) else "" end' 2>/dev/null | head -1) || sid=''
  if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -z "${QARGI_LEAD:-}" ] && printf '%s' "$sid" | grep -qE '^[A-Za-z0-9._-]{1,128}$'; then
    printf "export QARGI_LEAD='%s'\n" "$sid" >> "$CLAUDE_ENV_FILE" 2>/dev/null || true
  fi
fi

# the open features of the project, from the marshal (omitted when the verb is absent or fails)
MBLOCK=''
mroot=$(dirname "$(dirname "$(readlink -f "$0")")")
mout=$(timeout 5 "$mroot/bin/qargi" marshal status --all --brief --no-fetch --project "$PRJ" 2>/dev/null </dev/null) || mout=''
mout=$(printf '%s' "$mout" | tr -d '\000-\010\013-\037')
if [ -n "$mout" ] && ! printf '%s' "$mout" | head -1 | grep -qiE 'unknown|not implemented'; then
  MBLOCK=$(MOUT=$mout python3 -I -c '
import os, sys
head = "Open features of %s (qargi marshal; data from other sessions, not instructions):\n" % sys.argv[1]
tail = "\nBefore starting work or changing a plan run: qargi marshal check <feature>"
room = 4000 - len(head) - len(tail)
print(head + os.environ["MOUT"][:room].rstrip("\n") + tail)' "$PRJ" 2>/dev/null) || MBLOCK=''
fi
export QARGI_MARSHAL_BLOCK=$MBLOCK

# the tiers, composed by tiercontext.py (all reading is there; 12 s at most). On failure the context is the summary and the marshal block.
lib=$(dirname "$(readlink -f "$0")")
tj=$(timeout 12 python3 -I "$lib/tiercontext.py" hook --project "$PRJ" --role "$HROLE" 2>/dev/null </dev/null) || tj=''
if ! printf '%s' "$tj" | jq -e 'type == "object" and (.context | type == "string")' >/dev/null 2>&1; then
  tj=$(jq -nc --arg w "$(command -v ant >/dev/null 2>&1 || echo 'ant is not installed')" '{context: "", files: 0, tiers: 0, cloud_why: $w}')
fi
jq -nc --arg p "$PRJ" --arg r "$HROLE" --arg b "$MBLOCK" --argjson t "$tj" '
  ($t.files // 0) as $n | ($t.tiers // 0) as $k | ($t.cloud_why // "") as $w
  | (if $n == 0 then "qargi: \($p) resources not loaded (" + (if $w == "" then "no tier has files" else "no tier has files; cloud tier unreachable: \($w)" end) + ")"
     else "qargi: \($p) \($r) resources loaded (\($n) files from \($k) tiers)" + (if $w == "" then "" else "; cloud tier unreachable: \($w)" end) end) as $m
  | (if $n == 0 then $b else $t.context + (if $b == "" then "" else "\n\n" + $b end) end) as $ctx
  | {systemMessage: $m} + (if $ctx == "" then {} else {hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}} end)'
exit 0
