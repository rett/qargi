#!/usr/bin/env bash
# Local dispatch without a way to push: the agent works in a clone of a bare copy that
# has no remote, runs git through a credential-less wrapper, and the coordinator
# compares every ref of the real repository (and of its remote) before and after.
#
#   local.sh prepare (--repo DIR | --repo-url URL [--credential-file FILE]) --base BRANCH --slug SLUG --scratch DIR [--role R] [--profile NAME]
#   local.sh verify RUN_DIR
#   local.sh clean RUN_DIR [--discard]   remove a collected, verified run and its temporary directory (--discard: whatever verify says)
#   local.sh clean --applied --scratch DIR   remove every run under DIR whose work is applied and merged; keep and name the others
#   local.sh clean --stale DAYS --scratch DIR [--yes]   list the finished runs (verified or applied) under DIR older than DAYS; with --yes clean them
#   local.sh list [--scratch DIR]        read-only: each run (under DIR, else the registry's) with role, slug, age, applied and merged
#   local.sh run RUN_DIR [--task FILE] [--model TIER|ID] [--effort LEVEL] [--timeout SECONDS] [--again] [--dry-run]
#                                        start the member of a prepared run as a command line, for a runtime whose dispatch.mode is "command"
#                                        (lib/local_run.py says how); a runtime that dispatches in the lead's session is refused
#
# This stops every ordinary push (`git push`, `git push origin`, a pushurl, a remote added
# from a config). It is not a sandbox against an agent that deliberately goes around it
# (it runs as the same user): `verify` is what turns such an attempt into a loud failure.
# The run directory records the task's ability (RUN/ability, default build) and, under --profile, the profile (RUN/profile); under review the guard
# (qargi __guard) refuses every change to the clone, so a review writes only to OUT.
# A run based on feature/X of a stored project first asks the marshal (marshal_check): another live lead holds X -> refused, no run
# is made; warnings go to stderr. The lead of X is recorded in the run line as "lead" (null when nobody leads it).
# prepare also appends one JSON line per run to $QARGI_STATE/local-runs.jsonl (run directory, slug, ability, base,
# start time, temporary directory, and the repository: its real path (repo), or its URL (url) and the path of its credential file (cred), never a token;
# mode 600), so `qargi report` can list the local runs. The registry is the lead's and the only record `verify`, `clean`, `run` and `review apply` believe
# about a run (lib.sh run_record): the repository, the URL and the credential path come from it, and a run whose own repo.path, repo.url or cred.path
# (files a member can write) differ is refused, as is a directory the registry does not name. `clean` removes the temporary directory that this line names
# for the run, not the one the run's own tmpdir file says (a member can write the run directory, and a file there could name another run's temporary directory).
# After the TASK-BLOCK PATHS lines it prints TASK-BLOCK MEMORY (tiercontext.py packet: the tier summary, the always rows of the
# indexes and the no-write rule; the repo tier is the clone's committed copy) when the repository belongs to a stored project.
. "$(dirname "$0")/lib.sh"
. "$(dirname "$0")/marshal.sh"

# drop_qargi_refs -> stdin without the refs under refs/qargi/ (lines "local REF SHA" and "remote SHA REF"). The marshal refs backend
# keeps its records there and the lead's renewer fetches and pushes them during a run; that is not an agent push. Only that
# namespace: refs/qargi-x/ and every other ref stay compared.
drop_qargi_refs() { awk '{ r = ($1 == "local") ? $2 : $3 } r !~ /^refs\/qargi\//'; }

snapshot_url() { # url credential-file(optional) -> sorted refs of the remote
  ( [ -z "${2:-}" ] || git_auth_env "$2"
    u=$1; [ -z "${2:-}" ] || u=${1/https:\/\//https://x-access-token@}
    out=$(timeout 60 git ls-remote --heads --tags "$u" 2>/dev/null </dev/null) && printf '%s\n' "$out" | sed 's/^/remote /' | drop_qargi_refs | sort || echo "remote unavailable" )
}

snapshot() { # repo -> sorted refs of the repository and of its remote
  git -C "$1" for-each-ref --format='local %(refname) %(objectname)' | drop_qargi_refs | sort
  if git -C "$1" remote get-url origin >/dev/null 2>&1; then
    if out=$(timeout 60 git -C "$1" ls-remote --heads --tags origin 2>/dev/null </dev/null); then
      printf '%s\n' "$out" | sed 's/^/remote /' | drop_qargi_refs | sort
    else
      echo "remote unavailable"
    fi
  fi
}

# merged_tip REPO TIP -> 0 when the commit TIP (the second word of a run's applied file, which a member can write) is on a local branch
# other than agent/*, 1 when it is not, 2 when TIP is not a full hex object name. A word that is not one never reaches git, so an
# option-like text cannot become an option of for-each-ref; the value is given in the --contains=VALUE form and the ref patterns after --.
merged_tip() {
  case $2 in ''|*[!0-9a-f]*) return 2;; esac
  [ "${#2}" = 40 ] || [ "${#2}" = 64 ] || return 2
  [ -n "$(git -C "$1" for-each-ref --contains="$2" --format='%(refname)' -- refs/heads 2>/dev/null | grep -v '^refs/heads/agent/' | head -1)" ]
}

