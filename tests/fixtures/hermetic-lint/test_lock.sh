#!/usr/bin/env bash
# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
. tests/hermetic.sh
flock /var/lock/x true
echo "$XDG_RUNTIME_DIR"
