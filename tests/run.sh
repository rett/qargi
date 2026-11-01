#!/usr/bin/env bash
# Runs every test and the linter. No API access, no private data.
set -u
# hermetic: nothing of the caller's cloud binding or qargi setup reaches the tests, and HOME is a fresh directory
# (each test also scrubs itself, see tests/hermetic.sh and tests/hermetic.py)
for _v in $(compgen -e); do case $_v in ANTHROPIC_*|QARGI_*) unset "$_v";; esac; done
HOME=$(mktemp -d); export HOME
trap 'rm -rf "$HOME"' EXIT
cd "$(dirname "$0")/.." || exit 1
rc=0
t0=$SECONDS
run() { local s=$SECONDS; echo "== $*"; if out=$("$@" 2>&1); then echo "$out" | tail -3; else echo "$out" | tail -20; echo "FAILED: $*"; rc=1; fi; echo "   ($((SECONDS - s))s)"; }
run python3 tests/test_canon.py
run python3 tests/test_tiers.py
run python3 tests/test_tierplan.py
run bash tests/test_tier_hook.sh
run bash tests/test_tier_packet.sh
run python3 tests/test_help.py
run python3 tests/test_membackend.py
run python3 tests/test_transfer.py
run python3 tests/test_discover.py
run bash tests/test_watch.sh
run bash tests/test_session.sh
run python3 tests/test_report.py
run python3 tests/test_noticed.py
run python3 tests/test_cloud.py
run python3 tests/test_upgrade.py
run python3 tests/test_supervise.py
run bash tests/test_prompt.sh
run python3 tests/test_guard.py
run bash tests/test_agent.sh
run bash tests/test_role.sh
run bash tests/test_methodology.sh
run bash tests/test_attach.sh
run bash tests/test_new.sh
run bash tests/test_flow.sh
run bash tests/test_verify_env.sh
run bash tests/test_release_preflight.sh
run python3 tests/test_migrate.py
run python3 tests/test_home.py
run python3 tests/test_migrate_home.py
run bash tests/test_project.sh
run bash tests/test_local.sh
run bash tests/test_cred.sh
run bash tests/test_packs.sh
run bash tests/test_packs_seed.sh
run bash tests/test_packs_claude.sh
run bash tests/test_packs_claude_hostile.sh
run bash tests/test_review.sh
run bash tests/test_marshal.sh
run bash tests/test_marshal_flow.sh
run bash tests/test_marshal_hook.sh
run bash tests/test_journal.sh
run bash tests/test_team.sh
run bash tests/test_leadcred.sh
run bash tests/test_lead.sh
run python3 tests/role_seed_sim.py shared
run python3 tests/role_seed_sim.py build
run python3 tests/role_seed_sim.py write
run python3 tests/role_seed_sim.py review
run python3 tests/role_seed_sim.py test
run shellcheck -x -S warning lib/*.sh bin/qargi install.sh tests/*.sh
echo "total: $((SECONDS - t0))s ($([ $rc = 0 ] && echo passed || echo FAILED))"
exit $rc
