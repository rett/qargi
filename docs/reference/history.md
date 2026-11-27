# History of suite runs and review reports

`qargi history` lists the **history** of a project: one line for each whole-suite run of `qargi feature verify` and `qargi release verify`, and one for each report that `qargi review check` read from a report-only run. The history is **evidence, not a gate**. No verb decides anything from it: what a verify means is still the record of the branch (`verified()` and the per-branch record in the state's `releases/` directory, which `feature status` and `release status` read), and a missing, damaged or removed history changes no verdict and refuses nothing. What the history adds is something a record of the last run cannot be: a run you can cite by an id, with the commit and the tree it ran on, the command it ran, the gates, the failing tests and the log, and an earlier run that a later run did not overwrite.

## Where it is

| What | Where | Mode |
| --- | --- | --- |
| the history of a project | `$QARGI_STATE/history/PROJECT.jsonl` | file 600, directory 700 |
| the log of a suite run | `$QARGI_STATE/suite-logs/runs/ID.log` | file 600, directory 700 |
| the last run of a name (as before) | `$QARGI_STATE/suite-logs/PROJECT.feature-NAME.log`, `PROJECT.release-VERSION.log` | 600 |

The state directory is `~/.qargi/state` unless `QARGI_STATE` says otherwise. The file is a list of lines, each one JSON object of the draft kind `qargi-history-entry` (`qargi help json qargi-history-entry` shows its fields; [JSON output](json-output.md#draft-kinds) says what a draft is).

## How it is written

- **Append only.** An entry is written once, by one write on a descriptor opened with `O_APPEND`, under an `flock` on the file itself, and is fsynced. Nothing in the file is ever rewritten, renamed or removed by qargi: the bytes before an append are the bytes after it. A line that a crash left without its newline keeps its bytes, and the next entry starts on a line of its own.
- **Tolerant to read.** A line that cannot be read (a torn last line is the one to expect) is skipped, with one warning on standard error and the number of lines skipped (`skipped` in the document); it is never an error.
- **Never a failure of a verb.** If an entry cannot be written (a full disk, a file that is a link), the verb says so on standard error and goes on with the verdict it has.
- **Attempt.** The `attempt` of a suite entry is 1 plus the number of earlier suite entries of the project with the same head, tree, command and `verify.environment` id. It is worked out under the same lock as the append, so two runs at once get two numbers.
- **Logs.** Each run's log is kept as `suite-logs/runs/ID.log`, besides the last-run file. A project keeps the newest 20 of them; the oldest are removed as a new entry is appended, except the log of the latest pass of each branch. An entry whose log was removed keeps its `log` path, and `qargi history show` says the file is gone.
- **Lead side only.** The writers are the lead's verbs, and a member's guard refuses `qargi history`, the script behind it and a write into the state's `history/` and `suite-logs/` directories.

## What is recorded

A **suite entry** (`entry_kind` `suite`) is added when a `feature verify` or a `release verify` ends, pass or fail, and also when the verb is stopped by a signal after the suite started (`result` `interrupted`; the per-branch record is not written then, as before).

| Field | Meaning |
| --- | --- |
| `id` | 16 random hex digits |
| `project`, `verb`, `name`, `branch` | the project; `feature verify` or `release verify`; the feature name or the version; the branch whose head ran |
| `head`, `tree` | the commit and its tree |
| `command`, `environment_id` | the command identity `verified()` compares: the test command (or the identity of the declared gates) and the id of `verify.environment` (null when off) |
| `gates` | each declared gate in order: `name`, `result` (`pass`, `fail`, `not run`, `covered by NAME`), `seconds` |
| `result` | `pass`, `fail` or `interrupted` |
| `started`, `ended`, `seconds` | UTC times, and the whole seconds the run took |
| `failing_tests`, `failing_total` | the failing-test lines the failure report prints (`FAIL ...`, `FAIL: ...`, `--- FAIL: ...`), each once, at most 200 (each cut at 300 characters), and how many there were |
| `load_start`, `load_end` | the first field of `/proc/loadavg` at the start and at the end, as text (`"0.52"`: a document holds integers only), null when it cannot be read |
| `attempt` | see above |
| `log` | the path of the kept log |

A **review entry** (`entry_kind` `review`) is added by `qargi review check` of a report-only run that the lead's registry names, when the report is read to its verdict (a report that fails the check, a member's own structural check and a series of patches add nothing). It holds the run (`run`, `slug`), the `verdict` word (`accept` or `revise`, each time the report is checked), the `report_sha256` of the bytes of the report and never its text, the `base` branch and `base_sha`, the reviewer's `role` and `class`, and the `runtime` and `model` as the registry records them (the model is the one asked for at prepare, never one a runtime reported). `vendor` is the family name that the descriptor of the runtime gives (`family`), or null when there is no descriptor or it names none. `tests_run` is what the reviewer's manifest records under that key (a list or a count), or null.

## The verb

```
qargi history [--project P] [--kind suite|review] [--head SHA] [--limit N] [--json]
qargi history show ID [--project P] [--json]
```

The list is newest first, at most `--limit` entries (default 20, at most 1000). `--head` is a prefix of 4 to 64 hex digits and matches the head of a suite entry and the base of a review entry. The text has one row for each entry:

```
TIME                  KIND    NAME   HEAD      TREE      RESULT  SECONDS  ATTEMPT  ID
2026-11-27T09:14:02Z  suite   dots   9f3c1a07  4be2d6c0  pass    412      2        0c5d83a1f6e24b97
2026-11-27T08:51:40Z  review  fix-x  77a0be12  -         accept  -        -        d1e3a40b7c9825f6
```

With `--json` the verb prints one document of the draft kind `qargi-history` (`project`, `matched`, `skipped` and `entries`, each of the kind `qargi-history-entry`), checked against its registry file before it is printed. It exits 0 after a complete document, also when nothing matches; 70 when the document fails its registry file (nothing is printed), 1 when the history cannot be read or `show` names no entry (or more than one) and 2 for a wrong call. `show ID` takes the whole id or a prefix of 4 digits or more, prints every field of the entry (a command or a test name with a control character is shown escaped), and with `--json` prints the entry as it was stored.

Lead only under the current member guard, as `qargi backlog graph` is.

## What it does not do

- It is not a gate and not a cache: a verify never reads it, and it does not say whether a branch may merge or be released.
- It does not store the text of a report, a log's content in the file, or anything a secret scanner would look for: a log is a file of its own, as the last-run log always was.
- It is not pruned: only the logs are capped. The file grows by one line for each run; remove it by hand if it is not wanted (the next run starts a new one).
