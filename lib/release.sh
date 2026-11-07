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
#                                           A release (not a hotfix) then lists the features merged into develop since the previous tag.
#   release.sh status VERSION [--hotfix]    the full-suite verdict names the command that produced it, when it ran, how long it took and its mode (-j N, shard I/K) (the suite record); a
#                                           release.test_command that is not that command gets a line of its own: the pass is not the release gate.
#                                           For an existing tag also warns: no GitHub release for it (gh release view, through
#                                           QARGI_GH), or its commit lacks .github/workflows/release.yml while the branch has it;
#                                           with release.sign set and no release yet it says "awaiting signature" until `sign` recorded
#                                           one that still holds, and "VERSION is ready for signing" when the repository is in the state sign needs
#                                           With a branch: the pull request's checks (gh pr checks: name and pass/fail/pending). With a tag: the
#                                           checklist after the release: tag on origin, GitHub release, the assets of release.assets, the signatures of
#                                           release.sign.files, and the project's release.after_steps (an optional list of words; not tracked).
#   release.sh verify VERSION [--hotfix]    run the whole suite on the branch head (develop's head before a release starts); same warnings
#                                           With the answer release.version_files (a list of paths) start, status and verify check that each file contains
#                                           VERSION at the release branch and warn of the ones that do not: "bump these on the release branch". No answer, no check.
#   release.sh fix VERSION [--hotfix] [--push [--plan T --approved W]]
#                                           a worktree on the release branch under the worktree root (prints its path), to commit a fix in; --push is `push`
#   release.sh push VERSION [--hotfix] [--plan T --approved W]     push the branch, open the pull request into master (or say "updated PR #N" when it is open)
#                                           When master and the branch have no merge base (master is one snapshot commit, say) the plan has the line "join the history
#                                           of master": once approved, master is merged into the branch with -s ours --allow-unrelated-histories, in a temporary
#                                           worktree, as a commit of its own before the push, and only if the tree is unchanged; `start`, `status` and `finish` say so.
#   release.sh finish VERSION [--hotfix] [--keep] [--ignore-checks WORDS] [--plan T --approved W]
#                                           after the checks pass: merge, tag, back-merge, delete the branch, push. The plan lists the pull request's checks
#                                           and refuses while one fails or is pending, unless --ignore-checks gives, in the person's words, why (recorded).
#                                           Then it prints the steps of the answer release.after_steps ({version} replaced) as "after the release: STEP"
#                                           lines, never runs them, and records them in STATE/release/PROJECT-VERSION.after.json ({steps: [...]}) for
#                                           `status`, which shows the recorded steps (the answer as it is now when there is no record).
#
#   release.sh assets VERSION [--recreate]  build the release files of the tag VERSION: a clean detached worktree of the tag under STATE/release-assets/,
#                                           the project's answer release.assets_command run in it (a command line, or a list of words with {version}
#                                           replaced; QARGI_RELEASE_VERSION is set; refused with a message when unset), the worktree recorded under
#                                           STATE/release/ so that `sign` and `publish` take the files from it. Prints where the files are and the next
#                                           command (`qargi release sign VERSION` when release.sign is set). An existing asset worktree is kept unless
#                                           --recreate. Lead only (refused in a member run and when QARGI_NESTED is set); no plan token: it runs the
#                                           command the lead put in the answers, on the tag, and changes no branch.
#   release.sh sign VERSION                 sign the files of the answer release.sign.files (ssh-keygen -Y sign -f KEY -n NAMESPACE FILE, one by one),
#                                           run release.sign.verify_command and record the result under STATE/release/. Only from the tag, because the
#                                           release files are built from the tagged commit: after `finish`, before `publish`. The repository's HEAD
#                                           must be the commit of the tag VERSION, on master or detached, with no tracked file modified (when `assets`
#                                           built the files, the files are those of its worktree, which must be at the tag instead). ssh-keygen
#                                           runs on the person's own terminal (stdin, stdout and stderr are inherited; nothing is captured and no
#                                           input is logged), so the passphrase is typed there and never passes through qargi; no ssh agent is
#                                           asked (SSH_AUTH_SOCK and SSH_ASKPASS are removed from its environment). Refused when stdin is no
#                                           terminal, in a member run, when QARGI_NESTED is set and when the project has no release.sign (signing is
#                                           optional and off by default; exit 2); the guard refuses it to a member too.
#                                           The verify command is an argv list, run without a shell in the repository.
#
#   release.sh publish VERSION [--plan T --approved W] [--asset FILE]... [--asset-dir DIR]... [--notes-file FILE]
#                                           create the GitHub release of the tag VERSION (gh release create --verify-tag, through
#                                           QARGI_GH) with the tag's changelog section as notes; for a tag pushed before the release
#                                           workflow existed. Refuses when the release exists, the tag is missing or the section is empty.
#                                           The files of --asset, of every regular file of --asset-dir and of the answer release.assets (names or globs,
#                                           {version} replaced) are attached by the same gh release create. A relative name is taken in the asset worktree
#                                           of `assets` when there is one, else in the repository; a full path must lie in a worktree of the repository. The notes are --notes-file, else the answer
#                                           release.notes_file ({version} replaced), else the changelog section. When release.sign is
#                                           set it refuses until `sign` recorded an ok for VERSION and no signed file changed since; the
#                                           plan token covers the notes and the hash of every asset.
#
#   release.sh site VERSION [--plan T --approved W]
#                                           build the documentation site of the tag VERSION and commit it on the detached site branch (answers site.branch,
#                                           default gh-pages when repo.detached lists it, and site.config, default site/site.json, whose folder pages/ holds
#                                           the hand pages). Only when site.enabled is true. The source is the tag's tree (git archive), the generator is
#                                           lib/site.py; the work is done in a temporary worktree of the site branch, which moves by update-ref only after
#                                           the commit, so no working tree is touched. The commit sets "release" in the site.json; the build checks the site and its output (_site/) is not committed, a Pages build of the branch needing _site/ empty.
#                                           It never pushes: it prints the push command. Refused in a member run and when QARGI_NESTED is set.
#                                           `finish` ends with "next: qargi release site VERSION" (the methodology's after_release step) and `status`
#                                           says whether the site of VERSION is built and pushed, both only when site.enabled is true.
#
# The layout of what a release updates is the project's: the answers release.version_file (default VERSION; none: the project has no such file),
# release.changelog.unreleased and .released (heading templates; default '## [Unreleased]' and '## [{version}] - {date}'), release.man_pages (default
# man/*.1), release.version_files (other files that carry the version; checked, never bumped), release.test_command (what `verify` runs; default test_command) and release.preflight (an argv list, {version} replaced, run by `start` and
# `push` before they change anything; a non-zero exit refuses). lib/release_layout.py checks and applies them.
#
# Options for all: --project P, --date D. Pushing, merging and tagging need the plan token and an approval.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
VER='' PROJ='' DATE='' PLAN_ARG='' APPROVED='' HOTFIX='' KEEP='' RESOLVED='' ALLOW_EMPTY='' NOTES_OPT='' FIXPUSH='' IGNORE_CHECKS='' IGNORE_SET='' IGNORED='' RECREATE=''; ASSETS=() ASSET_DIRS=()
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --date) need_val "$1" $#; DATE=$2; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;;
    --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --asset) need_val "$1" $#; ASSETS+=("$2"); shift 2;; --asset-dir) need_val "$1" $#; ASSET_DIRS+=("$2"); shift 2;; --recreate) RECREATE=1; shift;; --notes-file) need_val "$1" $#; NOTES_OPT=$2; shift 2;;
    --push) FIXPUSH=1; shift;; --ignore-checks) need_val "$1" $#; IGNORE_CHECKS=$2; IGNORE_SET=1; shift 2;;
    --hotfix) HOTFIX=1; shift;; --keep) KEEP=1; shift;; --resolved) RESOLVED=1; shift;; --allow-empty-notes) ALLOW_EMPTY=1; shift;;
    -*) die "unknown option $1";; *) VER=$1; shift;;
  esac
