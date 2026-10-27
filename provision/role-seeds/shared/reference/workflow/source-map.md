# Source map

Kind: workflow
Applies to: any
Sources: dev-agent seed

## Contents

Look in the project's own files first, in this order: agent instructions, README, contributing guide, build file, CI workflows, the code, then the tests. When two disagree, the code and the CI configuration describe what actually runs. A finding that a change breaks a rule cites the rule's file and ref.

### Project specifics

| Question | Where |
|---|---|
| How is it built? | <build file or command> |
| How are tests run, in which modes, and which are slow? | <test README, Makefile, CI workflow> |
| Which linters and generators run, and which files are generated? | <config files, paths> |
| Where are the changelog and the user-facing docs? | <files> |
| Which helpers sandbox paths, time and commands? | <helper package> |
| Where are fixtures and goldens, and how are they regenerated? | <directory, generator> |
| How is a release made? | <doc> |
