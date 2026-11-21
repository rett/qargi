#!/usr/bin/env bash
# `--dry-run` of the git-flow verbs that have one: release start, release push and release fix --push, feature finish and branch prune. A dry run prints the plan, the
# refusals the apply would meet (each as the apply prints it, with dry=1 first in the detail of the contract line) and `dry-run: N would refuse; nothing was changed`, and
# changes nothing: the refs of the repository and of its origin, .git/worktrees, the state directory (the audit log, the ref journal, the intent and lock files, the marshal
# records, the stored plans), no lease renewed, nothing fetched. Every case compares a snapshot of all of it before and after. Offline: a bare repository is the origin.
# The last part is `branch prune --agents`, the one deletion of branch prune that is not gated: the merged agent branches at once, journaled first, the lead's, branches only (a
# branch held by any worktree is kept, as is one the journal does not reach).
# Run: tests/test_dry_run.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_LEAD=lead GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin"
cd "$T" || exit 1   # not below the checkout: when that is a member's run directory, the verbs below would be refused as a member's
REL="$DA release"; F="$DA feature"
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gh.log"\ncase "$*" in *"pr create"*) echo https://example.net/acme/x/pull/1;; esac\n' "$T" > "$T/gh"; chmod +x "$T/gh"; export QARGI_GH=$T/gh

# snap: everything a dry run must leave as it was, as one digest: the refs of the repository (R) and of its origin (O), its worktrees, the names in .git and .git/worktrees (a fetch
# leaves FETCH_HEAD), and the state directory with the digest of every file (the audit log, the ref journal, the intent and lock files, the marshal records, the stored plans)
snap() { { git -C "$R" for-each-ref; git -C "$R" worktree list; ls -A "$R/.git" "$R/.git/worktrees" 2>/dev/null; [ -z "${O:-}" ] || git -C "$O" for-each-ref
           find "$T/s" | sort; find "$T/s" -type f -exec md5sum {} + 2>/dev/null | sort -k2; } | md5sum; }
lastline() { tail -n 1 "$T/do"; }
wtl() { { ls -A "$R/.git/worktrees" 2>/dev/null; git -C "$R" worktree list; } | md5sum; }
# dry ARGS...: runs the command (a qargi verb with --dry-run), standard output in $T/do, standard error in $T/de, and sets rc and the snapshots
dry() { s0=$(snap); "$@" >"$T/do" 2>"$T/de"; rc=$?; s1=$(snap); }
contract() { grep -m1 '^qargi-refusal/1 ' "$T/de"; }
mkproj() { # NAME [with-origin]: a repository with master and develop, the project's answers, the main checkout parked
  R=$T/$1; O=''; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"
  git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
  if [ -n "${2:-}" ]; then O=$T/$1-origin.git; git init -q --bare "$O"; git -C "$R" remote add origin "$O"; git -C "$R" push -q origin master develop; fi
  git -C "$R" checkout -q -b parked
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
}
task() { # NAME: a task branch with one commit, cut from develop (as an applied, verified series would be)
  git -C "$R" branch "agent/$1" "${2:-develop}"; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R" worktree remove --force "$w"
}
# rstart ARGS: release start through its plan (a token) and the approval; a refusal of the plan is printed and fails
rstart() { local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go; }

# ---------------------------------------------------------------------------------------------------------------------------- release
mkproj rel with-origin
$REL verify 0.2.0 >/dev/null 2>&1
w0=$(wtl); dry $REL start 0.2.0 --date 2026-03-04 --dry-run
[ "$rc" = 0 ] && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ "$w0" = "$(wtl)" ] && [ -z "$(ls -A "$R/.git/worktrees" 2>/dev/null)" ] \
  && ok "release start --dry-run: the plan, 0 would refuse, exit 0; the refs, the state directory and .git/worktrees are as they were" || no "start dry run: rc=$rc $(cat "$T/do" "$T/de")"
dt=$(tok < "$T/do"); [ -n "$dt" ] && [ "$dt" = "$($REL start 0.2.0 --date 2026-03-04 | tok)" ] && ok "the token of a dry run is the plain plan's" || no "dry token $dt"
before=$(wtl); dry $REL start 0.2.0 --date 2026-03-05 --dry-run --plan "$dt"
[ "$rc" = 1 ] && contract | grep -q '"code":"plan-stale".*"detail":"dry=1 moved=date token=' && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ "$before" = "$(wtl)" ] \
  && ok "release start --dry-run with a token that moved: plan-stale names the label (date), dry=1 first in the detail, 1 would refuse, exit 1" || no "start dry run, stale: rc=$rc $(cat "$T/do" "$T/de")"
