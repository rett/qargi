#!/usr/bin/env bash
# shellcheck disable=SC2154  # af, REPO, PROJ come from gitflow.sh (project_load)
# A fork that follows an upstream repository. The project keeps its own changes, the overlay, on top of it; one local branch
# (the answers' upstream.into, default upstream) carries the upstream line and nothing else. The answers name the remote
# (upstream.remote) and the branch it follows (upstream.branch); upstream.overlay_check, optional, is a command array that
# checks the overlay still applies or builds.
#
#   upstream.sh status [--project P]             fetch that one branch of that remote (the only verb that reaches the network) and say how far
#                                                `into` is behind and ahead of it, with the newest upstream commits
#   upstream.sh review [--limit N] [--project P] the upstream commits not yet in `into` (from the last fetch), the files each touches, and a
#                                                mark on the ones that touch a file the overlay changed (develop since it parted from `into`)
#   upstream.sh sync [--project P] [--plan T --approved W]
#                                                fast-forward `into` to the fetched upstream branch, only as a fast-forward: a plan and a token
#                                                first, the move journaled, nothing pushed, nothing merged into develop. Refused when `into`
#                                                has commits of its own. With upstream.overlay_check, the command then runs on a trial merge
#                                                of `into` into develop in a temporary worktree (the fast-forward stands either way).
# The upstream line never meets develop directly: after a sync, cut a feature and merge the branch into it (qargi feature start
# upstream-X, qargi feature merge upstream-X BRANCH), fix the overlay there, and let the feature land as any other.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
PROJ='' LIMIT=30 PLAN_ARG='' APPROVED=''
USAGE="usage: qargi upstream status|review|sync [--limit N] [--project P] [--plan T --approved WORDS]"
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --limit) need_val "$1" $#; LIMIT=$2; shift 2;;
    --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    -*) usage_die "unknown option $1";;
    *) usage_die "$USAGE";;
  esac
done
export PLAN_ARG   # need_plan reads it
case $verb in status|review|sync) ;; *) usage_die "$USAGE";; esac
printf '%s' "$LIMIT" | grep -Eq '^[1-9][0-9]*$' || usage_die "--limit needs a positive number"
. "$(dirname "$0")/gitflow.sh"
project_load
UREM=$(jq -r '.upstream.remote // ""' "$af"); UBR=$(jq -r '.upstream.branch // ""' "$af"); INTO=$(jq -r '.upstream.into // "upstream"' "$af")
[ -n "$UREM" ] && [ -n "$UBR" ] || die "no upstream answers for $PROJ: qargi project set $PROJ upstream.remote REMOTE and upstream.branch BRANCH (the remote and the branch the fork follows; upstream.into, default upstream, is the local branch that carries the upstream line)"
g remote get-url "$UREM" >/dev/null 2>&1 || die "the repository has no remote named $UREM (upstream.remote): git -C $REPO remote add $UREM URL"
mapfile -t OVERLAY_CHECK < <(jq -r '(.upstream.overlay_check // []) | if type == "array" then .[] else empty end' "$af")
RT=refs/remotes/$UREM/$UBR
utip() { g rev-parse -q --verify "$RT^{commit}" || true; }
need_fetched() { U=$(utip); [ -n "$U" ] || die "$UREM/$UBR is not fetched yet: qargi upstream status fetches it"; }
log1() { g log -1 --format='%h %ad %s' --date=short "$1"; }

