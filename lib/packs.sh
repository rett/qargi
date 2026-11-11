#!/usr/bin/env bash
# Skills and tools ("packs"): one library, names globally unique, attached by scope links.
#
#   library   ~/.qargi/config/packs/skills/<name>/   (a directory with SKILL.md)
#             ~/.qargi/config/packs/tools/<name>.json (an MCP server with an allowlist)
#   links     ~/.qargi/config/packs/links.json
#
# A link attaches a pack at a scope: user (every project and role), user-role (one role of every
# project), project (every role of one project), project-role (one role of one project). A role
# gets every pack linked at a scope that reaches it, unless the project answers disable it for
# that role (roles.<role>.packs_off). There is no precedence to learn: names cannot collide.
#
#   packs.sh skill|tool new     NAME --compatible LIST
#   packs.sh skill|tool import  SOURCE --compatible LIST [--name N] [--ref REF] [--path SUB] [--plan TOKEN --approved "..."]
#   packs.sh skill|tool list    [PROJECT [ROLE]]
#   packs.sh skill|tool show    NAME
#   packs.sh skill|tool seal    NAME [--compatible LIST] [--plan TOKEN --approved "..."]    approve the current content (after you edited it)
#   packs.sh tool import|seal   ... --tool-list FILE    judge the pack's tools by the server's own tool listing too (below)
#   packs.sh skill|tool link    NAME --scope S [--project P] [--role R]      unlink: the same
#   packs.sh skill|tool enable|disable PROJECT ROLE NAME                     (role-level opt-out)
#   packs.sh skill accept PROJECT NAME [--user] [--plan TOKEN --approved "..."]   accept a skill a session loads that qargi does not manage
#   packs.sh skill unaccept PROJECT NAME [--user] [--plan TOKEN --approved "..."] take the acceptance back
#   packs.sh skill|tool effective PROJECT ROLE       what the role gets
#   packs.sh skill|tool check   PROJECT ROLE         review, drift and missing packs of that role
#   packs.sh skill|tool remove  NAME                 refused while linked
#   packs.sh packs render PROJECT ROLE OUTDIR        (provisioning)
#   packs.sh packs load [NAME] --role R [--project P]   what the role has enabled, or one pack's text (reads only)
#   packs.sh packs apply INSTANCE --asked "..." [--plan TOKEN --approved "..."]   (existing cloud agent)
#   packs.sh packs apply --target T PROJECT [--plan TOKEN --approved "..."]   render for a local session of the project's runtime
#   packs.sh packs check --target T PROJECT                                  drift of that render, then the skills a session would load (read only)
#                      (T is the render target of the project's local runtime, session.render_target in lib/providers/NAME.json: claude-code for Claude Code)
#   packs.sh packs link|unlink PROJECT [--plan TOKEN --approved "..."]   make the checkout's project skills directory a symlink to that render, or undo it
#                                                                       (the plan also lists the skills a session would load)
#   packs.sh packs seed [--install] [--plan TOKEN --approved "..."]    add or update the baseline packs shipped in packs/
#
# Every pack declares which providers can use it, compatible_providers: runtime names, family names, or the single word "any"
# (--compatible LIST: comma separated, or a JSON array). It is kept in the pack's record and covered by the content hash, so it is
# approved with the content and a change of it is drift. A pack that does not declare it fails its review. A pack that declares a list
# the project's provider is not on is skipped for that project, with a note that says so (lib/packs_compat.py), never attached silently.
#
# Imported content is untrusted instructions: it is shown (files, scripts, URLs, secret findings),
# hashed and approved before it is stored, and any later change fails `check` and provisioning
# until it is reviewed again.
#
# A tool pack names the tools of an MCP server it allows and a policy for each. The review refuses a tool whose name says it writes
# as always_allow or auto unless the pack says write_ok (lib/packs_check.py has the rule). `tool import|seal --tool-list FILE` also
# takes the server's own tool listing (the JSON result of MCP tools/list, as a file; no server is ever contacted): a tool the listing
# does not mark readOnlyHint true is then refused as always_allow or auto without write_ok, one it marks destructiveHint true is
# reported, and the record keeps the listing's sha256 and what it says of the pack's tools (tool_list). tool_list is covered by the
# content hash like compatible_providers, so it is approved with the pack; a seal without --tool-list keeps the record's.
. "$(dirname "$0")/lib.sh"

PACKS=$DA_CONF/packs; LINKS=$PACKS/links.json
KIND=${1:-}; VERB=${2:-}; shift 2 || true
COMPAT_ARG='' INSTALL='' USER_SCOPE='' RENDER_ONLY='' TARGET='' SCOPE='' PROJECT='' ROLE='' NAME='' REF='' SUBPATH='' APPROVED='' PLAN_ARG='' TOOL_LIST='' ARGS=()
while [ $# -gt 0 ]; do
  case $1 in
    --scope) need_val "$1" $#; SCOPE=$2; shift 2;;
    --project) need_val "$1" $#; PROJECT=$2; shift 2;;
    --role) need_val "$1" $#; ROLE=$2; shift 2;;
    --name) need_val "$1" $#; NAME=$2; shift 2;;
    --ref) need_val "$1" $#; REF=$2; shift 2;;
    --path) need_val "$1" $#; SUBPATH=$2; shift 2;;
    --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;;
    --asked) need_val "$1" $#; ASKED=$2; shift 2;;
    --compatible) need_val "$1" $#; COMPAT_ARG=$2; shift 2;;
    --target) need_val "$1" $#; TARGET=$2; shift 2;;
    --tool-list) need_val "$1" $#; TOOL_LIST=$2; shift 2;;
    --install) INSTALL=1; shift;;
    --user) USER_SCOPE=1; shift;;
    '--render-only') RENDER_ONLY=1; shift;;   # internal (lib/local.sh): check the render alone, without the section of the skills a session would load
    --*) usage_die "unknown option $1";;
    *) ARGS+=("$1"); shift;;
  esac
done
export PLAN_ARG ASKED
COMPATPY=$(dirname "$(readlink -f "$0")")/packs_compat.py
REVIEWPY=$(dirname "$(readlink -f "$0")")/conformance/review.py
CHECKPY=$(dirname "$(readlink -f "$0")")/packs_check.py   # the per-pack work of check and list in one process: hash, review, compatibility

# The provider of a project serves a verb only when its descriptor says so (lib/provider.py layout, require-skills): a null layout
# field or an unverified skills capability ends the verb here with exit 3 and "provider NAME has no FACILITY: WOULD".
prov_of() { # project: sets PROV (the runtime of the project's local surface, where a session loads the render; there is no default, none is exit 2), RTOP (<state>/render), RPRJ (the project's renders) and RLIVE (the render for PROV)
  PROV=$(project_provider "$1" local) || exit $?; RTOP=$DA_STATE/render; RPRJ=$RTOP/$1; RLIVE=$RPRJ/$PROV
}
prov_need() { # project would field...: prov_of, then the refusals above
  local would=$2 f; prov_of "$1"; shift 2
  pymod provider require-skills "$PROV" --would "$would" || exit $?
  for f; do pymod provider layout "$PROV" "$f" --would "$would" >/dev/null || exit $?; done
}
case $KIND in skill|tool|packs) ;; *) usage_die "usage: packs.sh skill|tool|packs <verb> ...";; esac
[ -z "$TOOL_LIST" ] || case $KIND:$VERB in tool:import|tool:seal) ;; *) usage_die "--tool-list FILE (the server's own tool listing) goes with qargi tool import and qargi tool seal";; esac
# Changing a skill needs a present person (library/SPEC.md, "Who may modify a skill"): need_plan always checks the token, so
# no environment variable stands in for it here.
need_token() { # expected-token; never empty, and never skipped
  [ -n "${1:-}" ] || die "internal error: no plan token to check; nothing was changed"
  need_plan "$1"
}
mkdir -p "$PACKS/skills" "$PACKS/tools"; [ -f "$LINKS" ] || echo '{"links":[]}' > "$LINKS"

