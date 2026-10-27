# Source map

Where a reviewer finds the project's rules, so a finding can cite one.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

A finding that a change breaks a rule cites the rule's file and ref. Look for rules in the agent instructions, the contributing guide, linter and CI configuration, and the tests that pin behaviour.

### Project specifics

| Question | Where |
|---|---|
| What does the project forbid? | <agent instructions, contributing guide> |
| What do linters and CI enforce? | <configuration files> |
| Which behaviour is pinned by tests? | <test directories> |
