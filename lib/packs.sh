#!/usr/bin/env bash
# Skills and tools ("packs"): one library, names globally unique, attached by scope links.
#
#   library   $XDG_CONFIG_HOME/dev-agent/packs/skills/<name>/   (a directory with SKILL.md)
#             $XDG_CONFIG_HOME/dev-agent/packs/tools/<name>.json (an MCP server with an allowlist)
#   links     $XDG_CONFIG_HOME/dev-agent/packs/links.json
#
# A link attaches a pack at a scope: user (every project and role), user-role (one role of every
# project), project (every role of one project), project-role (one role of one project). A role
# gets every pack linked at a scope that reaches it, unless the project answers disable it for
# that role (roles.<role>.packs_off). There is no precedence to learn: names cannot collide.
#
#   packs.sh skill|tool new     NAME
#   packs.sh skill|tool import  SOURCE [--name N] [--ref REF] [--path SUB] [--plan TOKEN --approved "..."]
#   packs.sh skill|tool list    [PROJECT [ROLE]]
#   packs.sh skill|tool show    NAME
#   packs.sh skill|tool seal    NAME [--plan TOKEN --approved "..."]    approve the current content (after you edited it)
#   packs.sh skill|tool link    NAME --scope S [--project P] [--role R]      unlink: the same
#   packs.sh skill|tool enable|disable PROJECT ROLE NAME                     (role-level opt-out)
#   packs.sh skill|tool effective PROJECT ROLE       what the role gets
#   packs.sh skill|tool check   PROJECT ROLE         review, drift and missing packs of that role
#   packs.sh skill|tool remove  NAME                 refused while linked
#   packs.sh packs render PROJECT ROLE OUTDIR        (provisioning)
#   packs.sh packs apply INSTANCE --asked "..." [--plan TOKEN --approved "..."]   (existing cloud agent)
#
# Imported content is untrusted instructions: it is shown (files, scripts, URLs, secret findings),
# hashed and approved before it is stored, and any later change fails `check` and provisioning
# until it is reviewed again.
. "$(dirname "$0")/lib.sh"

PACKS=$DA_CONF/packs; LINKS=$PACKS/links.json
KIND=${1:-}; VERB=${2:-}; shift 2 || true
SCOPE='' PROJECT='' ROLE='' NAME='' REF='' SUBPATH='' APPROVED='' PLAN_ARG='' ARGS=()
while [ $# -gt 0 ]; do
  case $1 in
    --scope) SCOPE=$2; shift 2;;
    --project) PROJECT=$2; shift 2;;
    --role) ROLE=$2; shift 2;;
    --name) NAME=$2; shift 2;;
    --ref) REF=$2; shift 2;;
    --path) SUBPATH=$2; shift 2;;
    --approved) APPROVED=$2; shift 2;;
    --plan) PLAN_ARG=$2; shift 2;;
    --asked) ASKED=$2; shift 2;;
    --*) die "unknown option $1";;
    *) ARGS+=("$1"); shift;;
  esac
done
export PLAN_ARG ASKED
case $KIND in skill|tool|packs) ;; *) die "usage: packs.sh skill|tool|packs <verb> ...";; esac
mkdir -p "$PACKS/skills" "$PACKS/tools"; [ -f "$LINKS" ] || echo '{"links":[]}' > "$LINKS"