# a refusing fixture: develop moved on since the suite last passed
mkproj relno with-origin
git -C "$R" update-ref refs/heads/develop "$(git -C "$R" commit-tree -p develop -m x 'develop^{tree}')"
dry $REL start 0.2.0 --dry-run
[ "$rc" = 1 ] && grep -q "the whole suite has no passing run at the head of develop" "$T/de" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ -z "$(ls -A "$R/.git/worktrees" 2>/dev/null)" ] \
  && ok "release start --dry-run of a develop that did not pass: the refusal, 1 would refuse, exit 1, nothing changed" || no "start dry run, refused: rc=$rc $(cat "$T/do" "$T/de")"
# a TERM while the worktree of the plan exists: the exit trap removes it, and no last line is printed (the status is 143)
mkproj relterm with-origin
$REL verify 0.2.0 >/dev/null 2>&1
jq --arg m "$T/dmark" --arg g "$T/dgo" '.release = {preflight: ["sh", "-c", "touch " + $m + "; i=0; while [ ! -e " + $g + " ] && [ $i -lt 30 ]; do sleep 0.1; i=$((i + 1)); done"]}' "$T/c/projects/relterm.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/relterm.json"
rm -f "$T/dmark" "$T/dgo"; s0=$(snap)
$REL start 0.2.0 --dry-run >"$T/do" 2>"$T/de" & dpid=$!
wait_until '[ -e "$T/dmark" ]' 10 && kill -TERM "$dpid"; : > "$T/dgo"; wait "$dpid"; rc=$?
[ "$rc" = 143 ] && [ "$s0" = "$(snap)" ] && ! grep -q '^dry-run:' "$T/do" && ok "release start --dry-run ended by TERM while its worktree exists leaves .git/worktrees, git worktree list and the state directory as they were" || no "TERM: rc=$rc $(cat "$T/do" "$T/de"); $(ls -A "$R/.git/worktrees")"
# push, and a fix outside the cut
mkproj relpush with-origin
$REL verify 0.2.0 >/dev/null 2>&1
rstart 0.2.0 --date 2026-03-04 >/dev/null 2>&1 || no "(setup) release start"
: > "$T/gh.log"; dry $REL push 0.2.0 --dry-run
[ "$rc" = 0 ] && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && ! grep -q "pr create" "$T/gh.log" && [ -z "$(git -C "$O" for-each-ref refs/heads/release)" ] \
  && ok "release push --dry-run: 0 would refuse; nothing is pushed, no pull request is made, nothing changed" || no "push dry run: rc=$rc $(cat "$T/do" "$T/de")"
mkproj relfix with-origin
$REL verify 0.2.0 >/dev/null 2>&1
ct=$($REL plan 0.2.0 --date 2026-03-04 2>&1 | tok); $REL plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "go ahead" >/dev/null 2>&1; $REL start 0.2.0 --plan "$ct" >/dev/null 2>&1
w=$($REL fix 0.2.0 | sed -n 's/^worktree: //p'); echo fix > "$w/fix.txt"; git -C "$w" add fix.txt && git -C "$w" commit -q -m "a fix"; fx=$(git -C "$R" rev-parse --short=7 release/0.2.0)
dry $REL fix 0.2.0 --push --dry-run --plan "$ct"
[ "$rc" = 1 ] && contract | grep -q "\"code\":\"cut-fix-outside\",\"exit\":1,\"verb\":\"release push\".*\"detail\":\"dry=1 commits=$fx\"" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] \
  && ok "release fix --push --dry-run over a commit outside the cut: cut-fix-outside, 1 would refuse, nothing changed" || no "fix --push dry run: rc=$rc $(cat "$T/do" "$T/de")"

# ---------------------------------------------------------------------------------------------------------------------------- feature finish
mkproj fin with-origin
$F start fa >/dev/null 2>&1; task t1 feature/fa; $F merge fa agent/t1 >/dev/null 2>&1; $F verify fa >/dev/null 2>&1
plain=$($F finish fa 2>&1); pt=$(tok <<<"$plain")
[ -n "$pt" ] && ok "(setup) a feature with a passing run: the plain plan has a token" || no "(setup) plain plan: $plain"
# the marshal lease is renewed by a verb of the lead once a third of it has passed: with the clock ten minutes on, a plain verb would write the record, a dry run must not
fclock=$(( $(date +%s) + 600 ))
dry env QARGI_MARSHAL_NOW=$fclock $F finish fa --dry-run
[ "$rc" = 0 ] && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && grep -q "^invalidated by: project, branch, head, develop, keep, delete-merged, origin-branch, push$" "$T/do" && grep -q "^not fetched: origin is asked with ls-remote" "$T/do" \
  && ok "feature finish --dry-run: the plan, what invalidates it, 0 would refuse, exit 0; the lease is not renewed and nothing is fetched or changed" || no "finish dry run: rc=$rc $(cat "$T/do" "$T/de")"
