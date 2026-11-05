---
name: docs-site-member
description: Writing to a documentation branch that shares no history with the main branches: base your work on that branch and never merge it.
---
# A site branch

A site branch holds a documentation site and shares no history with the main branches.

- Work in a clone of the site branch, not of `develop`.
- Base your `agent/<slug>` branch on the site branch named in your task.
- Never merge the site branch into a long-lived branch, or a long-lived branch into it.
- Read code facts with `git show` from the code branch; never rebase or cherry-pick across.
- Your patches apply onto the site branch only; say so in the report, with its sha.
- Never let a line start with `<`: keep a code span that holds a placeholder on one line, or put the placeholder after other text; hard-wrap prose so no wrapped line begins with `<`.
- Run the project's render check, not only the Markdown checks, before reporting: a green build proves nothing about layout.