item_path() { if [ "$1" = skill ]; then echo "$PACKS/skills/$2"; else echo "$PACKS/tools/$2.json"; fi; }
record_of() { if [ -d "$1" ]; then echo "$1/.pack.json"; else echo "${1%.json}.pack.json"; fi; }
compat_of() { # path -> the compatible_providers of the pack's record as compact sorted JSON; empty when the record has none
  jq -cS '.compatible_providers | select(. != null) | if type == "array" then unique else . end' "$(record_of "$1")" 2>/dev/null
}
compat_parse() { # LIST (names separated by commas, or a JSON array) -> compact, sorted JSON on stdout; status 1 and the problem on stderr
  local j why
  case $1 in
    '['*) j=$(jq -cS 'if type == "array" then unique else . end' <<<"$1" 2>/dev/null) || j=$1;;
    *) j=$(jq -nc --arg s "$1" '$s | split(",") | map(gsub("^ +| +$"; "")) | unique');;
  esac
  why=$(python3 -I "$COMPATPY" valid "$j") || { echo "compatible_providers: $why" >&2; return 1; }
  printf '%s\n' "$j"
}
compat_need() { # the --compatible of a verb that makes a pack: parsed, or the verb ends
  [ -n "${COMPAT_ARG:-}" ] || usage_die "$VERB needs --compatible LIST: the providers that can use this pack, runtime or family names separated by commas, or any (it is kept with the pack and approved with its content)"
  compat_parse "$COMPAT_ARG" || exit 1
}
# The content hash of a pack: its files, and compatible_providers (given as the second argument, else the record's own; a pack with no
# declaration hashes as its files alone, and fails its review). The hash is what approval stores, so the declaration is approved with the content.
# A directory pack's hash also covers what is not a regular file of one name: a link, a pipe, a socket, an empty directory, a file with a second name
# (with its type, link count and link target). They fail the review, and a pack that gains one after approval is drift. A pack with none of them
# hashes as its files alone, so every hash made without them is unchanged.
tl_of() { # path -> the tool_list of a tool pack's record (what the server's tool listing said of its tools, kept at approval) as compact sorted JSON; empty when the record has none, and for a skill
  [ -d "$1" ] || jq -cS '.tool_list | select(. != null)' "$(record_of "$1")" 2>/dev/null
  return 0
}
# A tool pack's hash also covers the tool_list of its record (given as the third argument, else the record's own), so what the listing said is
# approved with the pack and a change of it is drift. A pack with none hashes as before.
content_hash() { # path [compat-json [tool-list-json]]
  local h c x t
  if [ -d "$1" ]; then
    h=$(cd "$1" && find . -type f ! -path ./.pack.json -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
    x=$(cd "$1" && find . ! -path . ! -path ./.pack.json \( \( ! -type f ! -type d \) -o \( -type d -empty \) -o \( -type f -links +1 \) \) -printf '%y %n %P -> %l\0' | LC_ALL=C sort -z | tr '\0' '\n')
    [ -z "$x" ] || h=$({ printf '%s\nnon-regular entries\n' "$h"; printf '%s\n' "$x"; } | sha256sum | cut -c1-16)
  else h=$(sha256sum < "$1" | cut -c1-16); fi
  if [ $# -ge 2 ]; then c=$2; else c=$(compat_of "$1"); fi
  if [ $# -ge 3 ]; then t=$3; else t=$(tl_of "$1"); fi
  [ -z "$c" ] || h=$(printf '%s\ncompatible_providers=%s\n' "$h" "$c" | sha256sum | cut -c1-16)
  [ -z "$t" ] || h=$(printf '%s\ntool_list=%s\n' "$h" "$t" | sha256sum | cut -c1-16)
  echo "$h"
}
write_record() { # path kind source compat-json [tool-list-json]: a record made here has the tool_list it is given, or none
  jq -n --arg k "$2" --arg src "$3" --arg h "$(content_hash "$1" "$4" "${5-}")" --arg t "$(now)" --argjson c "$4" --argjson tl "${5:-null}" \
    '{kind:$k, source:$src, sha256:$h, stored:$t, compatible_providers:$c} + (if $tl == null then {} else {tool_list:$tl} end)' > "$(record_of "$1")"
}
# The tool_list of --tool-list FILE for the tool pack at a path: lib/packs_check.py reads the listing (a file; no server is contacted) and prints what
# it says of the pack's tools. The verb ends when FILE is no listing.
tl_need() { # path -> the tool_list JSON on stdout; status 1 and the reason on stderr when FILE is no listing
  python3 -I "$CHECKPY" toollist "$TOOL_LIST" "$1"
}

showable() { python3 -I "$REVIEWPY" vis; }   # stdin with control, escape and bidi characters written out: what a pack holds never reaches the terminal raw

# What a reviewer needs to see before trusting a pack; prints findings, returns 1 on a FAIL.
review() { # kind path [compat-json [tool-list-json]]: the declaration is the third argument while the pack has no record yet (import, seed), else the record's; so is the tool_list of a tool pack, the fourth
  local p=$2 rc=0 n size c cw tl=()
  [ $# -lt 4 ] || tl=("$4")
  if [ $# -ge 3 ]; then c=$3; else c=$(compat_of "$p"); fi
  if cw=$(python3 -I "$COMPATPY" valid "$c"); then echo "compatible_providers: $(jq -r 'join(", ")' <<<"$c")"
  else echo "FAIL: compatible_providers: $cw"; rc=1; fi
  if [ "$1" = skill ]; then
    [ -f "$p/SKILL.md" ] || { echo "FAIL: no SKILL.md"; return 1; }
    head -1 "$p/SKILL.md" | grep -qx -- '---' || { echo "FAIL: SKILL.md has no front matter"; rc=1; }
    grep -q '^name: *[a-z0-9]' "$p/SKILL.md" || { echo "FAIL: SKILL.md front matter has no name"; rc=1; }
    grep -q '^description: *[^< ]' "$p/SKILL.md" || { echo "FAIL: SKILL.md front matter has no real description"; rc=1; }
    # the owner's policy for every pack: only text (no binary, archive, special file or symbolic link, no NUL byte, invalid UTF-8, control or
    # bidi character in a file or its name); the failures come escaped, from the same rules as the provider packs (conformance/review.py)
    pol=$(python3 -I "$REVIEWPY" policy "$p" 2>&1) || { echo "$pol"; rc=1; }
    n=$(find "$p" -type f ! -path "$p/.pack.json" | wc -l); size=$(find "$p" -type f ! -path "$p/.pack.json" -exec cat {} + | wc -c)
    # the top-level .pack.json is qargi's own record of a library pack and no part of the skill; one deeper is skill content that nothing
    # reads as a record (it would pass for an approval), so it is a finding, and it counts in the content hash like any file
    local nested; nested=$(cd "$p" && find . -mindepth 2 -name .pack.json | sed 's#^\./#  #' | sort)
    [ -z "$nested" ] || { echo "FAIL: .pack.json is qargi's own record and only the top level of a library pack holds it; remove or rename these:"; echo "$nested" | showable; rc=1; }
    echo "files: $n, $size bytes"
    { [ "$n" -le 100 ] && [ "$size" -le 2000000 ]; } || { echo "FAIL: more than 100 files or 2 MB"; rc=1; }
    (cd "$p" && find . -type f ! -path ./.pack.json | sed 's#^\./#  #' | sort | head -40) | showable
    local scripts; scripts=$(cd "$p" && find . -type f ! -path ./.pack.json \( -perm /111 -o -name '*.sh' -o -name '*.py' -o -name '*.js' -o -name '*.rb' \) | sed 's#^\./#  #')
    [ -z "$scripts" ] || { echo "executable or script files (the agent may run these):"; echo "$scripts" | showable; }
    local urls; urls=$(grep -rhoE 'https?://[A-Za-z0-9._~:/?#@!$&*+,;=%-]+' "$p" 2>/dev/null | sort -u | head -15)
    [ -z "$urls" ] || { echo "URLs mentioned:"; echo "$urls" | sed 's/^/  /' | showable; }
    local net; net=$(grep -rnE '\b(curl|wget|ssh|scp|nc|ncat)\b' "$p" 2>/dev/null | head -8 | cut -c1-150)
    [ -z "$net" ] || { echo "network commands mentioned:"; echo "$net" | sed 's/^/  /' | showable; }
    if grep -rqE 'sk-ant-|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY' "$p"; then echo "FAIL: looks like a secret"; rc=1; fi
  else
    # the owner's policy for every pack, tool packs too: only UTF-8 text, and no control or bidi character in the file or, after the JSON
    # escapes are decoded, in any key or string (\u001b is plain ASCII on disk); everything below is printed through showable
    pol=$(python3 -I "$REVIEWPY" policy "$p" 2>&1) || { echo "$pol"; rc=1; }
    jq -e . "$p" >/dev/null 2>&1 || { echo "FAIL: not valid JSON"; return 1; }
    # the findings about the document: its name, its URL, the tools map, the name and the policy of each tool, a write-like tool that would run
    # unattended, and what the server's tool listing says of the tools (the tool_list given, else the record's). One definition of them, in
    # lib/packs_check.py (tool_msgs); a review that cannot ask it fails. The NOTE lines among them are for the person and fail nothing
    local msg; msg=$(python3 -I "$CHECKPY" toolmsgs "$p" ${tl[@]+"${tl[@]}"}) || { echo "FAIL: the findings about the tool pack could not be worked out (lib/packs_check.py toolmsgs failed)"; rc=1; }
    if [ -n "$msg" ]; then echo "$msg" | showable; ! grep -q '^FAIL' <<<"$msg" || rc=1; fi
    [ "$(jq -r '.write_ok // false' "$p")" != true ] || echo "NOTE: write_ok is set: write-like tools may run unattended"
    jq -r '"tools: " + ((.tools // {}) | to_entries | map(.key + "=" + (.value|tostring)) | join(", "))' "$p" | showable
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

# True when no pack reaches any role of the project (effective() is empty for every role): the case where a check would only say that nothing was rendered.
none_linked() { # project
  local r
  for r in $(jq -r '.roles | keys[]' "$DA_CONF/projects/$1.json" 2>/dev/null | grep -vx lead); do
    [ -z "$(effective "$1" "$r")" ] || return 1
  done
  return 0
}

# The packs of effective() that the project's provider can use. SURFACES is local, cloud or local,cloud (a pack is used when its
# declaration matches the runtime of at least one of them). CP_OK gets the kind:name lines to attach, CP_SKIP one "kind<TAB>name<TAB>why"
# per pack the project's provider cannot use. Only a pack that DECLARES a list the provider is not on is skipped: a pack in the links
# that is missing from the library, or does not declare compatible_providers, or changed since it was approved (the declaration is
# part of the approved content), stays in CP_OK so that it fails loudly where it is used (its review, its drift check), and "any"
# needs no provider at all.
compat_filter() { # project role surfaces
  local kind a b c
  CP_OK=(); CP_SKIP=()
  # one process for all the packs (packs_check.py filter, the rules above): "ok<TAB>kind:name" or "skip<TAB>kind<TAB>name<TAB>why" per pack
  while IFS=$'\t' read -r kind a b c; do
    case $kind in
      ok) CP_OK+=("$a");;
      skip) CP_SKIP+=("$a"$'\t'"$b"$'\t'"$c");;
    esac
  done < <(effective "$1" "$2" | python3 -I "$CHECKPY" filter "$1" "$3" "$PACKS" "$DA_CONF")
}
skip_say() { # prefix: one line per CP_SKIP entry
  local x k n why
  for x in ${CP_SKIP[@]+"${CP_SKIP[@]}"}; do IFS=$'\t' read -r k n why <<<"$x"; echo "$1skipped $k $n: $why"; done
}

link_args() { # validates --scope/--project/--role, prints the link as JSON
  case $SCOPE in
    user) jq -nc --arg k "$1" '{pack:$k, scope:"user"}';;
    user-role) valid_role "$ROLE" || usage_die "user-role scope needs --role (one of: $DA_ROLES)"; jq -nc --arg k "$1" --arg r "$ROLE" '{pack:$k, scope:"user-role", role:$r}';;
    project) [ -f "$DA_CONF/projects/$PROJECT.json" ] || usage_die "project scope needs --project with stored answers"; jq -nc --arg k "$1" --arg p "$PROJECT" '{pack:$k, scope:"project", project:$p}';;
    project-role) [ -f "$DA_CONF/projects/$PROJECT.json" ] && valid_role "$ROLE" || usage_die "project-role scope needs --project (with stored answers) and --role"
                  jq -nc --arg k "$1" --arg p "$PROJECT" --arg r "$ROLE" '{pack:$k, scope:"project-role", project:$p, role:$r}';;
    *) usage_die "--scope user|user-role|project|project-role";;
  esac
}

