#!/usr/bin/env bash
# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
. tests/hermetic.sh
s=$SECONDS
work
[ $((SECONDS - s)) -lt 5 ]
