---
name: qargi-contributing
description: Habits for a member changing qargi itself: quoting, sleep, fail-first tests, shrink-only ceilings, targeted tests.
---
# Working on qargi

- Internal flags in Python scripts are single-quoted.
- A foreground `sleep` is blocked: use your runtime's background facility.
- Backtick text inside a double-quoted `echo` is executed.
- Write every new test fail-first.
- `tests/skill-budget.txt` and `tests/neutral-allowlist.txt` only shrink; never raise them.
- Run only targeted tests. The lead runs the suite.