s0=$(snap); env QARGI_MARSHAL_NOW=$fclock $F finish fa >/dev/null 2>&1; [ "$s0" != "$(snap)" ] && ok "(control) the same moment, without --dry-run, renews the lease: the snapshot does see a write" || no "(control) the plain finish plan left the snapshot as it was"
[ "$(tok < "$T/do")" = "$pt" ] && ok "the token of the dry run is the plain plan's" || no "finish dry token: $(tok < "$T/do") against $pt"
dry $F finish fa --dry-run --plan "$pt"
[ "$rc" = 0 ] && grep -q "the plan $pt is the one shown: the apply of finish would go on" "$T/do" && grep -q "^not run in a dry run: the finish itself" "$T/do" && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ "$(git -C "$R" rev-parse develop)" != "$(git -C "$R" rev-parse feature/fa)" ] \
  && ok "with the token that was shown the dry run says the apply would go on, and merges, pushes and deletes nothing" || no "finish dry run with the token: rc=$rc $(cat "$T/do" "$T/de")"
dry $F finish fa --keep --dry-run --plan "$pt"
[ "$rc" = 1 ] && contract | grep -q '"code":"plan-stale","exit":1,"verb":"feature finish".*"detail":"dry=1 moved=keep token=' && grep -q "refused \[plan-stale\] .*moved: keep" "$T/de" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] \
  && ok "a token of another plan: plan-stale names the label that moved (keep), dry=1 first in the detail, 1 would refuse, exit 1" || no "finish dry run, stale: rc=$rc $(cat "$T/do" "$T/de")"
dry $F finish fa --dry-run --approved go
[ "$rc" = 0 ] && [ "$(git -C "$R" rev-parse develop)" != "$(git -C "$R" rev-parse feature/fa)" ] && [ "$s0" = "$s1" ] && ok "--approved with --dry-run applies nothing" || no "dry run with --approved: rc=$rc $(cat "$T/do" "$T/de")"
# origin is asked, never fetched: a commit that reached origin's develop and is not here yet is named, and nothing is fetched
oc=$(git -C "$O" commit-tree -p develop -m "on origin" 'develop^{tree}'); git -C "$O" update-ref refs/heads/develop "$oc"; rm -f "$R/.git/FETCH_HEAD"
dry $F finish fa --dry-run
[ "$rc" = 0 ] && grep -q "origin/develop is at ${oc:0:7}, which this repository does not have yet: the apply fetches it" "$T/do" && [ "$s0" = "$s1" ] && [ ! -e "$R/.git/FETCH_HEAD" ] \
  && ok "origin's develop ahead of this repository: named with ls-remote, 'not fetched', no FETCH_HEAD, nothing changed" || no "finish dry run, origin ahead: rc=$rc $(cat "$T/do" "$T/de")"
git -C "$R" fetch -q origin; dry $F finish fa --dry-run
[ "$rc" = 1 ] && grep -q "develop is behind or differs from origin/develop" "$T/de" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && ok "origin's develop that is not in develop: a refusal the apply meets after its fetch, 1 would refuse" || no "finish dry run, origin differs: rc=$rc $(cat "$T/do" "$T/de")"
git -C "$O" update-ref refs/heads/develop "$(git -C "$R" rev-parse develop)"; git -C "$R" fetch -q origin
# another live lead holds the feature: the marshal's refusal, counted
dry env QARGI_LEAD=bob $F finish fa --dry-run
[ "$rc" = 1 ] && grep -q "led by lead" "$T/de" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && ok "a feature another lead holds: the marshal's refusal, 1 would refuse, nothing changed" || no "finish dry run, another lead: rc=$rc $(cat "$T/do" "$T/de")"
# a finish with no passing run
$F start fb >/dev/null 2>&1; task t2 feature/fb; $F merge fb agent/t2 >/dev/null 2>&1
dry $F finish fb --dry-run
[ "$rc" = 1 ] && grep -q "the whole suite has no passing run at the head of feature/fb" "$T/de" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && ok "feature finish --dry-run of a feature with no passing run: the refusal, 1 would refuse, nothing changed" || no "finish dry run, refused: rc=$rc $(cat "$T/do" "$T/de")"
dry $F finish nope --dry-run
[ "$rc" = 1 ] && grep -q "no branch feature/nope" "$T/de" && [ "$s0" = "$s1" ] && ok "a feature that does not exist: refused, and no record is made of it" || no "finish dry run, no feature: rc=$rc $(cat "$T/do" "$T/de")"
# an earlier finish that was cut off left a record: the dry run shows what finishing it would do, and the record, its lock and the refs stay
fh=$(git -C "$R" rev-parse feature/fa); dv=$(git -C "$R" rev-parse develop)
mkdir -p "$T/s/finish-intent"
jq -nc --arg d0 "$dv" --arg m "$fh" --arg h "$fh" '{schema:1, verb:"feature:finish", project:"fin", name:"fa", pushed:false, refs:[{ref:"refs/heads/develop", local_old:$d0, origin_old:"", new:$m}], ctx:{head:$h, keep:"1", pushd:"", pushwhy:"the repository has no origin", rdel:"", k:"k"}, done:[]}' > "$T/s/finish-intent/fin-feature-fa.json"
dry $F finish fa --dry-run
[ "$rc" = 0 ] && grep -q "finish feature fa of fin was cut off" "$T/do" && grep -q "^invalidated by: record$" "$T/do" && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ ! -e "$T/s/finish-intent/fin-feature-fa.json.run" ] \
  && ok "a finish that was cut off: the dry run shows what finishing it does, takes no lock and leaves the record as it is" || no "finish dry run, cut off: rc=$rc $(cat "$T/do" "$T/de")"
