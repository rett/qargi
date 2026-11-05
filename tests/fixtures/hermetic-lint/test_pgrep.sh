#!/usr/bin/env bash
# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
. tests/hermetic.sh
pgrep -f worker
pkill worker
killall worker