set_off() { # project role json-array
  "$(dirname "$0")/project.sh" set "$1" "roles.$2.packs_off" "$3" >/dev/null
}

# The render target: the facts only this script knows (links, review, hashes) go to packs_render.py as one JSON file.
rn_inputs() { # project outfile
  local prj=$1 out=$2 roles r e k n rows x why
  [ -f "$DA_CONF/projects/$prj.json" ] || die "no stored answers for project '$prj'"
  roles=$(jq -r '.roles | keys[]' "$DA_CONF/projects/$prj.json" | grep -vx lead)
  # the render is for the local surface; a pack the provider of that surface cannot use is left out and noted (skipped)
  : > "$out.skips"; rows=''
  for r in $roles; do
    compat_filter "$prj" "$r" local
    for e in ${CP_OK[@]+"${CP_OK[@]}"}; do rows+="$r $e"$'\n'; done
    for x in ${CP_SKIP[@]+"${CP_SKIP[@]}"}; do
      IFS=$'\t' read -r k n why <<<"$x"
      jq -nc --arg k "$k" --arg n "$n" --arg w "$why" --arg r "$r" '{kind:$k,name:$n,why:$w,role:$r}' >> "$out.skips"
    done
  done
  : > "$out.rows"
  # the facts of each pack (path, content hash, approved hash, whether its review passes; an unreadable file fails it), one process for all of them
  printf '%s' "$rows" | python3 -I "$CHECKPY" rows "$PACKS" "$out.rows"
  jq -s --arg p "$prj" --arg v "$PROV" --arg s "$DA_STATE" --arg h "$HOME" --arg c "$(jq -r '.repo.path // ""' "$DA_CONF/projects/$prj.json")" --argjson none "$(jq -c '.packs.none == true' "$DA_CONF/projects/$prj.json")" --slurpfile sk "$out.skips" '
    {project:$p, provider:$v, state:$s, home:$h, checkout:$c, packs_none:$none,
     packs: (group_by(.kind+":"+.name) | map({kind:.[0].kind, name:.[0].name, path:.[0].path, sha256:.[0].sha256, approved:.[0].approved,
                                              review_ok:.[0].review_ok, exists:.[0].exists, compatible_providers:.[0].compatible_providers, roles:(map(.role)|unique)})),
     skipped: ($sk | group_by(.kind+":"+.name) | map({kind:.[0].kind, name:.[0].name, why:.[0].why, roles:(map(.role)|unique)}))}' "$out.rows" > "$out"
  rm -f "$out.rows" "$out.skips"
}
# The audit of the skills a session opened in the checkout would load (lib/packs_audit.py): the script finds the directories (scan) and
# hashes them with strict_hash (links, modes and empty directories count; content_hash is the library's approval hash and does not see
# them), the shell adds the library's approval of the same name and the acceptances file, and the script judges.
au_inputs() { # ccinputs outfile: the render inputs plus every visible skill (scan hashes it with strict_hash) and the library's approval of its name
  local cc=$1 out=$2
  python3 -I "$(dirname "$(readlink -f "$0")")/packs_audit.py" scan "$cc" "$out.scan" || return 1
  # the library's hash and approval of each name, one process for all the skills (packs_check.py audit)
  python3 -I "$CHECKPY" audit "$PACKS" "$cc" "$out.scan" "$out" || { rm -f "$out.scan"; return 1; }
  rm -f "$out.scan"
}
au_report() { # ccinputs workdir: print the section; the status is 1 when a skill is drifted
  if au_inputs "$1" "$2/au.json"; then python3 -I "$(dirname "$(readlink -f "$0")")/packs_audit.py" report "$2/au.json"
  else echo "skills a session would load: cannot be listed"; return 0; fi
}
rn_launch() { # dir: the exact command that loads the render (the provider's session_launch)
  local c; c=$(pymod provider launch "$PROV" "$1") || exit $?
  echo "launch: $c"
}
rn_cleanup() { # the temporary files, this run's staging directory and the lock file, whatever the exit
  local st
  if [ -n "${RN_W:-}" ]; then
    st=$(jq -r '.stage // empty' "$RN_W/token.stage" 2>/dev/null)
    [ -z "$st" ] || [ "$(dirname "$st")" != "${RPRJ:-}" ] || rm -rf "$st"
    rm -rf "$RN_W"
  fi
  [ -z "${RN_LK:-}" ] || rm -f "$RN_LK"
}
rn_lock() { # project: exclusive lock for plan+swap on render/.PROJECT.lock; the file is removed at exit, so re-check the inode
  RN_LK=$RTOP/.$1.lock
  while :; do
    [ ! -L "$RN_LK" ] || rm -f "$RN_LK"
    exec 9>"$RN_LK" || die "cannot open the lock file $RN_LK"
    flock 9 || die "cannot lock $RN_LK"
    [ /proc/self/fd/9 -ef "$RN_LK" ] && break
  done
}
# --target names the render target of the project's local runtime (session.render_target of its definition). The renderer is the
# same for every runtime (packs_render.py, which reads the skills directory, the MCP form and the settings form from the definition).
rt_say() { # project-or-empty: "--target is RT (...)", RT the render target of the project's provider (or a description of it when that is not known)
  local rt='' pv
  if [ -n "${1:-}" ] && pv=$(pymod provider of "$1" --conf "$DA_CONF" --surface local 2>/dev/null </dev/null); then rt=$(pymod provider layout "$pv" render_target 2>/dev/null </dev/null) || rt=''; fi
  echo "--target is ${rt:-the render target of the provider of the project} (or managed-agents / none for a cloud instance); check needs --target ${rt:-that target}"
}
rt_main() { # verb: apply|check with --target
  local prj=${ARGS[0]:-} rt
  [ -n "$TARGET" ] || die "$(rt_say "$prj")"
  [ -n "$prj" ] || usage_die "$1 --target $TARGET needs PROJECT"
  prov_of "$prj"
  rt=$(pymod provider layout "$PROV" render_target --would "render the project's packs for a local session") || exit $?
  [ "$TARGET" = "$rt" ] || die "--target is $rt for provider $PROV (or managed-agents / none for a cloud instance); check needs --target $rt"
  rn_main "$1"
}
rn_main() { # verb: apply|check
  local prj=${ARGS[0]:-} PY tok live
  [ -n "$prj" ] || usage_die "$1 --target $TARGET needs PROJECT"
  PY=$(dirname "$(readlink -f "$0")")/packs_render.py
  RN_W=$(mktemp -d); RN_LK=''; trap rn_cleanup EXIT
  rn_inputs "$prj" "$RN_W/in.json"
  live=$RLIVE
  [ "$1" = check ] || prov_need "$prj" "render the project's packs for a local session" project_skills_dir
  if [ "$1" = check ]; then
    # read only: the section of the skills a session would load follows; only a drifted one adds to the exit status
    local rc=0
    prov_need "$prj" "list the skills a session would load" project_skills_dir
    [ "$(jq -r '.packs.none == true' "$DA_CONF/projects/$prj.json")" = true ] || ! none_linked "$prj" || echo "no pack is linked to any role of $prj (qargi skill link NAME --scope project --project $prj)"
    python3 -I "$PY" check "$RN_W/in.json" || rc=1
    [ -n "$RENDER_ONLY" ] || au_report "$RN_W/in.json" "$RN_W" || rc=1
    exit $rc
  fi
  python3 -I "$PY" prep "$RN_W/in.json" || exit 1
  rn_lock "$prj"
  python3 -I "$PY" plan "$RN_W/in.json" "$RN_W/token" || exit 1
  tok=$(cat "$RN_W/token")
  if [ -z "$APPROVED" ]; then
    echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0
  fi
  need_token "$tok"
  audit_log packs-apply-claude-code "$prj $tok"
  python3 -I "$PY" swap "$RN_W/in.json" "$RN_W/token.stage" "$tok" || exit 1
  echo "applied: $live"; rn_launch "$live"
  exit 0
}

