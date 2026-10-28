#!/usr/bin/env bash
# The local never-push barrier on a throwaway repository and remote. Run: tests/test_local.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0
git init -q -b main "$T/r" && git -C "$T/r" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
git init -q --bare "$T/remote.git" && git -C "$T/r" remote add origin "$T/remote.git" && git -C "$T/r" push -q origin main
eval "$(./bin/qargi local prepare --repo "$T/r" --base main --slug demo --scratch "$T" | sed 's/^/export /')"
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
[ "$($GIT -C "$CLONE" branch --show-current)" = agent/demo ] && ok "clone is on agent/demo" || no "branch"
echo x > "$CLONE/f"; $GIT -C "$CLONE" add f && $GIT -C "$CLONE" commit -q -m work && ok "commit through the wrapper"
[ "$($GIT -C "$CLONE" log -1 --format=%an)" = qargi ] && ok "author is qargi" || no "author"
$GIT -C "$CLONE" push origin agent/demo >/dev/null 2>&1 && no "git push origin succeeded" || ok "git push origin fails"
git -C "$CLONE" remote -v | grep -q "$T/r" && no "the clone knows the real repository" || ok "the clone does not know the real repository path"
./bin/qargi local verify "$RUN" >/dev/null 2>&1 && ok "verify passes after a clean run" || no "verify clean"
[ "$(cat "$RUN/ability")" = build ] && ok "the run records its ability (build by default)" || no "ability file"
R2=$(./bin/qargi local prepare --repo "$T/r" --base main --slug rev --scratch "$T" --ability review | sed -n 's/^RUN=//p')
[ "$(cat "$R2/ability")" = review ] && ok "--ability review is recorded for the guard" || no "review ability"
./bin/qargi local prepare --repo "$T/r" --base main --slug bad --scratch "$T" --ability deploy >/dev/null 2>&1 && no "an unknown ability was accepted" || ok "an unknown ability is refused"
git -C "$CLONE" push -q "$T/remote.git" agent/demo 2>/dev/null   # a bypass with plain git
./bin/qargi local verify "$RUN" >/dev/null 2>&1 && no "verify missed a push to the remote" || ok "verify catches a push to the remote"
exit $fail
