#!/usr/bin/env bash
# Shared helpers for the dev-agent skill. Registry and tracker live outside
# the repository, under the XDG config and state directories.
set -u

# DEV_AGENT_CONF / DEV_AGENT_STATE override the locations (for tests); do not
# redirect XDG_CONFIG_HOME instead, because the ant CLI keeps its login there.
DA_CONF=${DEV_AGENT_CONF:-${XDG_CONFIG_HOME:-$HOME/.config}/dev-agent}
DA_STATE=${DEV_AGENT_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/dev-agent}
REG=$DA_CONF/instances.json
TRK=$DA_STATE/sessions.json
export BETA=managed-agents-2026-04-01

mkdir -p "$DA_CONF" "$DA_STATE"
chmod 700 "$DA_CONF" "$DA_STATE"
for f in "$REG" "$TRK"; do
  [ -f "$f" ] || { echo '{}' > "$f"; chmod 600 "$f"; }
done

die() { echo "dev-agent: $*" >&2; exit 1; }

# Cloud verbs that create or drive a session need --asked "<what the user
# said>": the quote is stored in the tracker so the choice is auditable.
need_asked() {
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