rm -f "$T/s/finish-intent/fin-feature-fa.json"
out=$($F status fa --dry-run 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "belongs to feature finish" <<<"$out" && ok "--dry-run belongs to feature finish: another feature verb refuses it" || no "--dry-run on status: rc=$rc $out"

# ---------------------------------------------------------------------------------------------------------------------------- branch prune
B="$DA branch"
mkproj prn with-origin
$F start pa >/dev/null 2>&1; task t1 feature/pa; task t2 feature/pa; $F merge pa agent/t1 >/dev/null 2>&1; $F merge pa agent/t2 >/dev/null 2>&1   # two agent branches merged into an open feature
$F start pb >/dev/null 2>&1; task t4 feature/pb; $F merge pb agent/t4 >/dev/null 2>&1; $F verify pb >/dev/null 2>&1
fp=$($F finish pb --keep 2>&1 | tok); $F finish pb --keep --plan "$fp" --approved go >/dev/null 2>&1   # feature/pb is merged into develop and kept
task t9   # not merged anywhere: kept
git -C "$R" rev-parse -q --verify refs/heads/feature/pb >/dev/null && [ "$($B prune | grep -c '^  delete local')" = 4 ] && ok "(setup) four merged branches are listed by the plain plan: agent/t1, agent/t2, agent/t4 and feature/pb" || no "(setup) prune plan: $($B prune 2>&1)"
pp=$($B prune | tok)
dry $B prune --dry-run
[ "$rc" = 0 ] && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ "$(tok < "$T/do")" = "$pp" ] && grep -q "^invalidated by: project, remote, branches$" "$T/do" && [ "$(grep -c '^  delete local' "$T/do")" = 4 ] \
  && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/agent/t1)" ] && ok "branch prune --dry-run: the plan with the plain plan's token, what invalidates it, 0 would refuse, exit 0; nothing is deleted and nothing else changed" || no "prune dry run: rc=$rc $(cat "$T/do" "$T/de")"
dry $B prune --dry-run --plan "$pp"
[ "$rc" = 0 ] && grep -q "the plan $pp is the one shown: the apply of branch prune would go on" "$T/do" && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/agent/t2)" ] \
  && ok "with the token that was shown the dry run says the apply would go on, and deletes nothing" || no "prune dry run with the token: rc=$rc $(cat "$T/do" "$T/de")"
dry $B prune --dry-run --approved go
[ "$rc" = 0 ] && [ "$s0" = "$s1" ] && [ "$(grep -c '^  delete local' "$T/do")" = 4 ] && ok "--approved with --dry-run applies nothing" || no "prune dry run with --approved: rc=$rc $(cat "$T/do" "$T/de")"
task t3 feature/pa; $F merge pa agent/t3 >/dev/null 2>&1   # another merged branch since the plan: the plan changed
dry $B prune --dry-run --plan "$pp"
[ "$rc" = 1 ] && contract | grep -q '"code":"plan-stale","exit":1,"verb":"branch prune".*"detail":"dry=1 moved=branches token=' && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && [ "$(grep -c '^  delete local' "$T/do")" = 5 ] \
  && ok "a branch merged since the plan: plan-stale names the label that moved (branches), dry=1 first in the detail, 1 would refuse, exit 1, nothing deleted" || no "prune dry run, stale: rc=$rc $(cat "$T/do" "$T/de")"
# --remote: origin is asked with ls-remote and never fetched; the branches on origin are planned, and a tip this repository does not have is kept as 'not fetched'
git -C "$R" push -q origin agent/t1 agent/t2 feature/pb
git clone -q "$O" "$T/other" && git -C "$T/other" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m "only on origin" && git -C "$T/other" push -q origin HEAD:refs/heads/agent/zz
rm -f "$R/.git/FETCH_HEAD"
dry $B prune --remote --dry-run
[ "$rc" = 0 ] && grep -q "^not fetched: origin is asked with ls-remote" "$T/do" && grep -q "^  delete origin/agent/t1 " "$T/do" && grep -q "^  kept origin/agent/zz: its tip .* is not fetched" "$T/do" && [ "$s0" = "$s1" ] && [ ! -e "$R/.git/FETCH_HEAD" ] && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] \
  && ok "branch prune --remote --dry-run: origin asked with ls-remote, 'not fetched', no FETCH_HEAD; the branches on origin are planned and nothing is deleted there" || no "prune --remote dry run: rc=$rc $(cat "$T/do" "$T/de")"