done
[ "$verb" = publish ] || { [ ${#ASSETS[@]} -eq 0 ] && [ ${#ASSET_DIRS[@]} -eq 0 ] && [ -z "$NOTES_OPT" ]; } || die "--asset, --asset-dir and --notes-file belong to release publish"
[ "$verb" = assets ] || [ -z "$RECREATE" ] || die "--recreate belongs to release assets"
[ "$verb" = fix ] || [ -z "$FIXPUSH" ] || die "--push belongs to release fix"
[ "$verb" = finish ] || [ -z "$IGNORE_SET" ] || die "--ignore-checks belongs to release finish"
[ -z "$IGNORE_SET" ] || printf '%s' "$IGNORE_CHECKS" | grep -q '[^[:space:]]' || die "--ignore-checks needs the reason, in the words you gave: --ignore-checks \"...\""
[ "$verb" != fix ] || [ -z "$FIXPUSH" ] || verb=push   # fix --push is push
export PLAN_ARG RESOLVED   # need_plan reads PLAN_ARG; merge_step reads RESOLVED

[ -n "$VER" ] || die "usage: qargi release start|status|verify|fix|push|finish|assets|sign|publish|site VERSION [--hotfix] [--project P]"
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
RL=$(dirname "$0")/release_layout.py
# the layout answers (see the head of this file): the version file, the manual pages, the test command of `verify`
VFILE=$(jq -r '(.release? // {}) | .version_file // "VERSION"' "$af"); VFILE_SET=$(jq -r '(.release? // {}) | has("version_file")' "$af")
RTC=$(jq -r '(.release? // {}) | .test_command // empty | if type == "array" then map(@sh) | join(" ") else . end' "$af"); [ -z "$RTC" ] || TESTCMD=$RTC
GH=${QARGI_GH:-gh}   # the one way this script talks to GitHub; tests put a stub here
repo_slug() { jq -r '.repo.url' "$af" | sed 's|^https://[^/]*/||; s|\.git$||'; }
notes='' SITESRC=''   # the temporary file of `publish`, the extracted tag of `site`
rel_exit() { [ -z "$notes" ] || rm -f "$notes"; [ -z "$SITESRC" ] || rm -rf "$SITESRC"; on_exit; }   # the one EXIT handler: what gitflow.sh cleans up, and the temporary files
trap rel_exit EXIT
# gh_release_state TAG -> sets GHS to found|missing|noauth|nogh|unchecked (and GHWHY): does GitHub have a release for the tag? Read-only.
gh_release_state() {
  local out rc=0
  GHWHY='' GHS_FOR=$1
  command -v "$GH" >/dev/null 2>&1 || { GHS=nogh; return 0; }
  out=$("$GH" -R "$(repo_slug)" release view "$1" 2>&1 </dev/null) || rc=$?
  if [ "$rc" = 0 ]; then GHS=found
  elif grep -qi 'auth login\|not logged in\|authentication' <<<"$out"; then GHS=noauth
  elif grep -qi 'release not found' <<<"$out"; then GHS=missing
  else GHS=unchecked; GHWHY=$(printf '%s' "$out" | grep -v '^[[:space:]]*$' | head -1 | cut -c1-120); fi
  return 0
}
# version_files_report REF: the answer release.version_files (other files that carry the version), checked at REF: each must contain VER as a whole
# version (release_layout.py has-version, the file on stdin). Prints nothing when the answer is not set (no answer, no check); otherwise one line, a
# warning naming the files that lack VER (a missing file lacks it too) and the fix, or that all carry it. Never a failure: `start` cannot refuse,
# because the files are bumped on the release branch it creates.
version_files_report() {
  local ref=$1 f bad='' n=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    n=$((n + 1))
    if g show "$ref:$f" 2>/dev/null | python3 -I "$RL" has-version - "$VER"; then :; else bad+="${bad:+, }$f"; fi
  done < <(jq -r '(.release? // {}).version_files // [] | .[]' "$af")
  [ "$n" -gt 0 ] || return 0
  if [ -n "$bad" ]; then echo "warning: release.version_files: $bad on $ref do not contain $VER: bump these on the release branch (qargi release fix $VER${HOTFIX:+ --hotfix} makes a worktree for it)"
  else echo "version files (release.version_files): all $n contain $VER"; fi
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
# The history of master. A master that shares no history with the release branch (for example one parentless snapshot commit) cannot be merged:
# git refuses "unrelated histories". `push` joins them first, in its plan: master is merged into the release branch keeping the release's tree,
# so the later `finish` is an ordinary --no-ff merge. unrelated_note says so in `start` and `status`; join_history does it.
unrelated_note() { echo "master and $BR share no history (no merge base; master may be one snapshot commit): qargi release push $VER${HOTFIX:+ --hotfix} joins the history of master first (a merge of master that keeps the release tree, in its plan), before CI runs, so that finish is an ordinary --no-ff merge"; }
# join_history SHA MASTER_SHA -> JOINED: a merge commit of master into the branch BR at SHA, made in a temporary worktree with -s ours
# --allow-unrelated-histories, and BR moved to it only when its tree is the tree of SHA and its parents are SHA and master. Otherwise nothing moved.
# MASTER_SHA is the master the plan showed (and its token covers): the join is refused when master is anywhere else now. The merge is mechanical: the
# lead's hooks do not run on it (core.hooksPath=/dev/null) and it is never signed (no passphrase prompt), as review apply makes its commits.
join_history() {
  local old=$1 m=$2 t0 t1 out
  [ -n "$m" ] && [ "$(sha_of master)" = "$m" ] || die "master is not at ${m:0:7}, where the plan showed it (it is at $(sha_of master | cut -c1-7)): nothing was changed; make the plan again (qargi release push $VER${HOTFIX:+ --hotfix})"
  t0=$(g rev-parse "$old^{tree}")
  worktree "$old"
  out=$(git -C "$WT" -c core.hooksPath=/dev/null merge -q --no-ff --no-gpg-sign -s ours --allow-unrelated-histories -m "Join the history of master" -m "master and $BR had no merge base. This merge keeps the tree of $BR as it was (-s ours), so the release changes nothing; it only makes the later merge into master an ordinary --no-ff merge." "$m" 2>&1) \
    || { cleanup; die "joining the history of master failed: $out"$'\n'"nothing was changed"; }
  JOINED=$(git -C "$WT" rev-parse HEAD); t1=$(git -C "$WT" rev-parse 'HEAD^{tree}')
  if [ "$t0" != "$t1" ] || [ "$(git -C "$WT" rev-parse 'HEAD^1')" != "$old" ] || [ "$(git -C "$WT" rev-parse 'HEAD^2')" != "$m" ]; then
    cleanup; die "the join with master would change the tree of $BR (${t0:0:7} before, ${t1:0:7} after) or is not a merge of $BR and master: refused, nothing was changed"
  fi
  cleanup
  g update-ref "refs/heads/$BR" "$JOINED" "$old" || die "could not move $BR to the join commit (it moved meanwhile?); nothing was pushed"
  journal_ref "$REPO" "refs/heads/$BR" "$old" "$JOINED" "$KIND:join"
  wt_follow "$BR" "$JOINED"
}
# join_blocker BRANCH -> prints why the join would be refused for a checked-out BRANCH (nothing when it will not): need_free_wt lets only a clean worktree
# under qargi's worktree root hold it
join_blocker() {
  local h w
  h=$(held "$1"); [ -n "$h" ] || return 0
  w=$(wt_of "$1")
  if [ -z "$w" ]; then echo "$1 is checked out in $h, which is not a worktree qargi made under its root: the join will be refused until it is checked out elsewhere (leave the branch there, or remove that worktree)"; return 0; fi
  [ -z "$(git -C "$w" status --porcelain 2>/dev/null)" ] || echo "$1 is checked out in $w, which has uncommitted changes: the join will be refused until they are committed or discarded"
}
open_release() { g for-each-ref --format='%(refname:short)' "refs/heads/${RELPREFIX}*"; }   # the open release branches
# suite_verdict BRANCH -> SV_TEXT, the last whole-suite run recorded for the branch ("pass at this head (command: C; ran AT)"; empty when none was
# recorded), and SV_NOTE, set when release.test_command is set and is not the command of that run: the run is then not the release gate.
suite_verdict() {
  local f cur res at cmd took mode
  SV_TEXT='' SV_NOTE=''
  f=$(rec "$1"); [ -f "$f" ] || return 0
  cur=$(jq -r '.sha // empty' "$f" 2>/dev/null) || return 0; [ -n "$cur" ] || return 0
  res=$(jq -r '.result // "?"' "$f"); at=$(jq -r '.at // "an unknown time"' "$f"); cmd=$(jq -r '.command // "an unknown command"' "$f")
  took=$(jq -r 'if (.seconds | type) == "number" then "took \(.seconds)s" else empty end' "$f"); mode=$(jq -r '.mode // empty' "$f")
  SV_TEXT="$res at $([ "$cur" = "$(sha_of "$1")" ] && echo 'this head' || echo 'an older head') (command: $cmd; ran $at${took:+; $took}${mode:+; $mode})"
  if [ -n "$RTC" ] && [ "$RTC" != "$cmd" ]; then
    SV_NOTE="  note: release.test_command is \"$RTC\", not the command of that run: it is not the release gate (qargi release verify $VER runs it)"
  elif [ -n "$TESTCMD" ] && [ "$TESTCMD" != "$cmd" ]; then
    SV_NOTE="  note: the test command is now \"$TESTCMD\", not the command of that run: a release does not start from it (qargi release verify $VER runs the current one)"
  fi
}

# The signing of a release (lib/release_sign.py holds the answers' checks and the record). The record of VER is a file under STATE/release/.
RS=$(dirname "$0")/release_sign.py
SIGNREC=$DA_STATE/release/$PROJ-$VER.sign.json
sign_configured() { jq -e '(.release // {}) | has("sign")' "$af" >/dev/null 2>&1; }
# The release asset worktree: `assets` builds the release files in a clean detached worktree of the tag, under the state directory, and records it
# in ASSETREC. While it is there at the tag, `sign` and `publish` take the files from it (relative names) instead of the repository.
ASSETREC=$DA_STATE/release/$PROJ-$VER.assets.json
ASSETWT=$DA_STATE/release-assets/$PROJ-$VER
# asset_wt: sets AWT to the recorded asset worktree of VER when it exists and is still at the tag (a note on stderr when the record is stale); else ''
asset_wt() {
  local p tc
  AWT=''
  [ -f "$ASSETREC" ] || return 0
  p=$(jq -r '.worktree // empty' "$ASSETREC" 2>/dev/null); tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || return 0
  if [ -n "$p" ] && [ -d "$p" ] && [ "$(git -C "$p" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null)" = "$tc" ]; then AWT=$p
  else echo "note: the release asset worktree of $VER (${p:-none}) is gone or no longer at the tag: ignored (qargi release assets $VER --recreate makes it again)" >&2; fi
}
# sign_root: the directory the release files are signed and published from: the asset worktree when there is one, else the repository
sign_root() { asset_wt; printf '%s' "${AWT:-$REPO}"; }
# after_steps_record: the answer release.after_steps ({version} replaced) as "after the release: STEP" lines, kept in AFTERREC (one JSON file under
# the state, {steps: [...]}) for `release status`. They are shown, never run. after_steps_list gives them back to `status`.
AFTERREC=$DA_STATE/release/$PROJ-$VER.after.json
after_steps_record() {
  local st=()
  mapfile -t st < <(python3 -I "$RS" after-steps "$af" "$VER" 2>/dev/null)
  [ "${#st[@]}" -gt 0 ] || return 0
  mkdir -p "$DA_STATE/release"
  printf '%s\n' "${st[@]}" | jq -R . | jq -s --arg p "$PROJ" --arg v "$VER" --arg t "$(now)" '{schema:1, project:$p, version:$v, at:$t, steps:.}' > "$AFTERREC"
  printf 'after the release: %s\n' "${st[@]}"
}
# after_steps_list: the steps for `release status`, one per line: those `finish` recorded in AFTERREC; when there is no (readable) record, the answer as it is now
after_steps_list() {
  local s
  if [ -f "$AFTERREC" ] && s=$(jq -r '.steps[] | strings' "$AFTERREC" 2>/dev/null) && [ -n "$s" ]; then printf '%s\n' "$s"; return 0; fi
  s=$(jq -r '(.release? // {}) | (.after_steps // []) | if type == "array" then .[] | strings else empty end' "$af" 2>/dev/null) || return 0
  [ -z "$s" ] || printf '%s\n' "${s//\{version\}/$VER}"
}
# sign_status: for a tag that exists in a project that signs its releases (and has no GitHub release yet), whether the signature of VER is recorded
# and still true; if not, "awaiting signature" and either that the release is ready for signing or what stands in the way. Read-only.
sign_status() {
  local tc s
  sign_configured || return 0
  tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || return 0
  [ "${GHS:-}" != found ] || return 0
  python3 -I "$RS" config "$af" >/dev/null 2>&1 || { echo "warning: the release answers of $PROJ are not valid (qargi project validate $PROJ), so the signature of $VER was not checked"; return 0; }
  if s=$(python3 -I "$RS" check --state "$SIGNREC" --repo "$(sign_root)" --af "$af" --commit "$tc"); then echo "signature: $s"; return 0; fi
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
  asset_wt
  if [ -n "$AWT" ]; then   # the release files were built in the asset worktree of the tag (qargi release assets): the repository's own checkout is not involved
    if [ -n "$(git -C "$AWT" status --porcelain --untracked-files=no)" ]; then SG_WHY="tracked files of the asset worktree $AWT are modified: the release files must be built from the tag as it is"; return 0; fi
    while IFS= read -r f; do
      [ -f "$AWT/$f" ] || { SG_WHY="the file $f of release.sign.files does not exist in the asset worktree $AWT: qargi release assets $VER builds the release files"; return 0; }
    done < <(jq -r '.release.sign.files[]' "$af")
    return 0
  fi
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

# The documentation site of a release (lib/release_site.py holds the answers' checks; lib/site.py is the generator)
RSITE=$(dirname "$0")/release_site.py
SITE_SUBJECT="Site: built from release"   # the subject of the commit `site` makes, followed by the version: `status` finds it by it
# site_answers -> SITE_ON (true|false), SITE_BR, SITE_CONF, SITE_PAGES; fails when the site answers are not valid
site_answers() {
  local line
  line=$(python3 -I "$RSITE" config "$af") || return 1
  IFS=$'\t' read -r SITE_ON SITE_BR SITE_CONF SITE_PAGES <<<"$line"
}
# site_status: when site.enabled is true, one line saying whether the site of VER is built on the site branch and whether origin has it. Read-only.
site_status() {
  local c why=''
  site_answers 2>/dev/null && [ "$SITE_ON" = true ] || return 0
  branch_exists "$SITE_BR" || { echo "site: not built for $VER (no local branch $SITE_BR)"; return 0; }
  c=$(g log -1 --format=%H --grep="^$SITE_SUBJECT ${VER//./\\.}\$" "refs/heads/$SITE_BR" --)
  [ -n "$c" ] || { echo "site: not built for $VER"; return 0; }
  remote_tip "$SITE_BR"
  case $RSTATE in
    found)
      if [ "$RTIP" = "$c" ] || { g cat-file -e "$RTIP^{commit}" 2>/dev/null && g merge-base --is-ancestor "$c" "$RTIP"; }; then echo "site: pushed"; return 0; fi
      g cat-file -e "$RTIP^{commit}" 2>/dev/null || why=" (origin $SITE_BR is at ${RTIP:0:7}, which is not fetched)";;
    unchecked)
      if g rev-parse -q --verify "refs/remotes/origin/$SITE_BR" >/dev/null && g merge-base --is-ancestor "$c" "refs/remotes/origin/$SITE_BR"; then
        echo "site: pushed (as of the last fetch; origin not checked: $RWHY)"; return 0
      fi
      why=" (origin not checked: $RWHY)";;
    none) why=" (no origin remote)";;
  esac
  echo "site: built at ${c:0:7}, not pushed$why"
}
# after_release: the methodology's steps after a release (methodology.json after_release) whose answer is true, as "next: ..." lines
after_release() { python3 -I "$RSITE" next "$af" "$METH" "$VER" 2>/dev/null || true; }

# rel_valid: the release answers of the project must be valid before a verb relies on them
rel_valid() { python3 -I "$RS" config "$af" || die "the release answers of $PROJ are not valid (qargi project validate $PROJ)"; }
# man_pages_at REF: the manual pages a release dates, one per line: release.man_pages, else the man/*.1 files tracked at REF
man_pages_at() {
  if jq -e '(.release? // {}) | has("man_pages")' "$af" >/dev/null 2>&1; then jq -r '.release.man_pages[]' "$af"
  else g ls-tree -r --name-only "$1" | grep -E '(^|/)man[0-9]?/[^/]+\.[1-9]$' || true; fi
}
# run_preflight DIR: release.preflight (an argv list, {version} replaced) runs in DIR, with no shell and no input; a non-zero exit ends the verb
# with the tail of its output. It runs before the verb changes anything.
run_preflight() {
  local pre=() out rc=0
  mapfile -d '' -t pre < <(jq -j --arg v "$VER" '(.release? // {}) | (.preflight // [])[] | split("{version}") | join($v), "\u0000"' "$af")
  [ "${#pre[@]}" -gt 0 ] || return 0
  out=$(run_clean "$1" "${pre[@]}" </dev/null 2>&1) || rc=$?
  [ "$rc" = 0 ] || die "release.preflight failed (exit $rc): ${pre[*]}"$'\n'"$(printf '%s\n' "$out" | tail -n 15 | sed 's/^/  | /')"$'\n'"nothing was changed"
}

# --- the pull request and its CI checks (read-only calls through $GH)
# pr_checks BRANCH -> PRC_STATE (pass|failing|pending|nopr|nochecks|noauth|nogh|unchecked), PRC_LINES ("name: pass|fail|pending|skipped" per check),
# the counts PRC_PASS, PRC_FAIL, PRC_PEND and PRC_WHY. `pr checks` prints one tab-separated line per check (name, state, elapsed, url) when it is
# not on a terminal, and exits 0 when all passed, 8 while some are pending, 1 otherwise. Never fails.
pr_checks() {
  local out rc=0 line name state st
  PRC_STATE='' PRC_LINES='' PRC_WHY='' PRC_PASS=0 PRC_FAIL=0 PRC_PEND=0
  command -v "$GH" >/dev/null 2>&1 || { PRC_STATE=nogh; return 0; }
  out=$("$GH" -R "$(repo_slug)" pr checks "$1" 2>&1 </dev/null) || rc=$?
  while IFS= read -r line; do
    [[ $line == *$'\t'* ]] || continue
    IFS=$'\t' read -r name state _ <<<"$line"
    case $state in
      pass) st=pass; PRC_PASS=$((PRC_PASS + 1));;
      fail|failure|cancel|cancelled|error|timed_out) st=fail; PRC_FAIL=$((PRC_FAIL + 1));;
      pending|queued|in_progress|waiting) st=pending; PRC_PEND=$((PRC_PEND + 1));;
      skipping|skipped|neutral) st=skipped;;
      *) st=${state:-unknown};;
    esac
    PRC_LINES+="$name: $st"$'\n'
  done <<<"$out"
  PRC_LINES=${PRC_LINES%$'\n'}
  if [ "$rc" = 0 ]; then PRC_STATE=pass
  elif [ "$PRC_FAIL" -gt 0 ]; then PRC_STATE=failing
  elif [ "$PRC_PEND" -gt 0 ] || [ "$rc" = 8 ]; then PRC_STATE=pending
  elif grep -qi 'no pull requests found' <<<"$out"; then PRC_STATE=nopr
  elif grep -qi 'no checks reported' <<<"$out"; then PRC_STATE=nochecks
  elif grep -qi 'auth login\|not logged in\|authentication' <<<"$out"; then PRC_STATE=noauth
  else PRC_STATE=unchecked; PRC_WHY=$(printf '%s' "$out" | grep -v '^[[:space:]]*$' | head -1 | cut -c1-120); fi
  return 0
}
# pr_checks_print BRANCH: pr_checks, then the verdict and one line per check; what could not be read is a warning, never a refusal
pr_checks_print() {
  local l
  pr_checks "$1"
  case $PRC_STATE in
    pass) echo "pull request checks of $1: all passed${PRC_LINES:+ ($PRC_PASS passed)}";;
    failing) echo "pull request checks of $1: $PRC_FAIL failing, $PRC_PEND pending, $PRC_PASS passed";;
    pending) echo "pull request checks of $1: $PRC_PEND pending, $PRC_PASS passed";;
    nopr) echo "warning: no pull request for $1, so no CI ran on it (qargi release push $VER${HOTFIX:+ --hotfix})";;
    nochecks) echo "warning: the pull request of $1 reports no checks";;
    nogh) echo "warning: gh is not installed, so the pull request checks of $1 were not read";;
    noauth) echo "warning: gh is not authenticated, so the pull request checks of $1 were not read (gh auth login)";;
    *) echo "warning: could not read the pull request checks of $1 (${PRC_WHY:-no answer})";;
  esac
  [ -z "$PRC_LINES" ] || while IFS= read -r l; do echo "  check $l"; done <<<"$PRC_LINES"
}
# pr_find BRANCH -> PR_NUM and PR_URL of the open pull request whose head is BRANCH (empty: none, or it could not be asked). Read-only.
pr_find() {
  local out
  PR_NUM='' PR_URL=''
  command -v "$GH" >/dev/null 2>&1 || return 0
  out=$("$GH" -R "$(repo_slug)" pr list --head "$1" --state open --json number,url --jq '.[] | "\(.number) \(.url)"' 2>/dev/null </dev/null | head -1) || return 0
  read -r PR_NUM PR_URL <<<"$out"
  case $PR_NUM in ''|*[!0-9]*) PR_NUM='' PR_URL='';; esac
  return 0
}
# remote_tag_state TAG -> RTAG (pushed|absent|none|unchecked): does the live origin have the tag? Bounded like remote_tip. Never fails.
remote_tag_state() {
  local out rc=0
  RTAG=unchecked
  g remote get-url origin >/dev/null 2>&1 || { RTAG=none; return 0; }
  command -v timeout >/dev/null 2>&1 || return 0
  out=$(GIT_TERMINAL_PROMPT=0 timeout "${QARGI_REMOTE_TIMEOUT:-10}" git -C "$REPO" ls-remote --tags origin "refs/tags/$1" 2>&1) || rc=$?
  [ "$rc" = 0 ] || return 0
  if [ -n "$out" ]; then RTAG=pushed; else RTAG=absent; fi
}
# post_release: for a tag VER that exists, the checklist of what is left after `finish`: the tag on origin, the GitHub release, the assets the
# project records (release.assets; the signatures of release.sign.files) and the project's own after-steps (release.after_steps, a list of
# words; qargi does not record that they were done). Read-only; what cannot be asked is said, not guessed.
post_release() {
  local tc a base names='' step n=0
  tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || return 0
  echo "after the release $VER (tag at ${tc:0:7}):"
  remote_tag_state "$VER"
  case $RTAG in
    pushed) echo "  tag $VER: pushed to origin";;
    absent) echo "  tag $VER: NOT on origin (git -C $REPO push origin $VER)";;
    none) echo "  tag $VER: no origin remote";;
    *) echo "  tag $VER: origin not checked";;
  esac
  if g remote get-url origin >/dev/null 2>&1; then
    [ "${GHS_FOR:-}" = "$VER" ] || gh_release_state "$VER"   # tag_checks asked already
    case $GHS in
      found) echo "  GitHub release: published";;
      missing) echo "  GitHub release: MISSING (qargi release publish $VER)";;
      nogh) echo "  GitHub release: not checked (gh is not installed)";;
      noauth) echo "  GitHub release: not checked (gh is not authenticated)";;
      *) echo "  GitHub release: not checked (${GHWHY:-no answer})";;
    esac
    if [ "$GHS" = found ]; then
      names=$("$GH" -R "$(repo_slug)" release view "$VER" --json assets --jq '.assets[].name' 2>/dev/null </dev/null) || names='?'
      if [ "$names" = '?' ]; then echo "  assets: not checked (the asset list could not be read)"
      else
        # release.assets entries: {version} replaced, a glob matched by its base name against the names the release has
        python3 -I "$RS" asset-status "$af" "$VER" <<<"$names" 2>/dev/null | sed 's/^/  /' || true
        if sign_configured; then
          while IFS= read -r a; do
            [ -n "$a" ] || continue
            base=${a##*/}
            if grep -qxF -- "$base.sig" <<<"$names"; then echo "  signature $base.sig: attached"; else echo "  signature $base.sig: UNSIGNED, not attached to the release"; fi
          done < <(jq -r '(.release.sign.files // [])[]' "$af" 2>/dev/null)
        fi
      fi
    fi
  fi
  while IFS= read -r step; do
    [ -n "$step" ] || continue
    [ "$n" -gt 0 ] || echo "  after-steps (release.after_steps; qargi does not record that they were done):"
    n=$((n + 1)); echo "    - $step"
  done < <(after_steps_list)
  return 0
}

