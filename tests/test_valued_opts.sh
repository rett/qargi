#!/usr/bin/env bash
# A valued option given as the last word ends the command with exit 2 and "OPT needs a value": it never hangs and never
# dies on an unbound variable. Run: tests/test_valued_opts.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
T=$(mktemp -d -p "$HERMETIC"); export TMPDIR=$T
mkdir -p "$QARGI_CONF" "$QARGI_STATE"

# chk "verb words" OPTION: the option is the last word
chk() {
  local out rc
  # shellcheck disable=SC2086
  out=$(timeout 10 ./bin/qargi $1 2>&1 </dev/null); rc=$?
  if [ "$rc" = 2 ] && grep -q -- "${1##* } needs a value" <<<"$out"; then ok "$1"; else no "$1 (exit $rc): $out"; fi
}
for w in "agent for build --surface" "agent for build --roles" "agent for build --model" "agent list --project" "agent add forge --profile" \
  "status --role" "start x --label" "start x --asked" "start x --role" "start x --profile" "track x --session" \
  "upgrade --branch" "upgrade --tag" "upgrade --plan" "provision plan x --model" "provision plan x --role" "provision plan x --memory-store" \
  "credential setup lead-push demo --from-file" "credential setup lead-push demo --asked" \
  "project init demo --answers" "project new demo --dir" "project new demo --provider" "project attach --name" "project attach --plan" \
  "project adopt demo --methodology" "project link demo --plan" "project unlink demo --approved"; do
  chk "$w"
done
exit $fail
