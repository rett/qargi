---
name: dev-provision
description: Create the cloud resources for a dev-agent instance with ant apply (environment, agent, recipes memory store, development-reference store, manual-run deployment) named <project>-<role>-<component>; plan first, create only with the user's go-ahead.
argument-hint: plan|apply|add-reference NAME ...
---

# /dev-provision

Resources are named `<NAME>-agent`, `-environment`, `-memory`, `-reference`,
`-deployment`, where `NAME` is `<project>-<role>` (`--project P --role R`, role
defaults to `dev`). Files and `claude-lock.json` stay in the state directory,
outside any repository. Resources created in the Console or with
`ant beta:... create` cannot be adopted by `ant apply`: this creates new ones.

| Verb | Command | Notes |
|---|---|---|
| plan | `dev-agent provision plan NAME [--model M] [--effort E] [--apt "pkg ..."] [--networking unrestricted\|limited] [--budget CENTS]` | Renders the files and prints the `ant apply --dry-run` plan. Changes nothing. Show it to the user. |
| apply | `dev-agent provision apply NAME [same options] --asked "..." --approved "<the user's go-ahead for that plan>"` | Creates the resources, seeds the recipes and reference stores, attaches the reference store read-only, registers the instance. `--approved` is the user's approval, not yours. |
| add-reference | `dev-agent provision add-reference NAME --asked "..." --approved "..."` | Adds `<NAME>-reference` (read-only) to an existing instance. |

Defaults: Sonnet 5.5, effort high, budget 500 (cents, set on the deployment).
Models and effort for an instance can be chosen at `init` (`/dev-instances`).
