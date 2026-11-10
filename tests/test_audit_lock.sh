#!/usr/bin/env bash
# The audit log is appended to by lib.sh (audit_log) and by three python writers (lib/procenv.py audit, lib/transfer.py audit, the pack
# library's audit). Each takes an exclusive flock on audit.log.lock beside the log and writes one whole line under it. Checked here:
#   1. 20 processes (shell and the three python writers mixed) x 20 lines of 9000 bytes: 400 whole lines, each parses, in the one field order,
#      none lost or cut or run into another (the lines are long, because a long line is where an unlocked stdio append splits).
#   2. a writer waits while the lock is held: nothing is written until it is let go, then every line is there (this fails without the lock).
#   3. a lock that cannot be had (the lock path is a directory; no flock command; no fcntl) ends the writer with a message naming the cause
#      and writes nothing.
# Offline. Run: tests/test_audit_lock.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
mkdir -p "$HOME" "$T/c" "$T/s"
trap 'rm -rf "$T" "$HERMETIC"' EXIT
LOG=$T/s/audit.log

# one write by the writer KIND (sh, procenv, transfer, library) of the line VERB with DETAIL
PYW='
import sys
sys.path[:0] = [sys.argv[1] + "/lib", sys.argv[1] + "/lib/conformance"]
kind, verb, detail = sys.argv[2:5]
if kind == "nofcntl":
    sys.modules["fcntl"] = None
    kind = "procenv"
if kind == "procenv":
    import procenv; procenv.audit(verb, detail)
elif kind == "transfer":
    import transfer; transfer.audit(verb, detail)
else:
    from conformance import library; library.audit(verb, detail, {})
'
write_line() { # KIND VERB DETAIL
  case $1 in
    sh) bash -c '. "$1/lib/lib.sh"; audit_log "$2" "$3"' _ "$SRC" "$2" "$3";;
    *) python3 -I -c "$PYW" "$SRC" "$1" "$2" "$3";;
  esac
}
kinds=(sh procenv transfer library)
pad=$(head -c 9000 /dev/zero | tr '\0' x)

# --- 1. the same log from 20 processes, 20 lines each
for i in $(seq 0 19); do
  (
    kind=${kinds[$((i % 4))]}
    for j in $(seq 0 19); do write_line "$kind" "w$i-$j" "$pad" || exit 1; done
  ) &
done
wait
res=$(python3 -I - "$LOG" "$pad" <<'EOF'
import json, sys
log, pad = sys.argv[1:3]
raw = open(log, "rb").read()
bad, seen = [], set()
if not raw.endswith(b"\n"):
    bad.append("the log does not end in a newline")
lines = raw.decode().split("\n")[:-1]
for n, l in enumerate(lines, 1):
    try:
        row = json.loads(l)
    except ValueError:
        bad.append("line %d does not parse" % n)
        continue
    if list(row) != ["ts", "verb", "detail", "asked", "approved", "nested"] or row["detail"] != pad or row["nested"] is not False:
        bad.append("line %d is not whole: %s" % (n, list(row)))
    seen.add(row["verb"])
want = {"w%d-%d" % (i, j) for i in range(20) for j in range(20)}
if len(lines) != 400 or seen != want:
    bad.append("%d lines, %d distinct (want 400, 400); missing %d" % (len(lines), len(seen), len(want - seen)))
print("; ".join(bad[:5]) or "whole")
EOF
)
[ "$res" = whole ] && ok "20 mixed writers x 20 long lines: 400 whole, parseable lines in one field order, none lost" || no "concurrent audit writes: $res"
[ "$(stat -c %a "$LOG")" = 600 ] && [ -e "$LOG.lock" ] && ok "the log is mode 600 and the lock file audit.log.lock is beside it" || no "log mode $(stat -c %a "$LOG"), lock file $([ -e "$LOG.lock" ] && echo present || echo missing)"

# --- 2. the lock is taken: a held lock keeps every writer from writing
rm -f "$LOG"
( flock 9; : > "$T/held"; sleep 3 ) 9> "$LOG.lock" &
holder=$!
for _ in $(seq 100); do [ -e "$T/held" ] && break; sleep 0.1; done
for k in "${kinds[@]}"; do write_line "$k" "held-$k" d & done
sleep 1.2
before=$([ -e "$LOG" ] && wc -l < "$LOG" || echo 0)
wait "$holder"; wait
after=$(wc -l < "$LOG")
[ "$before" = 0 ] && [ "$after" = 4 ] && ok "all four writers wait for a held lock, then each writes its line" || no "lines while the lock was held: $before, after it was let go: $after (want 0, 4)"

# --- 3. a lock that cannot be had: a message naming the cause, nothing written
rm -rf "$LOG" "$LOG.lock"; mkdir "$LOG.lock"
for k in "${kinds[@]}"; do
  out=$(write_line "$k" "x" d 2>&1); rc=$?
  [ "$rc" != 0 ] && grep -q "audit.log.lock" <<<"$out" && [ ! -s "$LOG" ] && ok "$k: a lock that cannot be opened ends the writer, naming it, and writes nothing" || no "$k with a directory for a lock: exit $rc, output '$out', log $([ -s "$LOG" ] && echo written || echo empty)"
done
rmdir "$LOG.lock"
nb=$T/nobin; mkdir "$nb"
for c in jq date chmod; do ln -s "$(command -v "$c")" "$nb/$c"; done
out=$(bash -c '. "$1/lib/lib.sh"; PATH=$2; audit_log x d' _ "$SRC" "$nb" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "flock command (util-linux) is not installed" <<<"$out" && [ ! -s "$LOG" ] && ok "sh: no flock command ends the writer, saying so, and writes nothing" || no "sh without flock: exit $rc, output '$out', log $([ -s "$LOG" ] && echo written || echo empty)"
out=$(write_line nofcntl x d 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "fcntl" <<<"$out" && [ ! -s "$LOG" ] && ok "python: no fcntl ends the writer, saying so, and writes nothing" || no "python without fcntl: exit $rc, output '$out', log $([ -s "$LOG" ] && echo written || echo empty)"

[ "$fail" = 0 ] && echo "audit lock: all ok" || echo "audit lock: FAILED"
exit "$fail"
