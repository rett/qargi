#!/usr/bin/env bash
# Members: the local agents that do the work, named by you. qargi ships one member definition
# (agents/member.md); `add` renders it under the name you choose, with the abilities it serves
# (roles: build, write, review, test and yours; a task block carries the role's text). The members are recorded in ~/.qargi/config/agents.json.
#
#   agent.sh add NAME [--abilities build,write,review,test] [--model M] [--effort E] [--project P]
#   agent.sh list
#   agent.sh rename OLD NEW
#   agent.sh refresh NAME      re-render a member from the current definition, keeping its name, abilities, model and effort
#   agent.sh models [--project P] [--json]     the bases, the profiles (shipped and the project's), the members and what is wrong with them
#   agent.sh remove NAME
#   agent.sh for ROLE [--profile P] [--project P] [--json]     the member, model and effort for ROLE under a profile: dispatch spawns it
. "$(dirname "$0")/lib.sh"

root=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
TEMPLATE=$root/agents/member.md
DEFAULTS=$root/lib/model-defaults.json   # the one table: the bases (one per guard class) and the profiles (a base, a tier and an effort each)
PROVIDERS=$root/lib/providers            # one data file per provider: its model id for each tier
# the agent types Claude Code brings itself; a member must not shadow one
BUILTIN="general-purpose explore plan statusline-setup claude-code-guide claude output-style-setup"

verb=${1:-}; shift || true
POS=() ABIL='' MODEL='' EFFORT='' PROJ='' JSON='' PROFILE=''
while [ $# -gt 0 ]; do
  case $1 in
    --abilities) ABIL=$2; shift 2;;
    --model) MODEL=$2; shift 2;;
    --effort) EFFORT=$2; shift 2;;
    --project) PROJ=$2; shift 2;;
    --profile) PROFILE=$2; shift 2;;
    --json) JSON=1; shift;;
    -*) die "unknown option $1";;
    *) POS+=("$1"); shift;;
  esac
done

valid_name() { # name -> dies with the rule
  local n=$1 b lc
  printf '%s' "$n" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' && [ "${#n}" -le 40 ] \
    || die "'$n' is not a member name: kebab-case, lower-case letters, digits and single '-' (at most 40)"
  lc=$(printf '%s' "$n" | tr '[:upper:]' '[:lower:]')
  for b in $BUILTIN; do [ "$lc" != "$b" ] || die "'$n' is a built-in Claude Code agent type; choose another name"; done
  if [ "$n" = lead ] || valid_role "$n"; then die "'$n' is a role; name the member after itself, for example forge or scribe"; fi
}