mkproj prn0 with-origin
dry $B prune --dry-run
[ "$rc" = 0 ] && grep -q "^no merged agent/\* or feature/\* branches to prune" "$T/do" && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && ok "branch prune --dry-run with nothing to prune: the plan says so, 0 would refuse" || no "prune dry run, nothing: rc=$rc $(cat "$T/do" "$T/de")"

# ---------------------------------------------------------------------------------------------------------------------------- branch prune --agents
# the one deletion that is not gated: the merged agent/* branches of the repository, at once, journaled first, the lead's; it deletes branches only, so a branch a worktree holds is kept
mkproj agp with-origin
$F start fa >/dev/null 2>&1; task t1 feature/fa; task t2 feature/fa; task t5 feature/fa; task t6 feature/fa
git -C "$R" branch agent/hand develop; $DA ref note agent/hand >/dev/null 2>&1   # a branch the lead made and noted, then committed on with git
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" agent/hand; echo by-hand > "$w/hand.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "by hand"; git -C "$R" worktree remove --force "$w"
for b in t1 t2 t5 t6 hand; do $F merge fa "agent/$b" >/dev/null 2>&1; done   # merged into the open feature
task t3   # not merged anywhere: kept
$F start pb >/dev/null 2>&1; task t4 feature/pb; $F merge pb agent/t4 >/dev/null 2>&1; $F verify pb >/dev/null 2>&1
fp=$($F finish pb --keep 2>&1 | tok); $F finish pb --keep --plan "$fp" --approved go >/dev/null 2>&1   # feature/pb is merged into develop and kept: gated
for b in t1 t2 t3 t4 t5 t6; do $DA ref note "agent/$b" >/dev/null 2>&1; done   # the branches the verbs made are in the ref journal; --agents keeps one the journal does not reach
mkdir -p "$T/s/worktrees/agp/agent"; git -C "$R" worktree add -q "$T/s/worktrees/agp/agent/t2" agent/t2   # a worktree qargi made, clean: its branch is kept all the same (the gated prune removes it)
git -C "$R" worktree add -q "$T/s/worktrees/agp/agent/t5" agent/t5; echo dirty > "$T/s/worktrees/agp/agent/t5/dirty.txt"   # a dirty one: its branch is kept
git -C "$R" push -q origin agent/t6
tips=$(for b in t1 t4 t6 hand; do git -C "$R" rev-parse "agent/$b"; done | paste -sd' ')
dry $B prune --agents --dry-run
[ "$rc" = 0 ] && grep -q "^prune the merged agent branches of agp: 4 local (--agents: no plan token and no approval" "$T/do" && grep -q "^the apply of --agents would delete these 4 branches at once" "$T/do" && ! grep -q "^plan token" "$T/do" && ! grep -q "feature/pb" "$T/do" \
  && grep -q "^  kept agent/t5: its worktree .* has uncommitted changes" "$T/do" && grep -q "^  kept agent/t2: held by worktree .*agent/t2; the gated prune removes it$" "$T/do" && ! grep -q "remove its worktree" "$T/do" && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] \
  && ok "branch prune --agents --dry-run: the plan (the merged agent branches only, no token), nothing is deleted or changed" || no "agents dry run: rc=$rc $(cat "$T/do" "$T/de")"
out=$(QARGI_MEMBER_RUN=1 $B prune --agents 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "not available in a member run" <<<"$out" && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/agent/t1)" ] && ok "a member run is refused (exit 2) and deletes nothing" || no "agents in a member run: rc=$rc $out"
for a in "--remote" "--plan 000000000000" "--approved go"; do
  out=$($B prune --agents $a 2>&1); rc=$?
  [ "$rc" = 2 ] && grep -q "^qargi: --agents " <<<"$out" && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/agent/t1)" ] || no "--agents $a: rc=$rc $out"
done
ok "--agents with --remote, --plan or --approved is a usage error (exit 2), and deletes nothing"
before_audit=$(wc -l < "$T/s/audit.log" 2>/dev/null || echo 0)
out=$($B prune --agents 2>&1); rc=$?
gone=''; for b in t1 t4 t6 hand; do git -C "$R" rev-parse -q --verify "refs/heads/agent/$b" >/dev/null && gone="$gone $b"; done
[ "$rc" = 0 ] && [ -z "$gone" ] && grep -q "^deleted agent/t1$" <<<"$out" && ! grep -q "removed the worktree" <<<"$out" && grep -q "^pruned 4 local branch(es)$" <<<"$out" && ! grep -q "^plan token: " <<<"$out" \
  && ok "branch prune --agents deletes the merged agent branches at once, with no token and no approval" || no "agents apply: rc=$rc gone=$gone $out"
