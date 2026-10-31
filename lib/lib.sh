#!/usr/bin/env bash
# Shared helpers for the qargi skill. Registry and tracker live outside
# the repository, under ~/.qargi/config and ~/.qargi/state.
set -u

# Where the data lives (lib/paths.py does the same for the Python scripts; keep the two in step; its docstring has the
# whole story): QARGI_CONF and QARGI_STATE name a directory (tests do), else QARGI_HOME/config and QARGI_HOME/state,
# else ~/.qargi/config and ~/.qargi/state. XDG_CONFIG_HOME and XDG_STATE_HOME are not used for qargi's data (the ant
# CLI keeps its login in the former); they only locate the earlier layout, which `qargi migrate home` copies.
# A dev run (a checkout other than the one install.sh recorded in the live <config>/install.json, with nothing named)
# keeps its data in <tool root>/.qargi instead, so a branch checkout never touches live data.
QARGI_TOOL=$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")
DA_ROOT=${QARGI_HOME:-$HOME/.qargi}
if [ -z "${QARGI_CONF:-}${QARGI_STATE:-}${QARGI_HOME:-}" ] && [ -f "$HOME/.qargi/config/install.json" ]; then
  _rec=$(jq -r '.tool_root // empty' "$HOME/.qargi/config/install.json" 2>/dev/null) || _rec=''
  if [ -n "$_rec" ] && [ "$(readlink -f "$_rec")" != "$QARGI_TOOL" ]; then DA_ROOT=$QARGI_TOOL/.qargi; fi
fi
DA_CONF=${QARGI_CONF:-$DA_ROOT/config}
DA_STATE=${QARGI_STATE:-$DA_ROOT/state}
# Only the earlier layout exists and nothing was named: stop, so no empty new root appears beside the old data.
if [ -z "${QARGI_CONF:-}${QARGI_STATE:-}${QARGI_HOME:-}" ] && [ "$DA_ROOT" = "$HOME/.qargi" ] && [ ! -e "$HOME/.qargi" ] && [ ! -L "$HOME/.qargi" ] \
   && { [ -d "${XDG_CONFIG_HOME:-$HOME/.config}/qargi" ] || [ -d "${XDG_STATE_HOME:-$HOME/.local/state}/qargi" ]; }; then
  echo "qargi: qargi keeps its data in $HOME/.qargi now; yours is still in the earlier XDG directories. Nothing was changed. Run: qargi migrate home (it shows the plan first and copies, so the old directories stay as a backup)." >&2
  exit 1
fi
REG=$DA_CONF/instances.json
TRK=$DA_STATE/sessions.json
MEMBERS_FILE=$DA_CONF/agents.json   # the members you named (qargi agent add): {name: {abilities, file, model, effort, project}}
export BETA=managed-agents-2026-04-01

mkdir -p "$DA_CONF" "$DA_STATE"
chmod 700 "$DA_CONF" "$DA_STATE"
[ -n "${QARGI_CONF:-}${QARGI_STATE:-}" ] || chmod 700 "$DA_ROOT"
for f in "$REG" "$TRK" "$MEMBERS_FILE"; do
  [ -f "$f" ] || { echo '{}' > "$f"; chmod 600 "$f"; }
done

