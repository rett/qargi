#!/usr/bin/env bash
# Runs every test and the linter. No API access, no private data.
set -u
cd "$(dirname "$0")/.." || exit 1
rc=0
run() { echo "== $*"; if out=$("$@" 2>&1); then echo "$out" | tail -3; else echo "$out" | tail -20; echo "FAILED: $*"; rc=1; fi; }
run python3 tests/test_canon.py
run python3 tests/test_help.py
run python3 tests/test_membackend.py
run python3 tests/test_transfer.py
run python3 tests/test_discover.py
run bash tests/test_watch.sh
run bash tests/test_session.sh
run python3 tests/test_report.py
run python3 tests/test_noticed.py
run python3 tests/test_cloud.py
run python3 tests/test_supervise.py
run bash tests/test_prompt.sh
run python3 tests/test_guard.py
run bash tests/test_agent.sh
run python3 tests/test_migrate.py
run python3 tests/test_home.py
run python3 tests/test_migrate_home.py
run bash tests/test_project.sh
run bash tests/test_local.sh
run bash tests/test_cred.sh
run bash tests/test_packs.sh
run bash tests/test_review.sh
run bash tests/test_team.sh
run bash tests/test_leadcred.sh
run bash tests/test_lead.sh
run python3 tests/role_seed_sim.py shared
run python3 tests/role_seed_sim.py build
run python3 tests/role_seed_sim.py write
run python3 tests/role_seed_sim.py review
run python3 tests/role_seed_sim.py test
run shellcheck -x -S warning lib/*.sh bin/qargi install.sh tests/*.sh
exit $rc
