#!/usr/bin/env bash
# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
. tests/hermetic.sh
T=$(mktemp -d)
for _ in $(seq 1 50); do [ -e "$T/ready" ] && break; sleep 0.1; done
pgrep -f "uniq-$$"   # hermetic: allow pgrep (unique to this process)
# a path in a comment is not code: /tmp/x
ls "$T"/tmp
out=$(timeout 300 work)
echo "a sleep inside a quoted command: sleep 3"
