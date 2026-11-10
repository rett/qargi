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
# shellcheck source=fixtures.sh
. tests/fixtures.sh

# top-level directories a copy of the tool does not need (the tests, the sample projects, generated completions, the manual page and the docs)
NOT_COPIED="tests examples completions man docs"

# 1. no test spells the list out: neither as the word pair the list begins with, nor as a copy line (cp, rsync, copytree, copy2) of three or more of
# the tool's top-level directories, which is a hand-written list that leaves the others out (hermetic.* and this test are the lists themselves)
spelled=$(grep -lE "provision contract|\"provision\", \"contract\"" tests/*.sh tests/*.py 2>/dev/null | grep -v -e '^tests/hermetic\.' -e '^tests/test_tool_copy\.sh$' | tr '\n' ' ')
by_hand=$(python3 -I - tests/*.sh tests/*.py <<'PY'
import re, sys
DIRS = "provision skills roles agents contract packs catalog lib bin".split()
for path in sys.argv[1:]:
    if re.match(r"tests/(hermetic\.|test_tool_copy\.sh$)", path):
        continue
    for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        if line.lstrip().startswith("#") or not re.search(r"(^|[^A-Za-z_])(cp|rsync|copytree|copy2?)\b", line):
            continue
        named = {d for d in DIRS if re.search(r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])" % d, line)}
        if len(named) >= 3:
            print("%s:%d " % (path, n), end="")
PY
)
[ -z "$spelled" ] && [ -z "$by_hand" ] && ok "no test lists the tool's directories itself" || no "these tests spell out the directories to copy (use copy_tool from tests/hermetic.sh): $spelled$by_hand"

# 2. every top-level directory is copied or named as not needed
missing=
for d in */; do
  d=${d%/}
  case " $TOOL_DIRS $NOT_COPIED " in *" $d "*) ;; *) missing="$missing $d";; esac
done
[ -z "$missing" ] && ok "every top-level directory is in TOOL_DIRS or is one a copy does not need" || no "top-level directories in neither TOOL_DIRS (tests/hermetic.sh) nor NOT_COPIED here:$missing"
for d in $TOOL_DIRS; do [ -e "$d" ] || no "TOOL_DIRS names $d, which the repository does not have"; done

# 3. install.sh --copy copies every directory a modified copy needs (TOOL_DIRS), whatever else it copies, and nothing the repository lacks
inst=$(sed -n 's/^tool_dirs="\(.*\)"$/\1/p' install.sh)
[ -n "$inst" ] || no "install.sh has no tool_dirs= line"
lack=; for d in $TOOL_DIRS; do case " $inst " in *" $d "*) ;; *) lack="$lack $d";; esac; done
[ -n "$inst" ] && [ -z "$lack" ] && ok "install.sh --copy copies every entry of TOOL_DIRS" || no "install.sh tool_dirs lacks:$lack"
extra=; for d in $inst; do [ -e "$d" ] || extra="$extra $d(missing)"; case " $TOOL_DIRS $NOT_COPIED " in *" $d "*) ;; *) extra="$extra $d(unknown)";; esac; done
[ -z "$extra" ] && ok "and every entry of its list exists and is in TOOL_DIRS or NOT_COPIED" || no "install.sh tool_dirs has:$extra"
grep -nE 'cp -r "\$here/(bin|lib|provision)' install.sh >/dev/null && no "install.sh spells the directories out again" || ok "install.sh copies from the one list, not a second spelled one"

# 4. copy_tool
mkdir -p "$T/src/lib" "$T/src/contract"; echo a > "$T/src/lib/a"; echo b > "$T/src/contract/b"; echo 1 > "$T/src/VERSION"; echo x > "$T/src/other"
copy_tool "$T/src" "$T/all"
[ -f "$T/all/lib/a" ] && [ -f "$T/all/contract/b" ] && [ -f "$T/all/VERSION" ] && [ ! -e "$T/all/other" ] && [ ! -e "$T/all/bin" ] && ok "copy_tool copies the entries of TOOL_DIRS that exist and nothing else" || no "copy_tool: $(find "$T/all" | sort | tr '\n' ' ')"
copy_tool "$T/src" "$T/some" lib VERSION
[ -f "$T/some/lib/a" ] && [ -f "$T/some/VERSION" ] && [ ! -e "$T/some/contract" ] && ok "copy_tool with names copies only those" || no "copy_tool names: $(find "$T/some" | sort | tr '\n' ' ')"

# 5. the Python tests read the same list
py=$(python3 -I -c 'import sys; sys.path.insert(0, "tests"); import hermetic; print(" ".join(hermetic.TOOL_DIRS))' 2>&1)
[ "$py" = "$TOOL_DIRS" ] && ok "tests/hermetic.py has the list of tests/hermetic.sh" || no "hermetic.py: $py"
exit $fail
