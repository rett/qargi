# Source map

Where each kind of fact lives in the repository, so the answer is read rather than guessed.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

Look in the project's own files first, in this order: agent instructions, README, contributing guide, build file, CI workflows, the code, then the tests. When two disagree, the code and the CI configuration describe what actually runs.

### Project specifics

| Question | Where |
|---|---|
| How is it built? | <build file or command> |
| How are tests run, and which are slow? | <test README, Makefile target> |
| Which linters and generators run? | <config files, CI workflow> |
| Where is the changelog and what format? | <file> |
| Where are user-facing docs? | <directory> |
| Which files are generated? | <paths and generator> |
| How is a release made? | <doc> |