case $verb in
  start)
    rel_valid
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
    run_preflight "$WT"
    oldver=''
    if [ "$VFILE" != none ]; then
      if [ -f "$WT/$VFILE" ]; then oldver=$(tr -d '[:space:]' < "$WT/$VFILE"); echo "$VER" > "$WT/$VFILE"; git -C "$WT" add -- "$VFILE"
      elif [ "$VFILE_SET" = true ]; then die "release.version_file: $VFILE is not a file at the head of $BASE (set it to none when the project has no version file)"; fi
    fi
    while IFS= read -r mp; do
      [ -n "$mp" ] || continue
      [ -f "$WT/$mp" ] || die "release.man_pages: $mp is not a file at the head of $BASE"
      python3 -I "$RL" manpage "$WT/$mp" "$mp" "$VER" "$DATE" "$oldver" || exit 1
      git -C "$WT" add "$mp"
    done < <(man_pages_at "$b0")
    if [ -f "$WT/CHANGELOG.md" ]; then
      python3 -I "$RL" changelog "$WT/CHANGELOG.md" "$VER" "$DATE" "$ALLOW_EMPTY" "$af" || exit 1
      git -C "$WT" add CHANGELOG.md
    fi
    wcommit --allow-empty -m "Bumped version number to $VER"
    g update-ref "refs/heads/$BR" "$(git -C "$WT" rev-parse HEAD)" "" || die "could not create $BR"
    journal_ref "$REPO" "refs/heads/$BR" "" "$(sha_of "$BR")" "$KIND:start"
    echo "created $BR from $BASE ($(g rev-parse --short "$BR")): the version is $VER and the changelog (and a man page) is dated $DATE"
    if [ "$KIND" = release ]; then   # what the release contains: the features merged into develop since the previous tag (--no-ff merges "Merge branch 'feature/...'")
      prev=$(g describe --tags --abbrev=0 --match '[0-9]*' "$b0" 2>/dev/null || true)
      feats=$(g log --first-parent --merges --format='%h %s' "${prev:+$prev..}$b0" | sed -n "s/^\([0-9a-f]*\) Merge branch '\(feature\/[^']*\)'.*/  \1 \2/p")
      if [ -n "$feats" ]; then echo "features merged into develop since ${prev:-the first commit} ($(printf '%s\n' "$feats" | wc -l)):"; printf '%s\n' "$feats"
      else echo "no feature was merged into develop since ${prev:-the first commit}"; fi
    fi
    if branch_exists master && no_merge_base master "$BR"; then echo "note: $(unrelated_note)"; fi
    if jq -e '(.release? // {}) | (.version_files // []) | length > 0' "$af" >/dev/null 2>&1; then version_files_report "$BR"
    else echo "other files that carry the version (a manifest) are yours to bump on this branch"; fi
    echo "only minor fixes belong here; new features wait for the next release. Then: qargi release push $VER${HOTFIX:+ --hotfix}";;
  status)
    h=$(sha_of "$BR")
    if [ -z "$h" ]; then
      suite_verdict "$BASE"
      echo "no $BR yet. develop is at $(g rev-parse --short develop 2>/dev/null || echo '?'), full suite: ${SV_TEXT:-not run}"
      [ -z "$SV_NOTE" ] || echo "$SV_NOTE"
      remote_report "$BASE"
      tag_checks
      sign_status
      site_status
      post_release
      exit 0
    fi
    echo "$KIND $VER of $PROJ on $BR at $(g rev-parse --short "$BR"), $(g rev-list --count "$BASE..$BR") commit(s) ahead of $BASE"
    g log --format='  %h %s' "$BASE..$BR" | head -20
    if branch_exists master && no_merge_base master "$BR"; then echo "warning: $(unrelated_note)"; fi
    suite_verdict "$BR"
    echo "full suite: ${SV_TEXT:-not run on this branch}"
    [ -z "$SV_NOTE" ] || echo "$SV_NOTE"
    version_files_report "$BR"
    remote_report "$BR"; remote_report "$BASE"
    g rev-parse -q --verify "refs/tags/$VER" >/dev/null && echo "tag $VER exists" || true
    if g remote get-url origin >/dev/null 2>&1; then pr_checks_print "$BR"; fi
    tag_checks
    sign_status
    site_status
    post_release;;
  verify)
    rel_valid
    [ -n "$TESTCMD" ] || die "no test_command (or release.test_command) in the answers for $PROJ: qargi project set $PROJ test_command '...'"
    on=$BR; branch_exists "$BR" || on=$BASE
    h=$(sha_of "$on"); [ -n "$h" ] || die "no branch $on"
    worktree "$h"
    echo "running the whole suite on $on at $(g rev-parse --short "$on"): $TESTCMD"
    other_runs_warning
    busy_begin release-verify "$VER"
    t0=$SECONDS
    if run_suite_logged "release-$VER"; then res=pass; else res=fail; fi
    busy_end
    record_suite "$on" "$h" "$res" "$((SECONDS - t0))"
    echo "full suite: $res at $(g rev-parse --short "$on")"
    if [ "$on" = "$BR" ]; then version_files_report "$BR"; fi
    tag_checks
    [ "$res" = pass ] || suite_failure_report
    [ "$res" = pass ];;
  fix)
    # a worktree on the release branch to commit a fix in, once the pull request's checks failed or review asked for a change
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi release start $VER${HOTFIX:+ --hotfix})"
    g rev-parse -q --verify "refs/tags/$VER" >/dev/null && die "the tag $VER exists already: $BR was finished, a fix is a hotfix now (qargi release start $VER --hotfix)"
    fw=$(held "$BR")
    if [ -z "$fw" ]; then
      wtp=$WT_ROOT/$BR; [ ! -e "$wtp" ] || die "$wtp exists already but does not hold $BR: remove or move it"
      mkdir -p "$(dirname "$wtp")" && g worktree add -q "$wtp" "$BR" || die "could not make the worktree of $BR at $wtp"
      fw=$wtp; echo "created the worktree of $BR at $fw"
    else
      echo "$BR is checked out in $fw already"
    fi
    [ -z "$(git -C "$fw" status --porcelain 2>/dev/null)" ] || echo "note: $fw has uncommitted changes"
    echo "worktree: $fw"
    echo "next: fix there (minor fixes only) and commit on $BR; then push the fix with: qargi release fix $VER${HOTFIX:+ --hotfix} --push (the same as release push: a plan token and an approval; it updates the open pull request, whose checks run again)"
    echo "when the checks pass: qargi release finish $VER${HOTFIX:+ --hotfix} (finish removes the worktree)";;
  push)
    rel_valid
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi release start $VER${HOTFIX:+ --hotfix})"
    g remote get-url origin >/dev/null 2>&1 || die "the repository has no origin remote to push $BR to"
    join='' msha=''; if branch_exists master && no_merge_base master "$BR"; then join=1; msha=$(sha_of master); fi   # the plan joins the history of master first (the master it shows)
    tok=$( { printf '%s\n%s\n%s\n' "$PROJ" "$BR" "$h"; [ -z "$join" ] || printf 'join\n%s\n' "$msha"; } | plan_token)
    echo "push $BR (at $(g rev-parse --short "$BR")) to origin and open a pull request into master, so CI runs on the commit that will be released"
    if [ -n "$join" ]; then
      echo "master (at $(g rev-parse --short master)) and $BR have no merge base: they share no history, so finish could not merge them (git refuses unrelated histories; master may be one snapshot commit)"
      echo "join the history of master: merge master into the release branch keeping the release tree (-s ours --allow-unrelated-histories), as a new commit on $BR before the push; the tree of $BR must be the same before and after (checked: the branch does not move otherwise), and master must still be at ${msha:0:7}; the lead's hooks and signing do not run on it"
      jb=$(join_blocker "$BR"); [ -z "$jb" ] || echo "warning: $jb"
    fi
    jq -e '(.release? // {}) | has("preflight")' "$af" >/dev/null 2>&1 && echo "preflight (release.preflight, run in a copy of $BR before the push): $(jq -r '.release.preflight | join(" ")' "$af")"
    remote_report "$BR"
    pw=$(wt_of "$BR"); [ -z "$pw" ] || [ -z "$(git -C "$pw" status --porcelain 2>/dev/null)" ] || echo "warning: $pw has uncommitted changes: only what is committed on $BR is pushed"
    pr_find "$BR"; [ -z "$PR_NUM" ] || echo "the pull request #$PR_NUM of $BR is open already: the push updates it${PR_URL:+ ($PR_URL)}"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi release push $VER${HOTFIX:+ --hotfix} --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    worktree "$h"; run_preflight "$WT"; cleanup
    if [ -n "$join" ]; then
      need_free_wt "$BR"
      join_history "$h" "$msha"; h=$JOINED
      echo "joined the history of master: $BR is at ${h:0:7} (a merge of master that keeps the tree)"
      audit_log "release:join" "$PROJ $BR"
    fi
    rb0=$RTIP; [ "$RSTATE" = found ] || [ "$RSTATE" = absent ] || rb0=$(remote_was "$BR")   # remote_report asked origin live
    g push -q -u origin "$BR" || die "pushing $BR failed"
    journal_push "refs/heads/$BR" "$rb0" "$h" "$KIND:push"
    audit_log "release:push" "$PROJ $BR"
    command -v "$GH" >/dev/null 2>&1 || die "pushed $BR, but gh is not installed: open the pull request into master yourself"
    pr_find "$BR"
    if [ -n "$PR_NUM" ]; then
      echo "pushed $BR and updated PR #$PR_NUM${PR_URL:+: $PR_URL} (it was open already; its checks run on the new head)"
    else
      url=$(cd "$REPO" && "$GH" pr create --base master --head "$BR" --title "$PROJ $VER" --body "$KIND $VER" 2>&1) || {
        # a pull request that could not be listed is still found by the refusal of pr create
        PR_NUM=$(grep -o '/pull/[0-9]*' <<<"$url" | head -1 | tr -dc 0-9)
        if grep -qi 'already exists' <<<"$url" && [ -n "$PR_NUM" ]; then echo "pushed $BR and updated PR #$PR_NUM (it was open already; its checks run on the new head)"; url=''
        else die "pushed $BR; gh pr create failed: $url"; fi
      }
      [ -z "$url" ] || echo "pushed $BR and opened: $url"
    fi
    echo "when its checks pass: qargi release finish $VER${HOTFIX:+ --hotfix}";;
  finish)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR"
    branch_exists master && branch_exists develop || die "git-flow needs a master and a develop branch"
    g rev-parse -q --verify "refs/tags/$VER" >/dev/null && die "the tag $VER exists already"
    rel_valid
    ftmp=$(mktemp -d "$DA_STATE/.release-chk.XXXXXX")
    if [ "$VFILE" != none ]; then
      if [ -f "$REPO/$VFILE" ] || g cat-file -e "$BR:$VFILE" 2>/dev/null; then g show "$BR:$VFILE" 2>/dev/null | grep -qx "$VER" || { rm -rf "$ftmp"; die "$BR does not carry $VFILE $VER"; }; fi
    elif g cat-file -e "$BR:CHANGELOG.md" 2>/dev/null; then   # no version file: the changelog's heading is where the version is written
      g show "$BR:CHANGELOG.md" > "$ftmp/changelog"
      python3 -I "$RL" has-section "$ftmp/changelog" "$VER" "$af" || { rm -rf "$ftmp"; die "release.version_file is none and the CHANGELOG.md of $BR has no released section for $VER (release.changelog.released)"; }
    fi
    # a manual page that leaves with an empty .TH date or version (a regenerated page that lost what `start` set) is not released
    emptyth=''
    while IFS= read -r mp; do
      [ -n "$mp" ] || continue
      g show "$BR:$mp" > "$ftmp/page" 2>/dev/null || continue
      python3 -I "$RL" th-empty "$ftmp/page" >/dev/null || emptyth+=" $mp"
    done < <(man_pages_at "$BR")
    rm -rf "$ftmp"
    [ -z "$emptyth" ] || die "the .TH line of$emptyth on $BR has no date or no version: set them (qargi release start sets both) before finishing"
    # the second target: develop, or for a hotfix the open release branch (the fix reaches develop when that is finished)
    second=develop
    if [ "$KIND" = hotfix ]; then
      rels=$(open_release); n=$(printf '%s' "$rels" | grep -c . || true)
      [ "$n" -le 1 ] || die "more than one release branch is open ($(echo "$rels" | tr '\n' ' ')): merge this hotfix into the right one by hand"
      [ "$n" = 0 ] || second=$rels
    fi
    detached_mix "$BR" master; detached_mix "$BR" "$second"
    if no_merge_base master "$BR"; then
      die "master and $BR share no history (no merge base; master may be one snapshot commit): git would refuse to merge them (unrelated histories) and nothing can be merged. Run qargi release push $VER${HOTFIX:+ --hotfix}: its plan joins the history of master into $BR (a merge that keeps the release tree), then wait for the checks of the pushed head and finish. Nothing was changed"
    fi
    if no_merge_base "$second" "$BR"; then
      if [ "$second" = develop ] && [ "$KIND" = hotfix ]; then   # no release is open: the second target is develop itself, and there is no release to finish first
        die "develop and $BR share no history (no merge base) and no release is open, so there is no release to finish first: git would refuse to merge them (unrelated histories). Join the history of develop and master by hand (a merge of master into develop that keeps develop's tree), then finish the hotfix again. Nothing was changed"
      fi
      die "$second and $BR share no history (no merge base): git would refuse to merge them (unrelated histories). Usually the first release is not finished yet, and its push joins the history of master (qargi release push VERSION): finish that release first, or join them by hand. Nothing was changed"
    fi
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$BR" "$h" "$second" "$(sha_of master)" "$(sha_of "$second")" "$KEEP" "$IGNORE_CHECKS" | plan_token)
    echo "finish $KIND $VER of $PROJ: merge $BR into master with --no-ff, tag $VER on it, merge $BR into $second with --no-ff${KEEP:+, keep $BR}$([ -n "$KEEP" ] || echo ", delete $BR"), push master, $second and the tag together (all or none)"
    remote_report "$BR"; remote_report master; remote_report "$second"
    show_incoming master "$BR"
    if g remote get-url origin >/dev/null 2>&1; then   # the checks of the pull request at the head being released
      pr_checks_print "$BR"
      rw=$(remote_was "$BR"); [ -z "$rw" ] || [ "$rw" = "$h" ] || echo "warning: origin/$BR was at ${rw:0:7} at the last fetch, not at the head ${h:0:7} that is released: those checks may be of an older commit (qargi release push, then wait for the checks)"
      case $PRC_STATE in
        failing|pending)
          if [ -n "$IGNORE_SET" ]; then echo "the checks are $PRC_STATE; ignored on your word: $IGNORE_CHECKS"
          else die "the checks of the pull request of $BR are $PRC_STATE: wait for them, or fix and push again (qargi release fix $VER${HOTFIX:+ --hotfix}); to finish anyway, in your own words: --ignore-checks \"...\""; fi;;
        pass) [ -z "$IGNORE_SET" ] || echo "note: the checks passed, so --ignore-checks changes nothing (nothing is ignored, so the words are not recorded unless the checks fail by the apply)";;
        *) [ -z "$IGNORE_SET" ] || echo "the checks could not be read; ignored on your word: $IGNORE_CHECKS";;
      esac
    fi
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi release finish $VER${HOTFIX:+ --hotfix}${KEEP:+ --keep}${IGNORE_SET:+ --ignore-checks \"$IGNORE_CHECKS\"} --plan $tok --approved \"...\")"; exit 0; fi
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
      pr_checks "$BR"   # read again: they may have changed since the plan
      if [ "$PRC_STATE" != pass ]; then
        if [ -n "$IGNORE_SET" ]; then echo "checks ${PRC_STATE}, ignored on your word: $IGNORE_CHECKS"; IGNORED=1
        elif [ "$PRC_STATE" = nogh ]; then die "gh is needed to read the pull request's checks (or --ignore-checks \"...\" in your own words)"
        else die "the pull request's checks have not all passed (${PRC_STATE}; or there is no pull request for $BR): nothing was merged or pushed. Fix and push again (qargi release fix $VER${HOTFIX:+ --hotfix}), or --ignore-checks \"...\" in your own words"; fi
      fi
    else
      [ "$(verified "$BR")" = "$h pass" ] || die "the repository has no origin, so no CI: the whole suite must have a passing run at the head of $BR (qargi release verify $VER${HOTFIX:+ --hotfix})"
      echo "note: no origin remote, so no CI ran on $BR; the local whole-suite run stands in" >&2
    fi
    need_free master "$second"; need_free_wt "$BR"   # a clean worktree that qargi made for the fix may hold BR: it is removed below
    m0=$(sha_of master); s0=$(sha_of "$second")
    rm0=$(remote_was master); rs0=$(remote_was "$second"); rb0=$(remote_was "$BR")   # what origin has (fetched above): where the journal lines of the pushes start
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
      journal_push refs/heads/master "$rm0" "$nm" "$KIND:finish"
      journal_push "refs/heads/$second" "$rs0" "$ns" "$KIND:finish"
      journal_push "refs/tags/$VER" "" "$(g rev-parse "refs/tags/$VER")" "$KIND:finish"
    fi
    journal_ref "$REPO" "refs/tags/$VER" "" "$(g rev-parse "refs/tags/$VER")" "$KIND:finish"
    g update-ref refs/heads/master "$nm" "$m0" && g update-ref "refs/heads/$second" "$ns" "$s0" || die "origin has the release but master or $second moved locally meanwhile: git fetch origin, then check master and $second against origin"
    journal_ref "$REPO" refs/heads/master "$m0" "$nm" "$KIND:finish"
    journal_ref "$REPO" "refs/heads/$second" "$s0" "$ns" "$KIND:finish"
    merge_forget "$k1" "$k2"
    if [ -z "$KEEP" ]; then wt_drop "$BR"; g update-ref -d "refs/heads/$BR" "$h"; journal_ref "$REPO" "refs/heads/$BR" "$h" "" "$KIND:finish"; fi
    audit_log "release:finish" "$PROJ $VER${IGNORED:+ checks ignored: $IGNORE_CHECKS}"
    [ -z "$IGNORED" ] || echo "checks ignored on your word: $IGNORE_CHECKS"
    echo "merged $BR into master (tagged $VER) and into $second${KEEP:+; kept $BR}$([ -n "$KEEP" ] || echo "; deleted $BR")"
    [ "$second" != develop ] || parking_follow
    if g remote get-url origin >/dev/null 2>&1; then
      if [ -z "$KEEP" ] && [ -n "$rb0" ]; then
        if g push -q origin --delete "$BR"; then journal_push "refs/heads/$BR" "$rb0" "" "$KIND:finish"; else echo "note: could not delete origin/$BR" >&2; fi
      fi
      echo "pushed master, $second and tag $VER"
    else
      echo "no origin remote: nothing was pushed"
    fi
    lead_advice
    after_steps_record
    after_release;;
  assets)
    python3 -I "$RS" lead-only assets || exit $?
    rel_valid
    jq -e '(.release // {}) | has("assets_command")' "$af" >/dev/null 2>&1 || die "release.assets_command is not set for $PROJ: the command that builds the release files, run in a clean worktree of the tag (qargi project set $PROJ release.assets_command '[\"make\", \"dist\"]'; a command line or a list of words)"
    tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || die "no tag $VER (qargi release finish $VER makes it): the release files are built from the tag"
    if [ -e "$ASSETWT" ] || [ -f "$ASSETREC" ]; then
      [ -n "$RECREATE" ] || die "the release asset worktree of $VER exists already ($ASSETWT): its files may be signed; to build again from the tag: qargi release assets $VER --recreate"
      g worktree remove --force "$ASSETWT" >/dev/null 2>&1 || true; rm -rf "$ASSETWT" "$ASSETREC"
    fi
    g worktree prune
    mkdir -p "$(dirname "$ASSETWT")" "$DA_STATE/release"
    g worktree add -q --detach "$ASSETWT" "$tc" 2>/dev/null || die "could not make a worktree of tag $VER at $ASSETWT"
    acmd=()
    if [ "$(jq -r '.release.assets_command | type' "$af")" = array ]; then
      mapfile -d '' -t acmd < <(jq -j --arg v "$VER" '.release.assets_command[] | split("{version}") | join($v), "\u0000"' "$af")
    else acmd=(bash -c "$(jq -r '.release.assets_command' "$af")"); fi
    echo "building the release files of $PROJ $VER in a clean worktree of the tag (${tc:0:7}): $ASSETWT"
    echo "running: ${acmd[*]}"
    arc=0
    run_clean "$ASSETWT" env QARGI_RELEASE_VERSION="$VER" "${acmd[@]}" </dev/null || arc=$?
    [ "$arc" = 0 ] || die "release.assets_command failed (exit $arc); the worktree is left at $ASSETWT to look at (qargi release assets $VER --recreate starts again)"
    jq -n --arg p "$PROJ" --arg v "$VER" --arg c "$tc" --arg w "$ASSETWT" --arg t "$(now)" '{schema:1, project:$p, version:$v, commit:$c, worktree:$w, at:$t}' > "$ASSETREC"
    audit_log "release:assets" "$PROJ $VER"
    made=$( { git -C "$ASSETWT" ls-files --others; git -C "$ASSETWT" ls-files --modified; } | sort -u)
    echo "the release files are in $ASSETWT ($(printf '%s' "$made" | grep -c . || true) file(s) made or changed by the command):"
    printf '%s\n' "$made" | head -n 30 | sed -e '/^$/d' -e 's/^/  /'
    if sign_configured; then echo "next: qargi release sign $VER   (signs release.sign.files from this worktree, then qargi release publish $VER)"
    else echo "next: qargi release publish $VER   (release.assets and --asset FILE or --asset-dir DIR name the files; relative names are taken in this worktree)"; fi;;
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
    sroot=$(sign_root)
    mapfile -t sfiles < <(python3 -I "$RS" resolve "$sroot" "${rels[@]}") && [ "${#sfiles[@]}" = "${#rels[@]}" ] || die "a file of release.sign.files cannot be used"
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
      (cd "$sroot" && "${vcmd[@]}" </dev/null) && vrc=0 || vrc=$?
    fi
    res=$(python3 -I "$RS" record --state "$SIGNREC" --repo "$sroot" --af "$af" --project "$PROJ" --version "$VER" --commit "$tc" --sign-rc "$signrc" --verify-rc "$vrc") || true
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
      sect=$(bash "$(dirname "$0")/changelog_section.sh" "$VER" "$notes" "$(jq -r '(.release? // {}).changelog.released // ""' "$af")" 2>/dev/null) || die "tag $VER: no changelog section for $VER in CHANGELOG.md at the tagged commit (it is missing or empty): nothing to publish"
      printf '%s\n' "$sect" > "$notes"
      nsrc="the $VER section of CHANGELOG.md at the tag"
    fi
    # the assets: release.assets, every --asset and every file of --asset-dir, each a regular file inside the release asset worktree (qargi release assets)
    # or the repository (relative names are taken in the asset worktree when there is one), or inside another worktree of the repository (a full path);
    # attached by the same gh release create
    asset_wt
    aargs=(assets --af "$af" --version "$VER" --base "${AWT:-$REPO}" --root "$REPO")
    while IFS= read -r w; do [ -z "$w" ] || aargs+=(--root "$w"); done < <(g worktree list --porcelain | sed -n 's/^worktree //p')
    for a in "${ASSETS[@]}"; do aargs+=(--asset "$a"); done
    for a in "${ASSET_DIRS[@]}"; do aargs+=(--asset-dir "$a"); done
    assets=(); ahash=; arel=
    out=$(python3 -I "$RS" "${aargs[@]}") || die "an asset cannot be used; nothing was published"
    if [ -n "$out" ]; then
      while IFS=$'\t' read -r h abs rel; do
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
      signline=$(python3 -I "$RS" check --state "$SIGNREC" --repo "$(sign_root)" --af "$af" --commit "$tc") \
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
  site)
    python3 -I "$RSITE" lead-only || exit $?
    [ -z "$HOTFIX" ] || die "--hotfix does not belong to release site: the site is built from the tag VERSION, whatever made it"
    site_answers || die "the site answers of $PROJ are not valid (qargi project validate $PROJ)"
    [ "$SITE_ON" = true ] || die "the site of $PROJ is not enabled: set site.enabled to true (qargi project set $PROJ site.enabled true; site.branch and site.config say where it lives)"
    tc=$(g rev-parse -q --verify "refs/tags/$VER^{commit}") || die "no tag $VER (qargi release finish $VER makes it): the site is built from the tag"
    s0=$(sha_of "$SITE_BR")
    if [ -z "$s0" ]; then
      g rev-parse -q --verify "refs/remotes/origin/$SITE_BR" >/dev/null && die "no local branch $SITE_BR: git -C $REPO branch $SITE_BR origin/$SITE_BR"
      die "no branch $SITE_BR (site.branch): the hand pages live there; make it once with git switch --orphan $SITE_BR"
    fi
    is_detached "$SITE_BR" || die "$SITE_BR is not in repo.detached: the site branch never meets the git-flow branches"
    g cat-file -e "$s0:$SITE_CONF" 2>/dev/null || die "$SITE_BR has no $SITE_CONF (site.config)"
    g cat-file -e "$s0:$SITE_PAGES" 2>/dev/null || die "$SITE_BR has no folder $SITE_PAGES beside $SITE_CONF: the hand pages live there"
    need_free "$SITE_BR"
    # the source is the tag's tree, extracted; the hand pages and site.json are the site branch's, in a temporary worktree of it
    SITESRC=$(mktemp -d "$DA_STATE/release-site-src.XXXXXX")
    g archive --format=tar "$tc" | tar -x -C "$SITESRC" || die "could not extract the tree of tag $VER"
    worktree "$s0"
    python3 -I "$RSITE" set-release "$WT/$SITE_CONF" "$VER" || exit 1
    git -C "$WT" rm -r -q --ignore-unmatch -- _site >/dev/null; rm -rf "${WT:?}/_site"
    bout=$(cd "$WT" && python3 -I "$(dirname "$0")/site.py" build --release "$VER" --source "$SITESRC" --pages "$WT/$SITE_PAGES" --config "$WT/$SITE_CONF" \
             --out "$WT/_site" --allow-root "$WT" </dev/null 2>&1) \
      || die "the site of $VER did not build; nothing was changed:"$'\n'"$(printf '%s\n' "$bout" | tail -n 25 | sed 's/^/  | /')"
    # the build runs to check the site (a page that does not build refuses), but its output is not committed: a Pages build of the branch needs _site/
    # empty. A _site/ that an earlier build committed is removed by the commit (the git rm above).
    rm -rf "${WT:?}/_site"
    git -C "$WT" add -A -- "$SITE_CONF"
    if git -C "$WT" diff --cached --quiet; then echo "the site on $SITE_BR (at ${s0:0:7}) is already the build of $VER: nothing to commit"; exit 0; fi
    tree=$(git -C "$WT" write-tree)
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$VER" "$tc" "$SITE_BR" "$s0" "$tree" | plan_token)
    echo "build the documentation site of $PROJ $VER: the tree of tag $VER (${tc:0:7}) with lib/site.py, and the hand pages of $SITE_BR (${s0:0:7}) in $SITE_PAGES"
    echo "commit it on $SITE_BR: $SITE_CONF records release $VER; the build only checks the site, _site/ is not committed (and one an earlier build committed is removed); nothing is pushed"
    printf '%s\n' "$bout" | grep -E '^(warning|error|note):|^build:' | head -20 | sed 's/^/  | /'
    echo "  changes: $(git -C "$WT" diff --cached --shortstat | sed 's/^ *//')"
    remote_report "$SITE_BR"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi release site $VER --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    wcommit -m "$SITE_SUBJECT $VER" -m "Built by qargi release site from tag $VER (${tc:0:12}) with the hand pages of $SITE_BR at ${s0:0:12}: $SITE_CONF records release $VER; _site/ is not committed."
    new=$(git -C "$WT" rev-parse HEAD)
    g update-ref "refs/heads/$SITE_BR" "$new" "$s0" || die "$SITE_BR moved meanwhile; nothing was changed (run it again)"
    journal_ref "$REPO" "refs/heads/$SITE_BR" "$s0" "$new" "release:site"
    audit_log "release:site" "$PROJ $VER $SITE_BR ${new:0:12}"
    echo "built the site of $VER on $SITE_BR at ${new:0:7}; nothing was pushed"
    echo "preview it before you push: build the site locally and serve it (the site branch's build script, for example tools/build-local.sh REPO OUT, then python3 -m http.server --directory OUT)"
    if g remote get-url origin >/dev/null 2>&1; then echo "push it with: git -C $REPO push origin $SITE_BR"
    else echo "the repository has no origin remote: push $SITE_BR where the site is deployed from"; fi;;
  *) die "usage: qargi release start|status|verify|fix|push|finish|assets|sign|publish|site VERSION [--hotfix] [--project P]";;
esac
