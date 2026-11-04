#!/usr/bin/env bash
# shellcheck disable=SC2154  # af, REPO, PROJ, TESTCMD come from gitflow.sh (project_load)
# Releases and hotfixes, by the usual git-flow rules (long-lived master and develop, short-lived release and hotfix branches):
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
#   release.sh status VERSION [--hotfix]    for an existing tag also warns: no GitHub release for it (gh release view, through
#                                           QARGI_GH), or its commit lacks .github/workflows/release.yml while the branch has it;
#                                           with release.sign set and no release yet it says "awaiting signature" until `sign` recorded
#                                           one that still holds, and "VERSION is ready for signing" when the repository is in the state sign needs
#   release.sh verify VERSION [--hotfix]    run the whole suite on the branch head (develop's head before a release starts); same warnings
#   release.sh push VERSION [--hotfix] [--plan T --approved W]     push the branch, open the pull request into master
#   release.sh finish VERSION [--hotfix] [--keep] [--plan T --approved W]
#                                           after the checks pass: merge, tag, back-merge, delete the branch, push
#
#   release.sh sign VERSION                 sign the files of the answer release.sign.files (ssh-keygen -Y sign -f KEY -n NAMESPACE FILE, one by one),
#                                           run release.sign.verify_command and record the result under STATE/release/. Only from the tag, because the
#                                           release files are built from the tagged commit: after `finish`, before `publish`. The repository's HEAD
#                                           must be the commit of the tag VERSION, on master or detached, with no tracked file modified. ssh-keygen
#                                           runs on the person's own terminal (stdin, stdout and stderr are inherited; nothing is captured and no
#                                           input is logged), so the passphrase is typed there and never passes through qargi; no ssh agent is
#                                           asked (SSH_AUTH_SOCK and SSH_ASKPASS are removed from its environment). Refused when stdin is no
#                                           terminal, in a member run, when QARGI_NESTED is set and when the project has no release.sign (signing is
#                                           optional and off by default; exit 2); the guard refuses it to a member too.
#                                           The verify command is an argv list, run without a shell in the repository.
#
#   release.sh publish VERSION [--plan T --approved W] [--asset FILE]... [--notes-file FILE]
#                                           create the GitHub release of the tag VERSION (gh release create --verify-tag, through
#                                           QARGI_GH) with the tag's changelog section as notes; for a tag pushed before the release
#                                           workflow existed. Refuses when the release exists, the tag is missing or the section is empty.
#                                           The files of --asset and of the answer release.assets (relative to the repository, inside it)
#                                           are attached by the same gh release create. The notes are --notes-file, else the answer
#                                           release.notes_file ({version} replaced), else the changelog section. When release.sign is
#                                           set it refuses until `sign` recorded an ok for VERSION and no signed file changed since; the
#                                           plan token covers the notes and the hash of every asset.
#
# Options for all: --project P, --date D. Pushing, merging and tagging need the plan token and an approval.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
VER='' PROJ='' DATE='' PLAN_ARG='' APPROVED='' HOTFIX='' KEEP='' RESOLVED='' ALLOW_EMPTY='' NOTES_OPT=''; ASSETS=()
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --date) need_val "$1" $#; DATE=$2; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;;
    --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --asset) need_val "$1" $#; ASSETS+=("$2"); shift 2;; --notes-file) need_val "$1" $#; NOTES_OPT=$2; shift 2;;
    --hotfix) HOTFIX=1; shift;; --keep) KEEP=1; shift;; --resolved) RESOLVED=1; shift;; --allow-empty-notes) ALLOW_EMPTY=1; shift;;
    -*) die "unknown option $1";; *) VER=$1; shift;;
  esac
