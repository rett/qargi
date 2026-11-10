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
# short tokens that are not findings of the absent rule: asserted present, a whole word, an anchor, a character a path does not hold,
# a long or hyphenated token, a variable, a comment, an allowed line
grep -q k1 <<<"$out" && ok "present"
[ "$(grep -c k1 <<<"$out")" = 2 ]
! grep -qw jq <<<"$out"
! grep -q 'jq:' <<<"$out"
! grep -q "^k1$" <<<"$out"
! grep -qE '(^|[^[:alnum:]])fatal' <<<"$out"
! grep -q "unrelated-text" <<<"$out"
! grep -q 'own-g' <<<"$out"
! grep -q "$TOK" "$f"
! grep -qE 'nlline|PWNED_x' <<<"$out"
# ! grep -q k1 <<<"$out"
# hermetic: allow absent (the file is fixed text with no path in it)
! grep -q fake "$f"
