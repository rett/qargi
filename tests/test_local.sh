#!/usr/bin/env bash
# The local never-push barrier on a throwaway repository and remote. Run: tests/test_local.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
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
[ "$(jq -r 'select(.slug=="demo") | .run' "$T/s/local-runs.jsonl")" = "$RUN" ] && [ "$(wc -l < "$T/s/local-runs.jsonl")" = 2 ] && ok "prepare registers each run (one line, run directory, slug, ability, base, start)" || no "registry: $(cat "$T/s/local-runs.jsonl")"
grep -q "$T/r" "$T/s/local-runs.jsonl" && no "the registry names the repository path" || ok "the registry holds no repository path"
# clean: a collected, verified run goes away with its temporary directory; anything else is refused
git init -q -b main "$T/r2" && git -C "$T/r2" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c1 --scratch "$T"); C1=$(sed -n 's/^RUN=//p' <<<"$out"); TM=$(sed -n 's/^TMP=//p' <<<"$out")
[ -d "$TM" ] && [ "$(cat "$C1/tmpdir")" = "$TM" ] && ok "prepare makes a private temporary directory and prints it as TMP" || no "TMP: $out"
case $TM in "$T"/qargi-run.*) ok "it is under QARGI_RUN_TMP (tmpfs by default)";; "$C1"/tmp) ok "it is inside the run when there is no tmpfs";; *) no "TMP place $TM";; esac
touch "$TM/sandbox-file"; mkdir -p "$TM/a/b"
./bin/qargi local clean "$C1" >/dev/null 2>&1 && no "clean removed a run with no manifest" || ok "clean refuses a run whose output has no manifest"
[ -d "$C1" ] && [ -d "$TM" ] && ok "and removes nothing" || no "refused clean removed things"
echo '{}' > "$C1/out/manifest.json"
git -C "$T/r2" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m moved
./bin/qargi local clean "$C1" >/dev/null 2>&1 && no "clean removed a run whose refs changed" || ok "clean refuses when the repository's refs changed (evidence)"
[ -d "$C1" ] && ok "the evidence stays" || no "evidence removed"
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c2 --scratch "$T"); C2=$(sed -n 's/^RUN=//p' <<<"$out"); TM2=$(sed -n 's/^TMP=//p' <<<"$out")
echo '{}' > "$C2/out/p--manifest.json"; touch "$TM2/leftover"
./bin/qargi local clean "$C2" >/dev/null 2>&1 && [ ! -e "$C2" ] && [ ! -e "$TM2" ] && ok "clean removes the run and its temporary directory" || no "clean: $C2 $TM2"
[ -d "$TM" ] && ok "another run's temporary directory is untouched" || no "touched another run's tmp"
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c3 --scratch "$T"); C3=$(sed -n 's/^RUN=//p' <<<"$out")
./bin/qargi local clean "$C3" --discard >/dev/null 2>&1 && [ ! -e "$C3" ] && ok "--discard cleans a run that produced no manifest" || no "discard"
./bin/qargi local clean "$T" >/dev/null 2>&1 && no "clean accepted a directory that is not a run" || ok "clean refuses a directory that prepare did not make"
rm -rf "$C1" "$TM"
exit $fail
