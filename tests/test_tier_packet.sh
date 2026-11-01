#!/usr/bin/env bash
# The memory block `qargi local prepare` prints after TASK-BLOCK PATHS (lib/tiercontext.py packet): the tier summary, the always
# rows of each present tier, the do-not-write rule, the cap of 3000 characters, the warning about a lead's uncommitted repo tier,
# and that a failing or hanging packet never changes prepare's exit status. Offline: a throwaway repository with a committed
# repo tier, a JSONL fixture for the cloud tier. QARGI_HOME, QARGI_CONF and QARGI_STATE are temporary directories.
# Run: tests/test_tier_packet.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
[ -z "${TMP:-}" ] || export TMPDIR=$TMP
T=$(mktemp -d); fail=0
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
SRC=$PWD
export QARGI_HOME=$T/qh QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T QARGI_CANON_FIXTURE_DIR=$T/fix
mkdir -p "$T/c/projects" "$T/s" "$T/fix" "$T/scratch"
G() { git -c user.name=t -c user.email=t@example.net "$@"; }
w() { mkdir -p "$(dirname "$1")"; printf '%s' "$2" > "$1"; }
MARKER=$'# Canon\n\ncanon: 2\nkind: memory\nproject: alpha\nroles: build\n'
row() { printf '\n| %s | a note | %s |' "$1" "${2:-always}"; }
R=$T/r; TIER=$R/qargi/memory
git init -q -b main "$R"
w "$TIER/CANON.md" "$MARKER"; w "$TIER/README.md" $'README-REPO\n'
w "$TIER/shared/INDEX.md" "# Shared$(row s-always.md)$(row s-later.md 'when debugging builds')"$'\n'
w "$TIER/roles/build/INDEX.md" "# Build$(row b-always.md)$(row b-later.md 'when debugging builds')"$'\n'
w "$TIER/roles/build/b-always.md" $'B-ALWAYS-BODY\n'
G -C "$R" add -A && G -C "$R" commit -q -m tier
git init -q --bare "$T/remote.git" && G -C "$R" remote add origin "$T/remote.git" && G -C "$R" push -q origin main
jq -n --arg r "$R" '{project:"alpha", repo:{path:$r}, memory:{memory_store:"memstore_FIX1"}}' > "$T/c/projects/alpha.json"
cloud() { jq -nc --arg p "$1" --arg c "$2" '{type:"memory",id:("m"+$p),path:$p,content:$c,content_sha256:""}' >> "$T/fix/memstore_FIX1.jsonl"; }
cloud /CANON.md "$MARKER"; cloud /README.md $'README-CLOUD\n'; cloud /roles/build/INDEX.md "# Build$(row c-always.md)"$'\n'
slug=0
prep() { # prepare output in $T/out, stderr in $T/err, status in $rc
  slug=$((slug + 1))
  "$SRC/bin/qargi" local prepare --repo "$R" --base main --slug "p$slug" --scratch "$T/scratch" > "$T/out" 2> "$T/err"; rc=$?
}

prep; mem=$(sed '1,/^TASK-BLOCK MEMORY$/d' "$T/out")
[ "$rc" = 0 ] && grep -q '^TASK-BLOCK MEMORY$' "$T/out" && ok "prepare prints a TASK-BLOCK MEMORY block" || no "no block: $(cat "$T/out" "$T/err")"
[ "$(grep -n '^BASE_SHA=' "$T/out" | tail -1 | cut -d: -f1)" -lt "$(grep -n '^TASK-BLOCK MEMORY$' "$T/out" | cut -d: -f1)" ] 2>/dev/null && ok "it comes after the TASK-BLOCK PATHS lines" || no "order"
printf '%s\n' "$mem" | grep -q '^Always-load (role build):$' && ok "the always-load list names the role" || no "heading: $mem"
printf '%s\n' "$mem" | grep -qE '^repo /shared/INDEX\.md: .*s-always\.md' && printf '%s\n' "$mem" | grep -qE '^repo /roles/build/INDEX\.md: .*b-always\.md' \
  && printf '%s\n' "$mem" | grep -qE '^cloud /roles/build/INDEX\.md: .*c-always\.md' && ok "each always row appears as TIER INDEXPATH: row, for every present tier" || no "rows: $mem"
printf '%s\n' "$mem" | grep -qE 'b-later|s-later' && no "a row that is not always was listed" || ok "rows that are not always are left out"
printf '%s\n' "$mem" | grep -qE '^repo +dir +' && printf '%s\n' "$mem" | grep -qE '^cloud +cloud +memstore_FIX1 +present' && ok "the block starts with the tier summary" || no "summary: $mem"
printf '%s\n' "$mem" | grep -qF 'Do not write any tier: propose new or changed notes in your report; the lead files them.' && ok "it tells the member not to write any tier" || no "rule line"
printf '%s' "$mem" | grep -q 'B-ALWAYS-BODY' && no "a note body is in the packet" || ok "only the rows are in the packet, not the notes"
RUN=$(sed -n 's/^RUN=//p' "$T/out" | head -1)
grep -rqF 'Always-load' "$RUN" 2>/dev/null && no "the packet was stored in the run directory" || ok "the packet is printed, never stored"
! grep -q 'WARNING: the repo tier' "$T/out" "$T/err" && ok "a clean checkout gives no warning" || no "warned on a clean checkout"