[ -n "$(git -C "$R" rev-parse -q --verify refs/heads/agent/t3)" ] && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/agent/t5)" ] && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/agent/t2)" ] && [ -d "$T/s/worktrees/agp/agent/t2" ] && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/feature/pb)" ] && [ -n "$(git -C "$R" rev-parse -q --verify refs/heads/feature/fa)" ] \
  && [ -n "$(git -C "$O" rev-parse -q --verify refs/heads/agent/t6)" ] && ok "kept: the unmerged agent branch, the ones a worktree holds (a clean one too, and the worktree stays), the feature branches (gated) and the branch on origin (--remote stays gated)" || no "agents kept: $(git -C "$R" for-each-ref --format='%(refname)' refs/heads)"
reach=1; for t in $tips; do git -C "$R" cat-file -e "$t^{commit}" && { git -C "$R" merge-base --is-ancestor "$t" feature/fa || git -C "$R" merge-base --is-ancestor "$t" develop; } || reach=''; done
[ -n "$reach" ] && ok "every tip stays reachable from the branch it was merged into" || no "a tip is not reachable"
J=$T/s/ref-journal.jsonl
jq -e -s --arg r "$(readlink -f "$R")" '[.[] | select(.ref == "refs/heads/agent/hand" and .repo == $r)] | (.[0].old | test("^0+$")) and (.[-1].new | test("^0+$")) and (.[-1].verb == "branch:prune") and (length >= 3) and ([.[1:-1][] | select(.verb == "branch:prune" and (.why | test("^a commit made on the branch with git")))] | length >= 1)' "$J" >/dev/null \
  && ok "the commits made with git on a noted branch are journaled before it is deleted (journal_reach), then the deletion (branch:prune)" || no "journal of agent/hand: $(jq -c 'select(.ref == "refs/heads/agent/hand") | [.old[0:7], .new[0:7], .verb]' "$J" | paste -sd' ')"
