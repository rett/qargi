#!/usr/bin/env bash
# qargi project attach: reads an existing repository, changes nothing in it, stores the answers only after approval.
# Run: tests/test_attach.sh
set -u
cd "$(dirname "$0")/.." || exit 1
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

# detection reads the integration branch, not the checked-out working tree
S=$T/feat; git init -q -b master "$S"; mkdir -p "$S/.github/workflows"
printf 'test:\n\t@true\n' > "$S/Makefile"; echo 0.1.0 > "$S/VERSION"; printf '# Changelog\n\n## [Unreleased]\n' > "$S/CHANGELOG.md"
printf 'on: push\n' > "$S/.github/workflows/ci.yml"
$G -C "$S" add -A && $G -C "$S" commit -q -m base && git -C "$S" branch develop && git -C "$S" checkout -q -b feature/x develop
git -C "$S" remote add origin https://github.com/acme/feat.git
$G -C "$S" rm -q -r .github CHANGELOG.md && $G -C "$S" commit -q -m "drop ci and changelog on the feature"
out=$($DA project attach "$S" 2>&1)
grep -q "^read from: develop (the methodology's integration branch develop" <<<"$out" && grep -q "checked-out branch is feature/x" <<<"$out" && ok "attach says which ref it read" || no "ref: $out"
grep -q "CI workflows: ci.yml" <<<"$out" && ! grep -q -- "- ci:" <<<"$out" && ! grep -q -- "- file: CHANGELOG.md" <<<"$out" && ok "CI and changelog come from develop, not the feature checkout" || no "tree: $out"
printf 'dirty\n' > "$S/Makefile"; out=$($DA project attach "$S" 2>&1)
grep -q "test command: make test" <<<"$out" && ok "uncommitted changes in the working tree are not read" || no "dirty: $out"
git -C "$S" checkout -q -- Makefile
git -C "$S" branch -D develop -q; out=$($DA project attach "$S" 2>&1)
grep -q "^read from: master (the default branch master" <<<"$out" && grep -q -- "- ci:" <<<"$out" || { grep -q "CI workflows: ci.yml" <<<"$out" && grep -q "^read from: master" <<<"$out"; } && ok "without develop it falls back to the default branch" || no "fallback: $out"
git -C "$S" branch develop master

# the remote as read and the normalised url
out=$($DA project attach "$R" 2>&1)
grep -q "remote (origin as read): git@github.com:acme/Widget-Tool.git" <<<"$out" && grep -q "repo.url (normalised to https.*): https://github.com/acme/Widget-Tool$" <<<"$out" && ok "the origin as read and the normalised url are both printed" || no "remote: $out"
git -C "$S" remote set-url origin https://github.com/acme/feat
out=$($DA project attach "$S" 2>&1)
! grep -q "normalised" <<<"$out" && ok "no normalisation note when the origin is already the url" || no "note: $out"

# answers already stored: say so, diff, list missing fields, no plan token; --force keeps what cannot be detected
$DA project template feat | jq '.repo.url = "https://github.com/old/feat" | .repo.long_lived = ["master"] | .roles.build.model = "claude-opus-5-5" | .roles.build.effort = "low"
  | .memory = {memory_store: "memstore_keep", reference_store: "memstore_refkeep"} | .budget_cents = 900 | .cloud = {profile: "keepprof", workspace_id: "wrkspc_keep0123456789"} | .methodology = "gitflow"' > "$T/feat.json"
$DA project init feat --answers "$T/feat.json" >/dev/null 2>&1 || no "init feat"
out=$($DA project attach "$S" 2>&1)
grep -q "^ALREADY STORED" <<<"$out" && grep -q 'repo.url: stored "https://github.com/old/feat", detected "https://github.com/acme/feat"' <<<"$out" && grep -q 'repo.long_lived: stored "master", detected "master,develop"' <<<"$out" && ok "stored answers are announced with a diff of the detected values" || no "diff: $out"
grep -q -- "- test_command" <<<"$out" && ! grep -q "models\|roles.build.model: stored" <<<"$out" && ok "fields the schema wants and the file lacks are listed; undetected ones are not diffed" || no "missing: $out"
! grep -q "^plan token" <<<"$out" && ! grep -q "stored answers would be" <<<"$out" && ok "no plan token for an apply that would be refused" || no "token shown: $out"
before=$(cat "$T/c/projects/feat.json"); $DA project attach "$S" --plan x --approved go >/dev/null 2>&1 && no "applied without --force" || ok "approving without --force is refused"
[ "$before" = "$(cat "$T/c/projects/feat.json")" ] && ok "without --force nothing is stored" || no "stored changed"
out=$($DA project attach "$S" --force 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
[ -n "$tok" ] && grep -q "memstore_keep" <<<"$out" && ok "with --force the plan has a token and keeps the stored values" || no "force plan: $out"
$DA project attach "$S" --force --plan "$tok" --approved go >/dev/null 2>&1 || no "force apply"
jq -e '.roles.build.model == "claude-opus-5-5" and .roles.build.effort == "low" and .memory.memory_store == "memstore_keep" and .memory.reference_store == "memstore_refkeep"
  and .budget_cents == 900 and .cloud.workspace_id == "wrkspc_keep0123456789" and .repo.url == "https://github.com/acme/feat" and .repo.long_lived == ["master","develop"]
  and .test_command == "make test"' "$T/c/projects/feat.json" >/dev/null && ok "--force changes only the detected fields and keeps roles, cloud, memory and budget" || no "forced: $(cat "$T/c/projects/feat.json")"
out=$($DA project attach "$S" 2>&1)
grep -q "no difference" <<<"$out" && ! grep -q "wants and the stored file lacks" <<<"$out" && ok "after --force stored and detected agree" || no "again: $out"
rm -rf "$T"
exit $fail
