---
name: shellcheck-gate
description: Lint every shell file you add or change with shellcheck at warning level before you report, quote its verdict line among your gates, and fix findings rather than silence them.
---
# Shell lint gate

Run this before you report DONE. A shell finding that reaches the whole-suite run stops that run at lint and costs the lead a full cycle.

## What counts
- Every `*.sh` file and every file whose first line is a `sh` or `bash` shebang, test scripts included.
- Only files you added or changed: `git diff --name-only BASE_SHA..HEAD`, filtered to shell files. Untouched files are out of scope.

## Run
- From the repository root: `shellcheck -x -S warning FILES...`. A `.shellcheckrc` there applies on its own.
- If the project profile names a different lint command, the profile wins; report the difference.
- shellcheck prints nothing when it passes, so print your own verdict line:
  `shellcheck -x -S warning $FILES && echo "shellcheck: 0 findings in $(echo $FILES | wc -w) files"`
- Record it in the report's `gates[]`:
  `{"name": "shellcheck", "command": "shellcheck -x -S warning ...", "result": "pass", "exit_code": 0, "verdict_line": "shellcheck: 0 findings in 3 files"}`
- shellcheck not installed: set `result` to `not run`, give the reason, and never write `pass`.

## Fix, do not silence
- Fix the code. Add no new `# shellcheck disable=` unless the finding is a proven false positive.
- A disable is one line, names the code, and gives a reason, for example
  `# shellcheck disable=SC2034 # read by the sourcing script`.
  Mention each one in the report.
- For a file sourced by a computed path, tell shellcheck where it is: `# shellcheck source=lib/common.sh`.

## Existing findings
- A file you touched must end clean.
- A few old findings in it: fix them in their own commit, apart from your change.
- A large backlog: do not fix it here. Report it as a baseline problem and lint only the lines you wrote.
