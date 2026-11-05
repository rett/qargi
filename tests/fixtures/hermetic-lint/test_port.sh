#!/usr/bin/env bash
# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
. tests/hermetic.sh
curl http://127.0.0.1:8080/x
serve --port 9000