# packs link|unlink: CHECKOUT/<project skills dir of the provider> as a symbolic link to the render of the provider's render
# target. The shell gathers the facts only it knows (the content hashes of a real skills directory's skills and of the library
# packs of the same names), packs_link.py
# classifies, plans and acts. Same gating as rn_main: no --approved prints the token; apply re-plans and needs the token to match.
cl_inputs() { # project outfile: the render inputs plus the skills of a real project skills directory in the checkout
  local prj=$1 out=$2 co sk d n kids='[]'
  rn_inputs "$prj" "$out.cc"
  co=$(jq -r .checkout "$out.cc"); sk=$co/$(pymod provider layout "$PROV" project_skills_dir)
  if [ -n "$co" ] && [ -d "$(dirname "$sk")" ] && [ ! -L "$(dirname "$sk")" ] && [ -d "$sk" ] && [ ! -L "$sk" ]; then
    while IFS= read -r -d '' d; do
      [ -f "$d/SKILL.md" ] || continue
      n=$(basename "$d")
      kids=$(jq -c --arg n "$n" --argjson l "$([ -d "$PACKS/skills/$n" ] && echo true || echo false)" '. + [{name:$n, in_library:$l}]' <<<"$kids")
    done < <(find "$sk" -mindepth 1 -maxdepth 1 -type d -print0)
  fi
  jq --argjson k "$kids" '. + {kids:$k}' "$out.cc" > "$out"; rm -f "$out.cc"
}
cl_main() { # verb: link|unlink
  local prj=${ARGS[0]:-} PY tok
  [ -n "$prj" ] || usage_die "packs $1 needs PROJECT"
  valid_project "$prj" || die "not a project name: $prj"
  PY=$(dirname "$(readlink -f "$0")")/packs_link.py
  prov_need "$prj" "link the checkout's skills directory to the render" project_skills_dir
  RN_W=$(mktemp -d); RN_LK=''; trap rn_cleanup EXIT
  # the same per-project lock as the render's apply; without a render directory there is nothing to race with
  if [ -d "$RTOP" ] && [ ! -L "$RTOP" ]; then rn_lock "$prj"; fi
  cl_inputs "$prj" "$RN_W/in.json"
  jq -r '.skipped[]? | "skipped \(.kind) \(.name): \(.why)"' "$RN_W/in.json"
  python3 -I "$PY" plan "$1" "$RN_W/in.json" "$RN_W/token" || exit 1
  # the plan is shown with what a session would load now (a drifted skill is not a reason to stop here: it only informs)
  [ -n "$APPROVED" ] || au_report "$RN_W/in.json" "$RN_W" || true
  [ -s "$RN_W/token" ] || exit 0   # already linked: no plan, no token
  tok=$(cat "$RN_W/token")
  if [ -z "$APPROVED" ]; then
    echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0
  fi
  need_token "$tok"
  audit_log "packs-$1" "$prj $tok"
  python3 -I "$PY" apply "$1" "$RN_W/in.json" "$tok" || exit 1
  exit 0
}