jq -e -s '[.[] | select(.ref == "refs/heads/agent/t1")] | .[-1] | (.new | test("^0+$")) and .verb == "branch:prune"' "$J" >/dev/null && ok "each deletion is a line of the journal" || no "journal of agent/t1"
[ "$(wc -l < "$T/s/audit.log")" = $((before_audit + 1)) ] && tail -n 1 "$T/s/audit.log" | jq -e '.verb == "branch:prune" and (.detail | test("agp 4 local 0 remote")) and .approved == ""' >/dev/null && ok "one audit line, branch:prune, with no approval words" || no "audit line: $(tail -n 2 "$T/s/audit.log")"
out=$($B prune --agents 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^no merged agent/\* branches to prune" <<<"$out" && ok "a second run finds nothing to prune" || no "agents, nothing left: rc=$rc $out"
out=$($B prune 2>&1); grep -q "delete local feature/pb" <<<"$out" && grep -q "delete local agent/t2 .*; remove its worktree .*agent/t2" <<<"$out" && ! grep -Eq "delete local agent/(t1|t4|t6|hand) " <<<"$out" && grep -q "^plan token: " <<<"$out" \
  && ok "the plain prune still plans the feature branch and the agent branch a clean worktree of qargi holds (with its worktree), and asks for a token" || no "plain prune after --agents: $out"

# ---------------------------------------------------------------------------------------------------------------------------- branch prune --agents: worktrees and the journal
# a worktrees.root that contains the repository (the project's validation accepts it): a merged agent branch checked out in the main checkout is kept, so is one outside the root, one in a worktree
# the runtime made inside the repository, one in a clean worktree qargi made (git does not list its ignored files, and status.showUntrackedFiles=no hides its untracked ones: --agents removes no
# worktree), one that repo.long_lived or repo.detached names, and one the journal does not reach (made by hand and not noted, or a journal with a line that is not JSON); a free one is deleted
mkproj agr with-origin
jq --arg r "$T" '.worktrees = {root: $r} | .repo.long_lived += ["agent/ll"] | .repo.detached = ["agent/dt"]' "$T/c/projects/agr.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/agr.json"
$F start fa >/dev/null 2>&1
for b in m1 o1 q1 i1 d1 d2 d3; do task "$b" feature/fa; done
git -C "$R" branch agent/ll develop; git -C "$R" branch agent/dt develop
for b in m1 o1 q1 i1 d1 d3 ll dt; do $DA ref note "agent/$b" >/dev/null 2>&1; done   # d2 is made by hand and not noted
for b in m1 o1 q1 i1 d1 d2 d3; do $F merge fa "agent/$b" >/dev/null 2>&1; done
printf '*.local\n' >> "$R/.git/info/exclude"; git -C "$R" config status.showUntrackedFiles no
wo=$(mktemp -d); rmdir "$wo"; wi=$R/.wt-d3                                   # outside the root; inside the repository
git -C "$R" checkout -q agent/m1                                             # the main checkout holds it (the root contains the repository, so the path test alone calls it qargi's)
git -C "$R" worktree add -q "$wo" agent/o1
git -C "$R" worktree add -q "$wi" agent/d3
git -C "$R" worktree add -q "$T/agent/q1" agent/q1                           # a clean worktree qargi made
git -C "$R" worktree add -q "$T/agent/i1" agent/i1; echo secret > "$T/agent/i1/.env.local"; echo note > "$T/agent/i1/untracked.txt"   # an ignored and an untracked file: git status is clean
[ -z "$(git -C "$T/agent/i1" status --porcelain)" ] && ok "(setup) the worktree with an ignored and an untracked file reports a clean status" || no "(setup) i1 status: $(git -C "$T/agent/i1" status --porcelain)"
dry $B prune --agents --dry-run
[ "$rc" = 0 ] && grep -q "^  delete local agent/d1 " "$T/do" && ! grep -q "remove its worktree" "$T/do" && [ "$(grep -c '^  delete local' "$T/do")" = 1 ] && grep -q "^  kept agent/m1: checked out in $(readlink -f "$R"), which qargi did not make$" "$T/do" \
  && grep -q "^  kept agent/o1: checked out in $wo, which qargi did not make$" "$T/do" && grep -q "^  kept agent/d3: checked out in $wi, which qargi did not make$" "$T/do" && grep -q "^  kept agent/q1: held by worktree $T/agent/q1; the gated prune removes it$" "$T/do" \
  && grep -q "^  kept agent/i1: held by worktree $T/agent/i1; the gated prune removes it$" "$T/do" && grep -Eq "^  kept agent/d2: its journal does not reach [0-9a-f]{7} \(the journal has no line of it: .*; the gated prune deletes it$" "$T/do" && [ "$s0" = "$s1" ] \
  && ok "--agents --dry-run, root containing the repository: only the branch no worktree holds and the journal reaches is planned; the main checkout's, the outside one, the one inside the repository, the clean worktrees' and the unreached one are kept" || no "agents (root containing the repository) dry run: rc=$rc $(cat "$T/do" "$T/de")"
out=$($B prune --agents 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^deleted agent/d1$" <<<"$out" && grep -q "^pruned 1 local branch(es)$" <<<"$out" && ! grep -Eq "^removed the worktree|could not remove" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/agent/d1 >/dev/null \
  && ok "--agents deletes the one branch that is free, and removes no worktree" || no "agents apply (root containing the repository): rc=$rc $out"
kept=1; for b in m1 o1 q1 i1 d2 d3 ll dt; do git -C "$R" rev-parse -q --verify "refs/heads/agent/$b" >/dev/null || kept=''; done
[ -n "$kept" ] && [ "$(git -C "$R" symbolic-ref -q HEAD)" = refs/heads/agent/m1 ] && [ -d "$wo" ] && [ -d "$wi" ] && [ -d "$T/agent/q1" ] && [ -f "$T/agent/i1/.env.local" ] && [ -f "$T/agent/i1/untracked.txt" ] && git -C "$R" worktree list | grep -q "$T/agent/i1" \
  && ok "every other branch is kept, the main checkout is still on its branch, no worktree is gone, and the ignored and the untracked file are there" || no "agents apply kept: $(git -C "$R" for-each-ref --format='%(refname)' refs/heads/agent) $(git -C "$R" worktree list)"
# the journal is unreadable (a line that is not JSON): a branch no worktree holds is kept as well
git -C "$R" checkout -q parked; for w in "$T/agent/q1" "$T/agent/i1" "$wo" "$wi"; do git -C "$R" worktree remove --force "$w"; done
printf 'not json\n' >> "$T/s/ref-journal.jsonl"
dry $B prune --agents --dry-run
[ "$rc" = 0 ] && grep -q "^no merged agent/\* branches to prune" "$T/do" && ! grep -q "^  delete local" "$T/do" && grep -q "^  kept agent/m1: its journal does not reach .*is not JSON" "$T/do" && [ "$s0" = "$s1" ] \
  && ok "--agents --dry-run with a journal that has a line that is not JSON: nothing is planned, each branch is kept with the reason" || no "agents, unreadable journal, dry run: rc=$rc $(cat "$T/do" "$T/de")"
before=$(git -C "$R" for-each-ref | md5sum)
out=$($B prune --agents 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$before" = "$(git -C "$R" for-each-ref | md5sum)" ] && ! grep -q "^deleted" <<<"$out" && ok "--agents with that journal deletes nothing" || no "agents, unreadable journal: rc=$rc $out"
out=$($B prune 2>&1); grep -q "delete local agent/m1 " <<<"$out" && grep -q "journal: no step will be journaled for agent/m1" <<<"$out" && ok "the gated prune still plans those branches, with the note that the journal does not lead to them" || no "gated prune, unreadable journal: $out"

# ---------------------------------------------------------------------------------------------------------------------------- feature-runs-open
# feature finish refuses while a run of the feature is open: the code carries the count and the names of the runs (a digest of them in the contract line), the message names three
# and +N, the older text (each run with the command that closes it) follows as `more:`; a dry run lists the refusal and goes on to the checks after it
mkproj orun with-origin
jq '.models = {provider: {local: "claude-code", cloud: "claude-platform"}}' "$T/c/projects/orun.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/orun.json"
export QARGI_RUN_TMP=$T/shm; mkdir -p "$T/shm" "$T/scr"
mkrun() { $DA local prepare --repo "$R" --base "$2" --slug "$1" --scratch "$T/scr" | sed -n 's/^RUN=//p'; }
$F start fa >/dev/null 2>&1; task t1 feature/fa; $F merge fa agent/t1 >/dev/null 2>&1; $F verify fa >/dev/null 2>&1
rm1=$(mkrun r1 feature/fa); rm2=$(mkrun r2 feature/fa); rm3=$(mkrun r3 feature/fa); rm4=$(mkrun r4 feature/fa)
refs0=$(git -C "$R" for-each-ref | md5sum)
out=$($F finish fa 2>&1); rc=$?
c=$(grep -m1 '^qargi-refusal/1 ' <<<"$out")
[ "$rc" = 1 ] && [ "$(head -n 1 <<<"$out")" = "$c" ] && grep -q '"code":"feature-runs-open","exit":1,"verb":"feature finish"' <<<"$c" && grep -Eq '"detail":"count=4 runs=sha256:[0-9a-f]{12}"' <<<"$c" && ! grep -q "$T/scr" <<<"$c" \
  && grep -Eq "^qargi: refused \[feature-runs-open\] 4 run\(s\) of this feature are still open: [^ ,]+, [^ ,]+, [^ ,]+ \+1$" <<<"$out" && grep -q "^  more: feature fa has 4 open run(s); finish it when they are taken in or dropped:" <<<"$out" \
  && grep -q "^  $rm1 (build r1): prepared, not verified$" <<<"$out" && [ "$(grep -c '^    close it: ' <<<"$out")" = 4 ] && grep -q "Nothing was changed" <<<"$out" && [ "$refs0" = "$(git -C "$R" for-each-ref | md5sum)" ] \
  && ok "feature finish with four runs open: feature-runs-open, the contract line first with the count and a digest of the names, three names and +1, each run with the way to close it" || no "feature-runs-open: rc=$rc $out"
dry $F finish fa --dry-run
[ "$rc" = 1 ] && contract | grep -Eq '"code":"feature-runs-open","exit":1,"verb":"feature finish".*"detail":"dry=1 count=4 runs=sha256:[0-9a-f]{12}"' && grep -q "^plan token: " "$T/do" && grep -q "^invalidated by: " "$T/do" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] \
  && ok "feature finish --dry-run with runs open: the refusal is listed with dry=1 and the plan goes on to its token, 1 would refuse, exit 1, nothing changed" || no "feature-runs-open dry run: rc=$rc $(cat "$T/do" "$T/de")"
ft=$(tok < "$T/do"); dry $F finish fa --dry-run --plan "$ft"
[ "$rc" = 1 ] && contract | grep -Eq '"code":"feature-runs-open".*"detail":"dry=1 count=4 ' && ! grep -q "is the one shown" "$T/do" && grep -q "^not run in a dry run: the finish itself" "$T/do" && [ "$(lastline)" = "dry-run: 1 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] \
  && ok "feature finish --dry-run --plan with a refusal counted: it does not say the apply would go on" || no "dry run with the token and a refusal: rc=$rc $(cat "$T/do" "$T/de")"
# a feature with no passing run and a run open: both are listed, 2 would refuse
$F start fb >/dev/null 2>&1; task t2 feature/fb; $F merge fb agent/t2 >/dev/null 2>&1; rm5=$(mkrun r5 feature/fb)
dry $F finish fb --dry-run
[ "$rc" = 1 ] && contract | grep -Eq '"code":"feature-runs-open".*"detail":"dry=1 count=1 runs=sha256:' && grep -q "the whole suite has no passing run at the head of feature/fb" "$T/de" && [ "$(lastline)" = "dry-run: 2 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] \
  && ok "an open run and a feature with no passing run: both are listed, 2 would refuse" || no "feature-runs-open and no passing run: rc=$rc $(cat "$T/do" "$T/de")"
for r in "$rm1" "$rm2" "$rm3" "$rm4" "$rm5"; do $DA local clean "$r" --discard >/dev/null 2>&1; done
dry $F finish fa --dry-run
[ "$rc" = 0 ] && ! grep -q "feature-runs-open" "$T/de" && [ "$(lastline)" = "dry-run: 0 would refuse; nothing was changed" ] && [ "$s0" = "$s1" ] && ok "with every run cleaned the dry run has nothing to refuse" || no "no run open, dry run: rc=$rc $(cat "$T/do" "$T/de")"
exit $fail