# Naming convention (see README): <project>-<component>[-<role>]. Project and role
# are single lower-case tokens (no dashes) so a name parses unambiguously; the
# role comes from a fixed list. The environment and the memory stores belong to the
# project: <project>-environment, <project>-memory, <project>-reference; the agent
# and the deployment belong to a role: <project>-<role>, <project>-deployment-<role>.
# An instance is <project>-<role>; a session is named <instance>-<task-slug>.
# The roles are the four abilities (build, review, write, test), each defined by a skill qargi-<ability>.
DA_ROLES=${QARGI_ROLES:-"build review write test"}
valid_project() { printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9]{0,23}$'; }
# "lead" is the team coordinator: an instance role of its own, defined by the project's teams, not a work role.
valid_role() { local r; for r in $DA_ROLES lead; do [ "$r" = "$1" ] && return 0; done; return 1; }
valid_slug() { printf '%s' "$1" | grep -Eq '^[a-z0-9][a-z0-9-]{0,40}$'; }
# split_instance NAME: sets PROJECT and ROLE, or dies with the rule.
split_instance() {
  PROJECT=${1%%-*}; ROLE=${1#*-}
  if [ "$PROJECT-$ROLE" != "$1" ] || ! valid_project "$PROJECT" || ! valid_role "$ROLE"; then
    die "'$1' is not a standard instance name: <project>-<role> with a lower-case project (letters, digits) and a role from: $DA_ROLES"
  fi
}

# mem_index STORE: JSON lines {path,id} of every memory of a store (metadata only).
mem_index() {
  ant beta:memory-stores:memories list --memory-store-id "$1" --path-prefix / --view basic --max-items -1 </dev/null 2>/dev/null \
    | jq -c 'select(.type=="memory") | {path, id}'
}
# mem_dump STORE: JSON lines of every memory of a store, with content (QARGI_CANON_FIXTURE_DIR replaces the cloud in tests).
mem_dump() {
  if [ -n "${QARGI_CANON_FIXTURE_DIR:-}" ]; then cat "$QARGI_CANON_FIXTURE_DIR/$1.jsonl"; return; fi
  ant beta:memory-stores:memories list --memory-store-id "$1" --path-prefix / --view full --max-items -1 </dev/null 2>/dev/null \
    | jq -c 'select(.type=="memory") | {type, id, path, content, content_sha256}'
}

# mem_exec_ops STORE PLAN_JSON: run a plan's steps ({ops: [move|create|update|marker]}) against a store, in order;
# stops at the first failure. canon.sh and migrate.sh plan with Python and execute with this.
mem_exec_ops() {
  local store=$1 plan=$2 n=0 op f
  while IFS= read -r op <&3; do
    case $(jq -r .op <<<"$op") in
      move)
        ant beta:memory-stores:memories update --memory-store-id "$store" --memory-id "$(jq -r .id <<<"$op")" \
          --path "$(jq -r .to <<<"$op")" </dev/null >/dev/null 2>&1 || die "move failed: $(jq -r .from <<<"$op")";;
      create|marker|update)
        f=$(mktemp); jq -j .content <<<"$op" > "$f"
        if [ -n "$(jq -r '.id // empty' <<<"$op")" ]; then
          sha=$(jq -r '.sha // empty' <<<"$op"); pre=()
          [ -z "$sha" ] || pre=(--precondition "{type: content_sha256, content_sha256: \"$sha\"}")
          printf 'content: "@%s"\n' "$f" | ant beta:memory-stores:memories update --memory-store-id "$store" \
            --memory-id "$(jq -r .id <<<"$op")" "${pre[@]}" >/dev/null 2>&1 || { rm -f "$f"; die "update failed (changed meanwhile?): $(jq -r .path <<<"$op")"; }
        else
          printf 'content: "@%s"\n' "$f" | ant beta:memory-stores:memories create --memory-store-id "$store" \
            --path "$(jq -r .path <<<"$op")" >/dev/null 2>&1 || { rm -f "$f"; die "create failed: $(jq -r .path <<<"$op")"; }
        fi
        rm -f "$f";;
    esac
    n=$((n+1))
  done 3< <(jq -c '.ops[]' "$plan")
  echo "applied $n step(s)"
}

# mem_read STORE ID: the content of one memory.
mem_read() {
  ant beta:memory-stores:memories retrieve --memory-store-id "$1" --memory-id "$2" </dev/null 2>/dev/null | jq -r '.content // empty'
}

# res_name COMPONENT: the cloud resource name for the current $PROJECT and $ROLE.
res_name() {
  case $1 in
    environment) echo "$PROJECT-environment";;
    agent) echo "$PROJECT-$ROLE";;
    deployment) echo "$PROJECT-deployment-$ROLE";;
    *) return 1;;
  esac
}

die() { echo "qargi: $*" >&2; exit 1; }