# skill accept|unaccept: the owner's record, in accepted.json, of a skill a session loads that qargi does not manage (see the
# audit above). Gated like packs link: the plan prints the review of the skill and a token over scope, name and content hash,
# and apply re-plans and needs the token to match. The --approved text is stored with the record, not verified. One lock
# for the file, since the acceptances of every project share it; the script writes it atomically, mode 600.
ac_main() { # verb: accept|unaccept
  local prj=${ARGS[0]:-} name=${ARGS[1]:-} scope=project who tok hash real shown AUPY ACC rec
  [ "$KIND" = skill ] || die "$1 is for skills: qargi skill $1 PROJECT NAME"
  [ -n "$prj" ] && [ -n "$name" ] || usage_die "skill $1 needs PROJECT NAME"
  valid_project "$prj" || die "not a project name: $prj"
  # [[ =~ ]] anchors at the end of the string; grep -E '$' would accept a trailing newline
  { [[ $name =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] && [[ $name != *$'\n'* ]]; } || die "not a skill name: $name"
  [ -z "$USER_SCOPE" ] || scope=user
  who=$scope; [ "$scope" = user ] || who=project:$prj
  [ "$1" != accept ] || prov_need "$prj" "audit the skills a session would load" project_skills_dir
  AUPY=$(dirname "$(readlink -f "$0")")/packs_audit.py; ACC=$PACKS/accepted.json
  RN_W=$(mktemp -d); RN_LK=''; trap rn_cleanup EXIT
  exec 8>"$ACC.lock" || die "cannot open the lock file $ACC.lock"
  flock 8 || die "cannot lock $ACC.lock"
  if [ "$1" = accept ]; then
    rn_inputs "$prj" "$RN_W/cc.json"
    au_inputs "$RN_W/cc.json" "$RN_W/au.json" || exit 1
    python3 -I "$AUPY" target "$RN_W/au.json" "$name" "$scope" "$RN_W/target.json" || exit 1
    hash=$(jq -r .hash "$RN_W/target.json"); real=$(jq -r .real "$RN_W/target.json"); shown=$(jq -r .path "$RN_W/target.json")
    echo "== review of skill $name at $(printf '%s' "$shown" | tr -d '\000-\037\177')"
    review skill "$real" || echo "note: the review has FAIL findings; accepting takes the skill as it is, qargi does not store or change it"
    tok=$(printf 'skill-accept|%s|%s|%s' "$who" "$name" "$hash" | plan_token)
  else
    rec=$(python3 -I "$AUPY" acceptance "$ACC" "$scope" "$prj" "$name") || exit 1
    hash=$(jq -r .sha256 <<<"$rec")
    echo "unaccept plan for $prj: remove the acceptance of skill $name ($who, content $hash)"
    echo "  accepted at $(jq -r '.at // "?"' <<<"$rec") from $(jq -r '.path // "?"' <<<"$rec"), approved: $(jq -r '.approved // ""' <<<"$rec")"
    echo "  the skill itself is not touched; qargi lists it as unmanaged again."
    tok=$(printf 'skill-unaccept|%s|%s|%s' "$who" "$name" "$hash" | plan_token)
  fi
  if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0; fi
  need_token "$tok"
  audit_log "skill-$1" "$prj $name $hash $who $tok"
  if [ "$1" = accept ]; then
    python3 -I "$AUPY" store accept "$ACC" "$scope" "$prj" "$name" "$hash" "$shown" "$APPROVED" "$(now)" || exit 1
    echo "accepted skill $name (content $hash) for $([ "$scope" = user ] && echo every project || echo "project $prj"); qargi skill unaccept $prj $name${USER_SCOPE:+ --user} undoes it"
  else
    python3 -I "$AUPY" store unaccept "$ACC" "$scope" "$prj" "$name" || exit 1
    echo "unaccepted skill $name ($who)"
  fi
  exit 0
}

case $VERB in accept|unaccept) ac_main "$VERB";; esac

