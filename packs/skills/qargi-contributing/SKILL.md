---
name: qargi-contributing
description: Habits for a member changing qargi itself: quoting, commit messages, sleep, stash, fail-first tests, shrink-only ceilings, targeted tests.
---
# Working on qargi

- Internal flags in Python scripts are single-quoted.
- The guard refuses shell text that contains a refused verb. Write each commit message with your runtime's file-writing tool and commit with `-F FILE`.
- A foreground `sleep` is blocked: use your runtime's background facility.
- Backtick text inside a double-quoted `echo` is executed.
- Never use bare `git stash`: use a WIP commit.
- Write every new test fail-first.
- `tests/skill-budget.txt` and `tests/neutral-allowlist.txt` only shrink; never raise them.
- Run only targeted tests. The lead runs the suite.