item_path() { if [ "$1" = skill ]; then echo "$PACKS/skills/$2"; else echo "$PACKS/tools/$2.json"; fi; }
record_of() { if [ -d "$1" ]; then echo "$1/.pack.json"; else echo "${1%.json}.pack.json"; fi; }
content_hash() {
  if [ -d "$1" ]; then (cd "$1" && find . -type f ! -name .pack.json -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
  else sha256sum < "$1" | cut -c1-16; fi
}
write_record() { # path kind source
  jq -n --arg k "$2" --arg src "$3" --arg h "$(content_hash "$1")" --arg t "$(now)" '{kind:$k, source:$src, sha256:$h, stored:$t}' > "$(record_of "$1")"
}

# What a reviewer needs to see before trusting a pack; prints findings, returns 1 on a FAIL.
review() { # kind path
  local p=$2 rc=0 n size
  if [ "$1" = skill ]; then
    [ -f "$p/SKILL.md" ] || { echo "FAIL: no SKILL.md"; return 1; }
    head -1 "$p/SKILL.md" | grep -qx -- '---' || { echo "FAIL: SKILL.md has no front matter"; rc=1; }
    grep -q '^name: *[a-z0-9]' "$p/SKILL.md" || { echo "FAIL: SKILL.md front matter has no name"; rc=1; }
    grep -q '^description: *[^< ]' "$p/SKILL.md" || { echo "FAIL: SKILL.md front matter has no real description"; rc=1; }
    [ -z "$(find "$p" -type l)" ] || { echo "FAIL: symbolic links are not allowed"; rc=1; }
    n=$(find "$p" -type f ! -name .pack.json | wc -l); size=$(find "$p" -type f ! -name .pack.json -exec cat {} + | wc -c)
    echo "files: $n, $size bytes"
    { [ "$n" -le 100 ] && [ "$size" -le 2000000 ]; } || { echo "FAIL: more than 100 files or 2 MB"; rc=1; }
    (cd "$p" && find . -type f ! -name .pack.json | sed 's#^\./#  #' | sort | head -40)
    local scripts; scripts=$(cd "$p" && find . -type f ! -name .pack.json \( -perm /111 -o -name '*.sh' -o -name '*.py' -o -name '*.js' -o -name '*.rb' \) | sed 's#^\./#  #')
    [ -z "$scripts" ] || { echo "executable or script files (the agent may run these):"; echo "$scripts"; }
    local urls; urls=$(grep -rhoE 'https?://[A-Za-z0-9._~:/?#@!$&*+,;=%-]+' "$p" 2>/dev/null | sort -u | head -15)
    [ -z "$urls" ] || { echo "URLs mentioned:"; echo "$urls" | sed 's/^/  /'; }
    local net; net=$(grep -rnE '\b(curl|wget|ssh|scp|nc|ncat)\b' "$p" 2>/dev/null | head -8 | cut -c1-150)
    [ -z "$net" ] || { echo "network commands mentioned:"; echo "$net" | sed 's/^/  /'; }
    if grep -rqE 'sk-ant-|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY' "$p"; then echo "FAIL: looks like a secret"; rc=1; fi
  else
    jq -e . "$p" >/dev/null 2>&1 || { echo "FAIL: not valid JSON"; return 1; }
    local msg; msg=$(jq -r '
      . as $t |
      [ (if (.name|type)!="string" or ((.name|tostring)|test("^[a-z0-9][a-z0-9-]{0,40}$")|not) then "FAIL: name: lower-case letters, digits, -" else empty end),
        (if (.url|type)!="string" or ((.url|tostring)|startswith("https://")|not) or ((.url|tostring)|test("example\\.invalid|OWNER|<")) then "FAIL: url: a real https URL" else empty end),
        (if (.tools|type)!="object" or ((.tools|length)==0) then "FAIL: tools: an explicit allowlist of tool names with a policy each" else empty end),
        ((.tools // {}) | to_entries[]? | select(.value|IN("always_allow","always_ask","auto")|not) | "FAIL: tools."+.key+": policy must be always_allow, always_ask or auto"),
        ((.tools // {}) | to_entries[]? | select((.key|test("(^|_)(create|update|delete|remove|post|push|write|merge|send|set|add|edit|close|comment)")) and (.value=="always_allow" or .value=="auto") and ($t.write_ok != true)) | "FAIL: tools."+.key+": a write-like tool may not run unattended (use always_ask) unless write_ok is true on the pack, on purpose")
      ] | .[]' "$p" 2>/dev/null)
    if [ -n "$msg" ]; then echo "$msg"; rc=1; fi
    [ "$(jq -r '.write_ok // false' "$p")" != true ] || echo "NOTE: write_ok is set: write-like tools may run unattended"
    jq -r '"tools: " + ((.tools // {}) | to_entries | map(.key + "=" + .value) | join(", "))' "$p"
    jq -e '(.vault_ids // []) | all(test("^vlt_[A-Za-z0-9]+$"))' "$p" >/dev/null 2>&1 || { echo "FAIL: vault_ids must be vault ids (vlt_...), never secrets"; rc=1; }
    if grep -qE 'sk-ant-|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer [A-Za-z0-9._-]{20,}' "$p"; then echo "FAIL: looks like a secret (credentials belong in a vault)"; rc=1; fi
  fi
  return $rc
}

# The packs a role gets: every pack linked at a scope that reaches it, minus its disable list.
effective() { # project role -> "kind:name" lines
  local off='[]'
  [ -f "$DA_CONF/projects/$1.json" ] && off=$(jq -c --arg r "$2" '.roles[$r].packs_off // []' "$DA_CONF/projects/$1.json")
  jq -r --arg p "$1" --arg r "$2" --argjson off "$off" '
    [.links[] | select((.scope=="user") or (.scope=="user-role" and .role==$r) or (.scope=="project" and .project==$p) or (.scope=="project-role" and .project==$p and .role==$r)) | .pack]
    | unique | map(select(. as $x | ($off | index($x)) | not)) | .[]' "$LINKS"
}

link_args() { # validates --scope/--project/--role, prints the link as JSON
  case $SCOPE in
    user) jq -nc --arg k "$1" '{pack:$k, scope:"user"}';;
    user-role) valid_role "$ROLE" || die "user-role scope needs --role (one of: $DA_ROLES)"; jq -nc --arg k "$1" --arg r "$ROLE" '{pack:$k, scope:"user-role", role:$r}';;
    project) [ -f "$DA_CONF/projects/$PROJECT.json" ] || die "project scope needs --project with stored answers"; jq -nc --arg k "$1" --arg p "$PROJECT" '{pack:$k, scope:"project", project:$p}';;
    project-role) [ -f "$DA_CONF/projects/$PROJECT.json" ] && valid_role "$ROLE" || die "project-role scope needs --project (with stored answers) and --role"
                  jq -nc --arg k "$1" --arg p "$PROJECT" --arg r "$ROLE" '{pack:$k, scope:"project-role", project:$p, role:$r}';;
    *) die "--scope user|user-role|project|project-role";;
  esac
}

set_off() { # project role json-array
  "$(dirname "$0")/project.sh" set "$1" "roles.$2.packs_off" "$3" >/dev/null
}

if [ "$KIND" = packs ]; then
  case $VERB in
    render)
      PRJ=${ARGS[0]:-}; ROL=${ARGS[1]:-}; OUT=${ARGS[2]:-}; [ -n "$OUT" ] || die "render needs PROJECT ROLE OUTDIR"
      rm -rf "$OUT"; mkdir -p "$OUT/skills"; : > "$OUT/custom_skills.txt"; echo '[]' > "$OUT/mcp.json"
      while read -r e; do
        [ -n "$e" ] || continue; k=${e%%:*}; n=${e#*:}; P=$(item_path "$k" "$n")
        [ -e "$P" ] || die "attached pack $e is not in the library"
        review "$k" "$P" >/dev/null || die "attached pack $e fails its review (dev-agent $k check $PRJ $ROL)"
        want=$(jq -r '.sha256 // ""' "$(record_of "$P")" 2>/dev/null)
        { [ -z "$want" ] || [ "$want" = "$(content_hash "$P")" ]; } || die "attached pack $e changed since it was approved (drift); review it and re-import"
        if [ "$k" = skill ]; then cp -r "$P" "$OUT/skills/$n"; rm -f "$OUT/skills/$n/.pack.json"; echo "$n" >> "$OUT/custom_skills.txt"
        else jq -c --slurpfile t "$P" '. + $t' "$OUT/mcp.json" > "$OUT/mcp.json.tmp" && mv "$OUT/mcp.json.tmp" "$OUT/mcp.json"; fi
      done < <(effective "$PRJ" "$ROL");;
    apply)
      INST=${ARGS[0]:-}; need_asked; ant_ok
      i=$(inst_get "$INST") || exit 1; [ "$(jq -r .location <<<"$i")" = cloud ] || die "apply is for cloud instances"
      split_instance "$INST"; aid=$(jq -r .agent.id <<<"$i"); did=$(jq -r .deployment_id <<<"$i")
      W=$DA_STATE/packs/$INST; rm -rf "$W/out" "$W/apply"; mkdir -p "$W"
      "$0" packs render "$PROJECT" "$ROLE" "$W/out" || exit 1
      ag=$(ant beta:agents retrieve --agent-id "$aid" </dev/null 2>/dev/null) || die "cannot read the agent"
      aver=$(jq -r .version <<<"$ag")
      anth=$(jq -c --arg r "$ROLE" '[(.roles[$r].skills // [])[] | {type:"anthropic", skill_id:.}]' "$DA_CONF/projects/$PROJECT.json" 2>/dev/null || echo '[]')
      echo "agent $aid v$aver  ($PROJECT/$ROLE)"
      echo "  anthropic skills: $(jq -r 'map(.skill_id)|join(", ")|if .=="" then "none" else . end' <<<"$anth")"
      echo "  custom skills:    $(paste -sd, "$W/out/custom_skills.txt" | sed 's/,/, /g;s/^$/none/')"
      echo "  mcp servers:      $(jq -r 'map(.name)|join(", ")|if .=="" then "none" else . end' "$W/out/mcp.json")"
      vids=$(jq -r '[.[].vault_ids // [] | .[]] | unique | join(" ")' "$W/out/mcp.json")
      [ -z "$vids" ] || echo "  note: these tools use vault(s) $vids; attach them to the deployment, they are not attached by this command"
      tok=$({ find "$W/out" -type f -print0 | sort -z | xargs -0 cat; printf '%s|%s|%s' "$aid" "$aver" "$anth"; } | plan_token)
      if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0; fi
      need_plan "$tok"; audit_log packs-apply "$INST agent $aid v$aver"
      cust='[]'
      if [ -s "$W/out/custom_skills.txt" ]; then
        mkdir -p "$W/apply/skills"; cp -r "$W/out/skills/." "$W/apply/skills/"
        mapfile -t names < "$W/out/custom_skills.txt"
        (cd "$W/apply" && ant apply --yes --lock-file "$W/lock.json" "${names[@]/#/skills/}" </dev/null) || die "uploading the custom skills failed; the agent was not changed"
        for n in "${names[@]}"; do
          id=$(jq -r --arg n "$n" '.resources | to_entries[] | select(.key|test("skills/" + $n + "/?(SKILL.md)?$")) | .value.id' "$W/lock.json" | head -1)
          [ -n "$id" ] || die "no skill id for $n in the lock file; the agent was not changed"
          cust=$(jq -c --arg id "$id" '. + [{type:"custom", skill_id:$id, version:"latest"}]' <<<"$cust")
        done
      fi
      skills=$(jq -c -n --argjson a "$anth" --argjson c "$cust" '$a + $c')
      servers=$(jq -c 'map({type:"url", name:.name, url:.url})' "$W/out/mcp.json")
      tools=$(jq -c --slurpfile m "$W/out/mcp.json" '
        map(select(.type != "mcp_toolset")) + ($m[0] | map({type:"mcp_toolset", mcp_server_name:.name, default_config:{enabled:false},
          configs:(.tools | to_entries | map({name:.key, enabled:true, permission_policy:{type:.value}}))}))' <<<"$(jq -c .tools <<<"$ag")")
      ant beta:agents update --agent-id "$aid" --version "$aver" --skill "$skills" --mcp-server "$servers" --tool "$tools" </dev/null >/dev/null 2>&1 \
        || die "agent update failed (custom skills were uploaded)"
      ant beta:deployments update --deployment-id "$did" --agent "$aid" </dev/null >/dev/null 2>&1 || die "agent updated but re-pointing the deployment failed"
      nv=$(ant beta:deployments retrieve --deployment-id "$did" </dev/null 2>/dev/null | jq .agent.version)
      json_update "$REG" '.[$n].agent.version_pinned = $v' --arg n "$INST" --argjson v "$nv"
      echo "applied; the deployment now pins agent v$nv";;
    *) die "usage: packs.sh packs render|apply ...";;
  esac
  exit 0