case $verb in
  status)
    out=$(GIT_TERMINAL_PROMPT=0 git -C "$REPO" fetch -q --no-tags "$UREM" "+refs/heads/$UBR:$RT" 2>&1 </dev/null) || die "could not fetch $UBR from $UREM: ${out:-git fetch failed}"
    U=$(utip); [ -n "$U" ] || die "$UREM has no branch $UBR (upstream.branch)"
    H=$(sha_of "$INTO")
    if [ -z "$H" ]; then
      echo "upstream $UREM/$UBR at ${U:0:7} (fetched); no local branch $INTO yet (upstream.into): qargi upstream sync creates it there"
      echo "newest upstream commits:"; g log --format='  %h %ad %s' --date=short -n 10 "$RT"
      exit 0
    fi
    behind=$(g rev-list --count "$INTO..$RT"); ahead=$(g rev-list --count "$RT..$INTO")
    echo "upstream $UREM/$UBR at ${U:0:7} (fetched); $INTO at ${H:0:7}: $behind behind, $ahead ahead"
    [ "$ahead" = 0 ] || echo "  note: $INTO has $ahead commit(s) that $UREM/$UBR lacks; it carries the upstream line only, so sync will refuse (not a fast-forward)"
    if [ "$behind" = 0 ]; then echo "nothing new upstream; newest: $(log1 "$RT")"
    else
      echo "new upstream commits (newest first; qargi upstream review lists the files):"
      g log --format='  %h %ad %s' --date=short "$INTO..$RT" | head -10
      [ "$behind" -le 10 ] || echo "  ... and $((behind - 10)) more"
    fi;;
  review)
    need_fetched
    H=$(sha_of "$INTO"); [ -n "$H" ] || die "no local branch $INTO (upstream.into): qargi upstream sync creates it at $UREM/$UBR, or make it at the commit the fork was taken from (git branch $INTO COMMIT)"
    branch_exists develop || die "no develop branch: the overlay is what develop changed since it parted from $INTO"
    mb=$(g merge-base "$INTO" develop 2>/dev/null) || die "$INTO and develop have no common history: upstream.into should be the branch the fork was taken from"
    OV=$(mktemp "$DA_STATE/.overlay.XXXXXX")
    g diff --name-only "$mb" develop | LC_ALL=C sort -u > "$OV"
    n=$(g rev-list --count "$INTO..$RT")
    echo "upstream commits not in $INTO: $n ($UREM/$UBR at ${U:0:7}, as of the last fetch); overlay: $(wc -l < "$OV") file(s) develop changed since ${mb:0:7}"
    [ "$n" != 0 ] || { rm -f "$OV"; exit 0; }
    listed=$n; [ "$n" -le "$LIMIT" ] || listed=$LIMIT
    shown=0 hits=0
    while read -r sha; do
      shown=$((shown + 1)); [ "$shown" -le "$LIMIT" ] || break
      files=$(g log -1 -m --first-parent --name-only --format= "$sha" | grep -v '^$' | LC_ALL=C sort -u)
      hit=$(comm -12 <(printf '%s\n' "$files") "$OV" | tr '\n' ' '); hit=${hit% }
      [ -z "$hit" ] || hits=$((hits + 1))
      echo "  $(log1 "$sha")${hit:+  [overlay: $hit]}"
      printf '%s\n' "$files" | grep -v '^$' | head -20 | sed 's/^/      /'
      [ "$(printf '%s\n' "$files" | grep -vc '^$')" -le 20 ] || echo "      ... (more files)"
    done < <(g rev-list "$INTO..$RT")
    [ "$n" -le "$LIMIT" ] || echo "  ... and $((n - LIMIT)) more (--limit N)"
    rm -f "$OV"
    echo "$hits of the $listed listed touch a file the overlay changed";;
  sync)
    need_fetched
    H=$(sha_of "$INTO")
    [ "$H" != "$U" ] || { echo "$INTO is at $UREM/$UBR already (${U:0:7})"; exit 0; }
    if [ -n "$H" ] && ! g merge-base --is-ancestor "$H" "$RT"; then
      echo "qargi: $INTO has commit(s) that $UREM/$UBR lacks (not a fast-forward):" >&2
      g log --format='  %h %s' "$RT..$INTO" | head -20 >&2
      die "$INTO carries the upstream line only; keep those commits on a branch of their own (git branch NAME $INTO) and put $INTO back on the line (git branch -f $INTO \$(git merge-base $INTO $RT)), or set upstream.into to the branch that follows upstream"
    fi
    [ -z "$H" ] || need_free_wt "$INTO"
    if [ -n "$H" ]; then n=$(g rev-list --count "$INTO..$RT"); else n=$(g rev-list --count "$RT"); fi
    tok=$(printf '%s\n%s\n%s\n%s\n' "$PROJ" "$INTO" "$H" "$U" | plan_token)
    if [ -n "$H" ]; then
      echo "fast-forward $INTO from ${H:0:7} to $UREM/$UBR (${U:0:7}): $n commit(s), local only (nothing is pushed, nothing is merged into develop)"
      show_incoming "$INTO" "$RT"
    else
      echo "create $INTO at $UREM/$UBR (${U:0:7}), $n commit(s) of upstream history, local only (nothing is pushed, nothing is merged into develop)"
    fi
    [ "${#OVERLAY_CHECK[@]}" = 0 ] || echo "  then the overlay check runs on a trial merge of $INTO into develop: ${OVERLAY_CHECK[*]}"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi upstream sync --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    g update-ref "refs/heads/$INTO" "$U" "${H:-0000000000000000000000000000000000000000}" || die "could not move $INTO (it changed meanwhile)"
    [ -z "$H" ] || wt_follow "$INTO" "$U"
    journal_ref "$REPO" "refs/heads/$INTO" "$H" "$U" upstream:sync
    audit_log "upstream:sync" "$PROJ $INTO ${H:0:7}..${U:0:7}"
    x=${U:0:7}
    echo "$INTO is at $UREM/$UBR ($x)$([ -n "$H" ] || echo "; created $INTO")"
    echo "next: qargi feature start upstream-$x --purpose \"upstream $UBR at $x\", then qargi feature merge upstream-$x $INTO: review and fix the overlay in that feature; $INTO itself is never merged into develop"
    rc=0
    if [ "${#OVERLAY_CHECK[@]}" != 0 ]; then
      if ! branch_exists develop; then echo "overlay check: not run (no develop branch)"
      else
        worktree develop
        if git -C "$WT" merge -q --no-commit --no-ff "refs/heads/$INTO" >/dev/null 2>&1; then
          if run_clean "$WT" "${OVERLAY_CHECK[@]}"; then echo "overlay check: pass (${OVERLAY_CHECK[*]} on a trial merge of $INTO into develop)"
          else echo "overlay check: fail (${OVERLAY_CHECK[*]} on a trial merge of $INTO into develop); the fast-forward stands, the overlay needs work in the feature"; rc=1; fi
        else
          echo "overlay check: not run; merging $INTO into develop conflicts in: $(git -C "$WT" diff --name-only --diff-filter=U | tr '\n' ' ')(resolve it in the feature)"; rc=1
        fi
        cleanup
      fi
    fi
    exit $rc;;
esac