if [ "$KIND" = packs ]; then
  case $VERB:$TARGET in
    link:*|unlink:*) cl_main "$VERB";;
    apply:|apply:managed-agents) ;;
    apply:none) die "$(rt_say "${ARGS[0]:-}")";;
    apply:*|check:*) rt_main "$VERB";;
  esac
  case $VERB in
    render)
      PRJ=${ARGS[0]:-}; ROL=${ARGS[1]:-}; OUT=${ARGS[2]:-}; [ -n "$OUT" ] || usage_die "render needs PROJECT ROLE OUTDIR"
      rm -rf "$OUT"; mkdir -p "$OUT/skills"; : > "$OUT/custom_skills.txt"; echo '[]' > "$OUT/mcp.json"
      compat_filter "$PRJ" "$ROL" cloud; skip_say "note: " >&2   # the cloud render is for the project's cloud provider
      for e in ${CP_OK[@]+"${CP_OK[@]}"}; do
        k=${e%%:*}; n=${e#*:}; P=$(item_path "$k" "$n")
        [ -e "$P" ] || die "attached pack $e is not in the library"
        review "$k" "$P" >/dev/null || die "attached pack $e fails its review (qargi $k check $PRJ $ROL)"
        want=$(jq -r '.sha256 // ""' "$(record_of "$P")" 2>/dev/null)
        { [ -z "$want" ] || [ "$want" = "$(content_hash "$P")" ]; } || die "attached pack $e changed since it was approved (drift); review it and re-import"
        if [ "$k" = skill ]; then cp -r "$P" "$OUT/skills/$n"; rm -f "$OUT/skills/$n/.pack.json"; echo "$n" >> "$OUT/custom_skills.txt"
        else jq -c --slurpfile t "$P" '. + $t' "$OUT/mcp.json" > "$OUT/mcp.json.tmp" && mv "$OUT/mcp.json.tmp" "$OUT/mcp.json"; fi
      done
      # The lead's GitHub tool, when the project grants a cloud push: a fixed allowlist, read tools and
      # branch/commit/pull-request writes unattended, merges asked of the person, nothing destructive.
      if [ "$ROL" = lead ] && [ "$(jq -r '.lead.push.cloud // "none"' "$DA_CONF/projects/$PRJ.json" 2>/dev/null)" = branches ]; then
        vid=$(jq -r '.lead.push.vault_id // ""' "$DA_CONF/projects/$PRJ.json")
        [ -n "$vid" ] || die "the lead has a cloud push grant but no vault: run qargi credential setup lead-push $PRJ"
        gt=$(dirname "$(readlink -f "$0")")/../provision/templates/github-lead.json; [ -f "$gt" ] || gt=$(dirname "$(readlink -f "$0")")/provision/templates/github-lead.json
        jq -c --arg v "$vid" --slurpfile g "$gt" '. + [($g[0] + {vault_ids: [$v]})]' "$OUT/mcp.json" > "$OUT/mcp.json.tmp" && mv "$OUT/mcp.json.tmp" "$OUT/mcp.json"
        if [ "$(jq -r '.lead.push.merge // "ask"' "$DA_CONF/projects/$PRJ.json")" = never ]; then
          jq -c 'map(if .name == "github" then del(.tools.merge_pull_request) else . end)' "$OUT/mcp.json" > "$OUT/mcp.json.tmp" && mv "$OUT/mcp.json.tmp" "$OUT/mcp.json"
        fi
      fi;;
    seed)
      # The baseline packs shipped in packs/ (manifest packs/baseline.json, one directory per skill under packs/skills/).
      # A pack is stored with source "qargi-baseline VERSION" and the hash it shipped with ("shipped"), so a later run can tell
      # a copy nobody edited (replaced when a newer version ships) from one the user edited (never overwritten).
      # Links are never touched. --install only adds what is missing, needs no token and never updates.
      ROOT=$(dirname "$(dirname "$(readlink -f "$0")")"); SHIP=$ROOT/packs
      [ -f "$SHIP/baseline.json" ] || die "no baseline packs shipped at $SHIP"
      jq -e '.schema == 1 and (.packs | type == "array")' "$SHIP/baseline.json" >/dev/null 2>&1 || die "$SHIP/baseline.json is not a baseline manifest"
      SRC="qargi-baseline $(cat "$ROOT/VERSION" 2>/dev/null || echo unknown)"
      ST=() PL=() NOTE='' CMP=()   # ST: "name|status|hs|old" in manifest order; PL: add/update plan lines; CMP: the declaration of each, in the same order
      cmp_of() { local x; for x in "${CMP[@]}"; do [ "${x%% *}" != "$1" ] || { jq -r 'join(",")' <<<"${x#* }"; return; }; done; }
      while IFS=$'\t' read -r k n c; do
        [ "$k" = skill ] || die "the baseline manifest names a $k pack ($n); only skills are shipped"
        valid_slug "$n" || die "the baseline manifest names '$n', not a pack name"
        { c=$(jq -cS 'if type == "array" then unique else . end' <<<"$c" 2>/dev/null) && python3 -I "$COMPATPY" valid "$c" >/dev/null; } || die "the baseline manifest gives the pack $n no valid compatible_providers (a list of runtime or family names, or [\"any\"])"
        D=$SHIP/skills/$n; [ -f "$D/SKILL.md" ] || die "the shipped pack $n is missing at $D"
        review skill "$D" "$c" >/dev/null 2>&1 || die "the shipped pack $n fails its review (qargi skill show cannot reach it; run it through review by hand)"
        hs=$(content_hash "$D" "$c"); P=$PACKS/skills/$n; old=''; CMP+=("$n $c")
        if [ -e "$PACKS/tools/$n.json" ]; then
          st=belongs
        elif [ ! -e "$P" ]; then st=add
        else
          rec=$P/.pack.json; src=$(jq -r '.source // ""' "$rec" 2>/dev/null); old=$(content_hash "$P")
          case $src in
            qargi-baseline*)
              if [ "$(jq -r '.shipped // ""' "$rec")" != "$old" ] || [ "$(jq -r '.sha256 // ""' "$rec")" != "$old" ]; then st=edited
              elif [ "$old" = "$hs" ]; then st=current
              else st=update; fi;;
            *) st=belongs;;
          esac
        fi
        ST+=("$n|$st|$hs|$old")
      done < <(jq -r '.packs[] | [.kind, .name, (.compatible_providers | tojson)] | @tsv' "$SHIP/baseline.json")
      for e in "${ST[@]}"; do
        IFS='|' read -r n st hs old <<<"$e"
        case $st in
          add) PL+=("$(printf '%-8s skill %s (content %s)  compatible_providers %s' add "$n" "$hs" "$(cmp_of "$n")")");;
          update)
            lk=$(jq -r --arg k "skill:$n" '[.links[] | select(.pack==$k) | .scope + (if .project then ":"+.project else "" end) + (if .role then "/"+.role else "" end)] | join(", ")' "$LINKS")
            PL+=("$(printf '%-8s skill %s (content %s -> %s; links: %s)  compatible_providers %s' update "$n" "$old" "$hs" "${lk:-none}" "$(cmp_of "$n")")");;
        esac
        # lines shown whatever the mode: what stays as it is
        case $st in
          current) [ -n "$INSTALL" ] || printf '%-8s skill %s\n' current "$n";;
          edited) [ -n "$INSTALL" ] || printf '%-8s skill %s: edited in your library (content %s; shipped %s)\n' kept "$n" "$old" "$hs"; NOTE=1;;
          belongs) [ -n "$INSTALL" ] || printf '%-8s skill %s: the name belongs to a pack you created or imported\n' kept "$n"; NOTE=1;;
        esac
      done
      seed_one() { # name hs: stage, swap in, write the record
        local n=$1 hs=$2 stage=$PACKS/skills/.seed-$1 x
        rm -rf "$stage"; cp -r "$SHIP/skills/$n" "$stage"; rm -f "$stage/.pack.json"
        rm -rf "${PACKS:?}/skills/$n"; mv "$stage" "$PACKS/skills/$n"
        write_record "$PACKS/skills/$n" skill "$SRC" "$(for x in "${CMP[@]}"; do [ "${x%% *}" != "$n" ] || echo "${x#* }"; done)"
        jq --arg s "$hs" '. + {shipped:$s}' "$PACKS/skills/$n/.pack.json" > "$PACKS/skills/$n/.pack.json.tmp" && mv "$PACKS/skills/$n/.pack.json.tmp" "$PACKS/skills/$n/.pack.json"
      }
      if [ -n "$INSTALL" ]; then
        names=''
        for e in "${ST[@]}"; do
          IFS='|' read -r n st hs old <<<"$e"
          [ "$st" = add ] || continue
          printf '%-8s skill %s (content %s)\n' add "$n" "$hs"; seed_one "$n" "$hs"; names="$names $n"
          echo "seeded skill $n (content $hs)"
        done
        [ -z "$names" ] || audit_log packs-seed "install$names"
        for e in "${ST[@]}"; do
          case $e in *"|update|"*) NOTE=1;; esac
        done
        if [ -n "$NOTE" ]; then echo "note: newer shipped versions: run qargi packs seed"; fi
        [ -n "$names" ] || [ -n "$NOTE" ] || echo "nothing to seed"
        exit 0
      fi
      if [ ${#PL[@]} -eq 0 ]; then echo "nothing to seed"; exit 0; fi
      printf '%s\n' "${PL[@]}"
      tok=$(printf '%s\n' "${PL[@]}" | sort | plan_token)
      if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0; fi
      need_token "$tok"
      names=''; for e in "${ST[@]}"; do IFS='|' read -r n st hs old <<<"$e"; case $st in add|update) names="$names $n";; esac; done
      audit_log packs-seed "$tok$names"
      reached=''
      for e in "${ST[@]}"; do
        IFS='|' read -r n st hs old <<<"$e"
        case $st in add|update) ;; *) continue;; esac
        if [ "$st" = update ]; then
          reached="$reached $(jq -r --arg k "skill:$n" --arg all "$(ls "$DA_CONF/projects" 2>/dev/null | sed -n 's/\.json$//p' | paste -sd' ')" \
            '.links[] | select(.pack==$k) | if .scope=="project" or .scope=="project-role" then .project else ($all | split(" ")[]) end' "$LINKS" | paste -sd' ')"
        fi
        seed_one "$n" "$hs"; echo "seeded skill $n (content $hs)"
      done
      for prj in $(printf '%s\n' $reached | sort -u); do
        rt=$(pymod provider layout "$(pymod provider of "$prj" --conf "$DA_CONF" --surface local 2>/dev/null)" render_target 2>/dev/null) && echo "next: qargi packs apply --target $rt $prj"
        [ ! -f "$REG" ] || jq -r --arg p "$prj" 'to_entries[] | select(.value.location=="cloud" and (.key | startswith($p + "-"))) | .key' "$REG" \
          | while read -r inst; do echo "next: qargi packs apply $inst"; done
      done
      exit 0;;
    load)
      # Read-only and evaluated from the links when called: the index of what the role has enabled, or one pack's text and
      # the library path of its files. Refuses what render refuses (a pack that fails its review or changed since approved).
      PRJ=${PROJECT:-$(pymod help infer)}; ROL=$ROLE; LN=${ARGS[0]:-}
      [ -n "$PRJ" ] || usage_die "load: name the project with --project P (none was inferred from here)"
      valid_role "$ROL" || usage_die "load: --role is one of: $DA_ROLES"
      vet() { # kind name -> dies unless the pack is sound; sets P
        P=$(item_path "$1" "$2"); [ -e "$P" ] || die "attached pack $1:$2 is not in the library"
        review "$1" "$P" >/dev/null || die "pack $1:$2 fails its review (qargi $1 check $PRJ $ROL)"
        want=$(jq -r '.sha256 // ""' "$(record_of "$P")" 2>/dev/null)
        { [ -z "$want" ] || [ "$want" = "$(content_hash "$P")" ]; } || die "pack $1:$2 changed since it was approved (drift); it is not loaded"
      }
      if [ -z "$LN" ]; then
        echo "enabled for $PRJ/$ROL (qargi packs load NAME --role $ROL --project $PRJ prints one):"
        compat_filter "$PRJ" "$ROL" local,cloud; skip_say "  "
        for e in ${CP_OK[@]+"${CP_OK[@]}"}; do
          k=${e%%:*}; n=${e#*:}; vet "$k" "$n"
          if [ "$k" = skill ]; then d=$(sed -n 's/^description: *//p' "$P/SKILL.md" | head -1); echo "  skill $n: ${d:-no description}"
          else echo "  tool  $n (MCP server; not loaded into a session by this verb)"; fi
        done
        exit 0
      fi
      printf '%s\n' "$LN" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]*$' || die "load: not a pack name: $LN"
      compat_filter "$PRJ" "$ROL" local,cloud
      e=$(printf '%s\n' ${CP_OK[@]+"${CP_OK[@]}"} | grep -x -E "(skill|tool):$(printf '%s' "$LN" | sed 's/[.]/\\./g')" | head -1)
      if [ -z "$e" ]; then
        sk=$(skip_say '' | grep -E "^skipped (skill|tool) $(printf '%s' "$LN" | sed 's/[.]/\\./g'): " | head -1)
        [ -z "$sk" ] || die "load: $LN is linked but skipped for $PRJ/$ROL: ${sk#skipped * "$LN": }; it is not loaded"
        die "load: $LN is not enabled for $PRJ/$ROL (link it, or see: qargi packs load --role $ROL --project $PRJ)"
      fi
      k=${e%%:*}; vet "$k" "$LN"
      if [ "$k" = skill ]; then
        echo "== skill $LN (approved library content; files beside it: $P)"; cat "$P/SKILL.md"
        others=$(cd "$P" && find . -type f ! -path ./.pack.json ! -name SKILL.md | sed 's#^\./#  #' | sort)
        [ -z "$others" ] || { echo; echo "== other files of $LN, relative to $P"; echo "$others"; }
      else echo "== tool $LN (MCP server definition)"; cat "$P"; fi
      exit 0;;
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
      off=$(tools_off "$ROLE" "$DA_CONF/projects/$PROJECT.json"); echo "  built-in tools off: ${off// /, }"
      vids=$(jq -r '[.[].vault_ids // [] | .[]] | unique | join(" ")' "$W/out/mcp.json")
      [ -z "$vids" ] || echo "  note: these tools use vault(s) $vids; attach them to the deployment, they are not attached by this command"
      tok=$({ find "$W/out" -type f -print0 | sort -z | xargs -0 cat; printf '%s|%s|%s|%s' "$aid" "$aver" "$anth" "$off"; } | plan_token)
      if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0; fi
      need_token "$tok"; audit_log packs-apply "$INST agent $aid v$aver"
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
      tools=$(jq -c --slurpfile m "$W/out/mcp.json" --arg off "$off" '
        map(select(.type != "mcp_toolset") | if .type == "agent_toolset_20260401" then .configs = ($off | split(" ") | map(select(length > 0) | {name: ., enabled: false})) else . end) + ($m[0] | map({type:"mcp_toolset", mcp_server_name:.name, default_config:{enabled:false},
          configs:(.tools | to_entries | map({name:.key, enabled:true, permission_policy:{type:.value}}))}))' <<<"$(jq -c .tools <<<"$ag")")
      ant beta:agents update --agent-id "$aid" --version "$aver" --skill "$skills" --mcp-server "$servers" --tool "$tools" </dev/null >/dev/null 2>&1 \
        || die "agent update failed (custom skills were uploaded)"
      ant beta:deployments update --deployment-id "$did" --agent "$aid" </dev/null >/dev/null 2>&1 || die "agent updated but re-pointing the deployment failed"
      nv=$(ant beta:deployments retrieve --deployment-id "$did" </dev/null 2>/dev/null | jq .agent.version)
      json_update "$REG" '.[$n].agent.version_pinned = $v' --arg n "$INST" --argjson v "$nv"
      echo "applied; the deployment now pins agent v$nv";;
    *) usage_die "usage: packs.sh packs render|load|apply|link|unlink|check|seed ...";;
  esac
  exit 0
