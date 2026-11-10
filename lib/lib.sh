#!/usr/bin/env bash
# Shared helpers for the qargi skill. Registry and tracker live outside
# the repository, under ~/.qargi/config and ~/.qargi/state.
set -u

# Where the data lives (lib/paths.py does the same for the Python scripts; keep the two in step; its docstring has the
# whole story): QARGI_CONF and QARGI_STATE name a directory (tests do), else QARGI_HOME/config and QARGI_HOME/state,
# else ~/.qargi/config and ~/.qargi/state. XDG_CONFIG_HOME and XDG_STATE_HOME are not used for qargi's data (the ant
# CLI keeps its login in the former).
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
REG=$DA_CONF/instances.json
TRK=$DA_STATE/sessions.json
MEMBERS_FILE=$DA_CONF/agents.json   # the members you named (qargi agent add): {"schema": 2, "projects": {PROJECT: {NAME: {roles, file, model, effort, ...}}}}
export BETA=managed-agents-2026-04-01

# The first load makes the directories (mode 700) and the three files. DA_NOSETUP, set in the environment of a read-only caller (qargi doctor and the
# scripts it runs), skips all of it: nothing is created or changed, and a file that is not there stays not there.
if [ -z "${DA_NOSETUP:-}" ]; then
  mkdir -p "$DA_CONF" "$DA_STATE"
  chmod 700 "$DA_CONF" "$DA_STATE"
  [ -n "${QARGI_CONF:-}${QARGI_STATE:-}" ] || chmod 700 "$DA_ROOT"
  for f in "$REG" "$TRK"; do
    [ -f "$f" ] || { echo '{}' > "$f"; chmod 600 "$f"; }
  done
  [ -f "$MEMBERS_FILE" ] || { echo '{"schema":2,"projects":{}}' > "$MEMBERS_FILE"; chmod 600 "$MEMBERS_FILE"; }
fi
members_shape_ok() { # -> 0 when agents.json is in the current shape: {} or {"schema": 2, "projects": {P: {NAME: record}}} (qargi agent and qargi upgrade ask)
  jq -e 'type == "object" and (length == 0 or (.schema == 2 and ((keys - ["schema", "projects"]) | length) == 0 and (.projects | type) == "object"
    and (.projects | all(.[]; type == "object" and all(.[]; type == "object")))))' "$MEMBERS_FILE" >/dev/null 2>&1
}