fi

TEMPLATE_TOOL='{"name":"NAME","url":"https://mcp.example.invalid/","vault_ids":[],"tools":{"read_item":"always_allow"}}'

case "$VERB" in
  new)
    NAME=${NAME:-${ARGS[0]:-}}; valid_slug "$NAME" || die "new needs a NAME (lower-case letters, digits, -)"
    P=$(item_path "$KIND" "$NAME"); [ ! -e "$P" ] || die "$NAME already exists in the library (names are unique)"
    [ -z "$(ls "$PACKS/skills/$NAME" "$PACKS/tools/$NAME.json" 2>/dev/null)" ] || die "$NAME is already used by another pack (skills and tools share one namespace)"
    if [ "$KIND" = skill ]; then
      mkdir -p "$P"; printf -- '---\nname: %s\ndescription: <when to use this skill, in one or two sentences>\n---\n\n# %s\n\n<the instructions the agent follows>\n' "$NAME" "$NAME" > "$P/SKILL.md"
    else printf '%s\n' "${TEMPLATE_TOOL//NAME/$NAME}" | jq . > "$P"; fi
    write_record "$P" "$KIND" created; audit_log "$KIND-new" "$NAME"
    echo "created $KIND $NAME: $P"; echo "edit it, then link it: dev-agent $KIND link $NAME --scope S ...";;
  import)
    SRC=${ARGS[0]:-}; [ -n "$SRC" ] || die "import needs a SOURCE (a directory or file, or an https git URL)"
    T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; SRCREC=$SRC
    if [[ $SRC == https://* ]]; then
      git clone -q --depth 1 ${REF:+--branch "$REF"} "$SRC" "$T/repo" </dev/null 2>/dev/null || die "could not clone $SRC"
      SRCREC="$SRC@$(git -C "$T/repo" rev-parse HEAD)${SUBPATH:+ path $SUBPATH}"; rm -rf "$T/repo/.git"; WORK=$T/repo${SUBPATH:+/$SUBPATH}
    else WORK=$SRC; [ -e "$WORK" ] || die "no such source: $SRC"; fi
    if [ "$KIND" = skill ]; then
      [ -d "$WORK" ] || die "a skill source is a directory with SKILL.md"
      NAME=${NAME:-$(sed -n 's/^name: *//p' "$WORK/SKILL.md" 2>/dev/null | head -1)}
      cp -r "$WORK" "$T/stage"; rm -f "$T/stage/.pack.json"
    else
      [ -f "$WORK" ] || die "a tool source is a JSON file"
      NAME=${NAME:-$(jq -r .name "$WORK" 2>/dev/null)}; cp "$WORK" "$T/stage"
    fi
    valid_slug "$NAME" || die "cannot work out a valid name; pass --name"
    [ -z "$(ls "$PACKS/skills/$NAME" "$PACKS/tools/$NAME.json" 2>/dev/null)" ] || die "$NAME already exists in the library (names are unique; pass --name or remove the old one)"
    echo "== review of $KIND $NAME from $SRCREC"
    review "$KIND" "$T/stage" || { echo "refused: fix the source first" >&2; exit 1; }
    TOK=$(content_hash "$T/stage")
    if [ -z "$APPROVED" ]; then echo "plan token: $TOK   (store it with: --plan $TOK --approved \"<the user's go-ahead after reading the review>\")"; exit 0; fi
    need_plan "$TOK"; audit_log "$KIND-import" "$NAME from $SRCREC"
    P=$(item_path "$KIND" "$NAME"); mv "$T/stage" "$P"; write_record "$P" "$KIND" "$SRCREC"
    echo "stored $KIND $NAME (content $TOK); link it to a scope to attach it";;
  list)
    PRJ=${ARGS[0]:-}; ROL=${ARGS[1]:-}
    for f in "$PACKS/${KIND}s"/*; do
      [ -e "$f" ] || continue; case $f in *.pack.json) continue;; esac; n=$(basename "$f" .json); mark=''
      [ -z "$PRJ" ] || [ -z "$ROL" ] || { effective "$PRJ" "$ROL" | grep -qx "$KIND:$n" && mark='  [attached to '$PRJ/$ROL']'; }
      lk=$(jq -r --arg k "$KIND:$n" '[.links[] | select(.pack==$k) | .scope + (if .project then ":"+.project else "" end) + (if .role then "/"+.role else "" end)] | join(", ")' "$LINKS")
      echo "$n   links: ${lk:-none}$mark"
    done;;
  show)
    NAME=${ARGS[0]:-}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    echo "path: $P"; jq . "$(record_of "$P")" 2>/dev/null; jq -r --arg k "$KIND:$NAME" '.links[] | select(.pack==$k) | "link: " + tostring' "$LINKS"; review "$KIND" "$P" || true;;
  seal)
    NAME=${ARGS[0]:-}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    echo "== review of $KIND $NAME"; review "$KIND" "$P" || { echo "refused: fix it first" >&2; exit 1; }
    TOK=$(content_hash "$P")
    if [ -z "$APPROVED" ]; then echo "plan token: $TOK   (approve this content with: --plan $TOK --approved \"<the user's go-ahead after reading the review>\")"; exit 0; fi
    need_plan "$TOK"; audit_log "$KIND-seal" "$NAME $TOK"
    src=$(jq -r '.source // "created"' "$(record_of "$P")" 2>/dev/null); write_record "$P" "$KIND" "$src"; echo "sealed $KIND $NAME (content $TOK)";;
  link|unlink)
    NAME=${ARGS[0]:-}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    L=$(link_args "$KIND:$NAME")
    if [ "$VERB" = link ]; then
      review "$KIND" "$P" >/dev/null || die "the pack fails its review: dev-agent $KIND show $NAME"
      want=$(jq -r '.sha256 // ""' "$(record_of "$P")" 2>/dev/null)
      [ "$want" = "$(content_hash "$P")" ] || die "$NAME changed since it was approved; review and approve it: dev-agent $KIND seal $NAME"
      json_update "$LINKS" '.links = ((.links + [$l]) | unique)' --argjson l "$L"
    else json_update "$LINKS" '.links = (.links | map(select(. != $l)))' --argjson l "$L"; fi
    audit_log "$KIND-$VERB" "$L"; echo "$VERB: $L";;
  enable|disable)
    PRJ=${ARGS[0]:-}; ROL=${ARGS[1]:-}; N=${ARGS[2]:-}
    [ -f "$DA_CONF/projects/$PRJ.json" ] || die "no stored answers for project '$PRJ'"
    jq -e --arg r "$ROL" '.roles[$r]' "$DA_CONF/projects/$PRJ.json" >/dev/null || die "role '$ROL' is not enabled for $PRJ"
    cur=$(jq -c --arg r "$ROL" '.roles[$r].packs_off // []' "$DA_CONF/projects/$PRJ.json")
    if [ "$VERB" = disable ]; then new=$(jq -c --arg e "$KIND:$N" '. + [$e] | unique' <<<"$cur")
    else new=$(jq -c --arg e "$KIND:$N" 'map(select(. != $e))' <<<"$cur"); fi
    set_off "$PRJ" "$ROL" "$new"; audit_log "$KIND-$VERB" "$PRJ $ROL $N"; echo "$PRJ/$ROL packs_off: $new";;
  effective) effective "${ARGS[0]:-}" "${ARGS[1]:-}" | grep "^$KIND:" | sed "s/^$KIND://";;
  check)
    PRJ=${ARGS[0]:-}; ROL=${ARGS[1]:-}; rc=0; any=''
    while read -r e; do
      [ "${e%%:*}" = "$KIND" ] || continue; any=1; n=${e#*:}; P=$(item_path "$KIND" "$n")
      if [ ! -e "$P" ]; then echo "FAIL $e: linked but not in the library"; rc=1; continue; fi
      want=$(jq -r '.sha256 // ""' "$(record_of "$P")" 2>/dev/null); have=$(content_hash "$P")
      if [ -n "$want" ] && [ "$want" != "$have" ]; then echo "FAIL $e: content changed since it was approved (drift: $want -> $have); review it and re-import"; rc=1; fi
      if out=$(review "$KIND" "$P" 2>&1); then echo "ok   $e"; else echo "$out" | grep -E '^FAIL' | sed "s/^/$e: /"; rc=1; fi
    done < <(effective "$PRJ" "$ROL")
    [ -n "$any" ] || echo "no $KIND packs reach $PRJ/$ROL"
    exit $rc;;
  remove)
    NAME=${NAME:-${ARGS[0]:-}}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    [ "$(jq -r --arg k "$KIND:$NAME" '[.links[] | select(.pack==$k)] | length' "$LINKS")" = 0 ] || die "$NAME is linked; unlink it from every scope first (dev-agent $KIND show $NAME)"
    audit_log "$KIND-remove" "$NAME"; rm -rf "$P" "$(record_of "$P")"; echo "removed $KIND $NAME";;
  *) die "usage: packs.sh skill|tool new|import|list|show|seal|link|unlink|enable|disable|effective|check|remove ...";;
esac
