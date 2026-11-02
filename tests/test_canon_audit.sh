#!/usr/bin/env bash
# qargi canon audit: who wrote under which role folder. The role of a session comes from its title
# <project>-<role>-..., except for a session of a cloud base (<project>-worker, <project>-reviewer): its title carries the
# base's name, so the role is read from the local session tracker row of that session id. A session with no row, or a row
# without a role, is not attributed (never guessed) and the audit says so once. Hermetic, offline: a fake `ant`.
# Run: tests/test_canon_audit.sh
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

# sessions: id, title, and the writes of each (path, operation)
cat > "$FAKE/titles" <<'EOS'
sesn_1 alpha-worker-fix-parser
sesn_2 alpha-worker-fix-docs
sesn_3 alpha-reviewer-check-it
sesn_4 alpha-worker-no-role
sesn_5 alpha-build-legacy
sesn_6 alpha-reviewer-clean
EOS
cat > "$FAKE/writes" <<'EOS'
sesn_1	/roles/write/notes.md	create
sesn_2	/roles/build/notes.md	create
sesn_3	/roles/build/other.md	update
sesn_4	/roles/build/third.md	create
sesn_5	/roles/write/legacy.md	create
sesn_6	/shared/common.md	create
EOS
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
arg() { local k=$1; shift; while [ $# -gt 0 ]; do [ "$1" = "$k" ] && { echo "$2"; return; }; shift; done; }
case $1 in
  auth) exit 0;;
  beta:sessions)
    [ "$2" = retrieve ] || exit 0
    sid=$(arg --session-id "$@"); jq -nc --arg t "$(awk -v s="$sid" '$1==s {print $2}' "$FAKE/titles")" '{title: $t}';;
  beta:memory-stores:memory-versions)
    while IFS=$'\t' read -r s p o; do
      jq -nc --arg s "$s" --arg p "$p" --arg o "$o" '{created_by: {type: "session_actor", session_id: $s}, path: $p, operation: $o}'
    done < "$FAKE/writes";;
  *) echo '{}';;
esac
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

jq -n '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]},
         write:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  memory:{memory_store:"memstore_01"},budget_cents:500}' > "$T/c/projects/alpha.json"
# the local tracker: rows keyed by session id; sesn_3 has none, sesn_4 has a row without a role
jq -n '{sesn_1: {instance:"alpha-worker", label:"fix-parser", role:"build", profile:"build", model:"m", effort:"high"},
        sesn_2: {instance:"alpha-worker", label:"fix-docs", role:"build", profile:"build", model:"m", effort:"high"},
        sesn_4: {instance:"alpha-worker", label:"no-role"},
        sesn_5: {instance:"alpha-build", label:"legacy"}}' > "$T/s/sessions.json"
before=$(sha256sum "$T/s/sessions.json")

out=$(bin/qargi canon audit alpha --kind memory 2>&1); rc=$?
[ "$rc" = 1 ] && ok "a cross-role write makes the audit exit 1" || no "exit $rc: $out"
grep -qF 'CROSS-ROLE: session sesn_1 (role build) create /roles/write/notes.md' <<<"$out" \
  && ok "a base session is attributed to the role of its tracker row, and its cross-role write is reported" || no "no report for the base session: $out"
grep -q 'sesn_2' <<<"$out" && no "a base session that wrote under its own role was reported: $out" || ok "a base session writing under its own role is not reported"
grep -qF 'CROSS-ROLE: session sesn_5 (role build) create /roles/write/legacy.md' <<<"$out" \
  && ok "a session of a role instance is still attributed by its title" || no "legacy instance: $out"
grep -q 'sesn_3\|sesn_4\|sesn_6' <<<"$out" && no "an unattributed session was reported: $out" || ok "sessions with no tracker row or no role are not reported"
[ "$(grep -c '^NOTE:' <<<"$out")" = 1 ] && grep -qxF 'NOTE: 2 session(s) could not be attributed to a role' <<<"$out" \
  && ok "one NOTE counts the sessions that could not be attributed (sesn_6 wrote only under shared)" || no "note: $out"
[ "$before" = "$(sha256sum "$T/s/sessions.json")" ] && ok "the tracker is not modified" || no "the tracker changed"

# nothing unattributed and nothing crossing: no NOTE, the usual line, exit 0
printf 'sesn_2\t/roles/build/notes.md\tcreate\n' > "$FAKE/writes"
out=$(bin/qargi canon audit alpha --kind memory 2>&1); rc=$?
[ "$rc" = 0 ] && grep -qF 'no cross-role writes found' <<<"$out" && ! grep -q '^NOTE' <<<"$out" && ok "a clean audit has no NOTE" || no "clean audit (rc=$rc): $out"

exit $fail
