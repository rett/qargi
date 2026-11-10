#!/usr/bin/env bash
# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
# Seven lines, each a short token asserted absent from output that can hold a random temporary path.
. tests/hermetic.sh
! grep -q "k1" <<<"$out"
grep -qi warn "$T/e" && no "warned"
[ "$(grep -c 'free' "$T/o")" = 0 ]
[ -z "$(cat "$T/o" | grep -i usage)" ]
! grep -qiE 'warn|invalid' "$T/e"
if ! grep -q pf2 "$T/s"; then :; fi
[ "$rc" = 0 ] && ! grep -q 'gate' <<<"$out"
