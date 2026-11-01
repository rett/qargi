#!/usr/bin/env bash
# shellcheck disable=SC2154  # af, REPO, PROJ, TESTCMD come from gitflow.sh (project_load)
# Releases and hotfixes, by the git-flow rules of "A successful Git branching model":
#   release/<version>  from develop, merged into master (tagged) and back into develop, then deleted
#   hotfix/<version>   from master,  merged into master (tagged) and into develop, or into the open release branch
# The merges are --no-ff. The commands are those the model lists, done in temporary worktrees; a branch moves only after
# every merge has succeeded, so a conflict leaves everything as it was. Between start and finish the branch is pushed
# and a pull request into master runs CI on the commit that will be released.
#
#   release.sh start VERSION [--hotfix]     branch from develop (master for a hotfix); the first commit bumps VERSION and dates
#                                           the changelog and man page. A release starts only from a develop whose head passed `verify`.
#                                           Preflight: a man page's .TH date and version are set too, and a CHANGELOG.md needs
#                                           content under '## [Unreleased]' (--allow-empty-notes waives that); otherwise it refuses.
#   release.sh status VERSION [--hotfix]
#   release.sh verify VERSION [--hotfix]    run the whole suite on the branch head (develop's head before a release starts)
#   release.sh push VERSION [--hotfix] [--plan T --approved W]     push the branch, open the pull request into master
#   release.sh finish VERSION [--hotfix] [--keep] [--plan T --approved W]
#                                           after the checks pass: merge, tag, back-merge, delete the branch, push
#
# Options for all: --project P, --date D. Pushing, merging and tagging need the plan token and an approval.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
VER='' PROJ='' DATE='' PLAN_ARG='' APPROVED='' HOTFIX='' KEEP='' RESOLVED='' ALLOW_EMPTY=''
while [ $# -gt 0 ]; do
  case $1 in
    --project) PROJ=$2; shift 2;; --date) DATE=$2; shift 2;; --plan) PLAN_ARG=$2; shift 2;; --approved) APPROVED=$2; shift 2;;
    --hotfix) HOTFIX=1; shift;; --keep) KEEP=1; shift;; --resolved) RESOLVED=1; shift;; --allow-empty-notes) ALLOW_EMPTY=1; shift;;
    -*) die "unknown option $1";; *) VER=$1; shift;;
  esac
done
export PLAN_ARG RESOLVED   # need_plan reads PLAN_ARG; merge_step reads RESOLVED

[ -n "$VER" ] || die "usage: qargi release start|status|verify|push|finish VERSION [--hotfix] [--project P]"
printf '%s' "$VER" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "'$VER' is not a version like 0.1.1"
. "$(dirname "$0")/gitflow.sh"
project_load
read -r REL_PAT HOT_PAT < <(python3 -I - "$(dirname "$0")" "$METH" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import methodology as M
b = M.load(sys.argv[2])[2]["branches"]
print(b["release"], b.get("hotfix", "hotfix/{version}"))
PY
) || exit 1
if [ -n "$HOTFIX" ]; then BR=${HOT_PAT//\{version\}/$VER} BASE=master KIND=hotfix; else BR=${REL_PAT//\{version\}/$VER} BASE=develop KIND=release; fi
RELPREFIX=${REL_PAT%%\{version\}*}
open_release() { g for-each-ref --format='%(refname:short)' "refs/heads/${RELPREFIX}*"; }   # the open release branches

case $verb in
  start)
    branch_exists "$BR" && die "$BR exists already"
    branch_exists "$BASE" || die "no $BASE branch to start from"
    if [ "$KIND" = release ]; then
      v=$(verified "$BASE")
      [ "$v" = "$(sha_of develop) pass" ] || die "the whole suite has no passing run at the head of develop (qargi release verify $VER); run it at the checkpoint, then start"
    else
      g rev-parse -q --verify "refs/tags/$VER" >/dev/null && die "the tag $VER exists already"
    fi
    [ -n "$DATE" ] || DATE=$(date +%F)
    printf '%s' "$DATE" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' || die "--date YYYY-MM-DD"
    b0=$(sha_of "$BASE")
    worktree "$BASE"
    git -C "$WT" checkout -q --detach "$b0"
    # the preflight: every file the release must update is checked and rewritten in the temporary worktree first; a refusal
    # exits before any branch exists, so nothing has changed
    oldver=''; [ -f "$WT/VERSION" ] && oldver=$(tr -d '[:space:]' < "$WT/VERSION")
    if [ -f "$WT/VERSION" ]; then echo "$VER" > "$WT/VERSION"; git -C "$WT" add VERSION; fi
    while IFS= read -r mp; do
      [ -n "$mp" ] || continue
      python3 -I - "$WT/$mp" "$mp" "$VER" "$DATE" "$oldver" <<'PY' || exit 1