done
[ "$verb" = publish ] || { [ ${#ASSETS[@]} -eq 0 ] && [ -z "$NOTES_OPT" ]; } || die "--asset and --notes-file belong to release publish"
export PLAN_ARG RESOLVED   # need_plan reads PLAN_ARG; merge_step reads RESOLVED

[ -n "$VER" ] || die "usage: qargi release start|status|verify|push|finish|sign|publish VERSION [--hotfix] [--project P]"
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
GH=${QARGI_GH:-gh}   # the one way this script talks to GitHub; tests put a stub here
repo_slug() { jq -r '.repo.url' "$af" | sed 's|^https://[^/]*/||; s|\.git$||'; }
notes=''   # the temporary file of `publish`
rel_exit() { [ -z "$notes" ] || rm -f "$notes"; on_exit; }   # the one EXIT handler: what gitflow.sh cleans up, and the notes file
trap rel_exit EXIT
# gh_release_state TAG -> sets GHS to found|missing|noauth|nogh|unchecked (and GHWHY): does GitHub have a release for the tag? Read-only.
gh_release_state() {
  local out rc=0
  GHWHY=''
  command -v "$GH" >/dev/null 2>&1 || { GHS=nogh; return 0; }
  out=$("$GH" -R "$(repo_slug)" release view "$1" 2>&1 </dev/null) || rc=$?
  if [ "$rc" = 0 ]; then GHS=found
  elif grep -qi 'auth login\|not logged in\|authentication' <<<"$out"; then GHS=noauth
  elif grep -qi 'release not found' <<<"$out"; then GHS=missing
  else GHS=unchecked; GHWHY=$(printf '%s' "$out" | grep -v '^[[:space:]]*$' | head -1 | cut -c1-120); fi
  return 0
}
# tag_checks: for a tag VER that exists, warnings (never a failure) about what stops it from being a published release:
# a tag workflow starts only if the tagged commit holds it, and a release must exist on GitHub for the tag
tag_checks() {
  local tc on
  tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || return 0
  on=$BR; branch_exists "$BR" || on=$BASE
  if g cat-file -e "$on:.github/workflows/release.yml" 2>/dev/null && ! g cat-file -e "$tc:.github/workflows/release.yml" 2>/dev/null; then
    echo "warning: tag $VER (${tc:0:7}) lacks .github/workflows/release.yml, which $on has: pushing a tag starts the release workflow only when the tagged commit contains it. Publish the release with: qargi release publish $VER"
  fi
  g remote get-url origin >/dev/null 2>&1 || return 0   # a tag nobody could have pushed has no release to look for
  gh_release_state "$VER"
  case $GHS in
    missing) echo "warning: tag $VER has no GitHub release. Publish it with: qargi release publish $VER";;
    nogh) echo "note: gh is not installed, so whether GitHub has a release for tag $VER was not checked";;
    noauth) echo "note: gh is not authenticated, so whether GitHub has a release for tag $VER was not checked (gh auth login)";;
    unchecked) echo "note: could not ask GitHub whether tag $VER has a release (${GHWHY:-no answer})";;
  esac
}
open_release() { g for-each-ref --format='%(refname:short)' "refs/heads/${RELPREFIX}*"; }   # the open release branches

# The signing of a release (lib/release_sign.py holds the answers' checks and the record). The record of VER is a file under STATE/release/.
RS=$(dirname "$0")/release_sign.py
SIGNREC=$DA_STATE/release/$PROJ-$VER.sign.json
sign_configured() { jq -e '(.release // {}) | has("sign")' "$af" >/dev/null 2>&1; }
# sign_status: for a tag that exists in a project that signs its releases (and has no GitHub release yet), whether the signature of VER is recorded
# and still true; if not, "awaiting signature" and either that the release is ready for signing or what stands in the way. Read-only.
sign_status() {
  local tc s
  sign_configured || return 0
  tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || return 0
  [ "${GHS:-}" != found ] || return 0
  python3 -I "$RS" config "$af" >/dev/null 2>&1 || { echo "warning: the release answers of $PROJ are not valid (qargi project validate $PROJ), so the signature of $VER was not checked"; return 0; }
  if s=$(python3 -I "$RS" check --state "$SIGNREC" --repo "$REPO" --af "$af" --commit "$tc"); then echo "signature: $s"; return 0; fi
  echo "awaiting signature: $s"
  sign_gate
  if [ -z "$SG_WHY" ]; then echo "$VER is ready for signing: qargi release sign $VER"; else echo "  not ready for signing: $SG_WHY"; fi
}
# sign_gate: sets SG_WHY to why the repository is not in a state to sign VER (empty when it is). The files are built from the tagged commit, so
# the repository's HEAD must be that commit, on master or detached (a develop, feature or other branch is refused) with no tracked file modified.
sign_gate() {
  local tc head br f
  SG_WHY=''
  tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || { SG_WHY="no tag $VER yet (qargi release finish $VER makes it): sign from the tag, after finish and before publish"; return 0; }
  head=$(g rev-parse -q --verify 'HEAD^{commit}') || head=''
  br=$(g symbolic-ref -q --short HEAD) || br=''
  if [ "$head" != "$tc" ]; then
    SG_WHY="HEAD of $REPO is ${br:-detached} at ${head:0:7}, not the tag $VER (${tc:0:7}): git -C $REPO checkout --detach $VER, build the release files there, then sign"; return 0
  fi
  if [ -n "$br" ] && [ "$br" != master ]; then SG_WHY="$REPO is on branch $br: sign from master or a detached HEAD at the tag (git -C $REPO checkout --detach $VER)"; return 0; fi
  if [ -n "$(g status --porcelain --untracked-files=no)" ]; then SG_WHY="tracked files of $REPO are modified: the release files must be built from the tag as it is"; return 0; fi
  while IFS= read -r f; do
    [ -f "$REPO/$f" ] || { SG_WHY="the file $f of release.sign.files does not exist in $REPO: build the release files first"; return 0; }
  done < <(jq -r '.release.sign.files[]' "$af")
}