agents_dir() { # project-or-empty -> the directory the definition goes to
  if [ -n "$1" ]; then
    local f=$DA_CONF/projects/$1.json rp
    [ -f "$f" ] || die "no stored answers for $1"
    rp=$(jq -r '.repo.path // ""' "$f"); rp=${rp/#\~/$HOME}
    [ -n "$rp" ] && [ -d "$rp" ] || die "--project $1: its answers name no local repository (repo.path)"
    echo "$rp/.claude/agents"
  else
    echo "$HOME/.claude/agents"
  fi
}

hide_in_git() { # repo file: keep a project-level definition out of the repository's commits
  local repo=$1 rel=$2 ex
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || return 0
  ex=$(git -C "$repo" rev-parse --git-path info/exclude); case $ex in /*) ;; *) ex=$repo/$ex;; esac
  mkdir -p "$(dirname "$ex")"; touch "$ex"
  grep -qx -F "/$rel" "$ex" || printf '/%s\n' "$rel" >> "$ex"
}

default_row() { # ability -> the table's profile row for it (a role of yours falls back to its class: write -> build, read-only -> review)
  case " $ROLE_BUILTIN " in *" $1 "*) jq -e --arg a "$1" '.profiles | has($a)' "$DEFAULTS" >/dev/null && { echo "$1"; return; };; esac
  case $(role_class "$1" 2>/dev/null) in read-only) echo review;; *) echo build;; esac
}

project_answer() { # project ability field(model|effort) -> the project's valid answer, or nothing
  local f=$DA_CONF/projects/$1.json v
  [ -n "$1" ] && [ -f "$f" ] || return 0
  v=$(jq -r --arg a "$2" --arg k "$3" 'if $a == "lead" then .lead[$k] else .roles[$a][$k] end // empty' "$f" 2>/dev/null) || return 0
  case $3 in
    model) printf '%s' "$v" | grep -Eq '^[a-z0-9][a-z0-9.-]*$' && echo "$v";;
    effort) case $v in low|medium|high|xhigh|max) echo "$v";; esac;;
  esac
  return 0
}

provider_for() { # project-or-empty -> the active provider (the project's models.provider, default claude); dies when it has no file
  local f=$DA_CONF/projects/$1.json p=claude
  [ -z "$1" ] || [ ! -f "$f" ] || p=$(jq -r '.models.provider // "claude" | tostring' "$f" 2>/dev/null) || p=claude
  if ! printf '%s' "$p" | grep -Eq '^[a-z][a-z0-9-]*$' || [ ! -f "$PROVIDERS/$p.json" ]; then
    die "models.provider '$p' has no file under lib/providers/; available: $(find "$PROVIDERS" -name '*.json' -exec basename {} .json \; | sort | paste -sd, - | sed 's/,/, /g')"
  fi
  echo "$p"
}

tier_model() { # provider tier -> the provider's model id
  jq -r --arg t "$2" '.tiers[$t]' "$PROVIDERS/$1.json"
}

default_for() { # project ability field -> the project's answer for it, else the table's value (a tier is resolved through the active provider)
  local v; v=$(project_answer "$1" "$2" "$3")
  if [ -z "$v" ]; then
    if [ "$3" = model ]; then v=$(tier_model "$(provider_for "$1")" "$(jq -r --arg r "$(default_row "$2")" '.profiles[$r].tier' "$DEFAULTS")")
    else v=$(jq -r --arg r "$(default_row "$2")" --arg k "$3" '.profiles[$r][$k]' "$DEFAULTS"); fi
  fi
  echo "$v"
}

render() { # name abilities-csv model [effort] -> the definition on stdout
  # a member that only reviews is read-only by class, named in its hook command (under the protected agents directory)
  local ga=' --class read-only' a
  for a in $(printf '%s' "$2" | tr ',' ' '); do [ "$(role_class "$a")" = read-only ] || ga=''; done
  local el="/^{{EFFORT_LINE}}\$/d"
  [ -z "${4:-}" ] || el="s/^{{EFFORT_LINE}}\$/effort: $4/"
  sed -e "$el" -e "s/{{GUARD_ARGS}}/$ga/g" -e "s/{{NAME}}/$1/g" -e "s/{{ABILITIES}}/$(printf '%s' "$2" | sed 's/,/, /g')/g" -e "s/{{MODEL}}/$3/g" "$TEMPLATE"
}

add() {
  local n=${POS[0]:-} a list='' dir file seq first
  [ -n "$n" ] || die "usage: qargi agent add NAME [--abilities build,write,review,test] [--model M] [--effort E] [--project P]"
  valid_name "$n"
  jq -e --arg n "$n" 'has($n)' "$MEMBERS_FILE" >/dev/null && die "a member named $n exists already (qargi agent list)"
  for a in $(printf '%s' "${ABIL:-build,write,review,test}" | tr ',' ' '); do
    [ "$a" != lead ] && valid_role "$a" || die "--abilities: a comma-separated list of roles ($DA_ROLES; qargi role list)"
    case ",$list," in *",$a,"*) ;; *) list=${list:+$list,}$a;; esac
  done
  [ -n "$list" ] || die "--abilities: give at least one"
  first=${list%%,*}
  [ -z "$PROJ" ] || provider_for "$PROJ" >/dev/null || exit 1
  [ -n "$MODEL" ] || MODEL=$(default_for "$PROJ" "$first" model)
  [ -n "$EFFORT" ] || EFFORT=$(default_for "$PROJ" "$first" effort)
  printf '%s' "$MODEL" | grep -Eq '^[a-z0-9][a-z0-9.-]*$' || die "--model: a model alias or id (letters, digits, . -)"
  case $EFFORT in ''|low|medium|high|xhigh|max) ;; *) die "--effort low|medium|high|xhigh|max";; esac
  [ -f "$TEMPLATE" ] || die "the member definition is missing: $TEMPLATE"
  dir=$(agents_dir "$PROJ") || exit 1; file=$dir/$n.md
  [ ! -e "$file" ] && [ ! -L "$file" ] || die "$file exists already; choose another name or remove it first"
  mkdir -p "$dir"; render "$n" "$list" "$MODEL" "$EFFORT" > "$file"
  [ -z "$PROJ" ] || hide_in_git "$(dirname "$(dirname "$dir")")" ".claude/agents/$n.md"
  seq=$(jq '[.[].seq // 0] | max // 0 | . + 1' "$MEMBERS_FILE")
  json_update "$MEMBERS_FILE" '.[$n] = {abilities: ($a | split(",")), file: $f, model: $m, effort: (if $e == "" then null else $e end),
      project: (if $p == "" then null else $p end), created: $t, seq: $s}' \
    --arg n "$n" --arg a "$list" --arg f "$file" --arg m "$MODEL" --arg e "$EFFORT" --arg p "$PROJ" --arg t "$(now)" --argjson s "$seq"
  echo "member $n ($list) at $file"
}

# The profile resolver, in jq. Inputs ($d the table, $tiers and $aliases the provider's, $pf the project's answers or {}, $rc each role's class):
# `profiles` is the list of every profile, the shipped ones with the project's entries merged over them key by key. It is defensive:
# a malformed entry, key or value is ignored, never an error; what cannot be honoured is marked in `refused`.
PJQ=$(cat <<'EOF'
def okeff: . == "low" or . == "medium" or . == "high" or . == "xhigh" or . == "max";
def okmod: type == "string" and test("^[a-z0-9][a-z0-9.-]*$");
def tier_of($m): ([$aliases | to_entries[] | select(.value == $m) | .key][0]) // ([$tiers | to_entries[] | select(.value == $m) | .key][0]);
def pclean: if type == "object" then
    {} + (if (.base | type) == "string" then {base} else {} end)
       + (if (.tier | type) == "string" and (.tier | test("^[a-z]+$")) then {tier} else {} end)
       + (if (.model | okmod) then {model} else {} end)
       + (if (.effort | okeff) then {effort} else {} end)
       + (if (.purpose | type) == "string" then {purpose} else {} end)
       + (if (.abilities | type) == "array" then {abilities: [.abilities[] | select(type == "string")]} else {} end)
  else null end;
def pprofiles: (($pf.profiles // {}) | if type == "object" then . else {} end)
  | with_entries(select((.key | test("^[a-z][a-z0-9-]{0,30}$")) and .key != "lead") | .value |= pclean)
  | with_entries(select(.value != null));
def legacy($n): (if $n == "lead" then $pf.lead else (($pf.roles // {}) | .[$n]?) end)
  | if type == "object" then {model: (if (.model | okmod) then .model else null end), effort: (if (.effort | okeff) then .effort else null end)} else {model: null, effort: null} end;
def profiles:
  $d[0].profiles as $sh | pprofiles as $pp | $d[0].bases as $bases
  | [($sh | keys_unsorted[]), (($pp | keys_unsorted) - ($sh | keys_unsorted))[]][] as $n
  | $sh[$n] as $s | $pp[$n] as $p
  | (if $p == null then legacy($n) else {model: null, effort: null} end) as $lg
  | (($s // {}) + ($p // {})) as $m
  | ($m.base // null) as $base
  | (if $p.model then {k: "m", v: $p.model} elif $p.tier then {k: "t", v: $p.tier} elif $lg.model then {k: "m", v: $lg.model}
     else {k: "t", v: ($m.tier // "balanced")} end) as $sel
  | (if $sel.k == "m" then tier_of($sel.v) as $t | {tier: ($t // $m.tier // null), alias: (if $t then ($aliases[$t] // null) else null end), id: (if $t then ($tiers[$t] // null) else $sel.v end)}
     else {tier: $sel.v, alias: ($aliases[$sel.v] // null), id: ($tiers[$sel.v] // null)} end) as $r
  | (if $base == null then (if $n == "lead" then null else "no base: give base worker or reviewer" end)
     elif $bases[$base] == null then "base \($base) is not a base (\($bases | keys | join(", ")))"
     elif ([($m.abilities // [])[] | select($rc[.] != null and $rc[.] != $bases[$base].class)] | length) > 0
       then "abilities \(($m.abilities // []) | join(",")) do not fit base \($base) (\($bases[$base].class))"
     else null end) as $refused
  | {name: $n, base: $base, class: (if $base != null then ($bases[$base].class? // null) else null end), tier: $r.tier, model: $r.alias, model_id: $r.id,
     effort: ($p.effort // $lg.effort // $m.effort // "medium"), opt_in: ($s.opt_in // false), purpose: ($m.purpose // ""),
     abilities: ($m.abilities // null), shipped: ($s != null), project: ($p != null), via_roles: (($lg.model != null or $lg.effort != null)),
     source: (if $p != null or $lg.model != null or $lg.effort != null then "project" else "shipped" end), refused: $refused};
EOF
)

pf_json() { # project-or-empty -> the project's stored answers as one object ({} when there are none or they are unreadable)
  local f=$DA_CONF/projects/$1.json
  if [ -n "$1" ] && [ -f "$f" ]; then jq -c 'if type == "object" then . else {} end' "$f" 2>/dev/null || echo '{}'; else echo '{}'; fi
}

role_classes() { # -> {role: class} for every role (a role without a readable class is left out)
  local r c o='{}'
  for r in $DA_ROLES; do
    [ "$r" != lead ] || continue
    c=$(role_class "$r" 2>/dev/null) || continue
    o=$(jq -c --arg r "$r" --arg c "$c" '.[$r] = $c' <<<"$o")
  done
  echo "$o"
}

models() { # the bases, the profiles with the project's own merged in, the escalation and the registered members
  local proj=$PROJ pf prov tiers aliases rc out
  if [ -n "$proj" ]; then [ -f "$DA_CONF/projects/$proj.json" ] || die "no stored answers for $proj"
  else proj=$(python3 -I "$root/lib/help.py" infer); fi
  pf=$(pf_json "$proj")
  prov=$(provider_for "$proj") || exit 1
  tiers=$(jq -c .tiers "$PROVIDERS/$prov.json"); aliases=$(jq -c '.aliases // {}' "$PROVIDERS/$prov.json")
  rc=$(role_classes)
  out=$(jq -n --slurpfile d "$DEFAULTS" --slurpfile m "$MEMBERS_FILE" --argjson pf "$pf" --argjson tiers "$tiers" --argjson aliases "$aliases" --argjson rc "$rc" --arg prov "$prov" "$PJQ"'
    ($d[0].bases) as $bases
    | {provider: $prov, aliases: $aliases,
       bases: ($bases | with_entries(.key as $k | .value += {registered: ($m[0] | has($k))})),
       profiles: ([profiles | {key: .name, value: .}] | from_entries),
       escalate: ($d[0].escalate | with_entries(.value = {tier: .value, model: $tiers[.value]})),
       members: [$m[0] | to_entries | sort_by(.value.seq // 0)[] | {name: .key, abilities: .value.abilities, model: (.value.model // null),
         effort: (.value.effort // null), project: (.value.project // null),
         pinned: ((.value.model // "") | startswith("claude-")),
         frontier: (((.value.model // "") == $tiers.frontier) or ((.value.model // "") == $aliases.frontier))}]}')
  if [ -n "$JSON" ]; then printf '%s\n' "$out"; return 0; fi
  echo "bases (one member each, by guard class)"
  jq -r '.bases | to_entries[] | [.key, .value.class, (.value.abilities | join(",")), (if .value.registered then "registered" else "not registered" end)] | @tsv' <<<"$out" \
    | while IFS=$'\t' read -r n c a r; do printf '  %-10s %-10s %-18s %s\n' "$n" "$c" "$a" "$r"; done
  echo "profiles (provider: $prov; tier -> alias -> model/effort; a role of yours uses its class: write -> build, read-only -> review)"
  jq -r '.profiles[] | [.name, (.base // "-"), ((.tier // "?") + " -> " + (.model // "-") + " -> " + (.model_id // "-") + "/" + (.effort // "default")),
      (.source + (if .via_roles then " (roles)" else "" end)), (if .opt_in then "opt-in" elif .name == "lead" then "never dispatched" else "" end)] | @tsv' <<<"$out" \
    | while IFS=$'\t' read -r n b d s t; do printf '  %-11s %-9s %-52s %-10s %s\n' "$n" "$b" "$d" "$s" "$t"; done
  jq -r '"  offer \(.escalate.build.tier) (\(.escalate.build.model)) for a hard task: only when asked"' <<<"$out"
  echo "members"
  if [ "$(jq '.members | length' <<<"$out")" = 0 ]; then echo "  none yet (qargi agent add NAME)"; else
    jq -r '.members[] | "  \(.name)\t\(.abilities | join(","))\t\(.model // "-")/\(.effort // "default")\t\(if .frontier then "frontier (opt-in)" else "" end)"' <<<"$out" \
      | while IFS=$'\t' read -r n a me note; do printf '  %-12s %-22s %-28s %s\n' "${n# }" "$a" "$me" "$note"; done
  fi
}

# the dispatch resolver, in jq (with $PJQ): one role, one profile -> the base member, model and effort, or an error with its exit code
RESOLVEJQ='
  def mclass: if ((.abilities // []) | length) > 0 and all((.abilities // [])[]; $rc[.] == "read-only") then "read-only" else "write" end;
  def serves($a): any((.abilities // [])[]; . == $a);
  [profiles | {key: .name, value: .}] | from_entries as $P
  | $d[0].bases as $bases
  | (if $rclass == "read-only" then "review" else "build" end) as $row
  | (if $prof != "" then $prof elif $P[$role] != null then $role else null end) as $want
  | (if $want != null then $want else $row end) as $pn
  | $P[$pn] as $p
  | ($m[0] | to_entries | map(select((.value.project // null) == null or .value.project == $proj))
      | sort_by((if (.value.project // "") == $proj and $proj != "" then 0 else 1 end), (.value.seq // 0))) as $E
  | def cands($a): [$E[] | select(.value | serves($a) and mclass == $rclass)];
    if $p == null then {code: 1, err: "no profile named \($pn) (qargi agent models lists them)"}
    elif $p.base == null then {code: 2, err: "the \($pn) profile has no base and is never dispatched"}
    elif $p.refused != null then {code: 2, err: "the \($pn) profile is refused: \($p.refused)"}
    elif $p.class != $rclass then {code: 2, err: "the \($role) role is \($rclass) but the \($pn) profile has base \($p.base), which is \($p.class); use a profile of a \($rclass) base"}
    else
      ([$E[] | select(.key == $p.base and (.value | (any((.abilities // [])[]; $rc[.] == $rclass)) and mclass == $p.class))][0]) as $b
      | (if $b != null then {m: $b, legacy: false}
         else (cands($role)[0] // (if $row != $role then cands($row)[0] else null end)) as $l | if $l != null then {m: $l, legacy: true} else null end end) as $sel
      | if $sel == null then {code: 1, err: "no member serves the \($role) role: qargi agent add NAME --abilities \($role)"}
        else {code: 0, out: {role: $role, class: $rclass, profile: $pn,
          profile_source: (if $want == null then "class-fallback" elif $p.source == "project" then "project" else "shipped" end),
          base: $p.base, member: $sel.m.key, member_scope: (if $sel.m.value.project != null then "project" else "user" end), legacy: $sel.legacy,
          tier: $p.tier, model: $p.model, model_id: $p.model_id, effort: $p.effort, opt_in: $p.opt_in, purpose: $p.purpose}} end
    end'

resolve_for() { # role profile-or-empty project-or-empty -> prints the answer, or the reason on stderr (exit 1, or 2 for a refusal)
  local role=$1 prof=$2 proj=$3 pf prov res code
  pf=$(pf_json "$proj"); prov=$(provider_for "$proj") || exit 1
  res=$(jq -n --slurpfile d "$DEFAULTS" --slurpfile m "$MEMBERS_FILE" --argjson pf "$pf" --argjson tiers "$(jq -c .tiers "$PROVIDERS/$prov.json")" \
    --argjson aliases "$(jq -c '.aliases // {}' "$PROVIDERS/$prov.json")" --argjson rc "$(role_classes)" \
    --arg role "$role" --arg rclass "$(role_class "$role")" --arg prof "$prof" --arg proj "$proj" "$PJQ$RESOLVEJQ") || die "could not resolve the profile"
  code=$(jq -r .code <<<"$res")
  if [ "$code" != 0 ]; then echo "qargi: $(jq -r .err <<<"$res")" >&2; exit "$code"; fi
  if [ -n "$JSON" ]; then jq '.out' <<<"$res"; return 0; fi
  jq -r '.out | "\(.member) \(.model // "-") \(.effort // "default") \(.profile)"' <<<"$res"
  if [ "$(jq -r '.out.model // ""' <<<"$res")" = "" ]; then
    echo "qargi: warning: model $(jq -r '.out.model_id' <<<"$res") has no alias; the definition of member $(jq -r .out.member <<<"$res") applies" >&2
  fi
}

case $verb in
  add) add;;
  list)
    jq -r 'to_entries | sort_by(.value.seq // 0)[] | [.key, (.value.abilities | join(",")), (if .value.project then "project " + .value.project else "user" end),
        (.value.model // "-") + "/" + (.value.effort // "default"), .value.file] | @tsv' "$MEMBERS_FILE" \
      | while IFS=$'\t' read -r n a s m f; do
          [ -f "$f" ] || f="$f (MISSING)"
          printf '%s\t%s\t%s\t%s\t%s\n' "$n" "$a" "$s" "$m" "$f"
        done | column -t -s "$(printf '\t')"
    [ "$(jq length "$MEMBERS_FILE")" != 0 ] || echo "no members yet: qargi agent add NAME [--abilities build,write,review,test]";;
  rename)
    old=${POS[0]:-}; new=${POS[1]:-}
    [ -n "$old" ] && [ -n "$new" ] || die "usage: qargi agent rename OLD NEW"
    rec=$(jq -ce --arg n "$old" '.[$n]' "$MEMBERS_FILE") || die "no member named $old (qargi agent list)"
    valid_name "$new"
    jq -e --arg n "$new" 'has($n)' "$MEMBERS_FILE" >/dev/null && die "a member named $new exists already"
    f=$(jq -r .file <<<"$rec"); nf=$(dirname "$f")/$new.md
    [ ! -e "$nf" ] || die "$nf exists already"
    if [ -f "$f" ]; then sed "s/^name: $old\$/name: $new/" "$f" > "$nf" && rm -f "$f"; fi
    json_update "$MEMBERS_FILE" '.[$new] = (.[$old] | .file = $f) | del(.[$old])' --arg old "$old" --arg new "$new" --arg f "$nf"
    echo "renamed member $old -> $new ($nf)";;
  refresh)
    n=${POS[0]:-}; [ -n "$n" ] || die "usage: qargi agent refresh NAME"
    rec=$(jq -ce --arg n "$n" '.[$n]' "$MEMBERS_FILE") || die "no member named $n (qargi agent list)"
    [ -f "$TEMPLATE" ] || die "the member definition is missing: $TEMPLATE"
    f=$(jq -r .file <<<"$rec"); [ -n "$f" ] || die "member $n records no definition file"
    new=$(render "$n" "$(jq -r '.abilities | join(",")' <<<"$rec")" "$(jq -r '.model // "sonnet"' <<<"$rec")" "$(jq -r '.effort // ""' <<<"$rec")")
    if [ -f "$f" ] && [ "$new" = "$(cat "$f")" ]; then echo "member $n is current ($f)"; exit 0; fi
    mkdir -p "$(dirname "$f")"; printf '%s\n' "$new" > "$f.tmp.$$" && mv -f "$f.tmp.$$" "$f"
    echo "refreshed member $n ($f); sessions started afterwards use it";;
  models) models;;
  remove)
    n=${POS[0]:-}; [ -n "$n" ] || die "usage: qargi agent remove NAME"
    rec=$(jq -ce --arg n "$n" '.[$n]' "$MEMBERS_FILE") || die "no member named $n (qargi agent list)"
    f=$(jq -r .file <<<"$rec"); [ ! -f "$f" ] || rm -f "$f"
    json_update "$MEMBERS_FILE" 'del(.[$n])' --arg n "$n"
    echo "removed member $n${f:+ ($f)}";;
  for)
    a=${POS[0]:-}
    [ -n "$a" ] && [ "$a" != lead ] && valid_role "$a" || die "usage: qargi agent for ROLE [--profile P] [--project P] [--json]   (a role of: $DA_ROLES)"
    [ -z "$PROFILE" ] || printf '%s' "$PROFILE" | grep -Eq '^[a-z][a-z0-9-]{0,30}$' || die "--profile: a profile name (lower-case letters, digits and '-', at most 31)"
    [ -n "$PROJ" ] || PROJ=$(python3 -I "$root/lib/help.py" infer)
    resolve_for "$a" "$PROFILE" "$PROJ";;
  *) die "usage: qargi agent add|list|models|rename|refresh|remove|for ...";;
esac
