#!/usr/bin/env bash
# The one list of what a test copies to run a modified copy of the tool (TOOL_DIRS in tests/hermetic.sh, copy_tool, and TOOL_DIRS of
# tests/hermetic.py), so a new top-level directory is one edit. This test says: no other test spells the list out; every top-level
# directory of the repository is in the list or is named below as one a copy does not need; copy_tool copies what exists and skips
# what does not. Run: tests/test_tool_copy.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }

# top-level directories a copy of the tool does not need (the tests, the sample projects, generated completions and the manual page)
NOT_COPIED="tests examples completions man"

# 1. no test spells the list out
spelled=$(grep -lE "provision contract|\"provision\", \"contract\"" tests/*.sh tests/*.py 2>/dev/null | grep -v -e '^tests/hermetic\.' -e '^tests/test_tool_copy\.sh$' | tr '\n' ' ')
[ -z "$spelled" ] && ok "no test lists the tool's directories itself" || no "these tests spell out the directories to copy (use copy_tool from tests/hermetic.sh): $spelled"

# 2. every top-level directory is copied or named as not needed
missing=
for d in */; do
  d=${d%/}
  case " $TOOL_DIRS $NOT_COPIED " in *" $d "*) ;; *) missing="$missing $d";; esac
done
[ -z "$missing" ] && ok "every top-level directory is in TOOL_DIRS or is one a copy does not need" || no "top-level directories in neither TOOL_DIRS (tests/hermetic.sh) nor NOT_COPIED here:$missing"
for d in $TOOL_DIRS; do [ -e "$d" ] || no "TOOL_DIRS names $d, which the repository does not have"; done

# 3. copy_tool
mkdir -p "$T/src/lib" "$T/src/contract"; echo a > "$T/src/lib/a"; echo b > "$T/src/contract/b"; echo 1 > "$T/src/VERSION"; echo x > "$T/src/other"
copy_tool "$T/src" "$T/all"
[ -f "$T/all/lib/a" ] && [ -f "$T/all/contract/b" ] && [ -f "$T/all/VERSION" ] && [ ! -e "$T/all/other" ] && [ ! -e "$T/all/bin" ] && ok "copy_tool copies the entries of TOOL_DIRS that exist and nothing else" || no "copy_tool: $(find "$T/all" | sort | tr '\n' ' ')"
copy_tool "$T/src" "$T/some" lib VERSION
[ -f "$T/some/lib/a" ] && [ -f "$T/some/VERSION" ] && [ ! -e "$T/some/contract" ] && ok "copy_tool with names copies only those" || no "copy_tool names: $(find "$T/some" | sort | tr '\n' ' ')"

# 4. the Python tests read the same list
py=$(python3 -I -c 'import sys; sys.path.insert(0, "tests"); import hermetic; print(" ".join(hermetic.TOOL_DIRS))' 2>&1)
[ "$py" = "$TOOL_DIRS" ] && ok "tests/hermetic.py has the list of tests/hermetic.sh" || no "hermetic.py: $py"
exit $fail