import re, sys
path, name, ver, date, old = sys.argv[1:6]
def refuse(why):
    sys.exit("qargi: %s: %s. Fix: make its .TH line read .TH NAME SECTION \"DATE\" \"NAME VERSION\", then start the release again." % (name, why))
lines = open(path, encoding="utf-8").read().split("\n")
for i, l in enumerate(lines):
    if l.startswith(".TH ") or l == ".TH":
        break
else:
    refuse("it has no .TH line, so the release cannot set its date and version")
tok = re.findall(r'"[^"]*"|\S+', lines[i])
if len(tok) < 5:
    refuse("its .TH line has no date and source (version) fields, so the bump cannot update them")
src = tok[4].strip('"')
if old and old in src:
    src = src.replace(old, ver)
else:
    m = list(re.finditer(r"\d+\.\d+\.\d+[\w.+-]*", src))
    if not m:
        refuse("the source field of its .TH line (%s) carries no version, so the bump cannot update it" % tok[4])
    src = src[:m[-1].start()] + ver + src[m[-1].end():]
tok[3] = '"%s"' % date
tok[4] = '"%s"' % src
lines[i] = " ".join(tok)
open(path, "w", encoding="utf-8").write("\n".join(lines))
PY
      git -C "$WT" add "$mp"
    done < <(git -C "$WT" ls-files | grep -E '(^|/)man[0-9]?/[^/]+\.[1-9]$' || true)
    if [ -f "$WT/CHANGELOG.md" ]; then
      python3 -I - "$WT/CHANGELOG.md" "$VER" "$DATE" "$ALLOW_EMPTY" <<'PY' || exit 1
import re, sys
p, ver, date, allow = sys.argv[1:5]
t = open(p, encoding="utf-8").read()
m = re.search(r"^## \[Unreleased\][^\n]*\n", t, re.M)
if not m:
    sys.exit("qargi: CHANGELOG.md has no '## [Unreleased]' section to release. Fix: add one with the changes of this release, then start again.")
rest = t[m.end():]
n = re.search(r"^## ", rest, re.M)
body = rest[:n.start()] if n else rest
if not allow and not [l for l in body.split("\n") if l.strip() and not l.startswith("#")]:
    sys.exit("qargi: CHANGELOG.md has nothing under '## [Unreleased]'. Fix: record the changes of this release there (or pass --allow-empty-notes to release without notes), then start again.")
