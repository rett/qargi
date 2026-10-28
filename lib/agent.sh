#!/usr/bin/env bash
# Members: the local agents that do the work, named by you. qargi ships one member definition
# (agents/member.md); `add` renders it under the name you choose, with the abilities it serves
# (build, write, review, test; each ability is defined by the skill qargi-<ability>, which the
# member loads when a task block names it). The members are recorded in $XDG_CONFIG_HOME/qargi/agents.json.
#
#   agent.sh add NAME [--abilities build,write,review,test] [--model M] [--effort E] [--project P]
#   agent.sh list
#   agent.sh rename OLD NEW
#   agent.sh remove NAME
#   agent.sh for ABILITY [--project P]     the member that serves ABILITY: dispatch spawns it
. "$(dirname "$0")/lib.sh"

root=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
TEMPLATE=$root/agents/member.md
ABILITIES_ALL="build write review test"
# the agent types Claude Code brings itself; a member must not shadow one
BUILTIN="general-purpose explore plan statusline-setup claude-code-guide claude output-style-setup"

verb=${1:-}; shift || true
POS=() ABIL='' MODEL='' EFFORT='' PROJ=''
while [ $# -gt 0 ]; do
  case $1 in
    --abilities) ABIL=$2; shift 2;;
    --model) MODEL=$2; shift 2;;
    --effort) EFFORT=$2; shift 2;;
    --project) PROJ=$2; shift 2;;
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
  case $n in lead|build|write|review|test) die "'$n' is a role of qargi; name the member after itself, for example forge or scribe";; esac
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

render() { # name abilities-csv model -> the definition on stdout
  sed -e "s/{{NAME}}/$1/g" -e "s/{{ABILITIES}}/$(printf '%s' "$2" | sed 's/,/, /g')/g" -e "s/{{MODEL}}/$3/g" "$TEMPLATE"
}

add() {
  local n=${POS[0]:-} a list='' dir file seq
  [ -n "$n" ] || die "usage: qargi agent add NAME [--abilities build,write,review,test] [--model M] [--effort E] [--project P]"
  valid_name "$n"
  jq -e --arg n "$n" 'has($n)' "$MEMBERS_FILE" >/dev/null && die "a member named $n exists already (qargi agent list)"
  for a in $(printf '%s' "${ABIL:-build,write,review,test}" | tr ',' ' '); do
    case " $ABILITIES_ALL " in *" $a "*) ;; *) die "--abilities: a comma-separated list of build, write, review, test";; esac
    case ",$list," in *",$a,"*) ;; *) list=${list:+$list,}$a;; esac
  done
  [ -n "$list" ] || die "--abilities: give at least one"
  MODEL=${MODEL:-sonnet}
  printf '%s' "$MODEL" | grep -Eq '^[a-z0-9][a-z0-9.-]*$' || die "--model: a model alias or id (letters, digits, . -)"
  case $EFFORT in ''|low|medium|high|xhigh|max) ;; *) die "--effort low|medium|high|xhigh|max";; esac
  [ -f "$TEMPLATE" ] || die "the member definition is missing: $TEMPLATE"
  dir=$(agents_dir "$PROJ") || exit 1; file=$dir/$n.md
  [ ! -e "$file" ] && [ ! -L "$file" ] || die "$file exists already; choose another name or remove it first"
  mkdir -p "$dir"; render "$n" "$list" "$MODEL" > "$file"
  [ -z "$PROJ" ] || hide_in_git "$(dirname "$(dirname "$dir")")" ".claude/agents/$n.md"
  seq=$(jq '[.[].seq // 0] | max // 0 | . + 1' "$MEMBERS_FILE")
  json_update "$MEMBERS_FILE" '.[$n] = {abilities: ($a | split(",")), file: $f, model: $m, effort: (if $e == "" then null else $e end),
      project: (if $p == "" then null else $p end), created: $t, seq: $s}' \
    --arg n "$n" --arg a "$list" --arg f "$file" --arg m "$MODEL" --arg e "$EFFORT" --arg p "$PROJ" --arg t "$(now)" --argjson s "$seq"
  echo "member $n ($list) at $file"
}

member_for() { # ability project-or-empty -> the first member registered for it (the project's own members first)
  jq -r --arg a "$1" --arg p "$2" '[to_entries[] | select(.value.abilities | index($a))]
      | sort_by((if (.value.project // "") == $p and $p != "" then 0 elif (.value.project // null) == null then 1 else 2 end), (.value.seq // 0))
      | map(select((.value.project // null) == null or .value.project == $p)) | .[0].key // empty' "$MEMBERS_FILE"
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
  remove)
    n=${POS[0]:-}; [ -n "$n" ] || die "usage: qargi agent remove NAME"
    rec=$(jq -ce --arg n "$n" '.[$n]' "$MEMBERS_FILE") || die "no member named $n (qargi agent list)"
    f=$(jq -r .file <<<"$rec"); [ ! -f "$f" ] || rm -f "$f"
    json_update "$MEMBERS_FILE" 'del(.[$n])' --arg n "$n"
    echo "removed member $n${f:+ ($f)}";;
  for)
    a=${POS[0]:-}
    case " $ABILITIES_ALL " in *" $a "*) ;; *) die "usage: qargi agent for build|write|review|test [--project P]";; esac
    [ -n "$PROJ" ] || PROJ=$(python3 -I "$root/lib/help.py" infer)
    m=$(member_for "$a" "$PROJ")
    [ -n "$m" ] || die "no member serves the $a ability: qargi agent add NAME --abilities $a"
    echo "$m";;
  *) die "usage: qargi agent add|list|rename|remove|for ...";;
esac
