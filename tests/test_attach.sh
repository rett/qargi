#!/usr/bin/env bash
# qargi project attach: reads an existing repository, changes nothing in it, stores the answers only after approval.
# Run: tests/test_attach.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c"
G="git -c user.name=t -c user.email=t@example.net"
R=$T/repo; git init -q -b main "$R"
printf 'test:\n\t@true\n' > "$R/Makefile"; echo 1.2.3 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n' > "$R/CHANGELOG.md"
$G -C "$R" add -A && $G -C "$R" commit -q -m one && git -C "$R" tag v1.2.3 && git -C "$R" remote add origin git@github.com:acme/Widget-Tool.git
before=$(git -C "$R" status --porcelain; git -C "$R" for-each-ref; find "$R" -path "$R/.git" -prune -o -type f -print | sort | xargs cat | sha256sum)

out=$($DA project attach "$R" 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
[ -n "$tok" ] && grep -q "test command: make test" <<<"$out" && grep -q "version: VERSION 1.2.3" <<<"$out" && grep -q "(v<semver>)" <<<"$out" && ok "attach reads the test command, version and tag pattern" || no "detect: $out"
grep -q '"url": "https://github.com/acme/Widget-Tool"' <<<"$out" && grep -q '"project": "widgettool"' <<<"$out" && ok "the remote becomes an https URL and the name a project token" || no "answers: $out"
grep -q -- "- branch: develop" <<<"$out" && grep -q -- "- file: CONTRIBUTING.md" <<<"$out" && ! grep -q -- "- file: CHANGELOG.md" <<<"$out" && ok "the gaps name what is missing and not what is there" || no "gaps: $out"
[ ! -e "$T/c/projects/widgettool.json" ] && ok "showing the plan stores nothing" || no "stored without approval"
$DA project attach "$R" --plan deadbeef0000 --approved go >/dev/null 2>&1 && no "a wrong plan token was accepted" || ok "a wrong plan token is refused"
$DA project attach "$R" --plan "$tok" --approved "go ahead" >/dev/null 2>&1 && jq -e '.project == "widgettool" and .methodology == "gitflow" and .repo.path != ""' "$T/c/projects/widgettool.json" >/dev/null && ok "with the token and an approval the answers are stored" || no "store: $($DA project attach "$R" --plan "$tok" --approved x 2>&1)"
[ "$(stat -c %a "$T/c/projects/widgettool.json")" = 600 ] && ok "the stored file is private" || no "mode"
$DA project attach "$R" --plan "$tok" --approved "go ahead" >/dev/null 2>&1 && no "an existing project was replaced" || ok "an existing project is not replaced without --force"
after=$(git -C "$R" status --porcelain; git -C "$R" for-each-ref; find "$R" -path "$R/.git" -prune -o -type f -print | sort | xargs cat | sha256sum)
[ "$before" = "$after" ] && ok "the repository is exactly as it was" || no "the repository changed"
$DA project show widgettool >/dev/null 2>&1 && $DA project validate widgettool >/dev/null 2>&1 && ok "the stored answers validate" || no "validate"

# no remote, no tests: it asks instead of guessing
N=$T/bare; git init -q -b trunk "$N"; $G -C "$N" commit -q --allow-empty -m x
out=$($DA project attach "$N" --name plain 2>&1)
grep -q "repo.url: the repository has no origin remote" <<<"$out" && grep -q "test_command: no test command was recognised" <<<"$out" && ok "what it cannot determine becomes a question" || no "questions: $out"
tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA project attach "$N" --name plain --plan "$tok" --approved go >/dev/null 2>&1 && no "stored with the placeholder URL" || ok "it will not store a placeholder repository URL"
out=$($DA project attach "$N" --name plain --url https://github.com/acme/plain 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA project attach "$N" --name plain --url https://github.com/acme/plain --plan "$tok" --approved go >/dev/null 2>&1 && ok "--url supplies the missing remote" || no "url"
$DA project attach "$T" >/dev/null 2>&1 && no "a directory that is not a repository was attached" || ok "a directory that is not a repository is refused"
rm -rf "$T"
exit $fail