open(p, "w", encoding="utf-8").write(t.replace("## [Unreleased]", "## [Unreleased]\n\n## [%s] - %s" % (ver, date), 1))
PY
      git -C "$WT" add CHANGELOG.md
    fi
    wcommit --allow-empty -m "Bumped version number to $VER"
    g update-ref "refs/heads/$BR" "$(git -C "$WT" rev-parse HEAD)" "" || die "could not create $BR"
    journal_ref "$REPO" "refs/heads/$BR" "" "$(sha_of "$BR")" "$KIND:start"
    echo "created $BR from $BASE ($(g rev-parse --short "$BR")): the version is $VER and the changelog (and a man page) is dated $DATE"
    echo "other files that carry the version (a manifest) are yours to bump on this branch"
    echo "only minor fixes belong here; new features wait for the next release. Then: qargi release push $VER${HOTFIX:+ --hotfix}";;
  status)
    h=$(sha_of "$BR")
    if [ -z "$h" ]; then
      echo "no $BR yet. develop is at $(g rev-parse --short develop 2>/dev/null || echo '?'), full suite: $(v=$(verified "$BASE"); if [ -z "$v" ]; then echo "not run"; elif [ "${v%% *}" = "$(sha_of "$BASE")" ]; then echo "${v##* } at this head"; else echo "${v##* } at an older head"; fi)"
      remote_report "$BASE"
      exit 0
    fi
    echo "$KIND $VER of $PROJ on $BR at $(g rev-parse --short "$BR"), $(g rev-list --count "$BASE..$BR") commit(s) ahead of $BASE"
    g log --format='  %h %s' "$BASE..$BR" | head -20
    v=$(verified "$BR"); if [ -z "$v" ]; then echo "full suite: not run on this branch"; elif [ "${v%% *}" = "$h" ]; then echo "full suite: ${v##* } at this head"; else echo "full suite: ${v##* } at an older head"; fi
    remote_report "$BR"; remote_report "$BASE"
    g rev-parse -q --verify "refs/tags/$VER" >/dev/null && echo "tag $VER exists" || true;;
  verify)
    [ -n "$TESTCMD" ] || die "no test_command in the answers for $PROJ: qargi project set $PROJ test_command '...'"
    on=$BR; branch_exists "$BR" || on=$BASE
    h=$(sha_of "$on"); [ -n "$h" ] || die "no branch $on"
    worktree "$h"
    echo "running the whole suite on $on at $(g rev-parse --short "$on"): $TESTCMD"
    if run_suite; then res=pass; else res=fail; fi
    jq -nc --arg s "$h" --arg r "$res" --arg t "$(now)" --arg c "$TESTCMD" '{sha:$s, result:$r, at:$t, command:$c}' > "$(rec "$on")"
    echo "full suite: $res at $(g rev-parse --short "$on")"; [ "$res" = pass ];;
  push)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi release start $VER${HOTFIX:+ --hotfix})"
    g remote get-url origin >/dev/null 2>&1 || die "the repository has no origin remote to push $BR to"
    tok=$(printf '%s\n%s\n%s\n' "$PROJ" "$BR" "$h" | plan_token)
    echo "push $BR (at $(g rev-parse --short "$BR")) to origin and open a pull request into master, so CI runs on the commit that will be released"
    remote_report "$BR"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi release push $VER${HOTFIX:+ --hotfix} --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    g push -q -u origin "$BR" || die "pushing $BR failed"
    audit_log "release:push" "$PROJ $BR"
    command -v gh >/dev/null 2>&1 || die "pushed $BR, but gh is not installed: open the pull request into master yourself"
    url=$(cd "$REPO" && gh pr create --base master --head "$BR" --title "$VER" --body "$KIND $VER" 2>&1) || die "pushed $BR; gh pr create failed: $url"
    echo "pushed $BR and opened: $url"
    echo "when its checks pass: qargi release finish $VER${HOTFIX:+ --hotfix}";;
  finish)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR"
    branch_exists master && branch_exists develop || die "git-flow needs a master and a develop branch"
    g rev-parse -q --verify "refs/tags/$VER" >/dev/null && die "the tag $VER exists already"
    if [ -f "$REPO/VERSION" ] || g cat-file -e "$BR:VERSION" 2>/dev/null; then g show "$BR:VERSION" 2>/dev/null | grep -qx "$VER" || die "$BR does not carry VERSION $VER"; fi
    # the second target: develop, or for a hotfix the open release branch (the fix reaches develop when that is finished)
    second=develop
    if [ "$KIND" = hotfix ]; then
      rels=$(open_release); n=$(printf '%s' "$rels" | grep -c . || true)
      [ "$n" -le 1 ] || die "more than one release branch is open ($(echo "$rels" | tr '\n' ' ')): merge this hotfix into the right one by hand"
      [ "$n" = 0 ] || second=$rels
    fi
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$BR" "$h" "$second" "$(sha_of master)" "$(sha_of "$second")" "$KEEP" | plan_token)
    echo "finish $KIND $VER of $PROJ: merge $BR into master with --no-ff, tag $VER on it, merge $BR into $second with --no-ff${KEEP:+, keep $BR}$([ -n "$KEEP" ] || echo ", delete $BR"), push master, $second and the tag together (all or none)"
    remote_report "$BR"; remote_report master; remote_report "$second"
    show_incoming master "$BR"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi release finish $VER${HOTFIX:+ --hotfix}${KEEP:+ --keep} --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    if g remote get-url origin >/dev/null 2>&1; then
      g fetch -q origin || die "fetch failed"
      g rev-parse -q --verify "refs/remotes/origin/$BR" >/dev/null || die "$BR is not on origin: qargi release push $VER${HOTFIX:+ --hotfix} (CI must see what is released)"
      [ "$(g rev-parse "origin/$BR")" = "$h" ] || die "origin/$BR is not the local $BR: the pull request's checks ran on a different commit. Push it (qargi release push) and wait for the checks"
      for b in master "$second"; do
        if g rev-parse -q --verify "refs/remotes/origin/$b" >/dev/null; then
          g merge-base --is-ancestor "origin/$b" "$b" || die "$b is behind or differs from origin/$b: reconcile them first"
        fi
      done
      command -v gh >/dev/null 2>&1 || die "gh is needed to read the pull request's checks"
      gh -R "$(jq -r '.repo.url' "$af" | sed 's|^https://[^/]*/||')" pr checks "$BR" >/dev/null 2>&1 || die "the pull request's checks have not all passed (or there is no pull request for $BR): nothing was merged or pushed"
    else
      [ "$(verified "$BR")" = "$h pass" ] || die "the repository has no origin, so no CI: the whole suite must have a passing run at the head of $BR (qargi release verify $VER${HOTFIX:+ --hotfix})"
      echo "note: no origin remote, so no CI ran on $BR; the local whole-suite run stands in" >&2
    fi
    need_free master "$second" "$BR"
    m0=$(sha_of master); s0=$(sha_of "$second")
    k1="$KIND-$VER-into-master"; k2="$KIND-$VER-into-${second//\//_}"
    merge_step "$m0" "refs/heads/$BR" "$k1" "Merge branch '$BR'"
    nm=$MERGED
    merge_step "$s0" "refs/heads/$BR" "$k2" "Merge branch '$BR' into $second"
    ns=$MERGED
    g tag -a "$VER" -m "$VER" "$nm"
    if g remote get-url origin >/dev/null 2>&1; then
      # all or none: the push comes before any local branch moves, so a failure changes nothing
      if ! g push -q --atomic origin "$nm:refs/heads/master" "$ns:refs/heads/$second" "refs/tags/$VER"; then
        g tag -d "$VER" >/dev/null 2>&1; die "the push failed; nothing was changed locally or on origin (run it again)"
      fi
    fi
    g update-ref refs/heads/master "$nm" "$m0" && g update-ref "refs/heads/$second" "$ns" "$s0" || die "origin has the release but master or $second moved locally meanwhile: git fetch origin, then check master and $second against origin"
    journal_ref "$REPO" refs/heads/master "$m0" "$nm" "$KIND:finish"
    journal_ref "$REPO" "refs/heads/$second" "$s0" "$ns" "$KIND:finish"
    merge_forget "$k1" "$k2"
    if [ -z "$KEEP" ]; then g update-ref -d "refs/heads/$BR" "$h"; journal_ref "$REPO" "refs/heads/$BR" "$h" "" "$KIND:finish"; fi
    audit_log "release:finish" "$PROJ $VER"
    echo "merged $BR into master (tagged $VER) and into $second${KEEP:+; kept $BR}$([ -n "$KEEP" ] || echo "; deleted $BR")"
    if g remote get-url origin >/dev/null 2>&1; then
      if [ -z "$KEEP" ] && g rev-parse -q --verify "refs/remotes/origin/$BR" >/dev/null; then g push -q origin --delete "$BR" || echo "note: could not delete origin/$BR" >&2; fi
      echo "pushed master, $second and tag $VER"
    else
      echo "no origin remote: nothing was pushed"
    fi;;
  *) die "usage: qargi release start|status|verify|push|finish VERSION [--hotfix] [--project P]";;
esac
