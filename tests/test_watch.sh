#!/usr/bin/env bash
# qargi watch: the early budget warning. Offline (fake ant).
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake; mkdir -p "$T/bin" "$FAKE"
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
case $1 in
  auth) exit 0;;
  beta:sessions) jq -nc --arg c "$(cat "$FAKE/cost")" --arg st "$(cat "$FAKE/status")" '{status:$st,usage:{list_cost:{amount:$c}},budget:{max_list_cost:{amount:"3000"}}}';;
esac
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH
echo running > "$FAKE/status"
echo 2550 > "$FAKE/cost"; out=$(timeout 20 bin/qargi watch sesn_x 60 2>&1); rc=$?
[ "$rc" = 4 ] && [ "$out" = "QARGI WATCH sesn_x budget_tight 2550/3000" ] && ok "at 85 percent the watch ends early with the cost and the ceiling" || no "tight: rc=$rc $out"
echo 2000 > "$FAKE/cost"; out=$(timeout 40 bin/qargi watch sesn_x 1 2>&1); rc=$?
[ "$rc" = 2 ] && echo "$out" | grep -q timeout && ok "below the threshold it keeps watching (here until its own timeout)" || no "below: rc=$rc $out"
echo 2900 > "$FAKE/cost"; out=$(timeout 40 bin/qargi watch sesn_x 1 --warn 0 2>&1); rc=$?
[ "$rc" = 2 ] && ok "--warn 0 turns the warning off" || no "warn 0: rc=$rc $out"
echo 2900 > "$FAKE/cost"; out=$(timeout 20 bin/qargi watch sesn_x --warn 95 60 2>&1); rc=$?
[ "$rc" = 4 ] && ok "--warn takes another percent, and the options can come in any order" || no "warn 95: rc=$rc $out"
rm -rf "$T"; exit $fail
