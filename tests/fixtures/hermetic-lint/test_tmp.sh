#!/usr/bin/env bash
# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
. tests/hermetic.sh
cd /tmp && ls
ls /dev/shm/x
ls /run/user/1000