# journal_steps SIDE NAME OLD NEW -> 0 and the verbs, in order, of the lead's ref journal ($DA_STATE/ref-journal.jsonl) that explain the change
# of the ref NAME from OLD to NEW (a sha, or 40 zeros for absent) since the run began (JSTART, an epoch); SIDE is local (a branch or tag of
# the repository CREPO) or remote (a ref of its origin; for the run of a repository URL, the lines of that URL, CURLK). NEW must be reachable
# from OLD by following lines of this repository, side and ref with epoch >= JSTART, each from its old value to its new one. Lines that
# start elsewhere (an earlier creation made in the same second as the run) are not on the path, and an unjournaled hand anywhere breaks it,
# because no line starts where the hand left the ref. A rewrite (qargi ref record --rewrite) is named with the reason the lead gave.
# Trusted only as far as the state directory is (the guard keeps an agent from writing it; same-user code could).
journal_steps() {
  local f=$DA_STATE/ref-journal.jsonl rp='' out
  [ -f "$f" ] && [ -n "${JSTART:-}" ] || return 1
  [ -z "${CREPO:-}" ] || { rp=$(readlink -f "$CREPO" 2>/dev/null) || rp=$CREPO; }
  [ -n "$rp" ] || [ -n "${CURLK:-}" ] || return 1
  out=$(jq -sre --arg r "$rp" --arg u "${CURLK:-}" --arg side "$1" --arg n "$2" --arg o "$3" --arg w "$4" --argjson s "$JSTART" '
    def mine: if $side == "remote" then .remote == "origin" and (($r != "" and .repo == $r) or ($u != "" and .url == $u))
              else (has("remote") | not) and $r != "" and .repo == $r end;
    [ .[] | select(type == "object" and .ref == $n and ((.epoch // 0) >= $s) and mine and (.old | type) == "string" and (.new | type) == "string") ] as $e
    | reduce range(0; ($e | length) + 1) as $i ({($o): -1};
        reduce range(0; $e | length) as $j (.; if has($e[$j].old) and (has($e[$j].new) | not) then .[$e[$j].new] = $j else . end))
    | select($w != $o and has($w)) | . as $p
    | [ $w | recurse(if . != $o then $e[$p[.]].old else empty end) | select(. != $o) | $e[$p[.]] ] | reverse
    | map(if .verb == "ref:rewrite" then "a rewrite (qargi ref record --rewrite: " + ((.why // "") | tostring) + ")" else "qargi " + ((.verb // "?") | tostring | sub(":"; " ")) end)
    | reduce .[] as $v ([]; if index([$v]) then . else . + [$v] end) | join(", ")' "$f" 2>/dev/null) && [ -n "$out" ] || return 1
  printf '%s\n' "$out" | LC_ALL=C tr -d '\000-\011\013-\037\177'   # the reason is the lead's text: no control or escape byte reaches the terminal
}

# parking_of REPO -> the parking branch of the stored project of REPO (answers repo.parking_branch), else scratch
parking_of() {
  local pj p=''
  pj=$(project_of "$1" '')
  [ -z "$pj" ] || p=$(jq -r '.repo.parking_branch // ""' "$DA_CONF/projects/$pj.json" 2>/dev/null) || p=''
  echo "${p:-scratch}"
}

# compare REPO REF AFTER [strict] [ACCEPTED] -> prints each offending change, returns 1 if there is one; each change it accepts is named in
# the file ACCEPTED, one line each. Refs under refs/qargi/ are not compared (see drop_qargi_refs). A change is accepted, in either phase, when
#   - the lead's ref journal explains it (journal_steps): a branch or a tag of the repository, or a branch or tag of its origin, moved,
#     created or deleted by qargi's own verbs (feature finish and park, release and hotfix finish, branch prune, review apply, the
#     parking branch following develop, a rewrite the lead recorded ...); a peeled tag line of origin (TAG^{}) goes with its tag;
#   - a remote-tracking ref refs/remotes/origin/X now says what origin has (a fetch or a push did that; origin's own ref is compared
#     on its own line), or a tag of the repository is now origin's tag of the same name (fetched);
#   - the parking branch (answers repo.parking_branch, default scratch) was fast-forwarded to develop's tip, by hand or by qargi.
# Without strict (after the run's first passing verify, against RUN/verified) also: a fast-forward of develop, master or an
# agent|feature|release|hotfix/* branch, and a new agent|feature|release|hotfix/* branch: the lead's own merges. Everything else, a rewrite
# or a deletion nobody journaled, a tag or a push made by hand, any other ref, is offending.
compare() {
  local repo=$1 ref=$2 aft=$3 strict=${4:-} acc=${5:-/dev/null} bad=0 k kind name old new steps park='' dev tgt short a b c uo='' un='' hasr=''
  local zero=0000000000000000000000000000000000000000 why=" (not in the lead's ref journal)"
  local -A O=() N=() ACC=()
  while read -r a b c; do case $a in local) O["local $b"]=$c;; remote) if [ "$b" = unavailable ] && [ -z "$c" ]; then uo=1; else O["remote $c"]=$b; fi;; esac; done < <(drop_qargi_refs < "$ref")
  while read -r a b c; do case $a in local) N["local $b"]=$c;; remote) if [ "$b" = unavailable ] && [ -z "$c" ]; then un=1; else N["remote $c"]=$b; fi;; esac; done < <(drop_qargi_refs < "$aft")
  if [ "$uo" != "$un" ]; then
    echo "origin could not be asked $([ -n "$un" ] && echo "now" || echo "when the snapshot was taken"): its refs cannot be compared"; bad=1
  fi
  [ -z "$repo" ] || ! git -C "$repo" remote get-url origin >/dev/null 2>&1 || [ -n "$un" ] || hasr=1
  dev=${N["local refs/heads/develop"]:-}
  allowed() { case $1 in refs/heads/develop|refs/heads/master|refs/heads/agent/*|refs/heads/feature/*|refs/heads/release/*|refs/heads/hotfix/*) return 0;; esac; return 1; }
  shortref() { case $1 in refs/heads/*) echo "${1#refs/heads/}";; refs/tags/*) echo "tag ${1#refs/tags/}";; *) echo "$1";; esac; }
  while read -r k; do
    [ -n "$k" ] || continue
    kind=${k%% *}; name=${k#* }; old=${O[$k]:-}; new=${N[$k]:-}
    [ "$old" != "$new" ] || continue
    short=$(shortref "$name"); [ "$kind" = local ] || short="$short on origin"
    if [ -z "$old" ]; then a=created; elif [ -z "$new" ]; then a=deleted; else a=moved; fi
    # the lead's ref journal: qargi's own verbs
    case $name in
      *'^{}') if [ "$kind" = remote ] && [ -n "${ACC["remote ${name%'^{}'}"]:-}" ]; then ACC[$k]=1; continue; fi;;
      refs/heads/?*|refs/tags/?*)
        if steps=$(journal_steps "$kind" "$name" "${old:-$zero}" "${new:-$zero}"); then ACC[$k]=1; echo "$short $a by $steps" >> "$acc"; continue; fi;;
    esac
    if [ "$kind" = local ]; then
      # a remote-tracking ref of origin that says what origin has now, and a tag fetched from origin
      case $name in
        refs/remotes/origin/HEAD)
          tgt=$(git -C "$repo" symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null) || tgt=''
          if [ -n "$hasr" ] && [ -n "$tgt" ] && [ "$new" = "${N["local $tgt"]:-}" ]; then ACC[$k]=1; continue; fi;;
        refs/remotes/origin/?*)
          if [ -n "$hasr" ] && [ "$new" = "${N["remote refs/heads/${name#refs/remotes/origin/}"]:-}" ]; then ACC[$k]=1; echo "origin/${name#refs/remotes/origin/} $a to what origin has (a fetch or a push)" >> "$acc"; continue; fi;;
        refs/tags/?*)
          if [ -n "$hasr" ] && [ -n "$new" ] && [ "$new" = "${N["remote $name"]:-}" ]; then ACC[$k]=1; echo "$short $a as origin has it (fetched)" >> "$acc"; continue; fi;;
      esac
      # the parking branch fast-forwarded to develop's tip
      if [ -n "$old" ] && [ -n "$new" ] && [ "$new" = "$dev" ] && [[ $name == refs/heads/?* ]]; then
        [ -n "$park" ] || park=$(parking_of "$repo")
        if [ "$name" = "refs/heads/$park" ] && git -C "$repo" merge-base --is-ancestor "$old" "$new" 2>/dev/null; then
          ACC[$k]=1; echo "$short (the parking branch) fast-forwarded to develop" >> "$acc"; continue
        fi
      fi
      # after a passing verify: the lead's fast-forwards and new branches
      if [ -z "$strict" ] && [[ $name == refs/heads/?* ]]; then
        if [ -n "$old" ] && [ -n "$new" ] && allowed "$name"; then
          if git -C "$repo" merge-base --is-ancestor "$old" "$new" 2>/dev/null; then ACC[$k]=1; echo "$short fast-forwarded (a lead-side move after the run's passing verify)" >> "$acc"; continue; fi
          echo "branch rewritten (not a fast-forward): $name $old -> $new$why"; bad=1; continue
        fi
        if [ -z "$old" ] && allowed "$name"; then
          case $name in refs/heads/develop|refs/heads/master) ;; *) ACC[$k]=1; echo "$short created (a lead-side branch after the run's passing verify)" >> "$acc"; continue;; esac
        fi
        if [ -z "$new" ]; then echo "branch deleted: $name (was $old)$why"
        elif [ -z "$old" ]; then echo "branch created, not an allowed branch: $name $new$why"
        else echo "branch moved, not an allowed branch: $name $old -> $new$why"; fi
        bad=1; continue
      fi
    fi
    case $kind:$name in
      local:refs/heads/*)
        if [ -z "$new" ]; then echo "branch deleted: $name (was $old)$why"
        elif [ -z "$old" ]; then echo "branch created: $name $new$why"
        else echo "branch moved: $name $old -> $new$why"; fi;;
      local:refs/tags/*) echo "tag $a: $name ${old:-(none)} -> ${new:-(none)}$why";;
      local:refs/remotes/*) echo "remote-tracking ref $a: $name ${old:-(none)} -> ${new:-(none)} (it does not say what origin has)";;
      local:*) echo "ref $a: $name ${old:-(none)} -> ${new:-(none)}";;
      remote:*) echo "ref of origin $a: $name ${old:-(none)} -> ${new:-(none)}$why";;
    esac
    bad=1
  done < <({ printf '%s\n' "${!O[@]}"; printf '%s\n' "${!N[@]}"; } | LC_ALL=C sort -u)
  return $bad
}

# check RUN -> 0 and records RUN/verified when the refs are as the rule allows (RUN/refs.accepted names the changes it accepted); 2 otherwise;
# 3 when the registry does not vouch for RUN
check_run() {
  local run=$1 dir=$1 ref strict=1
  run_record "$run" || return 3   # the repository and the credential come from the lead's registry, never from the run directory
  ref=$dir/refs.before
  # the run's start (an epoch) bounds the lead's ref journal: prepare records it in RUN/started; with none, no change is journaled
  JSTART=$(cat "$dir/started" 2>/dev/null || true); [[ $JSTART =~ ^[0-9]{1,12}$ ]] || JSTART=''
  [ ! -f "$dir/verified" ] || { ref=$dir/verified; strict=''; }
  CREPO=$RUN_REPO CURLK=''
  if [ -n "$RUN_URL" ]; then
    CURLK=$(url_key "$RUN_URL")
    snapshot_url "$RUN_URL" "$RUN_CRED" > "$dir/refs.after"
  else
    snapshot "$RUN_REPO" > "$dir/refs.after"
  fi
  : > "$dir/refs.accepted"
  if compare "$RUN_REPO" "$ref" "$dir/refs.after" "$strict" "$dir/refs.accepted" > "$dir/refs.diff"; then
    cp "$dir/refs.after" "$dir/verified"
    return 0
  fi
  return 2
}

# render_warning REPO URL -> when the project this run belongs to has a render of its packs (packs apply --target T, T the render target of its
# provider; the render is state/render/PROJECT/RUNTIME), runs the read-only check of the render and, on findings, prints a WARNING block to stderr. Never fails the caller: a stale
# render must not block work. The project is the stored answers whose repo.path (or repo.url) is the one given; none found, nothing printed.
# No render directory (the usual case) costs no process: the glob below is the shell's own.
# A project with no provider cannot be checked (there is no default one): one note line says so and that the check was skipped. The check
# is asked for the render only ('--render-only'): the section about the skills a session would load is no part of whether the render is
# out of date, and a drifted accepted skill must not read as one. A provider that cannot render at all (exit 3) is nothing to warn about.
render_warning() {
  local m d prj f rp ru out rc pv rt pe lb
  for m in "$DA_STATE"/render/*/*/MANIFEST.json; do
    [ -f "$m" ] || continue
    d=$(dirname "$m"); prj=$(basename "$(dirname "$d")"); f=$DA_CONF/projects/$prj.json
    [ -f "$f" ] || continue
    rp=$(jq -r '.repo.path // ""' "$f" 2>/dev/null); rp=${rp/#\~/$HOME}; ru=$(jq -r '.repo.url // ""' "$f" 2>/dev/null)
    if [ -n "$1" ]; then [ -n "$rp" ] && [ "$(readlink -f "$rp")" = "$(readlink -f "$1")" ] || continue
    else [ -n "$ru" ] && [ "${ru%.git}" = "${2%.git}" ] || continue; fi
    rc=0; pv=$(python3 -I "$(dirname "$0")/provider.py" of "$prj" --conf "$DA_CONF" --surface local 2>/dev/null </dev/null) || rc=$?
    if [ "$rc" = 2 ]; then   # the render is the local surface's: an object that names only a cloud runtime is the same as none
      pe=$(python3 -I "$(dirname "$0")/provider.py" of "$prj" --conf "$DA_CONF" --surface local 2>&1 </dev/null) || true
      case $pe in
        *"has no local provider"*) echo "note: project $prj has no local provider (qargi project set $prj models.provider.local NAME); the render check was skipped" >&2;;
        *) echo "note: project $prj has no provider (qargi project set $prj models.provider NAME); the render check was skipped" >&2;;
      esac
      return 0
    fi
    # the render of a runtime is that runtime's; a project that has moved to another runtime has no render of it to check here
    [ "$rc" = 0 ] && [ "$pv" = "$(basename "$d")" ] || continue
    rt=$(python3 -I "$(dirname "$0")/provider.py" layout "$pv" render_target 2>/dev/null </dev/null) || return 0
    rc=0; out=$("$(dirname "$0")/packs.sh" packs check --target "$rt" '--render-only' "$prj" 2>&1) || rc=$?
    [ "$rc" != 0 ] && [ "$rc" != 3 ] || return 0
    lb=$(python3 -I "$(dirname "$0")/packs_render.py" label "$pv" 2>/dev/null </dev/null) || lb=$pv
    { echo "WARNING: the $lb render of project $prj is out of date or altered (the run goes on):"
      sed 's/^/  /' <<<"$out"
      echo "  fix: qargi packs apply --target $rt $prj"
      echo; } >&2
    return 0
  done
  return 0
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

verb=${1:-}; shift || true
case $verb in
  prepare)
    REPO='' URL='' CRED='' BASE='' SLUG='' SCR='' ROLE=build PROFILE=''
    while [ $# -gt 0 ]; do
      case $1 in --repo) need_val "$1" $#; REPO=$2; shift 2;; --repo-url) need_val "$1" $#; URL=$2; shift 2;; --credential-file) need_val "$1" $#; CRED=$2; shift 2;; --base) need_val "$1" $#; BASE=$2; shift 2;; --slug) need_val "$1" $#; SLUG=$2; shift 2;; --scratch) need_val "$1" $#; SCR=$2; shift 2;; --role) need_val "$1" $#; ROLE=$2; shift 2;; --profile) need_val "$1" $#; PROFILE=$2; shift 2;; *) usage_die "unknown option $1";; esac
    done
    if [ -n "$URL" ]; then
      [ -z "$REPO" ] || usage_die "give --repo or --repo-url, not both"
      case $URL in https://*) ;; *) die "--repo-url must be an https URL";; esac
      uauth=${URL#https://}; uauth=${uauth%%[/?#]*}
      case $uauth in *@*) die "--repo-url must not carry a user name or a password (https://USER@host): the URL is recorded and put in commands; give the token with --credential-file";; esac
      [ -z "$CRED" ] || { CRED=${CRED/#\~/$HOME}; [ -f "$CRED" ] || die "--credential-file: no such file"; CRED=$(readlink -f -- "$CRED"); }
    else
      [ -d "$REPO/.git" ] || [ -f "$REPO/.git" ] || die "--repo must be a git working tree"
      REPO=$(readlink -f -- "$REPO")   # recorded as a real path: the registry and RUN/repo.path say the same text
    fi
    [ "$ROLE" != lead ] && valid_role "$ROLE" || die "--role: one of $DA_ROLES (qargi role list)"
    CLASS=$(role_class "$ROLE")
    # a read-only role needs a read-only barrier on the local surface, or the project's recorded acceptance that there is none
    if [ "$CLASS" = read-only ]; then
      BPJ=$(project_of "$REPO" "$URL")
      [ -n "$BPJ" ] || { echo "qargi: no stored project has this repository, so no provider is known and a read-only role cannot start: store it (qargi project attach) and give it a provider (qargi project set PROJECT models.provider NAME)" >&2; exit 2; }
      barrier_guard local "$BPJ"
    fi
    valid_slug "$SLUG" || die "--slug: lower-case letters, digits and '-'"
    [ -n "$BASE" ] && [ -d "$SCR" ] || usage_die "prepare needs --base BRANCH and --scratch DIR"
    SCR=$(readlink -f -- "$SCR")   # an absolute run directory: the registry and every later verb name it from any working directory
    # a profile is resolved (by the one resolver, `agent for`) before anything is made: a refusal leaves no run directory
    MEMBER='' MODEL='' EFFORT=''
    if [ -n "$PROFILE" ]; then
      PPJ=$(project_of "$REPO" "$URL"); pargs0=(for "$ROLE" --profile "$PROFILE" --json)
      [ -z "$PPJ" ] || pargs0+=(--project "$PPJ")
      PRES=$("$(dirname "$0")/agent.sh" "${pargs0[@]}" 2>&1 </dev/null) || die "${PRES#qargi: }"
      MEMBER=$(jq -r '.member // ""' <<<"$PRES"); MODEL=$(jq -r '.model // "-"' <<<"$PRES"); EFFORT=$(jq -r '.effort // "-"' <<<"$PRES")
    else
      PROFILE=$ROLE
    fi
    # the contract addenda of the project's runtime on the local surface (resources.contract_addenda of its definition), read before anything
    # is made; a repository in no project, or a project with no local runtime, gets the core's contract alone (no runtime is assumed)
    ADDENDA='' CPJ=$(project_of "$REPO" "$URL")
    if [ -n "$CPJ" ]; then
      # a provider that is set but does not resolve is refused here, not left out of the contract
      CPROV=$(project_provider_if_set "$CPJ" local) || die "the local provider of project $CPJ does not resolve, so the contract addenda of its runtime cannot be added; nothing was made (qargi project show $CPJ)"
      [ -z "$CPROV" ] || ADDENDA=$(python3 -I "$(dirname "$0")/provider.py" addenda "$CPROV" local </dev/null) || die "could not read the contract addenda of the local runtime $CPROV (qargi provider check $CPROV)"
    fi
    LEAD=''
    case $BASE in
      feature/?*)
        MPROJ=$(project_of "$REPO" "$URL")
        if [ -n "$MPROJ" ]; then
          mrc=0; merr=$(mktemp "$DA_STATE/.marshal-gate.XXXXXX" 2>/dev/null) || merr=/dev/null
          marshal_check "$MPROJ" "${BASE#feature/}" 2>"$merr" || mrc=$?
          if [ "$merr" != /dev/null ]; then
            cat "$merr" >&2
            if [ "$mrc" = 1 ] && grep -q '^Traceback' "$merr"; then mrc=70; fi   # an exception also exits 1, but it is not a refusal
            rm -f "$merr"
          fi
          [ "$mrc" -ne 1 ] || exit 1   # another live lead holds the feature: the message is printed, no run is made
          [ "$mrc" -eq 0 ] || echo "qargi: warning: the marshal could not be asked (status $mrc); the run goes on" >&2
          LEAD=$("$(dirname "$0")/marshal.sh" status "${BASE#feature/}" --project "$MPROJ" --json 2>/dev/null | jq -r '.lead.id // empty' 2>/dev/null) || LEAD=''
        fi;;
    esac
    RUN=$(mktemp -d "$SCR/qargi.XXXXXX")
    mkdir -p "$RUN/out" "$RUN/home" "$RUN/contract"
    # the member reads the contract from the run: the core's files, then the runtime's addenda as one more file (CONTRACT below)
    cp "$(prompt_root)/contract/"*.md "$RUN/contract/" || die "could not copy the contract"
    [ -z "$ADDENDA" ] || printf '%s\n' "$ADDENDA" > "$RUN/contract/runtime-addenda.md"
    # a private temporary directory for the run's test sandboxes, on tmpfs when there is one; `clean` removes it, so a run
    # leaves nothing behind in /dev/shm and parallel runs never touch each other's files
    SHM=${QARGI_RUN_TMP:-/dev/shm}   # QARGI_RUN_TMP moves it (the tests do), so a test never leaves anything in /dev/shm
    while [ "${SHM%/}" != "$SHM" ] && [ "$SHM" != / ]; do SHM=${SHM%/}; done   # clean compares the parent as written
    if [ -d "$SHM" ] && [ -w "$SHM" ]; then TMPD=$(mktemp -d "$SHM/qargi-run.XXXXXX"); else TMPD=$RUN/tmp; mkdir -p "$TMPD"; fi
    printf '%s\n' "$TMPD" > "$RUN/tmpdir"
    printf '%s\n' "$ROLE" > "$RUN/ability"
    printf '%s\n' "$CLASS" > "$RUN/class"
    [ -z "$MEMBER" ] || printf '%s\n' "$PROFILE" > "$RUN/profile"
    date +%s > "$RUN/started"   # the epoch the lead's ref journal is read from by `verify`
    if [ -n "$URL" ]; then
      snapshot_url "$URL" "$CRED" > "$RUN/refs.before"
      printf '%s\n' "$URL" > "$RUN/repo.url"; [ -z "$CRED" ] || printf '%s\n' "$CRED" > "$RUN/cred.path"   # a path, never the token
      ( [ -z "$CRED" ] || git_auth_env "$CRED"
        u=$URL; [ -z "$CRED" ] || u=${URL/https:\/\//https://x-access-token@}
        git clone -q --bare "$u" "$RUN/bare.git" </dev/null ) || die "could not clone $URL (is the credential valid?)"
    else
      snapshot "$REPO" > "$RUN/refs.before"
      echo "$REPO" > "$RUN/repo.path"
      git clone -q --bare --no-hardlinks "$REPO" "$RUN/bare.git" || die "bare copy failed"
    fi
    git -C "$RUN/bare.git" remote remove origin 2>/dev/null || true
    git -C "$RUN/bare.git" config --unset-all remote.origin.url 2>/dev/null || true
    git clone -q --no-hardlinks "$RUN/bare.git" "$RUN/clone" || die "clone failed"
    git -C "$RUN/clone" remote set-url --push origin DISABLED
    git -C "$RUN/clone" rev-parse --verify -q "origin/$BASE" >/dev/null || die "no branch $BASE in the repository"
    git -C "$RUN/clone" checkout -q -b "agent/$SLUG" "origin/$BASE"
    cat > "$RUN/git" <<WRAP
#!/usr/bin/env bash
# git without credentials: no home, no global config, no ssh, no prompts.
exec env -i HOME="$RUN/home" PATH="\$PATH" LANG=C.UTF-8 TERM=dumb \\
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_SSH_COMMAND=false \\
  GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=false \\
  GIT_AUTHOR_NAME=qargi GIT_COMMITTER_NAME=qargi \\
  GIT_AUTHOR_EMAIL=qargi@example.invalid GIT_COMMITTER_EMAIL=qargi@example.invalid \\
  git "\$@"
WRAP
    chmod 755 "$RUN/git"
    jq -nc --arg r "$RUN" --arg s "$SLUG" --arg a "$ROLE" --arg b "$BASE" --arg t "$(now)" --arg l "$LEAD" --arg p "$PROFILE" --arg d "$TMPD" --arg rp "$REPO" --arg ru "$URL" --arg rc "$CRED" \
      '{run:$r, slug:$s, ability:$a, profile:$p, base:$b, started:$t, lead:(if $l == "" then null else $l end), tmpdir:$d}
       + (if $ru == "" then {repo:$rp} else {url:$ru} + (if $rc == "" then {} else {cred:$rc} end) end)' | ( umask 077; cat >> "$DA_STATE/local-runs.jsonl" )
    chmod 600 "$DA_STATE/local-runs.jsonl" 2>/dev/null || true
    render_warning "$REPO" "$URL"
    echo "RUN=$RUN"
    echo "ROLE=$ROLE"
    echo "CLASS=$CLASS"
    echo "PROFILE=$PROFILE"
    [ -z "$MEMBER" ] || { echo "MEMBER=$MEMBER"; echo "MODEL=$MODEL"; echo "EFFORT=$EFFORT"; }
    echo "CLONE=$RUN/clone"
    echo "OUT=$RUN/out"
    echo "TMP=$TMPD"
    echo "GIT=$RUN/git"
    BSHA=$(git -C "$RUN/clone" rev-parse "origin/$BASE")
    echo "BASE_SHA=$BSHA"
    echo "CONTRACT=$RUN/contract"
    echo
    echo "TASK-BLOCK PATHS"
    echo "RUN_DIR=$RUN"
    echo "CLONE=$RUN/clone"
    echo "OUT=$RUN/out"
    echo "TMP=$TMPD"
    echo "GIT=$RUN/git"
    echo "BASE_SHA=$BSHA"
    echo "CONTRACT=$RUN/contract"
    # the memory context packet: the tier summary and the always rows, for a repository that belongs to a stored project.
    # It never changes prepare's result: a failure or a timeout prints nothing.
    PPROJ=$(project_of "$REPO" "$URL")
    if [ -n "$PPROJ" ]; then
      tc=$(dirname "$(readlink -f "$0")")/tiercontext.py
      prel=$(timeout 3 python3 -I "$tc" repo-rel --project "$PPROJ" 2>/dev/null </dev/null) || prel=''
      pargs=(--project "$PPROJ" --role "$ROLE")
      [ -z "$prel" ] || pargs+=(--repo-tier "$RUN/clone/$prel")
      [ -z "$REPO" ] || [ -z "$prel" ] || pargs+=(--checkout "$REPO")
      if pkt=$(timeout 8 python3 -I "$tc" packet "${pargs[@]}" </dev/null) && [ -n "$pkt" ]; then
        printf '\nTASK-BLOCK MEMORY\n%s\n' "$pkt"
      fi
    fi;;
  verify)
    RUN=${1:-}; [ -f "$RUN/refs.before" ] || usage_die "verify needs a RUN dir made by prepare"
    # a read-only run's product is a report, never patches: patches in its output are not to be applied or accepted
    if [ "$(run_class "$RUN")" = read-only ] && [ -n "$(find "$RUN/out" -maxdepth 2 \( -name '*.patch' -o -name run.bundle \) 2>/dev/null | head -1)" ]; then
      echo "qargi: $RUN is a read-only run ($(cat "$RUN/ability" 2>/dev/null || echo review)) and its output holds patches. A read-only run's product is a report, never patches: read $RUN/out/report.md, and do not apply or accept the patches." >&2
      exit 2
    fi
    reg_load; crc=0; check_run "$RUN" || crc=$?
    if [ "$crc" = 3 ]; then
      exit 3   # run_record said why: the registry does not vouch for this run directory, so no repository was asked
    elif [ "$crc" = 0 ]; then
      if [ -s "$RUN/refs.accepted" ]; then
        echo "refs differ from the snapshot only by the lead's own moves; nothing was pushed by the run:"
        sed 's/^/  /' "$RUN/refs.accepted"
      else echo "refs unchanged: nothing was pushed to the repository or its remote"; fi
    else
      echo "REFS CHANGED during the run (the agent must not have pushed):" >&2
      cat "$RUN/refs.diff" >&2
      if [ -s "$RUN/refs.accepted" ]; then echo "accepted as the lead's own moves:" >&2; sed 's/^/  /' "$RUN/refs.accepted" >&2; fi
      [ ! -f "$RUN/verified" ] && echo "(before the run's first passing verify a ref may differ only as far as the lead's ref journal names it, a remote-tracking ref follows origin, or the parking branch is fast-forwarded to develop)" >&2 \
        || echo "(after a passing verify the lead's fast-forwards and new branches are accepted too; nothing else that the lead's ref journal does not name)" >&2
      exit 2
    fi;;
  clean)
    # after the series is collected and verified: remove the run (clone, bare copy, output, wrapper) and its temporary directory.
    #   clean RUN [--discard]            one run; --discard drops it on purpose, whatever verify says and whatever it holds
    #   clean --applied --scratch DIR    every run directly under DIR whose work is recorded applied (RUN/applied) and merged
    #   clean --stale DAYS --scratch DIR [--yes]   the finished runs (RUN/verified or RUN/applied) older than DAYS: a plan, removed only with --yes
    CLEAN_RUN='' DISCARD='' ALL='' SCR='' STALE='' YES=''
    while [ $# -gt 0 ]; do
      case $1 in
        --discard) DISCARD=1; shift;;
        --applied) ALL=1; shift;;
        --stale) need_val "$1" $#; STALE=${2:-}; shift 2;;
        --yes) YES=1; shift;;
        --scratch) need_val "$1" $#; SCR=${2:-}; shift 2;;
        -*) usage_die "clean: unknown option $1";;
        *) [ -z "$CLEAN_RUN" ] || usage_die "clean takes one RUN dir"; CLEAN_RUN=$1; shift;;
      esac
    done
    if [ -n "$STALE" ]; then
      [ -z "$ALL$CLEAN_RUN$DISCARD" ] || usage_die "clean --stale takes no RUN dir, no --applied and no --discard: it cleans only finished runs, and each by the rules of clean"
      case $STALE in ''|*[!0-9]*) usage_die "clean --stale needs a whole number of days, got '$STALE'";; esac
      [ -n "$SCR" ] || usage_die "clean --stale needs --scratch DIR, the directory the runs were prepared in"
      [ -d "$SCR" ] || die "clean --stale: no such directory $SCR"
      scr=$(readlink -f "$SCR"); nowe=$(date +%s); plan_n=0; done_n=0; kept_n=0; bad_n=0; reg_load
      for d in "$scr"/qargi.??????; do
        [ -d "$d" ] && [ ! -L "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && reg_has "$d" || continue   # a directory prepare made (the registry says so), directly under DIR
        [ -f "$d/verified" ] || [ -f "$d/applied" ] || continue                                      # a run still in progress is never stale
        st=$(cat "$d/started" 2>/dev/null || true)
        [[ $st =~ ^[0-9]{1,12}$ ]] || { echo "skipped $d: no start time recorded, so its age is unknown"; continue; }   # the file is a member's: only digits reach the arithmetic
        age=$(( (nowe - st) / 86400 )); [ "$age" -ge "$STALE" ] || continue
        st=verified; [ ! -f "$d/applied" ] || st=applied
        if [ -z "$YES" ]; then echo "would clean $d ($st, ${age}d old)"; plan_n=$((plan_n + 1)); continue; fi
        if ! why=$("$0" clean "$d" 2>&1 </dev/null); then echo "kept $d: ${why#qargi: }"; kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue; fi
        echo "$why"; done_n=$((done_n + 1))
      done
      if [ -z "$YES" ]; then echo "plan: $plan_n finished run(s) older than $STALE day(s) under $scr; nothing changed, add --yes to clean them"; exit 0; fi
      echo "cleaned $done_n run(s), kept $kept_n"
      [ "$bad_n" = 0 ] || exit 1   # a stale run that clean refused (never applied, not merged, refs changed) stays, named, with the reason
      exit 0
    fi
    [ -z "$YES" ] || die "clean: --yes is for --stale"
    if [ -n "$ALL" ]; then
      [ -z "$CLEAN_RUN$DISCARD" ] || usage_die "clean --applied takes no RUN dir and no --discard: it cleans only what is applied and merged"
      [ -d "$SCR" ] || usage_die "clean --applied needs --scratch DIR, the directory the runs were prepared in"
      scr=$(readlink -f "$SCR"); done_n=0; kept_n=0; bad_n=0; reg_load
      for d in "$scr"/qargi.??????; do
        [ -d "$d" ] && [ ! -L "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && reg_has "$d" || continue   # a directory prepare made (the registry says so), directly under DIR
        if [ ! -f "$d/applied" ]; then echo "kept $d: its work is not recorded applied"; kept_n=$((kept_n + 1)); continue; fi
        if [ -z "$(reg_get "$d" repo)" ]; then echo "kept $d: whether it is merged cannot be checked for a run of a repository URL"; kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue; fi
        if ! why=$("$0" clean "$d" 2>&1 </dev/null); then echo "kept $d: ${why#qargi: }"; kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue; fi
        echo "$why"; done_n=$((done_n + 1))
      done
      echo "cleaned $done_n run(s), kept $kept_n"
      [ "$bad_n" = 0 ] || exit 1   # an applied run that was refused (not merged, refs changed); a run still in progress is no failure
      exit 0
    fi
    [ -z "$SCR" ] || die "clean: --scratch is for --applied and --stale"
    reg_load
    RUN=$CLEAN_RUN
    while [ "${RUN%/}" != "$RUN" ] && [ "$RUN" != / ]; do RUN=${RUN%/}; done   # a trailing slash makes rm -rf follow a link
    [ ! -L "$RUN" ] || die "clean: $RUN is a link, not a directory prepare made"
    [ -f "$RUN/refs.before" ] && [ -f "$RUN/ability" ] && case $(basename "$RUN") in qargi.??????) ;; *) false;; esac \
      || usage_die "clean needs a RUN dir made by prepare"
    [ -n "$DISCARD" ] || [ -f "$RUN/out/manifest.json" ] || [ -n "$(find "$RUN/out" -name '*manifest.json' 2>/dev/null | head -1)" ] \
      || die "$RUN/out holds no manifest: collect the work first, or --discard to drop a run that produced none"
    # changed refs are evidence: kept, unless the run is dropped on purpose (--discard), which says so and goes on
    vrc=0; vout=$("$0" verify "$RUN" 2>&1 </dev/null) || vrc=$?
    if [ "$vrc" = 3 ]; then   # the registry does not vouch for the run directory: nothing was asked of any repository
      [ -n "$DISCARD" ] || die "${vout#qargi: }"
      echo "qargi: warning: the lead's registry does not vouch for $RUN; dropped on purpose:" >&2
      sed 's/^/  /' <<<"$vout" >&2
    elif [ "$vrc" != 0 ]; then
      [ -n "$DISCARD" ] || die "the refs of the repository changed during this run: keep $RUN as evidence and tell the user (qargi local verify $RUN)"
      echo "qargi: warning: the refs of the repository changed during this run; dropped on purpose:" >&2
      sed 's/^/  /' <<<"$vout" >&2
    fi
    acc=''; [ "$vrc" != 0 ] || acc=$(sed -n 's/^  /accepted, the lead'"'"'s own move: /p' <<<"$vout")   # what verify accepted, named again when the run is cleaned
    # finished work is never dropped before it is merged: commits in the clone must be applied (review apply) and the applied tip must
    # be on a branch other than agent/*, in the real repository. --discard is the deliberate way to drop them.
    nc=$(git -C "$RUN/clone" rev-list --count HEAD --not --remotes=origin 2>/dev/null || echo 0)
    if [ "${nc:-0}" -gt 0 ]; then
      if [ -n "$DISCARD" ]; then echo "qargi: dropped $nc unmerged commit(s) of $RUN on purpose" >&2
      else
        [ -f "$RUN/applied" ] || die "$RUN holds $nc commit(s) that were never applied: qargi review apply $RUN, then qargi feature merge, then clean (--discard drops them on purpose)"
        read -r _ab atip _ < "$RUN/applied"
        rp=$(reg_get "$RUN" repo)   # the lead's registry, never RUN/repo.path
        if [ -n "$rp" ]; then
          mrc=0; merged_tip "$rp" "${atip:-}" || mrc=$?
          [ "$mrc" != 2 ] || die "$RUN/applied does not hold a commit name as its second word, so whether the work is merged cannot be checked: look at it, or --discard drops the run on purpose"
          [ "$mrc" = 0 ] || die "$RUN's work (${atip:0:12}) is not merged into any branch yet: qargi feature merge NAME $_ab, then clean (--discard drops it on purpose)"
        fi
      fi
    fi
    # the run's temporary directory is the one the lead's registry names for this run directory ($DA_STATE/local-runs.jsonl, written by prepare), else RUN/tmp:
    # never the run's own tmpdir file, which a member can write and which could name another run's directory. It is removed only when it is where prepare puts
    # one: RUN/tmp, or qargi-run.XXXXXX directly under /dev/shm (QARGI_RUN_TMP, when prepare was told to use another parent); a recorded path anywhere else is
    # left alone. The recorded text is only a claim until checked: the trailing slashes are stripped (rm -rf on a link with one empties what the link leads
    # to), a link is refused after that, the real path of the directory must be directly under the real path of that parent (no link in between), and what
    # is removed is that real path, on its own file system.
    t=$(reg_get "$RUN" tmpdir)
    [ -n "$t" ] || t=$RUN/tmp
    while [ "${t%/}" != "$t" ] && [ "$t" != / ]; do t=${t%/}; done
    rt=''
    if [ -n "$t" ] && [ ! -L "$t" ] && [ -d "$t" ]; then
      name=$(basename -- "$t"); par=$(dirname -- "$t"); rp=$(realpath -- "$t" 2>/dev/null || true)
      if [ -n "$rp" ] && [ "$(basename -- "$rp")" = "$name" ]; then
        case $name in
          qargi-run.??????)
            for b in /dev/shm "${QARGI_RUN_TMP:-}"; do
              while [ "${b%/}" != "$b" ] && [ "$b" != / ]; do b=${b%/}; done
              [ -n "$b" ] && [ "$par" = "$b" ] && [ "$(dirname -- "$rp")" = "$(realpath -- "$b" 2>/dev/null)" ] && rt=$rp
            done;;
          tmp) [ "$(dirname -- "$rp")" = "$(realpath -- "$RUN")" ] && rt=$rp;;
        esac
      fi
    fi
    if [ -z "$rt" ] && [ -n "$t" ]; then echo "qargi: note: left $t alone: it is not a directory prepare makes under /dev/shm, QARGI_RUN_TMP or the run" >&2; fi
    [ -z "$rt" ] || rm -rf --one-file-system -- "$rt"
    rm -rf --one-file-system -- "$RUN"
    [ -z "$acc" ] || printf '%s\n' "$acc"
    echo "cleaned $RUN${rt:+ and $rt}";;
  list)
    # read-only: the runs under --scratch DIR (the directories prepare made), else the runs of the registry that still exist
    SCR=''
    while [ $# -gt 0 ]; do
      case $1 in --scratch) need_val "$1" $#; SCR=${2:-}; shift 2;; *) usage_die "list: unknown option $1";; esac
    done
    runs=(); reg_load
    if [ -n "$SCR" ]; then
      [ -d "$SCR" ] || die "list: no such directory $SCR"
      for d in "$(readlink -f "$SCR")"/qargi.??????; do [ -d "$d" ] && [ ! -L "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && reg_has "$d" && runs+=("$d"); done
    else
      for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do [ -d "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && runs+=("$d"); done
    fi
    printf '%-10s %-18s %-10s %-6s %-8s %s\n' ROLE SLUG AGE APPLIED MERGED RUN
    nowe=$(date +%s)
    plain() { LC_ALL=C tr -d '\000-\037\177'; }   # the files of a run are a member's to write: no control or escape byte reaches the terminal
    for d in ${runs[@]+"${runs[@]}"}; do
      sl=$(reg_get "$d" slug)
      st=$(cat "$d/started" 2>/dev/null || true)
      if [[ $st =~ ^[0-9]{1,12}$ ]]; then   # the file is a member's: only digits ever reach the arithmetic
        age=$((nowe - st))
        if [ "$age" -ge 86400 ]; then ag="$((age / 86400))d"; elif [ "$age" -ge 3600 ]; then ag="$((age / 3600))h"; else ag="$((age / 60))m"; fi
      else ag='?'; fi
      ap=no; mg=no
      if [ -f "$d/applied" ]; then
        ap=yes; read -r _ab atip _ < "$d/applied"; rp=$(reg_get "$d" repo)
        if [ -z "$rp" ]; then mg='?'
        else mrc=0; merged_tip "$rp" "${atip:-}" || mrc=$?; case $mrc in 0) mg=yes;; 2) mg='?';; esac; fi
      fi
      printf '%-10s %-18s %-10s %-6s %-8s %s\n' "$( (cat "$d/ability" 2>/dev/null || echo '?') | plain)" "$(printf '%s' "${sl:--}" | plain)" "$ag" "$ap" "$mg" "$(printf '%s' "$d" | plain)"
    done;;
  run)
    # the project of the run is the stored one that has its repository; its local runtime says how to start the member (lib/local_run.py)
    RUN=${1:-}; shift || true
    [ -f "$RUN/refs.before" ] && [ -f "$RUN/ability" ] || usage_die "run needs a RUN dir made by prepare"
    for a in "$@"; do case $a in --project|--runtime|--class) die "run: $a is not an option (the project and its runtime come from the run)";; esac; done
    reg_load; run_record "$RUN" || exit 2   # the project is found by the repository the lead's registry records, not by files in the run directory
    RPJ=$(project_of "$RUN_REPO" "$RUN_URL")
    [ -n "$RPJ" ] || { echo "qargi: no stored project has the repository of this run, so no runtime is known: store it (qargi project attach) and give it a local provider (qargi project set PROJECT models.provider.local NAME)" >&2; exit 2; }
    RPROV=$(project_provider "$RPJ" local) || exit $?
    exec python3 -I "$(dirname "$0")/local_run.py" "$RUN" --project "$RPJ" --runtime "$RPROV" --class "$(run_class "$RUN")" "$@";;
  *) usage_die "usage: local.sh prepare|verify|clean|list|run ...";;
esac
