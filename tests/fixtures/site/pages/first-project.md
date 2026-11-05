---
title: Your first project
description: Set up a project called acme with qargi, store its answers, add a member and dispatch a first task, checking each step before you rely on it.
doctype: tutorial
nav: First project
---
This page sets up a project named `acme`. Every name below is an example.

## Store the answers

Print an answers file, edit it, then store it.

```bash
qargi project template acme > acme.json
qargi project init acme --answers acme.json
```

The answers live outside the repository. Read `qargi help files` for where.

## Add a member

A member is a local agent you name. It works in its own clone and never pushes.

```bash
qargi agent add forge --roles build,test
qargi agent for build
```

| Ability | What it does |
|---|---|
| `build` | changes the code with its tests |
| `review` | reads a change and changes no file |

## Check what comes back

1. Run `qargi review check ./run`.
2. Read the patches one by one.
3. Apply them on a scratch branch, never on a long-lived one.
   - The lead decides what is merged.
   - Nothing is pushed by a member.

> A refusal is a result: report it, do not work around it.

Back to the [overview](/) or on to the [releases](/releases/). Options are listed per verb in the [reference](/reference/set-up/#project-init).
