#!/usr/bin/env bash
# Runs every test and the linter. No API access, no private data.
set -u
cd "$(dirname "$0")/.." || exit 1
rc=0
run() { echo "== $*"; if out=$("$@" 2>&1); then echo "$out" | tail -3; else echo "$out" | tail -20; echo "FAILED: $*"; rc=1; fi; }
run python3 tests/test_canon.py
run bash tests/test_project.sh
run bash tests/test_local.sh
run bash tests/test_cred.sh
run bash tests/test_packs.sh
run bash tests/test_review.sh
run python3 tests/role_seed_sim.py shared
run python3 tests/role_seed_sim.py dev
run python3 tests/role_seed_sim.py docs
run python3 tests/role_seed_sim.py review
run python3 tests/role_seed_sim.py test
run shellcheck -x -S warning lib/*.sh bin/qargi install.sh tests/*.sh
exit $rc
