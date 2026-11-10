#!/usr/bin/env bash
# qargi canon check|plan|apply when a store cannot be listed: an unreachable store is reported as "unreachable: <reason>" and is never
# taken for an empty one (nothing is advised, planned or written from it); a project with no store recorded checks clean; a reachable
# empty store is still an empty store. Hermetic, offline: a fake `ant` whose list fails or succeeds as FAKE/mode says.
# Run: tests/test_canon_reach.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$FAKE"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
echo "$*" >> "$FAKE/calls"
case $1 in
  auth) exit 0;;
  beta:memory-stores:memories)
    if [ "$2" = list ]; then
      if [ "$(cat "$FAKE/mode")" = fail ]; then printf '\nError: 403 forbidden for this key\nsecond line\n' >&2; exit 1; fi
      if [ "$(cat "$FAKE/mode")" = silent ]; then exit 3; fi
      if [ "$(cat "$FAKE/mode")" = junk ]; then echo '{"type":"memory","id":"m1","path":"/junk.md","content":"x","content_sha256":"0"}'; fi
      exit 0
    fi
    exit 0;;
  *) echo '{}';;
esac
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

role='{"base":"main","push":{"mode":"none"},"model":"claude-sonnet-5-5","effort":"high","apt":[],"skills":[]}'
jq -n --argjson r "$role" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",long_lived:["main"]},
  roles:{build:$r},memory:{memory_store:"memstore_01",reference_store:"memstore_02"},budget_cents:500}' > "$T/c/projects/alpha.json"
jq -n --argjson r "$role" '{schema:1,project:"solo",repo:{url:"https://github.com/example/solo",long_lived:["main"]},
  roles:{build:$r},budget_cents:500}' > "$T/c/projects/solo.json"

echo fail > "$FAKE/mode"; : > "$FAKE/calls"
out=$(bin/qargi canon check alpha 2>&1); rc=$?
[ "$rc" = 1 ] && ok "check: exit 1 when the stores cannot be listed" || no "check exit $rc: $out"
[ "$(grep -c '^unreachable: Error: 403 forbidden for this key$' <<<"$out")" = 2 ] \
  && ok "check: one 'unreachable: <reason>' line for each store, the first line of the error" || no "check lines: $out"
grep -qi 'canon plan\|empty store\|FAIL /CANON.md' <<<"$out" && no "check advised a plan for an unreachable store: $out" || ok "check: no plan advised, no empty store reported"

out=$(bin/qargi canon plan alpha 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q '^unreachable: Error: 403' <<<"$out" && ! grep -qE '^  (create|update|move|mark)' <<<"$out" \
  && ok "plan: refuses, names the reason, plans nothing" || no "plan (rc=$rc): $out"

out=$(bin/qargi canon apply alpha --plan x --approved go 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q '^unreachable: Error: 403' <<<"$out" && ok "apply: refuses with the reason" || no "apply (rc=$rc): $out"
grep -qE 'memories (create|update)|memory-versions' "$FAKE/calls" && no "something was written: $(cat "$FAKE/calls")" || ok "apply: nothing was written"

out=$(bin/qargi canon seed-role alpha --role build --approved go 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q 'unreachable' <<<"$out" && ! grep -qE 'memories (create|update)' "$FAKE/calls" \
  && ok "seed-role: refuses and writes nothing" || no "seed-role (rc=$rc): $out"

# a list that fails with no error text is still unreachable, and the reason is the status in generic words (no vendor tool is named there)
echo silent > "$FAKE/mode"
out=$(bin/qargi canon check alpha --kind memory 2>&1); rc=$?
[ "$rc" = 1 ] && [ "$(grep -c '^unreachable: the store list failed (status 3)$' <<<"$out")" = 1 ] \
  && ok "check: a silent failure is 'unreachable: the store list failed (status 3)'" || no "silent (rc=$rc): $out"

# a project with no store recorded checks clean (nothing to reach)
out=$(bin/qargi canon check solo 2>&1); rc=$?
[ "$rc" = 0 ] && grep -qF 'memory: no store recorded' <<<"$out" && ! grep -q unreachable <<<"$out" \
  && ok "a local-only project checks clean" || no "solo (rc=$rc): $out"

# a store that lists fine and is empty is an empty store: the plan is advised
echo ok > "$FAKE/mode"
out=$(bin/qargi canon check alpha --kind memory 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q 'canon plan' <<<"$out" && ! grep -q unreachable <<<"$out" \
  && ok "a reachable empty store still reports the plan" || no "empty (rc=$rc): $out"

# no temporary directory is left behind: plan, apply and a failing plan each leave TMPDIR as they found it
mkdir -p "$T/tmp"
left() { find "$T/tmp" -mindepth 1 | sort | head -5 | tr '\n' ' '; }
out=$(TMPDIR=$T/tmp bin/qargi canon plan alpha 2>&1); rc=$?
tok=$(sed -n 's/^plan token: \([0-9a-f]*\) .*/\1/p' <<<"$out")
[ "$rc" = 0 ] && [ -n "$tok" ] && [ -z "$(left)" ] && ok "plan: succeeds and leaves TMPDIR empty" || no "plan tmp (rc=$rc, left: $(left)): $out"
out=$(TMPDIR=$T/tmp bin/qargi canon apply alpha --plan "$tok" --approved go 2>&1); rc=$?
[ "$rc" = 0 ] && [ -z "$(left)" ] && ok "apply: succeeds and leaves TMPDIR empty" || no "apply tmp (rc=$rc, left: $(left)): $out"
echo junk > "$FAKE/mode"
out=$(TMPDIR=$T/tmp bin/qargi canon apply alpha --plan x --approved go 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q 'unrecognised layout' <<<"$out" && [ -z "$(left)" ] \
  && ok "a failing plan leaves TMPDIR empty" || no "failing plan tmp (rc=$rc, left: $(left)): $out"
echo ok > "$FAKE/mode"
out=$(TMPDIR=$T/tmp bin/qargi canon plan solo 2>&1); rc=$?
[ -z "$(left)" ] && ok "a project with no store: nothing left in TMPDIR" || no "solo tmp (rc=$rc, left: $(left)): $out"

# a project with no store recorded: plan and apply stop with the reason and print no token, no jq error
# (jq starts each of its errors with `jq:`; the bare name could sit in a random temporary path in the output)
for v in "plan solo" "apply solo --plan x --approved go"; do
  out=$(bin/qargi canon $v 2>&1); rc=$?
  [ "$rc" != 0 ] && grep -qF 'no memory store recorded' <<<"$out" && ! grep -qiE 'plan token|jq:|Could not open' <<<"$out" \
    && ok "${v%% *}: a project with no store stops with 'no store recorded', no token" || no "solo $v (rc=$rc): $out"
done
out=$(bin/qargi canon plan solo --kind reference 2>&1); rc=$?
[ "$rc" != 0 ] && grep -qF 'no reference store recorded' <<<"$out" && ! grep -q 'plan token' <<<"$out" \
  && ok "plan --kind reference: the same" || no "solo reference (rc=$rc): $out"

# each store is read once per plan, and its plan is built once (one list call per kind and probe)
echo ok > "$FAKE/mode"; : > "$FAKE/calls"
bin/qargi canon plan alpha >/dev/null 2>&1
n=$(grep -c 'memories list' "$FAKE/calls")
[ "$n" = 4 ] && ok "plan: one probe by reach_all and one by the plan, for each of the two stores" || no "plan listed the stores $n time(s), want 4: $(cat "$FAKE/calls")"

exit $fail
