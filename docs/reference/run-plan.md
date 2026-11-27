# Run plan check

`qargi flow plan check FILE [--json]` reads a run plan and says whether it is valid and in which order its nodes can run. A **run plan** is one JSON file: one feature and the task nodes that merge into it, each with the role that does it, the paths it may change, the command that says it is done, and the nodes it comes after.

The check is **static and read-only**: no state, no token, no network, nothing written. It plans nothing and starts nothing: it does not prepare a run, dispatch a member, merge a branch or approve anything, and a valid plan grants no authority to do any of it. Running a plan (a `flow run`, stored flow state, automatic rework, hooks, a scheduler) is not part of qargi; the checker is the one piece that exists, so that a lead can write down a feature's tasks and see their order and their conflicts before dispatching the first.

The validation and the ordering are those of the [backlog graph](backlog-graph.md) reader (`lib/backlog_graph.py`: its JSON reader that refuses constants and duplicate keys, its deterministic order and its cycle detection, no recursion), and the rule for a `done` command is the one `qargi local prepare` applies to a DONE (`lib/done_words.py`). The code is `lib/run_plan.py`. Like the graph reader it is lead only under the member guard: a member's guard refuses `qargi flow ...`, and the member reports the plan findings in its task output instead.

## The format

The document is of the kind `qargi-run-plan` (schema 1; `qargi help json qargi-run-plan` shows its fields, `lib/kinds/qargi-run-plan.json` is the registry file). The kind is a **draft**: see [JSON output](json-output.md#draft-kinds). The checker refuses a key that is not listed.

| Key | Meaning |
| --- | --- |
| `kind` | `"qargi-run-plan"` |
| `schema` | the integer `1` |
| `project` | the name of the project: lower case letters and digits, starting with a letter, at most 24 |
| `target_feature` | the open feature the nodes merge into: a lower case slug of at most 40 characters, not `master` or `develop` |
| `nodes` | a non-empty list of task nodes (at most 500) |

A node:

| Key | Meaning |
| --- | --- |
| `id` | a lower case slug (letters, digits, single hyphens, at most 40), unique in the plan |
| `task` | non-empty text: what the node does |
| `role` | a role qargi knows: one of those `qargi role list` prints |
| `scope` | a non-empty list (at most 100) of the paths or globs, relative to the repository root, the node may change. A directory stands for everything beneath it. No `..`, no absolute path, no space, comma or control character, no empty or `.` segment (a leading `./` and a trailing `/` are taken off) |
| `done` | one command line whose exit status says the task is done. It must parse in bash, and its command words must be real, as for `qargi local prepare --done`: an executable on `PATH`, a shell builtin or keyword, or, for a word with a slash in the first command, a file below the current directory, a file under a path of the node's `scope` (the task may create it) or an absolute file. Prose ("all the tests pass") is refused. Arguments are never read |
| `after` | optional, default empty: the ids of the nodes that must be done before this one |
| `review_kind` | `none`, `review` or `advisor`: what looks at the result before it merges |
| `profile` | optional: a lower case word (letters, digits, hyphens) |
| `runtime` | optional: a lower case word (letters, digits, hyphens) |

`profile` and `runtime` are only checked for their form; the checker does not look them up.

## What it checks

Each finding has a stable `code`, a `severity` (`error` or `note`), a message, the ids of the nodes it is about and a `path` in the plan. Findings are sorted: errors first, then by code, nodes and path. The plan is valid when no finding is an error.

| Code | Severity | When |
| --- | --- | --- |
| `invalid-json`, `duplicate-json-key` | error | the file is not JSON (a constant such as `NaN` counts), or an object writes a key twice |
| `too-large`, `too-many-nodes` | error | the file is over 1 MiB, or there are over 500 nodes |
| `not-an-object` | error | the plan, or a node, is not a JSON object |
| `wrong-kind`, `wrong-schema` | error | `kind` is not `qargi-run-plan`, or `schema` is not the integer 1 |
| `unknown-key`, `missing-key` | error | a key the plan or a node does not have, or a required key that is absent |
| `bad-value` | error | `project`, `target_feature`, `task`, `role`, `profile` or `runtime` is not of its form, or `nodes` is not a list |
| `empty-nodes` | error | `nodes` is empty |
| `bad-id`, `duplicate-id` | error | a node id is not a slug, or two nodes have the same one |
| `unknown-role` | error | the role is not one `qargi role list` prints |
| `bad-scope` | error | `scope` is not a non-empty list, or an entry is empty, absolute, holds `..`, a space or a comma |
| `bad-done` | error | `done` is empty, several lines, not parseable, has no command word, or a command word is not real (see above) |
| `bad-review-kind` | error | `review_kind` is not `none`, `review` or `advisor` |
| `bad-after`, `unknown-after`, `self-after` | error | `after` is not a list of ids or names one twice; it names an id that is no node; it names the node itself |
| `cycle` | error | the nodes come after each other in a circle; one cycle is named (`cycle` lists it: each node comes after the next, the last after the first) |
| `scope-overlap-unordered` | error | two nodes that `after` does not order, directly or through other nodes, have scopes that can touch the same path; `patterns` names the first pair of entries that can |
| `review-requested` | note | a node has `review_kind` `review` or `advisor`: only noted, a review is a task of its own |

### Overlap

Two nodes are **ordered** when one comes after the other through `after`, also through other nodes. Two unordered nodes conflict when some path can match an entry of each scope. The decision is conservative: where it cannot be made it is an overlap.

- A directory entry stands for everything beneath it, so `lib` overlaps `lib/a.py`; `**` as a whole segment matches any number of segments.
- A literal and a glob are decided with the glob rules of the shell (`*`, `?`, `[...]`). Two globs in one segment are told apart only by what they fix at the start and at the end: `lib/*.py` and `lib/*.sh` cannot meet, `lib/a*.py` and `lib/*b.py` can. A segment with a brace or a backslash is not in that dialect and is taken to overlap.
- The overlap is looked for only when the order itself is sound (every id valid and unique, every `after` naming a node, no cycle).

A few files are written by almost every task: `CHANGELOG.md`, `man/qargi.1`, `docs/reference/refusals.md`, `tests/suite.txt` and `tests/durations.txt`. A node that lists one of them in its `scope` overlaps every other unordered node that lists it (the message says so). A node that does not list them is **not assumed** to write them: declare them in the `scope` of a task that changes them, and order those tasks with `after`.

## Output and exit status

The text form prints the nodes in a valid run order, in waves, then the findings. A wave is the nodes whose `after` are all in earlier waves; the nodes of one wave have no order between them. The waves are printed when the order is sound, also when other findings make the plan invalid.

```
run plan check: valid
  project acme, target feature export-report, 4 nodes
  waves (a wave starts when the ones before it are done):
    wave 1: reader, writer
    wave 2: command
    wave 3: docs
  note review-requested [writer]: the node writer has review_kind review: the checker only notes it, a review is a task of its own
```

`--json` prints one document of the kind `qargi-run-plan-check` (schema 1, a draft): `valid`, `digest` (of the bytes read), `project`, `target_feature`, `nodes` (the count), `waves` and `findings`. The document is checked against its registry file before it is printed.

| Exit | Meaning |
| --- | --- |
| 0 | the plan is valid (notes are allowed) |
| 1 | the plan is not: at least one finding is an error. With `--json` the document is printed all the same, and `valid` is false |
| 2 | a wrong call, or a file that cannot be read (one line on standard error, no document) |
| 70 | the document of `--json` failed the check of its own registry file: a defect of qargi, no document is printed |

The same bytes, the same roles and the same files a `done` names give the same output, byte for byte.

## An example

```json
{
  "kind": "qargi-run-plan",
  "schema": 1,
  "project": "acme",
  "target_feature": "export-report",
  "nodes": [
    {
      "id": "reader",
      "task": "Read the report file into the report model and refuse a malformed one.",
      "role": "build",
      "scope": ["src/report/reader.py", "tests/test_reader.py"],
      "done": "python3 tests/test_reader.py",
      "review_kind": "none"
    },
    {
      "id": "writer",
      "task": "Write the report model as a CSV file.",
      "role": "build",
      "scope": ["src/report/writer.py", "tests/test_writer.py"],
      "done": "python3 tests/test_writer.py",
      "review_kind": "review",
      "profile": "careful"
    },
    {
      "id": "command",
      "task": "Add the export verb that joins the reader and the writer.",
      "role": "build",
      "scope": ["src/cli.py", "tests/test_cli.py", "CHANGELOG.md"],
      "done": "python3 tests/test_cli.py",
      "after": ["reader", "writer"],
      "review_kind": "none"
    },
    {
      "id": "docs",
      "task": "Describe the export verb in the user guide.",
      "role": "write",
      "scope": ["docs/", "CHANGELOG.md"],
      "done": "python3 tests/test_docs_links.py",
      "after": ["command"],
      "review_kind": "none"
    }
  ]
}
```

`reader` and `writer` touch different files, so they share wave 1. `command` and `docs` both list `CHANGELOG.md`; `docs` comes after `command`, so that is fine. Without `"after": ["command"]` on `docs` the plan is invalid:

```
run plan check: invalid
  project acme, target feature export-report, 4 nodes
  waves (a wave starts when the ones before it are done):
    wave 1: docs, reader, writer
    wave 2: command
  error scope-overlap-unordered [command, docs]: the nodes command and docs are not ordered by after and their scopes can touch the same path: CHANGELOG.md and CHANGELOG.md (a file most tasks change: declare it in the scope of the task that changes it, and order those tasks)
  note review-requested [writer]: the node writer has review_kind review: the checker only notes it, a review is a task of its own
```

## What it does not do

- It does not run, prepare, dispatch, verify or merge anything, and keeps no state: there is no flow to resume, no token and no audit line.
- It does not look at the repository's history, the open feature's branch, the marshal or the network. It reads the plan, the roles, `PATH` and the files a `done` names, and the repository is the current directory.
- It does not decide that a plan is a good one: that the scopes are right, that a `done` tests the task, or that a review is done. A `review_kind` is a note.
- It does not assume which tasks write the shared files; the plan says so in `scope`.
- It does not rework a failed node, order nodes by what they write beyond `scope`, or cap how many run at once.
