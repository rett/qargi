#!/usr/bin/env bash
# `qargi project profile check [NAME] [--profile FILE]`: the profile of a repository still carries the shipped template header (exit 1), a gate command
# the repository does not know is a warning (exit 0), and `project validate` prints the header finding as a WARN line. Offline, hermetic.
# Run: tests/test_project_profile.sh
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export QARGI_CONF=$T/c QARGI_STATE=$T/s HOME=$T/h
mkdir -p "$T/c/projects" "$T/c/profiles" "$T/s" "$T/h"
DA=$ROOT/bin/qargi
R=$T/acme-repo; PF=$T/c/profiles/acme-repo.md
mkdir -p "$R"
jq -n --arg r "$R" '{schema:1,project:"acme",repo:{url:"https://github.com/example/acme-repo",path:$r,long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/acme.json"
printf 'lint:\n\techo lint\ntest build:\n\techo t\n.PHONY: lint test build\n' > "$R/Makefile"
printf '# acme\n\nRun the suite with `bash tests/run.sh`.\n' > "$R/CLAUDE.md"
snap() { find "$@" -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum | sha256sum; }

# --- no profile is fine
out=$($DA project profile check acme 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^no profile at $PF" <<<"$out"; } && ok "no profile: said, exit 0" || no "no profile (rc=$rc): $out"

# --- the shipped example, copied and not adapted
cp examples/myproject/profile.md "$PF"
before=$(snap "$T/c" "$R")
out=$($DA project profile check acme 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q '^FAIL line 1 still carries the shipped template header: "# Example profile' <<<"$out" && grep -q '^FAIL line 3 still carries the shipped template header: "Copy to' <<<"$out"; } \
  && ok "the template header is a finding (both lines named), exit 1" || no "template header (rc=$rc): $out"
[ "$(snap "$T/c" "$R")" = "$before" ] && ok "the check writes nothing" || no "the check changed a file"
out=$($DA project validate acme 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^WARN: the profile $PF still carries the shipped template header" <<<"$out"; } && ok "project validate prints the header finding as a warning (exit 0)" || no "validate (rc=$rc): $out"
out=$($DA project validate "$T/c/projects/acme.json" 2>&1); grep -q "^WARN: the profile .* template header" <<<"$out" && ok "and for an answers file" || no "validate file: $out"

# --- the same profile with the header replaced: its gates are looked up
sed '1,3d' examples/myproject/profile.md | sed '1i # Profile: acme' > "$PF"
out=$($DA project profile check acme 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q "^FAIL" <<<"$out"; } && ok "an adapted profile has no header finding, exit 0" || no "adapted (rc=$rc): $out"
grep -q '^WARN line [0-9]*: gate `make gate-go` is not in the instruction files or the Makefile targets' <<<"$out" && ok "a make target the Makefile lacks is a warning" || no "gate-go: $out"
grep -q 'gate `make lint-sh`' <<<"$out" && ok "another missing target is a warning too" || no "lint-sh: $out"
grep -q 'gate `make lint`\|gate `make build`' <<<"$out" && no "a target the Makefile has was flagged: $out" || ok "make targets the Makefile defines (also in a multi-name rule and in .PHONY) are found"
grep -q "internal/\*\*\|README.md\|gate \`docs/\`" <<<"$out" && no "a path was taken for a command: $out" || ok "paths and globs in backticks are not gate commands"
grep -qE "^[0-9]+ warnings" <<<"$out" && ok "the warnings are counted" || no "count: $out"
out=$($DA project validate acme 2>&1); ! grep -q "^WARN: the profile" <<<"$out" && ok "validate prints no header warning for an adapted profile" || no "validate adapted: $out"

# --- a profile whose gates all exist
cat > "$PF" <<'EOF'
# Profile: acme

## Rules
- Use `make nothing-here` never (not in the gates section, so not looked up).

## Gates by path
- `src/**`: `make lint`, `make test`, `bash tests/run.sh`.
- `docs/`, `README.md`: `make lint`.
- Always: `make lint`.

## Review (coordinator)
- `make missing-target`
EOF
out=$($DA project profile check acme 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^ok   3 gate commands" <<<"$out" && ! grep -q "^WARN" <<<"$out"; } && ok "gates found in the Makefile targets and in CLAUDE.md pass, and only the Gates section is read" || no "all found (rc=$rc): $out"
# a script of the repository counts, and a command in AGENTS.md
mkdir -p "$R/tests/tools"; : > "$R/tests/tools/scrub.sh"
printf '## Gates\n- `tests/tools/scrub.sh` and `gofmt -l .` and `go vet ./...`\n' > "$PF"
printf 'Run `gofmt -l .` before you commit.\n' > "$R/AGENTS.md"
out=$($DA project profile check acme 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'gate `go vet ./...` is not in' <<<"$out" && ! grep -qE 'scrub\.sh|(^|[^[:alnum:]])gofmt([^[:alnum:]]|$)' <<<"$out"; } && ok "a script that exists and a command in AGENTS.md are found; an unknown one is a warning, exit 0" || no "script/agents (rc=$rc): $out"

# --- --profile FILE, the project from the current directory, no project at all
cp examples/myproject/profile.md "$T/other.md"
out=$($DA project profile check acme --profile "$T/other.md" 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q "^profile: $T/other.md" <<<"$out"; } && ok "--profile reads the file given" || no "--profile (rc=$rc): $out"
out=$($DA project profile check --profile "$T/nope.md" acme 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q "no such profile file" <<<"$out"; } && ok "a --profile file that is not there is a usage error (exit 2)" || no "missing --profile (rc=$rc): $out"
cp examples/myproject/profile.md "$PF"
out=$(cd "$R" && $DA project profile check 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q "^profile: $PF (repository acme-repo)" <<<"$out"; } && ok "inside the repository the project may be left out" || no "inferred (rc=$rc): $out"
git init -q -b main "$T/bare-repo"; printf '## Gates\n- `make lint`\n' > "$T/p2.md"; printf 'lint:\n\techo\n' > "$T/bare-repo/Makefile"
out=$(cd "$T/bare-repo" && $DA project profile check --profile "$T/p2.md" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^ok   1 gate commands" <<<"$out"; } && ok "with no project, the repository of the current directory is used" || no "no project (rc=$rc): $out"
out=$(cd "$T" && $DA project profile check --profile "$T/p2.md" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^WARN the repository directory is not known" <<<"$out"; } && ok "outside any repository the gates are not checked, said as a warning" || no "no repo (rc=$rc): $out"

# --- usage errors
$DA project profile >/dev/null 2>&1; [ $? = 2 ] && ok "profile without a verb is a usage error" || no "profile alone"
$DA project profile frob >/dev/null 2>&1; [ $? = 2 ] && ok "an unknown profile verb is a usage error" || no "profile frob"
$DA project profile check --profile >/dev/null 2>&1; [ $? = 2 ] && ok "--profile without a value is a usage error" || no "--profile alone"
$DA project profile check --bogus >/dev/null 2>&1; [ $? = 2 ] && ok "an unknown option is a usage error" || no "--bogus"
$DA project profile check nosuch >/dev/null 2>&1; [ $? -ne 0 ] && ok "a project that is not stored is refused" || no "nosuch"
exit $fail