# Naming convention (see docs/flow/README.md): <project>-<component>[-<role>]. Project and role
# are single lower-case tokens (no dashes) so a name parses unambiguously; the
# role comes from a fixed list. The environment and the memory stores belong to the
# project: <project>-environment, <project>-memory, <project>-reference; the agent
# and the deployment belong to a role: <project>-<role>, <project>-deployment-<role>.
# An instance is <project>-<role>; a session is named <instance>-<task-slug>.
# A role is a directory with role.json (its class, write or read-only, and a description) and ROLE.md (its instructions).
# Four ship with qargi (build, write, review, test; <tool>/roles); you add your own under <config>/roles. Role names are one
# lower-case token, unique across both places, and never "lead", "worker" or "reviewer" (the last two are the cloud bases).
ROLE_BUILTIN="build review write test"
role_dir() { # name -> the directory of the role, or fails (a base name is never a role, whatever directory carries it)
  local d
  ! is_base "$1" || return 1
  for d in "$QARGI_TOOL/roles/$1" "$DA_CONF/roles/$1"; do
    if [ -f "$d/role.json" ] && [ -f "$d/ROLE.md" ]; then echo "$d"; return 0; fi
  done
  return 1
}
role_names() { # the built-in roles, then yours in name order
  local r d
  for r in $ROLE_BUILTIN; do echo "$r"; done
  for d in "$DA_CONF"/roles/*/; do
    r=$(basename "$d")
    case " $ROLE_BUILTIN " in *" $r "*) continue;; esac
    if [ -f "$d/role.json" ] && [ -f "$d/ROLE.md" ] && printf '%s' "$r" | grep -Eq '^[a-z][a-z0-9]{0,23}$' && [ "$r" != lead ] && ! is_base "$r"; then echo "$r"; fi
  done
}
role_class() { # name -> write | read-only (lead: coordinator)
  [ "$1" != lead ] || { echo coordinator; return 0; }
  local d; d=$(role_dir "$1") || return 1
  jq -r '.class // "write"' "$d/role.json"
}
# The two cloud bases are instance names too: worker (write) and reviewer (read-only), from the bases of model-defaults.json.
_QARGI_DEFAULTS=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/model-defaults.json
base_class() { # name -> the class of a base (worker, reviewer), or fails when the name is not a base
  [ -f "$_QARGI_DEFAULTS" ] || return 1
  jq -er --arg n "$1" '.bases[$n].class // empty' "$_QARGI_DEFAULTS" 2>/dev/null
}
is_base() { base_class "$1" >/dev/null; }
instance_class() { # name -> write | read-only | coordinator; never fails, and a name or a class it does not know is read-only
  local c
  [ "$1" != lead ] || { echo coordinator; return 0; }
  if is_base "$1"; then c=$(base_class "$1"); else c=$(role_class "$1" 2>/dev/null) || c=''; fi
  case $c in write|read-only) echo "$c";; *) echo read-only;; esac
}
class_abilities() { # BASE [PROJECT_JSON] -> a JSON array: the abilities of a base, and those of the project's own profiles that use it
  local f=${2:-}; [ -f "$f" ] && jq -e . "$f" >/dev/null 2>&1 || f=''
  jq -nc --arg b "$1" --slurpfile d "$_QARGI_DEFAULTS" --argjson p "$([ -n "$f" ] && cat "$f" || echo '{}')" \
    '(($d[0].bases[$b].abilities // []) + [($p.profiles // {})[] | select(.base == $b) | (.abilities // [])[]]) | unique' 2>/dev/null || echo '[]'
}
# run_class RUN -> the class of a local run: write or read-only. The lead's registry says (prepare records it: the run directory is a member's to
# write, and a class file there would let a write run pass for a read-only one); a run the registry does not name, or names with no class, counts as
# write, never as read-only. Nothing in the run directory is read.
run_class() {
  local c
  reg_has "$1" || reg_load
  c=$(reg_get "$1" class)
  case $c in write|read-only) echo "$c"; return 0;; esac
  echo write
}
# out_has_report OUT -> 0 when OUT holds a report: a regular file (not a link) named report.md or *-report.md directly in it. The one test local.sh and
# lib/lead_usage.py (has_report) share.
out_has_report() {
  local f
  for f in "$1"/report.md "$1"/*-report.md; do [ -f "$f" ] && [ ! -L "$f" ] && return 0; done
  return 1
}
# The lead's registry of local runs ($DA_STATE/local-runs.jsonl, one JSON line per run, written by `local prepare`, mode 600) is what decides what a run is
# and where it came from: its directory, slug, base, temporary directory and the repository (repo: a real path; or url and cred: a repository URL and the path
# of its credential file, never a token). The run directory is a member's to write, so nothing in it that says the same is believed (see run_record).
#   reg_load            fills LRUNS (real path of each run directory the registry names -> its last line) and LRUNS_ORDER (those paths, first seen first)
#   reg_has DIR         0 when the registry names the directory DIR (compared by real path)
#   reg_get DIR FIELD   the text of FIELD in the registry's line for DIR (empty when absent or not a string)
#   reg_json DIR FILTER the compact JSON a jq FILTER makes of the registry's line for DIR (nothing when the run is not in it)
#   reg_record DIR      run_record from the registry alone, for a run whose directory is gone (its saved copy: local verify --saved)
#   reg_id ID           the run directory of the registry whose name is ID (qargi.XXXXXX), when exactly one has it
#   reg_edit DIR drop|cleaned   rewrites the registry under its lock: drops the lines of DIR, or marks them cleaned (a time), mode 600
# The line also holds what prepare took from the lead's answers, the one copy that verify, clean and review apply believe: the class of the run (class:
# write or read-only), the stored project of its repository (project) and answers, an object with the answers that decide what verification accepts (runs.owned_refs, repo.long_lived,
# repo.parking_branch, git.author, review.keep_author, review.scrub, review.trailer_policy, review.reject_trailers).
# A path is compared by its real path; the run directory of a line may be gone (a reboot that emptied a tmpfs, a clean), and the path is then
# taken as written, resolved as far as it exists (readlink -m).
declare -gA LRUNS=()   # -g: lib.sh is sourced from inside a function by some callers
LRUNS_ORDER=()
reg_load() {
  local f=$DA_STATE/local-runs.jsonl r line rr
  LRUNS=(); LRUNS_ORDER=()
  [ -f "$f" ] || return 0
  # @tsv doubles every backslash and leaves no other escape in a compact line; undo that one
  while IFS=$'\t' read -r r line; do
    r=${r//\\\\/\\}; line=${line//\\\\/\\}
    rr=$(readlink -m -- "$r" 2>/dev/null) || continue
    [ -n "$rr" ] || continue
    [ -n "${LRUNS[$rr]+x}" ] || LRUNS_ORDER+=("$rr")
    LRUNS[$rr]=$line
  done < <(jq -r 'select(type == "object" and (.run | type) == "string") | [.run, tojson] | @tsv' "$f" 2>/dev/null)
}
reg_has() { local rr; rr=$(readlink -m -- "$1" 2>/dev/null) || return 1; [ -n "${LRUNS[$rr]+x}" ]; }
reg_get() {
  local rr; rr=$(readlink -m -- "$1" 2>/dev/null) || return 0
  [ -n "${LRUNS[$rr]+x}" ] || return 0
  jq -r --arg k "$2" 'if (.[$k] | type) == "string" then .[$k] else "" end' <<<"${LRUNS[$rr]}" 2>/dev/null || true
}
# reg_mark DIR KEY VALUE -> sets KEY to VALUE (a string) in the registry's line for the run DIR, in place, under the registry's lock (the one
# prepare appends under), mode 600 kept; a run the registry does not name is left alone, and a failure is not the caller's (the mark is a
# record, the run's own files stay what verify and clean decide on). verify marks a run verified, clean marks it cleaned: the run keeps its
# one line, and the readers (marshal status, handoff, report) see the truth after the run directory is gone.
reg_json() {
  local rr; rr=$(readlink -m -- "$1" 2>/dev/null) || return 0
  [ -n "${LRUNS[$rr]+x}" ] || return 0
  jq -c "$2" <<<"${LRUNS[$rr]}" 2>/dev/null || true
}
reg_mark() {
  local f=$DA_STATE/local-runs.jsonl rr
  rr=$(readlink -f -- "$1" 2>/dev/null) || rr=$1
  [ -f "$f" ] || return 0
  ( flock 9 && umask 077 && jq -c --arg r "$rr" --arg g "$1" --arg k "$2" --arg v "$3" \
      'if type == "object" and ((.run | type) == "string") and (.run == $r or .run == $g) then .[$k] = $v else . end' "$f" > "$f.tmp" \
      && chmod 600 "$f.tmp" && mv "$f.tmp" "$f"
  ) 9> "$f.lock" 2>/dev/null || true
}
reg_record() {
  RUN_REPO='' RUN_URL='' RUN_CRED='' RUN_ANS=''
  reg_has "$1" || { echo "qargi: $1 is not in the lead's registry ($DA_STATE/local-runs.jsonl): only a run made by qargi local prepare on this machine is trusted" >&2; return 1; }
  RUN_REPO=$(reg_get "$1" repo); RUN_URL=$(reg_get "$1" url); RUN_CRED=$(reg_get "$1" cred)
  RUN_ANS=$(reg_json "$1" 'if (.answers | type) == "object" then .answers else empty end')
  [ -n "$RUN_REPO" ] || [ -n "$RUN_URL" ] || { echo "qargi: the lead's registry names no repository for $1: it cannot be verified" >&2; return 1; }
}
reg_id() {
  local d hit='' n=0
  case $1 in qargi.??????) ;; *) return 1;; esac
  for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do [ "${d##*/}" != "$1" ] || { hit=$d; n=$((n + 1)); }; done
  [ "$n" = 1 ] && printf '%s\n' "$hit"
}
reg_edit() {
  local f=$DA_STATE/local-runs.jsonl rr tmp
  [ -f "$f" ] || return 0
  rr=$(readlink -m -- "$1" 2>/dev/null) || return 1
  ( umask 077; flock 9 || exit 1
    tmp=$(mktemp "$f.tmp.XXXXXX") || exit 1
    # a line is the run's when its run, resolved as far as it exists, is the same path; any other line, a malformed one too, is kept as it is
    while IFS= read -r line || [ -n "$line" ]; do
      r=$(jq -r 'if type == "object" and (.run | type) == "string" then .run else empty end' <<<"$line" 2>/dev/null) || r=''
      if [ -n "$r" ] && [ "$(readlink -m -- "$r" 2>/dev/null)" = "$rr" ]; then
        [ "$2" = drop ] && continue
        line=$(jq -c --arg t "$(now)" '.cleaned = $t' <<<"$line")
      fi
      printf '%s\n' "$line"
    done < "$f" > "$tmp" && chmod 600 "$tmp" && mv -f -- "$tmp" "$f" || { rm -f "$tmp"; exit 1; }
  ) 9> "$f.lock"
}
# run_record RUN -> 0 and sets RUN_REPO, RUN_URL, RUN_CRED and RUN_ANS from the registry (reg_load first); 1 with the reason on stderr when the registry does not
# name the run, names no repository for it, or the run directory's own repo.path, repo.url or cred.path (which a member can write) differ from it or are not
# plain files. verify, clean, run and review apply take the repository, the URL and the credential path from these variables and from nothing else: git run
# in a repository a member chose reads its configuration (core.sshCommand, credential.helper ...), and a URL and a credential path chosen by a member send
# any file the lead can read as a token to a host of its choice.
run_record() {
  local run=$1 name want got
  reg_record "$run" || return 1
  for name in repo.path repo.url cred.path; do
    case $name in repo.path) want=$RUN_REPO;; repo.url) want=$RUN_URL;; *) want=$RUN_CRED;; esac
    if [ -z "$want" ]; then
      [ ! -e "$run/$name" ] && [ ! -L "$run/$name" ] || { echo "qargi: $run/$name exists but the lead's registry records none: the run directory was changed after prepare" >&2; return 1; }
      continue
    fi
    [ -f "$run/$name" ] && [ ! -L "$run/$name" ] || { echo "qargi: $run/$name is missing or not a plain file, and the lead's registry records $want: the run directory was changed after prepare" >&2; return 1; }
    got=$(cat -- "$run/$name" 2>/dev/null || true)
    [ "$got" = "$want" ] || { echo "qargi: $run/$name says '$got' but the lead's registry says '$want': the run directory was changed after prepare, nothing was run against it" >&2; return 1; }
  done
}
# project_of REPO URL -> the stored project whose repo.path (or repo.url) is the one given; nothing when there is none
project_of() {
  local f rp ru
  for f in "$DA_CONF"/projects/*.json; do
    [ -f "$f" ] || continue
    rp=$(jq -r '.repo.path // ""' "$f" 2>/dev/null); rp=${rp/#\~/$HOME}; ru=$(jq -r '.repo.url // ""' "$f" 2>/dev/null)
    if [ -n "$1" ]; then [ -n "$rp" ] && [ "$(readlink -f "$rp")" = "$(readlink -f "$1")" ] || continue
    else [ -n "$ru" ] && [ "${ru%.git}" = "${2%.git}" ] || continue; fi
    basename "$f" .json; return 0
  done
  return 0
}
# run_answers -> prints (JSON) the answers that decide what verification accepts for the run reg_record/run_record just read: the snapshot prepare took into
# the lead's registry (RUN_ANS), never the stored project's file, which anything running as the lead's user can write or add a decoy of. A record
# with no snapshot prints nothing.
run_answers() {
  [ -z "${RUN_ANS:-}" ] || printf '%s\n' "$RUN_ANS"
  return 0
}
# run_project RUN -> the stored project a registered run was made for (reg_load first): the one prepare recorded
run_project() {
  reg_get "$1" project
}
DA_ROLES=${QARGI_ROLES:-$(role_names | tr '\n' ' ' | sed 's/ $//')}
valid_project() { printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9]{0,23}$'; }
# "lead" is the team coordinator: an instance role of its own, defined by the project's teams, not a work role.
valid_role() { local r; for r in $DA_ROLES lead; do [ "$r" = "$1" ] && return 0; done; return 1; }
valid_slug() { printf '%s' "$1" | grep -Eq '^[a-z0-9][a-z0-9-]{0,40}$'; }
# split_instance NAME: sets PROJECT and ROLE, or dies with the rule.
split_instance() {
  PROJECT=${1%%-*}; ROLE=${1#*-}
  if [ "$PROJECT-$ROLE" != "$1" ] || ! valid_project "$PROJECT" || { ! valid_role "$ROLE" && ! is_base "$ROLE"; }; then
    die "'$1' is not a standard instance name: <project>-<role> with a lower-case project (letters, digits) and a role from: $DA_ROLES, or a base: worker, reviewer"
  fi
}

# project_provider PROJECT [SURFACE]: prints the runtime the project uses on a surface (local or cloud): models.provider in its answers is a
# name (a runtime, or a family with exactly one runtime on the surface) or an object {local, cloud}. Every verb passes the surface it runs
# on (members run on local, instances and sessions on cloud). There is no default: a project with no provider, a surface its answers leave
# unset, an unknown project or none at all is refused by lib/provider.py `of`, which prints the one message (qargi: project P has no
# [local|cloud] provider: set one with qargi project set P models.provider[.SURFACE] NAME) and exits 2; a single name that was resolved
# through its family is noted on stderr. Without a surface it answers only when models.provider is one name or names the same runtime for
# both surfaces. Run in $(...) the helper cannot end its caller, so every caller propagates the status:
#   prov=$(project_provider "$p" local) || exit $?
project_provider() { # project-or-empty [surface]
  local p
  p=$(python3 -I "$(dirname "${BASH_SOURCE[0]}")/provider.py" of "${1:-}" --conf "$DA_CONF" ${2:+--surface "$2"} </dev/null) || return $?
  printf '%s' "$p" | grep -Eq '^[a-z][a-z0-9-]*$' || { echo "qargi: models.provider '$p' is not a provider name (lower-case letters, digits and '-')" >&2; return 1; }
  echo "$p"
}
# project_provider_if_set PROJECT SURFACE: like project_provider for a caller that adds something only when a provider is set. No project, a project
# that is not stored, or no provider for the surface: prints nothing and succeeds ("no addendum"). A provider that is set and does not resolve (an unknown
# runtime, a family that names none or several, answers that cannot be read): prints the reason on stderr and fails, so the caller refuses instead of
# leaving out what the runtime would have added.
project_provider_if_set() { # project-or-empty surface
  local p
  p=$(python3 -I "$(dirname "${BASH_SOURCE[0]}")/provider.py" of-if-set "${1:-}" --conf "$DA_CONF" --surface "$2" </dev/null) || return $?
  [ -z "$p" ] || printf '%s' "$p" | grep -Eq '^[a-z][a-z0-9-]*$' || { echo "qargi: models.provider '$p' is not a provider name (lower-case letters, digits and '-')" >&2; return 1; }
  [ -z "$p" ] || echo "$p"
}
# cloud_note PROJECT TOPIC: the notes topic TOPIC of the definition of the runtime the project uses on the cloud surface (output-dir and
# clone-dir: where a hosted session keeps its outputs and its clones). The core names no hosted directory; the runtime's definition does.
# Prints the text; on failure (no cloud runtime for the project, or it has no such topic) prints the reason on stderr and returns its status.
cloud_note() { # project topic
  python3 -I "$(dirname "${BASH_SOURCE[0]}")/provider.py" notes "$2" --project "$1" --surface cloud </dev/null
}
# barrier_guard SURFACE PROJECT-or-empty: a read-only role is about to run on SURFACE. Exits 2 with the reason and the
# `qargi provider accept` command when the project's provider has no read-only barrier there and the project did not accept
# that; a partial barrier passes and prints its note on stderr. (lib/provider.py require-barrier decides.)
barrier_guard() {
  local rc=0 prov
  prov=$(project_provider "${2:-}" "$1") || exit $?   # no default provider: a project with none for this surface is refused here (exit 2)
  python3 -I "$(dirname "${BASH_SOURCE[0]}")/provider.py" require-barrier "$prov" "$1" ${2:+--project "$2"} || rc=$?
  [ "$rc" = 0 ] || exit "$rc"
}

# mem_index STORE: JSON lines {path,id} of every memory of a store (metadata only).
mem_index() {
  ant beta:memory-stores:memories list --memory-store-id "$1" --path-prefix / --view basic --max-items -1 </dev/null 2>/dev/null \
    | jq -c 'select(.type=="memory") | {path, id}'
}
# mem_dump STORE: JSON lines of every memory of a store, with content (QARGI_CANON_FIXTURE_DIR replaces the cloud in tests).
mem_dump() {
  if [ -n "${QARGI_CANON_FIXTURE_DIR:-}" ]; then cat "$QARGI_CANON_FIXTURE_DIR/$1.jsonl"; return; fi
  local out err why rc=0
  err=$(mktemp) || return 1
  out=$(ant beta:memory-stores:memories list --memory-store-id "$1" --path-prefix / --view full --max-items -1 </dev/null 2>"$err") || rc=$?
  why=$(grep -v '^[[:space:]]*$' "$err" | head -1 | cut -c1-160); rm -f "$err"
  # a failing list is not an empty store: status 1 and the reason on standard error
  [ "$rc" = 0 ] || { echo "${why:-ant failed (status $rc)}" >&2; return 1; }
  jq -c 'select(.type=="memory") | {type, id, path, content, content_sha256}' <<<"$out"
}

# mem_exec_ops STORE PLAN_JSON: run a plan's steps ({ops: [move|create|update|marker]}) against a store, in order;
# stops at the first failure. canon.sh plans with Python and execute with this.
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
usage_die() { echo "qargi: $*" >&2; exit 2; }   # a usage error (unknown option, missing argument, a usage line): exit 2, as the manual page promises
need_val() { # OPTION "$#" -> exit 2 when a valued option is the last word: call it first in each valued branch of an option loop
  [ "$2" -ge 2 ] || { echo "qargi: $1 needs a value" >&2; exit 2; }
}
run_clean() { # DIR COMMAND...: runs a command in DIR without the project's cloud binding: a suite, a release check or a scrub must not see it
  local dir=$1; shift
  (cd "$dir" && env -u ANTHROPIC_PROFILE -u QARGI_CLOUD_WORKSPACE -u QARGI_CLOUD_PROJECT "$@")
}

# Cloud verbs that create or drive a session need --asked "<what the user
# said>": the quote is stored in the tracker so the choice is auditable.
# Every approval-gated or cloud-driving verb leaves an append-only line here.
audit_log() { # verb [detail]
  local f=$DA_STATE/audit.log
  # AUDIT_ORIGIN (set by the supervisor only) adds an origin field, so its lines can be told from the owner's
  jq -nc --arg t "$(now)" --arg v "$1" --arg d "${2:-}" --arg a "${ASKED:-}" --arg p "${APPROVED:-}" --arg n "${NESTED_SKIPPED:-}" --arg o "${AUDIT_ORIGIN:-}" \
    '{ts:$t, verb:$v, detail:$d, asked:$a, approved:$p, nested:($n != "")} + (if $o == "" then {} else {origin:$o} end)' >> "$f"
  chmod 600 "$f" 2>/dev/null || true
}

# An approval applies to the plan the user saw: plans print a token (a hash of what
# would be done) and apply must be given that token. Calls nested inside an approved
# apply (provisioning seeding its stores) may skip it, through need_plan_nested alone.
plan_token() { sha256sum | cut -c1-12; }
need_plan() { # expected-token; the caller's --plan value is $PLAN_ARG; always checked, whatever the environment holds
  [ "${PLAN_ARG:-}" = "$1" ] || die "the plan changed or --plan is missing: run the plan, show it to the user, then apply exactly that with --plan $1"
}
need_plan_nested() { # as need_plan, but a call nested in an approved apply (QARGI_NESTED set) skips the check; canon apply only
  [ -z "${QARGI_NESTED:-}" ] || { NESTED_SKIPPED=1; return 0; }   # the audit line says "nested" only when the check was skipped
  need_plan "$1"
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
  ant auth status >/dev/null 2>&1 || die "ant is not logged in (run: ant auth login${QARGI_CLOUD_PROJECT:+, or: qargi cloud login $QARGI_CLOUD_PROJECT})"
  # a project bound to a workspace (qargi cloud): the profile in use must still reach it, so nothing lands in another one
  if [ -n "${QARGI_CLOUD_WORKSPACE:-}" ]; then
    [ "$(python3 -I "$(dirname "${BASH_SOURCE[0]}")/cloud.py" workspace "${ANTHROPIC_PROFILE:-default}" 2>/dev/null)" = "$QARGI_CLOUD_WORKSPACE" ] \
      || die "ant profile ${ANTHROPIC_PROFILE:-?} does not reach workspace $QARGI_CLOUD_WORKSPACE, which project ${QARGI_CLOUD_PROJECT:-?} is bound to: qargi cloud check ${QARGI_CLOUD_PROJECT:-}"
  fi
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
# Sets GIT_ASKPASS to lib/askpass.sh, which reads the file named by QARGI_ASKPASS_FILE at call time (the token is never in argv, and no
# helper file is made, so there is nothing to clean up).
git_auth_env() { # credential-file -> exports for the caller's subshell
  export QARGI_ASKPASS_FILE=$1 GIT_ASKPASS=$QARGI_TOOL/lib/askpass.sh GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_SSH_COMMAND=false
}
# url_key URL -> the one spelling of a repository URL that the ref journal records and `local verify` compares: https://HOST/PATH with
# no user or password, no trailing / and no .git (git@HOST:PATH and ssh://git@HOST/PATH give the same); a local path stays a path
url_key() {
  local u=$1 h
  case $u in '') return 0;; /*) u=${u%/}; printf '%s\n' "${u%.git}"; return 0;; *://*) u=${u#*://};; *:*) u=${u/:/\/};; esac
  h=${u%%/*}; u=${u#"$h"}; h=${h##*@}; u=${u%/}
  printf 'https://%s%s\n' "$h" "${u%.git}"
}

# The system prompt of a cloud agent of ROLE: the cloud preamble (names the role), the agent
# contract (contract/), and the role's instructions (roles/<role>/ROLE.md, the same text a local member's task block carries), or for the lead its contract. Provisioning and refresh-prompt
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
  local d='web_search web_fetch edit write'; [ "$(instance_class "$1")" != write ] || d='web_search web_fetch'   # any class but write: no edit, no write
  if [ -f "$2" ] && jq -e --arg r "$1" '.roles[$r].tools_off' "$2" >/dev/null 2>&1; then jq -r --arg r "$1" '.roles[$r].tools_off | join(" ")' "$2"; else echo "$d"; fi
}

# The directory that holds provision/, contract/ and skills/: the one above lib/, in the checkout and in an installed copy alike.
prompt_root() {
  echo "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.."
}

# cloud_contract [PROJECT]: the member contract of a cloud prompt: contract.md and output-format.md, then the contract addenda of the runtime the
# project uses on the cloud surface (resources.contract_addenda of its definition: its own rules about its surface, which the neutral contract
# does not name). Without a project, or for a project with no cloud provider set, there is no addendum: no runtime is ever assumed. A project whose
# cloud provider is set but does not resolve, and a runtime whose addenda cannot be read (a file missing, not text, a library pack changed since it was
# sealed), fail the prompt rather than leaving them out.
cloud_contract() { # [project]
  local ct prov; ct=$(prompt_root)/contract
  cat "$ct/contract.md" "$ct/output-format.md" || return 1
  prov=$(project_provider_if_set "${1:-}" cloud) || { echo "qargi: the prompt of a cloud agent of project ${1:-} cannot be made: its cloud provider does not resolve, so the contract addenda of its runtime would be left out" >&2; return 1; }
  [ -n "$prov" ] || return 0
  python3 -I "$(dirname "${BASH_SOURCE[0]}")/provider.py" addenda "$prov" cloud
}

agent_prompt() { # role [project]
  local root; root=$(prompt_root)
  local tpl=$root/provision/templates rs=$root/provision/role-seeds/$1
  # a base (worker, reviewer) is a role-neutral agent: the role text comes with each session, so the agent itself holds only a short fallback
  if is_base "$1"; then cat "$tpl/base-system.md"; return 0; fi
  sed "s/{{ROLE}}/$1/g" "$tpl/cloud-preamble.md"
  # the lead delegates and reports; the worker contract (patches, clones) is the members' own
  [ "$1" = lead ] || cloud_contract "${2:-}" || return 1
  local rd; if rd=$(role_dir "$1"); then echo; cat "$rd/ROLE.md"; fi
  [ ! -f "$rs/contract.md" ] || cat "$rs/contract.md"
  [ "$1" != lead ] || [ -z "${2:-}" ] || lead_teams_block "$2" || return 1
}

# The hashes that say whether a cloud agent's prompt is out of date, with no cloud call. sha is the hash of the whole
# rendered prompt (what refresh-prompt would push); skill is the hash of the files that change most, the contract as the prompt carries it
# (cloud_contract: contract/ and the cloud runtime's addenda) and the role text (roles/<role>/ROLE.md). Prints {sha, skill}.
prompt_stamp() { # role project
  # the prompt and the contract are rendered into variables first (a trailing x keeps the final newlines for the hash): a pipeline inside $(...)
  # cannot report the status of its first stage, and the hash of a partial prompt (an addendum that cannot be read) must never be recorded
  local p c sha k
  p=$(agent_prompt "$1" "$2" && printf x) || return 1; p=${p%x}
  c=$({ cloud_contract "$2" || exit 1; cat "$(role_dir "$1" 2>/dev/null)/ROLE.md" 2>/dev/null; true; } 2>/dev/null && printf x) || return 1; c=${c%x}
  sha=$(printf '%s' "$p" | sha256sum | cut -c1-16); k=$(printf '%s' "$c" | sha256sum | cut -c1-16)
  jq -nc --arg s "$sha" --arg k "$k" '{sha: $s, skill: $k}'
}

# prompt_state INSTANCE: current | stale skill | stale prompt | unknown | none. Compares the prompt rendered now with the
# hash recorded when the agent was provisioned or last refreshed. A registry entry with no hash is
# unknown, never stale; a local instance has no cloud prompt (none).
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