case $verb in
  start)
    branch_exists "$BR" && die "$BR exists already"
    branch_exists "$BASE" || die "no $BASE branch to start from"
    g rev-parse -q --verify "refs/tags/$VER" >/dev/null && die "the tag $VER exists already"
    if [ "$KIND" = release ]; then
      v=$(verified "$BASE")
      [ "$v" = "$(sha_of develop) pass" ] || die "the whole suite has no passing run at the head of develop (qargi release verify $VER); run it at the checkpoint, then start"
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
      tag_checks
      sign_status
      exit 0
    fi
    echo "$KIND $VER of $PROJ on $BR at $(g rev-parse --short "$BR"), $(g rev-list --count "$BASE..$BR") commit(s) ahead of $BASE"
    g log --format='  %h %s' "$BASE..$BR" | head -20
    v=$(verified "$BR"); if [ -z "$v" ]; then echo "full suite: not run on this branch"; elif [ "${v%% *}" = "$h" ]; then echo "full suite: ${v##* } at this head"; else echo "full suite: ${v##* } at an older head"; fi
    remote_report "$BR"; remote_report "$BASE"
    g rev-parse -q --verify "refs/tags/$VER" >/dev/null && echo "tag $VER exists" || true
    tag_checks
    sign_status;;
  verify)
    [ -n "$TESTCMD" ] || die "no test_command in the answers for $PROJ: qargi project set $PROJ test_command '...'"
    on=$BR; branch_exists "$BR" || on=$BASE
    h=$(sha_of "$on"); [ -n "$h" ] || die "no branch $on"
    worktree "$h"
    echo "running the whole suite on $on at $(g rev-parse --short "$on"): $TESTCMD"
    if run_suite; then res=pass; else res=fail; fi
    jq -nc --arg s "$h" --arg r "$res" --arg t "$(now)" --arg c "$TESTCMD" '{sha:$s, result:$r, at:$t, command:$c}' > "$(rec "$on")"
    echo "full suite: $res at $(g rev-parse --short "$on")"
    tag_checks
    [ "$res" = pass ];;
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
    command -v "$GH" >/dev/null 2>&1 || die "pushed $BR, but gh is not installed: open the pull request into master yourself"
    url=$(cd "$REPO" && "$GH" pr create --base master --head "$BR" --title "$PROJ $VER" --body "$KIND $VER" 2>&1) || die "pushed $BR; gh pr create failed: $url"
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
      command -v "$GH" >/dev/null 2>&1 || die "gh is needed to read the pull request's checks"
      "$GH" -R "$(repo_slug)" pr checks "$BR" >/dev/null 2>&1 || die "the pull request's checks have not all passed (or there is no pull request for $BR): nothing was merged or pushed"
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
  sign)
    python3 -I "$RS" lead-only || exit $?
    sign_configured || { echo "qargi: signing is not enabled for this project (set release.sign in the project answers)" >&2; exit 2; }
    python3 -I "$RS" config "$af" --need-sign || die "the answers of $PROJ do not hold a usable release.sign"
    sign_gate; [ -z "$SG_WHY" ] || die "$SG_WHY"
    # the passphrase is typed on the person's terminal, so a stdin that is no terminal (a pipe, a file, an agent's tool) is refused
    [ -t 0 ] || die "release sign needs a terminal on stdin: ssh-keygen asks for the key's passphrase there, and it must be you who types it. Run it in your own terminal"
    key=$(jq -r '.release.sign.key' "$af"); key=${key/#\~/$HOME}
    ns=$(jq -r '.release.sign.namespace' "$af")
    [ -f "$key" ] || die "release.sign.key: $key is not a file"
    mapfile -t rels < <(jq -r '.release.sign.files[]' "$af")
    mapfile -t sfiles < <(python3 -I "$RS" resolve "$REPO" "${rels[@]}") && [ "${#sfiles[@]}" = "${#rels[@]}" ] || die "a file of release.sign.files cannot be used"
    [ "${#sfiles[@]}" -gt 0 ] || die "release.sign.files names nothing to sign"
    rm -f "$SIGNREC"; mkdir -p "$DA_STATE/release"
    tc=$(g rev-parse "refs/tags/$VER^{commit}")
    echo "signing ${#sfiles[@]} file(s) of $PROJ $VER with $key (namespace $ns); ssh-keygen asks for the passphrase on this terminal"
    signrc=0
    for line in "${sfiles[@]}"; do
      IFS=$'\t' read -r _ abs rel <<<"$line"
      rm -f "$abs.sig"
      echo "  $rel"
      # stdin, stdout and stderr are this terminal's own; no ssh agent or askpass program may stand in for the person
      env -u SSH_AUTH_SOCK -u SSH_ASKPASS -u SSH_ASKPASS_REQUIRE ssh-keygen -Y sign -f "$key" -n "$ns" "$abs" || { signrc=$?; echo "qargi: signing $rel failed (ssh-keygen exit $signrc)" >&2; break; }
    done
    vrc=none
    if [ "$signrc" = 0 ] && jq -e '.release.sign.verify_command' "$af" >/dev/null 2>&1; then
      mapfile -d '' -t vcmd < <(jq -j '.release.sign.verify_command[] | ., "\u0000"' "$af")
      echo "verifying: ${vcmd[*]}"
      (cd "$REPO" && "${vcmd[@]}" </dev/null) && vrc=0 || vrc=$?
    fi
    res=$(python3 -I "$RS" record --state "$SIGNREC" --repo "$REPO" --af "$af" --project "$PROJ" --version "$VER" --commit "$tc" --sign-rc "$signrc" --verify-rc "$vrc") || true
    audit_log "release:sign" "$PROJ $VER ${res:-failed}"
    case ${res:-} in
      ok) echo "signed$([ "$vrc" = none ] && echo " (release.sign.verify_command is not set, so nothing verified it)" || echo " and verified"): $VER of $PROJ is recorded (${SIGNREC#"$DA_STATE/"})"
          echo "attach the .sig files with release.assets or --asset; then: qargi release publish $VER";;
      verify-failed) die "the signatures were made, but verify_command exited $vrc: the signature is not recorded as ok (fix it and sign again)";;
      *) die "signing failed: nothing is recorded as signed";;
    esac;;
  publish)
    tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || die "no tag $VER (qargi release finish $VER makes it)"
    python3 -I "$RS" config "$af" || die "the release answers of $PROJ are not valid (qargi project validate $PROJ)"
    notes=$(mktemp "$DA_STATE/.release-notes.XXXXXX")
    # the notes: --notes-file, else the answer release.notes_file, else the VER section of CHANGELOG.md at the tag
    nfile=$NOTES_OPT
    [ -n "$nfile" ] || { nfile=$(jq -r '.release.notes_file // ""' "$af"); nfile=${nfile//\{version\}/$VER}; }
    if [ -n "$nfile" ]; then
      out=$(python3 -I "$RS" resolve "$REPO" "$nfile") || die "the notes file cannot be used"
      IFS=$'\t' read -r _ nabs nrel <<<"$out"
      cp "$nabs" "$notes"
      grep -q '[^[:space:]]' "$notes" || die "the notes file $nrel is empty: nothing to publish"
      nsrc="the file $nrel"
    else
      g show "$tc:CHANGELOG.md" > "$notes" 2>/dev/null || die "the tagged commit of $VER has no CHANGELOG.md to take the notes from"
      sect=$(bash "$(dirname "$0")/changelog_section.sh" "$VER" "$notes" 2>/dev/null) || die "tag $VER: no changelog section for $VER in CHANGELOG.md at the tagged commit (it is missing or empty): nothing to publish"
      printf '%s\n' "$sect" > "$notes"
      nsrc="the $VER section of CHANGELOG.md at the tag"
    fi
    # the assets: release.assets and every --asset, each a regular file inside the repository; attached by the same gh release create
    mapfile -t alist < <(jq -r '(.release.assets // [])[]' "$af")
    alist+=("${ASSETS[@]}")
    assets=(); ahash=; arel=; declare -A seen
    if [ "${#alist[@]}" -gt 0 ]; then
      out=$(python3 -I "$RS" resolve "$REPO" "${alist[@]}") || die "an asset cannot be used; nothing was published"
      while IFS=$'\t' read -r h abs rel; do
        [ -z "${seen[$abs]:-}" ] || continue; seen[$abs]=1   # named twice (the answers and --asset)
        assets+=("$abs"); ahash+="$h $rel"$'\n'; arel+="$rel"$'\n'
      done <<<"$out"
    fi
    title="$PROJ $VER"
    gh_release_state "$VER"
    case $GHS in
      found) die "tag $VER already has a GitHub release: nothing to publish";;
      nogh) echo "note: gh is not installed, so whether GitHub has a release for tag $VER was not checked; applying needs it" >&2;;
      noauth) echo "note: gh is not authenticated, so whether GitHub has a release for tag $VER was not checked; applying needs it (gh auth login)" >&2;;
      unchecked) echo "note: could not ask GitHub whether tag $VER has a release (${GHWHY:-no answer})" >&2;;
    esac
    # when the project signs its releases, nothing is published before the signature of this tag is recorded ok and the signed files are as signed
    signline=''; stok=''
    if sign_configured; then
      signline=$(python3 -I "$RS" check --state "$SIGNREC" --repo "$REPO" --af "$af" --commit "$tc") \
        || die "awaiting signature: $signline. Sign $VER first (qargi release sign $VER, in your terminal); nothing was published"
      stok=$(sha256sum < "$SIGNREC")
    fi
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$VER" "$tc" "$(sha256sum < "$notes")" "$title" "$ahash" "$stok" | plan_token)
    echo "publish the GitHub release of tag $VER of $PROJ: tag at ${tc:0:7} ($(g log -1 --format=%s "$tc"))"
    echo "notes ($nsrc):"
    sed 's/^/  | /' "$notes"
    if [ "${#assets[@]}" -gt 0 ]; then
      echo "assets (${#assets[@]}), attached by the same gh release create:"
      sed 's/^\([0-9a-f]*\) /  | \1  /' <<<"${ahash%$'\n'}"
    fi
    if [ -n "$signline" ]; then
      echo "signature: $signline"
      while IFS= read -r f; do
        grep -qxF -- "$f.sig" <<<"$arel" || echo "note: $f.sig is not among the assets: attach it with --asset $f.sig or release.assets"
      done < <(jq -r '.files | keys[]' "$SIGNREC")
    fi
    echo "run: $GH -R $(repo_slug) release create $VER --verify-tag --title \"$title\" --notes-file NOTES$([ "${#assets[@]}" -eq 0 ] || printf ' %s' "${assets[@]}")"
    echo "(--verify-tag: the tag must already be on origin; NOTES holds the text above)"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi release publish $VER --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    case $GHS in
      missing) ;;
      nogh) die "gh is not installed: create the release by hand, or run the release workflow by hand with this tag";;
      noauth) die "gh is not authenticated (gh auth login); nothing was published";;
      *) die "could not ask GitHub whether tag $VER has a release (${GHWHY:-no answer}); nothing was published";;
    esac
    out=$("$GH" -R "$(repo_slug)" release create "$VER" --verify-tag --title "$title" --notes-file "$notes" "${assets[@]}" 2>&1 </dev/null) || die "gh release create failed for tag $VER: $out"
    audit_log "release:publish" "$PROJ $VER${assets[0]:+ (${#assets[@]} asset(s))}"
    echo "published the release of tag $VER: $out";;
  *) die "usage: qargi release start|status|verify|push|finish|sign|publish VERSION [--hotfix] [--project P]";;
esac
