#!/usr/bin/env bash
# Shared helpers for the qargi skill. Registry and tracker live outside
# the repository, under the XDG config and state directories.
set -u

# QARGI_CONF / QARGI_STATE override the locations (for tests); do not
# redirect XDG_CONFIG_HOME instead, because the ant CLI keeps its login there.
DA_CONF=${QARGI_CONF:-${XDG_CONFIG_HOME:-$HOME/.config}/qargi}
DA_STATE=${QARGI_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/qargi}
REG=$DA_CONF/instances.json
TRK=$DA_STATE/sessions.json
export BETA=managed-agents-2026-04-01

mkdir -p "$DA_CONF" "$DA_STATE"
chmod 700 "$DA_CONF" "$DA_STATE"
for f in "$REG" "$TRK"; do
  [ -f "$f" ] || { echo '{}' > "$f"; chmod 600 "$f"; }
done

# Naming convention (see README): <project>-<role>-<component>. Project and role
# are single lower-case tokens (no dashes) so a name parses unambiguously; the
# role comes from a fixed list. Memory stores belong to the project:
# <project>-memory and <project>-reference. A session is named
# <project>-<role>-<task-slug>.
DA_ROLES=${QARGI_ROLES:-"dev review docs test"}
valid_project() { printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9]{0,23}$'; }
valid_role() { local r; for r in $DA_ROLES; do [ "$r" = "$1" ] && return 0; done; return 1; }
valid_slug() { printf '%s' "$1" | grep -Eq '^[a-z0-9][a-z0-9-]{0,40}$'; }
# split_instance NAME: sets PROJECT and ROLE, or dies with the rule.
split_instance() {
  PROJECT=${1%%-*}; ROLE=${1#*-}
  if [ "$PROJECT-$ROLE" != "$1" ] || ! valid_project "$PROJECT" || ! valid_role "$ROLE"; then
    die "'$1' is not a standard instance name: <project>-<role> with a lower-case project (letters, digits) and a role from: $DA_ROLES"
  fi
}

die() { echo "qargi: $*" >&2; exit 1; }

# Cloud verbs that create or drive a session need --asked "<what the user
# said>": the quote is stored in the tracker so the choice is auditable.
# Every approval-gated or cloud-driving verb leaves an append-only line here.
audit_log() { # verb [detail]
  local f=$DA_STATE/audit.log
  jq -nc --arg t "$(now)" --arg v "$1" --arg d "${2:-}" --arg a "${ASKED:-}" --arg p "${APPROVED:-}" --arg n "${QARGI_NESTED:-}" \
    '{ts:$t, verb:$v, detail:$d, asked:$a, approved:$p, nested:($n != "")}' >> "$f"
  chmod 600 "$f" 2>/dev/null || true
}

# An approval applies to the plan the user saw: plans print a token (a hash of what
# would be done) and apply must be given that token. Calls nested inside an approved
# apply (provisioning seeding its stores) skip it.
plan_token() { sha256sum | cut -c1-12; }
need_plan() { # expected-token; the caller's --plan value is $PLAN_ARG
  [ -z "${QARGI_NESTED:-}" ] || return 0
  [ "${PLAN_ARG:-}" = "$1" ] || die "the plan changed or --plan is missing: run the plan, show it to the user, then apply exactly that with --plan $1"
}

need_asked() {
  audit_log "asked:${verb:-cmd}" "${NAME:-${ARG:-}}"
  [ -n "${ASKED:-}" ] || die "cloud verbs need --asked \"<the user's request that names this cloud instance>\"; cloud is never chosen automatically"
}

# json_update FILE JQ_FILTER [jq args...]: atomic, locked in-place update.
json_update() {
  local file=$1 filter=$2; shift 2
  (
    flock 9
    jq "$@" "$filter" "$file" > "$file.tmp" && chmod 600 "$file.tmp" && mv "$file.tmp" "$file"
  ) 9> "$file.lock"
}

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# A cloud call that fails on an expired login should say so.
ant_ok() {
  ant auth status >/dev/null 2>&1 || die "ant is not logged in (run: ant auth login)"
}

inst_get() { jq -e --arg n "$1" '.[$n]' "$REG" 2>/dev/null || die "no instance named $1 (see: list)"; }

# newest idle session of an instance, or empty
inst_idle_session() {
  jq -r --arg n "$1" '[to_entries[] | select(.value.instance==$n and .value.status=="idle" and (.value.closed_at==null))]
    | sort_by(.value.created) | last | .key // empty' "$TRK"
}

# Refresh one tracker row from the API.
trk_refresh() {
  local sid=$1 s
  s=$(ant beta:sessions retrieve --session-id "$sid" 2>/dev/null) || return 1
  json_update "$TRK" '.[$s] += {status: $st.status, stop_reason: ($st.stop_reason.type // null),
      last_seen: $t, list_cost: ($st.usage.list_cost.amount // null)}' \
    --arg s "$sid" --arg t "$(now)" --argjson st "$s"
}

cred_file() { # project -> expanded credential file path, or empty
  local f; f=$(jq -r '.repo.credential_file // ""' "$DA_CONF/projects/$1.json" 2>/dev/null)
  [ -z "$f" ] || printf '%s' "${f/#\~/$HOME}"
}

# git environment that authenticates over https with the token and nothing else.
# Sets GIT_ASKPASS to a helper that reads the file at call time (the token is never in argv).
git_auth_env() { # credential-file -> exports for the caller's subshell
  ASKPASS=$(mktemp "${TMPDIR:-/tmp}/qargi-askpass.XXXXXX")
  printf '#!/bin/sh\ncat %s\n' "$(printf '%q' "$1")" > "$ASKPASS"; chmod 700 "$ASKPASS"
  export GIT_ASKPASS=$ASKPASS GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_SSH_COMMAND=false
}

# The system prompt of a cloud agent of ROLE: the cloud preamble (names the role), the agent
# contract, and the role's contract addendum if it has one. Provisioning and refresh-prompt
# build it the same way, so an agent can always be brought back in line with the tool.
agent_prompt() { # role
  local lib; lib=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
  local tpl=$lib/../provision/templates rs=$lib/../provision/role-seeds/$1 contract=$lib/../skills/qargi-task/agent-contract.md
  [ -d "$tpl" ] || { tpl=$lib/provision/templates; rs=$lib/provision/role-seeds/$1; contract=$lib/skills/qargi-task/agent-contract.md; }
  sed "s/{{ROLE}}/$1/g" "$tpl/cloud-preamble.md"; cat "$contract"; [ ! -f "$rs/contract.md" ] || cat "$rs/contract.md"
}