# the repo tier of the packet is the clone's committed copy; the lead's uncommitted edit is warned about
w "$TIER/roles/build/INDEX.md" "# Build$(row b-always.md)$(row uncommitted.md)"$'\n'
w "$TIER/roles/build/new.md" $'x\n'
n=$(G -C "$R" status --porcelain --untracked-files=all -- qargi/memory | wc -l)
prep; mem=$(sed '1,/^TASK-BLOCK MEMORY$/d' "$T/out")
printf '%s' "$mem" | grep -q 'uncommitted\.md' && no "the lead's uncommitted row leaked into the packet" || ok "the packet shows the committed copy, not the lead's working tree"
w1="WARNING: the repo tier qargi/memory has $n uncommitted path(s) in the lead's checkout; your clone has the committed version only."
printf '%s' "$mem" | grep -qF "$w1" && grep -qF "$w1" "$T/err" && ok "the uncommitted warning is in the packet and on stderr (N=$n)" || no "warning: $mem // $(cat "$T/err")"
[ "$rc" = 0 ] && ok "the warning does not block prepare" || no "rc $rc"
G -C "$R" checkout -q -- . && rm -f "$TIER/roles/build/new.md"

# the cap
rows=''; for i in $(seq 120); do rows+=$(row "long-note-name-number-$i.md"); done
w "$TIER/roles/build/INDEX.md" "# Build$rows"$'\n'
G -C "$R" add -A && G -C "$R" commit -q -m many
prep; mem=$(sed '1,/^TASK-BLOCK MEMORY$/d' "$T/out")
[ "${#mem}" -le 3000 ] && [ "${#mem}" -gt 1000 ] && ok "the packet is capped at 3000 characters (${#mem})" || no "cap: ${#mem}"
printf '%s\n' "$mem" | grep -qF 'Do not write any tier' && ok "the rule survives the cap" || no "rule lost under the cap"

# a project without tiers answers: nothing (an unregistered repository)
git init -q -b main "$T/other"; G -C "$T/other" commit -q --allow-empty -m one
"$SRC/bin/qargi" local prepare --repo "$T/other" --base main --slug none --scratch "$T/scratch" > "$T/out" 2> "$T/err"; rc=$?
[ "$rc" = 0 ] && grep -q '^TASK-BLOCK PATHS$' "$T/out" && ! grep -q 'TASK-BLOCK MEMORY' "$T/out" && ok "no project: no memory block, prepare unchanged" || no "no project: rc $rc $(cat "$T/out")"

# a registered project whose tiers are all missing: nothing is printed
mkdir -p "$T/notier"; git init -q -b main "$T/notier"; G -C "$T/notier" commit -q --allow-empty -m one
jq -n --arg r "$T/notier" '{project:"beta", repo:{path:$r}, memory:{}}' > "$T/c/projects/beta.json"
"$SRC/bin/qargi" local prepare --repo "$T/notier" --base main --slug notier --scratch "$T/scratch" > "$T/out" 2> "$T/err"; rc=$?
[ "$rc" = 0 ] && ! grep -q 'TASK-BLOCK MEMORY' "$T/out" && ok "every tier missing: the packet prints nothing" || no "all missing: rc $rc $(cat "$T/out")"

# a packet that fails or hangs never changes prepare's exit status
mkdir -p "$T/root"; tar --exclude=.git --exclude=tests -cf - . | tar -xf - -C "$T/root"
printf 'import sys\nsys.exit(1)\n' > "$T/root/lib/tiercontext.py"
"$T/root/bin/qargi" local prepare --repo "$R" --base main --slug failing --scratch "$T/scratch" > "$T/out" 2> "$T/err"; rc=$?
[ "$rc" = 0 ] && grep -q '^BASE_SHA=' "$T/out" && ! grep -q 'TASK-BLOCK MEMORY' "$T/out" && ok "a failing packet prints nothing and prepare still exits 0" || no "failing packet: rc $rc $(cat "$T/out" "$T/err")"
printf 'import time\ntime.sleep(60)\n' > "$T/root/lib/tiercontext.py"
s=$SECONDS
"$T/root/bin/qargi" local prepare --repo "$R" --base main --slug hanging --scratch "$T/scratch" > "$T/out" 2> "$T/err"; rc=$?
[ "$rc" = 0 ] && [ $((SECONDS - s)) -lt 25 ] && ! grep -q 'TASK-BLOCK MEMORY' "$T/out" && ok "a hanging packet is cut off (timeout 8) and prepare exits 0 ($((SECONDS - s)) s)" || no "hanging packet: rc $rc, $((SECONDS - s)) s"
exit $fail