fi

TEMPLATE_TOOL='{"name":"NAME","url":"https://mcp.example.invalid/","vault_ids":[],"tools":{"read_item":"always_allow"}}'

case "$VERB" in
  new)
    NAME=${NAME:-${ARGS[0]:-}}; valid_slug "$NAME" || usage_die "new needs a NAME (lower-case letters, digits, -)"
    COMPAT=$(compat_need) || exit 1
    P=$(item_path "$KIND" "$NAME"); [ ! -e "$P" ] || die "$NAME already exists in the library (names are unique)"
    [ -z "$(ls "$PACKS/skills/$NAME" "$PACKS/tools/$NAME.json" 2>/dev/null)" ] || die "$NAME is already used by another pack (skills and tools share one namespace)"
    if [ "$KIND" = skill ]; then
      mkdir -p "$P"; printf -- '---\nname: %s\ndescription: <when to use this skill, in one or two sentences>\n---\n\n# %s\n\n<the instructions the agent follows>\n' "$NAME" "$NAME" > "$P/SKILL.md"
    else printf '%s\n' "${TEMPLATE_TOOL//NAME/$NAME}" | jq . > "$P"; fi
    write_record "$P" "$KIND" created "$COMPAT"; audit_log "$KIND-new" "$NAME"
    echo "created $KIND $NAME: $P (compatible_providers: $(jq -r 'join(", ")' <<<"$COMPAT"))"; echo "edit it, then link it: qargi $KIND link $NAME --scope S ...";;
  import)
    SRC=${ARGS[0]:-}; [ -n "$SRC" ] || usage_die "import needs a SOURCE (a directory or file, or an https git URL)"
    COMPAT=$(compat_need) || exit 1   # before anything is fetched: the declaration is part of what is approved
    T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; SRCREC=$SRC
    if [[ $SRC == https://* ]]; then
      git clone -q --depth 1 ${REF:+--branch "$REF"} "$SRC" "$T/repo" </dev/null 2>/dev/null || die "could not clone $SRC"
      SRCREC="$SRC@$(git -C "$T/repo" rev-parse HEAD)${SUBPATH:+ path $SUBPATH}"; rm -rf "$T/repo/.git"; WORK=$T/repo${SUBPATH:+/$SUBPATH}
    else WORK=$SRC; [ -e "$WORK" ] || die "no such source: $SRC"; fi
    if [ "$KIND" = skill ]; then
      [ -d "$WORK" ] || die "a skill source is a directory with SKILL.md"
      NAME=${NAME:-$(sed -n 's/^name: *//p' "$WORK/SKILL.md" 2>/dev/null | head -1)}
      # a top-level .pack.json in the source is qargi's own record (a pack copied out of the library, or made by qargi): not copied, and said so
      cp -r "$WORK" "$T/stage"; if [ -e "$T/stage/.pack.json" ] || [ -L "$T/stage/.pack.json" ]; then IGNORED_REC=1; rm -rf "$T/stage/.pack.json"; fi
    else
      [ -f "$WORK" ] || die "a tool source is a JSON file"
      NAME=${NAME:-$(jq -r .name "$WORK" 2>/dev/null)}; cp "$WORK" "$T/stage"
    fi
    valid_slug "$NAME" || usage_die "cannot work out a valid name; pass --name"
    [ -z "$(ls "$PACKS/skills/$NAME" "$PACKS/tools/$NAME.json" 2>/dev/null)" ] || die "$NAME already exists in the library (names are unique; pass --name or remove the old one)"
    echo "== review of $KIND $NAME from $SRCREC"
    [ -z "${IGNORED_REC:-}" ] || echo "note: the source's top-level .pack.json is qargi's own record of a library pack: it is ignored and not copied (the pack gets a new record from this import)"
    # the server's own tool listing, when it is given: what it says of the pack's tools is judged in the review, covered by the token and kept in the record
    TL=''; [ -z "$TOOL_LIST" ] || { TL=$(tl_need "$T/stage") || exit 1; }
    review "$KIND" "$T/stage" "$COMPAT" "$TL" || { echo "refused: fix the source first" >&2; exit 1; }
    TOK=$(content_hash "$T/stage" "$COMPAT" "$TL")
    if [ -z "$APPROVED" ]; then echo "plan token: $TOK   (store it with: --plan $TOK --approved \"<the user's go-ahead after reading the review>\")"; exit 0; fi
    need_token "$TOK"; audit_log "$KIND-import" "$NAME from $SRCREC"
    P=$(item_path "$KIND" "$NAME"); mv "$T/stage" "$P"; write_record "$P" "$KIND" "$SRCREC" "$COMPAT" "$TL"
    echo "stored $KIND $NAME (content $TOK); link it to a scope to attach it";;
  list)
    PRJ=${ARGS[0]:-}; ROL=${ARGS[1]:-}; lopts=()
    # one process lists them all (packs_check.py list); the packs the role gets are asked of effective once, not once per pack
    [ -z "$PRJ" ] || [ -z "$ROL" ] || lopts=(--attached "$(effective "$PRJ" "$ROL")" --label "$PRJ/$ROL")
    python3 -I "$CHECKPY" list "$KIND" "$PACKS" ${lopts[@]+"${lopts[@]}"};;
  show)
    NAME=${ARGS[0]:-}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    echo "path: $P"; jq . "$(record_of "$P")" 2>/dev/null; jq -r --arg k "$KIND:$NAME" '.links[] | select(.pack==$k) | "link: " + tostring' "$LINKS"; review "$KIND" "$P" || true;;
  seal)
    NAME=${ARGS[0]:-}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    # the declaration is approved with the content: --compatible changes it, else the record's stands, and a pack with none must be given one
    if [ -n "$COMPAT_ARG" ]; then COMPAT=$(compat_parse "$COMPAT_ARG") || exit 1
    else COMPAT=$(compat_of "$P"); [ -n "$COMPAT" ] || die "$NAME declares no compatible_providers; seal it with --compatible LIST (the providers that can use it: runtime or family names separated by commas, or any)"; fi
    # the server's tool listing is approved with the content too: --tool-list FILE replaces what the record keeps of it, else the record's stands
    curtl=$(tl_of "$P"); if [ -n "$TOOL_LIST" ]; then TL=$(tl_need "$P") || exit 1; else TL=$curtl; fi
    echo "== review of $KIND $NAME"; review "$KIND" "$P" "$COMPAT" "$TL" || { echo "refused: fix it first" >&2; exit 1; }
    cur=$(compat_of "$P"); [ -z "$COMPAT_ARG" ] || [ "$COMPAT" = "$cur" ] || echo "compatible_providers changes: ${cur:-(none)} -> $COMPAT"
    if [ -n "$TOOL_LIST" ] && [ "$TL" != "$curtl" ]; then
      was='(none)'; [ -z "$curtl" ] || was=$(jq -r '.sha256[0:16]' <<<"$curtl" 2>/dev/null) || was='(unreadable)'
      echo "tool listing changes: $was -> $(jq -r '.sha256[0:16]' <<<"$TL")"
    fi
    TOK=$(content_hash "$P" "$COMPAT" "$TL")
    if [ -z "$APPROVED" ]; then echo "plan token: $TOK   (approve this content with: --plan $TOK --approved \"<the user's go-ahead after reading the review>\")"; exit 0; fi
    need_token "$TOK"; audit_log "$KIND-seal" "$NAME $TOK"
    src=$(jq -r '.source // "created"' "$(record_of "$P")" 2>/dev/null); write_record "$P" "$KIND" "$src" "$COMPAT" "$TL"; echo "sealed $KIND $NAME (content $TOK)";;
  link|unlink)
    NAME=${ARGS[0]:-}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    L=$(link_args "$KIND:$NAME") || exit $?   # a usage error in the scope ends the verb with its status, not only the substitution
    if [ "$VERB" = link ]; then
      review "$KIND" "$P" >/dev/null || die "the pack fails its review: qargi $KIND show $NAME"
      want=$(jq -r '.sha256 // ""' "$(record_of "$P")" 2>/dev/null)
      [ "$want" = "$(content_hash "$P")" ] || die "$NAME changed since it was approved; review and approve it: qargi $KIND seal $NAME"
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
  effective)
    # what the role gets: the packs its project's provider can use (on the local or the cloud surface), then, as "skipped KIND NAME: why", the ones it cannot
    compat_filter "${ARGS[0]:-}" "${ARGS[1]:-}" local,cloud
    printf '%s\n' ${CP_OK[@]+"${CP_OK[@]}"} | grep "^$KIND:" | sed "s/^$KIND://"
    skip_say '' | grep "^skipped $KIND " || true;;
  check)
    PRJ=${ARGS[0]:-}; ROL=${ARGS[1]:-}; rc=0; any=''
    compat_filter "$PRJ" "$ROL" local,cloud
    skip_say '' | grep "^skipped $KIND " | sed 's/^skipped /skip /' || true
    names=()
    for e in ${CP_OK[@]+"${CP_OK[@]}"}; do [ "${e%%:*}" = "$KIND" ] && names+=("${e#*:}"); done
    # drift and review of every pack, one process (packs_check.py check)
    if [ "${#names[@]}" -gt 0 ]; then any=1; python3 -I "$CHECKPY" check "$KIND" "$PACKS" "${names[@]}" || rc=1; fi
    if [ -n "$any" ]; then :
    elif none_linked "$PRJ"; then echo "no pack is linked to any role of $PRJ"
    else echo "no $KIND packs reach $PRJ/$ROL"; fi
    exit $rc;;
  remove)
    NAME=${NAME:-${ARGS[0]:-}}; P=$(item_path "$KIND" "$NAME"); [ -e "$P" ] || die "no such $KIND in the library"
    [ "$(jq -r --arg k "$KIND:$NAME" '[.links[] | select(.pack==$k)] | length' "$LINKS")" = 0 ] || die "$NAME is linked; unlink it from every scope first (qargi $KIND show $NAME)"
    audit_log "$KIND-remove" "$NAME"; rm -rf "$P" "$(record_of "$P")"; echo "removed $KIND $NAME";;
  *) usage_die "usage: packs.sh skill|tool new|import|list|show|seal|link|unlink|enable|disable|effective|check|remove ...; skill accept|unaccept PROJECT NAME";;
esac