# Cloud verbs that create or drive a session need --asked "<what the user
# said>": the quote is stored in the tracker so the choice is auditable.
# Every approval-gated or cloud-driving verb leaves an append-only line here.
audit_log() { # verb [detail]
  local f=$DA_STATE/audit.log
  # AUDIT_ORIGIN (set by the supervisor only) adds an origin field, so its lines can be told from the owner's
  jq -nc --arg t "$(now)" --arg v "$1" --arg d "${2:-}" --arg a "${ASKED:-}" --arg p "${APPROVED:-}" --arg n "${QARGI_NESTED:-}" --arg o "${AUDIT_ORIGIN:-}" \
    '{ts:$t, verb:$v, detail:$d, asked:$a, approved:$p, nested:($n != "")} + (if $o == "" then {} else {origin:$o} end)' >> "$f"
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

# Why a session went idle. The session object has no stop_reason; the reason is on the session.status_idle events
# (the thread_status_idle ones are per thread and ignored). Prints {type, event_ids} of the last one, or nothing.
idle_stop() { # sid
  ant beta:sessions:events list --session-id "$1" --max-items -1 </dev/null 2>/dev/null \
    | jq -sc '[.[] | if type == "array" then .[] else . end | select(.type == "session.status_idle" and .stop_reason.type != null)]
        | sort_by(.processed_at) | last // empty | {type: .stop_reason.type, event_ids: (.stop_reason.event_ids // null)}'
}

# Refresh one tracker row from the API. stop_reason is the type of the last session.status_idle event while the
# session is idle (end_turn, requires_action, retries_exhausted, budget_reached) and empty otherwise; stop_event_ids
# are the events a requires_action waits on. An interrupt (qargi stop) also ends with end_turn: see interrupt_sent_at.
trk_refresh() {
  local sid=$1 s stop=''
  s=$(ant beta:sessions retrieve --session-id "$sid" 2>/dev/null) || return 1
  [ "$(jq -r .status <<<"$s")" != idle ] || stop=$(idle_stop "$sid")
  json_update "$TRK" '.[$s] += {status: $st.status, stop_reason: ($stop.type // $st.stop_reason.type // null), stop_event_ids: ($stop.event_ids // null),
      last_seen: $t, last_processed_at: ($st.updated_at // null), list_cost: ($st.usage.list_cost.amount // null)}' \
    --arg s "$sid" --arg t "$(now)" --argjson st "$s" --argjson stop "${stop:-null}"
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
# contract, and the ability's skill (skills/qargi-<role>/SKILL.md, the same text a local member
# loads), or for the lead its contract. Provisioning and refresh-prompt
# build it the same way, so an agent can always be brought back in line with the tool.
# The teams of a project as text for the lead's prompt: members, bases, scopes, standards,
# rounds and budget, so a lead started from the console needs only a task.
lead_teams_block() { # project
  local f=$DA_CONF/projects/$1.json
  [ -f "$f" ] || return 0
  jq -r '. as $c
    | "\n# Teams of project \($c.project)\nRepository: \($c.repo.url). Branches no member may touch: \($c.repo.long_lived | join(", ")).\n"
    + ($c.teams | to_entries | map(
        "\n## Team \(.key)\nMembers (start in this order): \(.value.members | join(", ")). At most \(.value.max_rounds // 2) revise rounds. Budget \(.value.budget_cents // $c.budget_cents) cents.\n"
        + "Base branch per member: " + (.value.members | map("\(.) = \($c.roles[.].base)") | join("; ")) + "  (@dispatcher: the branch the person who started you names).\n"
        + "Each member: CLONE /workspace/<role>, OUT_PREFIX <role>--, SCOPE as below (none = the whole task).\n"
        + "Scopes: " + ((.value.scopes // {}) | if length == 0 then "none" else (to_entries | map("\(.key): \(.value | join(", "))") | join("; ")) end) + "\n"
        + "Standards for the reviewer: " + ((.value.standards // []) | if length == 0 then "none" else join(", ") end) + "\n") | join(""))
    + "\n# Push\n" + (if (($c.lead.push.cloud // "none") == "branches") then
        "You may create branches named \($c.lead.push.branch_pattern // "agent/*") and push to them, and open pull requests, with the GitHub tools you have. Carry each member\u0027s commits one at a time with their messages, so the series stays reviewable. Merging a pull request and creating a release are asked of the person by the platform: request them only after the reviewer\u0027s verdict is accept and the person has told you to, and never work around a refusal. Never push any other branch or a tag, never delete a branch, never force-push. Members never push and you never tell them to.\n"
      else "You never push. Members never push. Deliver patches; the coordinator who dispatched you applies and publishes them.\n" end)
    + "\nIf the first message is a plain task rather than a TEAM brief, use the only team above (or ask which), build the entry of each member from these definitions, ask for the base branch if it is @dispatcher, and proceed.\n"' "$f"
}

# tools_off ROLE PROJECT_JSON: the built-in tools a cloud role does not get (roles.<role>.tools_off overrides the default).
tools_off() {
  local d='web_search web_fetch'; case $1 in review|lead) d='web_search web_fetch edit';; esac
  if [ -f "$2" ] && jq -e --arg r "$1" '.roles[$r].tools_off' "$2" >/dev/null 2>&1; then jq -r --arg r "$1" '.roles[$r].tools_off | join(" ")' "$2"; else echo "$d"; fi
}

# The directory that holds provision/ and skills/: the checkout, or lib/ itself in an installed copy.
prompt_root() {
  local lib; lib=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
  if [ -d "$lib/../provision/templates" ]; then echo "$lib/.."; else echo "$lib"; fi
}

agent_prompt() { # role [project]
  local root; root=$(prompt_root)
  local tpl=$root/provision/templates rs=$root/provision/role-seeds/$1 sk=$root/skills
  sed "s/{{ROLE}}/$1/g" "$tpl/cloud-preamble.md"
  # the lead delegates and reports; the worker contract (patches, clones) is the members' own
  [ "$1" = lead ] || cat "$sk/qargi-task/agent-contract.md"
  if [ -f "$sk/qargi-$1/SKILL.md" ]; then echo; awk 'f>=2 {print} /^---$/ {f++}' "$sk/qargi-$1/SKILL.md"; fi
  [ ! -f "$rs/contract.md" ] || cat "$rs/contract.md"
  [ "$1" != lead ] || [ -z "${2:-}" ] || lead_teams_block "$2" || return 1
}

# The hashes that say whether a cloud agent's prompt is out of date, with no cloud call. sha is the hash of the whole
# rendered prompt (what refresh-prompt would push); skill is the hash of the two files that change most, the agent
# contract and the role's skill. Prints {sha, skill}.
prompt_stamp() { # role project
  local sk sha; sk=$(prompt_root)/skills
  sha=$(agent_prompt "$1" "$2" | sha256sum | cut -c1-16)
  [ "${PIPESTATUS[0]}" = 0 ] || return 1
  jq -nc --arg s "$sha" --arg k "$(cat "$sk/qargi-task/agent-contract.md" "$sk/qargi-$1/SKILL.md" 2>/dev/null | sha256sum | cut -c1-16)" '{sha: $s, skill: $k}'
}

# prompt_state INSTANCE: current | stale skill | stale prompt | unknown | none. Compares the prompt rendered now with the
# hash recorded when the agent was provisioned or last refreshed. A registry entry with no hash (made before it was
# recorded, or by init) is unknown, never stale; a local instance has no cloud prompt (none).
prompt_state() {
  local n=$1 rec old oldk cur
  rec=$(jq -c --arg n "$n" '.[$n] // empty' "$REG" 2>/dev/null)
  [ -n "$rec" ] && [ "$(jq -r .location <<<"$rec")" = cloud ] || { echo none; return 0; }
  valid_project "${n%%-*}" && valid_role "${n#*-}" || { echo none; return 0; }
  old=$(jq -r '.prompt.sha // empty' <<<"$rec"); oldk=$(jq -r '.prompt.skill // empty' <<<"$rec")
  [ -n "$old" ] || { echo unknown; return 0; }
  cur=$(prompt_stamp "${n#*-}" "${n%%-*}") || { echo unknown; return 0; }
  if [ "$(jq -r .sha <<<"$cur")" = "$old" ]; then echo current
  elif [ -n "$oldk" ] && [ "$(jq -r .skill <<<"$cur")" != "$oldk" ]; then echo "stale skill"
  else echo "stale prompt"; fi
}

# prompt_record INSTANCE: remember the hashes of the prompt the cloud agent now has (provisioned or refreshed).
prompt_record() {
  local n=$1 st
  st=$(prompt_stamp "${n#*-}" "${n%%-*}") || return 0
  json_update "$REG" 'if has($n) then .[$n].prompt = ($p + {at: $t}) else . end' --arg n "$n" --argjson p "$st" --arg t "$(now)"
}

